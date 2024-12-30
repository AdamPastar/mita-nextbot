import uuid
import os
from aiogram import Bot, Dispatcher
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import ChatMemberUpdatedFilter
from aiogram.types import ChatMemberUpdated
import asyncio
import sqlite3

API_TOKEN = "your_bot_token"
ADMIN_IDS = []  # Замените на список ID администраторов
CHANNEL_ID = ""  # Замените на @username вашего канала

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Подключение к базе данных
conn = sqlite3.connect("suggestions.db")
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    file_path TEXT,
    status TEXT
)''')
c.execute('''CREATE TABLE IF NOT EXISTS banned_users (
    user_id INTEGER PRIMARY KEY
)''')
c.execute('''CREATE TABLE IF NOT EXISTS admin_messages (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    message_id INTEGER
)''')
conn.commit()

@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=("member", "left", "kicked")))
async def on_member_update(event: ChatMemberUpdated):
    if event.chat.id != CHANNEL_ID:
        return

    if event.new_chat_member.status == "member":
        await bot.send_message(ADMIN_IDS[0], f"@{event.from_user.username or event.from_user.id} подписался на @pudge_hub 🥰")
    elif event.new_chat_member.status in ["left", "kicked"]:
        await bot.send_message(ADMIN_IDS[0], f"@{event.from_user.username or event.from_user.id} отписался от @pudge_hub 💔")

@dp.message(Command("start"))
async def start(message: Message):
    await message.reply("Привет! Отправь мне картинку, GIF или видео, и я предложу их админам для паблика. Можно прикрепить несколько файлов.")

@dp.message(Command("myid"))
async def get_user_id(message: Message):
    await message.reply(f"Ваш ID: `{message.from_user.id}`", parse_mode="Markdown")

@dp.message(lambda message: message.photo or message.animation or message.video)
async def handle_media(message: Message):
    os.makedirs("downloads", exist_ok=True)  # Создаём папку, если её нет
    print(f"Директория 'downloads' существует: {os.path.exists('downloads')}")

    member = await bot.get_chat_member(CHANNEL_ID, message.from_user.id)
    if member.status not in ["member", "administrator", "creator"]:
        await message.reply("Вы должны быть подписаны на @pudge_hub, чтобы отправлять предложения.")
        return

    banned = c.execute("SELECT user_id FROM banned_users WHERE user_id = ?", (message.from_user.id,)).fetchone()
    if banned:
        await message.reply("Вы заблокированы и не можете отправлять предложения.")
        return

    if message.photo:
        file = message.photo[-1]
        file_extension = "jpg"
    elif message.animation:
        file = message.animation
        file_extension = "gif"
    elif message.video:
        if message.video.duration > 7200:  # Проверяем длительность видео
            await message.reply("Видео должно быть не длиннее 2 часов.")
            return
        file = message.video
        file_extension = "mp4"
    else:
        await message.reply("Неподдерживаемый формат файла.")
        return

    file_info = await bot.get_file(file.file_id)

    unique_name = f"{uuid.uuid4().hex}.{file_extension}"
    file_path = f"downloads/{unique_name}"
    print(f"Сохранение файла в: {file_path}")

    await bot.download_file(file_info.file_path, destination=file_path)
    print(f"Файл сохранён: {file_path}")

    c.execute("INSERT INTO suggestions (user_id, file_path, status) VALUES (?, ?, 'pending')", 
              (message.from_user.id, file_path))
    suggestion_id = c.lastrowid
    conn.commit()

    await message.reply("Файл отправлен на рассмотрение.")

    for admin_id in ADMIN_IDS:
        media_file = FSInputFile(file_path)
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="👍", callback_data=f"approve_{suggestion_id}")
        keyboard.button(text="👎", callback_data=f"reject_{suggestion_id}")
        keyboard.button(text="🗑️", callback_data=f"ban_{message.from_user.id}")
        keyboard.adjust(3)

        if file_extension == "jpg":
            admin_message = await bot.send_photo(admin_id, media_file, caption=f"Предложение от @{message.from_user.username}", 
                                                 reply_markup=keyboard.as_markup())
        elif file_extension == "gif":
            admin_message = await bot.send_animation(admin_id, media_file, caption=f"Предложение от @{message.from_user.username}", 
                                                     reply_markup=keyboard.as_markup())
        elif file_extension == "mp4":
            admin_message = await bot.send_video(admin_id, media_file, caption=f"Предложение от @{message.from_user.username}", 
                                                 reply_markup=keyboard.as_markup())

        c.execute("INSERT INTO admin_messages (user_id, message_id) VALUES (?, ?)", (message.from_user.id, admin_message.message_id))
        conn.commit()

@dp.callback_query(lambda query: query.data.startswith("approve_"))
async def approve_suggestion(callback_query: CallbackQuery):
    suggestion_id = int(callback_query.data.split("approve_")[1])

    suggestion = c.execute("SELECT file_path FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    if not suggestion:
        await callback_query.answer("Ошибка: Предложение не найдено.")
        return

    file_path = suggestion[0]

    media_file = FSInputFile(file_path)
    file_extension = file_path.split(".")[-1]

    if file_extension == "jpg":
        await bot.send_photo(CHANNEL_ID, media_file)
    elif file_extension == "gif":
        await bot.send_animation(CHANNEL_ID, media_file)
    elif file_extension == "mp4":
        await bot.send_video(CHANNEL_ID, media_file)

    c.execute("DELETE FROM suggestions WHERE id = ?", (suggestion_id,))
    conn.commit()

    if os.path.exists(file_path):
        os.remove(file_path)

    await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
    await callback_query.answer("Файл одобрен.")

@dp.callback_query(lambda query: query.data.startswith("reject_"))
async def reject_suggestion(callback_query: CallbackQuery):
    suggestion_id = int(callback_query.data.split("reject_")[1])

    suggestion = c.execute("SELECT file_path FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    if not suggestion:
        await callback_query.answer("Ошибка: Предложение не найдено.")
        return

    file_path = suggestion[0]

    c.execute("DELETE FROM suggestions WHERE id = ?", (suggestion_id,))
    conn.commit()

    if os.path.exists(file_path):
        os.remove(file_path)

    await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
    await callback_query.answer("Файл отклонён.")

@dp.callback_query(lambda query: query.data.startswith("ban_"))
async def ban_user(callback_query: CallbackQuery):
    user_id = int(callback_query.data.split("ban_")[1])

    c.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id,))
    conn.commit()

    suggestions = c.execute("SELECT file_path FROM suggestions WHERE user_id = ?", (user_id,)).fetchall()
    for suggestion in suggestions:
        file_path = suggestion[0]
        if os.path.exists(file_path):
            os.remove(file_path)
    c.execute("DELETE FROM suggestions WHERE user_id = ?", (user_id,))
    conn.commit()

    admin_messages = c.execute("SELECT message_id FROM admin_messages WHERE user_id = ?", (user_id,)).fetchall()
    for message in admin_messages:
        try:
            await bot.delete_message(callback_query.message.chat.id, message[0])
        except Exception as e:
            print(f"Ошибка при удалении сообщения {message[0]}: {e}")
    c.execute("DELETE FROM admin_messages WHERE user_id = ?", (user_id,))
    conn.commit()

    await callback_query.answer("Пользователь забанен, его предложения удалены.")

    try:
        photo_path = "image.jpeg"
        caption = "Вы были заблокированы и больше не можете пользоваться ботом."
        photo = FSInputFile(photo_path)
        await bot.send_photo(user_id, photo, caption=caption)
    except Exception as e:
        print(f"Не удалось отправить сообщение с картинкой пользователю {user_id}: {e}")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    dp.chat_member.register(on_member_update)
    dp.message.register(start, Command("start"))
    dp.message.register(handle_media, lambda message: message.photo or message.animation or message.video)
    dp.callback_query.register(approve_suggestion, lambda query: query.data.startswith("approve_"))
    dp.callback_query.register(reject_suggestion, lambda query: query.data.startswith("reject_"))
    dp.callback_query.register(ban_user, lambda query: query.data.startswith("ban_"))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
