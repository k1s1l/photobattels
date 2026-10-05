# Photo Battle Bot

Telegram-бот для фотобатлов.

- 1 фото раз в 4 часа.
- Повтор фото запрещён в ближайших 2 баттлах.
- SQLite хранит очередь и историю.
- `/queue` — очередь.
- `/publish` — публикация очереди в канал.

Установка:
```bash
pip install -r requirements.txt
python bot.py
```

Создай `.env` на основе `.env.example`:
```env
BOT_TOKEN=токен_от_BotFather
CHANNEL_ID=@твой_канал
ADMIN_ID=твой_числовой_ID
```

Добавь бота администратором канала с правом публикации.

Не загружай `.env`, `photo_battle.db` и `photos/` на GitHub.
