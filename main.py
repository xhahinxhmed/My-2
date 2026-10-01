import os
import re
import json
import asyncio
import time
from threading import Thread
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==========================================
# কনফিগারেশন
# ==========================================
BOT_TOKEN = "8960530766:AAHI_Z9TRjSGeApIVP8H1FVjBRMqoB3V_Xk"
ADMIN_ID = 6891217464
BOT_USERNAME = "@Direct12_bot"
RENDER_URL = "https://telegram-bot-odb7.onrender.com"
DB_FILE = "videos.json"

# ==========================================
# ডাটাবেজ
# ==========================================
def load_db():
    if not os.path.exists(DB_FILE):
        return {"next_id": 1, "videos": {}}
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"next_id": 1, "videos": {}}

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

def add_video(file_id, title):
    db = load_db()
    vid = str(db["next_id"])
    db["videos"][vid] = {"file_id": file_id, "title": title}
    db["next_id"] += 1
    save_db(db)
    return vid

def get_video(vid):
    db = load_db()
    return db["videos"].get(str(vid))

# ==========================================
# Telegram Application (webhook mode)
# ==========================================
application = Application.builder().token(BOT_TOKEN).updater(None).build()

# ১৫ মিনিট পর delete
async def delete_after_delay(chat_id, message_id, context):
    await asyncio.sleep(900)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        print(f"✅ Deleted: {message_id}")
    except Exception as e:
        print(f"Delete error: {e}")

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "👋 হ্যালো! ভিডিও ডাউনলোড করতে আমাদের ওয়েবসাইটের Download বাটনে ক্লিক করুন।"
        )
        return

    video = get_video(args[0])
    if not video:
        await update.message.reply_text("❌ দুঃখিত! ভিডিওটি পাওয়া যায়নি।")
        return

    try:
        sent = await context.bot.send_video(
            chat_id=chat_id,
            video=video["file_id"],
            caption=f"🍿 **{video['title']}**\n\n"
                    f"⚠️ এটি ১৫ মিনিট পর স্বয়ংক্রিয়ভাবে মুছে যাবে।",
            parse_mode="Markdown"
        )
        asyncio.create_task(delete_after_delay(chat_id, sent.message_id, context))
    except Exception as e:
        await update.message.reply_text("❌ ভিডিওটি পাঠানো যায়নি।")
        print(f"Send error: {e}")

# Admin video upload
async def catch_everything(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    if message.text and message.text.startswith('/'):
        return

    file_id = None

    if message.video:
        file_id = message.video.file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith('video/'):
        file_id = message.document.file_id
    elif message.animation:
        file_id = message.animation.file_id
    elif message.text and ("t.me/" in message.text):
        link_parts = re.findall(r't\.me/(?:c/)?([^/]+)/(\d+)', message.text)
        if link_parts:
            channel_peer, msg_id = link_parts[0]
            message_id = int(msg_id)
            chat_target = int(f"-100{channel_peer}") if channel_peer.isdigit() else f"@{channel_peer}"
            try:
                target_msg = await context.bot.forward_message(
                    chat_id=message.chat_id,
                    from_chat_id=chat_target,
                    message_id=message_id
                )
                if target_msg.video:
                    file_id = target_msg.video.file_id
                elif target_msg.document:
                    file_id = target_msg.document.file_id
                elif target_msg.animation:
                    file_id = target_msg.animation.file_id
                await context.bot.delete_message(
                    chat_id=message.chat_id, message_id=target_msg.message_id
                )
            except Exception as e:
                await message.reply_text("❌ চ্যানেল থেকে ফাইল রিড করা যায়নি।")
                return

    if file_id:
        title = message.caption or f"Video {load_db()['next_id']}"
        short_id = add_video(file_id, title)
        final_link = f"https://t.me/{BOT_USERNAME}?start={short_id}"
        await message.reply_text(
            text=f"✅ **ভিডিও সেভ হয়েছে!**\n\n"
                 f"🆔 **Short ID:** `{short_id}`\n"
                 f"📝 **Title:** {title}\n\n"
                 f"🔗 **Download লিংক:**\n"
                 f"`{final_link}`",
            parse_mode="Markdown"
        )
    elif message.text:
        await update.message.reply_text(
            "👋 হ্যালো! ভিডিও ডাউনলোড করতে আমাদের ওয়েবসাইট ব্যবহার করুন।"
        )

# Handlers add
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.ALL, catch_everything))

# ==========================================
# Flask + Webhook
# ==========================================
app = Flask('')
loop = asyncio.new_event_loop()

@app.route('/')
def home():
    return "✅ Premium Hub Bot is Running"

@app.route('/health')
def health():
    return "alive", 200

@app.route(f'/webhook/{BOT_TOKEN}', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, application.bot)
        asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
        return "ok", 200
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return "error", 500

# ==========================================
# Startup
# ==========================================
async def setup_bot():
    await application.initialize()
    await application.bot.set_webhook(
        url=f"{RENDER_URL}/webhook/{BOT_TOKEN}",
        drop_pending_updates=True
    )
    await application.start()
    print(f"✅ Webhook set: {RENDER_URL}/webhook/{BOT_TOKEN}")

def run_async():
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup_bot())
    loop.run_forever()

def main():
    Thread(target=run_async, daemon=True).start()
    time.sleep(3)  # bot setup হওয়ার জন্য অপেক্ষা
    port = int(os.environ.get("PORT", 8080))
    print(f"🌐 Flask running on port {port}")
    app.run(host='0.0.0.0', port=port, use_reloader=False)

if __name__ == '__main__':
    main()
