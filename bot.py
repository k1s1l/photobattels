import os, sqlite3, logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import imagehash
from PIL import Image
from dotenv import load_dotenv
from telegram import Update, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()
BOT_TOKEN=os.getenv("BOT_TOKEN","")
CHANNEL_ID=os.getenv("CHANNEL_ID","")
ADMIN_ID=int(os.getenv("ADMIN_ID","0") or 0)
COOLDOWN_HOURS=4
BLOCK_BATTLES=2
DB_FILE="photo_battle.db"
PHOTO_DIR=Path("photos"); PHOTO_DIR.mkdir(exist_ok=True)
logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)

def db():
    c=sqlite3.connect(DB_FILE); c.row_factory=sqlite3.Row; return c
def now(): return datetime.now(timezone.utc)
def init_db():
    c=db()
    c.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,last_photo_time TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS photos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,
        telegram_file_id TEXT NOT NULL,file_path TEXT NOT NULL,
        photo_hash TEXT NOT NULL,created_at TEXT NOT NULL,
        battle_number INTEGER,status TEXT DEFAULT 'queued')""")
    c.commit(); c.close()
def last_photo(uid):
    c=db(); r=c.execute("SELECT last_photo_time FROM users WHERE user_id=?",(uid,)).fetchone(); c.close()
    return datetime.fromisoformat(r["last_photo_time"]) if r and r["last_photo_time"] else None
def set_last(uid):
    c=db(); c.execute("""INSERT INTO users(user_id,last_photo_time) VALUES(?,?)
        ON CONFLICT(user_id) DO UPDATE SET last_photo_time=excluded.last_photo_time""",(uid,now().isoformat())); c.commit(); c.close()
def last_battle():
    c=db(); r=c.execute("SELECT MAX(battle_number) b FROM photos").fetchone(); c.close(); return r["b"] or 0
def phash(path): return str(imagehash.phash(Image.open(path)))
def duplicate(uid,h):
    b=last_battle()
    if not b:return False
    minimum=max(1,b-BLOCK_BATTLES+1)
    c=db(); r=c.execute("""SELECT id FROM photos WHERE user_id=? AND photo_hash=?
        AND battle_number IS NOT NULL AND battle_number>=? LIMIT 1""",(uid,h,minimum)).fetchone(); c.close()
    return r is not None
def save(uid,fid,path,h):
    c=db(); c.execute("""INSERT INTO photos(user_id,telegram_file_id,file_path,photo_hash,created_at,status)
        VALUES(?,?,?,?,?,'queued')""",(uid,fid,path,h,now().isoformat())); c.commit(); c.close()
def admin(u): return u.effective_user and u.effective_user.id==ADMIN_ID

async def start(update,context):
    await update.message.reply_text("👋 Привет!\n\n📸 Это бот фотобатлов.\n\nТы можешь отправлять одну фотографию раз в 4 часа.\n\n⚠️ Одна и та же фотография не может повторно участвовать в ближайших двух баттлах.\n\nПросто отправь фотографию сюда.")

async def photo(update,context):
    m=update.message; uid=update.effective_user.id
    lp=last_photo(uid)
    if lp:
        d=now()-lp; cd=timedelta(hours=COOLDOWN_HOURS)
        if d<cd:
            s=max(0,int((cd-d).total_seconds())); h=s//3600; mi=(s%3600)//60
            await m.reply_text(f"⏳ Ты уже отправлял фотографию!\n\nСледующую фотографию можно отправить через {h} ч. {mi} мин.\n\nСпасибо за участие! ❤️"); return
    p=m.photo[-1]; f=await context.bot.get_file(p.file_id)
    path=PHOTO_DIR/f"{uid}_{int(now().timestamp())}.jpg"
    await f.download_to_drive(custom_path=str(path))
    try: h=phash(path)
    except Exception:
        path.unlink(missing_ok=True); await m.reply_text("❌ Не получилось обработать фотографию.\n\nПопробуй отправить её ещё раз."); return
    if duplicate(uid,h):
        path.unlink(missing_ok=True)
        await m.reply_text("❌ Эта фотография уже участвовала в одном из твоих последних двух баттлов!\n\nПожалуйста, отправь другой снимок.\n\nМы хотим, чтобы каждый баттл был интересным и разнообразным! ❤️"); return
    save(uid,p.file_id,str(path),h); set_last(uid)
    await m.reply_text("✅ Фотография успешно принята!\n\n📸 Твой снимок добавлен в очередь на ближайший баттл.\n\nВсё хорошо, спасибо за участие! ❤️\nЖелаем удачи и пусть победит сильнейший!")

async def other(update,context):
    if update.message: await update.message.reply_text("📸 Отправь мне именно фотографию.")
def queue_rows():
    c=db(); r=c.execute("SELECT * FROM photos WHERE status='queued' ORDER BY id").fetchall(); c.close(); return r
async def queue(update,context):
    if not admin(update): return
    await update.message.reply_text(f"📸 В очереди сейчас: {len(queue_rows())} фотографий.")
async def publish(update,context):
    if not admin(update): return
    rows=queue_rows()
    if not rows: await update.message.reply_text("📭 Очередь пустая."); return
    battle=last_battle()+1; ids=[]
    for i in range(0,len(rows),10):
        batch=rows[i:i+10]; media=[]; opened=[]
        try:
            for r in batch:
                x=open(r["file_path"],"rb"); opened.append(x); media.append(InputMediaPhoto(x))
            await context.bot.send_media_group(chat_id=CHANNEL_ID,media=media); ids += [r["id"] for r in batch]
        finally:
            for x in opened:x.close()
    c=db()
    c.executemany("UPDATE photos SET status='published',battle_number=? WHERE id=?",[(battle,i) for i in ids])
    c.commit(); c.close()
    await update.message.reply_text(f"✅ Баттл №{battle} опубликован!\n\n📸 Фотографий: {len(ids)}")
def main():
    if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN не указан")
    if not CHANNEL_ID: raise RuntimeError("CHANNEL_ID не указан")
    if not ADMIN_ID: raise RuntimeError("ADMIN_ID не указан")
    init_db(); app=Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("queue",queue)); app.add_handler(CommandHandler("publish",publish))
    app.add_handler(MessageHandler(filters.PHOTO,photo)); app.add_handler(MessageHandler(~filters.COMMAND & ~filters.PHOTO,other))
    app.run_polling()
if __name__=="__main__": main()
