import asyncio
import re
import time
import os
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ChatPermissions, ChatMemberUpdated
from aiogram.filters import ChatMemberUpdatedFilter
from aiohttp import web

# --- НАСТРОЙКИ ---
TOKEN = os.getenv('BOT_TOKEN') 
# ADMIN_ID удален, бот работает динамически для всех админов

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

user_messages = {}
active_chats = set()
warns = {} 

# --- ВЕБ-СЕРВЕР ---
async def handle(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# --- ПРАВИЛА ЧАТА ---
RULES_TEXT = (
    "Правила чата\n\n"
    "1. Уважение: Без оскорблений. (Варн -> Мут 24ч -> Бан)\n"
    "2. Спам: Без флуда. (Мут 1-12ч)\n"
    "3. Контент: Без 18+. (Мут/Бан)\n"
    "4. Политика: Запрещена. (Мут 6ч)\n"
    "5. Мошенничество: Robux запрещены. (БАН)\n"
    "6. Roblox: Соблюдаем правила платформы. (Мут 24ч)\n"
    "7. Реклама: Ссылки запрещены. (Мут 24ч)\n"
    "8. Профили: Без мата. (Мут до исправления)\n"
    "9. Админ: Решения не обсуждаются. (Мут 12ч)\n"
    "10. Атмосфера: Будьте дружелюбны!"
)

# --- СПИСОК МАТОВ ---
BAD_WORDS = [
    r"\bху[йеияёю]\w*\b", r"\bхул[иея]\b", r"\bоху[ее]\w*\b", r"\bпоху\w*\b",
    r"\bпизд\w*\b", r"\bпропизд\w*\b", r"\bвыпизд\w*\b", r"\bеб[аеёиоуя]\w*\b", 
    r"\bёб\w*\b", r"\bвыёб\w*\b", r"\bзаеб\w*\b", r"\bдоеб\w*\b", r"\bебл[аио]\w*\b",
    r"\bбля[тд]\w*\b", r"\bблд\b", r"\bсук\w*\b", r"\bсуч[ьея]\w*\b",
    r"\bмуд[аик]\w*\b", r"\bгн[ио]да\b", r"\bговн\w*\b", r"\bгандон\w*\b", 
    r"\bпид[оа]р\w*\b", r"\bпед[оа]р\w*\b", r"\bшлюх\w*\b", r"\bшалав\w*\b",
    r"\bзалуп\w*\b", r"\bкурв\w*\b", r"\bчмо\b", r"\bдроч\w*\b", r"\bмраз\w*\b",
    r"\bублюд\w*\b", r"\bвырод\w*\b", r"\bдаун\b", r"\bдебил\w*\b", r"\bпорно\b",
    r"\bсекс\w*\b", r"\bчлен\b", r"\bсиськ\w*\b", r"\bхентай\b", r"\bтрах\w*\b",
    r"\bсосать\w*\b", r"\bминет\b", r"\bголая\b", r"\bголый\b", r"\bвлагалищ\w*\b",
    r"\bпенис\b", r"\bпедикулез\b", r"\bспид\b", r"\bгероин\b", r"\bнаркот\w*\b", 
    r"\bнахуй\w*\b", r"\bнах\w*\b
]

# --- ЛОГИРОВАНИЕ ДЛЯ ВСЕХ АДМИНОВ ---
async def send_log_to_admins(chat_id, log_text):
    try:
        admins = await bot.get_chat_administrators(chat_id)
        for admin in admins:
            if not admin.user.is_bot:
                try: 
                    await bot.send_message(admin.user.id, "ОТЧЕТ МОДЕРАЦИИ\n\n" + log_text)
                except: 
                    pass # Пропускаем, если админ не нажал /start в личке
    except Exception as e:
        logging.error(f"Ошибка логирования: {e}")

async def is_admin(message: types.Message):
    try:
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in ["administrator", "creator"]
    except: return False

# --- УНИВЕРСАЛЬНАЯ ФУНКЦИЯ НАКАЗАНИЯ ---
async def punish(message: types.Message, reason: str, hours=0, is_ban=False, is_warn=False):
    try:
        if await is_admin(message): return
        uid = message.from_user.id
        name = message.from_user.full_name
        chat_id = message.chat.id
        
        await message.delete()

        action = ""
        finish_time = ""

        if is_ban:
            await bot.ban_chat_member(chat_id, uid)
            action = "БАН НАВСЕГДА"
            await message.answer(f"Пользователь {name} забанен навсегда.\nПричина: {reason}")
        
        elif is_warn:
            warns[uid] = warns.get(uid, 0) + 1
            if warns[uid] >= 3:
                await bot.ban_chat_member(chat_id, uid)
                action = "БАН (3/3 ВАРНА)"
                await message.answer(f"Пользователь {name} забанен за 3/3 предупреждений.\nПричина: {reason}")
                warns[uid] = 0
            else:
                action = f"ВАРН {warns[uid]}/3"
                await message.answer(f"Пользователь {name} получил предупреждение {warns[uid]}/3.\nПричина: {reason}")
        
        else:
            until = datetime.now() + timedelta(hours=hours)
            finish_time = until.strftime("%d.%m %H:%M")
            await bot.restrict_chat_member(chat_id, uid, permissions=ChatPermissions(can_send_messages=False), until_date=until)
            action = f"МУТ НА {hours}ч"
            await message.answer(f"Пользователь {name} заглушен до {finish_time}.\nПричина: {reason}")

        log = f"Чат: {message.chat.title}\nНарушитель: {name}\nДействие: {action}\nПричина: {reason}"
        if finish_time: log += f"\nОкончание: {finish_time}"
        
        await send_log_to_admins(chat_id, log)
    except Exception as e:
        logging.error(f"Ошибка в punish: {e}")

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("rules"))
async def cmd_rules(message: types.Message):
    await message.answer(RULES_TEXT)

@dp.message(F.new_chat_members)
async def welcome(message: types.Message):
    for user in message.new_chat_members:
        if user.id == bot.id:
            await message.answer("Здравствуйте! Я готов к работе. Пожалуйста, назначьте меня администратором.")
        else:
            await message.answer(f"Привет, {user.first_name}! Ознакомься с правилами: /rules")

@dp.my_chat_member()
async def on_promoted(event: ChatMemberUpdated):
    if event.new_chat_member.status in ["administrator", "creator"]:
        await bot.send_message(event.chat.id, "Права получены! Начинаю следить за порядком.")

@dp.message()
async def global_mod(message: types.Message):
    if not message.text or await is_admin(message): return
    text = message.text.lower()
    uid = message.from_user.id

    if any(x in text for x in ["robux", "робукс", "продам акк", "cheat"]):
        await punish(message, "Мошенничество (Пункт 5)", is_ban=True)
        return

    if "http" in text or "t.me/" in text:
        await punish(message, "Реклама (Пункт 7)", hours=24)
        return

    if any(x in text for x in ["политика", "путин", "война", "зеленский"]):
        await punish(message, "Политика (Пункт 4)", hours=6)
        return

    if any(x in text for x in ["админ лох", "почему мут", "тупой бот"]):
        await punish(message, "Обсуждение действий администрации (Пункт 9)", hours=12)
        return

    clean_text = re.sub(r"[^а-яёa-z\s]", "", text)
    if any(re.search(p, clean_text) for p in BAD_WORDS):
        await punish(message, "Использование мата (Пункт 1)", is_warn=True)
        return

    now = time.time()
    if uid in user_messages and now - user_messages[uid] < 0.7:
        await punish(message, "Спам/Флуд (Пункт 2)", hours=1)
        return
    user_messages[uid] = now

# --- ЗАПУСК ---
async def main():
    await start_web_server()
    await dp.start_polling(bot, allowed_updates=["message", "chat_member", "my_chat_member"])

if __name__ == "__main__":
    asyncio.run(main())
