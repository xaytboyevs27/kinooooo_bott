from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes
from db import connect
from utils import check_rate, logger, get_text
import datetime
import os
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, SUPERADMIN_ID

def get_lang(user_id):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT language FROM users WHERE user_id=?", (user_id,))
    res = cur.fetchone()
    con.close()
    return res[0] if res and res[0] else 'uz'

PAGE_SIZE = 8


def _has_active_vip(user_id: int) -> bool:
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT vip_until FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    if not row or not row[0]:
        return False
    try:
        vip_until = datetime.datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        return vip_until > datetime.datetime.now()
    except (TypeError, ValueError):
        return False


# --- MIDDLEWARE / HELPERS ---
async def check_force_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if _has_active_vip(user_id):
        return True

    con = connect()
    cur = con.cursor()
    cur.execute("SELECT chat_id, invite_link, title FROM force_sub_channels")
    channels = cur.fetchall()
    con.close()

    unsubscribed = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=ch[0], user_id=user_id)
            if member.status in ['left', 'kicked']:
                unsubscribed.append(ch)
        except Exception as e:
            logger.warning(f"Force-sub check failed for channel {ch[0]}: {e}")

    if unsubscribed:
        lang = get_lang(user_id)
        kb = [[InlineKeyboardButton(f"🔔 {ch[2]}", url=ch[1])] for ch in unsubscribed]
        kb.append([InlineKeyboardButton(get_text(lang, 'subbed'), callback_data="check_sub")])
        msg = update.message or update.callback_query.message
        await msg.reply_text(get_text(lang, 'force_sub'), reply_markup=InlineKeyboardMarkup(kb))
        return False
    return True

async def check_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    from config import SUPERADMIN_ID
    if str(user_id) == str(SUPERADMIN_ID): return True

    con = connect()
    try:
        cur = con.cursor()
        cur.execute("SELECT role FROM admins WHERE user_id=?", (user_id,))
        is_admin_row = cur.fetchone()
        if is_admin_row: return True

        cur.execute("SELECT value FROM sys_settings WHERE key='maintenance_mode'")
        res = cur.fetchone()
        if res and res[0] == 'on':
            msg = update.message or update.callback_query.message
            await msg.reply_text("🛠 **TEXNIK ISHLAR**\n\nBotda hozirda texnik ishlar olib borilmoqda. Iltimos, birozdan so'ng qayta urinib ko'ring.", parse_mode="Markdown")
            return False
    finally:
        con.close()

    return True

# --- COMMANDS ---
async def set_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz")],
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
        [InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")]
    ])
    await update.message.reply_text("🌐 Tilni tanlang / Выберите язык / Choose a language:", reply_markup=kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await check_maintenance(update, context): return
    con = connect()
    cur = con.cursor()

    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user.id,))
    is_new = not cur.fetchone()

    if is_new:
        cur.execute("INSERT INTO users(user_id, username) VALUES(?,?)", (user.id, user.username))
        if context.args and context.args[0].startswith("ref_"):
            ref_str = context.args[0][4:]
            if ref_str.isdigit():
                ref_id = int(ref_str)
                if ref_id != user.id:
                    cur.execute("SELECT user_id, referred_count, vip_until FROM users WHERE user_id=?", (ref_id,))
                    r_data = cur.fetchone()
                    if r_data:
                        new_count = (r_data[1] or 0) + 1
                        cur.execute("UPDATE users SET referred_count=?, referrer_id=? WHERE user_id=?", (new_count, ref_id, user.id))
                        if new_count % 10 == 0:
                            now_dt = datetime.datetime.now()
                            base_time = datetime.datetime.strptime(r_data[2], "%Y-%m-%d %H:%M:%S") if r_data[2] and datetime.datetime.strptime(r_data[2], "%Y-%m-%d %H:%M:%S") > now_dt else now_dt
                            vip_time = base_time + datetime.timedelta(days=30)
                            cur.execute("UPDATE users SET vip_until=? WHERE user_id=?", (vip_time.strftime("%Y-%m-%d %H:%M:%S"), ref_id))
                            try:
                                await context.bot.send_message(chat_id=ref_id, text=f"🎉 Tabriklaymiz! Sizning taklifingiz bilan {new_count} kishi kirdi! \nSizga 1 Oylik (30 kunlik) VIP taqdim etildi!")
                            except Exception as e:
                                logger.warning(f"Could not notify referrer {ref_id}: {e}")

    con.commit()

    if not await check_force_sub(update, context):
        if context.args and not context.args[0].startswith("ref_"):
            context.user_data['pending_code'] = context.args[0].strip().upper()
        con.close()
        return

    # Kanal postidagi "Kinoni olish" tugmasi orqali kirilganda
    if context.args and not context.args[0].startswith("ref_"):
        code_arg = context.args[0].strip().upper()
        if await send_media_by_code(update, context, code_arg):
            con.close()
            return

    lang = get_lang(user.id)

    cur.execute("SELECT value FROM sys_settings WHERE key='start_text'")
    custom_start = cur.fetchone()
    con.close()

    greeting = custom_start[0] if custom_start and custom_start[0] else get_text(lang, 'greeting').format(name=user.first_name)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(lang, 'btn_search'), callback_data="cmd_search"), InlineKeyboardButton(get_text(lang, 'btn_serials'), callback_data="cmd_serials")],
        [InlineKeyboardButton(get_text(lang, 'btn_top'), callback_data="cmd_top"), InlineKeyboardButton(get_text(lang, 'btn_new'), callback_data="cmd_new")],
        [InlineKeyboardButton(get_text(lang, 'btn_rand'), callback_data="cmd_random"), InlineKeyboardButton(get_text(lang, 'btn_fav'), callback_data="cmd_my")],
        [InlineKeyboardButton(get_text(lang, 'btn_ai'), callback_data="cmd_ai"), InlineKeyboardButton(get_text(lang, 'btn_ref'), callback_data="cmd_ref")],
        [InlineKeyboardButton(get_text(lang, 'btn_vip'), callback_data="cmd_buy_vip"), InlineKeyboardButton("🎁 Kunlik Bonus", callback_data="cmd_daily_bonus")]
    ])

    await update.message.reply_text(greeting, reply_markup=kb, parse_mode="Markdown")

def _paginate(rows, page):
    page = max(1, int(page or 1))
    total = len(rows)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > total_pages:
        page = total_pages
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    return rows[start:end], page, total_pages, total

def _nav_kb(prefix, page, total_pages):
    row = []
    if page > 1:
        row.append(InlineKeyboardButton("◀️", callback_data=f"{prefix}:{page-1}"))
    else:
        row.append(InlineKeyboardButton("▪️", callback_data=f"{prefix}:noop"))
    row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data=f"{prefix}:noop"))
    if page < total_pages:
        row.append(InlineKeyboardButton("▶️", callback_data=f"{prefix}:{page+1}"))
    else:
        row.append(InlineKeyboardButton("▫️", callback_data=f"{prefix}:noop"))
    return [row]

async def _edit_or_reply_text_kb(update, context, text, kb):
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb) if kb else None)
            return
        except Exception:
            pass
    target = update.message or (update.callback_query.message if update.callback_query else None)
    if target:
        await target.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb) if kb else None)

async def get_top(update: Update, context: ContextTypes.DEFAULT_TYPE, page=1):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT code, type, title, views FROM media ORDER BY views DESC")
    media_all = cur.fetchall()
    con.close()

    if not media_all:
        await _edit_or_reply_text_kb(update, context, "🔥 Eng reytingli kinolar:\n\nHozircha yo'q.", None)
        return

    media, page, total_pages, total = _paginate(media_all, page)
    offset = (page - 1) * PAGE_SIZE
    text = "🔥 Eng reytingli kinolar:\n\n"
    for i, m in enumerate(media):
        text += f"{offset+i+1}. {'🎬' if m[1]=='movie' else '📺'} {m[2]} (Kod: `{m[0]}`) - {m[3]} ko'rish\n"
    text += f"\n📊 Jami: {total} ta | Sahifa {page}/{total_pages}"
    kb = _nav_kb("top", page, total_pages)
    await _edit_or_reply_text_kb(update, context, text, kb)

async def get_new(update: Update, context: ContextTypes.DEFAULT_TYPE, page=1):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT code, type, title FROM media ORDER BY id DESC")
    media_all = cur.fetchall()
    con.close()

    if not media_all:
        await _edit_or_reply_text_kb(update, context, "🆕 Yangi qo'shilganlar:\n\nHozircha yo'q.", None)
        return

    media, page, total_pages, total = _paginate(media_all, page)
    offset = (page - 1) * PAGE_SIZE
    text = "🆕 Yangi qo'shilganlar:\n\n"
    for i, m in enumerate(media):
        text += f"{offset+i+1}. {'🎬' if m[1]=='movie' else '📺'} {m[2]} (Kod: `{m[0]}`)\n"
    text += f"\n📊 Jami: {total} ta | Sahifa {page}/{total_pages}"
    kb = _nav_kb("new", page, total_pages)
    await _edit_or_reply_text_kb(update, context, text, kb)

async def get_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT code, title FROM media ORDER BY RANDOM() LIMIT 1")
    media = cur.fetchone()
    con.close()
    msg = update.message or update.callback_query.message
    if media:
        if update.callback_query: await update.callback_query.answer()
        await msg.reply_text(f"Nima ko'rishni bilmayapsizmi?\nKod: `{media[0]}`\nNom: {media[1]}", parse_mode="Markdown")
    else:
        if update.callback_query: await update.callback_query.answer()
        await msg.reply_text("Baza bo'sh.")

async def get_my(update: Update, context: ContextTypes.DEFAULT_TYPE, page=1):
    user_id = update.effective_user.id
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT m.code, m.type, m.title FROM favorites f JOIN media m ON f.media_id = m.id WHERE f.user_id=? ORDER BY m.title ASC", (user_id,))
    favs_all = cur.fetchall()
    con.close()

    if not favs_all:
        await _edit_or_reply_text_kb(update, context, "❤️ Sevimlilar hozircha bo'sh.", None)
        return

    favs, page, total_pages, total = _paginate(favs_all, page)
    offset = (page - 1) * PAGE_SIZE
    text = "❤️ Sevimli kinolaringiz:\n\n"
    for i, f in enumerate(favs):
        text += f"{offset+i+1}. {'🎬' if f[1]=='movie' else '📺'} {f[2]} (Kod: `{f[0]}`)\n"
    text += f"\n📊 Jami: {total} ta | Sahifa {page}/{total_pages}"
    kb = _nav_kb("my", page, total_pages)
    await _edit_or_reply_text_kb(update, context, text, kb)

async def get_serials(update: Update, context: ContextTypes.DEFAULT_TYPE, page=1):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id, title FROM media WHERE type='serial' ORDER BY title ASC")
    serials_all = cur.fetchall()
    con.close()

    if not serials_all:
        await _edit_or_reply_text_kb(update, context, "📺 Barcha mavjud seriallar ro'yxati:\n\n❌ Hozircha seriallar bazada yo'q.", None)
        return

    serials, page, total_pages, total = _paginate(serials_all, page)
    text = "📺 Barcha mavjud seriallar ro'yxati:\nMa'qulini tanlang:\n\n"
    offset = (page - 1) * PAGE_SIZE
    for i, s in enumerate(serials):
        text += f"{offset+i+1}. {s[1]}\n"
    text += f"\n📊 Jami: {total} ta serial | Sahifa {page}/{total_pages}"

    kb = [[InlineKeyboardButton(f"📺 {s[1]}", callback_data=f"back_med:{s[0]}")] for s in serials]
    kb += _nav_kb("ser", page, total_pages)
    await _edit_or_reply_text_kb(update, context, text, kb)

async def get_daily_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    con = connect()
    cur = con.cursor()
    
    cur.execute("SELECT last_checkin, streak, points FROM daily_checkins WHERE user_id=?", (user_id,))
    res = cur.fetchone()
    
    now = datetime.datetime.now()
    if res:
        last_checkin_str, streak, points = res
        last_checkin = datetime.datetime.strptime(last_checkin_str, "%Y-%m-%d %H:%M:%S") if last_checkin_str else None
        
        if last_checkin and last_checkin.date() == now.date():
            con.close()
            return await update.callback_query.answer("Siz bugungi bonusni olgansiz! Ertaga yana keling.", show_alert=True)
            
        if last_checkin and last_checkin.date() == (now - datetime.timedelta(days=1)).date():
            streak += 1
        else:
            streak = 1
            
        points += (10 + (streak * 2)) # Har kuni o'sib boruvchi bonus
        cur.execute("UPDATE daily_checkins SET last_checkin=?, streak=?, points=? WHERE user_id=?", 
                    (now.strftime("%Y-%m-%d %H:%M:%S"), streak, points, user_id))
    else:
        streak, points = 1, 10
        cur.execute("INSERT INTO daily_checkins (user_id, last_checkin, streak, points) VALUES (?, ?, ?, ?)", 
                    (user_id, now.strftime("%Y-%m-%d %H:%M:%S"), streak, points))
                    
    # VIP kun qo'shish har 7 kunda
    vip_msg = ""
    if streak > 0 and streak % 7 == 0:
        cur.execute("SELECT vip_until FROM users WHERE user_id=?", (user_id,))
        ures = cur.fetchone()
        base_time = datetime.datetime.strptime(ures[0], "%Y-%m-%d %H:%M:%S") if ures and ures[0] and datetime.datetime.strptime(ures[0], "%Y-%m-%d %H:%M:%S") > now else now
        vip_time = base_time + datetime.timedelta(days=1)
        cur.execute("UPDATE users SET vip_until=? WHERE user_id=?", (vip_time.strftime("%Y-%m-%d %H:%M:%S"), user_id))
        vip_msg = "\n\n🎉 7 kun ketma-ket kirganingiz uchun sizga 1 kunlik VIP hadya etildi!"
        
    con.commit()
    con.close()
    
    await update.callback_query.answer(f"✅ Bugungi bonus olindi!\nDavomiylik: {streak} kun\nBallar: {points}{vip_msg}", show_alert=True)

# --- P2P CARD PAYMENTS ---
async def apply_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Iltimos, promo kodni yuboring. \nMisol: `/promo KOD`", parse_mode="Markdown")
        
    code = context.args[0].upper()
    user_id = update.effective_user.id
    
    con = connect(); cur = con.cursor()
    cur.execute("SELECT duration_days, discount_percent, max_uses, used_count FROM vouchers WHERE code=?", (code,))
    res = cur.fetchone()
    
    if not res:
        con.close()
        return await update.message.reply_text("❌ Noto'g'ri yoki yaroqsiz promo kod.")
        
    days, discount, max_uses, used_count = res
    if max_uses > 0 and used_count >= max_uses:
        con.close()
        return await update.message.reply_text("❌ Bu promo kod tugagan (limitga yetgan).")
        
    # User apply promo
    if days > 0:
        cur.execute("SELECT vip_until FROM users WHERE user_id=?", (user_id,))
        ures = cur.fetchone()
        now = datetime.datetime.now()
        base_time = datetime.datetime.strptime(ures[0], "%Y-%m-%d %H:%M:%S") if ures and ures[0] and datetime.datetime.strptime(ures[0], "%Y-%m-%d %H:%M:%S") > now else now
        vip_time = base_time + datetime.timedelta(days=days)
        cur.execute("UPDATE users SET vip_until=? WHERE user_id=?", (vip_time.strftime("%Y-%m-%d %H:%M:%S"), user_id))
        msg = f"🎉 Promo kod qabul qilindi! Sizga {days} kunlik VIP berildi."
    elif discount > 0:
        msg = f"🎉 Promo kod qabul qilindi! Siz keyingi VIP xaridingiz uchun {discount}% chegirmaga egasiz! (Tez kunda ishga tushadi)"
    
    cur.execute("UPDATE vouchers SET used_count = used_count + 1 WHERE code=?", (code,))
    con.commit(); con.close()
    
    await update.message.reply_text(msg)

async def buy_vip_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    
    text = (
        "💎 **VIP Obuna Paketlari**\n\n"
        "Sizga mos keladigan VIP paketni tanlang. VIP orqali siz barcha filmlarni cheklovlarsiz va reklamasiz ko'rishingiz mumkin!\n\n"
        "🥉 1 Hafta - 5,000 so'm\n"
        "🥈 1 Oy - 15,000 so'm\n"
        "🥇 3 Oy - 35,000 so'm\n"
        "💎 6 Oy - 60,000 so'm\n"
        "👑 1 Yil - 100,000 so'm"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🥉 1 Hafta (5,000 so'm)", callback_data="buy_vip_days:7")],
        [InlineKeyboardButton("🥈 1 Oy (15,000 so'm)", callback_data="buy_vip_days:30")],
        [InlineKeyboardButton("🥇 3 Oy (35,000 so'm)", callback_data="buy_vip_days:90")],
        [InlineKeyboardButton("💎 6 Oy (60,000 so'm)", callback_data="buy_vip_days:180")],
        [InlineKeyboardButton("👑 1 Yil (100,000 so'm)", callback_data="buy_vip_days:365")],
    ])
    
    if update.callback_query: await update.callback_query.answer()
    await msg.reply_text(text, reply_markup=kb, parse_mode="Markdown")

async def buy_vip_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    days = int(query.data.split(":")[1])
    await query.answer()
    
    prices = {7: "5,000", 30: "15,000", 90: "35,000", 180: "60,000", 365: "100,000"}
    price = prices.get(days, "15,000")
    
    context.user_data['pending_vip_days'] = days
    
    text = (
        f"💳 **VIP Obuna ({days} Kunlik)**\n\n"
        f"Narxi: {price} so'm (Promo kodlar bo'lsa, admin tekshirib chegirma qo'llaydi)\n"
        "Karta raqam: `98601606377203607`\n\n"
        "📥 *Iltimos, yuqoridagi kartaga to'lov qilganingizni tasdiqlovchi chek (skrinshot/rasmni) hoziroq botga rasm shaklida yuboring!*"
    )
    await query.edit_message_text(text, parse_mode="Markdown")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('pending_vip_days') is None:
        return

    user = update.effective_user
    photo = update.message.photo[-1].file_id if update.message.photo else None
    if not photo:
        context.user_data.pop('pending_vip_days', None)
        return

    days = context.user_data.get('pending_vip_days', 30)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"pay_ok:{user.id}:{days}")],
        [InlineKeyboardButton("❌ Rad etish", callback_data=f"pay_no:{user.id}")]
    ])

    caption = f"📨 Yangi to'lov cheki keldi!\nFoydalanuvchi: {user.first_name} (@{user.username})\nID: {user.id}\nPaket: {days} kunlik VIP"
    await context.bot.send_photo(chat_id=SUPERADMIN_ID, photo=photo, caption=caption, reply_markup=kb)
    context.user_data.pop('pending_vip_days', None)

    await update.message.reply_text("⏳ Chek adminga yuborildi. Iltimos, admin tizimi uni ko'rib tasdiqlashini kuting.")

# --- V3 REFERRALS ---
async def get_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_info = await context.bot.get_me()
    user_id = update.effective_user.id
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT referred_count FROM users WHERE user_id=?", (user_id,))
    res = cur.fetchone()
    con.close()
    
    count = res[0] if res else 0
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        f"🔗 **Sizning taklif havolangiz**:\n`{ref_link}`\n\n"
        f"👥 Hozirgacha taklif qilinganlar: **{count} kishi**\n"
        "💡 Har 10 ta do'stingiz botga kirganda, avtomatik tarzda 1 OYLIK VIP obuna yutib olasiz!",
        parse_mode="Markdown"
    )

# --- COMMANDS CONT. ---
async def req_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await buy_vip_card(update, context) # Route to payment directly if empty
        
    code = context.args[0]
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT duration_days, is_used FROM vouchers WHERE code=?", (code,))
    voucher = cur.fetchone()
    
    if not voucher:
        await update.message.reply_text("❌ Bunday Vucher kodi mavjud emas.")
    elif voucher[1] == 1:
        await update.message.reply_text("❌ Bu kod qachondir allaqachon ishlatilgan.")
    else:
        days = voucher[0]
        cur.execute("UPDATE vouchers SET is_used=1 WHERE code=?", (code,))
        vip_time = datetime.datetime.now() + datetime.timedelta(days=days)
        cur.execute("UPDATE users SET vip_until=? WHERE user_id=?", (vip_time.strftime("%Y-%m-%d %H:%M:%S"), update.effective_user.id))
        con.commit()
        await update.message.reply_text(f"🎉 Tabriklaymiz! Sizga {days} kunlik VIP obuna taqdim etildi!")
    con.close()

async def _safe_send_message(update: Update, text: str, reply_markup=None):
    try:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception:
        await update.message.reply_text(text, reply_markup=reply_markup)

# --- AI KNOWLEDGE & TOOLS ---
def get_top_movies(limit: int = 10) -> str:
    """Botdagi eng ko'p ko'rilgan top kinolar va seriallar ro'yxatini qaytaradi."""
    try:
        con = connect()
        cur = con.cursor()
        cur.execute("SELECT code, type, title, views FROM media ORDER BY views DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        con.close()
        if not rows: return "Botda hozircha kinolar yo'q."
        res = []
        for i, r in enumerate(rows, 1):
            mtype = "🎬 Kino" if r[1] == "movie" else "📺 Serial"
            res.append(f"{i}. {r[2]} ({mtype}) - Kodi: `{r[0]}` (Ko'rishlar: {r[3]})")
        return "\n".join(res)
    except Exception as e:
        return f"Xatolik: {e}"

def get_new_movies(limit: int = 10) -> str:
    """Botga eng so'nggi qo'shilgan yangi kinolar va seriallar ro'yxatini qaytaradi."""
    try:
        con = connect()
        cur = con.cursor()
        cur.execute("SELECT code, type, title, views FROM media ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        con.close()
        if not rows: return "Botda hozircha kinolar yo'q."
        res = []
        for i, r in enumerate(rows, 1):
            mtype = "🎬 Kino" if r[1] == "movie" else "📺 Serial"
            res.append(f"{i}. {r[2]} ({mtype}) - Kodi: `{r[0]}`")
        return "\n".join(res)
    except Exception as e:
        return f"Xatolik: {e}"

def search_bot_movies(query: str, limit: int = 10) -> str:
    """Bot bazasidan kino yoki serialni nomi bo'yicha qidiradi."""
    try:
        con = connect()
        cur = con.cursor()
        cur.execute("SELECT code, type, title, views, is_vip FROM media WHERE title LIKE ? LIMIT ?", (f"%{query}%", limit))
        rows = cur.fetchall()
        con.close()
        if not rows: return f"'{query}' bo'yicha bot bazasida kino topilmadi."
        res = []
        for r in rows:
            vip = " 👑 [VIP]" if r[4] == 1 else ""
            mtype = "🎬 Kino" if r[1] == "movie" else "📺 Serial"
            res.append(f"- {r[2]} ({mtype}) - Kodi: `{r[0]}`{vip} (Ko'rishlar: {r[3]})")
        return "\n".join(res)
    except Exception as e:
        return f"Xatolik: {e}"

def get_movie_details(code: str) -> str:
    """Aniq bir kino yoki serial kodi bo'yicha to'liq ma'lumotni qaytaradi."""
    try:
        con = connect()
        cur = con.cursor()
        cur.execute("SELECT code, type, title, description, views, is_vip FROM media WHERE code=?", (code.strip().upper(),))
        row = cur.fetchone()
        con.close()
        if not row: return f"'{code}' kodli kino bot bazasida topilmadi."
        mtype = "Kino" if row[1] == "movie" else "Serial"
        vip = "Faqat VIP foydalanuvchilar uchun" if row[5] == 1 else "Barcha uchun bepul"
        desc = row[3] if row[3] else "Tavsif mavjud emas."
        return f"Nomi: {row[2]}\nTuri: {mtype}\nKodi: {row[0]}\nKo'rishlar: {row[4]}\nVIP holati: {vip}\nTavsifi: {desc}"
    except Exception as e:
        return f"Xatolik: {e}"

def get_all_serials(limit: int = 15) -> str:
    """Botdagi barcha mavjud seriallar ro'yxatini qaytaradi."""
    try:
        con = connect()
        cur = con.cursor()
        cur.execute("SELECT code, title, views FROM media WHERE type='serial' ORDER BY views DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        con.close()
        if not rows: return "Botda hozircha seriallar yo'q."
        res = []
        for i, r in enumerate(rows, 1):
            res.append(f"{i}. 📺 {r[1]} - Kodi: `{r[0]}` (Ko'rishlar: {r[2]})")
        return "\n".join(res)
    except Exception as e:
        return f"Xatolik: {e}"

def get_bot_stats() -> str:
    """Bot statistikasi: kinolar, seriallar va foydalanuvchilar soni."""
    try:
        con = connect()
        cur = con.cursor()
        cur.execute("SELECT count(*) FROM media WHERE type='movie'")
        m_cnt = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM media WHERE type='serial'")
        s_cnt = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM users")
        u_cnt = cur.fetchone()[0]
        con.close()
        return f"Botda jami {m_cnt} ta kino, {s_cnt} ta serial va {u_cnt} ta foydalanuvchi bor."
    except Exception as e:
        return f"Xatolik: {e}"

def get_vip_info() -> str:
    """VIP obuna tariflari, narxlari va imtiyozlari haqida ma'lumot."""
    return (
        "VIP imtiyozlari:\n"
        "- Majburiy homiy kanallarga obuna bo'lmasdan barcha kinolarni tomosha qilish\n"
        "- Reklamalarsiz to'liq tomosha qilish\n"
        "- VIP-eksklyuziv kinolarni ko'rish imkoniyati\n\n"
        "VIP tariflari va narxlari:\n"
        "🥉 1 Hafta — 5,000 so'm\n"
        "🥈 1 Oy — 15,000 so'm\n"
        "🥇 3 Oy — 35,000 so'm\n"
        "💎 6 Oy — 60,000 so'm\n"
        "👑 1 Yil — 100,000 so'm\n\n"
        "VIP sotib olish uchun menyudagi '💳 VIP Sotib Olish' tugmasini bosing yoki /vip buyrug'ini yuboring."
    )

def get_referral_info() -> str:
    """Do'stlarni taklif qilish va bepul VIP olish haqida ma'lumot."""
    return (
        "Referal tizimi qoidalari:\n"
        "- Har bir foydalanuvchining shaxsiy taklif havolasi mavjud.\n"
        "- Havolani olish uchun /ref buyrug'ini yuboring yoki menyudagi '🔗 Do'stlarni taklif' tugmasini bosing.\n"
        "- Har 10 ta do'stingiz botga qo'shilganda, sizga 1 Oylik (30 kunlik) bepul VIP taqdim etiladi!"
    )

AI_TOOLS = [
    get_top_movies,
    get_new_movies,
    search_bot_movies,
    get_movie_details,
    get_all_serials,
    get_bot_stats,
    get_vip_info,
    get_referral_info
]

AI_SYSTEM_INSTRUCTION = (
    "Siz 'KINO OLAMI' nomli mashhur Telegram kino botining rasmiy va aqlli AI yordamchisisiz. "
    "Siz botning barcha imkoniyatlari, kinolari, seriallari, narxlari va buyruqlarini mukammal bilasiz.\n\n"
    "BOT HAQIDA TO'LIQ MA'LUMOTLAR:\n"
    "1. Botning nomi: 'KINO OLAMI' (kinolar va seriallarni tomosha qilish boti).\n"
    "2. Bot qanday ishlaydi:\n"
    "   - Botda yuzlab kinolar va seriallar mavjud.\n"
    "   - Har bir film yoki serialning o'z maxsus raqamli yoki matnli KODI bor (masalan: 55, 22, 1, 13).\n"
    "   - Foydalanuvchi botga kino kodini yuborsa (masalan, 55), bot shu zahoti kinoni video shaklida chiqarib beradi.\n"
    "   - Seriallar bo'lsa, fasllar va qismlar tugmalari chiqadi.\n"
    "   - Foydalanuvchi kino nomini qidirishi ham mumkin.\n"
    "3. Botdagi asosiy buyruqlar:\n"
    "   - /start - Bosh menyu.\n"
    "   - /ai - AI suhbat rejimi (foydalanuvchi erkin savol-javob qilishi uchun).\n"
    "   - /stop - AI suhbatni to'xtatish va oddiy kino qidirishga qaytish.\n"
    "   - /top - Botdagi eng mashhur va ko'p ko'rilgan kinolar ro'yxati.\n"
    "   - /new - Botga yangi qo'shilgan eng so'nggi kinolar.\n"
    "   - /random - Tasodifiy birorta kino tomosha qilish.\n"
    "   - /vip - VIP obuna sotib olish.\n"
    "   - /ref - Do'stlarni taklif etish (referal havola).\n"
    "   - /lang - Bot tilini o'zgartirish (O'zbek, Rus, Ingliz).\n"
    "   - /promo - Promokod orqali bepul VIP olish.\n"
    "4. VIP tizimi va tariflar:\n"
    "   - VIP imtiyozlari: Majburiy homiy kanallarga a'zo bo'lmasdan kinolarni bemalol ko'rish, reklamalarsiz tomosha qilish va VIP-eksklyuziv kinolarni ko'rish.\n"
    "   - VIP narxlari: 1 Hafta (5,000 so'm), 1 Oy (15,000 so'm), 3 Oy (35,000 so'm), 6 Oy (60,000 so'm), 1 Yil (100,000 so'm).\n"
    "5. Referal tizimi:\n"
    "   - Har 10 ta taklif qilingan faol do'st uchun foydalanuvchiga 1 Oylik (30 kunlik) bepul VIP sovg'a qilinadi!\n\n"
    "MUHIM QOIDALAR:\n"
    "- Siz botdan tashqarida emassiz, siz aynan ushbu botning ichki aqlli yordamchisisiz. 'Men bu botni bilmayman' yoki 'Qaysi bot haqida gapiryapsiz?' deb aslo aytmang!\n"
    "- Foydalanuvchi botdagi kinolar, eng top kino, yangi kino, biror film bormi yoki yo'qligi, bot qanday ishlashi, nechta kino borligi, VIP narxlari haqida so'rasa, albatta taqdim etilgan maxsus vositalar (tools) orqali ma'lumot oling va aniq faktlar bilan javob bering.\n"
    "- Har doim kinolarni aytganda ularning BOTDAGI KODINI (masalan: Kodi: 55) ko'rsating va: 'Ushbu kinoni ko'rish uchun botga uning kodini yuboring (yoki pastdagi tugma orqali AI suhbatni to'xtatib kodni kiriting)' deb eslatib o'ting.\n"
    "- Foydalanuvchi qaysi tilda murojaat qilsa (o'zbek, rus, ingliz), shu tilda chiroyli, samimiy va tushunarli javob bering."
)

_GLOBAL_GENAI_CLIENT = None

def get_genai_client():
    global _GLOBAL_GENAI_CLIENT
    if _GLOBAL_GENAI_CLIENT is None:
        _GLOBAL_GENAI_CLIENT = genai.Client(api_key=GEMINI_API_KEY)
    return _GLOBAL_GENAI_CLIENT

def _create_ai_chat_session(model_name="gemini-3.5-flash-lite"):
    client = get_genai_client()
    return client.chats.create(
        model=model_name,
        config=types.GenerateContentConfig(
            system_instruction=AI_SYSTEM_INSTRUCTION,
            tools=AI_TOOLS
        )
    )

def _get_or_create_ai_chat(context: ContextTypes.DEFAULT_TYPE):
    chat = context.user_data.get('ai_chat')
    if chat is None:
        chat = _create_ai_chat_session("gemini-3.5-flash-lite")
        context.user_data['ai_chat'] = chat
    return chat

async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    if not GEMINI_API_KEY:
        context.user_data['ai_mode'] = False
        await update.message.reply_text("⚠️ Gemini API kaliti sozlanmagan. Iltimos, admin bilan bog'laning.")
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 AI suhbatni to'xtatish", callback_data="exit_ai_mode")]
    ])
    try:
        chat = _get_or_create_ai_chat(context)
        response = chat.send_message(text)
        reply_text = response.text
    except Exception as e:
        logger.warning(f"AI chat error: {e}, resetting client and retrying...")
        try:
            global _GLOBAL_GENAI_CLIENT
            _GLOBAL_GENAI_CLIENT = None
            chat = _create_ai_chat_session("gemini-3.5-flash-lite")
            context.user_data['ai_chat'] = chat
            response = chat.send_message(text)
            reply_text = response.text
        except Exception as e2:
            logger.error(f"AI retry failed: {e2}")
            reply_text = "❌ Kechirasiz, AI javob berishda xatolik yuz berdi. Iltimos, birozdan so'ng qayta urinib ko'ring."

    await _safe_send_message(update, reply_text, reply_markup=kb)

async def ai_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_maintenance(update, context): return
    if not await check_force_sub(update, context): return
    user_id = update.effective_user.id
    if not check_rate(user_id): return

    if not GEMINI_API_KEY:
        await update.message.reply_text("⚠️ Gemini API kaliti sozlanmagan. Iltimos, administrator bilan bog'laning.")
        return

    # Agar /ai dan keyin darhol savol yozilgan bo'lsa (masalan: /ai Titanic qanaqa film?)
    if context.args:
        prompt = " ".join(context.args)
        try:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        except Exception:
            pass
        try:
            temp_chat = _create_ai_chat_session("gemini-3.5-flash-lite")
            response = temp_chat.send_message(prompt)
            reply = response.text
        except Exception as e:
            logger.error(f"Gemini command error: {e}")
            reply = "❌ AI bilan bog'lanishda xatolik yuz berdi."

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 AI bilan suhbatlashish", callback_data="cmd_ai")]
        ])
        await _safe_send_message(update, reply, reply_markup=kb)
        return

    # /ai bir o'zi yuborilganda: AI suhbat rejimini yoqish
    context.user_data['ai_mode'] = True
    context.user_data['ai_chat'] = None

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 AI suhbatni to'xtatish", callback_data="exit_ai_mode")]
    ])
    welcome_ai = (
        "🤖 **KINO OLAMI AI Yordamchisi Ishga Tushdi!**\n\n"
        "Men botdagi barcha filmlar, yangiliklar, seriallar, top kinolar va qoidalar haqida to'liq bilaman.\n\n"
        "Menga istalgan savolingizni yozishingiz mumkin:\n"
        "• *«Botdagi eng top kino qaysi?»*\n"
        "• *«Avatar bormi?»*\n"
        "• *«VIP qanday olinadi?»*\n"
        "• *«Yangi qanday filmlar bor?»*\n\n"
        "💡 _Suhbatni to'xtatish uchun pastdagi tugmani bosing yoki /stop yozing._"
    )
    await _safe_send_message(update, welcome_ai, reply_markup=kb)

async def stop_ai_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ai_mode'] = False
    context.user_data['ai_chat'] = None
    await update.message.reply_text(
        "✅ **AI suhbat rejimi to'xtatildi.**\n\n"
        "Endi yana kino kodini yuborib kino qidirishingiz mumkin. Bosh menyuga qaytish: /start",
        parse_mode="Markdown"
    )

async def search_movie_string(update, text, cur, con, context=None):
    # Log Search
    try:
        cur.execute("INSERT INTO search_logs (user_id, query) VALUES (?, ?)", (update.effective_user.id, text))
        con.commit()
    except Exception as e:
        logger.warning(f"Search log insert failed: {e}")
    
    cur.execute("SELECT code, type, title FROM media WHERE title LIKE ? LIMIT 15", (f"%{text}%",))
    res = cur.fetchall()
    if res:
        msg = f"🔍 '{text}' natijasi:\n\n"
        for r in res: msg += f"{'🎬' if r[1]=='movie' else '📺'} {r[2]} (Kod: `{r[0]}`)\n"
        await _safe_send_message(update, msg)
    else: 
        # Bazadan topilmasa Gemini AI orqali aqlli javob qaytarish
        if GEMINI_API_KEY:
            if context:
                try:
                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                except Exception:
                    pass
            try:
                temp_chat = _create_ai_chat_session("gemini-3.5-flash-lite")
                prompt = (
                    f"Foydalanuvchi quyidagi so'rov yoki xabarni yozdi: '{text}'. "
                    f"Agar bu kino yoki serial haqida bo'lsa, vositalar orqali botda bor-yo'qligini tekshiring, "
                    f"kodi bilan tavsiya qiling. Agar bu salomlashish yoki umumiy savol bo'lsa, xushmuomala javob bering."
                )
                response = temp_chat.send_message(prompt)
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 AI bilan suhbatlashish", callback_data="cmd_ai")]
                ])
                await _safe_send_message(update, response.text, reply_markup=kb)
            except Exception as e:
                logger.warning(f"Gemini AI search error: {e}")
                await update.message.reply_text("❌ Hech narsa topilmadi.")
        else:
            await update.message.reply_text("❌ Hech narsa topilmadi.")
    con.close()

async def send_media_by_code(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str) -> bool:
    user_id = update.effective_user.id
    lang = get_lang(user_id)
    con = connect()
    try:
        cur = con.cursor()
        cur.execute("SELECT id, type, title, description, file_id, views, is_vip, genres FROM media WHERE code=?", (code.strip().upper(),))
        media = cur.fetchone()
        if not media:
            return False

        media_id, m_type, title, description, file_id, views, is_vip, genres = media
        
        if is_vip == 1:
            cur.execute("SELECT vip_until FROM users WHERE user_id=?", (user_id,))
            udata = cur.fetchone()
            if not udata or not udata[0] or datetime.datetime.strptime(udata[0], "%Y-%m-%d %H:%M:%S") < datetime.datetime.now():
                await context.bot.send_message(chat_id=user_id, text="🚫 Ushbu kino faqat VIP userlar qidirishi mumkin.")
                return True
                
        cur.execute("UPDATE media SET views = views + 1 WHERE id=?", (media_id,))
        con.commit()
        
        cur.execute("SELECT AVG(score), COUNT(score) FROM ratings WHERE media_id=?", (media_id,))
        r_data = cur.fetchone()
        avg = round(r_data[0], 1) if r_data and r_data[0] else 0.0
        cnt = r_data[1] if r_data else 0
        rating_text = f"⭐️ Reyting: {avg}/5.0 ({cnt} kishi baho bergan)"
        
        # Ads fetching
        cur.execute("SELECT id, text, image_id, button_text, button_url FROM ads WHERE is_active=1 ORDER BY RANDOM() LIMIT 1")
        ad = cur.fetchone()

        import html
        t_esc = html.escape(title)
        d_esc = html.escape(description) if description else ""
        g_esc = html.escape(genres) if genres else ""
        c_esc = html.escape(str(code.strip().upper()))
        
        cap_parts = [f"🎬 <b>{t_esc}</b>"]
        if d_esc:
            cap_parts.append(f"📝 {d_esc}")
        if g_esc:
            cap_parts.append(f"🎭 Janr: {g_esc}")
        cap_parts.append(f"🔢 Kod: <code>{c_esc}</code>")
        if rating_text.strip():
            cap_parts.append(rating_text.strip())
        if ad and ad[1]:
            cap_parts.append(f"📢 {html.escape(ad[1])}")
            
        full_caption = "\n\n".join(cap_parts)

        if m_type == 'movie':
            kb = [
                [InlineKeyboardButton(get_text(lang, 'fav_add'), callback_data=f"fav:{media_id}")],
                [InlineKeyboardButton("1⭐", callback_data=f"rate:1:{media_id}"), InlineKeyboardButton("3⭐", callback_data=f"rate:3:{media_id}"), InlineKeyboardButton("5⭐", callback_data=f"rate:5:{media_id}")]
            ]
            if ad and ad[3] and ad[4]:
                kb.append([InlineKeyboardButton(ad[3], url=ad[4])])
                
            cur.execute("INSERT OR REPLACE INTO watch_history (user_id, media_id, episode_id) VALUES (?, ?, ?)", (user_id, media_id, 0))
            con.commit()
            try:
                await context.bot.send_video(chat_id=user_id, video=file_id, caption=full_caption, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            except Exception:
                try:
                    await context.bot.send_document(chat_id=user_id, document=file_id, caption=full_caption, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Error sending movie {code} to {user_id}: {e}")
            return True
        elif m_type == 'serial':
            cur.execute("SELECT id, season_number FROM seasons WHERE media_id=? ORDER BY season_number ASC", (media_id,))
            seasons = cur.fetchall()
            if not seasons:
                if target_msg: await target_msg.reply_text("❌ Qismlari yo'q.")
                return True
            keyboard = [[InlineKeyboardButton(f"{s[1]}-Fasl", callback_data=f"sea:{s[0]}")] for s in seasons]
            keyboard.append([InlineKeyboardButton(get_text(lang, 'fav_add'), callback_data=f"fav:{media_id}")])
            keyboard.append([InlineKeyboardButton("1⭐", callback_data=f"rate:1:{media_id}"), InlineKeyboardButton("5⭐", callback_data=f"rate:5:{media_id}")])
            if ad and ad[3] and ad[4]:
                keyboard.append([InlineKeyboardButton(ad[3], url=ad[4])])
            if target_msg:
                await target_msg.reply_text(f"📺 {title}\n{desc_text}\n\nFaslni tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))
            return True
    finally:
        con.close()
    return False

# --- MAIN TEXT HANDLER ---
async def get_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_maintenance(update, context): return
    if not await check_force_sub(update, context): return
    user_id = update.effective_user.id
    if not check_rate(user_id): return
    
    text = update.message.text.strip()
    
    # Agar foydalanuvchi AI suhbat rejimida bo'lsa
    if context.user_data.get('ai_mode'):
        return await handle_ai_message(update, context, text)
        
    if not await send_media_by_code(update, context, text):
        con = connect()
        cur = con.cursor()
        return await search_movie_string(update, text, cur, con, context)


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    
    if data == "check_sub":
        await query.answer()
        if not await check_force_sub(update, context):
            return
        pending = context.user_data.pop('pending_code', None)
        if pending and await send_media_by_code(update, context, pending):
            return
        return await start(update, context)

    if data == "cmd_daily_bonus":
        return await get_daily_bonus(update, context)
    if data == "cmd_search":
        await query.answer()
        lang = get_lang(user_id)
        return await update.callback_query.message.reply_text(get_text(lang, 'search_prompt'), parse_mode="Markdown")
        
    if data == "cmd_top": await query.answer(); return await get_top(update, context)
    if data == "cmd_new": await query.answer(); return await get_new(update, context)
    if data == "cmd_random": await query.answer(); return await get_random(update, context)
    if data == "cmd_my": await query.answer(); return await get_my(update, context)
    if data == "cmd_ref": await query.answer(); return await get_ref(update, context)
    if data == "cmd_buy_vip": return await buy_vip_card(update, context)
    if data == "cmd_serials": await query.answer(); return await get_serials(update, context)
    if data == "cmd_ai":
        await query.answer()
        context.user_data['ai_mode'] = True
        context.user_data['ai_chat'] = None
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛑 AI suhbatni to'xtatish", callback_data="exit_ai_mode")]
        ])
        msg = (
            "🤖 **Gemini AI Suhbat Rejimi Yoqildi!**\n\n"
            "Endi menga istalgan savolingizni yozishingiz mumkin. "
            "Kino tavsiyalari, film qahramonlari, syujetlar yoki shunchaki umumiy suhbatlashamiz!\n\n"
            "💡 _Suhbatni to'xtatish uchun pastdagi tugmani bosing yoki /stop buyrug'ini yozing._"
        )
        return await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)

    if data == "exit_ai_mode":
        context.user_data['ai_mode'] = False
        context.user_data['ai_chat'] = None
        await query.answer("AI suhbat yakunlandi.")
        return await query.message.reply_text(
            "✅ **AI suhbat rejimi to'xtatildi.**\n\n"
            "Endi botga kino kodini yuborib kino qidirishingiz mumkin. Bosh menyuga qaytish: /start",
            parse_mode="Markdown"
        )

    for prefix, fn in [("top", get_top), ("new", get_new), ("my", get_my), ("ser", get_serials)]:
        if data.startswith(f"{prefix}:"):
            arg = data.split(":", 1)[1]
            if arg == "noop":
                await query.answer("...")
                return
            try:
                page = int(arg)
            except ValueError:
                return
            return await fn(update, context, page)

    con = connect()
    try:
        cur = con.cursor()
        if data.startswith("lang_"):
            lcode = data.split("_")[1]
            cur.execute("UPDATE users SET language=? WHERE user_id=?", (lcode, user_id))
            con.commit()
            await query.answer(get_text(lcode, 'lang_changed'), show_alert=True)
            return

        if data.startswith("pay_ok:"):
            parts = data.split(":")
            target_user = int(parts[1])
            days = int(parts[2]) if len(parts) > 2 else 30
            cur.execute("SELECT vip_until FROM users WHERE user_id=?", (target_user,))
            res = cur.fetchone()
            now_dt = datetime.datetime.now()
            base_time = datetime.datetime.strptime(res[0], "%Y-%m-%d %H:%M:%S") if res and res[0] and datetime.datetime.strptime(res[0], "%Y-%m-%d %H:%M:%S") > now_dt else now_dt
            vip_time = base_time + datetime.timedelta(days=days)
            cur.execute("UPDATE users SET vip_until=? WHERE user_id=?", (vip_time.strftime("%Y-%m-%d %H:%M:%S"), target_user))
            con.commit()
            try: await context.bot.send_message(chat_id=target_user, text=f"🎉 To'lovingiz admin tomonidan tasdiqlandi! \n{days} Kunlik VIP obunangiz aktivlashtirildi!")
            except Exception as e:
                logger.warning(f"Could not notify user {target_user} about VIP approval: {e}")
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ HOLAT: Tasdiqlandi ({days} kun Obuna berildi).")
            return

        if data.startswith("pay_no:"):
            target_user = int(data.split(":")[1])
            try: await context.bot.send_message(chat_id=target_user, text="❌ To'lovingiz admin tomonidan bekor qilindi (tasdiqlanmadi)!")
            except Exception as e:
                logger.warning(f"Could not notify user {target_user} about payment rejection: {e}")
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ HOLAT: Bekor qilindi.")
            return

        if data.startswith("fav:") or data.startswith("rate:"):
            try:
                if data.startswith("fav:"):
                    m_id = int(data.split(":")[1])
                    cur.execute("INSERT INTO favorites (user_id, media_id) VALUES (?, ?)", (user_id, m_id))
                    await query.answer("❤️ Sevimlilarga qo'shildi!", show_alert=True)
                elif data.startswith("rate:"):
                    pts = data.split(":")
                    cur.execute("INSERT OR REPLACE INTO ratings (user_id, media_id, score) VALUES (?, ?, ?)", (user_id, int(pts[2]), int(pts[1])))
                    await query.answer("⭐️ Bahoyigniz qayd etildi!", show_alert=True)
                con.commit()
            except:
                if data.startswith("fav:"):
                    cur.execute("DELETE FROM favorites WHERE user_id=? AND media_id=?", (user_id, m_id)); con.commit()
                    await query.answer("💔 Olib tashlandi!", show_alert=True)
            return

        if data in ["stats", "users", "broadcast", "settings", "add_movie", "add_serial", "add_episode", "edit_media_menu", "sys_settings", "cancel_admin", "admin_main", "admin_users", "admin_system"]:
            return

        if not check_rate(user_id): return await query.answer("Vaqt", show_alert=True)

        if data.startswith("sea:"):
            s_id = int(data.split(":")[1])
            cur.execute("SELECT id, episode_number FROM episodes WHERE season_id=? ORDER BY episode_number ASC", (s_id,))
            episodes = cur.fetchall()
            cur.execute("SELECT media_id, season_number FROM seasons WHERE id=?", (s_id,))
            s_data = cur.fetchone()
            cur.execute("SELECT episode_id FROM watch_history WHERE user_id=? AND media_id=?", (user_id, s_data[0]))
            watched = [r[0] for r in cur.fetchall()]
            k, r = [], []
            for ep in episodes:
                mark = "✅" if ep[0] in watched else ""
                r.append(InlineKeyboardButton(f"{ep[1]}{mark}", callback_data=f"epi:{ep[0]}"))
                if len(r) >= 4: k.append(r); r = []
            if r: k.append(r)
            k.append([InlineKeyboardButton("🔙", callback_data=f"back_med:{s_data[0]}")])
            await query.edit_message_text(f"Fasl: {s_data[1]}\nQismni tanlang:", reply_markup=InlineKeyboardMarkup(k))
        elif data.startswith("epi:"):
            ep_id = int(data.split(":")[1])
            cur.execute("SELECT file_id, season_id, episode_number FROM episodes WHERE id=?", (ep_id,))
            ep_data = cur.fetchone()
            if not ep_data: return await query.answer("❌", show_alert=True)
            cur.execute("SELECT media_id FROM seasons WHERE id=?", (ep_data[1],))
            m_id = cur.fetchone()[0]
            cur.execute("INSERT OR REPLACE INTO watch_history (user_id, media_id, episode_id) VALUES (?, ?, ?)", (user_id, m_id, ep_id))
            con.commit()
            await query.answer("Yuklanmoqda...")
            try: await query.message.reply_video(ep_data[0], caption=f"📺 Qism")
            except: await query.message.reply_document(ep_data[0], caption=f"📺 Qism")
        elif data.startswith("back_med:"):
            m_id = int(data.split(":")[1])
            cur.execute("SELECT title, description FROM media WHERE id=?", (m_id,))
            m = cur.fetchone()
            cur.execute("SELECT id, season_number FROM seasons WHERE media_id=? ORDER BY season_number ASC", (m_id,))
            ss = cur.fetchall()
            kb = [[InlineKeyboardButton(f"{s[1]}-Fasl", callback_data=f"sea:{s[0]}")] for s in ss]
            await query.edit_message_text(f"📺 {m[0]}\nFaslni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
    finally:
        con.close()