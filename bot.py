import asyncio
import io
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACKS = [
    m.strip() for m in os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash",
    ).split(",") if m.strip()
]
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-5-mini")
TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "tts-1-hd")
MEMORY_DB = os.getenv("MEMORY_DB", "sam_memory.db")
MODEL_TIMEOUT = int(os.getenv("MODEL_TIMEOUT_SECONDS", "20"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

openai_client = None
if OpenAI and OPENAI_API_KEY:
    try:
        openai_client = OpenAI(api_key=OPENAI_API_KEY, timeout=MODEL_TIMEOUT, max_retries=0)
    except Exception as exc:
        logger.warning("OpenAI disabled: %s", exc)

CHAT_HISTORY: Dict[int, List[dict]] = {}
MAX_HISTORY_MESSAGES = 12


def init_memory() -> None:
    with sqlite3.connect(MEMORY_DB) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        db.commit()


def load_history(user_id: int) -> List[dict]:
    with sqlite3.connect(MEMORY_DB) as db:
        rows = db.execute(
            "SELECT role, content FROM messages WHERE user_id=? "
            "ORDER BY rowid DESC LIMIT ?",
            (user_id, MAX_HISTORY_MESSAGES),
        ).fetchall()
    rows.reverse()
    return [
        {"role": role, "parts": [{"text": content}]}
        for role, content in rows
    ]


def save_message(user_id: int, role: str, content: str) -> None:
    with sqlite3.connect(MEMORY_DB) as db:
        db.execute(
            "INSERT INTO messages(user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (user_id, role, content, datetime.utcnow().isoformat()),
        )
        db.execute(
            """DELETE FROM messages
               WHERE user_id=? AND rowid NOT IN (
                   SELECT rowid FROM messages WHERE user_id=?
                   ORDER BY rowid DESC LIMIT ?
               )""",
            (user_id, user_id, MAX_HISTORY_MESSAGES),
        )
        db.commit()


def clear_history(user_id: int) -> None:
    with sqlite3.connect(MEMORY_DB) as db:
        db.execute("DELETE FROM messages WHERE user_id=?", (user_id,))
        db.commit()


def gemini_request(model: str, contents: list) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1200},
    }
    response = requests.post(
        url,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=MODEL_TIMEOUT,
    )
    if response.status_code != 200:
        try:
            detail = response.json()
        except Exception:
            detail = response.text[:500]
        raise RuntimeError(f"Gemini HTTP {response.status_code}: {detail}")

    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if p.get("text"))
    if not text:
        raise RuntimeError(f"Gemini returned empty text: {data}")
    return text.strip()


def ask_gemini(user_id: int, user_text: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    history = load_history(user_id)
    contents = history + [{"role": "user", "parts": [{"text": user_text}]}]
    models = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACKS if m != GEMINI_MODEL]
    last_error = None

    for model in models:
        try:
            answer = gemini_request(model, contents)
            save_message(user_id, "user", user_text)
            save_message(user_id, "model", answer)
            logger.info("Gemini response from %s for user %s", model, user_id)
            return answer
        except Exception as exc:
            last_error = exc
            logger.warning("Gemini model %s failed: %s", model, exc)

    raise RuntimeError(str(last_error))


def ask_openai(user_text: str) -> str:
    if not openai_client:
        raise RuntimeError("OpenAI is not configured")
    response = openai_client.chat.completions.create(
        model=OPENAI_CHAT_MODEL,
        messages=[{"role": "user", "content": user_text}],
        max_tokens=500,
    )
    return response.choices[0].message.content or ""


async def reply_with_timeout(message, text: str, timeout: int = 10) -> None:
    await asyncio.wait_for(message.reply_text(text), timeout=timeout)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "سلام 👋\n\n"
        "پیام معمولی بفرست تا با Gemini پاسخ بدهم.\n"
        "/reset - پاک کردن حافظه همین گفت‌وگو\n"
        "/memory - وضعیت حافظه این کاربر\n"
        "/generate <prompt> - تولید تصویر با OpenAI\n"
        "/speak <text> - تبدیل متن به صدا\n"
        "/search <query> - جستجو\n"
        "/earthquake - گزارش زلزله ۲۴ ساعت اخیر\n"
        "ویس هم می‌توانی بفرستی."
    )


async def reset_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await asyncio.to_thread(clear_history, user_id)
    await update.message.reply_text("حافظه این گفت‌وگو پاک شد. 🧹")


async def memory_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    history = await asyncio.to_thread(load_history, user_id)
    await update.message.reply_text(
        f"حافظه محلی SAM برای این کاربر فعال است.\n"
        f"تعداد پیام‌های ذخیره‌شده: {len(history)}"
    )


async def chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    user_text = update.message.text.strip()
    if not user_text:
        return

    try:
        await update.message.chat.send_action("typing")
    except Exception:
        pass

    # IMPORTANT: network/model calls run in a worker thread so Telegram's
    # asyncio event loop remains responsive to other updates.
    try:
        answer = await asyncio.wait_for(
            asyncio.to_thread(ask_gemini, user_id, user_text),
            timeout=MODEL_TIMEOUT + 5,
        )
        await reply_with_timeout(update.message, answer)
        return
    except asyncio.TimeoutError:
        logger.error("Gemini timed out for user %s", user_id)
        gemini_error = "timeout"
    except Exception as exc:
        logger.error("Gemini chat failed for user %s: %s", user_id, exc)
        gemini_error = str(exc)

    try:
        answer = await asyncio.wait_for(
            asyncio.to_thread(ask_openai, user_text),
            timeout=MODEL_TIMEOUT + 5,
        )
        await reply_with_timeout(update.message, answer)
        return
    except asyncio.TimeoutError:
        logger.error("OpenAI timed out for user %s", user_id)
    except Exception as exc:
        logger.error("OpenAI fallback failed for user %s: %s", user_id, exc)

    await reply_with_timeout(
        update.message,
        "نتونستم این پیام رو به سرویس هوش مصنوعی وصل کنم. "
        "جزئیات خطا در لاگ ربات ثبت شد؛ ربات روشن است و پیام بعدی را هم دریافت می‌کند.",
    )


def perform_search(query: str) -> str:
    try:
        response = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "pretty": 1},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("AbstractText"):
            return data["AbstractText"]
        topics = data.get("RelatedTopics") or []
        if topics and topics[0].get("Text"):
            return topics[0]["Text"]
        return "متأسفانه نتیجه‌ای پیدا نشد."
    except Exception as exc:
        logger.error("Search failed: %s", exc)
        return "در حال حاضر امکان جستجو وجود ندارد."


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("مثال: /search قیمت بیت‌کوین")
        return
    await update.message.reply_text("در حال جستجو... 🔎")
    result = await asyncio.to_thread(perform_search, query)
    await update.message.reply_text(result)


def get_earthquake_report() -> str:
    start_time = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    end_time = datetime.utcnow().isoformat()
    url = (
        "https://earthquake.usgs.gov/fdsnws/event/1/query"
        "?format=geojson"
        f"&starttime={start_time}&endtime={end_time}"
        "&minmagnitude=2.5&maxlatitude=45&minlatitude=20"
        "&maxlongitude=70&minlongitude=35&orderby=time"
    )
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        features = response.json().get("features", [])
        if not features:
            return "در ۲۴ ساعت گذشته زلزله ۲.۵+ در محدوده انتخابی ثبت نشده است."
        lines = ["گزارش زلزله‌های ۲۴ ساعت گذشته:", ""]
        for feature in features[:5]:
            props = feature["properties"]
            when = datetime.utcfromtimestamp(props["time"] / 1000).strftime("%Y-%m-%d %H:%M:%S UTC")
            lines.append(f"🔹 {props.get('mag')} ریشتر | {props.get('place')} | {when}")
        lines.append("\nمنبع: USGS")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("Earthquake API error: %s", exc)
        return "در حال حاضر امکان دریافت گزارش زلزله وجود ندارد."


async def earthquake_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("در حال دریافت گزارش زلزله... 🌍")
    result = await asyncio.to_thread(get_earthquake_report)
    await update.message.reply_text(result)


async def generate_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not openai_client:
        await update.message.reply_text("OpenAI در این محیط فعال نیست.")
        return
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.message.reply_text("مثال: /generate a robot artist")
        return
    await update.message.reply_text("در حال تولید تصویر... 🎨")
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: openai_client.images.generate(
                    model="dall-e-2", prompt=prompt, n=1, size="512x512"
                )
            ),
            timeout=MODEL_TIMEOUT + 10,
        )
        await update.message.reply_photo(photo=response.data[0].url, caption="تصویر آماده شد.")
    except asyncio.TimeoutError:
        await update.message.reply_text("تولید تصویر بیشتر از حد مجاز طول کشید و متوقف شد.")
    except Exception as exc:
        logger.error("Image generation failed: %s", exc)
        await update.message.reply_text("تولید تصویر انجام نشد؛ OpenAI احتمالاً اعتبار یا دسترسی لازم را ندارد.")


async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not openai_client:
        await update.message.reply_text("OpenAI در این محیط فعال نیست.")
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("مثال: /speak سلام دنیا")
        return
    await update.message.reply_text("در حال ساخت صدا... 🔊")
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: openai_client.audio.speech.create(
                    model=TTS_MODEL, voice="onyx", input=text
                )
            ),
            timeout=MODEL_TIMEOUT + 10,
        )
        audio_file = io.BytesIO(response.read())
        audio_file.name = "speech.mp3"
        await update.message.reply_audio(audio=audio_file, title="صدای تولید شده")
    except asyncio.TimeoutError:
        await update.message.reply_text("ساخت صدا بیشتر از حد مجاز طول کشید و متوقف شد.")
    except Exception as exc:
        logger.error("Speech generation failed: %s", exc)
        await update.message.reply_text("ساخت صدا انجام نشد؛ OpenAI احتمالاً اعتبار ندارد.")


async def voice_to_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not openai_client:
        await update.message.reply_text("تبدیل ویس فعلاً به OpenAI وابسته است.")
        return

    await update.message.reply_text("در حال گوش دادن و تبدیل صدا به متن... 🎙️")
    try:
        voice_file = await asyncio.wait_for(
            update.message.voice.get_file(), timeout=15
        )
        voice_bytes = io.BytesIO()
        await asyncio.wait_for(
            voice_file.download_to_memory(voice_bytes), timeout=20
        )
        voice_bytes.name = "voice.ogg"

        transcript = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: openai_client.audio.transcriptions.create(
                    model="whisper-1", file=voice_bytes
                )
            ),
            timeout=MODEL_TIMEOUT + 10,
        )
        text = (transcript.text or "").strip()
        if not text:
            await update.message.reply_text("صدا دریافت شد، ولی گفتاری قابل تشخیص پیدا نشد.")
            return
        await update.message.reply_text(f"📝 {text}")

        # Continue naturally into chat after transcription.
        try:
            answer = await asyncio.wait_for(
                asyncio.to_thread(ask_gemini, update.effective_user.id, text),
                timeout=MODEL_TIMEOUT + 5,
            )
            await update.message.reply_text(answer)
        except Exception as exc:
            logger.error("Voice follow-up chat failed: %s", exc)
            await update.message.reply_text(
                "متن ویس با موفقیت استخراج شد، اما پاسخ هوش مصنوعی در دسترس نیست."
            )
    except asyncio.TimeoutError:
        await update.message.reply_text("پردازش صدا بیش از حد طول کشید و متوقف شد.")
    except Exception as exc:
        logger.error("Voice transcription failed: %s", exc)
        await update.message.reply_text(
            "پردازش ویس ناموفق بود. خطای فنی در لاگ ثبت شد و ربات آماده پیام بعدی است."
        )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("این دستور را نمی‌شناسم. /start را بزن.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled Telegram error", exc_info=context.error)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is missing from .env")

    init_memory()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset_chat))
    application.add_handler(CommandHandler("memory", memory_status))
    application.add_handler(CommandHandler("generate", generate_image))
    application.add_handler(CommandHandler("speak", text_to_speech))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("earthquake", earthquake_command))
    application.add_handler(MessageHandler(filters.VOICE & ~filters.COMMAND, voice_to_text))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_message))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    application.add_error_handler(error_handler)

    logger.info("SAM bot starting: concurrent updates enabled, model timeout=%ss", MODEL_TIMEOUT)
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
