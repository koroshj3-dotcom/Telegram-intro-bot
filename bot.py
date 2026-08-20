import os
import json
import logging
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrogram import Client, filters
from pyrogram.types import Message

logging.basicConfig(level=logging.INFO)

# وب‌سرور کوچک برای رضایت Render و بیدار ماندن ربات
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active!")

    def log_message(self, format, *args):
        return  # خاموش کردن لاگ‌های اضافی وب‌سرور

def start_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# اجرای وب‌سرور در یک Thread جداگانه
threading.Thread(target=start_health_check_server, daemon=True).start()

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
INTRO_FILE = "intro.mp4"

app = Client("intro_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def get_video_info(file_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=width,height",
        "-of", "json", file_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(res.stdout)
    duration = int(float(data.get("format", {}).get("duration", 0)))
    streams = data.get("streams", [{}])
    width = streams[0].get("width", 1280) if streams else 1280
    height = streams[0].get("height", 720) if streams else 720
    return duration, width, height

def generate_thumbnail(video_path, thumb_path):
    cmd = [
        "ffmpeg", "-y", "-ss", "00:00:01",
        "-i", video_path, "-vframes", "1", thumb_path
    ]
    subprocess.run(cmd, capture_output=True)

def process_concat(intro_path, input_path, output_path):
    cmd = [
        "ffmpeg", "-y",
        "-i", intro_path,
        "-i", input_path,
        "-filter_complex",
        "[0:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v0];"
        "[1:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v1];"
        "[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];"
        "[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];"
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path
    ]
    subprocess.run(cmd, check=True)

@app.on_message(filters.command("start"))
async def start_cmd(_, message: Message):
    await message.reply_text("سلام! ویدیو خود را ارسال کنید تا اینترو به انتهای آن اضافه شود.")

@app.on_message(filters.video | filters.document)
async def process_video(client: Client, message: Message):
    if message.document and not message.document.mime_type.startswith("video/"):
        return

    if not os.path.exists(INTRO_FILE):
        await message.reply_text("❌ فایل intro.mp4 روی سرور پیدا نشد.")
        return

    status_msg = await message.reply_text("📥 در حال دانلود ویدیو...")
    
    input_path = await message.download()
    output_path = f"output_{message.id}.mp4"
    thumb_path = f"thumb_{message.id}.jpg"

    try:
        await status_msg.edit_text("⚙️ در حال چسباندن اینترو و تنظیم کیفیت...")
        process_concat(INTRO_FILE, input_path, output_path)

        duration, width, height = get_video_info(output_path)
        generate_thumbnail(output_path, thumb_path)

        await status_msg.edit_text("📤 در حال ارسال ویدیو...")
        await client.send_video(
            chat_id=message.chat.id,
            video=output_path,
            caption="✅ اینترو با موفقیت اضافه شد.",
            duration=duration,
            width=width,
            height=height,
            thumb=thumb_path if os.path.exists(thumb_path) else None,
            supports_streaming=True
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
