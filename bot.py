import asyncio
import logging
import os
import json
from typing import Any, Dict, List
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_ENV = os.getenv("ADMIN_ID")

if not TOKEN or not ADMIN_ID_ENV:
    logger.error("Ошибка: Токен или ID администратора не найдены в .env файле!")
    exit(1)

try:
    ADMIN_ID = int(ADMIN_ID_ENV)
except ValueError:
    logger.error("Ошибка: ADMIN_ID в .env файле должен быть числом!")
    exit(1)

# Файл для хранения истории
HISTORY_FILE = "history.json"

def load_history() -> Dict[str, Dict]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки истории: {e}")
            return {}
    return {}

def save_history(history: Dict[str, Dict]):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения истории: {e}")

def add_to_history(user_id: int, name: str, username: str, text: str):
    history = load_history()
    user_id_str = str(user_id)
    
    if user_id_str not in history:
        history[user_id_str] = {
            "name": name,
            "username": username,
            "messages": []
        }
    
    # Добавляем сообщение с меткой времени
    timestamp = datetime.now().strftime("%d.%m %H:%M")
    history[user_id_str]["messages"].append(f"[{timestamp}] {text}")
    
    # Ограничиваем историю последних 20 сообщений
    if len(history[user_id_str]["messages"]) > 20:
        history[user_id_str]["messages"] = history[user_id_str]["messages"][-20:]
    
    save_history(history)

# Состояния для FSM
class AdminStates(StatesGroup):
    waiting_for_reply = State()

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# Функция для создания кнопок управления для админа
def get_admin_keyboard(user_id: int):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_{user_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user_id}")
        ],
        [
            InlineKeyboardButton(text="📜 История", callback_data=f"history_{user_id}")
        ]
    ])
    return keyboard

@router.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("🛠 <b>Панель администратора запущена.</b>\n\nИспользуйте кнопки под сообщениями для ответа или просмотра истории.")
    else:
        await message.answer("👋 <b>Привет!</b> Напиши свой вопрос или сообщение, и я передам его администратору.")

@router.message(Command("cancel"), StateFilter(AdminStates.waiting_for_reply))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ <b>Отправка ответа отменена.</b>")

@router.message(Command("users"), F.from_user.id == ADMIN_ID)
async def cmd_users(message: Message):
    history = load_history()
    if not history:
        await message.answer("📭 Список пользователей пуст.")
        return
    
    text = "👤 <b>Список написавших пользователей:</b>\n\n"
    keyboard_buttons = []
    
    for user_id_str, data in history.items():
        username = f" (@{data['username']})" if data['username'] else ""
        button_text = f"{data['name']}{username}"
        keyboard_buttons.append([InlineKeyboardButton(text=button_text, callback_data=f"history_{user_id_str}")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await message.answer(text, reply_markup=keyboard)

# Обработка сообщений от пользователей (не админов)
@router.message(F.chat.id != ADMIN_ID)
async def forward_to_admin(message: Message):
    user = message.from_user
    username_text = f" (@{user.username})" if user.username else ""
    user_info = f"👤 <b>{user.full_name}</b>{username_text}\n🆔 <code>{user.id}</code>"
    
    # Сохраняем в историю
    msg_text = message.text if message.text else "[Медиа-файл]"
    add_to_history(user.id, user.full_name, user.username or "", msg_text)
    
    keyboard = get_admin_keyboard(user.id)
    
    try:
        if message.text:
            await bot.send_message(ADMIN_ID, f"{user_info}\n\n{message.text}", reply_markup=keyboard)
        else:
            caption = (message.caption or "") + f"\n\n{user_info}"
            await message.copy_to(chat_id=ADMIN_ID, caption=caption, reply_markup=keyboard)
        
        await message.answer("✅ <b>Ваше сообщение отправлено!</b> Ожидайте ответа.")
    except Exception as e:
        logger.error(f"Ошибка при пересылке: {e}")
        await message.answer("❌ Произошла ошибка при отправке сообщения.")

# Обработка нажатия на кнопку "История"
@router.callback_query(F.data.startswith("history_"))
async def handle_history_button(callback: CallbackQuery):
    user_id_str = callback.data.split("_")[1]
    history = load_history()
    
    if user_id_str not in history or not history[user_id_str]["messages"]:
        await callback.answer("История сообщений пуста.")
        return
    
    user_data = history[user_id_str]
    messages = user_data["messages"]
    
    text = f"📜 <b>История сообщений от {user_data['name']}:</b>\n\n"
    text += "\n".join(messages[-10:]) # Показываем последние 10 сообщений
    
    # Кнопка для ответа прямо из истории
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить пользователю", callback_data=f"reply_{user_id_str}")]
    ])
    
    await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()

# Обработка нажатия на кнопку "Ответить"
@router.callback_query(F.data.startswith("reply_"))
async def handle_reply_button(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[1])
    await state.update_data(reply_to_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_reply)
    
    await callback.message.answer(f"📝 <b>Введите ответ для пользователя</b> (ID: {user_id}):\n\nЧтобы отменить, нажмите /cancel")
    await callback.answer()

# Обработка нажатия на кнопку "Отклонить"
@router.callback_query(F.data.startswith("reject_"))
async def handle_reject_button(callback: CallbackQuery):
    user_id = int(callback.data.split("_")[1])
    
    try:
        await bot.send_message(user_id, "❌ <b>Ваше обращение было отклонено администратором.</b>")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(f"✅ Уведомление об отклонении отправлено пользователю {user_id}.")
    except Exception as e:
        logger.error(f"Ошибка при отклонении: {e}")
        await callback.message.answer(f"❌ Не удалось отправить уведомление.")
    
    await callback.answer()

# Обработка текста ответа от админа
@router.message(AdminStates.waiting_for_reply, F.chat.id == ADMIN_ID)
async def process_admin_reply(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("reply_to_user_id")
    
    try:
        await message.copy_to(chat_id=user_id)
        await message.answer(f"🚀 <b>Ответ успешно отправлен пользователю {user_id}!</b>")
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка при отправке ответа: {e}")
        await message.answer(f"❌ <b>Ошибка:</b> {e}")

# Регистрация роутера и запуск
dp.include_router(router)

async def main():
    logger.info("--- БОТ ЗАПУЩЕН (ВЕРСИЯ С ИСТОРИЕЙ) ---")
    logger.info(f"Админ ID: {ADMIN_ID}")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
