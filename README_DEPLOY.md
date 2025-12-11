# دستورالعمل راه‌اندازی ربات تلگرام پیشرفته (Polling)

این فایل شامل دستورالعمل‌های گام به گام برای راه‌اندازی ربات تلگرام شما با قابلیت‌های تولید تصویر، تولید صدای انسان‌نما، تبدیل ویس به متن، جستجوی وب و گزارش زلزله است.

**توکن تلگرام شما:** `7706907691:AAGhZZBsfDWLi8HROXAGROA7nILUBOpp5yY`
**کلید OpenAI شما:** `sk-proj-8XFK3YjCvSlzBKnGmgPXtRmM8qpthuTZ9NrLEMK5eb1reZvYB4lD-I0LqyVVwwj8Mc29i0wffHT3BlbkJrrDrv7JCiEP-gRxnuSYXv1xEJKvkvoJ00Uogk8STOodvgvbbNs23i-TP8q_ItxJJO_qQKxU4uwA`

## ۱. پیش‌نیازها

1.  **یک سرور دائمی:** (VPS، PythonAnywhere پولی، یا کامپیوتر همیشه روشن).
2.  **نصب پایتون:** Python 3.8 به بالا.
3.  **Git:** برای کلون کردن کد.

## ۲. راه‌اندازی اولیه

در ترمینال سرور خود، دستورات زیر را اجرا کنید:

1.  **کلون کردن مخزن:**
    ```bash
    git clone https://github.com/Ariyan3323/telegram-advanced-bot.git
    cd telegram-advanced-bot
    ```

2.  **ایجاد و فعال‌سازی محیط مجازی:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **نصب کتابخانه‌ها:**
    ```bash
    pip install python-telegram-bot openai requests
    ```

## ۳. اجرای ربات

ربات شما به گونه‌ای تنظیم شده است که **کلید OpenAI شما مستقیماً در فایل `bot.py` قرار داده شده است** و نیازی به تنظیم متغیر محیطی نیست.

**دستور نهایی برای اجرای ربات:**

```bash
# مطمئن شوید که محیط مجازی فعال است: source venv/bin/activate
python bot.py
```

### اجرای دائمی (توصیه شده)

برای اینکه ربات شما پس از بستن ترمینال همچنان فعال بماند، از ابزارهایی مانند `screen` یا `tmux` استفاده کنید:

1.  **نصب screen (اگر نصب نیست):**
    ```bash
    sudo apt install screen
    ```

2.  **شروع یک نشست جدید screen:**
    ```bash
    screen -S telegram_bot
    ```

3.  **اجرای ربات در نشست screen:**
    ```bash
    source venv/bin/activate
    python bot.py
    ```

4.  **خروج از نشست screen (بدون توقف ربات):**
    *   کلیدهای **Ctrl + A** را فشار دهید، سپس کلید **D** را بزنید.

ربات شما اکنون در پس‌زمینه سرور فعال است. برای بازگشت به نشست، دستور `screen -r telegram_bot` را وارد کنید.
