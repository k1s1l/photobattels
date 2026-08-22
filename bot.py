# =========================
# СОСТОЯНИЯ АДМИНКИ
# =========================

class BroadcastState(StatesGroup):
    waiting_broadcast = State()


# =========================
# АДМИН-ПАНЕЛЬ
# =========================

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
                    text="👥 Участники",
                    callback_data="users_count"
                )
            ]
        ]
    )

    await message.answer(
        "🛠 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Выбери действие:",
        reply_markup=keyboard
    )


# =========================
# НАЧАЛО РАССЫЛКИ
# =========================

@dp.callback_query(F.data == "broadcast")
async def broadcast_start(callback, state: FSMContext):

    if callback.from_user.id != ADMIN_ID:
        return

    await state.set_state(BroadcastState.waiting_broadcast)

    await callback.message.answer(
        "📢 <b>РАССЫЛКА</b>\n\n"
        "Отправь одним сообщением текст и ссылку.\n\n"
        "Например:\n\n"
        "Завтра батл! Жду ваши фотографии 🔥\n"
        "https://t.me/photobatteel"
    )

    await callback.answer()


# =========================
# ПОЛУЧЕНИЕ РАССЫЛКИ
# =========================

@dp.message(BroadcastState.waiting_broadcast)
async def send_broadcast(message: Message, state: FSMContext):

    if message.from_user.id != ADMIN_ID:
        return

    text = message.text or ""

    # Ищем ссылку
    link = None

    for word in text.split():
        if word.startswith("https://t.me/") or word.startswith("http://t.me/"):
            link = word
            break

    if not link:
        await message.answer(
            "❌ Не нашёл ссылку на Telegram.\n\n"
            "Отправь сообщение в таком формате:\n\n"
            "Завтра батл! Жду ваши фотографии 🔥\n"
            "https://t.me/photobatteel"
        )
        return

    # Убираем ссылку из текста
    broadcast_text = text.replace(link, "").strip()

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

    # Получаем всех пользователей
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()

    sent = 0
    failed = 0

    await message.answer(
        f"📤 Начинаю рассылку...\n\n"
        f"👥 Получателей: <b>{len(users)}</b>"
    )

    for (user_id,) in users:

        try:

            await bot.send_message(
                user_id,
                broadcast_text,
                reply_markup=keyboard
            )

            sent += 1

            # Чтобы Telegram не ограничил бота
            await asyncio.sleep(0.05)

        except Exception as e:

            print(
                f"Ошибка отправки пользователю {user_id}: {e}"
            )

            failed += 1

    await state.clear()

    await message.answer(
        "✅ <b>РАССЫЛКА ЗАВЕРШЕНА</b>\n\n"
        f"📨 Отправлено: <b>{sent}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>"
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
        f"👥 В базе сейчас <b>{count}</b> участников."
    )

    await callback.answer()


# =========================
# ОБЫЧНЫЕ СООБЩЕНИЯ
# =========================

@dp.message()
async def other(message: Message):

    save_user(message)

    await message.answer(
        "📷 Отправьте фотографию для участия в фото-батле."
    )
