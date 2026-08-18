FROM python:3.11-slim

# نصب FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# مسیر کاری
WORKDIR /app

# کپی فایل‌ها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# اجرای ربات
CMD ["python", "bot.py"]
