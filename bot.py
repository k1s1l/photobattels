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


# =========================
# НАСТРОЙКИ
# =========================

COOLDOWN = timedelta(hours=14)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()


# =========================
# DATABASE
# =========================

db = sqlite3.connect("battle.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    last_photo INTEGER
)
""")

db.commit()


# =========================
# СОХРАНЕНИЕ ПОЛЬЗОВАТЕЛЯ
# =========================

def save_user(message: Message):

    user_id = message.from_user.id
    username = message.from_user.username

    cursor.execute(
        """
        INSERT INTO users (user_id, username, last_photo)
        VALUES (?, ?, NULL)
        ON CONFLICT(user_id)
        DO UPDATE SET username = excluded.username
        """,
        (user_id, username)
    )

    db.commit()


# =========================
# START
# =========================

@dp.message(Command("start"))
async def start(message: Message):

    save_user(message)

    await message.answer(
        "👋 <b>Добро пожаловать на фото-батл!</b>\n\n"
        "📷 Отправь фотографию для участия.\n\n"
        "⏳ Фотографию можно отправлять раз в 14 часов."
    )


# =========================
# ФОТО
# =========================

@dp.message(F.photo)
async def receive_photo(message: Message):

    save_user(message)

    user_id = message.from_user.id
    now = datetime.now()

    cursor.execute(
        "SELECT last_photo FROM users WHERE user_id = ?",
        (user_id,)
    )

    result = cursor.fetchone()

    # Проверяем cooldown
    if result and result[0] is not None:

        last_photo = datetime.fromtimestamp(result[0])

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
                f"Следующую фотографию можно будет "
                f"отправить через <b>{hours} ч. "
                f"{minutes} мин.</b>"
            )

            return

    # Записываем время
    cursor.execute(
        """
        UPDATE users
        SET last_photo = ?
        WHERE user_id = ?
        """,
        (
            int(now.timestamp()),
            user_id
        )
    )

    db.commit()

    photo = message.photo[-1].file_id

    if message.from_user.username:
        username = f"@{message.from_user.username}"
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


# ==================================================
#                    АДМИНКА
# ==================================================

@dp.message(Command("admin"))
async def admin(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Рассылка",
                    callback_data="admin_broadcast"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Участники",
                    callback_data="admin_users"
                )
            ]
        ]
    )

    await message.answer(
        "🛠 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Выбери действие:",
        reply_markup=keyboard
    )


# ==================================================
#               НАЖАТИЕ "РАССЫЛКА"
# ==================================================

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    await callback.message.answer(
        "📢 <b>Создание рассылки</b>\n\n"
        "Отправь одним сообщением текст и ссылку.\n\n"
        "Пример:\n\n"
        "<code>"
        "Завтра батл! 🔥\n"
        "Жду ваши фотографии!\n\n"
        "https://t.me/photobatteel"
        "</code>\n\n"
        "После этого бот автоматически "
        "разошлёт сообщение всем участникам."
    )

    # Сохраняем режим рассылки
    broadcast_mode[ADMIN_ID] = True

    await callback.answer()


# ==================================================
#                  РАССЫЛКА
# ==================================================

broadcast_mode = {}


@dp.message(F.text)
async def text_handler(message: Message):

    user_id = message.from_user.id

    # =========================
    # АДМИНСКАЯ РАССЫЛКА
    # =========================

    if (
        user_id == ADMIN_ID
        and broadcast_mode.get(ADMIN_ID) is True
    ):

        text = message.text.strip()

        # Ищем Telegram ссылку
        link = None

        for word in text.split():

            if (
                word.startswith("https://t.me/")
                or word.startswith("http://t.me/")
            ):
                link = word
                break

        if not link:

            await message.answer(
                "❌ <b>Ссылка не найдена.</b>\n\n"
                "Отправь сообщение вместе со ссылкой:\n\n"
                "Завтра батл! 🔥\n"
                "Жду ваши фотографии!\n\n"
                "https://t.me/photobatteel"
            )

            return

        # Убираем ссылку из текста
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

        # Получаем пользователей
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

            target_id = row[0]

            try:

                await bot.send_message(
                    chat_id=target_id,
                    text=broadcast_text,
                    reply_markup=keyboard
                )

                sent += 1

                await asyncio.sleep(0.06)

            except Exception as error:

                print(
                    f"Ошибка отправки {target_id}: {error}"
                )

                failed += 1

        broadcast_mode[ADMIN_ID] = False

        await message.answer(
            "✅ <b>РАССЫЛКА ЗАВЕРШЕНА</b>\n\n"
            f"📨 Отправлено: <b>{sent}</b>\n"
            f"❌ Ошибок: <b>{failed}</b>"
        )

        return

    # =========================
    # ОБЫЧНЫЙ ТЕКСТ
    # =========================

    save_user(message)

    await message.answer(
        "📷 Отправьте фотографию "
        "для участия в фото-батле."
    )


# ==================================================
#              КОЛИЧЕСТВО УЧАСТНИКОВ
# ==================================================

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):

    if callback.from_user.id != ADMIN_ID:
        return

    cursor.execute(
        "SELECT COUNT(*) FROM users"
    )

    count = cursor.fetchone()[0]

    await callback.message.answer(
        f"👥 Сейчас зарегистрировано: "
        f"<b>{count}</b> участников."
    )

    await callback.answer()


# ==================================================
#                    ЗАПУСК
# ==================================================

async def main():

    print("BOT STARTED")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
