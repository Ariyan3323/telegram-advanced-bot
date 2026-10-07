import io
import logging
import os
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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

openai_client = None
if OpenAI and OPENAI_API_KEY:
    try:
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception as exc:
        logger.warning("OpenAI disabled: %s", exc)

CHAT_HISTORY: Dict[int, List[dict]] = {}
MAX_HISTORY_MESSAGES = 12


def gemini_request(model: str, contents: list) -> str:
    """Direct Gemini REST call; avoids google-genai/httpx dependency conflicts."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1200},
    }
    response = requests.post(
        url, params={"key": GEMINI_API_KEY}, json=payload, timeout=45
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


def ask_gemini(chat_id: int, user_text: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    history = CHAT_HISTORY.setdefault(chat_id, [])
    contents = history + [{"role": "user", "parts": [{"text": user_text}]}]
    models = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACKS if m != GEMINI_MODEL]
    last_error = None

    for model in models:
        try:
            answer = gemini_request(model, contents)
            history.extend([
                {"role": "user", "parts": [{"text": user_text}]},
                {"role": "model", "parts": [{"text": answer}]},
            ])
            del history[:-MAX_HISTORY_MESSAGES]
            logger.info("Gemini response from %s", model)
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "سلام 👋\n\n"
        "پیام معمولی بفرست تا با Gemini پاسخ بدهم.\n"
        "/reset - پاک کردن حافظه گفتگو\n"
        "/generate <prompt> - تولید تصویر با OpenAI\n"
        "/speak <text> - تبدیل متن به صدا\n"
        "/search <query> - جستجو\n"
        "/earthquake - گزارش زلزله ۲۴ ساعت اخیر\n"
        "ویس هم می‌توانی بفرستی."
    )


async def reset_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    CHAT_HISTORY.pop(update.effective_chat.id, None)
    await update.message.reply_text("حافظه این گفت‌وگو پاک شد. 🧹")


async def chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    user_text = update.message.text.strip()
    if not user_text:
        return

    await update.message.chat.send_action("typing")
    try:
        await update.message.reply_text(
            ask_gemini(update.effective_chat.id, user_text)
        )
        return
    except Exception as exc:
        logger.error("Gemini chat failed: %s", exc)

    try:
        await update.message.reply_text(ask_openai(user_text))
    except Exception as exc:
        logger.error("OpenAI fallback failed: %s", exc)
        await update.message.reply_text(
            "فعلاً سرویس هوش مصنوعی پاسخگو نیست؛ احتمالاً سهمیه Gemini "
            "یا اعتبار OpenAI تمام شده. ربات همچنان روشن است."
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
    await update.message.reply_text(perform_search(query))


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
            when = datetime.utcfromtimestamp(props["time"] / 1000).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
            lines.append(f"🔹 {props.get('mag')} ریشتر | {props.get('place')} | {when}")
        lines.append("\nمنبع: USGS")
        return "\n".join(lines)
    except Exception as exc:
        logger.error("Earthquake API error: %s", exc)
        return "در حال حاضر امکان دریافت گزارش زلزله وجود ندارد."


async def earthquake_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("در حال دریافت گزارش زلزله... 🌍")
    await update.message.reply_text(get_earthquake_report())


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
        response = openai_client.images.generate(
            model="dall-e-2", prompt=prompt, n=1, size="512x512"
        )
        await update.message.reply_photo(photo=response.data[0].url, caption="تصویر آماده شد.")
    except Exception as exc:
        logger.error("Image generation failed: %s", exc)
        await update.message.reply_text(
            "تولید تصویر انجام نشد؛ احتمالاً OpenAI اعتبار یا دسترسی مدل لازم را ندارد."
        )


async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not openai_client:
        await update.message.reply_text("OpenAI در این محیط فعال نیست.")
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("مثال: /speak سلام دنیا")
        return
    try:
        response = openai_client.audio.speech.create(model=TTS_MODEL, voice="onyx", input=text)
        audio_file = io.BytesIO(response.read())
        audio_file.name = "speech.mp3"
        await update.message.reply_audio(audio=audio_file, title="صدای تولید شده")
    except Exception as exc:
        logger.error("Speech generation failed: %s", exc)
        await update.message.reply_text("تولید صدا انجام نشد؛ احتمالاً OpenAI اعتبار ندارد.")


async def voice_to_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not openai_client:
        await update.message.reply_text("تبدیل ویس فعلاً به OpenAI وابسته است.")
        return
    await update.message.reply_text("در حال تبدیل ویس به متن... 🎙️")
    try:
        voice_file = await update.message.voice.get_file()
        voice_bytes = io.BytesIO()
        await voice_file.download_to_memory(voice_bytes)
        voice_bytes.name = "voice.ogg"
        transcript = openai_client.audio.transcriptions.create(model="whisper-1", file=voice_bytes)
        await update.message.reply_text(transcript.text)
    except Exception as exc:
        logger.error("Voice transcription failed: %s", exc)
        await update.message.reply_text("تبدیل ویس انجام نشد؛ احتمالاً OpenAI اعتبار ندارد.")


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("این دستور را نمی‌شناسم. /start را بزن.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled Telegram error", exc_info=context.error)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is missing from .env")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset_chat))
    application.add_handler(CommandHandler("generate", generate_image))
    application.add_handler(CommandHandler("speak", text_to_speech))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("earthquake", earthquake_command))
    application.add_handler(MessageHandler(filters.VOICE & ~filters.COMMAND, voice_to_text))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_message))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    application.add_error_handler(error_handler)

    logger.info("Bot starting with polling...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
