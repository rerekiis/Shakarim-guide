from concurrent.futures import Executor
import sqlite3
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
import json
from datetime import datetime, timedelta
import requests
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from io import BytesIO
from aiogram.types import InputFile
from aiogram.types.input_file import BufferedInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging
import os
from openpyxl import Workbook

# Токен бота
TOKEN = "7797023420:AAGxA9sa-C2Ml-1KkF3fFk7Dct7G5LwOapA"
OPENROUTER_API_KEY = "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"
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
KEYWORDS_FILE = "keywords.json"
DB_FILE = "database.db"
user_state = {}

# Структура базы данных
class UserRegistration(StatesGroup):
    waiting_for_name = State()
    waiting_for_group = State()

class ChatStates(StatesGroup):
    waiting_for_message = State()
    analyzing_message = State()
    finished = State()


def get_db_connection():
    return sqlite3.connect("database.db")

    


def setup_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER UNIQUE NOT NULL,  -- Telegram ID пользователя
    name TEXT NOT NULL,
    group_name TEXT,
    role_id INTEGER NOT NULL,
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS structure (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,         -- ФИО (например, Иванов Иван Иванович)
    position TEXT NOT NULL,     -- Должность (декан, заведующий и т. д.)
    contact TEXT NOT NULL,      -- Контактный номер
    email TEXT UNIQUE NOT NULL, -- Email
    office TEXT NOT NULL,       -- Адрес/кабинет
    schedule TEXT,              -- График работы
    photo_url TEXT,             -- Фото (ссылка на изображение)
    user_id INTEGER,            -- Связь с users (если есть в системе)
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,   -- Название организации
    info TEXT NOT NULL,          -- Информация об организации
    contact TEXT NOT NULL,       -- Контактные данные (номер телефона)
    address TEXT NOT NULL,       -- Адрес организации
    photo_url TEXT               -- Фото (логотип/изображение)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name TEXT NOT NULL,             -- Название мероприятия
    description TEXT NOT NULL,       -- Описание мероприятия
    event_date TIMESTAMP NOT NULL,   -- Дата проведения
    participant_limit INTEGER NOT NULL CHECK (participant_limit > 0),  -- Количество участников
    tg_id INTEGER NOT NULL,          -- Telegram ID создателя мероприятия
    FOREIGN KEY (tg_id) REFERENCES users(tg_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL,      -- Telegram ID пользователя вместо user_id
    message TEXT NOT NULL,
    response TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tg_id) REFERENCES users(tg_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL,      -- Telegram ID администратора вместо admin_id
    action TEXT NOT NULL,
    details TEXT,
    log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tg_id) REFERENCES users(tg_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS event_participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,   -- ID мероприятия
    tg_id INTEGER NOT NULL,      -- Telegram ID участника
    name TEXT NOT NULL,          -- Имя участника
    group_name TEXT NOT NULL,    -- Группа участника
    
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    FOREIGN KEY (tg_id) REFERENCES users(tg_id) ON DELETE CASCADE
);


 CREATE TABLE IF NOT EXISTS faq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT UNIQUE NOT NULL,
    answer TEXT NOT NULL
        );
                         

    """)


    # Создание роли "student", если её нет
    cursor.execute("INSERT OR IGNORE INTO roles (name) VALUES ('student')")
    conn.commit()
    
    conn.close()


from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="Учёба"),
            KeyboardButton(text="Структура")
        ]
    ],
    resize_keyboard=True
)

# Меню "Учёба"
study_menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="Организация"),
            KeyboardButton(text="Информация")
        ],
        [
            KeyboardButton(text="Найти маршрут"),
            KeyboardButton(text="Психолог")
        ],
        [
            KeyboardButton(text="⬅ Назад"),
        ]
    ],
    resize_keyboard=True
)

# Меню "Структура"
structure_menu = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="⬅ Назад")
        ]
    ],
    resize_keyboard=True
)

psychologist_menu=ReplyKeyboardMarkup(
    keyboard=[
        [
               KeyboardButton(text="завершить диалог с ИИ-психологом")
        ]
    ],
    resize_keyboard=True
)



#start
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT name, group_name FROM users WHERE tg_id = ?", (message.from_user.id,))
    user = cursor.fetchone()
    conn.close()

    if user:
        name, group = user
        await message.answer(f"Привет, {name}!\nТы зарегистрирован в группе {group}.", reply_markup=main_menu)
    else:
        await message.answer("Привет, первокурсник! Давай познакомимся. Напиши своё ФИО.")
        await state.set_state(UserRegistration.waiting_for_name)

#форма регистрации
@dp.message(UserRegistration.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Отлично! Теперь укажи свою группу.")
    await state.set_state(UserRegistration.waiting_for_group)


@dp.message(UserRegistration.waiting_for_group)
async def process_group(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    name = user_data["name"]
    group = message.text

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM roles WHERE name = 'student'")
    role_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT OR REPLACE INTO users (tg_id, name, group_name, role_id) VALUES (?, ?, ?, ?)",
        (message.from_user.id, name, group, role_id)
    )
    conn.commit()
    conn.close()

    await message.answer(f"Спасибо, {name}!\nТы зарегистрирован в группе {group}.", reply_markup=main_menu)
    await state.clear()


@dp.message(F.text == "Учёба")
async def show_study_menu(message: types.Message):
    await message.answer("Выберите раздел:", reply_markup=study_menu)

#ЭТО СТРУКТУАРАААААААААААААРААРАРАРРА
def get_db_connection():
    return sqlite3.connect(DB_FILE)

# Функция для получения всех записей по заданной должности
def get_structure_by_role(role: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Если не используете photo_blob, можно его убрать из запроса
    cursor.execute(
        "SELECT name, contact, email, office, schedule, photo_url,photo_blob FROM structure WHERE position = ?",
        (role,)
    )
    data = cursor.fetchall()
    conn.close()
    return data

# Словарь для хранения текущей позиции для каждого чата
user_structure_positions = {}

# Функция отправки карточки сотрудника структуры с пагинацией
async def send_structure_card(chat_id, role: str, position: int):
    persons = get_structure_by_role(role)
    if not persons:
        await bot.send_message(chat_id, "Информация не найдена.")
        return

    person = persons[position]
    name, contact, email, office, schedule, photo_url, photo_blob = person
    response = (
        f"👤 *{name}*\n"
        f"📌 Должность: {role}\n"
        f"📞 Контакты: {contact}\n"
        f"✉ Email: {email}\n"
        f"🏢 Кабинет: {office}\n"
        f"🕒 График: {schedule}"
    )

    keyboard_builder = InlineKeyboardBuilder()
    if position > 0:
        keyboard_builder.button(text="⬅ Назад", callback_data=f"prev_struct_{role}_{position}")
    if position < len(persons) - 1:
        keyboard_builder.button(text="Вперед ➡", callback_data=f"next_struct_{role}_{position}")
    keyboard_builder.button(text="📋 Список должностей", callback_data="show_structure")
    keyboard_builder.adjust(2)

    if photo_blob:
        # Если photo_blob уже является байтами, можно напрямую использовать его
        photo_file = BufferedInputFile(photo_blob, filename="dekan.jpg")
        await bot.send_photo(chat_id, photo_file, caption=response, parse_mode="Markdown", reply_markup=keyboard_builder.as_markup())
    elif photo_url:
        await bot.send_photo(chat_id, photo_url, caption=response, parse_mode="Markdown", reply_markup=keyboard_builder.as_markup())
    else:
        await bot.send_message(chat_id, response, parse_mode="Markdown", reply_markup=keyboard_builder.as_markup())

# Обработчик для текстового сообщения "Структура"
@dp.message(F.text == "Структура")
async def show_structure_immediately(message: types.Message):
    await send_structure_list(message.chat.id)

# Функция отправки списка должностей
async def send_structure_list(chat_id):
    keyboard_builder = InlineKeyboardBuilder()
    roles = ["Ректор", "Декан", "Зам. декана", "Зав. кафедрой"]
    for role in roles:
        keyboard_builder.button(text=role, callback_data=f"struct_{role}")
    keyboard_builder.adjust(1)
    await bot.send_message(chat_id, "Выберите должность:", reply_markup=keyboard_builder.as_markup())

# Обработчик выбора должности из списка
@dp.callback_query(lambda c: c.data.startswith("struct_"))
async def select_structure_role(callback_query: types.CallbackQuery):
    role = callback_query.data.split("_")[1]
    user_structure_positions[callback_query.message.chat.id] = 0
    await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
    await send_structure_card(callback_query.message.chat.id, role, 0)

# Обработчик кнопок пагинации для структуры
@dp.callback_query(lambda c: c.data.startswith(("prev_struct_", "next_struct_")))
async def pagination_structure(callback_query: types.CallbackQuery):
    # Формат callback_data: "prev_struct_{role}_{position}" или "next_struct_{role}_{position}"
    data_parts = callback_query.data.split("_")
    action = data_parts[0]
    role = data_parts[2]
    position = int(data_parts[3])
    persons = get_structure_by_role(role)
    if action == "prev":
        position -= 1
    elif action == "next":
        position += 1

    user_structure_positions[callback_query.message.chat.id] = position
    await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
    await send_structure_card(callback_query.message.chat.id, role, position)

# Обработчик для кнопки "Список должностей"
@dp.callback_query(lambda c: c.data == "show_structure")
async def show_structure_callback(callback_query: types.CallbackQuery):
    try:
        await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
    except Exception as e:
        logging.error(f"Ошибка при удалении сообщения: {e}")
        # Продолжаем выполнение даже если не удалось удалить сообщение
        
    await send_structure_list(callback_query.message.chat.id)


@dp.message(F.text == "⬅ Назад")
async def go_back(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_menu)

#organization
def get_organizations():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, info, contact, address, photo_url FROM organizations")
    data = cursor.fetchall()
    conn.close()
    return data

organizations = get_organizations()
user_positions = {}

# Функция отправки карточки организации
async def send_card(chat_id, position):
    org = organizations[position]
    caption = f"🏢 <b>{org[1]}</b>\n\n{org[2]}\n\n📞 Контакты: {org[3]}\n📍 Адрес: {org[4]}"
    
    keyboard_builder = InlineKeyboardBuilder()

    if position > 0:
        keyboard_builder.button(text="⬅ Назад", callback_data=f"prev_{position}")
    if position < len(organizations) - 1:
        keyboard_builder.button(text="Вперед ➡", callback_data=f"next_{position}")
    
    keyboard_builder.button(text="🏢 Организации", callback_data="show_orgs")
    

    keyboard_builder.adjust(2)  
    keyboard = keyboard_builder.as_markup()

    if org[5]:  
        await bot.send_photo(chat_id, org[5], caption=caption, parse_mode="HTML", reply_markup=keyboard)
    else:
        await bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=keyboard)

# Функция для отправки списка организаций
async def send_organizations_list(chat_id):
    keyboard_builder = InlineKeyboardBuilder()
    
    for i, org in enumerate(organizations):
        keyboard_builder.button(text=org[1], callback_data=f"org_{i}")
     
    keyboard_builder.adjust(1)  
    await bot.send_message(chat_id, "📋 Выберите организацию:", reply_markup=keyboard_builder.as_markup())

# Функция для отправки главного меню
async def send_main_menu(chat_id):
    await bot.send_message(chat_id, "🏠 Добро пожаловать в главное меню!", reply_markup=study_menu)


# Обработчик текстовой кнопки "Организация"
@dp.message(lambda message: message.text == "Организация")
async def show_organizations_by_button(message: types.Message):
    await send_organizations_list(message.chat.id)

# Обработчик кнопок пагинации
@dp.callback_query(lambda c: c.data.startswith(("prev_", "next_")))
async def pagination(callback_query: types.CallbackQuery):
    action, position = callback_query.data.split("_")
    position = int(position)

    if action == "prev":
        position -= 1
    elif action == "next":
        position += 1

    user_positions[callback_query.message.chat.id] = position
    await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
    await send_card(callback_query.message.chat.id, position)

# Обработчик кнопки "Организации"
@dp.callback_query(lambda c: c.data == "show_orgs")
async def show_organizations(callback_query: types.CallbackQuery):
    await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
    await send_organizations_list(callback_query.message.chat.id)

# Обработчик выбора конкретной организации
@dp.callback_query(lambda c: c.data.startswith("org_"))
async def select_organization(callback_query: types.CallbackQuery):
    position = int(callback_query.data.split("_")[1])
    user_positions[callback_query.message.chat.id] = position
    await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
    await send_card(callback_query.message.chat.id, position)

# Обработчик кнопки "Главное меню"
@dp.callback_query(lambda c: c.data == "main_menu")
async def back_to_main_menu(callback_query: types.CallbackQuery):
    await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)
    await send_main_menu(callback_query.message.chat.id)

#психолог ИИ
@dp.message(lambda message: message.text.lower() == "психолог")
async def psychologist_cmd(message: Message, state: FSMContext):
    user_id = message.from_user.id
    last_message = get_last_message(user_id)

    if last_message:
        await message.answer(f"Привет! В прошлый раз ты говорил: '{last_message}'. Как у тебя дела? Решилась ли ситуация?", reply_markup=psychologist_menu)
    else:
        await message.answer("Привет! Я ИИ-психолог 🧠. Расскажи, что тебя беспокоит одним целым текстом, чтобы я мог это обработать и дать тебе решение.", reply_markup=psychologist_menu)
    
    await state.set_state(ChatStates.waiting_for_message)


@dp.message(F.text.in_(["Организация", "Плата", "Социальные часы", "Психолог"]))
async def show_organization_info(message: types.Message):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Выполняем запрос по конкретному названию организации (не ищем все подряд)
    cursor.execute("SELECT name, info, contact, address, photo_url FROM organizations WHERE name = ?", (message.text,))
    org = cursor.fetchone()
    conn.close()

    if org:
        name, info, contact, address, photo_url = org
        response = f"🏢 *{name}*\n📜 {info}\n📞 Контакты: {contact}\n📍 Адрес: {address}"
        
        if photo_url:
            # Если есть фото, отправляем его вместе с информацией
            await message.answer_photo(photo_url, caption=response, parse_mode="Markdown")
        else:
            # Если фото нет, отправляем только текст
            await message.answer(response, parse_mode="Markdown")
    else:
        # Если организация не найдена
        await message.answer("Информация не найдена.")

# 📌 Загрузка ключевых слов
def load_json(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

alert_words = load_json(KEYWORDS_FILE)

def get_last_message(tg_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT message, timestamp FROM chat_history WHERE tg_id = ? ORDER BY timestamp DESC LIMIT 1", (tg_id,))
    last_message = cursor.fetchone()
    conn.close()

    if last_message:
        message_text, timestamp = last_message
        timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")

        # Если последнее сообщение было более 7 дней назад, не упоминать его
        if datetime.now() - timestamp > timedelta(days=7):
            return None

        # Если сообщение слишком короткое или незначительное, не упоминать его
        if len(message_text) < 10 or message_text.lower() in {"ок", "да", "нет", "понятно"}:
            return None

        return message_text
    return None

# Обработчик кнопки "остановить ИИ"
@dp.message(F.text == "завершить диалог с ИИ-психологом")
async def go_back(message: types.Message, state: FSMContext):
    await state.clear()  # Сбрасываем любое текущее состояние
    await message.answer("Вы вернулись в главное меню.", reply_markup=main_menu)


@dp.message(ChatStates.waiting_for_message)
async def analyze_and_respond(message: Message, state: FSMContext):
    text = message.text.lower()
    user_id = message.from_user.id

    found_alert = next((alert_text for word, alert_text in alert_words.items() if word in text), None)
    if found_alert:
        await alert_psychologist(message, found_alert)

    await state.set_state(ChatStates.analyzing_message)


# 🧠 Запрос к OpenRouter
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
    payload = {
    "model": "openai/gpt-3.5-turbo",
    "messages": [
        {
            "role": "system",
            "content": (
                "Ты — профессиональный психолог и чуткий собеседник. "
                "Твоя задача — поддерживать диалог естественно, без давления. "
                "Если человек не хочет продолжать разговор, уважай это и не настаивай. "
                "Отвечай просто, тепло и ненавязчиво."
            ),
        },
        {
            "role": "user",
            "content": "Пациент начал разговор. Ответь просто и дружелюбно, например: 'Понимаю тебя. Расскажи, что больше всего беспокоит?'"
        },
        {
            "role": "assistant",
            "content": "Понимаю тебя. Расскажи, что больше всего беспокоит?"
        },
        {
            "role": "user",
            "content": f"Пациент отвечает: {text}"
        },
        {
            "role": "system",
            "content": (
                "Проанализируй ответ пациента: "
                "- Если он отвечает кратко и уклончиво ('нет', 'не знаю', 'всё нормально'), не дави, просто пожелай хорошего дня. "
                "- Если он хочет говорить — поддержи его, но не задавай лишних вопросов. "
                "- Будь тактичным, избегай шаблонных фраз."
            ),
        }
    ]
}



    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        ai_reply = response.json()["choices"][0]["message"]["content"]
    except requests.RequestException:
        ai_reply = "Извините, я сейчас не могу обработать запрос. Попробуйте позже."

    # 📌 Сохранение в базу данных
    save_message_to_db(user_id, text, ai_reply)

    await message.answer(f"🧠 Психолог: {ai_reply}")
    await state.set_state(ChatStates.waiting_for_message)

def save_message_to_db(tg_id, message, response):
    if len(message.split()) > 15:  
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Проверяем последнее длинное сообщение пользователя
        cursor.execute("""
            SELECT timestamp FROM chat_history 
            WHERE tg_id = ? AND LENGTH(message) - LENGTH(REPLACE(message, ' ', '')) + 1 > 15 
            ORDER BY timestamp DESC LIMIT 1
        """, (tg_id,))
        last_message = cursor.fetchone()

        # Определяем, прошло ли достаточно времени для новой сессии
        if last_message:
            last_time = datetime.strptime(last_message[0], "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_time < timedelta(hours=1):
                conn.close()
                return  

        # Если это первое длинное сообщение или новая сессия, сохраняем
        cursor.execute("""
            INSERT INTO chat_history (tg_id, message, response)
            VALUES (?, ?, ?)
        """, (tg_id, message, response))
        conn.commit()
        conn.close()
# 🚨 Уведомление психолога
async def alert_psychologist(message: types.Message, alert_text: str):
    psychologist_chat_id = "946368702"  # ID психолога

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Проверяем, есть ли пользователь в базе users
    cursor.execute("SELECT name, group_name FROM users WHERE tg_id = ?", (message.from_user.id,))
    student = cursor.fetchone()
    conn.close()

    # Если данные найдены, добавляем их в сообщение
    full_name = student[0] if student else "Неизвестно"
    group_name = student[1] if student else "Неизвестно"

    student_info = (
        f"🚨 {alert_text}\n\n👤 ФИО: {full_name}\n"
        f"🎓 Группа: {group_name}\n📩 Сообщение: {message.text}"
    )

    await bot.send_message(psychologist_chat_id, student_info)



# Подключение к базе данных
def get_faq_data():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT question, answer FROM faq")
    data = cursor.fetchall()
    conn.close()
    return {question: answer for question, answer in data}

ITEMS_PER_PAGE = 3  

class FAQStates(StatesGroup):
    selecting_question = State()

# Генерация клавиатуры с вопросами и пагинацией
def get_faq_keyboard(page=0):
    faq_data = get_faq_data()
    faq_list = list(faq_data.keys())  
    builder = InlineKeyboardBuilder()
    
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE

    for idx, question in enumerate(faq_list[start:end], start):
        builder.button(text=question[:30], callback_data=f"faq:{idx}")  
    
    if start > 0:
        builder.button(text="⬅ Назад", callback_data=f"page:{page-1}")
    if end < len(faq_list):
        builder.button(text="Вперед ➡", callback_data=f"page:{page+1}")

    builder.adjust(1)
    return builder.as_markup()

faq_button = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Частые вопросы")],
        [KeyboardButton(text="Об Университете")],
        [KeyboardButton(text="Студенческая жизнь")],
        [KeyboardButton(text="Социальные сети")],
        [KeyboardButton(text="Библиотека")],
        [KeyboardButton(text="⬅ Назад")]
    ],
    resize_keyboard=True
)

 

@dp.message(F.text == "Информация")
async def show_faq_button(message: types.Message):
    await message.answer("Выберите раздел:", reply_markup=faq_button)


@dp.message(F.text == "Частые вопросы")
async def show_faq_menu(message: types.Message):
    await message.answer("Выберите вопрос:", reply_markup=get_faq_keyboard())

@dp.message(F.text == "Об Университете")
async def show_university_info(message: types.Message):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    # Предполагается, что информация хранится в таблице university_info с полями title и description
    cursor.execute("SELECT description FROM university_info WHERE title = 'Об университете'")
    data = cursor.fetchone()
    conn.close()
    if data:
        await message.answer(data[0])
    else:
        await message.answer("Информация об университете не найдена.")

# Обработчик для кнопки "Студенческая жизнь"
@dp.message(F.text == "Студенческая жизнь")
async def show_student_life_info(message: types.Message):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Предполагается, что информация хранится в таблице student_life с полями title и description
    cursor.execute("SELECT description FROM student_life WHERE title = 'Студенческая жизнь'")
    data = cursor.fetchone()
    conn.close()
    
    if data:
        await message.answer(data[0])
    else:
        await message.answer("Информация о студенческой жизни не найдена.")

@dp.message(F.text == "Социальные сети")
async def show_social_networks(message: types.Message):
    builder = InlineKeyboardBuilder()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT platform FROM social_links")
    data = cursor.fetchall()
    conn.close()
    
    if data:
        for row in data:
            platform = row[0]
            builder.button(text=platform, callback_data=f"social:{platform}")
        builder.adjust(1)
        await message.answer("Выберите социальную сеть:", reply_markup=builder.as_markup())
    else:
        await message.answer("Ссылки на социальные сети не найдены.")

# Обработчик для нажатия на кнопку конкретной соцсети
@dp.callback_query(lambda c: c.data.startswith("social:"))
async def social_callback_handler(callback: types.CallbackQuery):
    platform = callback.data.split(":")[1]
    # Получаем URL для выбранной соцсети из БД
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM social_links WHERE platform = ?", (platform,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        url = result[0]
        builder = InlineKeyboardBuilder()
        # Кнопка "Открыть" – URL-кнопка для перехода
        builder.button(text="Открыть", url=url)
        # Кнопка "Закрыть" – для возврата к списку соцсетей
        builder.button(text="Закрыть", callback_data="close_social")
        builder.adjust(2)
        await callback.message.edit_text(f"Социальная сеть: {platform}", reply_markup=builder.as_markup())
    else:
        await callback.message.answer("Информация не найдена.")

# Обработчик для кнопки "Закрыть", возвращает список социальных сетей
@dp.callback_query(F.data == "close_social")
async def close_social_handler(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT platform FROM social_links")
    data = cursor.fetchall()
    conn.close()
    
    if data:
        for row in data:
            platform = row[0]
            builder.button(text=platform, callback_data=f"social:{platform}")
        builder.adjust(1)
        await callback.message.edit_text("Выберите социальную сеть:", reply_markup=builder.as_markup())
    else:
        await callback.message.edit_text("Ссылки на социальные сети не найдены.")
    await callback.answer("Соц.сети")

@dp.message(F.text == "Библиотека")
async def show_library(message: types.Message):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Извлекаем запись о библиотеке по title
    cursor.execute("SELECT url, description FROM library WHERE title = 'Библиотека'")
    data = cursor.fetchone()
    conn.close()
    
    if data:
        url, description = data
        builder = InlineKeyboardBuilder()
        # Кнопка для перехода по ссылке
        builder.button(text="Открыть библиотеку", url=url)
        builder.adjust(1)
        await message.answer(description, reply_markup=builder.as_markup())
    else:
        await message.answer("Информация о библиотеке не найдена.")

@dp.callback_query(F.data.startswith("page:"))
async def change_page(callback: types.CallbackQuery):
    page = int(callback.data.split(":")[1])
    await callback.message.edit_reply_markup(reply_markup=get_faq_keyboard(page))

@dp.callback_query(F.data.startswith("faq:"))
async def show_answer(callback: types.CallbackQuery):
    idx = int(callback.data.split(":")[1])  
    faq_data = get_faq_data()
    faq_list = list(faq_data.keys()) 
    question = faq_list[idx]  
    answer = faq_data.get(question, "Ответ не найден")
    await callback.message.answer(f"*{question}*\n{answer}", parse_mode="Markdown")

class RouteState(StatesGroup):
    start_building = State()
    end_building = State()

# Координаты корпусов
BUILDINGS = {
    "Главный корпус": [50.39926893087973, 80.21283678151234],
    "3 корпус": [50.411225983226444, 80.23195149826937],
    "8 корпус": [50.44473520679828, 80.2311385313739],
    "9 корпус": [50.40101937972673, 80.21268325391492],
    "Общежитие №1": [50.400693893589136, 80.21582695214042],
    "Общежитие №2": [50.445618, 80.230461],
    "Общежитие №3": [50.423074, 80.235581],
    "Спорткомплекс №1": [50.40238996620285, 80.21023486930758]
}

# Клавиатура с корпусами
def get_building_keyboard():
    building_buttons = [[KeyboardButton(text=corp)] for corp in BUILDINGS.keys()]
    building_buttons.append([KeyboardButton(text="⬅ Назад")])  # Добавляем кнопку "Назад"
    return ReplyKeyboardMarkup(
        keyboard=building_buttons,
        resize_keyboard=True
    )

# Обработчик для кнопки "Назад"
@dp.message(F.text == "⬅ Назад")
async def go_back(message: types.Message, state: FSMContext):
    await message.answer("Главное меню:", reply_markup=main_menu)
    await state.clear()  # Завершаем все состояния

# Начало маршрута
@dp.message(F.text == "Найти маршрут")
async def ask_start_location(message: types.Message, state: FSMContext):
    await message.answer("Выбери начальный корпус:", reply_markup=get_building_keyboard())
    await state.set_state(RouteState.start_building)

# Выбор конечного корпуса
@dp.message(RouteState.start_building)
async def ask_end_location(message: types.Message, state: FSMContext):
    if message.text not in BUILDINGS:
        await message.answer("Выбери корпус из списка!")
        return

    await state.update_data(start_building=message.text)
    await message.answer(f"Начальный корпус: {message.text}\nТеперь выбери конечный корпус:", reply_markup=get_building_keyboard())
    await state.set_state(RouteState.end_building)

# Построение маршрута
@dp.message(RouteState.end_building)
async def get_route(message: types.Message, state: FSMContext):
    if message.text not in BUILDINGS:
        await message.answer("Выбери корпус из списка!")
        return

    data = await state.get_data()
    start_building = data.get("start_building")
    end_building = message.text

    if start_building == end_building:
        await message.answer("Начальный и конечный корпуса совпадают. Выбери другой конечный корпус.")
        return

    await message.answer(f"Строю маршрут из {start_building} в {end_building}...")

    start_coords = BUILDINGS[start_building]
    end_coords = BUILDINGS[end_building]

    # Формирование ссылки для Яндекс.Карт
    yandex_url = f"https://yandex.ru/maps/?rtext={start_coords[0]},{start_coords[1]}~{end_coords[0]},{end_coords[1]}&rtt=pedestrian"

    await message.answer(
        f"🚶 Пешком: маршрут из <b>{start_building}</b> в <b>{end_building}</b>\n"
        f"🔗 <a href='{yandex_url}'>Открыть маршрут в Яндекс.Картах</a>",
        parse_mode="HTML",
        disable_web_page_preview=True
    )

    await state.clear()  



# ADMINKA


ADMIN_ID = [5819205069, 946368702]

event_steps = {}
scheduler = AsyncIOScheduler()


# FSM для смены ролей
class RoleAssignment(StatesGroup):
    waiting_for_tg_id = State()
    waiting_for_role = State()

# FSM для добавления пользователя
class AddUser(StatesGroup):
    waiting_for_tg_id = State()
    waiting_for_name = State()
    waiting_for_role = State()

# FSM для удаления пользователя
class RemoveUser(StatesGroup):
    waiting_for_tg_id = State()

# Функция для подключения к БД с установкой row_factory
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = None
    return conn

def ensure_roles_exist():
    conn = get_db_connection()
    cursor = conn.cursor()
    roles = ['декан', 'преподаватель', 'зам декан', 'зав каф', 'психолог']
    for role in roles:
        cursor.execute("INSERT OR IGNORE INTO roles (name) VALUES (?)", (role,))
    conn.commit()
    conn.close()

ensure_roles_exist()

# Административное меню
admin_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Управление ролями", callback_data="manage_roles")],
        [InlineKeyboardButton(text="Добавить пользователя", callback_data="add_user")],
        [InlineKeyboardButton(text="Удалить пользователя", callback_data="remove_user")]
    ]
)


# Обновляем клавиатуру для панели декана
def get_dekan_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Создать мероприятие", callback_data="create_event")
    builder.button(text="📊 Экспорт пользователей", callback_data="export_users")
    builder.button(text="📋 Экспорт участников мероприятий", callback_data="export_events")
    builder.adjust(1)  # Кнопки в столбик
    return builder.as_markup()

# Клавиатура для психолога
psychologist_panel = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Проблемные студенты", callback_data="problem_students")]
    ]
)

async def problem_students(message: types.Message, alert_text: str):
    """
    Мгновенное уведомление психолога о тревожной ситуации.
    Получает данные студента из БД и отправляет сообщение с указанным текстом тревоги.
    """
    # Получаем данные студента из базы
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, group_name FROM users WHERE tg_id = ?", (message.from_user.id,))
    student = cursor.fetchone()
    conn.close()

    full_name = student["name"] if student else "Неизвестно"
    group_name = student["group_name"] if student else "Неизвестно"

    student_info = (
        f"🚨 {alert_text}\n\n"
        f"👤 ФИО: {full_name}\n"
        f"🎓 Группа: {group_name}\n"
        f"📩 Сообщение: {message.text}"
    )

    # Получаем tg_id психолога из базы
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT tg_id 
        FROM users 
        WHERE role_id = (SELECT id FROM roles WHERE name = 'психолог')
        LIMIT 1
    """)
    result = cursor.fetchone()
    conn.close()

    if result:
        psychologist_chat_id = result["tg_id"]
        await bot.send_message(psychologist_chat_id, student_info)
        
        # Добавляем уведомление в chat_history для психолога
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chat_history (tg_id, message, response) VALUES (?, ?, ?)",
            (psychologist_chat_id, "У вас новая запись (1)", "")
        )
        conn.commit()
        conn.close()
    else:
        logging.error("Психолог не найден в базе данных.")


@dp.callback_query(lambda call: call.data == "problem_students")
async def handle_all_problematic_students(call: types.CallbackQuery):
    logging.info("Обработчик 'Проблемные студенты' вызван. Callback data: %s", call.data)
    
    if not call.message:
        logging.error("Нет сообщения в callback!")
        await call.answer("Ошибка: нет сообщения для ответа.", show_alert=True)
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Получаем tg_id психолога
    cursor.execute("""
        SELECT tg_id 
        FROM users 
        WHERE role_id = (SELECT id FROM roles WHERE name = 'психолог')
        LIMIT 1
    """)
    result = cursor.fetchone()
    if not result:
        logging.error("Не найден психолог в базе данных.")
        conn.close()
        await call.answer("Ошибка: не найден психолог.", show_alert=True)
        return
    
    psychologist_chat_id = result[0]  # Используем индекс вместо ключа
    logging.info("Найден психолог с tg_id: %s", psychologist_chat_id)
    
    # Получаем записи из chat_history
    cursor.execute("""
        SELECT tg_id, message, response, timestamp
        FROM chat_history
        ORDER BY timestamp DESC
    """)
    entries = cursor.fetchall()
    conn.close()
    
    if not entries:
        logging.info("Записей в chat_history не найдено.")
        await call.message.answer("Нет сообщений от студентов.")
    else:
        messages = []
        for entry in entries:
            student_tg_id = entry[0]  # Используем индексы
            student_message = entry[1]
            ai_response = entry[2]
            timestamp = entry[3]
            
            # Получаем ФИО и группу студента
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name, group_name FROM users WHERE tg_id = ?", (student_tg_id,))
            student_data = cursor.fetchone()
            conn.close()
            
            if student_data:
                full_name = student_data[0]  # Используем индексы
                group_name = student_data[1]
            else:
                full_name, group_name = "Неизвестно", "Неизвестно"
            
            messages.append(
                f"👤 {full_name} ({group_name})\n"
                f"🕒 {timestamp}\n"
                f"💬 {student_message}\n"
                f"🤖 {ai_response}\n"
                "-------------------------"
            )
        final_message = "Проблемные студенты:\n\n" + "\n".join(messages)
        logging.info("Отправка сообщения психологу. Начало: %s", final_message[:100])
        await bot.send_message(psychologist_chat_id, final_message)
    
    await call.answer("Запрос обработан", show_alert=True)

@dp.message(Command("admin"))
async def start(message: types.Message):
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row  # Настраиваем возвращаемые строки как словари
    cursor = conn.cursor()  # Теперь создаем курсор после установки row_factory

    cursor.execute("""
        SELECT u.name, r.name as role_name 
        FROM users u
        JOIN roles r ON u.role_id = r.id
        WHERE u.tg_id = ?
    """, (message.from_user.id,))
    
    result = cursor.fetchone()
    conn.close()

    if result:
        user_name = result["name"]
        role_name = result["role_name"].lower()  # Приводим к нижнему регистру для надежности
        welcome_message = f"Добро пожаловать в панель администрации!"

        reply_markup = None  # Указываем по умолчанию
        if role_name == 'психолог':
            reply_markup = psychologist_panel
        elif role_name == 'декан':
            reply_markup = get_dekan_menu()
        elif message.from_user.id in ADMIN_ID:
            reply_markup = admin_menu

        await message.answer(welcome_message, reply_markup=reply_markup)
    else:
        await message.answer("Добро пожаловать! Вы не зарегистрированы в системе.")


# Команда /psychologist для доступа к панели психолога ]

@dp.message(Command("psychologist"))
async def open_psychologist_panel(message: types.Message):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Получаем роль пользователя
    cursor.execute("""
        SELECT r.name as role_name 
        FROM users u 
        JOIN roles r ON u.role_id = r.id 
        WHERE u.tg_id = ?
    """, (message.from_user.id,))
    user_role = cursor.fetchone()
    conn.close()

    if user_role and user_role[0].lower() == 'психолог':
        await message.answer("Панель психолога", reply_markup=psychologist_panel)
    else:
        await message.answer("У вас нет доступа к панели психолога.")

@dp.message(Command("dekan"))
async def open_dekan_panel(message: types.Message):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.name as role_name 
        FROM users u 
        JOIN roles r ON u.role_id = r.id 
        WHERE u.tg_id = ?
    """, (message.from_user.id,))
    result = cursor.fetchone()
    conn.close()

    if result and result[0].lower() == "декан":
        await message.answer("Панель декана", reply_markup=get_dekan_menu())
    else:
        await message.answer("У вас нет доступа к панели декана.")

        
# Обработчик управления ролями
@dp.callback_query(lambda call: call.data == "manage_roles")
async def start_role_assignment(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_ID:
        await call.message.answer("У вас нет прав для выполнения этой команды.")
        return
    await call.message.answer("Введите Telegram ID пользователя, которому хотите назначить новую роль:")
    await state.set_state(RoleAssignment.waiting_for_tg_id)
    await call.answer()

@dp.message(RoleAssignment.waiting_for_tg_id)
async def process_tg_id(message: types.Message, state: FSMContext):
    try:
        tg_id = int(message.text)
        await state.update_data(tg_id=tg_id)
    except ValueError:
        await message.answer("Некорректный Telegram ID. Введите корректное число.")
        return
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row  # Устанавливаем Row
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM roles WHERE name IN ('декан', 'преподаватель', 'зам декан', 'зав каф', 'психолог')")
    roles = cursor.fetchall()
    conn.close()

    if not roles:
        await message.answer("Нет доступных ролей. Добавьте их в систему.")
        return
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=role["name"], callback_data=f"select_role_{role['name']}")] for role in roles]
    )
    await message.answer("Выберите роль, которую хотите назначить пользователю:", reply_markup=keyboard)
    await state.set_state(RoleAssignment.waiting_for_role)

@dp.callback_query(lambda call: call.data.startswith("select_role_"))
async def process_role(call: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    tg_id = user_data["tg_id"]
    new_role = call.data.split("_")[-1].lower()
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM roles WHERE name = ?", (new_role,))
    role = cursor.fetchone()

    if not role:
        await call.message.answer("Такой роли не существует. Создайте её заранее.")
        conn.close()
        return

    role_id = role["id"]
    cursor.execute("UPDATE users SET role_id = ? WHERE tg_id = ?", (role_id, tg_id))
    conn.commit()
    cursor.execute("INSERT INTO admin_logs (tg_id, action, details) VALUES (?, ?, ?)", 
                   (call.from_user.id, "Назначение роли", f"{tg_id} → {new_role}"))
    conn.commit()
    conn.close()

    await call.message.answer(f"Роль пользователя с ID {tg_id} изменена на {new_role}.", reply_markup=admin_menu)
    await state.clear()
    await call.answer()

# Обработчик добавления пользователя
@dp.callback_query(lambda call: call.data == "add_user")
async def add_user_handler(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_ID:
        await call.message.answer("У вас нет прав для выполнения этой команды.")
        return
    await call.message.answer("Введите Telegram ID нового пользователя:")
    await state.set_state(AddUser.waiting_for_tg_id)
    await call.answer()

@dp.message(AddUser.waiting_for_tg_id)
async def process_new_user_tg_id(message: types.Message, state: FSMContext):
    try:
        new_tg_id = int(message.text)
    except ValueError:
        await message.answer("Некорректный Telegram ID. Введите корректное число.")
        return
    await state.update_data(new_tg_id=new_tg_id)
    await message.answer("Введите имя нового пользователя:")
    await state.set_state(AddUser.waiting_for_name)

@dp.message(AddUser.waiting_for_name)
async def process_new_user_name(message: types.Message, state: FSMContext):
    new_name = message.text
    await state.update_data(new_name=new_name)
    allowed_roles = ["декан", "зав каф", "психолог"]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=role.capitalize(), callback_data=f"add_role_{role}")] for role in allowed_roles
    ])
    await message.answer("Выберите роль для нового пользователя:", reply_markup=keyboard)
    await state.set_state(AddUser.waiting_for_role)

@dp.callback_query(lambda call: call.data.startswith("add_role_"))
async def process_new_user_role(call: types.CallbackQuery, state: FSMContext):
    new_role = call.data.split("add_role_")[-1].lower()
    data = await state.get_data()
    new_tg_id = data.get("new_tg_id")
    new_name = data.get("new_name")
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM roles WHERE name = ?", (new_role,))
    role = cursor.fetchone()

    if not role:
        await call.message.answer("Указанная роль не существует в системе. Создайте её заранее.")
        conn.close()
        await state.clear()
        return

    role_id = role["id"]
    try:
        cursor.execute("INSERT INTO users (tg_id, name, group_name, role_id) VALUES (?, ?, ?, ?)",
                       (new_tg_id, new_name, None, role_id))
        conn.commit()
        cursor.execute("INSERT INTO admin_logs (tg_id, action, details) VALUES (?, ?, ?)",
                       (call.from_user.id, "Добавление пользователя", f"{new_tg_id} - {new_name}, роль: {new_role}"))
        conn.commit()
        await call.message.answer(f"Пользователь {new_name} с Telegram ID {new_tg_id} и ролью {new_role} успешно добавлен.", reply_markup=admin_menu)
    except sqlite3.IntegrityError:
        await call.message.answer("Ошибка при добавлении пользователя. Возможно, пользователь с таким Telegram ID уже существует.", reply_markup=admin_menu)

    conn.close()
    await state.clear()
    await call.answer()

# Обработчик удаления пользователя
@dp.callback_query(lambda call: call.data == "remove_user")
async def remove_user_handler(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMIN_ID:
        await call.message.answer("У вас нет прав для выполнения этой команды.")
        return
    await call.message.answer("Введите Telegram ID пользователя, которого хотите удалить:")
    await state.set_state(RemoveUser.waiting_for_tg_id)
    await call.answer()

@dp.message(RemoveUser.waiting_for_tg_id)
async def process_remove_user(message: types.Message, state: FSMContext):
    try:
        tg_id = int(message.text)
    except ValueError:
        await message.answer("Некорректный Telegram ID. Введите корректное число.")
        return
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM users WHERE tg_id = ?", (tg_id,))
    user = cursor.fetchone()

    if not user:
        await message.answer("Пользователь с указанным Telegram ID не найден.", reply_markup=admin_menu)
        conn.close()
        await state.clear()
        return

    cursor.execute("DELETE FROM users WHERE tg_id = ?", (tg_id,))
    conn.commit()
    cursor.execute("INSERT INTO admin_logs (tg_id, action, details) VALUES (?, ?, ?)",
                   (message.from_user.id, "Удаление пользователя", f"Удалён пользователь с Telegram ID {tg_id}"))
    conn.commit()
    conn.close()

    await message.answer(f"Пользователь с Telegram ID {tg_id} успешно удалён.", reply_markup=admin_menu)
    await state.clear()

@dp.callback_query(lambda call: call.data == "contacts")
async def contacts_handler(call: types.CallbackQuery):
    await call.message.answer("Список контактов студентов: [пример контактов]")
    await call.answer()

@dp.callback_query(lambda call: call.data == "student_telegrams")
async def telegrams_handler(call: types.CallbackQuery):
    await call.message.answer("Список Telegram ID студентов: [пример данных]")
    await call.answer()


# === Функции для создания мероприятия ===
@dp.callback_query(lambda call: call.data == "create_event")
async def create_event_prompt(call: types.CallbackQuery):
    event_steps[call.from_user.id] = {"action": "create_event_name"}
    await call.message.answer("Введите название мероприятия:")
    await call.answer()


@dp.message()  # Один декоратор достаточно
async def handle_event_creation(message: types.Message):
    user_id = message.from_user.id
    if user_id in event_steps:
        step = event_steps[user_id]
        
        if step["action"] == "create_event_name":
            step["name"] = message.text
            step["action"] = "create_event_date"
            await message.answer("Введите дату мероприятия (ГГГГ-ММ-ДД ЧЧ:ММ):")
        
        elif step["action"] == "create_event_date":
            try:
                event_time = datetime.strptime(message.text, "%Y-%m-%d %H:%M")
                step["date"] = event_time.strftime("%Y-%m-%d %H:%M:%S")
                step["action"] = "create_event_limit"
                await message.answer("Введите максимальное число участников:")
            except ValueError:
                await message.answer("Ошибка: неверный формат даты. Используйте ГГГГ-ММ-ДД ЧЧ:ММ.")
        
        elif step["action"] == "create_event_limit":
            try:
                step["limit"] = int(message.text)
                step["action"] = "create_event_description"
                await message.answer("Введите описание мероприятия:")
            except ValueError:
                await message.answer("Ошибка: введите число!")
        
        elif step["action"] == "create_event_description":
            step["description"] = message.text

            # При создании мероприятия сохраняем только данные события, а данные участника будут сохраняться отдельно при записи
            conn = get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO events (event_name, description, event_date, participant_limit, tg_id)
                    VALUES (?, ?, ?, ?, ?)
                """, (step["name"], step["description"], step["date"], step["limit"], user_id))
                conn.commit()  # Важно сделать commit перед получением lastrowid
                event_id = cursor.lastrowid
                if not event_id:
                    raise ValueError("Не удалось получить ID созданного мероприятия")
                
                logging.info(f"Создано мероприятие с ID: {event_id}")
            except sqlite3.Error as e:
                logging.error(f"Ошибка при добавлении мероприятия: {e}")
                await message.answer("Ошибка при создании мероприятия. Попробуйте снова.")
                return

            # Создаем кнопку для участия в мероприятии
            participate_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="✅ Участвовать", callback_data=f"join_{event_id}")]]
            )

            # Рассылаем сообщение о новом мероприятии всем пользователям
            conn = get_db_connection()
            users = conn.execute("SELECT tg_id FROM users").fetchall()
            conn.close()
            
            for user in users:
                try:
                    await bot.send_message(
                        user[0],
                        f"📢 Новое мероприятие!\n\n<b>{step['name']}</b>\n"
                        f"📅 Дата: {step['date']}\n"
                        f"👥 Максимум участников: {step['limit']}\n"
                        f"ℹ️ Описание: {step['description']}",
                        parse_mode="HTML", reply_markup=participate_keyboard
                    )
                except Exception as e:
                    logging.error(f"Ошибка при отправке сообщения: {e}")

            # Планируем закрытие регистрации в указанную дату
            scheduler.add_job(close_event_registration, "date",
                              run_date=datetime.strptime(step["date"], "%Y-%m-%d %H:%M:%S"),
                              args=[event_id])

            await message.answer("✅ Мероприятие создано и отправлено пользователям!")
            del event_steps[user_id]


# Обработчик команды "Участвовать"
@dp.callback_query(F.data.startswith("join_"))
async def join_event(callback_query: types.CallbackQuery):
    event_id = int(callback_query.data.split("_")[1])
    user_id = callback_query.from_user.id

    conn = get_db_connection()
    cursor = conn.cursor()

    # Проверяем, существует ли мероприятие
    cursor.execute("SELECT participant_limit FROM events WHERE id = ?", (event_id,))
    limit_row = cursor.fetchone()
    
    if not limit_row:
        await callback_query.answer("Ошибка: мероприятие не найдено!", show_alert=True)
        conn.close()
        return
    
    limit = limit_row[0]  # Получаем значение из кортежа

    # Проверяем, зарегистрирован ли пользователь
    cursor.execute("SELECT name, group_name FROM users WHERE tg_id = ?", (user_id,))
    user_data = cursor.fetchone()
    
    if not user_data:
        await callback_query.answer("Ошибка: ваш профиль не зарегистрирован в системе!", show_alert=True)
        conn.close()
        return

    # Проверяем, не записан ли пользователь уже на это мероприятие
    cursor.execute("SELECT COUNT(*) FROM event_participants WHERE event_id = ? AND tg_id = ?", (event_id, user_id))
    if cursor.fetchone()[0] > 0:
        await callback_query.answer("Вы уже записаны на это мероприятие!", show_alert=True)
        conn.close()
        return

    # Проверяем лимит участников
    cursor.execute("SELECT COUNT(*) FROM event_participants WHERE event_id = ?", (event_id,))
    current_count = cursor.fetchone()[0]

    if current_count >= limit:
        await callback_query.answer("Запись закрыта, достигнут лимит участников.", show_alert=True)
        conn.close()
        return

    name, group_name = user_data

    try:
        cursor.execute("""
            INSERT INTO event_participants (event_id, tg_id, name, group_name)
            VALUES (?, ?, ?, ?)
        """, (event_id, user_id, name, group_name))
        conn.commit()
        await callback_query.message.answer(f"✅ {callback_query.from_user.full_name}, вы успешно записаны на мероприятие!")
        await callback_query.answer("Вы успешно записаны!", show_alert=True)
    except sqlite3.Error as e:
        logging.error(f"Ошибка при записи участника: {e}")
        await callback_query.answer("Произошла ошибка при записи", show_alert=True)
    finally:
        conn.close()



# === Функция для закрытия регистрации на мероприятие ===
async def close_event_registration(event_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tg_id FROM users")
    users = cursor.fetchall()
    conn.close()
    for user in users:
        try:
            # Если fetchall() возвращает кортеж, используем user[0]
            await bot.send_message(user[0], "⏳ Регистрация на мероприятие закрыта.")
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения о закрытии: {e}")












 

async def export_to_excel(chat_id: int, data_type: str):
    try:
        logging.info(f"Начало экспорта данных типа: {data_type}")
        wb = Workbook()
        ws = wb.active
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        if data_type == 'events':
            # Получаем список всех мероприятий
            cursor.execute("""
                SELECT DISTINCT e.id, e.event_name, e.event_date
                FROM events e
                ORDER BY e.event_date DESC
            """)
            events = cursor.fetchall()

            # Для каждого мероприятия получаем список участников
            result_data = []
            max_participants = 0
            
            for event in events:
                event_id, event_name, event_date = event
                cursor.execute("""
                    SELECT ep.name
                    FROM event_participants ep
                    WHERE ep.event_id = ?
                    ORDER BY ep.name
                """, (event_id,))
                participants = cursor.fetchall()
                
                # Обновляем максимальное количество участников
                max_participants = max(max_participants, len(participants))
                
                # Создаем список участников для этого мероприятия
                participant_names = [p[0] for p in participants]
                # Дополняем пустыми значениями, если участников меньше максимума
                participant_names.extend([''] * (max_participants - len(participant_names)))
                
                result_data.append([event_name, event_date] + participant_names)

            # Создаем заголовки
            headers = ['Мероприятие', 'Дата']
            for i in range(max_participants):
                headers.append(f'Участник {i+1}')
            
            ws.append(headers)
            
            # Добавляем данные
            for row in result_data:
                ws.append([str(cell) if cell is not None else '' for cell in row])

        else:  # для других типов данных оставляем как есть
            queries = {
                'users': {
                    'title': "Пользователи",
                    'headers': ['ID', 'Telegram ID', 'Имя', 'Группа', 'Роль'],
                    'query': """
                        SELECT u.id, u.tg_id, u.name, u.group_name, r.name as role_name
                        FROM users u
                        LEFT JOIN roles r ON u.role_id = r.id
                        ORDER BY u.id
                    """
                }
            }
            
            query_data = queries[data_type]
            ws.title = query_data['title']
            ws.append(query_data['headers'])
            
            cursor.execute(query_data['query'])
            rows = cursor.fetchall()
            
            for row in rows:
                row_data = [str(value) if value is not None else '' for value in row]
                ws.append(row_data)

        # Автоматическая настройка ширины столбцов
        for column in ws.columns:
            max_length = 0
            column = list(column)
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = (max_length + 2)
            ws.column_dimensions[column[0].column_letter].width = adjusted_width

        filename = f"{data_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        wb.save(filename)

        with open(filename, 'rb') as file:
            await bot.send_document(
                chat_id,
                BufferedInputFile(file.read(), filename=filename),
                caption=f"Экспорт данных: {data_type.capitalize()}"
            )

        os.remove(filename)
        conn.close()

    except Exception as e:
        logging.error(f"Ошибка при экспорте данных: {e}", exc_info=True)
        await bot.send_message(chat_id, f"Произошла ошибка при экспорте данных: {str(e)}")

@dp.callback_query(lambda call: call.data.startswith("export_"))
async def handle_export(call: types.CallbackQuery):
    """Обработчик кнопок экспорта"""
    try:
        logging.info(f"Получен запрос на экспорт: {call.data}")
        
        # Проверяем роль пользователя
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.name as role_name 
            FROM users u 
            JOIN roles r ON u.role_id = r.id 
            WHERE u.tg_id = ?
        """, (call.from_user.id,))
        result = cursor.fetchone()
        conn.close()

        if not result or result[0].lower() != "декан":
            await call.answer("У вас нет прав для выполнения этой команды.", show_alert=True)
            return

        await call.answer("Подготовка файла...")
        data_type = call.data.replace("export_", "")
        await export_to_excel(call.message.chat.id, data_type)
        
    except Exception as e:
        logging.error(f"Ошибка в обработчике экспорта: {e}", exc_info=True)
        await call.message.answer(f"Произошла ошибка при обработке запроса: {str(e)}")

async def main():
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('bot.log'),
            logging.StreamHandler()
        ]
    )
    
    setup_database()
    logging.info("База данных готова!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
    Executor.start_polling(dp)