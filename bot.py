import os
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import subprocess
import tempfile

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

INTRO_VIDEO_PATH = "/app/intro.mp4"  # مسیر صحیح
BOT_TOKEN = os.getenv("BOT_TOKEN")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ در حال پردازش...")
    
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
            
            cmd = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_file, '-c', 'copy', '-y', output_video]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                await update.message.reply_text("❌ خرابی!")
                return
            
            with open(output_video, 'rb') as video:
                await update.message.reply_video(video=video, caption="✅ تمام!", write_timeout=30)
    
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await update.message.reply_text(f"❌ {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! ویدیو بفرست 👋")

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
