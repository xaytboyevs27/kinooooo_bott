from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from db import connect
from utils import is_admin, logger

# States
AD_TEXT, AD_IMG, AD_BTN = range(50, 53)

async def ads_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    query = update.callback_query
    
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id, text, views FROM ads WHERE is_active=1")
    ads = cur.fetchall()
    con.close()
    
    text = "📢 **Reklamalar Tizimi**\n\nJoriy aktiv reklamalar:\n"
    kb = []
    if not ads:
        text += "Reklamalar yo'q."
    else:
        for ad in ads:
            text += f"ID: {ad[0]} | Ko'rishlar: {ad[2]}\n"
            kb.append([InlineKeyboardButton(f"🗑 O'chirish (ID: {ad[0]})", callback_data=f"del_ad:{ad[0]}")])
            
    kb.append([InlineKeyboardButton("➕ Yangi Reklama Qo'shish", callback_data="add_ad_start")])
    kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data="sys_settings")])
    
    await query.answer()
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_ad_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("📢 Reklama matnini yuboring:\n(Bekor qilish uchun /cancel)")
    return AD_TEXT

async def add_ad_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ad_text'] = update.message.text
    await update.message.reply_text("📸 Reklama rasmi (ixtiyoriy, agar yo'q bo'lsa 'yoq' deb yozing):")
    return AD_IMG

async def add_ad_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data['ad_img'] = update.message.photo[-1].file_id
    else:
        context.user_data['ad_img'] = None
    await update.message.reply_text("🔗 Reklama tugmasi (Format: Text - URL)\nMisol: `Kanalga O'tish - https://t.me/kanal`\n\nAgar tugma kerakmas bo'lsa, 'yoq' deb yozing.", parse_mode="Markdown")
    return AD_BTN

async def add_ad_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    btn_text, btn_url = None, None
    if txt.lower() != 'yoq' and "-" in txt:
        try:
            parts = txt.split("-")
            btn_text = parts[0].strip()
            btn_url = parts[1].strip()
        except:
            pass
            
    con = connect()
    cur = con.cursor()
    cur.execute("INSERT INTO ads (text, image_id, button_text, button_url) VALUES (?, ?, ?, ?)", 
                (context.user_data.get('ad_text'), context.user_data.get('ad_img'), btn_text, btn_url))
    con.commit()
    con.close()
    
    await update.message.reply_text("✅ Reklama muvaffaqiyatli qo'shildi!")
    return ConversationHandler.END

async def del_ad_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ad_id = int(update.callback_query.data.split(":")[1])
    con = connect()
    cur = con.cursor()
    cur.execute("UPDATE ads SET is_active=1 WHERE id=?", (ad_id,))
    cur.execute("DELETE FROM ads WHERE id=?", (ad_id,)) # Hard delete is better for simple apps
    con.commit()
    con.close()
    await update.callback_query.answer("O'chirildi!")
    await ads_menu(update, context)

def cancel_ad(update, context):
    update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END

def get_ads_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(add_ad_start, pattern="^add_ad_start$")],
        states={
            AD_TEXT: [MessageHandler(filters.TEXT & ~(filters.COMMAND), add_ad_text)],
            AD_IMG: [MessageHandler(filters.PHOTO | filters.TEXT & ~(filters.COMMAND), add_ad_img)],
            AD_BTN: [MessageHandler(filters.TEXT & ~(filters.COMMAND), add_ad_btn)],
        },
        fallbacks=[CommandHandler("cancel", cancel_ad)]
    )

def get_ads_callbacks():
    return [
        CallbackQueryHandler(ads_menu, pattern="^ads_menu$"),
        CallbackQueryHandler(del_ad_callback, pattern="^del_ad:")
    ]
