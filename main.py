import os
import re
import json
import asyncio
import time
from threading import Thread
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==========================================
# কনফিগারেশন
# ==========================================
BOT_TOKEN = "8960530766:AAGlXoTG82mtW7AIo8AvA6dEw9T9R0CdPKY"
ADMIN_ID = 6891217464
BOT_USERNAME = "Direct12_bot"
RENDER_URL = "https://telegram-bot-odb7.onrender.com"
WEB_APP_URL = "https://desi-hubpremium.vercel.app/"
DB_FILE = "videos.json"

HEADER_TEXT = "🎬 আপনার ভিডিওগুলো এখানে"

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

def add_album(media_list, title):
    """media_list = [{"file_id": "...", "type": "video/photo"}, ...]"""
    db = load_db()
    vid = str(db["next_id"])
    db["videos"][vid] = {"media": media_list, "title": title}
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

# Album collect করার জন্য buffer
album_buffer = {}       # media_group_id -> {"media": [...], "chat_id": ..., "title": ...}
album_tasks = {}        # media_group_id -> asyncio.Task

# ==========================================
# ১৫ মিনিট পর delete
# ==========================================
async def delete_after_delay(chat_id, message_ids, context):
    await asyncio.sleep(900)
    for mid in message_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception as e:
            print(f"Delete error {mid}: {e}")
    print(f"✅ Deleted {len(message_ids)} messages from chat {chat_id}")

# ==========================================
# Album process (10 সেকেন্ড অপেক্ষা করে সব media collect করে)
# ==========================================
async def process_album(media_group_id, context):
    await asyncio.sleep(3)  # সব media আসার জন্য অপেক্ষা

    data = album_buffer.pop(media_group_id, None)
    album_tasks.pop(media_group_id, None)

    if not data or not data["media"]:
        return

    chat_id = data["chat_id"]
    title = data["title"]
    media_list = data["media"]

    # Short ID save করো
    short_id = add_album(media_list, title)
    final_link = f"https://t.me/{BOT_USERNAME}?start={short_id}"

    count = len(media_list)
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✅ **{count}টি মিডিয়া সেভ হয়েছে!**\n\n"
             f"🆔 **Short ID:** `{short_id}`\n"
             f"📝 **Title:** {title}\n\n"
             f"🔗 **Download লিংক (ওয়েবে বসাও):**\n"
             f"`{final_link}`",
        parse_mode="Markdown"
    )

# ==========================================
# /start — User কে media পাঠায়
# ==========================================
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

    media_list = video.get("media", [])
    if not media_list:
        await update.message.reply_text("❌ কোনো মিডিয়া পাওয়া যায়নি।")
        return

    sent_ids = []

    # একটা একটা করে পাঠাও
    for item in media_list:
        try:
            if item["type"] == "video":
                m = await context.bot.send_video(chat_id=chat_id, video=item["file_id"])
            else:
                m = await context.bot.send_photo(chat_id=chat_id, photo=item["file_id"])
            sent_ids.append(m.message_id)
            await asyncio.sleep(0.5)   # spam এড়াতে
        except Exception as e:
            print(f"Send error: {e}")

    # শেষে final message + button
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 আরো দেখুন", url=WEB_APP_URL)]
    ])

    final_text = (
        f"*{HEADER_TEXT}*\n\n"
        f"⚠️ এই ভিডিওগুলো *১৫ মিনিট পর* ডিলিট হয়ে যাবে।\n"
        f"চাইলে সেভ করে রাখতে পারেন।"
    )

    try:
        final_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=final_text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        sent_ids.append(final_msg.message_id)
    except Exception as e:
        print(f"Final message error: {e}")

    # ১৫ মিনিট পর সব delete
    asyncio.create_task(delete_after_delay(chat_id, sent_ids, context))

# ==========================================
# Admin media handler (album + single)
# ==========================================
async def catch_everything(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    # শুধু admin
    if update.effective_user.id != ADMIN_ID:
        if message.text and not message.text.startswith('/'):
            await message.reply_text(
                "👋 হ্যালো! ভিডিও ডাউনলোড করতে আমাদের ওয়েবসাইট ব্যবহার করুন।"
            )
        return

    # কোনো media আছে কিনা
    file_id = None
    media_type = None

    if message.video:
        file_id = message.video.file_id
        media_type = "video"
    elif message.photo:
        file_id = message.photo[-1].file_id   # সবচেয়ে বড় resolution
        media_type = "photo"
    elif message.document and message.document.mime_type and message.document.mime_type.startswith('video/'):
        file_id = message.document.file_id
        media_type = "video"
    elif message.animation:
        file_id = message.animation.file_id
        media_type = "video"

    # চ্যানেল link টেক্সট দিলে forward করে file_id বের করা
    elif message.text and "t.me/" in message.text:
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
                    media_type = "video"
                elif target_msg.photo:
                    file_id = target_msg.photo[-1].file_id
                    media_type = "photo"
                elif target_msg.document:
                    file_id = target_msg.document.file_id
                    media_type = "video"
                elif target_msg.animation:
                    file_id = target_msg.animation.file_id
                    media_type = "video"

                await context.bot.delete_message(
                    chat_id=message.chat_id,
                    message_id=target_msg.message_id
                )
            except Exception as e:
                await message.reply_text("❌ চ্যানেল থেকে ফাইল রিড করা যায়নি।")
                print(f"Forward error: {e}")
                return

    # কোনো media পাওয়া যায়নি
    if not file_id:
        return

    # ===== Album (media_group_id থাকলে) =====
    if message.media_group_id:
        mgid = message.media_group_id

        if mgid not in album_buffer:
            album_buffer[mgid] = {
                "media": [],
                "chat_id": message.chat_id,
                "title": message.caption or f"Album"
            }

        album_buffer[mgid]["media"].append({
            "file_id": file_id,
            "type": media_type
        })

        # যদি caption থাকে, সেটাকে title বানাও
        if message.caption:
            album_buffer[mgid]["title"] = message.caption

        # প্রথম media আসার পর একটা task চালু করো
        if mgid not in album_tasks:
            task = asyncio.create_task(process_album(mgid, context))
            album_tasks[mgid] = task

        return

    # ===== Single media =====
    short_id = add_album([{"file_id": file_id, "type": media_type}],
                         message.caption or f"Video {load_db()['next_id']}")
    final_link = f"https://t.me/{BOT_USERNAME}?start={short_id}"

    await message.reply_text(
        text=f"✅ **মিডিয়া সেভ হয়েছে!**\n\n"
             f"🆔 **Short ID:** `{short_id}`\n"
             f"🔗 **Download লিংক:**\n"
             f"`{final_link}`",
        parse_mode="Markdown"
    )

# ==========================================
# Handlers
# ==========================================
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
    time.sleep(3)
    port = int(os.environ.get("PORT", 8080))
    print(f"🌐 Flask running on port {port}")
    app.run(host='0.0.0.0', port=port, use_reloader=False)

if __name__ == '__main__':
    main()
