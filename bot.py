import os
import json
import time
import asyncio
import logging
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrogram import Client, filters
from pyrogram.types import Message

logging.basicConfig(level=logging.INFO)

# --- وب‌سرور برای بیدار ماندن و سلامت Render ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active!")

    def log_message(self, format, *args):
        return

def start_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_health_check_server, daemon=True).start()

# --- تنظیمات ربات ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
INTRO_FILE = "intro.mp4"

app = Client("intro_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ساخت نوار پیشرفت متنی
def make_progress_bar(current, total):
    percentage = current * 100 / total if total > 0 else 0
    completed = int(percentage / 10)
    bar = "█" * completed + "░" * (10 - completed)
    return f"[{bar}] {percentage:.1f}%"

# کالبک درصد پیشرفت برای دانلود و آپلود تلگرام
async def telegram_progress(current, total, status_msg, action_text, last_edit):
    now = time.time()
    if now - last_edit[0] > 3 or current == total:
        last_edit[0] = now
        bar = make_progress_bar(current, total)
        try:
            await status_msg.edit_text(f"{action_text}\n\n{bar}")
        except Exception:
            pass

def get_video_info(file_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=width,height",
        "-of", "json", file_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(res.stdout)
    duration = float(data.get("format", {}).get("duration", 0))
    streams = data.get("streams", [{}])
    width = streams[0].get("width", 1280) if streams else 1280
    height = streams[0].get("height", 720) if streams else 720
    return duration, int(width), int(height)

def generate_thumbnail(video_path, thumb_path):
    cmd = [
        "ffmpeg", "-y", "-ss", "00:00:01",
        "-i", video_path, "-vframes", "1", thumb_path
    ]
    subprocess.run(cmd, capture_output=True)

# پردازش FFmpeg با قابلیت محاسبه درصد پیشرفت لحظه‌ای
async def process_concat_with_progress(intro_path, input_path, output_path, total_duration, status_msg):
    cmd = [
        "ffmpeg", "-y",
        "-progress", "pipe:1",
        "-i", intro_path,
        "-i", input_path,
        "-filter_complex",
        "[0:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v0];"
        "[1:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v1];"
        "[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];"
        "[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];"
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26", "-threads", "0",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )

    last_edit = 0
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        line_str = line.decode('utf-8', errors='ignore').strip()
        
        if line_str.startswith("out_time_us="):
            try:
                microseconds = int(line_str.split("=")[1])
                current_seconds = microseconds / 1_000_000
                now = time.time()
                
                if now - last_edit > 3 and total_duration > 0:
                    last_edit = now
                    bar = make_progress_bar(current_seconds, total_duration)
                    await status_msg.edit_text(f"⚙️ در حال اضافه کردن اینترو...\n\n{bar}")
            except Exception:
                pass

    await process.wait()

@app.on_message(filters.command("start"))
async def start_cmd(_, message: Message):
    await message.reply_text("سلام! ویدیو خود را ارسال کنید تا اینترو به آن اضافه شود.")

@app.on_message(filters.video | filters.document)
async def process_video(client: Client, message: Message):
    if message.document and not message.document.mime_type.startswith("video/"):
        return

    if not os.path.exists(INTRO_FILE):
        await message.reply_text("❌ فایل intro.mp4 روی سرور پیدا نشد.")
        return

    status_msg = await message.reply_text("📥 در حال شروع دانلود...")
    
    input_path = f"input_{message.id}.mp4"
    output_path = f"output_{message.id}.mp4"
    thumb_path = f"thumb_{message.id}.jpg"

    try:
        # ۱. دانلود با درصد پیشرفت
        last_edit = [0]
        input_path = await message.download(
            file_name=input_path,
            progress=telegram_progress,
            progress_args=(status_msg, "📥 در حال دانلود ویدیو...", last_edit)
        )

        # محاسبه زمان کل ویدیو (اینترو + ویدیوی اصلی)
        intro_dur, _, _ = get_video_info(INTRO_FILE)
        main_dur, width, height = get_video_info(input_path)
        total_duration = intro_dur + main_dur

        # ۲. پردازش FFmpeg با درصد پیشرفت
        await status_msg.edit_text("⚙️ در حال شروع پردازش ویدیو...")
        await process_concat_with_progress(INTRO_FILE, input_path, output_path, total_duration, status_msg)

        generate_thumbnail(output_path, thumb_path)

        # ۳. آپلود با درصد پیشرفت
        last_edit = [0]
        await status_msg.edit_text("📤 در حال شروع آپلود...")
        await client.send_video(
            chat_id=message.chat.id,
            video=output_path,
            caption="✅ اینترو با موفقیت اضافه شد.",
            duration=int(total_duration),
            width=width,
            height=height,
            thumb=thumb_path if os.path.exists(thumb_path) else None,
            supports_streaming=True,
            progress=telegram_progress,
            progress_args=(status_msg, "📤 در حال آپلود ویدیو...", last_edit)
        )
        await status_msg.delete()

    except Exception as e:
        logging.error(f"Error processing video: {e}")
        await status_msg.edit_text("❌ خطایی در پردازش ویدیو رخ داد.")

    finally:
        for path in [input_path, output_path, thumb_path]:
            if os.path.exists(path):
                os.remove(path)

if __name__ == "__main__":
    app.run()
