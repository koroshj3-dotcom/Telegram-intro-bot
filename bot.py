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
    await update.message.reply_text("⏳ در حال پردازش ویدیو (ممکن است ۱-۲ دقیقه طول بکشد)...")
    
    try:
        video_file = await update.message.video.get_file()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            input_video = os.path.join(temp_dir, "input.mp4")
            intro_normalized = os.path.join(temp_dir, "intro_norm.mp4")
            input_normalized = os.path.join(temp_dir, "input_norm.mp4")
            output_video = os.path.join(temp_dir, "output.mp4")
            
            # دانلود ویدیو
            logger.info("Downloading video...")
            await video_file.download_to_drive(input_video)
            
            # نرمال‌کردن intro
            logger.info("Normalizing intro...")
            cmd_intro = [
                'ffmpeg', '-i', INTRO_VIDEO_PATH,
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
                '-c:a', 'aac', '-y', intro_normalized
            ]
            subprocess.run(cmd_intro, capture_output=True, timeout=60)
            
            # نرمال‌کردن input
            logger.info("Normalizing input video...")
            cmd_input = [
                'ffmpeg', '-i', input_video,
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
                '-c:a', 'aac', '-y', input_normalized
            ]
            subprocess.run(cmd_input, capture_output=True, timeout=120)
            
            # concat
            logger.info("Concatenating videos...")
            concat_file = os.path.join(temp_dir, "concat.txt")
            with open(concat_file, 'w') as f:
                f.write(f"file '{intro_normalized}'\nfile '{input_normalized}'\n")
            
            cmd_concat = [
                'ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_file,
                '-c', 'copy', '-y', output_video
            ]
            result = subprocess.run(cmd_concat, capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                await update.message.reply_text(f"❌ خرابی: {result.stderr[:200]}")
                return
            
            logger.info("Sending video...")
            with open(output_video, 'rb') as video:
                await update.message.reply_video(
                    video=video,
                    caption="✅ تمام!",
                    write_timeout=60
                )
    
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await update.message.reply_text(f"❌ {str(e)[:100]}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! 👋\nویدیو بفرست")

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
