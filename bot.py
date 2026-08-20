import os
import sys
import json
import time
import asyncio
import logging
import subprocess
import threading
import sqlite3
from dotenv import load_dotenv

# تلاش برای بارگذاری ابزار نمایش آمار سرور
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# بارگذاری متغیرهای محیطی
load_dotenv()

API_ID_STR = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID_STR = os.environ.get("ADMIN_ID") # دریافت آیدی ادمین

if not API_ID_STR or not API_HASH or not BOT_TOKEN:
    print("\n" + "!"*60)
    print("❌ خطای بحرانی: اطلاعات ورود در فایل .env پیدا نشد!")
    print("!"*60 + "\n")
    sys.exit(1)

API_ID = int(API_ID_STR)
ADMIN_ID = int(ADMIN_ID_STR) if ADMIN_ID_STR else 0
INTRO_FILE = "intro.png"

# فعال‌سازی uvloop برای سرعت شبکه
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait

logging.basicConfig(level=logging.INFO)

# --- مدیریت دیتابیس SQLite ---
def init_db():
    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS queue
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  chat_id INTEGER,
                  message_id INTEGER,
                  status TEXT)''')
    conn.commit()
    conn.close()

def add_to_db(user_id, chat_id, message_id):
    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("INSERT INTO queue (user_id, chat_id, message_id, status) VALUES (?, ?, ?, 'waiting')",
              (user_id, chat_id, message_id))
    item_id = c.lastrowid
    conn.commit()
    conn.close()
    return item_id

def update_db_status(item_id, status):
    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("UPDATE queue SET status = ? WHERE id = ?", (status, item_id))
    conn.commit()
    conn.close()

# --- وب‌سرور ---
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

# --- تنظیمات کلاینت ---
app = Client(
    "intro_bot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN,
    workers=4,
    max_concurrent_transmissions=7
)

user_sessions = {}

def get_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = {'queue': [], 'is_processing': False, 'dashboard_msg': None, 'cancel_flag': False}
    return user_sessions[user_id]

def make_progress_bar(current, total):
    percentage = current * 100 / total if total > 0 else 0
    completed = int(percentage / 10)
    bar = "█" * completed + "░" * (10 - completed)
    return f"[{bar}] {percentage:.1f}%"

class CancelledError(Exception):
    pass

async def telegram_progress(current, total, user_id, action_text, last_edit):
    session = get_session(user_id)
    if session['cancel_flag']:
        raise CancelledError("Operation cancelled by user.")
        
    now = time.time()
    if now - last_edit[0] >= 3 or current == total:
        last_edit[0] = now
        bar = make_progress_bar(current, total)
        await update_dashboard(user_id, current_action=f"{action_text}\n{bar}")

def get_video_info(file_path):
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,duration,bit_rate:stream_tags=rotate:side_data=rotation", "-of", "json", file_path]
    res = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    if not streams: return 0.0, 1280, 720, "1000k"

    stream = streams[0]
    width, height = int(stream.get("width", 1280)), int(stream.get("height", 720))
    duration = float(stream.get("duration", 0))
    bit_rate = stream.get("bit_rate")

    cmd_fmt = ["ffprobe", "-v", "error", "-show_entries", "format=duration,bit_rate", "-of", "json", file_path]
    res_fmt = subprocess.run(cmd_fmt, capture_output=True, text=True)
    data_fmt = json.loads(res_fmt.stdout)
    if duration == 0: duration = float(data_fmt.get("format", {}).get("duration", 0))
    if not bit_rate: bit_rate = data_fmt.get("format", {}).get("bit_rate")
        
    try: bit_rate_kb = f"{int(int(bit_rate) / 1000)}k" if bit_rate else "1000k"
    except (ValueError, TypeError): bit_rate_kb = "1000k"

    rotation = 0
    tags = stream.get("tags", {})
    if "rotate" in tags:
        try: rotation = int(tags["rotate"])
        except ValueError: pass
    for side in stream.get("side_data_list", []):
        if "rotation" in side:
            try: rotation = int(side["rotation"])
            except ValueError: pass

    if abs(rotation) in (90, 270): width, height = height, width
    return duration, width, height, bit_rate_kb

def generate_thumbnail(video_path, thumb_path):
    cmd = ["ffmpeg", "-y", "-ss", "00:00:01", "-i", video_path, "-vframes", "1", thumb_path]
    subprocess.run(cmd, capture_output=True)

async def process_concat_with_progress(intro_path, input_path, output_path, total_duration, target_width, target_height, bit_rate, user_id):
    target_width = target_width - (target_width % 2)
    target_height = target_height - (target_height % 2)

    cmd = [
        "ffmpeg", "-y", "-progress", "pipe:1",
        "-loop", "1", "-framerate", "30", "-t", "3", "-i", intro_path,                     
        "-i", input_path,                                                                  
        "-f", "lavfi", "-t", "3", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-filter_complex",
        f"[0:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease[fg];"
        f"[0:v]scale={target_width}:{target_height}:force_original_aspect_ratio=crop,boxblur=20:20[bg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30[v0];"
        f"[1:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v1];"
        "[2:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];"
        "[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];"
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", bit_rate, "-maxrate", bit_rate, "-bufsize", str(int(bit_rate.replace('k',''))*2)+"k", "-threads", "0",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", output_path
    ]

    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    last_edit = 0
    session = get_session(user_id)
    
    while True:
        if session['cancel_flag']:
            process.kill()
            raise CancelledError("Operation cancelled by user.")
        try: line = await asyncio.wait_for(process.stdout.readline(), timeout=1.0)
        except asyncio.TimeoutError: continue
        if not line: break
            
        line_str = line.decode('utf-8', errors='ignore').strip()
        if line_str.startswith("out_time_us="):
            try:
                current_seconds = int(line_str.split("=")[1]) / 1_000_000
                now = time.time()
                if now - last_edit > 3 and total_duration > 0:
                    last_edit = now
                    bar = make_progress_bar(current_seconds, total_duration)
                    await update_dashboard(user_id, current_action=f"⚙️ در حال ساخت و چسباندن اینترو...\n{bar}")
            except Exception: pass
    await process.wait()

async def update_dashboard(user_id, current_action=""):
    session = get_session(user_id)
    if not session['dashboard_msg']: return
    queue = session['queue']
    text = "📊 **داشبورد وضعیت ویدیوها**\n\n"
    for i, item in enumerate(queue):
        if item['status'] == 'completed': text += f"✅ ویدیو {i+1}: تکمیل و ارسال شد\n"
        elif item['status'] == 'processing': text += f"🔄 ویدیو {i+1}: در حال پردازش\n{current_action}\n"
        elif item['status'] == 'waiting': text += f"🕒 ویدیو {i+1}: در صف انتظار...\n"
        elif item['status'] == 'cancelled': text += f"❌ ویدیو {i+1}: لغو شد\n"
            
    text += f"\nمجموع ویدیوها: {len(queue)}"
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 لغو تمامی عملیات‌ها", callback_data="cancel_all")]])
    
    try: await session['dashboard_msg'].edit_text(text, reply_markup=reply_markup)
    except FloodWait as e: await asyncio.sleep(e.value)
    except Exception: pass

async def process_user_queue(client: Client, user_id: int):
    session = get_session(user_id)
    session['is_processing'] = True
    
    while True:
        waiting_items = [item for item in session['queue'] if item['status'] == 'waiting']
        if not waiting_items or session['cancel_flag']: break
            
        current_item = waiting_items[0]
        current_item['status'] = 'processing'
        db_id = current_item['db_id']
        update_db_status(db_id, 'processing')
        
        message = current_item['message']
        input_path, output_path, thumb_path = f"input_{message.id}.mp4", f"output_{message.id}.mp4", f"thumb_{message.id}.jpg"
        
        try:
            last_edit = [0]
            input_path = await message.download(
                file_name=input_path, progress=telegram_progress, progress_args=(user_id, "📥 در حال دانلود ویدیو...", last_edit)
            )

            intro_dur = 3.0  
            main_dur, width, height, bit_rate = get_video_info(input_path)
            total_duration = intro_dur + main_dur

            await update_dashboard(user_id, "⚙️ شروع پردازش ویدیو...")
            await process_concat_with_progress(INTRO_FILE, input_path, output_path, total_duration, width, height, bit_rate, user_id)
            generate_thumbnail(output_path, thumb_path)

            last_edit = [0]
            await client.send_video(
                chat_id=message.chat.id, video=output_path, caption="✅ اینترو با موفقیت اضافه شد.",
                duration=int(total_duration), width=width, height=height,
                thumb=thumb_path if os.path.exists(thumb_path) else None, supports_streaming=True,
                progress=telegram_progress, progress_args=(user_id, "📤 در حال آپلود ویدیو...", last_edit)
            )
            current_item['status'] = 'completed'
            update_db_status(db_id, 'completed')
            await update_dashboard(user_id, "✅ انجام شد")
            
        except CancelledError:
            current_item['status'] = 'cancelled'
            update_db_status(db_id, 'cancelled')
        except Exception as e:
            logging.error(f"Error: {e}")
            current_item['status'] = 'error'
            update_db_status(db_id, 'error')
        finally:
            for path in [input_path, output_path, thumb_path]:
                if os.path.exists(path): os.remove(path)

    if session['cancel_flag']: await session['dashboard_msg'].edit_text("🛑 عملیات توسط شما لغو شد.")
    else:
        try: await session['dashboard_msg'].delete()
        except: pass
            
    session['queue'], session['is_processing'], session['dashboard_msg'], session['cancel_flag'] = [], False, None, False

async def recover_lost_queues(client: Client):
    conn = sqlite3.connect("bot_database.db")
    c = conn.cursor()
    c.execute("SELECT id, user_id, chat_id, message_id FROM queue WHERE status IN ('waiting', 'processing')")
    rows = c.fetchall()
    if not rows:
        conn.close()
        return

    from collections import defaultdict
    users_tasks = defaultdict(list)
    for r in rows:
        db_id, user_id, chat_id, message_id = r
        users_tasks[user_id].append((db_id, chat_id, message_id))
        c.execute("UPDATE queue SET status = 'waiting' WHERE id = ?", (db_id,))
    
    conn.commit()
    conn.close()
    
    for user_id, tasks in users_tasks.items():
        session = get_session(user_id)
        for db_id, chat_id, message_id in tasks:
            try:
                msg = await client.get_messages(chat_id, message_id)
                if msg and not msg.empty: session['queue'].append({'db_id': db_id, 'message': msg, 'status': 'waiting'})
                else: update_db_status(db_id, 'error_deleted')
            except Exception: update_db_status(db_id, 'error_fetch')
        
        if session['queue'] and not session['is_processing']:
            try:
                session['dashboard_msg'] = await client.send_message(chat_id=user_id, text="🔄 **بازیابی صف پس از راه‌اندازی مجدد سرور...**")
                asyncio.create_task(process_user_queue(client, user_id))
            except Exception: pass

# ----------------- پنل ادمین -----------------
@app.on_message(filters.command("id"))
async def send_user_id(_, message: Message):
    await message.reply_text(f"آیدی عددی تلگرام شما:\n`{message.from_user.id}`")

def get_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار سرور و رم", callback_data="admin_stats")],
        [InlineKeyboardButton("🔄 ری‌استارت ربات", callback_data="admin_restart")],
        [InlineKeyboardButton("🛑 خاموش کردن سیستم", callback_data="admin_shutdown")]
    ])

@app.on_message(filters.command("admin"))
async def admin_panel_cmd(_, message: Message):
    if not ADMIN_ID:
        return await message.reply_text("⚠️ شما هنوز آیدی ادمین را در فایل .env قرار نداده‌اید.\nابتدا دستور /id را بزنید و آیدی خود را در فایل محیطی به عنوان ADMIN_ID ثبت کنید.")
    
    if message.from_user.id != ADMIN_ID:
        return await message.reply_text("⛔ شما دسترسی به پنل مدیریت ندارید.")
        
    await message.reply_text("🎛 **پنل مدیریت ربات**\n\nجهت کنترل ربات از گزینه‌های زیر استفاده کنید:", reply_markup=get_admin_keyboard())

@app.on_callback_query(filters.regex("^admin_"))
async def admin_callbacks(client, callback_query: CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        return await callback_query.answer("⛔ دسترسی غیرمجاز", show_alert=True)
        
    action = callback_query.data.split("_")[1]
    
    if action == "stats":
        if HAS_PSUTIL:
            cpu = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory().percent
            text = f"📊 **وضعیت منابع سرور (کداسپیس)**\n\nپردازنده (CPU): {cpu}%\nحافظه (RAM): {ram}%"
        else:
            text = "⚠️ کتابخانه psutil نصب نیست.\nوضعیت سرور قابل مشاهده نمی‌باشد."
        
        await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_back")]]))
        
    elif action == "restart":
        await callback_query.answer("🔄 ربات در حال ری‌استارت است...", show_alert=True)
        await callback_query.message.edit_text("🔄 ربات ری‌استارت شد.")
        os.execl(sys.executable, sys.executable, *sys.argv)
        
    elif action == "shutdown":
        await callback_query.answer("🛑 ربات خاموش شد.", show_alert=True)
        await callback_query.message.edit_text("🛑 فرآیند پردازش ربات با موفقیت خاموش شد.")
        os._exit(0)
        
    elif action == "back":
        await callback_query.message.edit_text("🎛 **پنل مدیریت ربات**\n\nجهت کنترل ربات از گزینه‌های زیر استفاده کنید:", reply_markup=get_admin_keyboard())

# ----------------- هندلرهای اصلی -----------------
@app.on_message(filters.command("start"))
async def start_cmd(_, message: Message):
    await message.reply_text("سلام! ویدیوهای خود را ارسال کنید تا در صف قرار بگیرند و پردازش شوند.")

@app.on_message(filters.video | filters.document)
async def handle_incoming_video(client: Client, message: Message):
    if message.document and not message.document.mime_type.startswith("video/"): return
    if not os.path.exists(INTRO_FILE):
        return await message.reply_text("❌ عکس intro.png پیدا نشد.")

    user_id = message.from_user.id
    db_id = add_to_db(user_id, message.chat.id, message.id)
    
    session = get_session(user_id)
    session['queue'].append({'db_id': db_id, 'message': message, 'status': 'waiting'})
    
    if not session['dashboard_msg']: session['dashboard_msg'] = await message.reply_text("📊 ایجاد داشبورد وضعیت...")
    else: await update_dashboard(user_id)

    if not session['is_processing']: asyncio.create_task(process_user_queue(client, user_id))

@app.on_callback_query(filters.regex("^cancel_all$"))
async def cancel_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    session = get_session(user_id)
    if session['is_processing']:
        session['cancel_flag'] = True
        for item in session['queue']:
            if item['status'] in ('waiting', 'processing'): update_db_status(item['db_id'], 'cancelled')
        await callback_query.answer("🛑 در حال لغو عملیات... لطفاً صبر کنید.", show_alert=True)
    else:
        await callback_query.answer("عملیاتی در حال اجرا نیست.", show_alert=True)

async def main():
    init_db()
    await app.start()
    logging.info("Bot started successfully! Checking for lost queues...")
    await recover_lost_queues(app)
    await idle()
    await app.stop()

if __name__ == "__main__":
    try: loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
