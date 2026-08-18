import os
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import subprocess
import tempfile

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

INTRO_VIDEO_PATH = "/app/intro.mp4"
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ درحال پردازش... (فایل‌های بزرگ ۵-۱۰ دقیقه طول می‌کشد)")
    
    try:
        video_file = await update.message.video.get_file()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            input_video = os.path.join(temp_dir, "input.mp4")
            intro_norm = os.path.join(temp_dir, "intro_norm.mp4")
            input_norm = os.path.join(temp_dir, "input_norm.mp4")
            output_video = os.path.join(temp_dir, "output.mp4")
            
            logger.info("Downloading...")
            await video_file.download_to_drive(input_video)
            
            # مرحله 1: نرمال کردن intro (CRF 0 = بدون کیفیت بخش)
            logger.info("Normalizing intro (lossless)...")
            cmd_intro = [
                'ffmpeg', '-i', INTRO_VIDEO_PATH,
                '-c:v', 'libx264', '-crf', '0', '-preset', 'ultrafast',
                '-c:a', 'aac', '-y', intro_norm
            ]
            subprocess.run(cmd_intro, capture_output=True, timeout=900)
            
            # مرحله 2: نرمال کردن input (CRF 0 = بدون کیفیت بخش)
            logger.info("Normalizing input (lossless)...")
            cmd_input = [
                'ffmpeg', '-i', input_video,
                '-c:v', 'libx264', '-crf', '0', '-preset', 'ultrafast',
                '-c:a', 'aac', '-y', input_norm
            ]
            subprocess.run(cmd_input, capture_output=True, timeout=900)
            
            # مرحله 3: concat (copy = بدون re-encoding دوباره)
            logger.info("Concatenating...")
            concat_file = os.path.join(temp_dir, "concat.txt")
            with open(concat_file, 'w') as f:
                f.write(f"file '{intro_norm}'\nfile '{input_norm}'\n")
            
            cmd_concat = [
                'ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_file,
                '-c', 'copy', '-y', output_video
            ]
            result = subprocess.run(cmd_concat, capture_output=True, timeout=600)
            
            if not os.path.exists(output_video):
                logger.error("Output failed")
                await update.message.reply_text("❌ خرابی")
                return
            
            file_size = os.path.getsize(output_video) / (1024*1024*1024)
            logger.info(f"Output: {file_size:.2f}GB")
            
            logger.info("Sending...")
            with open(output_video, 'rb') as video:
                await update.message.reply_video(video=video, write_timeout=300)
    
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await update.message.reply_text(f"❌ {str(e)[:50]}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! 👋\nویدیو بفرست و من اینترو رو بهش می‌چسبونم")

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN!")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.COMMAND, start))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    logger.info("Bot started!")
    app.run_polling()

if __name__ == '__main__':
    main()
