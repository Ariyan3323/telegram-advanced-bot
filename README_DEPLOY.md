# دستورالعمل راه‌اندازی پایدار ربات تلگرام پیشرفته

این فایل شامل کد نهایی ربات تلگرام شما و دستورالعمل‌های لازم برای راه‌اندازی آن به صورت پایدار بر روی یک سرور دائمی است.

## ۱. پیش‌نیازها

برای اجرای پایدار ربات، به موارد زیر نیاز دارید:

1.  **یک سرور مجازی (VPS) یا کامپیوتر شخصی همیشه روشن:** برای اجرای دائمی کد.
2.  **نصب Python 3.10+**
3.  **توکن ربات تلگرام** (از BotFather)
4.  **کلید API اوپن‌ای‌آی (OpenAI API Key)**: برای قابلیت‌های تولید تصویر، صدا و تبدیل ویس به متن.

## ۲. راه‌اندازی محیط

در سرور خود، مراحل زیر را دنبال کنید:

### الف. نصب پیش‌نیازهای پایتون

```bash
# نصب محیط مجازی
python3 -m venv telegram_bot_venv

# فعال‌سازی محیط مجازی
source telegram_bot_venv/bin/activate

# نصب کتابخانه‌های مورد نیاز
pip install python-telegram-bot openai requests
```

### ب. ذخیره کد ربات

فایل `bot.py` را با محتوای زیر در سرور خود ذخیره کنید.

**توجه:** در خط ۱۲ کد، **توکن ربات** شما به صورت زیر تنظیم شده است:
`BOT_TOKEN = "7706907691:AAGhZZBsfDWLi8HROXAGROA7nILUBOpp5yY"`

اگر توکن ربات شما تغییر کرده است، حتماً آن را در این خط به‌روزرسانی کنید.

### ج. تنظیم کلید API اوپن‌ای‌آی

برای اینکه ربات بتواند از سرویس‌های OpenAI استفاده کند، باید کلید API خود را به عنوان یک متغیر محیطی تنظیم کنید.

```bash
export OPENAI_API_KEY="YOUR_OPENAI_API_KEY_HERE"
```
**توجه:** به جای `YOUR_OPENAI_API_KEY_HERE`، کلید واقعی خود را قرار دهید.

## ۳. اجرای ربات

برای اجرای ربات به صورت پایدار و در پس‌زمینه (حتی پس از بستن ترمینال)، از ابزارهایی مانند `screen` یا `tmux` یا `nohup` استفاده کنید. ساده‌ترین روش استفاده از `nohup` است:

```bash
# اجرای ربات در پس‌زمینه
nohup python bot.py &

# برای مشاهده لاگ‌ها (اختیاری)
tail -f nohup.out
```

## ۴. کد نهایی ربات (`bot.py`)

```python
import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
import requests
import io
from datetime import datetime, timedelta

# --- Configuration ---
# توکن ربات خود را اینجا قرار دهید
BOT_TOKEN = "7706907691:AAGhZZBsfDWLi8HROXAGROA7nILUBOpp5yY"
# این متغیرها برای Polling غیرضروری هستند، اما در کد باقی می‌مانند
WEBHOOK_URL = "https://8080-ijt1llq8z753utodvdpi1-324cad81.manusvm.computer"
PORT = 8080

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- OpenAI Client ---
try:
    # استفاده از مدل با کیفیت بالا برای صدای انسان‌نما
    TTS_MODEL = "tts-1-hd"
    # کلید API به صورت خودکار از متغیر محیطی OPENAI_API_KEY خوانده می‌شود
    client = OpenAI()
    openai_available = True
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}")
    client = None
    openai_available = False

# --- Search Function (using a public API) ---
def perform_search(query: str):
    url = f"https://api.duckduckgo.com/?q={query}&format=json&pretty=1"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data.get("AbstractText"):
            return data["AbstractText"]
        elif data.get("RelatedTopics") and data["RelatedTopics"][0].get("Text"):
            return data["RelatedTopics"][0]["Text"]
        else:
            return "متاسفانه نتیجه‌ای یافت نشد."
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return "در حال حاضر امکان جستجو وجود ندارد."

# --- Earthquake Function ---
def get_earthquake_report():
    # USGS API for all earthquakes M2.5+ in the last 24 hours (focused on Iran region)
    start_time = (datetime.now() - timedelta(hours=24)).isoformat()
    end_time = datetime.now().isoformat()
    
    # محدوده جغرافیایی تقریبی ایران و اطراف آن
    url = (
        f"https://earthquake.usgs.gov/fdsnws/event/1/query?"
        f"format=geojson&starttime={start_time}&endtime={end_time}&minmagnitude=2.5"
        f"&maxlatitude=45&minlatitude=20&maxlongitude=70&minlongitude=35"
        f"&orderby=time"
    )
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        features = data.get("features", [])
        if not features:
            return "در ۲۴ ساعت گذشته، زلزله‌ای با بزرگی ۲.۵ ریشتر یا بیشتر در منطقه ایران و اطراف آن ثبت نشده است."
        
        report = "گزارش زلزله‌های ۲۴ ساعت گذشته (بزرگی ۲.۵ ریشتر یا بیشتر):\n\n"
        for feature in features[:5]: # محدود به ۵ مورد آخر
            props = feature["properties"]
            mag = props["mag"]
            place = props["place"]
            time_ms = props["time"]
            
            # تبدیل زمان میلی‌ثانیه به زمان قابل خواندن (UTC)
            time_utc = datetime.fromtimestamp(time_ms / 1000).strftime('%Y-%m-%d %H:%M:%S UTC')
            
            report += f"🔹 **بزرگی:** {mag} ریشتر\n"
            report += f"📍 **مکان:** {place}\n"
            report += f"⏱ **زمان:** {time_utc}\n"
            report += "----------------------------------\n"
            
        report += "\nمنبع: USGS"
        return report
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Earthquake API error: {e}")
        return "متأسفانه در حال حاضر امکان دریافت گزارش زلزله وجود ندارد."

# --- Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message and instructions."""
    instructions = (
        "سلام! من ربات پیشرفته شما هستم.\n\n"
        "دستورات موجود:\n"
        "/generate <prompt> - تولید تصویر\n"
        "/speak <text> - تبدیل متن به صدای انسان‌نما\n"
        "/search <query> - جستجوی اطلاعات\n"
        "/earthquake - دریافت آخرین گزارش زلزله (۲۴ ساعت گذشته)\n\n"
        "همچنین می‌توانید برای من **پیام صوتی (ویس)** بفرستید تا آن را به متن تبدیل کنم."
    )
    await update.message.reply_text(instructions)

async def generate_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates an image based on user prompt."""
    if not openai_available:
        await update.message.reply_text("سرویس تولید تصویر در دسترس نیست.")
        return

    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("لطفا توضیحات تصویر را وارد کنید. مثال: /generate a robot artist")
        return

    await update.message.reply_text(f"در حال تولید تصویر برای: {prompt}...")
    try:
        response = client.images.generate(model="dall-e-2", prompt=prompt, n=1, size="512x512")
        image_url = response.data[0].url
        await update.message.reply_photo(photo=image_url, caption=f"تصویر شما برای: {prompt}")
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        await update.message.reply_text(f"خطا در تولید تصویر: {e}")

async def text_to_speech(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Converts text to speech using a high-quality model."""
    if not openai_available:
        await update.message.reply_text("سرویس تولید صدا در دسترس نیست.")
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("لطفا متن مورد نظر را وارد کنید. مثال: /speak سلام دنیا")
        return

    await update.message.reply_text(f"در حال تبدیل متن به صدای انسان‌نما: {text}...")
    try:
        response = client.audio.speech.create(model=TTS_MODEL, voice="onyx", input=text)
        
        audio_file = io.BytesIO()
        for chunk in response.iter_bytes(chunk_size=4096):
            audio_file.write(chunk)
        audio_file.seek(0)

        await update.message.reply_audio(audio=audio_file, title="صدای تولید شده انسان‌نما")
    except Exception as e:
        logger.error(f"Speech generation error: {e}")
        await update.message.reply_text(f"خطا در تولید صدا: {e}")

async def voice_to_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Converts user's voice message to text."""
    if not openai_available:
        await update.message.reply_text("سرویس تبدیل ویس به متن در دسترس نیست.")
        return

    await update.message.reply_text("در حال تبدیل پیام صوتی شما به متن...")
    try:
        voice_file = await update.message.voice.get_file()
        voice_bytes = io.BytesIO()
        await voice_file.download_to_memory(voice_bytes)
        voice_bytes.name = "voice.ogg"

        transcript = client.audio.transcriptions.create(
            model="whisper-1", 
            file=voice_bytes
        )
        
        await update.message.reply_text(f"**متن پیام صوتی شما:**\n\n{transcript.text}")

    except Exception as e:
        logger.error(f"Voice to text error: {e}")
        await update.message.reply_text(f"خطا در تبدیل ویس به متن: {e}")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Performs a web search."""
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("لطفا عبارت مورد نظر برای جستجو را وارد کنید. مثال: /search قیمت بیت‌کوین")
        return

    await update.message.reply_text(f"در حال جستجو برای: {query}...")
    result = perform_search(query)
    await update.message.reply_text(result)

async def earthquake_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Provides the latest earthquake report."""
    await update.message.reply_text("در حال دریافت آخرین گزارش زلزله...")
    report = get_earthquake_report()
    await update.message.reply_text(report, parse_mode='Markdown')

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="متاسفانه این دستور را متوجه نمی‌شوم. برای راهنمایی /start را بزنید.")

# --- Main Function ---
def main() -> None:
    """Starts the bot with Polling."""
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("generate", generate_image))
    application.add_handler(CommandHandler("speak", text_to_speech))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("earthquake", earthquake_command))
    application.add_handler(MessageHandler(filters.VOICE & ~filters.COMMAND, voice_to_text))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Start Polling
    logger.info("Bot is running with polling.")
    application.run_polling()

if __name__ == "__main__":
    main()
```
