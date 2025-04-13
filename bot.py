import os
import tempfile
import asyncio
import fitz  # PyMuPDF
import easyocr
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.types import ContentType, Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
from dotenv import load_dotenv
from collections import defaultdict
from docx import Document

# Загрузка переменных из .env
load_dotenv()
API_TOKEN = os.getenv("API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- Укажи прокси, если требуется ---
proxies = {
    "http": os.getenv("HTTP_PROXY"),
    "https": os.getenv("HTTPS_PROXY")
}

# Telegram-бот
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
reader = easyocr.Reader(['ru', 'en'])

# Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("🚀 Начать анализ")],
        [KeyboardButton("ℹ️ О боте"), KeyboardButton("📞 Поддержка")]
    ],
    resize_keyboard=True
)

photo_buffer = defaultdict(list)
photo_timers = {}

# --- Запрос к GPT через requests ---
def analyze_with_gpt(text: str) -> str:
    prompt = f"""
Ты опытный юрист. Проанализируй следующий договор. Ответ строго в формате Markdown:
1. **Не используй заголовки** (#) — просто текст и цифры (1., 2.)
2. Выделяй **ключевые пункты жирным**
3. Используй эмодзи:
   - 📌 Основные пункты
   - ⚠️ Риски
   - 💡 Рекомендации
4. Объясняй понятным языком, как для обычного человека

Вот текст договора:
{text}
"""

    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
        data = {
            "model": "gpt-4",
            "messages": [
                {"role": "system", "content": "Ты опытный юрист. Отвечай строго в Markdown — без заголовков, с эмодзи и структурой."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.4,
            "max_tokens": 1500
        }

        response = requests.post(url, headers=headers, json=data, proxies=proxies, timeout=60)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]

    except Exception as e:
        return f"❌ Ошибка при обращении к GPT:\n{e}"


@dp.message_handler(commands=["start"])
async def start_command(message: Message):
    await message.answer(
        "Привет! Я ЮрDecoder 🤖\nЯ помогу тебе разобрать договор простыми словами и найти риски.\n\nНажми кнопку ниже 👇",
        reply_markup=main_menu
    )

@dp.message_handler(lambda msg: msg.text == "🚀 Начать анализ")
async def handle_analysis_button(message: Message):
    await message.answer("Отправь мне договор: PDF, DOCX или фото 📄📷")

@dp.message_handler(lambda msg: msg.text == "ℹ️ О боте")
async def handle_about(message: Message):
    await message.answer("ЮрDecoder — бот, который помогает анализировать договоры с помощью GPT-4. Принимает PDF, Word и фото.")

@dp.message_handler(lambda msg: msg.text == "📞 Поддержка")
async def handle_support(message: Message):
    await message.answer("Обратись к разработчику: @ТВОЙ_ТЕЛЕГРАМ")

@dp.message_handler(content_types=ContentType.DOCUMENT)
async def handle_document(message: Message):
    document = message.document
    file_name = document.file_name.lower()
    if not (file_name.endswith('.pdf') or file_name.endswith('.docx')):
        await message.answer("Пожалуйста, пришли PDF, DOCX или фото.")
        return
    file = await document.download(destination_dir=tempfile.gettempdir())
    path = file.name
    text = ""
    if file_name.endswith('.pdf'):
        await message.answer("📄 Извлекаю текст из PDF...")
        try:
            doc = fitz.open(path)
            text = "".join([page.get_text() for page in doc])
            doc.close()
        except Exception as e:
            await message.answer(f"❌ Ошибка при обработке PDF:\n{e}")
            return
    elif file_name.endswith('.docx'):
        await message.answer("📄 Извлекаю текст из Word...")
        try:
            doc = Document(path)
            text = "\n".join([para.text for para in doc.paragraphs])
        except Exception as e:
            await message.answer(f"❌ Ошибка при обработке Word:\n{e}")
            return
    if text.strip():
        await message.answer("🤖 Анализирую договор с помощью AI...")
        result = analyze_with_gpt(text)
        await message.answer(result[:4000], parse_mode="Markdown")
    else:
        await message.answer("😕 Не удалось извлечь текст.")

async def process_photo_buffer(chat_id):
    await asyncio.sleep(7)
    images = photo_buffer.pop(chat_id, [])
    if not images:
        return
    await bot.send_message(chat_id, "📷 Распознаю текст со всех фото...")
    all_text = []
    for path in images:
        result = reader.readtext(path, detail=0, paragraph=True)
        all_text.append("\n".join(result))
    combined_text = "\n".join(all_text)
    if combined_text.strip():
        await bot.send_message(chat_id, "🤖 Анализирую договор с помощью AI...")
        result = analyze_with_gpt(combined_text)
        await bot.send_message(chat_id, result[:4000], parse_mode="Markdown")
    else:
        await bot.send_message(chat_id, "❌ Не удалось распознать текст на фото.")

@dp.message_handler(content_types=ContentType.PHOTO)
async def handle_photo(message: Message):
    chat_id = message.chat.id
    photo = message.photo[-1]
    file = await photo.download(destination_dir=tempfile.gettempdir())
    path = file.name
    photo_buffer[chat_id].append(path)
    if chat_id in photo_timers:
        photo_timers[chat_id].cancel()
    photo_timers[chat_id] = asyncio.create_task(process_photo_buffer(chat_id))

@dp.message_handler(content_types=ContentType.TEXT)
async def handle_text_contract(message: Message):
    text = message.text.strip()
    if len(text) < 100:
        await message.answer("❗️Похоже, вы отправили слишком короткий текст. Отправьте договор целиком.")
        return
    if len(text) > 12000:
        await message.answer("⚠️ Текст слишком длинный, обрезаю до первых 12000 символов.")
        text = text[:12000]
    await message.answer("🤖 Анализирую договор с помощью AI...")
    result = analyze_with_gpt(text)
    await message.answer(result[:4000], parse_mode="Markdown")

# Запуск
if __name__ == "__main__":
    print("Бот запущен ✅")
    async def on_startup(dp):
    await bot.delete_webhook(drop_pending_updates=True)

if __name__ == "__main__":
    print("Бот запущен ✅")
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)

