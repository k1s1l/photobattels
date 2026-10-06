import os
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import imagehash
from PIL import Image
from dotenv import load_dotenv
from telegram import Update, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")

# ОДНО ФОТО РАЗ В 16 ЧАСОВ
COOLDOWN_HOURS = 16

# Сколько последних баттлов запрещено использовать
# ту же фотографию
BLOCK_BATTLES = 2

DB_FILE = "photo_battle.db"
PHOTO_DIR = Path("photos")

# Киевское время
KYIV_TZ = ZoneInfo("Europe/Kyiv")

PHOTO_DIR.mkdir(exist_ok=True)

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("photo-battle")


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            last_photo_time TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            telegram_file_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            photo_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            battle_number INTEGER,
            status TEXT DEFAULT 'queued'
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# TIME
# =========================================================

def utc_now():
    return datetime.now(timezone.utc)


def kyiv_now():
    return datetime.now(KYIV_TZ)


def get_last_photo_time(user_id):
    conn = get_db()

    row = conn.execute(
        """
        SELECT last_photo_time
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    if not row or not row["last_photo_time"]:
        return None

    return datetime.fromisoformat(
        row["last_photo_time"]
    )


def update_last_photo_time(user_id):
    conn = get_db()

    conn.execute("""
        INSERT INTO users (
            user_id,
            last_photo_time
        )

        VALUES (?, ?)

        ON CONFLICT(user_id)

        DO UPDATE SET
            last_photo_time = excluded.last_photo_time
    """, (
        user_id,
        utc_now().isoformat()
    ))

    conn.commit()
    conn.close()


# =========================================================
# BATTLES
# =========================================================

def get_last_battle():
    conn = get_db()

    row = conn.execute(
        """
        SELECT MAX(battle_number) AS battle
        FROM photos
        """
    ).fetchone()

    conn.close()

    return row["battle"] or 0


# =========================================================
# PHOTO HASH
# =========================================================

def calculate_photo_hash(file_path):
    image = Image.open(file_path)

    # Perceptual hash позволяет распознавать
    # одинаковые/почти одинаковые фотографии
    # даже после сжатия или изменения размера
    photo_hash = imagehash.phash(image)

    return str(photo_hash)


# =========================================================
# DUPLICATE CHECK
# =========================================================

def photo_used_recently(user_id, photo_hash):

    current_battle = get_last_battle()

    if current_battle == 0:
        return False

    minimum_battle = max(
        1,
        current_battle - BLOCK_BATTLES + 1
    )

    conn = get_db()

    row = conn.execute("""
        SELECT id
        FROM photos

        WHERE user_id = ?

        AND photo_hash = ?

        AND battle_number IS NOT NULL

        AND battle_number >= ?

        LIMIT 1
    """, (
        user_id,
        photo_hash,
        minimum_battle
    )).fetchone()

    conn.close()

    return row is not None


# =========================================================
# SAVE PHOTO
# =========================================================

def save_photo(
    user_id,
    telegram_file_id,
    file_path,
    photo_hash
):

    conn = get_db()

    conn.execute("""
        INSERT INTO photos (
            user_id,
            telegram_file_id,
            file_path,
            photo_hash,
            created_at,
            status
        )

        VALUES (?, ?, ?, ?, ?, 'queued')
    """, (
        user_id,
        telegram_file_id,
        file_path,
        photo_hash,
        utc_now().isoformat()
    ))

    conn.commit()
    conn.close()


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "👋 Привет!\n\n"

        "📸 Это бот фотобатлов.\n\n"

        "Ты можешь отправлять одну фотографию "
        "раз в 16 часов.\n\n"

        "⚠️ Одна и та же фотография не может "
        "повторно участвовать в ближайших "
        "двух баттлах.\n\n"

        "Просто отправь фотографию сюда."
    )


# =========================================================
# PHOTO HANDLER
# =========================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message
    user = update.effective_user

    if not message or not message.photo or not user:
        return

    user_id = user.id

    # -----------------------------------------------------
    # 16 ЧАСОВ
    # -----------------------------------------------------

    last_photo = get_last_photo_time(user_id)

    if last_photo:

        difference = utc_now() - last_photo

        cooldown = timedelta(
            hours=COOLDOWN_HOURS
        )

        if difference < cooldown:

            remaining = cooldown - difference

            total_seconds = max(
                0,
                int(
                    remaining.total_seconds()
                )
            )

            hours = total_seconds // 3600

            minutes = (
                total_seconds % 3600
            ) // 60

            await message.reply_text(
                "⏳ Ты уже отправлял фотографию!\n\n"

                f"Следующую фотографию можно "
                f"отправить через "
                f"{hours} ч. {minutes} мин.\n\n"

                "Спасибо за участие! ❤️"
            )

            return

    # -----------------------------------------------------
    # DOWNLOAD PHOTO
    # -----------------------------------------------------

    telegram_photo = message.photo[-1]

    telegram_file = await context.bot.get_file(
        telegram_photo.file_id
    )

    filename = (
        f"{user_id}_"
        f"{int(utc_now().timestamp())}.jpg"
    )

    file_path = PHOTO_DIR / filename

    await telegram_file.download_to_drive(
        custom_path=str(file_path)
    )

    # -----------------------------------------------------
    # HASH
    # -----------------------------------------------------

    try:

        photo_hash = calculate_photo_hash(
            file_path
        )

    except Exception:

        if file_path.exists():
            file_path.unlink()

        await message.reply_text(
            "❌ Не получилось обработать фотографию.\n\n"
            "Попробуй отправить её ещё раз."
        )

        return

    # -----------------------------------------------------
    # DUPLICATE CHECK
    # -----------------------------------------------------

    if photo_used_recently(
        user_id,
        photo_hash
    ):

        if file_path.exists():
            file_path.unlink()

        await message.reply_text(
            "❌ Эта фотография уже участвовала "
            "в одном из твоих последних двух баттлов!\n\n"

            "Пожалуйста, отправь другой снимок.\n\n"

            "Мы хотим, чтобы каждый баттл "
            "был интересным и разнообразным! ❤️"
        )

        return

    # -----------------------------------------------------
    # SAVE TO DATABASE
    # -----------------------------------------------------

    save_photo(
        user_id=user_id,
        telegram_file_id=telegram_photo.file_id,
        file_path=str(file_path),
        photo_hash=photo_hash
    )

    update_last_photo_time(user_id)

    # -----------------------------------------------------
    # USER INFO
    # -----------------------------------------------------

    if user.username:
        username = f"@{user.username}"
    else:
        username = user.full_name

    sent_at = kyiv_now().strftime(
        "%d.%m.%Y %H:%M"
    )

    # -----------------------------------------------------
    # MESSAGE TO ADMIN
    # -----------------------------------------------------

    admin_caption = (
        "📤 МЕДИА НА КОНКУРС\n\n"

        f"👤 Участник: {username}\n"

        f"🆔 ID: {user.id}\n"

        f"🕒 {sent_at}"
    )

    try:

        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=telegram_photo.file_id,
            caption=admin_caption
        )

    except Exception:

        logger.exception(
            "Не удалось отправить фото администратору"
        )

    # -----------------------------------------------------
    # CONFIRMATION TO USER
    # -----------------------------------------------------

    await message.reply_text(
        "✅ Фотография успешно принята!\n\n"

        "📸 Твой снимок добавлен в очередь "
        "на ближайший баттл.\n\n"

        "Всё хорошо, спасибо за участие! ❤️\n"

        "Желаем удачи и пусть победит сильнейший!"
    )


# =========================================================
# OTHER MESSAGES
# =========================================================

async def other_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.message:

        await update.message.reply_text(
            "📸 Отправь мне именно фотографию."
        )


# =========================================================
# ADMIN CHECK
# =========================================================

def is_admin(update):

    return (
        update.effective_user
        and update.effective_user.id == ADMIN_ID
    )


# =========================================================
# QUEUE
# =========================================================

def get_queue():

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM photos

        WHERE status = 'queued'

        ORDER BY id ASC
    """).fetchall()

    conn.close()

    return rows


async def queue(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update):
        return

    photos = get_queue()

    await update.message.reply_text(
        f"📸 В очереди сейчас: "
        f"{len(photos)} фотографий."
    )


# =========================================================
# PUBLISH BATTLE
# =========================================================

async def publish(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update):
        return

    photos = get_queue()

    if not photos:

        await update.message.reply_text(
            "📭 Очередь пустая."
        )

        return

    battle_number = (
        get_last_battle() + 1
    )

    published_ids = []

    # Максимум 10 фото в одном media group
    for i in range(
        0,
        len(photos),
        10
    ):

        batch = photos[
            i:i + 10
        ]

        media = []
        opened_files = []

        try:

            for photo in batch:

                file = open(
                    photo["file_path"],
                    "rb"
                )

                opened_files.append(
                    file
                )

                media.append(
                    InputMediaPhoto(
                        media=file
                    )
                )

            await context.bot.send_media_group(
                chat_id=CHANNEL_ID,
                media=media
            )

            published_ids.extend(
                photo["id"]
                for photo in batch
            )

        finally:

            for file in opened_files:

                file.close()

    # -----------------------------------------------------
    # MARK AS PUBLISHED
    # -----------------------------------------------------

    conn = get_db()

    for photo_id in published_ids:

        conn.execute("""
            UPDATE photos

            SET
                status = 'published',
                battle_number = ?

            WHERE id = ?
        """, (
            battle_number,
            photo_id
        ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Баттл №{battle_number} опубликован!\n\n"

        f"📸 Фотографий: "
        f"{len(published_ids)}"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "❌ Не указан BOT_TOKEN"
        )

    if not CHANNEL_ID:

        raise RuntimeError(
            "❌ Не указан CHANNEL_ID"
        )

    if not ADMIN_ID:

        raise RuntimeError(
            "❌ Не указан ADMIN_ID"
        )

    init_database()

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Команды
    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "queue",
            queue
        )
    )

    application.add_handler(
        CommandHandler(
            "publish",
            publish
        )
    )

    # Фото
    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    # Остальные сообщения
    application.add_handler(
        MessageHandler(
            ~filters.COMMAND
            & ~filters.PHOTO,
            other_message
        )
    )

    logger.info(
        "🤖 Photo Battle Bot started"
    )

    application.run_polling()


if __name__ == "__main__":
    main()import os
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import imagehash
from PIL import Image
from dotenv import load_dotenv
from telegram import Update, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")

# ОДНО ФОТО РАЗ В 16 ЧАСОВ
COOLDOWN_HOURS = 16

# Сколько последних баттлов запрещено использовать
# ту же фотографию
BLOCK_BATTLES = 2

DB_FILE = "photo_battle.db"
PHOTO_DIR = Path("photos")

# Киевское время
KYIV_TZ = ZoneInfo("Europe/Kyiv")

PHOTO_DIR.mkdir(exist_ok=True)

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("photo-battle")


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            last_photo_time TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            telegram_file_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            photo_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            battle_number INTEGER,
            status TEXT DEFAULT 'queued'
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# TIME
# =========================================================

def utc_now():
    return datetime.now(timezone.utc)


def kyiv_now():
    return datetime.now(KYIV_TZ)


def get_last_photo_time(user_id):
    conn = get_db()

    row = conn.execute(
        """
        SELECT last_photo_time
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    if not row or not row["last_photo_time"]:
        return None

    return datetime.fromisoformat(
        row["last_photo_time"]
    )


def update_last_photo_time(user_id):
    conn = get_db()

    conn.execute("""
        INSERT INTO users (
            user_id,
            last_photo_time
        )

        VALUES (?, ?)

        ON CONFLICT(user_id)

        DO UPDATE SET
            last_photo_time = excluded.last_photo_time
    """, (
        user_id,
        utc_now().isoformat()
    ))

    conn.commit()
    conn.close()


# =========================================================
# BATTLES
# =========================================================

def get_last_battle():
    conn = get_db()

    row = conn.execute(
        """
        SELECT MAX(battle_number) AS battle
        FROM photos
        """
    ).fetchone()

    conn.close()

    return row["battle"] or 0


# =========================================================
# PHOTO HASH
# =========================================================

def calculate_photo_hash(file_path):
    image = Image.open(file_path)

    # Perceptual hash позволяет распознавать
    # одинаковые/почти одинаковые фотографии
    # даже после сжатия или изменения размера
    photo_hash = imagehash.phash(image)

    return str(photo_hash)


# =========================================================
# DUPLICATE CHECK
# =========================================================

def photo_used_recently(user_id, photo_hash):

    current_battle = get_last_battle()

    if current_battle == 0:
        return False

    minimum_battle = max(
        1,
        current_battle - BLOCK_BATTLES + 1
    )

    conn = get_db()

    row = conn.execute("""
        SELECT id
        FROM photos

        WHERE user_id = ?

        AND photo_hash = ?

        AND battle_number IS NOT NULL

        AND battle_number >= ?

        LIMIT 1
    """, (
        user_id,
        photo_hash,
        minimum_battle
    )).fetchone()

    conn.close()

    return row is not None


# =========================================================
# SAVE PHOTO
# =========================================================

def save_photo(
    user_id,
    telegram_file_id,
    file_path,
    photo_hash
):

    conn = get_db()

    conn.execute("""
        INSERT INTO photos (
            user_id,
            telegram_file_id,
            file_path,
            photo_hash,
            created_at,
            status
        )

        VALUES (?, ?, ?, ?, ?, 'queued')
    """, (
        user_id,
        telegram_file_id,
        file_path,
        photo_hash,
        utc_now().isoformat()
    ))

    conn.commit()
    conn.close()


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "👋 Привет!\n\n"

        "📸 Это бот фотобатлов.\n\n"

        "Ты можешь отправлять одну фотографию "
        "раз в 16 часов.\n\n"

        "⚠️ Одна и та же фотография не может "
        "повторно участвовать в ближайших "
        "двух баттлах.\n\n"

        "Просто отправь фотографию сюда."
    )


# =========================================================
# PHOTO HANDLER
# =========================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message
    user = update.effective_user

    if not message or not message.photo or not user:
        return

    user_id = user.id

    # -----------------------------------------------------
    # 16 ЧАСОВ
    # -----------------------------------------------------

    last_photo = get_last_photo_time(user_id)

    if last_photo:

        difference = utc_now() - last_photo

        cooldown = timedelta(
            hours=COOLDOWN_HOURS
        )

        if difference < cooldown:

            remaining = cooldown - difference

            total_seconds = max(
                0,
                int(
                    remaining.total_seconds()
                )
            )

            hours = total_seconds // 3600

            minutes = (
                total_seconds % 3600
            ) // 60

            await message.reply_text(
                "⏳ Ты уже отправлял фотографию!\n\n"

                f"Следующую фотографию можно "
                f"отправить через "
                f"{hours} ч. {minutes} мин.\n\n"

                "Спасибо за участие! ❤️"
            )

            return

    # -----------------------------------------------------
    # DOWNLOAD PHOTO
    # -----------------------------------------------------

    telegram_photo = message.photo[-1]

    telegram_file = await context.bot.get_file(
        telegram_photo.file_id
    )

    filename = (
        f"{user_id}_"
        f"{int(utc_now().timestamp())}.jpg"
    )

    file_path = PHOTO_DIR / filename

    await telegram_file.download_to_drive(
        custom_path=str(file_path)
    )

    # -----------------------------------------------------
    # HASH
    # -----------------------------------------------------

    try:

        photo_hash = calculate_photo_hash(
            file_path
        )

    except Exception:

        if file_path.exists():
            file_path.unlink()

        await message.reply_text(
            "❌ Не получилось обработать фотографию.\n\n"
            "Попробуй отправить её ещё раз."
        )

        return

    # -----------------------------------------------------
    # DUPLICATE CHECK
    # -----------------------------------------------------

    if photo_used_recently(
        user_id,
        photo_hash
    ):

        if file_path.exists():
            file_path.unlink()

        await message.reply_text(
            "❌ Эта фотография уже участвовала "
            "в одном из твоих последних двух баттлов!\n\n"

            "Пожалуйста, отправь другой снимок.\n\n"

            "Мы хотим, чтобы каждый баттл "
            "был интересным и разнообразным! ❤️"
        )

        return

    # -----------------------------------------------------
    # SAVE TO DATABASE
    # -----------------------------------------------------

    save_photo(
        user_id=user_id,
        telegram_file_id=telegram_photo.file_id,
        file_path=str(file_path),
        photo_hash=photo_hash
    )

    update_last_photo_time(user_id)

    # -----------------------------------------------------
    # USER INFO
    # -----------------------------------------------------

    if user.username:
        username = f"@{user.username}"
    else:
        username = user.full_name

    sent_at = kyiv_now().strftime(
        "%d.%m.%Y %H:%M"
    )

    # -----------------------------------------------------
    # MESSAGE TO ADMIN
    # -----------------------------------------------------

    admin_caption = (
        "📤 МЕДИА НА КОНКУРС\n\n"

        f"👤 Участник: {username}\n"

        f"🆔 ID: {user.id}\n"

        f"🕒 {sent_at}"
    )

    try:

        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=telegram_photo.file_id,
            caption=admin_caption
        )

    except Exception:

        logger.exception(
            "Не удалось отправить фото администратору"
        )

    # -----------------------------------------------------
    # CONFIRMATION TO USER
    # -----------------------------------------------------

    await message.reply_text(
        "✅ Фотография успешно принята!\n\n"

        "📸 Твой снимок добавлен в очередь "
        "на ближайший баттл.\n\n"

        "Всё хорошо, спасибо за участие! ❤️\n"

        "Желаем удачи и пусть победит сильнейший!"
    )


# =========================================================
# OTHER MESSAGES
# =========================================================

async def other_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.message:

        await update.message.reply_text(
            "📸 Отправь мне именно фотографию."
        )


# =========================================================
# ADMIN CHECK
# =========================================================

def is_admin(update):

    return (
        update.effective_user
        and update.effective_user.id == ADMIN_ID
    )


# =========================================================
# QUEUE
# =========================================================

def get_queue():

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM photos

        WHERE status = 'queued'

        ORDER BY id ASC
    """).fetchall()

    conn.close()

    return rows


async def queue(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update):
        return

    photos = get_queue()

    await update.message.reply_text(
        f"📸 В очереди сейчас: "
        f"{len(photos)} фотографий."
    )


# =========================================================
# PUBLISH BATTLE
# =========================================================

async def publish(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update):
        return

    photos = get_queue()

    if not photos:

        await update.message.reply_text(
            "📭 Очередь пустая."
        )

        return

    battle_number = (
        get_last_battle() + 1
    )

    published_ids = []

    # Максимум 10 фото в одном media group
    for i in range(
        0,
        len(photos),
        10
    ):

        batch = photos[
            i:i + 10
        ]

        media = []
        opened_files = []

        try:

            for photo in batch:

                file = open(
                    photo["file_path"],
                    "rb"
                )

                opened_files.append(
                    file
                )

                media.append(
                    InputMediaPhoto(
                        media=file
                    )
                )

            await context.bot.send_media_group(
                chat_id=CHANNEL_ID,
                media=media
            )

            published_ids.extend(
                photo["id"]
                for photo in batch
            )

        finally:

            for file in opened_files:

                file.close()

    # -----------------------------------------------------
    # MARK AS PUBLISHED
    # -----------------------------------------------------

    conn = get_db()

    for photo_id in published_ids:

        conn.execute("""
            UPDATE photos

            SET
                status = 'published',
                battle_number = ?

            WHERE id = ?
        """, (
            battle_number,
            photo_id
        ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Баттл №{battle_number} опубликован!\n\n"

        f"📸 Фотографий: "
        f"{len(published_ids)}"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "❌ Не указан BOT_TOKEN"
        )

    if not CHANNEL_ID:

        raise RuntimeError(
            "❌ Не указан CHANNEL_ID"
        )

    if not ADMIN_ID:

        raise RuntimeError(
            "❌ Не указан ADMIN_ID"
        )

    init_database()

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Команды
    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "queue",
            queue
        )
    )

    application.add_handler(
        CommandHandler(
            "publish",
            publish
        )
    )

    # Фото
    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    # Остальные сообщения
    application.add_handler(
        MessageHandler(
            ~filters.COMMAND
            & ~filters.PHOTO,
            other_message
        )
    )

    logger.info(
        "🤖 Photo Battle Bot started"
    )

    application.run_polling()


if __name__ == "__main__":
    main()
