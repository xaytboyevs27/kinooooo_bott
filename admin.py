from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from db import connect
from utils import is_admin, logger

(
    # Add Movie States
    AM_CODE, AM_TITLE, AM_DESC, AM_GENRE, AM_QUALITY, AM_FILE, AM_ASK_POST, AM_POST_PHOTO, AM_POST_CHANNEL,
    # Add Serial States
    AS_CODE, AS_TITLE, AS_DESC,
    # Add Episode States
    AE_CODE, AE_SEASON, AE_NUM, AE_FILE,
    # User Look-up
    AD_LOOKUP
) = range(17)

async def log_admin_action(admin_id, action):
    try:
        con = connect()
        cur = con.cursor()
        cur.execute("INSERT INTO admin_logs (admin_id, action) VALUES (?, ?)", (admin_id, action))
        con.commit()
        con.close()
        logger.info(f"Admin {admin_id}: {action}")
    except Exception as e:
        logger.error(f"log_admin_action failed: {e}")

# -------------- ADMIN PANEL CORE --------------
def _admin_main_kb():
    con = connect(); cur = con.cursor()
    cur.execute("SELECT value FROM sys_settings WHERE key='maintenance_mode'")
    m_res = cur.fetchone()
    con.close()
    m_status = "🔴 O'CHIK" if not m_res or m_res[0] == 'off' else "🟢 YOQUV"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Umumiy Statistika", callback_data="stats"), InlineKeyboardButton("👥 Userlar", callback_data="admin_users")],
        [InlineKeyboardButton("💰 Moliyaviy Dashboard", callback_data="finance_stats"), InlineKeyboardButton("🔍 User Qidirish", callback_data="user_lookup")],
        [InlineKeyboardButton("🎬 Kino Qo'shish", callback_data="add_movie"), InlineKeyboardButton("📺 Serial Qo'shish", callback_data="add_serial")],
        [InlineKeyboardButton("➕ Qism Qo'shish", callback_data="add_episode"), InlineKeyboardButton("📝 Tahrirlash", callback_data="edit_media_menu")],
        [InlineKeyboardButton("📣 Broadcast", callback_data="broadcast"), InlineKeyboardButton("⚙️ Sozlamalar", callback_data="admin_system")],
        [InlineKeyboardButton(f"🛠 Maintenance: {m_status}", callback_data="toggle_maintenance")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_admin")]
    ])


def _admin_users_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 User Qidirish", callback_data="user_lookup"), InlineKeyboardButton("💳 VIP boshqarish", callback_data="vip_manage")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_main")]
    ])


def _admin_system_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Tizim sozlamalari", callback_data="sys_settings"), InlineKeyboardButton("📁 Baza zaxirasi", callback_data="manual_backup")],
        [InlineKeyboardButton("📉 CSV export", callback_data="export_csv"), InlineKeyboardButton("📢 Reklamalar", callback_data="ads_menu")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_main")]
    ])


async def _show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, menu_name: str = "main"):
    kb_map = {
        "main": _admin_main_kb(),
        "users": _admin_users_kb(),
        "system": _admin_system_kb(),
    }
    title_map = {
        "main": "👮‍♂️ ADMIN PANEL",
        "users": "👥 USER MANAGEMENT",
        "system": "⚙️ SYSTEM MENU",
    }
    kb = kb_map.get(menu_name, _admin_main_kb())
    title = title_map.get(menu_name, "👮‍♂️ ADMIN PANEL")

    if update.callback_query:
        try:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(title, reply_markup=kb)
            return
        except Exception:
            pass

    target = update.message or (update.callback_query.message if update.callback_query else None)
    if target:
        await target.reply_text(title, reply_markup=kb)
        return

    if update.callback_query:
        await update.callback_query.message.reply_text(title, reply_markup=kb)


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    return await _show_admin_menu(update, context, "main")


async def admin_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    return await _show_admin_menu(update, context, "users")


async def admin_system_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    return await _show_admin_menu(update, context, "system")


async def admin_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    data = update.callback_query.data if update.callback_query else ""
    if not data:
        return

    handler_map = {
        "admin_main": admin_panel,
        "admin_users": admin_users_menu,
        "admin_system": admin_system_menu,
        "stats": stats,
        "finance_stats": finance_stats,
        "toggle_maintenance": toggle_maintenance,
        "user_lookup": lookup_start,
    }

    handler = handler_map.get(data)
    if handler:
        return await handler(update, context)

    if data == "cancel_admin":
        return await cancel_admin(update, context)


async def cancel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.delete()
    return ConversationHandler.END

async def stats(update, context):
    con = connect()
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM users WHERE last_seen >= date('now')")
    today_users = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM users WHERE vip_until > datetime('now')")
    vip_users = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM media WHERE type='movie'")
    movies = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM media WHERE type='serial'")
    serials = cur.fetchone()[0]
    
    # Top Searches
    cur.execute("SELECT query, COUNT(*) as c FROM search_logs GROUP BY query ORDER BY c DESC LIMIT 5")
    top_searches = cur.fetchall()
    search_text = "\n\n🔍 Eng ko'p qidirilganlar:\n" + "\n".join([f"- {s[0]} ({s[1]} marta)" for s in top_searches]) if top_searches else ""

    cur.execute("SELECT COUNT(*) FROM episodes")
    total_episodes = cur.fetchone()[0]
    
    con.close()

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        f"📊 **STATISTIKA**\n\n"
        f"👥 Foydalanuvchilar: {users}\n"
        f"🆕 Bugun: {today_users}\n"
        f"💳 VIP: {vip_users}\n\n"
        f"🎬 Kinolar: {movies}\n"
        f"📺 Seriallar: {serials}\n"
        f"🎞 Qismlar: {total_episodes}" + search_text,
        parse_mode="Markdown"
    )

async def finance_stats(update, context):
    con = connect()
    cur = con.cursor()
    
    cur.execute("SELECT COUNT(*) FROM users WHERE vip_until > datetime('now')")
    vip_active = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM ads WHERE is_active=1")
    active_ads = cur.fetchone()[0]
    
    cur.execute("SELECT SUM(views) FROM ads")
    total_ad_views = cur.fetchone()[0] or 0
    
    cur.execute("SELECT COUNT(*) FROM force_sub_channels WHERE price > 0")
    paid_channels = cur.fetchone()[0]
    
    cur.execute("SELECT SUM(price) FROM force_sub_channels")
    total_channel_revenue = cur.fetchone()[0] or 0
    
    con.close()
    
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        f"💰 **MOLIYAVIY DASHBOARD**\n\n"
        f"👑 Aktiv VIP obunachilar: {vip_active} ta (Taxminiy foyda: {vip_active * 15000} so'm/oy)\n\n"
        f"📢 Aktiv reklamalar: {active_ads} ta\n"
        f"👁 Reklama ko'rishlar soni: {total_ad_views} marta\n\n"
        f"🔗 Pullik majburiy obuna kanallar: {paid_channels} ta\n"
        f"💵 Kanallardan tushgan summa (taxminiy): {total_channel_revenue} so'm\n",
        parse_mode="Markdown"
    )

async def toggle_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    con = connect(); cur = con.cursor()
    cur.execute("SELECT value FROM sys_settings WHERE key='maintenance_mode'")
    res = cur.fetchone()
    new_val = 'off' if res and res[0] == 'on' else 'on'
    cur.execute("INSERT OR REPLACE INTO sys_settings (key, value) VALUES ('maintenance_mode', ?)", (new_val,))
    con.commit(); con.close()
    await update.callback_query.answer(f"Texnik ishlar holati: {new_val.upper()}", show_alert=True)
    return await admin_panel(update, context)

# -------------- USER LOOKUP --------------
async def lookup_start(update, context):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🔍 Foydalanuvchi ID sini yuboring:")
    return AD_LOOKUP

async def lookup_user(update, context):
    u_id = update.message.text.strip()
    if not u_id.isdigit(): return await update.message.reply_text("Faqat ID raqam yuboring:")
    
    con = connect(); cur = con.cursor()
    cur.execute("SELECT user_id, username, last_seen, vip_until, referred_count, role FROM users WHERE user_id=?", (u_id,))
    u = cur.fetchone()
    con.close()
    
    if not u: return await update.message.reply_text("Bunday foydalanuvchi topilmadi.")
    
    text = (
        f"👤 **Foydalanuvchi ma'lumotlari:**\n"
        f"ID: `{u[0]}`\n"
        f"Username: @{u[1] or 'yoq'}\n"
        f"Oxirgi faollik: {u[2]}\n"
        f"VIP holati: {'✅ Aktiv' if u[3] else '❌ Aktiv emas'}\n"
        f"VIP gacha: {u[3] or '-'}\n"
        f"Taklif qilgan do'stlari: {u[4] or 0}\n"
        f"Roli: {u[5]}"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ 30 kun VIP berish", callback_data=f"give_vip:{u[0]}:30"), InlineKeyboardButton("❌ VIPni olish", callback_data=f"take_vip:{u[0]}")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_main")]
    ])
    
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    return ConversationHandler.END

async def manage_vip(update, context):
    query = update.callback_query
    data = query.data.split(":")
    u_id = int(data[1])
    con = connect(); cur = con.cursor()
    
    if data[0] == "give_vip":
        import datetime
        days = int(data[2])
        cur.execute("SELECT vip_until FROM users WHERE user_id=?", (u_id,))
        res = cur.fetchone()
        now = datetime.datetime.now()
        base = datetime.datetime.strptime(res[0], "%Y-%m-%d %H:%M:%S") if res and res[0] and datetime.datetime.strptime(res[0], "%Y-%m-%d %H:%M:%S") > now else now
        new_vip = (base + datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("UPDATE users SET vip_until=? WHERE user_id=?", (new_vip, u_id))
        await query.answer(f"✅ Userga {days} kunlik VIP berildi.", show_alert=True)
    else:
        cur.execute("UPDATE users SET vip_until=NULL WHERE user_id=?", (u_id,))
        await query.answer("❌ VIP holati olib tashlandi.", show_alert=True)
        
    con.commit(); con.close()
    return await admin_panel(update, context)

# -------------- CANCEL CONV --------------
async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Jarayon bekor qilindi.")
    return ConversationHandler.END


# -------------- ADD MOVIE --------------
async def am_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("🎬 Kino qo'shish:\nKino kodi (raqam yoki matn) yuboring:")
    return AM_CODE

async def am_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id FROM media WHERE code=?", (code,))
    if cur.fetchone():
        await update.message.reply_text("❌ Bu kod band. Boshqa kod yuboring yoki /cancel bosing.")
        con.close()
        return AM_CODE
    con.close()
    
    context.user_data['temp_code'] = code
    await update.message.reply_text("Kino nomini yuboring:")
    return AM_TITLE

async def am_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_title'] = update.message.text
    await update.message.reply_text("Kino tavsifi (description) ni yuboring:")
    return AM_DESC

async def am_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_desc'] = update.message.text.strip()
    await update.message.reply_text(
        "🎭 **Kino janrini kiriting:**\n\n_(Masalan: Komedik, Jangari, Fantastika yoki /skip deb yuboring)_",
        parse_mode="Markdown"
    )
    return AM_GENRE

async def am_genre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data['temp_genre'] = "" if text == "/skip" else text
    await update.message.reply_text(
        "🎥 **Kino sifatini kiriting:**\n\n_(Masalan: Full HD, 720p, 4K yoki /skip yuboring)_",
        parse_mode="Markdown"
    )
    return AM_QUALITY

async def am_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data['temp_quality'] = "Full HD" if text == "/skip" else text
    await update.message.reply_text("📹 **Endi kino video faylini yuboring:**", parse_mode="Markdown")
    return AM_FILE

async def am_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.video and not update.message.document:
        await update.message.reply_text("Iltimos, video turidagi fayl yuboring!")
        return AM_FILE
        
    file_id = update.message.video.file_id if update.message.video else update.message.document.file_id
    code = context.user_data['temp_code']
    title = context.user_data['temp_title']
    desc = context.user_data['temp_desc']
    genre = context.user_data.get('temp_genre', '')
    
    con = connect()
    cur = con.cursor()
    cur.execute("INSERT INTO media (code, type, title, description, file_id, genres) VALUES (?, ?, ?, ?, ?, ?)",
                (code, 'movie', title, desc, file_id, genre))
    con.commit()
    
    # Backup channel
    cur.execute("SELECT value FROM sys_settings WHERE key='backup_channel'")
    b_chan = cur.fetchone()
    if b_chan and b_chan[0]:
        try: await context.bot.send_video(chat_id=b_chan[0], video=file_id, caption=f"🎬 {title}\n(Kod: {code})\n{desc}")
        except:
            try: await context.bot.send_document(chat_id=b_chan[0], document=file_id, caption=f"🎬 {title}\n(Kod: {code})\n{desc}")
            except Exception as e:
                logger.warning(f"Backup channel send failed for movie {code}: {e}")
    con.close()
    
    context.user_data['temp_file_id'] = file_id
    
    # Kanalga avto-post yuborish haqida so'rash
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT value FROM sys_settings WHERE key='post_channel'")
    p_row = cur.fetchone()
    p_chan = p_row[0] if p_row and p_row[0] else None
    chan_info = ""
    if p_chan:
        cur.execute("SELECT title FROM force_sub_channels WHERE chat_id=?", (p_chan,))
        ch_title = cur.fetchone()
        chan_info = f"\n📢 Mo'ljallangan kanal: <b>{ch_title[0] if ch_title else p_chan}</b>"
    con.close()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Ha, post yuborish", callback_data="am_post_yes")],
        [InlineKeyboardButton("🔄 Kanalni tanlash/o'zgartirish", callback_data="am_post_choose_channel")],
        [InlineKeyboardButton("❌ Yo'q, kerak emas", callback_data="am_post_no")]
    ])
    await update.message.reply_text(
        f"📢 <b>Ushbu kino kanalga avto-post qilinsinmi?</b>{chan_info}\n\n"
        "Kanalga afisha rasmi, ma'lumotlar (janr, sifat, kod) va <b>[🎬 Kinoni olish]</b> tugmasi bilan post yuboriladi.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    return AM_ASK_POST

async def am_ask_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import html
    query = update.callback_query
    await query.answer()
    data = query.data
    code = context.user_data.get('temp_code')
    title = context.user_data.get('temp_title')
    
    if data == "am_post_no":
        await query.edit_message_text(
            f"✅ <b>Kino muvaffaqiyatli saqlandi!</b>\n\n🎬 Nomi: <b>{html.escape(title)}</b>\n🔢 Kodi: <code>{html.escape(str(code))}</code>",
            parse_mode="HTML"
        )
        context.user_data.clear()
        return ConversationHandler.END
        
    if data == "am_post_choose_channel":
        con = connect()
        cur = con.cursor()
        cur.execute("SELECT chat_id, title FROM force_sub_channels")
        chans = cur.fetchall()
        con.close()
        
        if chans:
            kb_list = [[InlineKeyboardButton(f"📢 {ch[1]}", callback_data=f"am_chan:{ch[0]}")] for ch in chans]
            kb_list.append([InlineKeyboardButton("✏️ Boshqa kanal ID sini kiritish", callback_data="am_chan_manual")])
            await query.edit_message_text("📢 <b>Qaysi kanalga post yuborilsin?</b>\nKanalni tanlang:", reply_markup=InlineKeyboardMarkup(kb_list), parse_mode="HTML")
            return AM_POST_CHANNEL
        else:
            await query.edit_message_text("📢 <b>Post yuborish uchun kanal ID sini yuboring (-100... bilan):</b>", parse_mode="HTML")
            return AM_POST_CHANNEL

    if data == "am_post_yes":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭ O'tkazib yuborish (Rasmsiz)", callback_data="am_skip_photo")]
        ])
        await query.edit_message_text(
            "📸 <b>Post uchun rasm (afisha) yuboring:</b>\n\n"
            "<i>(Kanalda post chiroyli chiqishi uchun afisha rasmini yuboring. Agar rasmsiz video orqali post bo'lishini xohlasangiz, 'O'tkazib yuborish' tugmasini bosing)</i>",
            reply_markup=kb,
            parse_mode="HTML"
        )
        return AM_POST_PHOTO

async def am_post_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Iltimos, rasm yuboring yoki /cancel bosing!")
        return AM_POST_PHOTO
        
    photo_id = update.message.photo[-1].file_id
    context.user_data['temp_post_photo'] = photo_id
    return await _do_publish_movie_post(update, context)

async def am_skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['temp_post_photo'] = None
    return await _do_publish_movie_post(update, context)

async def _do_publish_movie_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Agar tanlangan kanal bo'lsa
    channel_id = context.user_data.get('temp_post_channel')
    if channel_id:
        return await _send_channel_post_final(update, context, channel_id)

    con = connect()
    cur = con.cursor()
    cur.execute("SELECT value FROM sys_settings WHERE key='post_channel'")
    p_chan_row = cur.fetchone()
    
    if p_chan_row and p_chan_row[0]:
        channel_id = p_chan_row[0]
        con.close()
        return await _send_channel_post_final(update, context, channel_id)
        
    cur.execute("SELECT chat_id, title FROM force_sub_channels")
    chans = cur.fetchall()
    con.close()
    
    if chans:
        kb_list = [[InlineKeyboardButton(f"📢 {ch[1]}", callback_data=f"am_chan:{ch[0]}")] for ch in chans]
        kb_list.append([InlineKeyboardButton("✏️ Boshqa kanal ID sini kiritish", callback_data="am_chan_manual")])
        msg = update.message or update.callback_query.message
        await msg.reply_text("📢 <b>Qaysi kanalga post yuborilsin?</b>\nKanalni tanlang:", reply_markup=InlineKeyboardMarkup(kb_list), parse_mode="HTML")
        return AM_POST_CHANNEL
    else:
        msg = update.message or update.callback_query.message
        await msg.reply_text("📢 <b>Post yuborish uchun kanal ID sini yuboring (-100... bilan):</b>", parse_mode="HTML")
        return AM_POST_CHANNEL

async def am_select_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "am_chan_manual":
        await query.edit_message_text("📢 <b>Kanal ID sini yuboring (-100 bilan boshlanadigan):</b>", parse_mode="HTML")
        return AM_POST_CHANNEL
        
    channel_id = data.split(":", 1)[1]
    con = connect()
    cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO sys_settings (key, value) VALUES ('post_channel', ?)", (channel_id,))
    con.commit()
    con.close()
    
    context.user_data['temp_post_channel'] = channel_id
    if 'temp_post_photo' in context.user_data:
        return await _send_channel_post_final(update, context, channel_id)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ O'tkazib yuborish (Rasmsiz)", callback_data="am_skip_photo")]
    ])
    await query.edit_message_text(
        "✅ Kanal tanlandi!\n\n📸 <b>Endi post uchun rasm (afisha) yuboring:</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    return AM_POST_PHOTO

async def am_manual_channel_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel_id = update.message.text.strip()
    con = connect()
    cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO sys_settings (key, value) VALUES ('post_channel', ?)", (channel_id,))
    con.commit()
    con.close()
    
    context.user_data['temp_post_channel'] = channel_id
    if 'temp_post_photo' in context.user_data:
        return await _send_channel_post_final(update, context, channel_id)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ O'tkazib yuborish (Rasmsiz)", callback_data="am_skip_photo")]
    ])
    await update.message.reply_text(
        "✅ Kanal ID saqlandi!\n\n📸 <b>Endi post uchun rasm (afisha) yuboring:</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    return AM_POST_PHOTO

async def _send_channel_post_final(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: str):
    import html
    code = context.user_data.get('temp_code')
    title = context.user_data.get('temp_title', '')
    desc = context.user_data.get('temp_desc', '')
    genre = context.user_data.get('temp_genre', '')
    quality = context.user_data.get('temp_quality', 'Full HD')
    file_id = context.user_data.get('temp_file_id')
    photo_id = context.user_data.get('temp_post_photo')
    
    # Poster rasmini media bazasiga ham saqlaymiz
    if photo_id:
        try:
            con = connect()
            cur = con.cursor()
            cur.execute("UPDATE media SET poster_file_id=? WHERE code=?", (photo_id, code))
            con.commit()
            con.close()
        except Exception as e:
            logger.warning(f"Could not update poster_file_id for {code}: {e}")
            
    bot_obj = await context.bot.get_me()
    bot_username = bot_obj.username
    
    # Rasmdagidek toza va aniq HTML formatlash
    t_esc = html.escape(title)
    d_esc = html.escape(desc)
    g_esc = html.escape(genre)
    q_esc = html.escape(quality)
    c_esc = html.escape(str(code))
    
    caption = f"🎬 <b>{t_esc}</b>\n\n"
    if d_esc:
        caption += f"📝 {d_esc}\n\n"
    if g_esc:
        caption += f"🎭 Janr: {g_esc}\n"
    if q_esc:
        caption += f"🎥 Sifat: {q_esc}\n"
    if g_esc or q_esc:
        caption += "\n"
    caption += f"🔢 Kod: {c_esc}\n\n"
    caption += "👇 Kinoni olish uchun botga o'ting:"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Kinoni olish", url=f"https://t.me/{bot_username}?start={code}")]
    ])
    
    sent_ok = False
    err_str = ""
    if photo_id:
        try:
            await context.bot.send_photo(chat_id=channel_id, photo=photo_id, caption=caption, reply_markup=kb, parse_mode="HTML")
            sent_ok = True
        except Exception as e:
            logger.warning(f"send_photo HTML failed: {e}")
            try:
                raw_cap = (
                    f"🎬 {title}\n\n"
                    + (f"📝 {desc}\n\n" if desc else "")
                    + (f"🎭 Janr: {genre}\n" if genre else "")
                    + (f"🎥 Sifat: {quality}\n\n" if quality else ("\n" if genre else ""))
                    + f"🔢 Kod: {code}\n\n"
                    + "👇 Kinoni olish uchun botga o'ting:"
                )
                await context.bot.send_photo(chat_id=channel_id, photo=photo_id, caption=raw_cap, reply_markup=kb)
                sent_ok = True
            except Exception as e2:
                err_str = str(e2)
                logger.error(f"Failed to send photo post to channel {channel_id}: {e2}")
    else:
        try:
            await context.bot.send_video(chat_id=channel_id, video=file_id, caption=caption, reply_markup=kb, parse_mode="HTML")
            sent_ok = True
        except Exception as e:
            try:
                raw_cap = (
                    f"🎬 {title}\n\n"
                    + (f"📝 {desc}\n\n" if desc else "")
                    + (f"🎭 Janr: {genre}\n" if genre else "")
                    + (f"🎥 Sifat: {quality}\n\n" if quality else ("\n" if genre else ""))
                    + f"🔢 Kod: {code}\n\n"
                    + "👇 Kinoni olish uchun botga o'ting:"
                )
                await context.bot.send_video(chat_id=channel_id, video=file_id, caption=raw_cap, reply_markup=kb)
                sent_ok = True
            except Exception as e2:
                err_str = str(e2)
                logger.error(f"Failed to send video post to channel {channel_id}: {e2}")
                
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if sent_ok:
        text_resp = f"✅ <b>Kino saqlandi va kanalga avto-post yuborildi!</b>\n\n🎬 Nomi: <b>{html.escape(title)}</b>\n🔢 Kodi: <code>{html.escape(str(code))}</code>"
    else:
        text_resp = f"✅ <b>Kino saqlandi!</b>\n⚠️ <i>Lekin kanalga post yuborishda xatolik bo'ldi: {html.escape(err_str)}</i>\n\n🎬 Nomi: <b>{html.escape(title)}</b>\n🔢 Kodi: <code>{html.escape(str(code))}</code>"
        
    if update.callback_query:
        await update.callback_query.edit_message_text(text_resp, parse_mode="HTML")
    elif msg:
        await msg.reply_text(text_resp, parse_mode="HTML")
        
    context.user_data.clear()
    return ConversationHandler.END


# -------------- ADD SERIAL --------------
async def as_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("📺 Serial qo'shish:\nSerial kodi (raqam yoki matn) yuboring:")
    return AS_CODE

async def as_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id FROM media WHERE code=?", (code,))
    if cur.fetchone():
        await update.message.reply_text("❌ Bu kod band. Boshqa kod yuboring yoki /cancel bosing.")
        con.close()
        return AS_CODE
    con.close()
    
    context.user_data['temp_code'] = code
    await update.message.reply_text("Serial nomini yuboring:")
    return AS_TITLE

async def as_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_title'] = update.message.text
    await update.message.reply_text("Serial tavsifini yuboring:")
    return AS_DESC

async def as_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text
    code = context.user_data['temp_code']
    title = context.user_data['temp_title']
    
    con = connect()
    cur = con.cursor()
    # file_id is NULL for serials
    cur.execute("INSERT INTO media (code, type, title, description) VALUES (?, ?, ?, ?)",
                (code, 'serial', title, desc))
    con.commit()
    con.close()
    
    await update.message.reply_text(f"✅ Serial muvaffaqiyatli saqlandi! Endi qismlarni qo'shishingiz mumkin.\nKodi: {code}")
    context.user_data.clear()
    return ConversationHandler.END


# -------------- ADD EPISODE --------------
async def ae_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("➕ Qism qo'shish:\nQaysi serialga qism qo'shmoqchisiz? Serial kodini yuboring:")
    return AE_CODE

async def ae_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id, title, type FROM media WHERE code=?", (code,))
    media = cur.fetchone()
    con.close()
    
    if not media or media[2] != 'serial':
        await update.message.reply_text("❌ Bunday serial topilmadi. Boshqa kod yuboring yoki /cancel bosing.")
        return AE_CODE
        
    context.user_data['target_media_id'] = media[0]
    await update.message.reply_text(f"Serial: {media[1]}\nNechanchi fasl? (Faqat raqam yuboring, masalan: 1):")
    return AE_SEASON

async def ae_season(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
        await update.message.reply_text("❌ Iltimos, faqat raqam yozing:")
        return AE_SEASON
        
    season_num = int(update.message.text)
    media_id = context.user_data['target_media_id']
    
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id FROM seasons WHERE media_id=? AND season_number=?", (media_id, season_num))
    season = cur.fetchone()
    
    if not season:
        cur.execute("INSERT INTO seasons (media_id, season_number) VALUES (?, ?)", (media_id, season_num))
        season_id = cur.lastrowid
        con.commit()
        await update.message.reply_text(f"✅ {season_num}-Fasl yaratildi!")
    else:
        season_id = season[0]
        
    con.close()
    
    context.user_data['target_season_id'] = season_id
    await update.message.reply_text("Nechanchi qism? (Faqat raqam yuboring, masalan: 5):")
    return AE_NUM

async def ae_num(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
        await update.message.reply_text("❌ Iltimos, faqat raqam yozing:")
        return AE_NUM
        
    context.user_data['temp_ep_num'] = int(update.message.text)
    await update.message.reply_text("Video faylni yuboring:")
    return AE_FILE

async def ae_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.video and not update.message.document:
        await update.message.reply_text("Iltimos, video turidagi fayl yuboring!")
        return AE_FILE
        
    file_id = update.message.video.file_id if update.message.video else update.message.document.file_id
    season_id = context.user_data['target_season_id']
    ep_num = context.user_data['temp_ep_num']
    
    con = connect()
    cur = con.cursor()
    # Overwrite if exists?
    cur.execute("SELECT id FROM episodes WHERE season_id=? AND episode_number=?", (season_id, ep_num))
    if cur.fetchone():
        cur.execute("UPDATE episodes SET file_id=? WHERE season_id=? AND episode_number=?", (file_id, season_id, ep_num))
    else:
        cur.execute("INSERT INTO episodes (season_id, episode_number, file_id) VALUES (?, ?, ?)",
                    (season_id, ep_num, file_id))
    con.commit()
    
    cur.execute("SELECT value FROM sys_settings WHERE key='backup_channel'")
    b_chan = cur.fetchone()
    if b_chan and b_chan[0]:
        cur.execute("SELECT m.code, m.title, s.season_number FROM media m JOIN seasons s ON m.id=s.media_id WHERE s.id=?", (season_id,))
        m_data = cur.fetchone()
        if m_data:
            cap = f"📺 {m_data[1]}\n(Kod: {m_data[0]})\n{m_data[2]}-Fasl, {ep_num}-Qism"
            try: await context.bot.send_video(chat_id=b_chan[0], video=file_id, caption=cap)
            except:
                try: await context.bot.send_document(chat_id=b_chan[0], document=file_id, caption=cap)
                except Exception as e:
                    logger.warning(f"Backup channel send failed for episode S{m_data[2]}E{ep_num}: {e}")

    # Auto POST Serial Episode
    cur.execute("SELECT value FROM sys_settings WHERE key='post_channel'")
    p_chan = cur.fetchone()
    if p_chan and p_chan[0]:
        cur.execute("SELECT m.code, m.title, s.season_number FROM media m JOIN seasons s ON m.id=s.media_id WHERE s.id=?", (season_id,))
        m_d = cur.fetchone()
        if m_d:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🍿 Botda ko'rish", url=f"https://t.me/{(await context.bot.get_me()).username}?start={m_d[0]}")]])
            cap_p = f"📺 **YANGI QISM:** {m_d[1]}\n\n🗓 {m_d[2]}-Fasl, {ep_num}-Qism\n\n🆔 Kod: `{m_d[0]}`"
            try: await context.bot.send_video(chat_id=p_chan[0], video=file_id, caption=cap_p, reply_markup=kb, parse_mode="Markdown")
            except:
                try: await context.bot.send_document(chat_id=p_chan[0], document=file_id, caption=cap_p, reply_markup=kb, parse_mode="Markdown")
                except Exception as e:
                    logger.warning(f"Post channel send failed for episode S{m_d[2]}E{ep_num}: {e}")

    con.close()
    
    await update.message.reply_text(f"✅ Qism muvaffaqiyatli saqlandi!\nKod orqali tekshirib ko'rishingiz mumkin.")
    context.user_data.clear()
    return ConversationHandler.END


def get_movie_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(am_start, pattern="^add_movie$")],
        states={
            AM_CODE: [MessageHandler(filters.TEXT & ~(filters.COMMAND), am_code)],
            AM_TITLE: [MessageHandler(filters.TEXT & ~(filters.COMMAND), am_title)],
            AM_DESC: [MessageHandler(filters.TEXT & ~(filters.COMMAND), am_desc)],
            AM_GENRE: [MessageHandler(filters.TEXT, am_genre)],
            AM_QUALITY: [MessageHandler(filters.TEXT, am_quality)],
            AM_FILE: [MessageHandler(filters.ALL & ~(filters.COMMAND), am_file)],
            AM_ASK_POST: [CallbackQueryHandler(am_ask_post_callback, pattern="^am_post_(yes|no|choose_channel)$")],
            AM_POST_PHOTO: [
                MessageHandler(filters.PHOTO, am_post_photo),
                CallbackQueryHandler(am_skip_photo, pattern="^am_skip_photo$")
            ],
            AM_POST_CHANNEL: [
                CallbackQueryHandler(am_select_channel_callback, pattern="^am_chan:"),
                CallbackQueryHandler(am_select_channel_callback, pattern="^am_chan_manual$"),
                MessageHandler(filters.TEXT & ~(filters.COMMAND), am_manual_channel_text)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)]
    )


def get_serial_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(as_start, pattern="^add_serial$")],
        states={
            AS_CODE: [MessageHandler(filters.TEXT & ~(filters.COMMAND), as_code)],
            AS_TITLE: [MessageHandler(filters.TEXT & ~(filters.COMMAND), as_title)],
            AS_DESC: [MessageHandler(filters.TEXT & ~(filters.COMMAND), as_desc)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)]
    )

def get_episode_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(ae_start, pattern="^add_episode$")],
        states={
            AE_CODE: [MessageHandler(filters.TEXT & ~(filters.COMMAND), ae_code)],
            AE_SEASON: [MessageHandler(filters.TEXT & ~(filters.COMMAND), ae_season)],
            AE_NUM: [MessageHandler(filters.TEXT & ~(filters.COMMAND), ae_num)],
            AE_FILE: [MessageHandler(filters.ALL & ~(filters.COMMAND), ae_file)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)]
    )

def get_admin_mgmt_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(lookup_start, pattern="^user_lookup$")],
        states={
            AD_LOOKUP: [MessageHandler(filters.TEXT & ~(filters.COMMAND), lookup_user)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)]
    )

def get_admin_callbacks():
    return [
        CallbackQueryHandler(admin_dispatch, pattern="^(admin_main|admin_users|admin_system|stats|finance_stats|toggle_maintenance|user_lookup|cancel_admin)$"),
    ]
