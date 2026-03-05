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
from aiohttp import web

# --- НАСТРОЙКА ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', force=True)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_ENV = os.getenv("ADMIN_ID")

if not TOKEN or not ADMIN_ID_ENV:
    logger.critical("ОШИБКА: BOT_TOKEN или ADMIN_ID не найдены в переменных окружения!")
    exit(1)
try:
    ADMIN_ID = int(ADMIN_ID_ENV)
except ValueError:
    logger.critical("ОШИБКА: ADMIN_ID должен быть числом.")
    exit(1)

# --- РАБОТА С ИСТОРИЕЙ ---
HISTORY_FILE = "history.json"
def load_history() -> Dict[str, Dict]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except Exception as e: logger.error(f"Ошибка загрузки истории: {e}")
    return {}
def save_history(history: Dict[str, Dict]):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f: json.dump(history, f, ensure_ascii=False, indent=4)
    except Exception as e: logger.error(f"Ошибка сохранения истории: {e}")
def add_to_history(user_id: int, name: str, username: str, text: str):
    history = load_history()
    user_id_str = str(user_id)
    if user_id_str not in history: history[user_id_str] = {"name": name, "username": username, "messages": []}
    timestamp = datetime.now().strftime("%d.%m %H:%M")
    history[user_id_str]["messages"].append(f"[{timestamp}] {text}")
    history[user_id_str]["messages"] = history[user_id_str]["messages"][-20:]
    save_history(history)

# --- ЛОГИКА БОТА ---
class AdminStates(StatesGroup): waiting_for_reply = State()
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
def get_admin_keyboard(user_id: int): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_{user_id}")], [InlineKeyboardButton(text="📜 История", callback_data=f"history_{user_id}")]])
@router.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id == ADMIN_ID: await message.answer("🛠 <b>Панель администратора запущена.</b>")
    else: await message.answer("👋 <b>Привет!</b> Напиши свой вопрос, и я передам его администратору.")
@router.message(F.chat.id != ADMIN_ID)
async def forward_to_admin(message: Message):
    user = message.from_user
    username_text = f" (@{user.username})" if user.username else ""
    user_info = f"👤 <b>{user.full_name}</b>{username_text}\n🆔 <code>{user.id}</code>"
    msg_text = message.text or "[Медиа-файл]"
    add_to_history(user.id, user.full_name, user.username or "", msg_text)
    try:
        await bot.send_message(ADMIN_ID, f"{user_info}\n\n{msg_text}", reply_markup=get_admin_keyboard(user.id))
        await message.answer("✅ <b>Ваше сообщение отправлено!</b>")
    except Exception as e: logger.error(f"Ошибка при пересылке: {e}")
@router.callback_query(F.data.startswith("history_"))
async def handle_history_button(callback: CallbackQuery):
    user_id_str = callback.data.split("_")[1]
    history = load_history()
    if user_id_str not in history or not history[user_id_str]["messages"]: return await callback.answer("История сообщений пуста.")
    user_data = history[user_id_str]
    text = f"📜 <b>История {user_data['name']}:</b>\n\n" + "\n".join(user_data["messages"][-10:])
    await callback.message.answer(text, reply_markup=get_admin_keyboard(user_id_str))
    await callback.answer()
@router.callback_query(F.data.startswith("reply_"))
async def handle_reply_button(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[1])
    await state.update_data(reply_to_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_reply)
    await callback.message.answer(f"📝 <b>Введите ответ для ID: {user_id}</b>")
    await callback.answer()
@router.message(AdminStates.waiting_for_reply, F.chat.id == ADMIN_ID)
async def process_admin_reply(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("reply_to_user_id")
    try:
        await message.copy_to(chat_id=user_id)
        await message.answer(f"🚀 <b>Ответ отправлен пользователю {user_id}!</b>")
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка при ответе: {e}")
        await message.answer(f"❌ <b>Ошибка:</b> {e}")

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle_health_check(request):
    return web.Response(text="Bot is running!")
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000)) # Render использует переменную PORT
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Веб-сервер запущен на порту {port}")

# --- ЗАПУСК ---
async def main():
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    # Запускаем веб-сервер и бота параллельно
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    try:
        logger.info("--- Запуск бота ---")
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
