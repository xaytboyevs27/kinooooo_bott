from telegram import Update
from telegram.ext import ContextTypes
from config import SUPERADMIN_ID
from db import connect

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != SUPERADMIN_ID:
        return
        
    if not context.args:
        await update.message.reply_text("Xabar matnini kiriting:\nMasalan: /broadcast Hammaga salom!")
        return
        
    text = " ".join(context.args)
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT user_id FROM users")
    users = cur.fetchall()
    con.close()
    
    count = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u[0], text=text)
            count += 1
        except Exception:
            pass
            
    await update.message.reply_text(f"✅ Xabar {count} ta foydalanuvchiga yuborildi.")
