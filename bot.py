import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from config import BOT_TOKEN, ADMIN_ID

bot=Bot(BOT_TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp=Dispatcher()

@dp.message(F.photo)
async def receive_photo(message: Message):
    photo=message.photo[-1].file_id
    username=f"@{message.from_user.username}" if message.from_user.username else "Нет username"
    now=datetime.now().strftime("%d.%m.%Y %H:%M")
    caption=(f"📤 <b>МЕДИА НА КОНКУРС</b>\n\n👤 Участник: {username}\n"
             f"🆔 ID: <code>{message.from_user.id}</code>\n🕒 {now}")
    await bot.send_photo(ADMIN_ID,photo,caption=caption)
    await message.answer("✅ Фотография успешно отправлена на батл!")

@dp.message()
async def other(message: Message):
    await message.answer("📷 Отправьте фотографию для участия в фото-батле.")

async def main():
    await dp.start_polling(bot)

if __name__=="__main__":
    asyncio.run(main())
