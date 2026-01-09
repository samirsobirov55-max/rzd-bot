import asyncio
import re
import time
import os
import traceback
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.exceptions import TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiohttp import web

# --- НАСТРОЙКИ ---
TOKEN = os.getenv('BOT_TOKEN') 
ADMIN_ID = 7913733869 # Твой ID

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

user_messages = {}
active_chats = set()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv("PORT", 8080)))
    await site.start()

# --- ФУНКЦИЯ УВЕДОМЛЕНИЯ ВСЕХ АДМИНОВ ---
async def notify_all_admins(chat_id, text):
    """Находит всех админов чата и шлет им сообщение в личку"""
    try:
        admins = await bot.get_chat_administrators(chat_id)
        for admin in admins:
            if not admin.user.is_bot:
                try:
                    await bot.send_message(admin.user.id, f"🔔 **ОТЧЕТ МОДЕРАЦИИ**\nГруппа: {chat_id}\n\n{text}")
                except Exception:
                    # Если админ не запустил бота в ЛС, сообщение не дойдет
                    pass
    except Exception as e:
        logging.error(f"Ошибка рассылки админам: {e}")

# --- СПИСОК МАТОВ (БЕЗ ИЗМЕНЕНИЙ) ---
BAD_WORDS = [
    r"\bху[йеияёю]\w*\b", r"\bхул[иея]\b", r"\bоху[ее]\w*\b", r"\bпоху\w*\b",
    r"\bпизд\w*\b", r"\bпропизд\w*\b", r"\bвыпизд\w*\b", r"\bеб[аеёиоуя]\w*\b", 
    r"\bёб\w*\b", r"\bвыёб\w*\b", r"\bзаеб\w*\b", r"\bдоеб\w*\b", r"\bебл[аио]\w*\b",
    r"\bбля[тд]\w*\b", r"\bблд\b", r"\bсук\w*\b", r"\bсуч[ьея]\w*\b",
    r"\bмуд[аик]\w*\b", r"\bгн[ио]да\b", r"\bговн\w*\b", r"\bгандон\w*\b", 
    r"\bпид[оа]р\w*\b", r"\bпед[оа]р\w*\b", r"\bшлюх\w*\b", r"\bшалав\w*\b",
    r"\bзалуп\w*\b", r"\bкурв\w*\b", r"\bчмо\b", r"\bдроч\w*\b", r"\bмраз\w*\b",
    r"\bублюд\w*\b", r"\bвырод\w*\b", r"\bдаун\b", r"\bдебил\w*\b", r"\bпорно\b",
    r"\bсекс\b", r"\bчлен\b", r"\bсиськ\w*\b", r"\bхентай\b", r"\bтрах\w*\b",
    r"\bсосать\b", r"\bминет\b", r"\bголая\b", r"\bголый\b", r"\bвлагалищ\w*\b",
    r"\bпенис\b", r"\bпедикулез\b", r"\bспид\b", r"\bгероин\b", r"\bнаркот\w*\b"
]

RULES_TEXT = (
    "🗓 **Правила чата**\n\n"
    "1️⃣ **Уважение**: Без оскорблений. (мут 24 ч → бан)\n"
    "2️⃣ **Спам**: Без флуда. (мут 1–12 ч)\n"
    "3️⃣ **Контент**: Без 18+. (моментальный бан)\n"
    "4️⃣ **Политика**: Запрещена. (мут 6 ч)\n"
    "5️⃣ **Мошенничество**: Robux запрещены. (БАН)\n"
    "6️⃣ **Roblox**: Соблюдаем правила платформы. (мут 24 ч)\n"
    "7️⃣ **Реклама**: Ссылки запрещены. (мут 24 ч)\n"
    "8️⃣ **Профили**: Без мата. (мут до исправления)\n"
    "9️⃣ **Админ**: Решения не обсуждаются. (мут 12 ч)\n"
    "🔟 **Атмосфера**: Будьте вежливы! ❤️"
)

# --- РАССЫЛКА ПО РАСПИСАНИЮ ---
async def send_morning():
    for chat_id in list(active_chats):
        try: await bot.send_message(chat_id, "☀️ **Доброе утро, команда!**\nПродуктивной смены! 🚂💨")
        except: pass

async def send_night():
    for chat_id in list(active_chats):
        try: await bot.send_message(chat_id, "🌙 **Смена окончена!**\nСпокойной ночи! 💤")
        except: pass

# --- ФУНКЦИЯ НАКАЗАНИЯ ---
async def punish(message: types.Message, reason: str, hours=0, is_ban=False):
    try:
        uid = message.from_user.id
        name = message.from_user.full_name
        member = await bot.get_chat_member(message.chat.id, uid)
        if member.status in ["administrator", "creator"]: return
        
        await message.delete()
        
        log_msg = f"Пользователь: {name} ({uid})\nПричина: {reason}\nДействие: "
        
        if is_ban:
            await bot.ban_chat_member(message.chat.id, uid)
            log_msg += "БАН НАВСЕГДА"
        else:
            mute_time = hours if hours > 0 else 1
            until = datetime.now() + timedelta(hours=mute_time)
            await bot.restrict_chat_member(message.chat.id, uid, permissions=types.ChatPermissions(can_send_messages=False), until_date=until)
            log_msg += f"МУТ НА {mute_time} ч."
            
        # Отправляем лог только админам в ЛС
        await notify_all_admins(message.chat.id, log_msg)
        
    except Exception:
        logging.error(traceback.format_exc())

# --- ОБРАБОТЧИКИ ---
@dp.message(F.new_chat_members)
async def on_join(message: types.Message):
    active_chats.add(message.chat.id)
    for user in message.new_chat_members:
        if user.id != bot.id:
            await message.answer(f"👋 Привет, {user.first_name}!\n\n{RULES_TEXT}")

@dp.message()
async def main_mod(message: types.Message):
    if not message.text or message.chat.type == "private": return
    active_chats.add(message.chat.id)
    
    if message.text == "/rules":
        await message.answer(RULES_TEXT)
        return

    text = message.text.lower()
    now = time.time()
    uid = message.from_user.id

    # 1. Анти-спам
    if uid in user_messages and now - user_messages[uid] < 0.7:
        await punish(message, "Спам/Флуд", hours=1)
        return
    user_messages[uid] = now

    # 2. Анти-скам
    if any(x in text for x in ["robux", "робукс", "продам акк"]):
        await punish(message, "Мошенничество", is_ban=True)
        return

    # 3. Ссылки
    if "http" in text or "t.me/" in text:
        await punish(message, "Реклама", hours=24)
        return

    # 4. Мат
    clean_text = re.sub(r"[^а-яёa-z\s]", "", text)
    if any(re.search(p, clean_text) for p in BAD_WORDS):
        await punish(message, "Мат", hours=24)
        return

async def main():
    await start_web_server()
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(send_morning, CronTrigger(hour=8, minute=0))
    scheduler.add_job(send_night, CronTrigger(hour=22, minute=0))
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
