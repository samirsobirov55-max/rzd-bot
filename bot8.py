import random
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import asyncio
import re
import time
import os
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ChatPermissions, ChatMemberUpdated, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import ChatMemberUpdatedFilter
from aiohttp import web
active_groups = set()

# --- НАСТРОЙКИ ---
TOKEN = os.getenv('BOT_TOKEN') 
OWNER_ID = 7913733869        # <--- ВСТАВЬ СВОЙ ID СЮДА
MY_GROUP_ID = -1002974508454  # <--- ВСТАВЬ ID ГРУППЫ СЮДА

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

user_messages = {}
active_chats = set()
warns = {} 

# Новые переменные для защиты от рейдов:
join_history = []
RAID_THRESHOLD = 3  # Порог входа (человек)
RAID_WINDOW = 1    # Промежуток времени (секунд)
# Списки для хранения истории наказаний (сбрасываются при перезагрузке бота на Render)
ban_list_history = {}  # {user_id: "имя (причина)"}
mute_list_history = {} # {user_id: "имя (до какого времени)"}

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
    r"\bсекс\b", r"\bчлен\b", r"\bсиськ\w*\b", r"\bхентай\b", r"\bтрах\w*\b",
    r"\bсосать\b", r"\bминет\b", r"\bголая\b", r"\bголый\b", r"\bвлагалищ\w*\b",
    r"\bпенис\b", r"\bпедикулез\b", r"\bспид\b", r"\bгероин\b", r"\bнаркот\w*\b", 
    r"\bнахуй\w*\b", r"\bнах\w*\b", r"\bипан\w*\b", r"\bиба\w*\b", r"\сосешь\w*\b"
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
                    pass 
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
            ban_list_history[uid] = f"{name} (Причина: {reason})"
            action = "БАН НАВСЕГДА"
            await message.answer(f"🚫 Пользователь {name} забанен.\nПричина: {reason}")
            
        elif is_warn:
            warns[uid] = warns.get(uid, 0) + 1
            if warns[uid] == 3:
                until = datetime.now() + timedelta(hours=24)
                finish_time = until.strftime("%d.%m %H:%M")
                mute_list_history[uid] = f"{name} (до {finish_time})"
                await bot.restrict_chat_member(chat_id, uid, permissions=ChatPermissions(can_send_messages=False), until_date=until)
                action = "МУТ 24ч (3/3 ВАРНА)"
                await message.answer(f"🤫 {name} получил 3/3 варна. Мут на 24 часа!\nПричина: {reason}")
            elif warns[uid] > 3:
                await bot.ban_chat_member(chat_id, uid)
                action = "БАН (РЕЦИДИВ)"
                await message.answer(f"🚫 {name} забанен за рецидив.\nПричина: {reason}")
                warns[uid] = 0
            else:
                action = f"ВАРН {warns[uid]}/3"
                await message.answer(f"⚠️ {name} получил предупреждение {warns[uid]}/3.\nПричина: {reason}")
        
        else:
            until = datetime.now() + timedelta(hours=hours)
            finish_time = until.strftime("%d.%m %H:%M")
            await bot.restrict_chat_member(chat_id, uid, permissions=ChatPermissions(can_send_messages=False), until_date=until)
            action = f"МУТ НА {hours}ч"
            await message.answer(f"Пользователь {name} заглушен до {finish_time}.\nПричина: {reason}")

        # Логи вынесены за пределы условий, чтобы работать ВСЕГДА
        log = f"Чат: {message.chat.title}\nНарушитель: {name}\nДействие: {action}\nПричина: {reason}"
        if finish_time: log += f"\nОкончание: {finish_time}"
        await send_log_to_admins(chat_id, log)

    except Exception as e:
        logging.error(f"Ошибка в punish: {e}")

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.chat.type == "private":
        builder = InlineKeyboardBuilder()
        bot_info = await bot.get_me()
        url = f"https://t.me/{bot_info.username}?startgroup=true"
        builder.row(types.InlineKeyboardButton(text="➕ Добавить в группу", url=url))
        
        await message.answer(
            f"Привет, {message.from_user.first_name}!\n\n"
            "🛡 Я — бот-модератор. Я защищаю чаты от мата, спама и 18+ контента.\n\n"
            "ℹ️ **Для админов:**\n"
            "Нажав эту кнопку, вы разрешили мне присылать вам отчеты о нарушениях в личку.\n\n"
            "Нажмите кнопку ниже, чтобы добавить меня в свой чат:",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )

@dp.message(Command("rules"))
async def cmd_rules(message: types.Message):
    await message.answer(RULES_TEXT)

@dp.message(Command("functions"))
async def cmd_functions(message: types.Message):
    text = (
        "Функции бота-модератора:\n\n"
        "Модерация:\n"
        "- Удаление сообщений с английскими буквами (латиницей).\n"
        "- Авто-предупреждения и мут за мат.\n"
        "- Бан за рекламу, спам и мошенничество (робуксы).\n"
        "- Мут за обсуждение действий админа или политику.\n\n"
        "Автоматизация:\n"
        "- Пожелание доброго утра ровно в 08:00 (МСК).\n"
        "- Пожелание спокойной ночи ровно в 22:00 (МСК).\n\n"
        "Команды:\n"
        "- /rules — показать правила чата.\n"
        "- /function — список всех возможностей.\n"
        "- Напиши слово бот — проверить статус работы."
    )
    await message.answer(text)

@dp.message(Command("info"))
async def cmd_info(message: types.Message):
    text = (
        "«РЖД» — это вертикально интегрированный холдинг, являющийся естественной монополией и одной из крупнейших транспортных систем в мире. "
        "Компания была создана 1 октября 2003 года на базе Министерства путей сообщения РФ. Весь пакет акций (100%) принадлежит государству в лице Правительства РФ.\n\n"
        "Масштаб и инфраструктура:\n"
        "Железнодорожная сеть России имеет эксплуатационную длину более 85 000 км, из которых почти половина электрифицирована. "
        "Сеть разделена на 16 территориальных филиалов. Холдинг обеспечивает более 45% всего грузооборота страны и около 30% пассажирских перевозок.\n\n"
        "Основные направления деятельности:\n"
        "- Грузовые перевозки: Главные грузы — уголь, нефть, руда. Приоритет — БАМ и Транссиб.\n"
        "- Пассажирские перевозки: ФПК (дальнее следование), ДОСС (Сапсаны, Ласточки) и пригородные электрички.\n"
        "- Инфраструктурное строительство: Проектирование и стройка путей, мостов и вокзалов.\n\n"
        "Текущее состояние (2025–2026 гг.):\n"
        "В 2026 году инвестпрограмма сфокусирована на безопасности и капремонте. "
        "Продолжается реализация проекта ВСМ-1 (Москва — Санкт-Петербург) со скоростями до 400 км/ч.\n\n"
        "Технологический суверенитет:\n"
        "Переход на отечественные платформы, такие как электропоезд «Финист». Развиваются беспилотное движение на МЦК и квантовые сети.\n\n"
        "Кадровая политика:\n"
        "Более 700 000 сотрудников. РЖД содержит свою сеть больниц, учебных центров и лагерей. "
        "В 2026 году компания активно индексирует зарплаты для привлечения кадров.\n\n"
        "Резюме: РЖД — фундамент экономики России, связывающий огромную территорию страны."
    )
    await message.answer(text)

# Команда для просмотра списка забаненных
@dp.message(Command("banlist"))
async def show_banlist(message: types.Message):
    if not await is_admin(message): return
    if not ban_list_history:
        await message.answer("Список банов пуст. Чисто и спокойно! ✨")
        return
    text = "Список забаненных:\n\n"
    for uid, info in ban_list_history.items():
        text += f"• ID {uid}: {info}\n"
    await message.answer(text)

# Команда для просмотра списка мутов
@dp.message(Command("mutelist"))
async def show_mutelist(message: types.Message):
    if not await is_admin(message): return
    if not mute_list_history:
        await message.answer("Сейчас никто не молчит. Все общаются! 🗣")
        return
    text = "Список мутов:\n\n"
    for uid, info in mute_list_history.items():
        text += f"• ID {uid}: {info}\n"
    await message.answer(text)

@dp.message(F.text.lower() == "бот")
async def bot_status(message: types.Message):
    await message.answer("✅ На месте")

@dp.message(F.new_chat_members)
async def anti_raid_welcome(message: types.Message):
    global join_history
    now = time.time()
    join_history = [t for t in join_history if now - t < RAID_WINDOW]
    for user in message.new_chat_members:
        if user.id == bot.id:
            await message.answer("Здравствуйте! Назначьте меня администратором для работы.")
            continue
        join_history.append(now)
        if len(join_history) > RAID_THRESHOLD:
            try:
                await bot.ban_chat_member(message.chat.id, user.id)
                await message.answer(f"⚠️ Обнаружена атака! Пользователь {user.full_name} забанен. Причина: Рейдер")
                log_text = f"Чат: {message.chat.title}\nДействие: БАН (Anti-Raid)\nНарушитель: {user.full_name}\nПричина: Рейдер"
                await send_log_to_admins(message.chat.id, log_text)
            except: pass
        else:
            try:
                await message.answer(f"Привет, {user.first_name}! Ознакомься с правилами: /rules")
            except Exception as e:
                logging.error(f"Не удалось отправить приветствие: {e}")

@dp.my_chat_member()
async def on_promoted(event: ChatMemberUpdated):
    if event.new_chat_member.status in ["administrator", "creator"]:
        await bot.send_message(event.chat.id, "Права получены! Начинаю следить за порядком.")

@dp.message(Command("id"))
async def get_id(message: types.Message):
    await message.answer(f"ID этого чата: {message.chat.id}\nТвой ID: {message.from_user.id}")

@dp.message()
async def global_mod(message: types.Message):
    # Хендлер копирования для Владельца (в личке)
    if message.chat.type == "private" and message.from_user.id == OWNER_ID:
        if message.text and message.text.startswith("/"):
            pass # Если команда, идем дальше к проверкам команд
        else:
            try:
                await message.copy_to(chat_id=MY_GROUP_ID)
                await message.delete()
                return
            except Exception as e:
                await message.answer(f"❌ Ошибка копирования: {e}")
                return

    if message.chat.type in ['group', 'supergroup']:
        active_groups.add(message.chat.id)
    if not message.text or await is_admin(message): 
           return

    uid = message.from_user.id
    if re.search(r'[a-zA-Z]', message.text):
        try:
            await message.delete()
            return
        except: return

    text = message.text.lower()
    super_clean_text = re.sub(r"[^а-яё]", "", text) 

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
    if re.search(r"\bшлюх\w*\b", text):
        await punish(message, "Тяжелые оскорбления (БАН)", is_ban=True)
        return
    
    for pattern in BAD_WORDS:
        base_word = re.sub(r"[^а-яё]", "", pattern.replace(r"\b", "").replace(r"\w*", ""))
        if base_word and base_word in super_clean_text:
            await punish(message, "Использование мата (Пункт 1)", is_warn=True)
            return

    now = time.time()
    if uid in user_messages and now - user_messages[uid] < 0.7:
        await punish(message, "Спам/Флуд (Пункт 2)", hours=1)
        return
    user_messages[uid] = now

# --- ЗАПУСК ---
async def send_scheduled_msg(mode):
    if not active_groups: return
    morning_texts = ["☀️ Доброе утро, чат! Просыпаемся! ☕", "🌅 Всем прекрасного утра! ✨"]
    night_texts = ["🌙 Время 22:00. Всем спокойной ночи! 😴", "🌃 Пора отдыхать, доброй ночи! 💤"]
    text = random.choice(morning_texts if mode == "morning" else night_texts)
    for chat_id in list(active_groups):
        try: await bot.send_message(chat_id, text)
        except: active_groups.discard(chat_id)

scheduler = AsyncIOScheduler(timezone=timezone("Europe/Moscow"))
scheduler.add_job(send_scheduled_msg, "cron", hour=8, minute=0, args=["morning"])
scheduler.add_job(send_scheduled_msg, "cron", hour=22, minute=0, args=["night"])

async def main():
    class SimpleHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running")

    httpd = HTTPServer(('0.0.0.0', 10000), SimpleHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    logging.info("Фоновый веб-сервер запущен на порту 10000")

    scheduler.start()
    logging.info("Планировщик запущен.")
    logging.info("Бот запущен и готов к работе!")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())












