import os
INTRO_VIDEO_PATH = "/app/intro.mp4"  # مسیر درست برای Railway
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import subprocess
import tempfile

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

INTRO_VIDEO_PATH = "intro.mp4"
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ در حال پردازش ویدیو... لطفاً صبر کنید")
    
    try:
        video_file = await update.message.video.get_file()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            input_video = os.path.join(temp_dir, "input.mp4")
            await video_file.download_to_drive(input_video)
            
            output_video = os.path.join(temp_dir, "output.mp4")
            
            concat_file = os.path.join(temp_dir, "concat.txt")
            with open(concat_file, 'w') as f:
                f.write(f"file '{INTRO_VIDEO_PATH}'\n")
                f.write(f"file '{input_video}'\n")
            
            cmd = [
                'ffmpeg',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file,
                '-c', 'copy',
                '-y',
                output_video
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                await update.message.reply_text("خرابی در پردازش ویدیو.")
                return
            
            with open(output_video, 'rb') as video:
                await update.message.reply_video(
                    video=video,
                    caption="✅ ویدیو آماده است!",
                    write_timeout=30
                )
            
            logger.info(f"Video processed for user {update.message.from_user.id}")
    
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await update.message.reply_text(f"خرابی: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! 👋\n\n"
        "ویدیو رو بفرست و من اینترو رو بهش می‌چسبونم."
    )

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set!")
    
    if not os.path.exists(INTRO_VIDEO_PATH):
        raise FileNotFoundError(f"intro.mp4 not found!")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(MessageHandler(filters.COMMAND, start))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    
    logger.info("Bot started!")
    app.run_polling()

if __name__ == '__main__':
    main()
