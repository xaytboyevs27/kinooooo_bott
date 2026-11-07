from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from db import connect
from utils import is_admin, logger
import asyncio
import time

(
    BR_TEXT, BR_PHOTO, BR_BTN_TEXT, BR_BTN_URL, BR_CONFIRM
) = range(50, 55)

async def br_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("📣 Yangi Kengaytirilgan Broadcast (Tarqatish):\nXabar matnini yuboring:")
    else:
        await update.message.reply_text("📣 Yangi Kengaytirilgan Broadcast (Tarqatish):\nXabar matnini yuboring:")
    return BR_TEXT

async def br_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['br_text'] = update.message.text
    context.user_data.pop('br_photo', None) # Clear previous if any
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Rasmsiz davom etish", callback_data="skip_photo")]
    ])
    await update.message.reply_text("Agar xabarga rasm/video biriktirmoqchi bo'lsangiz yuboring. Yoki pastdagi tugmani bosing:", reply_markup=kb)
    return BR_PHOTO

async def br_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "skip_photo":
        await update.callback_query.answer()
        pass
    else:
        if update.message.photo:
            context.user_data['br_photo'] = update.message.photo[-1].file_id # highest resolution
        elif update.message.video:
            context.user_data['br_photo'] = update.message.video.file_id
        
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Tugma qo'shish", callback_data="add_btn")],
        [InlineKeyboardButton("⏭ Tugmasiz davom etish", callback_data="skip_btn")]
    ])
    await update.effective_message.reply_text("Xabarga URL tugma qo'shishni xohlaysizmi?", reply_markup=kb)
    return BR_BTN_TEXT

async def br_btn_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "skip_btn":
        await update.callback_query.answer()
        context.user_data.pop('br_btn_text', None)
        return await br_pre_confirm(update, context)
    
    context.user_data['br_btn_text'] = update.message.text
    await update.message.reply_text("Tugma silkasini (URL) yuboring (masalan: https://t.me/...):")
    return BR_BTN_URL

async def br_btn_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text("❌ Noto'g'ri URL. Iltimos, http:// yoki https:// bilan boshlanuvchi havola yuboring:")
        return BR_BTN_URL
    
    context.user_data['br_btn_url'] = url
    return await br_pre_confirm(update, context)

async def br_pre_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Hozir yuborish", callback_data="send_now")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_br")]
    ])
    
    msg_text = context.user_data.get('br_text', '')
    btn_text = context.user_data.get('br_btn_text')
    
    preview = f"📝 **Xabarni tasdiqlash:**\n\n{msg_text[:200]}..."
    if btn_text: preview += f"\n\n🔘 Tugma: {btn_text}"
    
    msg = update.message or update.callback_query.message
    await msg.reply_text(preview, reply_markup=kb, parse_mode="Markdown")
    return BR_CONFIRM

async def broadcast_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data
    msg_text = data.get('text')
    photo_id = data.get('photo')
    btn_text = data.get('btn_t')
    btn_url = data.get('btn_u')
    admin_id = data.get('admin_id')
    status_msg_id = data.get('msg_id')

    reply_markup = None
    if btn_text and btn_url:
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn_text, url=btn_url)]])

    con = connect(); cur = con.cursor()
    cur.execute("SELECT user_id FROM users")
    users = [u[0] for u in cur.fetchall()]
    con.close()

    CHUNK = 25
    total = len(users)
    success, failed = 0, 0
    failed_users = []

    def _update_progress(done_now, s_now, f_now):
        perc = int((done_now / max(1, total)) * 100)
        bar = "▪️" * (perc // 10) + "▫️" * (10 - (perc // 10))
        text = (
            f"📣 **BROADCAST JARAYONI**\n\n"
            f"Progres: {bar} {perc}%\n"
            f"✅ Yuborildi: {s_now}\n"
            f"❌ Muammo: {f_now}\n"
            f"📊 Jami: {total}"
        )
        try:
            context.bot.loop.create_task(
                context.bot.edit_message_text(chat_id=admin_id, message_id=status_msg_id, text=text, parse_mode="Markdown")
            )
        except Exception as e:
            logger.warning(f"Broadcast progress edit failed for admin {admin_id}: {e}")

    async def _send_one(uid):
        if photo_id:
            try:
                await context.bot.send_photo(chat_id=uid, photo=photo_id, caption=msg_text, reply_markup=reply_markup)
                return True
            except Exception:
                try:
                    await context.bot.send_video(chat_id=uid, video=photo_id, caption=msg_text, reply_markup=reply_markup)
                    return True
                except Exception:
                    return False
        else:
            try:
                await context.bot.send_message(chat_id=uid, text=msg_text, reply_markup=reply_markup)
                return True
            except Exception:
                return False

    done = 0
    for i in range(0, total, CHUNK):
        chunk = users[i:i + CHUNK]
        tasks = [_send_one(uid) for uid in chunk]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        for uid, ok in zip(chunk, results):
            done += 1
            if ok:
                success += 1
            else:
                failed += 1
                failed_users.append(uid)
        _update_progress(done, success, failed)
        await asyncio.sleep(0.8)

    retried_ok, retried_fail = 0, 0
    if failed_users:
        logger.info(f"Broadcast: retrying {len(failed_users)} failed users...")
        retry_chunk = 25
        for i in range(0, len(failed_users), retry_chunk):
            chunk = failed_users[i:i + retry_chunk]
            tasks = [_send_one(uid) for uid in chunk]
            results = await asyncio.gather(*tasks, return_exceptions=False)
            for ok in results:
                if ok:
                    retried_ok += 1
                    success += 1
                    failed = max(0, failed - 1)
                else:
                    retried_fail += 1
            await asyncio.sleep(0.8)

    try:
        final_text = (
            f"📣 **BROADCAST TUGADI**\n\n"
            f"✅ Yuborildi: {success}\n"
            f"❌ Muammo (2 urinishdan keyin ham): {failed}\n"
            f"🔁 Qayta yuborildi: {retried_ok}\n"
            f"📊 Jami: {total}"
        )
        await context.bot.edit_message_text(chat_id=admin_id, message_id=status_msg_id, text=final_text, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Broadcast final update failed: {e}")

    from handlers.admin import log_admin_action
    await log_admin_action(admin_id, f"Broadcast tugadi. Yuborildi: {success}, Muammo: {failed}, Qayta yuborildi: {retried_ok}")

async def br_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_br":
        await query.message.edit_text("❌ Bekor qilindi.")
        context.user_data.clear()
        return ConversationHandler.END
        
    if query.data == "send_now":
        msg_text = context.user_data.get('br_text')
        photo_id = context.user_data.get('br_photo')
        btn_t = context.user_data.get('br_btn_text')
        btn_u = context.user_data.get('br_btn_url')
        
        status_msg = await query.message.edit_text("🚀 Tarqatish boshlanmoqda...")
        
        context.job_queue.run_once(broadcast_job, 1, data={
            'text': msg_text, 'photo': photo_id, 
            'btn_t': btn_t, 'btn_u': btn_u,
            'admin_id': update.effective_user.id,
            'msg_id': status_msg.message_id
        })
        
        context.user_data.clear()
        return ConversationHandler.END

async def cancel_br_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Xabar tarqatish bekor qilindi.")
    return ConversationHandler.END

def get_broadcast_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(br_start, pattern="^broadcast$"), CommandHandler("broadcast", br_start)],
        states={
            BR_TEXT: [MessageHandler(filters.TEXT & ~(filters.COMMAND), br_text)],
            BR_PHOTO: [
                MessageHandler(filters.PHOTO | filters.VIDEO, br_photo),
                CallbackQueryHandler(br_photo, pattern="^skip_photo$")
            ],
            BR_BTN_TEXT: [
                MessageHandler(filters.TEXT & ~(filters.COMMAND), br_btn_text),
                CallbackQueryHandler(br_btn_text, pattern="^skip_btn$")
            ],
            BR_BTN_URL: [MessageHandler(filters.TEXT & ~(filters.COMMAND), br_btn_url)],
            BR_CONFIRM: [CallbackQueryHandler(br_confirm, pattern="^(send_now|cancel_br)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_br_conv)]
    )
