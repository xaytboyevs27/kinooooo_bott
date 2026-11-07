from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from db import connect
from config import DB_PATH
from utils import is_admin, logger
import csv
import io
import time

(
    FS_ID, FS_LINK, FS_TITLE, FS_PRICE, FS_DAYS,
    SET_BACKUP, SET_PCHAN,
    # Voucher States
    VO_CODE, VO_DAYS, VO_DISCOUNT, VO_USES,
    # Direct Msg
    DM_UID, DM_TEXT,
    # Text Editor
    ET_START,
    # Admin Management
    AM_UID
) = range(30, 45)

# ------------- CSV EXPORT -------------
async def export_csv_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.callback_query.answer("Statistika tayyorlanmoqda...")
    
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT user_id, username, last_seen, language, role, vip_until, referred_count FROM users")
    users = cur.fetchall()
    con.close()
    
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["ID", "Username", "Last Seen", "Language", "Role", "VIP Until", "Ref Count"])
    writer.writerows(users)
    
    await context.bot.send_document(
        chat_id=update.effective_user.id,
        document=bytes(out.getvalue(), 'utf-8'),
        filename="users_stat.csv",
        caption="📊 Barcha foydalanuvchilar statistikasi"
    )

# ------------- AUTO BACKUP -------------
async def manual_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.callback_query.answer("Baza yuborilmoqda...")
    
    try:
        with open(DB_PATH, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_user.id,
                document=f,
                filename="database_backup.db",
                caption=f"📁 Bazaning oxirgi zaxirasi ({time.strftime('%Y-%m-%d %H:%M')})"
            )
    except Exception as e:
        await update.callback_query.message.reply_text(f"Xatolik: {e}")

async def set_backup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "💾 Zaxira saqlash maxfiy kanalini kiritish:\n\n"
        "Buning uchun oldin kanal yarating, botni u yerga admin qiling va kanalning ID raqamini (masalan: -1001234567) yuboring:"
    )
    return SET_BACKUP

async def set_backup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel_id = update.message.text.strip()
    con = connect()
    cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO sys_settings (key, value) VALUES ('backup_channel', ?)", (channel_id,))
    con.commit()
    con.close()
    
    await update.message.reply_text(f"✅ Maxfiy kanal muvaffaqiyatli saqlandi: {channel_id}\n\nEndi bot avtomatik tarzda .db faylini o'sha yerga har kuni yuborib turadi.")
    # Attempt to send a test message
    try:
        await context.bot.send_message(chat_id=channel_id, text="Zaxira kanali tasdiqlandi!")
    except Exception as e:
        await update.message.reply_text(f"Lekin kanalga yozib bo'lmadi (Bot admin emas bo'lishi mumkin): {e}")
        
    return ConversationHandler.END

# ------------- FORCE SUB (Majburiy Obuna) -------------
async def fs_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.callback_query.answer()
    # Shaxsiy kanal qo'shish
    await update.callback_query.message.reply_text("📣 Majburiy obuna kanali ID sini yuboring (-100... bilan):")
    return FS_ID

async def fs_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_fs_id'] = update.message.text.strip()
    await update.message.reply_text("Kanalga kirish uchun silkani (invite link) yuboring:")
    return FS_LINK

async def fs_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_fs_link'] = update.message.text.strip()
    await update.message.reply_text("Kanalning botagi yozuvda qanday nom bilan chiqishini yozing:")
    return FS_TITLE

async def fs_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_fs_title'] = update.message.text.strip()
    await update.message.reply_text("Kanalni ro'yxatda ushlab turish narxi (masalan: 50000) yoki '0' deb yozing bepul bo'lsa:")
    return FS_PRICE
    
async def fs_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_fs_price'] = int(update.message.text.strip()) if update.message.text.strip().isdigit() else 0
    await update.message.reply_text("Kanal botda necha kun turishi kerak? (masalan: 30) yoki '0' deb yozing cheksiz bo'lsa:")
    return FS_DAYS

async def fs_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = int(update.message.text.strip()) if update.message.text.strip().isdigit() else 0
    
    c_id = context.user_data['temp_fs_id']
    link = context.user_data['temp_fs_link']
    title = context.user_data['temp_fs_title']
    price = context.user_data['temp_fs_price']
    
    import datetime
    expires_at = None
    if days > 0:
        expires_at = (datetime.datetime.now() + datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    
    con = connect()
    cur = con.cursor()
    cur.execute("INSERT INTO force_sub_channels (chat_id, invite_link, title, price, expires_at) VALUES (?, ?, ?, ?, ?)", 
                (c_id, link, title, price, expires_at))
    con.commit()
    con.close()
    
    await update.message.reply_text(f"✅ Majburiy obuna kanal qo'shildi: {title}\nMuddat: {days} kun\nNarxi: {price} so'm")
    return ConversationHandler.END


# ------------- SYS MENU -------------
async def sys_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💾 Zaxira Kanal", callback_data="set_backup"), InlineKeyboardButton("📢 Post Kanali", callback_data="manage_post_channel")],
        [InlineKeyboardButton("➕ Majburiy Obuna", callback_data="add_force_sub"), InlineKeyboardButton("📁 Baza (DB)", callback_data="manual_backup")],
        [InlineKeyboardButton("🎟 Vucherlar", callback_data="vouchers_menu"), InlineKeyboardButton("💳 To'lovlar Tarixi", callback_data="pay_history")],
        [InlineKeyboardButton("✉️ Userga Yozish", callback_data="direct_msg"), InlineKeyboardButton("📝 Greeting Text Edit", callback_data="edit_start_text")],
        [InlineKeyboardButton("👮‍♂️ Adminlar", callback_data="admin_mgmt_menu"), InlineKeyboardButton("📢 Reklamalar", callback_data="ads_menu")],
        [InlineKeyboardButton("📉 CSV Export", callback_data="export_csv"), InlineKeyboardButton("🔙 Orqaga", callback_data="admin_main")]
    ])
    
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "⚙️ Tizim sozlamalari:\n\nQaysi sozlamani o'zgartirmoqchisiz?", 
        reply_markup=kb
    )

# ------------- POST CHANNEL SETTINGS -------------
async def manage_post_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    con = connect(); cur = con.cursor()
    cur.execute("SELECT value FROM sys_settings WHERE key='post_channel'")
    row = cur.fetchone()
    current_pchan = row[0] if row and row[0] else None
    
    current_title = "Belgilanmagan"
    if current_pchan:
        cur.execute("SELECT title FROM force_sub_channels WHERE chat_id=?", (current_pchan,))
        ch_title_row = cur.fetchone()
        current_title = f"{ch_title_row[0]} ({current_pchan})" if ch_title_row else current_pchan

    cur.execute("SELECT chat_id, title FROM force_sub_channels")
    chans = cur.fetchall()
    con.close()
    
    kb = []
    for ch in chans:
        is_curr = "✅ " if str(ch[0]) == str(current_pchan) else ""
        kb.append([InlineKeyboardButton(f"{is_curr}{ch[1]}", callback_data=f"set_pchan_direct:{ch[0]}")])
    kb.append([InlineKeyboardButton("✏️ Yangi ID kiritish", callback_data="set_pchan_manual")])
    if current_pchan:
        kb.append([InlineKeyboardButton("🗑 O'chirish", callback_data="clear_pchan")])
    kb.append([InlineKeyboardButton("🔙 Orqaga", callback_data="sys_settings")])
    
    text = (
        f"📢 <b>AVTO-POST KANALI SOZLAMASI</b>\n\n"
        f"📌 Hozirgi kanal: <b>{current_title}</b>\n\n"
        f"Kino qo'shilganda rasmdagidek avto-post yuborilishi uchun kanalni tanlang yoki yangi ID kiriting:"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def set_pchan_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    query = update.callback_query
    channel_id = query.data.split(":", 1)[1]
    
    con = connect(); cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO sys_settings (key, value) VALUES ('post_channel', ?)", (channel_id,))
    con.commit(); con.close()
    
    await query.answer("✅ Post kanali yangilandi!", show_alert=True)
    return await manage_post_channel(update, context)

async def clear_pchan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    query = update.callback_query
    
    con = connect(); cur = con.cursor()
    cur.execute("DELETE FROM sys_settings WHERE key='post_channel'")
    con.commit(); con.close()
    
    await query.answer("Post kanali olib tashlandi", show_alert=True)
    return await manage_post_channel(update, context)

async def set_pchan_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "📢 <b>Kanal ID raqamini yuboring (-100... bilan):</b>\n\n"
        "<i>Eslatma: Bot ushbu kanalda administrator bo'lishi va post yuborish huquqiga ega bo'lishi shart!</i>",
        parse_mode="HTML"
    )
    return SET_PCHAN

async def set_pchan_recv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel_id = update.message.text.strip()
    con = connect(); cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO sys_settings (key, value) VALUES ('post_channel', ?)", (channel_id,))
    con.commit(); con.close()
    
    await update.message.reply_text(f"✅ Yangi post kanali saqlandi: <code>{channel_id}</code>\n\nKanalga test xabari yuborilmoqda...", parse_mode="HTML")
    try:
        await context.bot.send_message(chat_id=channel_id, text="✅ Ushbu kanal kino boti uchun post kanali sifatida muvaffaqiyatli ulandi!")
        await update.message.reply_text("✅ Kanalga muvaffaqiyatli xabar yuborildi!")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Kanalga xabar yuborib bo'lmadi (Bot admin emas bo'lishi mumkin): {e}")
        
    return ConversationHandler.END

def get_post_channel_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(set_pchan_prompt, pattern="^set_pchan_manual$")],
        states={
            SET_PCHAN: [MessageHandler(filters.TEXT & ~(filters.COMMAND), set_pchan_recv)],
        },
        fallbacks=[CommandHandler("cancel", cancel_xtra)]
    )

async def cancel_xtra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END

def get_backup_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(set_backup_start, pattern="^set_backup$")],
        states={
            SET_BACKUP: [MessageHandler(filters.TEXT & ~(filters.COMMAND), set_backup_channel)],
        },
        fallbacks=[CommandHandler("cancel", cancel_xtra)]
    )

def get_force_sub_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(fs_start, pattern="^add_force_sub$")],
        states={
            FS_ID: [MessageHandler(filters.TEXT & ~(filters.COMMAND), fs_id)],
            FS_LINK: [MessageHandler(filters.TEXT & ~(filters.COMMAND), fs_link)],
            FS_TITLE: [MessageHandler(filters.TEXT & ~(filters.COMMAND), fs_title)],
            FS_PRICE: [MessageHandler(filters.TEXT & ~(filters.COMMAND), fs_price)],
            FS_DAYS: [MessageHandler(filters.TEXT & ~(filters.COMMAND), fs_days)],
        },
        fallbacks=[CommandHandler("cancel", cancel_xtra)]
    )
async def pay_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.callback_query.answer()
    
    con = connect(); cur = con.cursor()
    cur.execute("SELECT user_id, amount, created_at FROM payments ORDER BY id DESC LIMIT 10")
    pays = cur.fetchall()
    con.close()
    
    if not pays: return await update.callback_query.message.reply_text("To'lovlar tarixi bo'sh.")
    
    text = "💳 **OXIRGI TO'LOVLAR:**\n\n"
    for p in pays: text += f"👤 ID: `{p[0]}` | 💰 {p[1]} | 🗓 {p[2]}\n"
    
    await update.callback_query.message.reply_text(text, parse_mode="Markdown")

# ------------- VOUCHERS -------------
async def vo_start(update, context):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🎟 Yangi vucher kodi yuboring (masalan: PREMIUM2024):")
    return VO_CODE

async def vo_code(update, context):
    context.user_data['vo_code'] = update.message.text.strip().upper()
    await update.message.reply_text("Necha kunlik VIP? (Raqam yuboring, masalan: 30) yoki agar faqat chegirma bo'lsa '0' deng:")
    return VO_DAYS

async def vo_days(update, context):
    if not update.message.text.isdigit(): return await update.message.reply_text("Faqat raqam!")
    context.user_data['vo_days'] = int(update.message.text)
    await update.message.reply_text("Chegirma foizi (masalan 20, agar chegirma yo'q bo'lsa 0 deng):")
    return VO_DISCOUNT

async def vo_discount(update, context):
    if not update.message.text.isdigit(): return await update.message.reply_text("Faqat raqam!")
    context.user_data['vo_discount'] = int(update.message.text)
    await update.message.reply_text("Maksimal foydalanishlar soni (masalan: 100):")
    return VO_USES

async def vo_uses(update, context):
    if not update.message.text.isdigit(): return await update.message.reply_text("Faqat raqam!")
    uses = int(update.message.text)
    
    days = context.user_data['vo_days']
    discount = context.user_data['vo_discount']
    code = context.user_data['vo_code']
    
    con = connect(); cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO vouchers (code, duration_days, discount_percent, max_uses) VALUES (?, ?, ?, ?)", 
                (code, days, discount, uses))
    con.commit(); con.close()
    
    await update.message.reply_text(f"✅ Vucher yaratildi: `{code}`\nKun: {days}\nChegirma: {discount}%\nUrinishlar: {uses}", parse_mode="Markdown")
    return ConversationHandler.END

# ------------- DIRECT MSG -------------
async def dm_start(update, context):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("✉️ Kimga xabar yubormoqchisiz? User ID sini yuboring:")
    return DM_UID

async def dm_uid(update, context):
    u_id = update.message.text.strip()
    if not u_id.isdigit(): return await update.message.reply_text("Noto'g'ri ID:")
    context.user_data['dm_target'] = int(u_id)
    await update.message.reply_text("Xabar matnini yozing:")
    return DM_TEXT

async def dm_text(update, context):
    text = update.message.text
    target = context.user_data['dm_target']
    
    try:
        await context.bot.send_message(chat_id=target, text=f"🔔 **ADMIN XABARI:**\n\n{text}", parse_mode="Markdown")
        await update.message.reply_text("✅ Xabar yuborildi.")
    except Exception as e:
        await update.message.reply_text(f"❌ Xatolik: {e}")
    
    return ConversationHandler.END

def get_voucher_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(vo_start, pattern="^vouchers_menu$")],
        states={
            VO_CODE: [MessageHandler(filters.TEXT & ~(filters.COMMAND), vo_code)],
            VO_DAYS: [MessageHandler(filters.TEXT & ~(filters.COMMAND), vo_days)],
            VO_DISCOUNT: [MessageHandler(filters.TEXT & ~(filters.COMMAND), vo_discount)],
            VO_USES: [MessageHandler(filters.TEXT & ~(filters.COMMAND), vo_uses)],
        },
        fallbacks=[CommandHandler("cancel", cancel_xtra)]
    )

def get_dm_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(dm_start, pattern="^direct_msg$")],
        states={
            DM_UID: [MessageHandler(filters.TEXT & ~(filters.COMMAND), dm_uid)],
            DM_TEXT: [MessageHandler(filters.TEXT & ~(filters.COMMAND), dm_text)],
        },
        fallbacks=[CommandHandler("cancel", cancel_xtra)]
    )

def get_xtra_callbacks():
    return [
        CallbackQueryHandler(pay_history, pattern="^pay_history$"),
    ]
# ------------- TEXT EDITOR -------------
async def et_start_entry(update, context):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🆕 Yangi Start (Salomlashish) matnini yuboring (Markdown formatida mumkin):")
    return ET_START

async def et_start_recv(update, context):
    new_text = update.message.text
    con = connect(); cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO sys_settings (key, value) VALUES ('start_text', ?)", (new_text,))
    con.commit(); con.close()
    await update.message.reply_text("✅ Start xabari muvaffaqiyatli saqlandi!")
    return ConversationHandler.END

# ------------- ADMIN MGMT -------------
async def am_start_entry(update, context):
    await update.callback_query.answer()
    con = connect(); cur = con.cursor()
    cur.execute("SELECT user_id, role FROM admins")
    admins = cur.fetchall()
    con.close()
    
    text = "👮‍♂️ **Jori Adminlar:**\n\n"
    kb = []
    for a in admins:
        text += f"- `{a[0]}` ({a[1]})\n"
        kb.append([InlineKeyboardButton(f"🗑 {a[0]} ni o'chirish", callback_data=f"del_adm:{a[0]}")])
    
    kb.append([InlineKeyboardButton("➕ Admin qo'shish", callback_data="add_adm_prompt")])
    kb.append([InlineKeyboardButton("🔙", callback_data="sys_settings")])
    
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_adm_prompt(update, context):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Admin qilmoqchi bo'lgan foydalanuvchi ID sini yuboring:")
    return AM_UID

async def add_adm_recv(update, context):
    u_id = update.message.text.strip()
    if not u_id.isdigit(): return await update.message.reply_text("ID raqam yuboring:")
    
    con = connect(); cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO admins (user_id, role) VALUES (?, 'admin')", (int(u_id),))
    con.commit(); con.close()
    
    await update.message.reply_text(f"✅ {u_id} muvaffaqiyatli admin bo'ldi!")
    return ConversationHandler.END

async def del_adm(update, context):
    u_id = int(update.callback_query.data.split(":")[1])
    if str(u_id) == str(SUPERADMIN_ID): return await update.callback_query.answer("Superadminni o'chirib bo'lmaydi!", show_alert=True)
    
    con = connect(); cur = con.cursor()
    cur.execute("DELETE FROM admins WHERE user_id=?", (u_id,))
    con.commit(); con.close()
    
    await update.callback_query.answer("Admin olib tashlandi.", show_alert=True)
    return await am_start_entry(update, context)

def get_text_edit_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(et_start_entry, pattern="^edit_start_text$")],
        states={
            ET_START: [MessageHandler(filters.TEXT & ~(filters.COMMAND), et_start_recv)],
        },
        fallbacks=[CommandHandler("cancel", cancel_xtra)]
    )

def get_admin_mgmt_xtra_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(add_adm_prompt, pattern="^add_adm_prompt$")],
        states={
            AM_UID: [MessageHandler(filters.TEXT & ~(filters.COMMAND), add_adm_recv)],
        },
        fallbacks=[CommandHandler("cancel", cancel_xtra)]
    )

def get_xtra_callbacks_updated():
    return [
        CallbackQueryHandler(pay_history, pattern="^pay_history$"),
        CallbackQueryHandler(am_start_entry, pattern="^admin_mgmt_menu$"),
        CallbackQueryHandler(del_adm, pattern="^del_adm:"),
        CallbackQueryHandler(manage_post_channel, pattern="^manage_post_channel$"),
        CallbackQueryHandler(set_pchan_direct, pattern="^set_pchan_direct:"),
        CallbackQueryHandler(clear_pchan, pattern="^clear_pchan$"),
    ]
