import asyncio
import re
import time
import os
import traceback
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.exceptions import TelegramBadRequest

# --- НАСТРОЙКИ ---
# TOKEN берется из переменных окружения Railway (BOT_TOKEN)
TOKEN = os.getenv('BOT_TOKEN') 
ADMIN_ID = 7913733869 # Твой ID для получения отчетов об ошибках

bot = Bot(token=TOKEN)
dp = Dispatcher()

user_warns = {}
user_messages = {}

# --- ПОЛНЫЙ СПИСОК МАТОВ И ЗАПРЕТКИ (РАСШИРЕННЫЙ) ---
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

# --- СИСТЕМА ЛОГОВ (ОШИБКИ В ЛС) ---
async def send_admin_log(content, is_error=False):
    prefix = "❌ **КРИТИЧЕСКАЯ ОШИБКА**" if is_error else "🔔 **ЛОГ МОДЕРАЦИИ**"
    try: 
        await bot.send_message(ADMIN_ID, f"{prefix}\n\n{content}")
    except Exception as e: 
        print(f"Не удалось отправить лог админу: {e}")

# --- ФУНКЦИЯ НАКАЗАНИЯ ---
async def punish(message: types.Message, reason: str, hours=0, is_ban=False):
    try:
        uid = message.from_user.id
        name = message.from_user.full_name
        
        # Проверка на админа (их нельзя мутить/банить)
        member = await bot.get_chat_member(message.chat.id, uid)
        if member.status in ["administrator", "creator"]: return
        
        await message.delete()
        
        if is_ban:
            await bot.ban_chat_member(message.chat.id, uid)
            await bot.send_message(message.chat.id, f"🚫 {name} забанен навсегда!\nПричина: {reason}")
        else:
            mute_time = hours if hours > 0 else 1
            until = datetime.now() + timedelta(hours=mute_time)
            await bot.restrict_chat_member(
                message.chat.id, 
                uid, 
                permissions=types.ChatPermissions(can_send_messages=False), 
                until_date=until
            )
            await bot.send_message(message.chat.id, f"⚠️ {name} получил мут на {mute_time} ч.\nПричина: {reason}")
            
        await send_admin_log(f"Чат: {message.chat.title}\nПользователь: {name} ({uid})\nДействие: {'БАН' if is_ban else 'МУТ'}\nПричина: {reason}")
    except Exception:
        await send_admin_log(traceback.format_exc(), is_error=True)

# --- ОБРАБОТКА ВХОДА НОВЫХ УЧАСТНИКОВ ---
@dp.message(F.new_chat_members)
async def on_join(message: types.Message):
    try:
        for user in message.new_chat_members:
            if user.id == bot.id:
                await message.answer("🚂 Модератор РЖД-Бот запущен и готов к работе! Сделайте меня администратором.")
            else:
                await message.answer(f"👋 Привет, {user.first_name}! Добро пожаловать в наш чат.\n\n{RULES_TEXT}")
    except Exception:
        await send_admin_log(traceback.format_exc(), is_error=True)

# --- ОБРАБОТКА МЕДИА (ФОТО/ВИДЕО) ---
@dp.message(F.photo | F.video | F.animation)
async def on_media(message: types.Message):
    if message.caption:
        caption = message.caption.lower()
        if any(re.search(p, caption) for p in BAD_WORDS):
            await punish(message, "Запрещенный контент/мат в описании медиа", is_ban=True)

# --- ОСНОВНАЯ ЛОГИКА МОДЕРАЦИИ ---
@dp.message()
async def main_mod(message: types.Message):
    try:
        if not message.text or message.chat.type == "private": return
        
        # Команда правил
        if message.text == "/rules":
            await message.answer(RULES_TEXT)
            return

        text = message.text.lower()
        now = time.time()
        uid = message.from_user.id

        # 1. Анти-спам (проверка частоты сообщений)
        if uid in user_messages and now - user_messages[uid] < 0.7:
            await punish(message, "Спам/Флуд", hours=1)
            return
        user_messages[uid] = now

        # 2. Анти-скам (робуксы и продажа аккаунтов)
        if any(x in text for x in ["robux", "робукс", "продам акк", "купи робуксы"]):
            await punish(message, "Мошенничество (Robux/Продажа)", is_ban=True)
            return

        # 3. Анти-реклама (ссылки)
        if "http" in text or "t.me/" in text or "t.me +" in text:
            await punish(message, "Реклама сторонних ресурсов", hours=24)
            return

        # 4. Проверка на мат (с очисткой текста от символов)
        clean_text = re.sub(r"[^а-яёa-z\s]", "", text)
        if any(re.search(p, clean_text) for p in BAD_WORDS):
            await punish(message, "Использование нецензурной лексики", hours=24)
            return

    except Exception:
        await send_admin_log(traceback.format_exc(), is_error=True)

async def main():
    print(">>> Бот bot8.py запущен в облаке!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
