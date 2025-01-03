import uuid
import os
from aiogram import Bot, Dispatcher
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import ChatMemberUpdatedFilter
from aiogram.types import ChatMemberUpdated
import asyncio
import sqlite3

API_TOKEN = "="
ADMIN_IDS = [995460798]
CHANNEL_ID = "-1002478345916"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Подключение к базе данных
conn = sqlite3.connect("suggestions.db")
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    file_id TEXT,
    file_type TEXT,
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
c.execute("ALTER TABLE suggestions ADD COLUMN message_id INTEGER")
conn.commit()

@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=("member", "left", "kicked")))
async def on_member_update(event: ChatMemberUpdated):
    if event.chat.id != int(-1002376147314):
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

@dp.message(lambda message: message.photo or message.animation or message.video or (message.document and message.document.mime_type in ["image/gif", "image/jpeg", "image/png", "video/mp4"]))
async def handle_media(message: Message):
    member = await bot.get_chat_member(-1002376147314, message.from_user.id)
    if member.status not in ["member", "administrator", "creator"]:
        await message.reply("Вы должны быть подписаны на @pudge_hub, чтобы отправлять предложения!")
        return

    banned = c.execute("SELECT user_id FROM banned_users WHERE user_id = ?", (message.from_user.id,)).fetchone()
    if banned:
        #await message.reply("Ты заблокирован и не можешь отправлять предложения.")
        return

    if message.photo:
        file = message.photo[-1]
        file_type = "photo"
    elif message.animation:
        file = message.animation
        file_type = "animation"
    elif message.video:
        file = message.video
        file_type = "video"
    elif message.document and message.document.mime_type in ["image/gif", "image/jpeg", "image/png", "video/mp4"]:
        file = message.document
        file_type = "document"
    else:
        await message.reply("Неподдерживаемый формат файла.")
        return

    response = await message.reply("Файл отправлен на рассмотрение.")

    c.execute("INSERT INTO suggestions (user_id, file_id, file_type, status, message_id) VALUES (?, ?, ?, 'pending', ?)", 
              (message.from_user.id, file.file_id, file_type, response.message_id))
    suggestion_id = c.lastrowid
    conn.commit()

    for admin_id in ADMIN_IDS:
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="👍", callback_data=f"approve_{suggestion_id}")
        keyboard.button(text="👎", callback_data=f"reject_{suggestion_id}")
        keyboard.button(text="🗑️", callback_data=f"ban_{message.from_user.id}")
        keyboard.adjust(3)

        admin_message = None
        if file_type == "photo":
            admin_message = await bot.send_photo(admin_id, file.file_id, caption=f"Предложение от @{message.from_user.username}", 
                                     reply_markup=keyboard.as_markup())
        elif file_type == "animation":
            admin_message = await bot.send_animation(admin_id, file.file_id, caption=f"Предложение от @{message.from_user.username}", 
                                          reply_markup=keyboard.as_markup())
        elif file_type == "video":
            admin_message = await bot.send_video(admin_id, file.file_id, caption=f"Предложение от @{message.from_user.username}", 
                                      reply_markup=keyboard.as_markup())
        elif file_type == "document":
            admin_message = await bot.send_document(admin_id, file.file_id, caption=f"Предложение от @{message.from_user.username}", 
                                         reply_markup=keyboard.as_markup())

        if admin_message:
            c.execute("INSERT INTO admin_messages (user_id, message_id) VALUES (?, ?)", (message.from_user.id, admin_message.message_id))
    conn.commit()

@dp.callback_query(lambda query: query.data.startswith("approve_"))
async def approve_suggestion(callback_query: CallbackQuery):
    suggestion_id = int(callback_query.data.split("approve_")[1])

    suggestion = c.execute("SELECT user_id, file_id, file_type, message_id FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    if not suggestion:
        await callback_query.answer("Ошибка: Предложение не найдено.")
        return

    user_id, file_id, file_type, message_id = suggestion

    try:
        if file_type == "photo":
            await bot.send_photo(CHANNEL_ID, file_id)
        elif file_type == "animation":
            await bot.send_animation(CHANNEL_ID, file_id)
        elif file_type == "video":
            await bot.send_video(CHANNEL_ID, file_id)
        elif file_type == "document":
            await bot.send_document(CHANNEL_ID, file_id)

        # Редактирование сообщения пользователя об одобрении файла
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Ваш файл был одобрен и опубликован! Спасибо за участие."
        )

        c.execute("DELETE FROM suggestions WHERE id = ?", (suggestion_id,))
        conn.commit()

        await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
        await callback_query.answer("Файл одобрен.")
    except Exception as e:
        await callback_query.answer(f"Произошла ошибка при одобрении: {e}")


@dp.callback_query(lambda query: query.data.startswith("reject_"))
async def reject_suggestion(callback_query: CallbackQuery):
    suggestion_id = int(callback_query.data.split("reject_")[1])

    suggestion = c.execute("SELECT user_id, message_id FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    if not suggestion:
        await callback_query.answer("Ошибка: Предложение не найдено.")
        return

    user_id, message_id = suggestion

    try:
        # Редактирование сообщения пользователя об отклонении файла
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="К сожалению, ваш файл был отклонён. Спасибо за участие!"
        )

        c.execute("DELETE FROM suggestions WHERE id = ?", (suggestion_id,))
        conn.commit()

        await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
        await callback_query.answer("Файл отклонён.")
    except Exception as e:
        await callback_query.answer(f"Произошла ошибка при отклонении: {e}")

@dp.callback_query(lambda query: query.data.startswith("ban_"))
async def ban_user(callback_query: CallbackQuery):
    user_id = int(callback_query.data.split("ban_")[1])

    # Добавление пользователя в список забаненных
    c.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id,))
    conn.commit()

    # Получение всех предложений пользователя
    suggestions = c.execute("SELECT id, message_id FROM suggestions WHERE user_id = ?", (user_id,)).fetchall()

    for suggestion in suggestions:
        suggestion_id, message_id = suggestion

        # Попытка изменить сообщение пользователя на "[УДАЛЕНО]"
        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text="[УДАЛЕНО]"
            )
        except Exception as e:
            print(f"Не удалось изменить сообщение {message_id} для пользователя {user_id}: {e}")

        # Удаление сообщения у администраторов
        admin_messages = c.execute("SELECT message_id FROM admin_messages WHERE user_id = ?", (user_id,)).fetchall()
        for admin_message in admin_messages:
            try:
                await bot.delete_message(callback_query.message.chat.id, admin_message[0])
            except Exception as e:
                print(f"Ошибка при удалении сообщения {admin_message[0]}: {e}")

        # Удаление из базы данных
        c.execute("DELETE FROM suggestions WHERE id = ?", (suggestion_id,))
        c.execute("DELETE FROM admin_messages WHERE user_id = ?", (user_id,))
    conn.commit()

    await callback_query.answer("Пользователь забанен, его предложения удалены.")

    # Уведомление пользователя о блокировке
    try:
        await bot.send_photo(user_id, "https://i.imgur.com/vJSJciT.jpeg", caption="Вы были заблокированы и больше не можете пользоваться ботом.")
    except Exception as e:
        print(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    dp.chat_member.register(on_member_update)
    dp.message.register(start, Command("start"))
    dp.message.register(handle_media, lambda message: message.photo or message.animation or message.video or message.document)
    dp.callback_query.register(approve_suggestion, lambda query: query.data.startswith("approve_"))
    dp.callback_query.register(reject_suggestion, lambda query: query.data.startswith("reject_"))
    dp.callback_query.register(ban_user, lambda query: query.data.startswith("ban_"))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
