import asyncio
import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_ID


# =========================
# НАСТРОЙКИ
# =========================

COOLDOWN_HOURS = 14

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher(storage=MemoryStorage())


# =========================
# БАЗА ДАННЫХ
# =========================

db = sqlite3.connect("battle.db")
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
# СОСТОЯНИЯ АДМИНКИ
# =========================

class BroadcastState(StatesGroup):
    waiting_text = State()
    waiting_link = State()


# =========================
# СОХРАНЕНИЕ ПОЛЬЗОВАТЕЛЯ
# =========================

def save_user(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username

    cursor.execute(
        """
        INSERT OR IGNORE INTO users (user_id, username, last_photo)
        VALUES (?, ?, NULL)
        """,
        (user_id, username)
    )

    cursor.execute(
        """
        UPDATE users SET username = ?
        WHERE user_id = ?
        """,
        (username, user_id)
    )

    db.commit()


# =========================
# /START
# =========================

@dp.message(Command("start"))
async def start(message: Message):

    save_user(message)

    await message.answer(
        "👋 <b>Добро пожаловать на фото-батл!</b>\n\n"
        "📷 Отправь свою фотографию для участия.\n\n"
        "⏳ Одну фотографию можно отправлять раз в 14 часов."
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
    if result and result[0]:

        last_photo = datetime.fromtimestamp(result[0])

        time_passed = now - last_photo

        cooldown = timedelta(hours=COOLDOWN_HOURS)

        if time_passed < cooldown:

            remaining = cooldown - time_passed

            total_seconds = int(remaining.total_seconds())

            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60

            await message.answer(
                f"⏳ <b>Фотография уже была отправлена!</b>\n\n"
                f"Следующую фотографию можно будет отправить через "
                f"<b>{hours} ч. {minutes} мин.</b>"
            )

            return

    # Запоминаем время отправки
    cursor.execute(
        """
        UPDATE users
        SET last_photo = ?
        WHERE user_id = ?
        """,
        (int(now.timestamp()), user_id)
    )

    db.commit()

    photo = message.photo[-1].file_id

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "Нет username"
    )

    formatted_time = now.strftime("%d.%m.%Y %H:%M")

    caption = (
        f"📤 <b>МЕДИА НА КОНКУРС</b>\n\n"
        f"👤 Участник: {username}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"🕒 {formatted_time}"
    )

    await bot.send_photo(
        ADMIN_ID,
        photo,
        caption=caption
    )

    await message.answer(
        "✅ <b>Фотография успешно отправлена на батл!</b>\n\n"
        "⏳ Следующую фотографию можно будет отправить через 14 часов."
    )


# =========================
# ДРУГИЕ СООБЩЕНИЯ
# =========================

@dp.message()
async def other(message: Message):

    save_user(message)

    await message.answer(
        "📷 Отправьте фотографию для участия в фото-батле."
    )


# ==========================================================
#                         АДМИНКА
# ==========================================================

@dp.message(Command("admin"))
async def admin_panel(message: Message):

    if message.from_user.id != ADMIN_ID:
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Рассылка",
                    callback_data="broadcast"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Количество участников",
                    callback_data="users_count"
                )
            ]
        ]
    )

    await message.answer(
        "🛠 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Выберите действие:",
        reply_markup=keyboard
    )


# =========================
# КНОПКА РАССЫЛКИ
# =========================

@dp.callback_query(F.data == "broadcast")
async def broadcast_start(callback, state: FSMContext):

    if callback.from_user.id != ADMIN_ID:
        return

    await callback.message.answer(
        "📢 <b>Рассылка</b>\n\n"
        "Напиши текст сообщения.\n\n"
        "Например:\n"
        "<code>Завтра батл! Жду ваши фотографии 🔥</code>"
    )

    await state.set_state(BroadcastState.waiting_text)

    await callback.answer()


# =========================
# ПОЛУЧАЕМ ТЕКСТ
# =========================

@dp.message(BroadcastState.waiting_text)
async def broadcast_text(message: Message, state: FSMContext):

    if message.from_user.id != ADMIN_ID:
        return

    await state.update_data(text=message.text)

    await message.answer(
        "🔗 Теперь отправь ссылку на Telegram-канал.\n\n"
        "Например:\n"
        "<code>https://t.me/your_channel</code>"
    )

    await state.set_state(BroadcastState.waiting_link)


# =========================
# ПОЛУЧАЕМ ССЫЛКУ И РАССЫЛАЕМ
# =========================

@dp.message(BroadcastState.waiting_link)
async def broadcast_link(message: Message, state: FSMContext):

    if message.from_user.id != ADMIN_ID:
        return

    link = message.text.strip()

    if not link.startswith(("https://t.me/", "http://t.me/")):
        await message.answer(
            "❌ Похоже, это не ссылка на Telegram.\n\n"
            "Отправь ссылку вида:\n"
            "<code>https://t.me/your_channel</code>"
        )
        return

    data = await state.get_data()
    text = data["text"]

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

    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()

    sent = 0
    failed = 0

    await message.answer(
        f"📤 Начинаю рассылку...\n"
        f"👥 Получателей: <b>{len(users)}</b>"
    )

    for (user_id,) in users:

        try:

            await bot.send_message(
                user_id,
                text,
                reply_markup=keyboard
            )

            sent += 1

            # Небольшая пауза между сообщениями
            await asyncio.sleep(0.05)

        except Exception:
            failed += 1

    await state.clear()

    await message.answer(
        "✅ <b>Рассылка завершена!</b>\n\n"
        f"📨 Отправлено: <b>{sent}</b>\n"
        f"❌ Не удалось отправить: <b>{failed}</b>"
    )


# =========================
# КОЛИЧЕСТВО УЧАСТНИКОВ
# =========================

@dp.callback_query(F.data == "users_count")
async def users_count(callback):

    if callback.from_user.id != ADMIN_ID:
        return

    cursor.execute("SELECT COUNT(*) FROM users")

    count = cursor.fetchone()[0]

    await callback.message.answer(
        f"👥 Сейчас в базе: <b>{count}</b> участников."
    )

    await callback.answer()


# =========================
# ЗАПУСК
# =========================

async def main():

    print("🤖 Бот запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
