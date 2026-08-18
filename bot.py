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
    await update.message.reply_text("⏳ در حال پردازش ویدیو...")
    
    try:
        video_file = await update.message.video.get_file()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            input_video = os.path.join(temp_dir, "input.mp4")
            output_video = os.path.join(temp_dir, "output.mp4")
            
            # دانلود ویدیو
            logger.info(f"Downloading video...")
            await video_file.download_to_drive(input_video)
            logger.info(f"Video downloaded to {input_video}")
            
            # استفاده از ffmpeg concat filter
            cmd = [
                'ffmpeg',
                '-i', INTRO_VIDEO_PATH,
                '-i', input_video,
                '-filter_complex', '[0:v:0][0:a:0][1:v:0][1:a:0]concat=n=2:v=1:a=1[outv][outa]',
                '-map', '[outv]',
                '-map', '[outa]',
                '-y',
                output_video
            ]
            
            logger.info(f"Running FFmpeg command...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                await update.message.reply_text(f"❌ FFmpeg Error: {result.stderr[:100]}")
                return
            
            logger.info(f"Video processing complete")
            
            # ارسال ویدیو
            with open(output_video, 'rb') as video:
                await update.message.reply_video(
                    video=video,
                    caption="✅ تمام! اینترو اضافه شد",
                    write_timeout=60
                )
            
            logger.info("Video sent successfully")
    
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await update.message.reply_text(f"❌ خرابی: {str(e)[:100]}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! 👋\nویدیو بفرست و من اینترو رو بهش می‌چسبونم.")

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set!")
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.COMMAND, start))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    
    logger.info("Bot started!")
    app.run_polling()

if __name__ == '__main__':
    main()
