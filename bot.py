import asyncio
import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN, ADMIN_ID


# ==========================================
# НАСТРОЙКИ
# ==========================================

COOLDOWN = timedelta(hours=14)


# ==========================================
# BOT
# ==========================================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()


# ==========================================
# DATABASE
# ==========================================

db = sqlite3.connect(
    "battle.db",
    check_same_thread=False
)

cursor = db.cursor()


cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_seen INTEGER,
    last_seen INTEGER,
    last_photo INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    created_at INTEGER
)
""")

db.commit()


# ==========================================
# СОХРАНЕНИЕ ПОЛЬЗОВАТЕЛЯ
# ==========================================

def save_user(message: Message):

    user_id = message.from_user.id
    username = message.from_user.username
    now = int(datetime.now().timestamp())

    cursor.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user_id,)
    )

    exists = cursor.fetchone()

    if exists:

        cursor.execute(
            """
            UPDATE users
            SET username = ?, last_seen = ?
            WHERE user_id = ?
            """,
            (
                username,
                now,
                user_id
            )
        )

    else:

        cursor.execute(
            """
            INSERT INTO users
            (
                user_id,
                username,
                first_seen,
                last_seen,
                last_photo
            )
            VALUES (?, ?, ?, ?, NULL)
            """,
            (
                user_id,
                username,
                now,
                now
            )
        )

    db.commit()


# ==========================================
# /START
# ==========================================

@dp.message(Command("start"))
async def start(message: Message):

    save_user(message)

    await message.answer(
        "👋 <b>Добро пожаловать на фото-батл!</b>\n\n"
        "📷 Отправь фотографию для участия.\n\n"
        "⏳ Фотографию можно отправлять "
        "раз в 14 часов."
    )


# ==========================================
# ФОТО
# ==========================================

@dp.message(F.photo)
async def receive_photo(message: Message):

    save_user(message)

    user_id = message.from_user.id
    now = datetime.now()
    timestamp = int(now.timestamp())

    # Получаем последнее фото
    cursor.execute(
        """
        SELECT last_photo
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    result = cursor.fetchone()

    # Проверяем 14 часов
    if result and result[0] is not None:

        last_photo = datetime.fromtimestamp(
            result[0]
        )

        passed = now - last_photo

        if passed < COOLDOWN:

            remaining = COOLDOWN - passed

            total_seconds = int(
                remaining.total_seconds()
            )

            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60

            await message.answer(
                "⏳ <b>Фотография уже отправлена!</b>\n\n"
                f"Следующую фотографию можно отправить "
                f"через <b>{hours} ч. {minutes} мин.</b>"
            )

            return

    # Сохраняем время последнего фото
    cursor.execute(
        """
        UPDATE users
        SET last_photo = ?
        WHERE user_id = ?
        """,
        (
            timestamp,
            user_id
        )
    )

    # Сохраняем фотографию в статистику
    cursor.execute(
        """
        INSERT INTO photos
        (
            user_id,
            created_at
        )
        VALUES (?, ?)
        """,
        (
            user_id,
            timestamp
        )
    )

    db.commit()

    # Получаем фото
    photo = message.photo[-1].file_id

    if message.from_user.username:
        username = (
            f"@{message.from_user.username}"
        )
    else:
        username = "Нет username"

    time_string = now.strftime(
        "%d.%m.%Y %H:%M"
    )

    caption = (
        "📤 <b>МЕДИА НА КОНКУРС</b>\n\n"
        f"👤 Участник: {username}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"🕒 {time_string}"
    )

    # Отправляем админу
    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo,
        caption=caption
    )

    await message.answer(
        "✅ <b>Фотография успешно отправлена!</b>\n\n"
        "⏳ Следующую фотографию можно будет "
        "отправить через 14 часов."
    )


# ==========================================
# АДМИН-ПАНЕЛЬ
# ==========================================

@dp.message(Command("admin"))
async def admin(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="admin_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Рассылка",
                    callback_data="admin_broadcast"
                )
            ]
        ]
    )

    await message.answer(
        "🛠 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Выбери действие:",
        reply_markup=keyboard
    )


# ==========================================
# СТАТИСТИКА
# ==========================================

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:
        return

    now = datetime.now()

    current_timestamp = int(
        now.timestamp()
    )

    day_start = datetime(
        now.year,
        now.month,
        now.day
    )

    day_timestamp = int(
        day_start.timestamp()
    )

    yesterday_timestamp = int(
        (now - timedelta(hours=24)).timestamp()
    )

    # ======================================
    # ВСЕ ПОЛЬЗОВАТЕЛИ
    # ======================================

    cursor.execute(
        "SELECT COUNT(*) FROM users"
    )

    total_users = cursor.fetchone()[0]

    # ======================================
    # АКТИВНЫЕ ЗА 24 ЧАСА
    # ======================================

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE last_seen >= ?
        """,
        (yesterday_timestamp,)
    )

    active_users = cursor.fetchone()[0]

    # ======================================
    # НОВЫЕ СЕГОДНЯ
    # ======================================

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE first_seen >= ?
        """,
        (day_timestamp,)
    )

    new_users = cursor.fetchone()[0]

    # ======================================
    # ВСЕ ФОТО
    # ======================================

    cursor.execute(
        "SELECT COUNT(*) FROM photos"
    )

    total_photos = cursor.fetchone()[0]

    # ======================================
    # ФОТО СЕГОДНЯ
    # ======================================

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM photos
        WHERE created_at >= ?
        """,
        (day_timestamp,)
    )

    today_photos = cursor.fetchone()[0]

    # ======================================
    # СТАТИСТИКА
    # ======================================

    text = (
        "📊 <b>СТАТИСТИКА БОТА</b>\n\n"

        f"👥 Всего пользователей: "
        f"<b>{total_users}</b>\n"

        f"🟢 Активных за 24 часа: "
        f"<b>{active_users}</b>\n"

        f"🆕 Новых сегодня: "
        f"<b>{new_users}</b>\n\n"

        f"📸 Всего фотографий: "
        f"<b>{total_photos}</b>\n"

        f"📸 Фотографий сегодня: "
        f"<b>{today_photos}</b>"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data="admin_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data="admin_back"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


# ==========================================
# НАЗАД
# ==========================================

@dp.callback_query(F.data == "admin_back")
async def admin_back(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="admin_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Рассылка",
                    callback_data="admin_broadcast"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        "🛠 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Выбери действие:",
        reply_markup=keyboard
    )

    await callback.answer()


# ==========================================
# РЕЖИМ РАССЫЛКИ
# ==========================================

broadcast_mode = False


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(
    callback: CallbackQuery
):

    global broadcast_mode

    if callback.from_user.id != ADMIN_ID:
        return

    broadcast_mode = True

    await callback.message.answer(
        "📢 <b>РАССЫЛКА</b>\n\n"
        "Отправь одним сообщением текст "
        "и ссылку.\n\n"

        "Пример:\n\n"

        "Завтра батл! 🔥\n"
        "Жду ваши фотографии!\n\n"

        "https://t.me/photobatteel"
    )

    await callback.answer()


# ==========================================
# РАССЫЛКА
# ==========================================

@dp.message(F.text)
async def text_handler(message: Message):

    global broadcast_mode

    # ======================================
    # РАССЫЛКА АДМИНА
    # ======================================

    if (
        message.from_user.id == ADMIN_ID
        and broadcast_mode
    ):

        text = message.text.strip()

        link = None

        # Ищем ссылку
        for word in text.split():

            if (
                word.startswith("https://t.me/")
                or word.startswith("http://t.me/")
            ):

                link = word
                break

        if not link:

            await message.answer(
                "❌ Ссылка не найдена.\n\n"
                "Отправь текст и ссылку одним сообщением."
            )

            return

        # Убираем ссылку
        broadcast_text = text.replace(
            link,
            ""
        ).strip()

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📢 Наш Telegram-канал",
                        url=link
                    )
                ]
            ]
        )

        cursor.execute(
            "SELECT user_id FROM users"
        )

        users = cursor.fetchall()

        sent = 0
        failed = 0

        await message.answer(
            "📤 <b>Начинаю рассылку...</b>\n\n"
            f"👥 Получателей: <b>{len(users)}</b>"
        )

        for row in users:

            user_id = row[0]

            try:

                await bot.send_message(
                    chat_id=user_id,
                    text=broadcast_text,
                    reply_markup=keyboard
                )

                sent += 1

                await asyncio.sleep(0.06)

            except Exception as error:

                print(
                    f"Ошибка {user_id}: {error}"
                )

                failed += 1

        broadcast_mode = False

        await message.answer(
            "✅ <b>РАССЫЛКА ЗАВЕРШЕНА</b>\n\n"
            f"📨 Отправлено: <b>{sent}</b>\n"
            f"❌ Ошибок: <b>{failed}</b>"
        )

        return

    # ======================================
    # ОБЫЧНЫЙ ТЕКСТ
    # ======================================

    save_user(message)

    await message.answer(
        "📷 Отправьте фотографию "
        "для участия в фото-батле."
    )


# ==========================================
# ЗАПУСК
# ==========================================

async def main():

    print("🤖 BOT STARTED")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
