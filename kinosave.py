import sys
import os
import asyncio
import time

# Ensure project root and handlers are always in Python path (fixes server deployments)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in [_BASE_DIR, os.getcwd(), os.path.join(_BASE_DIR, "handlers")]:
    if _p and os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="telegram.ext")
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from config import BOT_TOKEN, DB_PATH
from db import init_db, connect

from handlers.user import (
    start, get_top, get_new, get_random, req_vip, get_movie,
    callback_query_handler, get_ref, buy_vip_card, handle_photo,
    buy_vip_days_callback, apply_promo, set_lang,
    ai_chat_command, stop_ai_mode
)
from handlers.admin import (
    admin_panel, admin_users_menu, admin_system_menu, cancel_admin,
    get_movie_conv, get_serial_conv, get_episode_conv,
    get_admin_mgmt_conv, get_admin_callbacks
)
from handlers.admin_media import get_edit_media_conv
from handlers.admin_broadcast import get_broadcast_conv
from handlers.admin_xtra import (
    get_backup_conv, get_force_sub_conv, sys_settings_menu, export_csv_stats, manual_backup,
    get_voucher_conv, get_dm_conv, get_xtra_callbacks_updated, get_text_edit_conv, get_admin_mgmt_xtra_conv,
    get_post_channel_conv
)
from handlers.admin_ads import get_ads_conv, get_ads_callbacks

async def post_init(application: Application):
    from telegram import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
    
    try:
        await application.bot.set_my_commands(
            [
                BotCommand("start", "Bosh menu"),
                BotCommand("ai", "🤖 AI Suhbat"),
                BotCommand("lang", "Tilni tanlash"),
                BotCommand("top", "Top kinolar"),
                BotCommand("new", "Yangi kinolar"),
                BotCommand("random", "Tasodifiy kino"),
                BotCommand("vip", "VIP obuna"),
                BotCommand("ref", "Do'stlarni taklif etish")
            ],
            scope=BotCommandScopeDefault()
        )
    except Exception as e: print(e)
    
    try:
        from config import SUPERADMIN_ID
        await application.bot.set_my_commands(
            [
                BotCommand("start", "Bosh menu"),
                BotCommand("ai", "🤖 AI Suhbat"),
                BotCommand("lang", "Tilni tanlash"),
                BotCommand("top", "Top kinolar"),
                BotCommand("new", "Yangi kinolar"),
                BotCommand("random", "Tasodifiy kino"),
                BotCommand("vip", "VIP obuna"),
                BotCommand("ref", "Do'stlarni taklif etish"),
                BotCommand("admin", "👮‍♂️ Admin Panel")
            ],
            scope=BotCommandScopeChat(chat_id=SUPERADMIN_ID)
        )
    except Exception as e: print(e)


async def auto_backup_job(context):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT value FROM sys_settings WHERE key='backup_channel'")
    b_ch = cur.fetchone()
    con.close()
    
    if b_ch and b_ch[0]:
        try:
            with open(DB_PATH, "rb") as f:
                await context.bot.send_document(
                    chat_id=b_ch[0],
                    document=f,
                    filename="database_auto.db",
                    caption=f"🔄 Daily Auto Backup: {time.strftime('%Y-%m-%d %H:%M')}"
                )
        except Exception:
            pass

async def vip_reminder_job(context):
    con = connect()
    cur = con.cursor()
    import datetime
    
    # 3 kun yoki undan kam qolgan, va eslatma yuborilmaganlarni topish
    now = datetime.datetime.now()
    three_days_later = (now + datetime.timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    cur.execute("SELECT user_id, vip_until FROM users WHERE vip_until > ? AND vip_until <= ? AND vip_reminder_sent = 0", (now_str, three_days_later))
    users = cur.fetchall()
    
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user[0], 
                text="⚠️ **Diqqat!**\n\nSizning VIP obunangiz tugashiga 3 kundan kam vaqt qoldi. VIP imtiyozlaridan uzilishsiz foydalanish uchun uni hoziroq uzaytiring!",
                parse_mode="Markdown"
            )
            cur.execute("UPDATE users SET vip_reminder_sent = 1 WHERE user_id=?", (user[0],))
        except:
            pass
            
    # Muddati o'tganlarning reminder holatini tiklash (keyingi safar vip olganda yana ishlashi uchun)
    cur.execute("UPDATE users SET vip_reminder_sent = 0 WHERE vip_until <= ?", (now_str,))
    
    con.commit()
    con.close()

def main():
    if not BOT_TOKEN:
        print("❌ Error: BOT_TOKEN is not set in config or environment variables.")
        return

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    init_db()
    
    # Scheduled Jobs (Auto Backup every 12 hours = 43200 seconds)
    if app.job_queue:
        app.job_queue.run_repeating(auto_backup_job, interval=43200, first=10)
        app.job_queue.run_repeating(vip_reminder_job, interval=3600, first=20) # Har soatda tekshiradi
    else:
        print("⚠️ Warning: JobQueue is not available. Auto-backup will not run.")
        print("To enable JobQueue, install with: pip install 'python-telegram-bot[job-queue]'")
    
    # --- User Endpoints
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ai", ai_chat_command))
    app.add_handler(CommandHandler("stop", stop_ai_mode))
    app.add_handler(CommandHandler("lang", set_lang))
    app.add_handler(CommandHandler("top", get_top))
    app.add_handler(CommandHandler("new", get_new))
    app.add_handler(CommandHandler("random", get_random))
    app.add_handler(CommandHandler("vip", req_vip))
    app.add_handler(CommandHandler("ref", get_ref))
    app.add_handler(CommandHandler("buy", buy_vip_card))
    app.add_handler(CommandHandler("promo", apply_promo))
    
    # --- P2P Payments
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo))
    
    # --- Admin Callbacks
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(cancel_admin, pattern="^cancel_admin$"))
    app.add_handler(CallbackQueryHandler(sys_settings_menu, pattern="^sys_settings$"))
    app.add_handler(CallbackQueryHandler(export_csv_stats, pattern="^export_csv$"))
    app.add_handler(CallbackQueryHandler(manual_backup, pattern="^manual_backup$"))
    app.add_handler(CallbackQueryHandler(buy_vip_days_callback, pattern="^buy_vip_days:"))
    
    # New Admin Callbacks
    for cb in get_admin_callbacks(): app.add_handler(cb)
    for cb in get_xtra_callbacks_updated(): app.add_handler(cb)
    for cb in get_ads_callbacks(): app.add_handler(cb)

    # --- Admin Forms
    app.add_handler(get_movie_conv())
    app.add_handler(get_serial_conv())
    app.add_handler(get_episode_conv())
    app.add_handler(get_edit_media_conv())
    app.add_handler(get_broadcast_conv())
    app.add_handler(get_force_sub_conv())
    app.add_handler(get_backup_conv())
    app.add_handler(get_admin_mgmt_conv())
    app.add_handler(get_voucher_conv())
    app.add_handler(get_dm_conv())
    app.add_handler(get_text_edit_conv())
    app.add_handler(get_admin_mgmt_xtra_conv())
    app.add_handler(get_post_channel_conv())
    app.add_handler(get_ads_conv())
    
    # --- Catch-all navigations and texts
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_movie))

    app.run_polling()

if __name__ == "__main__":
    main()
