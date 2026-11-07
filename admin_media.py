from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from db import connect
from utils import is_admin, logger

(
    ED_CODE, ED_ACTION, ED_NEW_TITLE, ED_NEW_DESC, ED_NEW_FILE
) = range(40, 45)

async def edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Tahrirlash yoki o'chirish uchun Kino yoki Serial kodini yuboring:")
    return ED_CODE

async def ed_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id, type, title, description FROM media WHERE code=?", (code,))
    media = cur.fetchone()
    con.close()
    
    if not media:
        await update.message.reply_text("❌ Bunday kod bilan media topilmadi. Qaytadan yuboring yoki /cancel bosing.")
        return ED_CODE
        
    context.user_data['ed_media_id'] = media[0]
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Nomini o'zgarish", callback_data="ed_title"), InlineKeyboardButton("📝 Tavsifni o'zgarish", callback_data="ed_desc")],
        [InlineKeyboardButton("🎥 Faylni almashtirish", callback_data="ed_file"), InlineKeyboardButton("👑 VIP / Bepul", callback_data="ed_vip_toggle")],
        [InlineKeyboardButton("🗂 Fasllarni tahrirlash", callback_data="ed_eps")],
        [InlineKeyboardButton("🗑 Butunlay o'chirish", callback_data="ed_delete")]
    ])
    
    await update.message.reply_text(f"Topildi: {media[2]} ({media[1]})\nNimasini tahrirlamoqchisiz?", reply_markup=kb)
    return ED_ACTION

async def ed_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "ed_title":
        await query.message.reply_text("Yangi nomni yuboring:")
        return ED_NEW_TITLE
    elif data == "ed_desc":
        await query.message.reply_text("Yangi tavsifni yuboring:")
        return ED_NEW_DESC
    elif data == "ed_file":
        await query.message.reply_text("Yangi video faylni yuboring (Faqat kinolar yoki alohida qismlar uchun):")
        return ED_NEW_FILE
    elif data == "ed_eps":
        m_id = context.user_data['ed_media_id']
        con = connect()
        cur = con.cursor()
        cur.execute("SELECT id, season_number FROM seasons WHERE media_id=? ORDER BY season_number ASC", (m_id,))
        seasons = cur.fetchall()
        con.close()
        
        if not seasons:
            await query.message.reply_text("❌ Qismlar/Fasllar topilmadi!")
            return ED_ACTION
            
        kb = [[InlineKeyboardButton(f"🗑 {s[1]}-Faslni o'chirish", callback_data=f"del_sea_{s[0]}")] for s in seasons]
        await query.message.reply_text("Qadam: Faslni tanlang. Diqqat, tanlangan faslning barcha qismlari u bilan birga o'chib ketadi!", reply_markup=InlineKeyboardMarkup(kb))
        return ED_ACTION
        
    elif data.startswith("del_sea_"):
        s_id = int(data.split("_")[2])
        con = connect()
        cur = con.cursor()
        cur.execute("DELETE FROM episodes WHERE season_id=?", (s_id,))
        cur.execute("DELETE FROM seasons WHERE id=?", (s_id,))
        con.commit()
        con.close()
        await query.message.reply_text("✅ Fasl butunlay o'chirib tashlandi. Siz yangitdan 'Qism qo'shish' orqali boshqatdan bu faslni tiklashingiz yoki epizodlarni overwrite qilishingiz mumkin.")
        return ConversationHandler.END
        
    elif data == "ed_delete":
        m_id = context.user_data['ed_media_id']
        con = connect()
        cur = con.cursor()
        cur.execute("DELETE FROM media WHERE id=?", (m_id,))
        cur.execute("DELETE FROM favorites WHERE media_id=?", (m_id,))
        # cascading manually if needed, but SQLite allows it
        con.commit()
        con.close()
        await query.message.reply_text("🗑 Media va unga ulangan barcha yozuvlar o'chirildi.")
        return ConversationHandler.END
        
    elif data == "ed_vip_toggle":
        m_id = context.user_data['ed_media_id']
        con = connect()
        cur = con.cursor()
        cur.execute("SELECT is_vip FROM media WHERE id=?", (m_id,))
        res = cur.fetchone()
        new_vip = 0 if res and res[0] == 1 else 1
        cur.execute("UPDATE media SET is_vip=? WHERE id=?", (new_vip, m_id))
        con.commit()
        con.close()
        msg = "👑 Kino VIP ga aylantirildi!" if new_vip else "🆓 Kino bepul qilib belgilandi."
        await query.answer(msg, show_alert=True)
        return ED_ACTION

async def ed_title_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_title = update.message.text
    m_id = context.user_data['ed_media_id']
    con = connect()
    cur = con.cursor()
    cur.execute("UPDATE media SET title=? WHERE id=?", (new_title, m_id))
    con.commit()
    con.close()
    await update.message.reply_text("✅ Nom yangilandi.")
    return ConversationHandler.END

async def ed_desc_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_desc = update.message.text
    m_id = context.user_data['ed_media_id']
    con = connect()
    cur = con.cursor()
    cur.execute("UPDATE media SET description=? WHERE id=?", (new_desc, m_id))
    con.commit()
    con.close()
    await update.message.reply_text("✅ Tavsif yangilandi.")
    return ConversationHandler.END

async def ed_file_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.video and not update.message.document:
        await update.message.reply_text("Video fayl yuboring!")
        return ED_NEW_FILE
        
    file_id = update.message.video.file_id if update.message.video else update.message.document.file_id
    m_id = context.user_data['ed_media_id']
    con = connect()
    cur = con.cursor()
    cur.execute("UPDATE media SET file_id=? WHERE id=?", (file_id, m_id))
    con.commit()
    con.close()
    await update.message.reply_text("✅ Video fayl almashtirildi.")
    return ConversationHandler.END

async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END

def get_edit_media_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_start, pattern="^edit_media_menu$")],
        states={
            ED_CODE: [MessageHandler(filters.TEXT & ~(filters.COMMAND), ed_code)],
            ED_ACTION: [CallbackQueryHandler(ed_action)],
            ED_NEW_TITLE: [MessageHandler(filters.TEXT & ~(filters.COMMAND), ed_title_recv)],
            ED_NEW_DESC: [MessageHandler(filters.TEXT & ~(filters.COMMAND), ed_desc_recv)],
            ED_NEW_FILE: [MessageHandler(filters.ALL & ~(filters.COMMAND), ed_file_recv)],
        },
        fallbacks=[CommandHandler("cancel", cancel_edit)]
    )
