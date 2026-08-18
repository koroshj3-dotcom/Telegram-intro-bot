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
    await update.message.reply_text("⏳ در حال پردازش...")
    
    try:
        video_file = await update.message.video.get_file()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            input_video = os.path.join(temp_dir, "input.mp4")
            output_video = os.path.join(temp_dir, "output.mp4")
            
            logger.info("Downloading...")
            await video_file.download_to_drive(input_video)
            
            # استفاده از filter_complex بدون re-encoding
            cmd = [
                'ffmpeg',
                '-i', INTRO_VIDEO_PATH,
                '-i', input_video,
                '-filter_complex', '[0:v:0][0:a:0][1:v:0][1:a:0]concat=n=2:v=1:a=1[outv][outa]',
                '-map', '[outv]',
                '-map', '[outa]',
                '-c', 'copy',
                '-y', output_video
            ]
            
            logger.info("Processing...")
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            
            if not os.path.exists(output_video):
                logger.error("Output file not created")
                await update.message.reply_text("❌ خرابی")
                return
            
            file_size = os.path.getsize(output_video) / (1024*1024)
            logger.info(f"Output: {file_size:.2f}MB")
            
            logger.info("Sending...")
            with open(output_video, 'rb') as video:
                await update.message.reply_video(
                    video=video, 
                    write_timeout=120
                )
    
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await update.message.reply_text(f"❌ {str(e)[:50]}")

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
