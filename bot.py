import os
import logging
import subprocess
import tempfile
from pyrogram import Client, filters
from pyrogram.types import Message

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# دریافت مقادیر از Variableهای محیطی
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
INTRO_VIDEO_PATH = "/app/intro.mp4"

app = Client("intro_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    await message.reply_text("سلام! 👋\nویدیو رو بفرست تا اینترو رو بدون افت کیفیت بهش بچسبونم.")

@app.on_message(filters.video & filters.private)
async def handle_video(client: Client, message: Message):
    status_msg = await message.reply_text("⏳ در حال دریافت و پردازش ویدیو...")
    
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_video = os.path.join(temp_dir, "input.mp4")
            output_video = os.path.join(temp_dir, "output.mp4")
            concat_file = os.path.join(temp_dir, "concat.txt")
            
            # ۱. دانلود فایل ویدیو (پشتیبانی تا ۲ گیگابایت)
            logger.info("Downloading video...")
            await message.download(file_name=input_video)
            
            # ۲. ساخت فایل لیست برای FFmpeg
            with open(concat_file, 'w') as f:
                f.write(f"file '{INTRO_VIDEO_PATH}'\nfile '{input_video}'\n")
            
            # ۳. اتصال سریع بدون انکود مجدد (Stream Copy - بدون افت کیفیت)
            logger.info("Concatenating video using stream copy...")
            cmd_concat = [
                'ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_file,
                '-c', 'copy', '-y', output_video
            ]
            
            process = subprocess.run(cmd_concat, capture_output=True, text=True)
            
            if process.returncode != 0 or not os.path.exists(output_video):
                logger.error(f"FFmpeg error: {process.stderr}")
                await status_msg.edit_text("❌ خطا در اتصال ویدیو. مطمئن شوید فرمت و رزولوشن ویدیو با اینترو یکسان است.")
                return

            # ۴. آپلود ویدیو نهایی
            await status_msg.edit_text("📤 در حال آپلود و ارسال...")
            await message.reply_video(
                video=output_video,
                caption="✅ اینترو با موفقیت اضافه شد (بدون تغییر کیفیت)."
            )
            await status_msg.delete()

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await status_msg.edit_text(f"❌ خطایی رخ داد: {str(e)[:50]}")

if __name__ == '__main__':
    app.run()
            
