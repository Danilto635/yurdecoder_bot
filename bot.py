import os
import tempfile
import fitz  # PyMuPDF
import easyocr
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import ContentType, Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
import openai
from collections import defaultdict
from docx import Document
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
reader = easyocr.Reader(['ru', 'en'])

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("🚀 Начать анализ")],
        [KeyboardButton("ℹ️ О боте"), KeyboardButton("📞 Поддержка")]
    ],
    resize_keyboard=True
)

photo_buffer = defaultdict(list)
photo_timers = {}

def analyze_with_gpt(text: str) -> str:
    prompt = f"""
Ты опытный юрист. Проанализируй следующий договор. Ответ строго в формате Markdown:
1. **Не используй заголовки**
2. Выделяй **ключевые пункты жирным**
3. Используй эмодзи:
   - 📌 Основные пункты
   - ⚠️ Риски
   - 💡 Рекомендации
4. Объясняй понятным языком

Вот текст договора:
{text}
"""
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Ты опытный юрист. Отвечай строго в Markdown, без заголовков, с эмодзи."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=1500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ Ошибка при обращении к GPT:\n{e}"

@dp.message_handler(commands=["start"])
async def start_command(message: Message):
    await message.answer(
        "Привет! Я ЮрDecoder 🤖\nОтправь мне договор (PDF, DOCX, фото), и я помогу его разобрать.",
        reply_markup=main_menu
    )

@dp.message_handler(lambda msg: msg.text == "🚀 Начать анализ")
async def handle_analysis_button(message: Message):
    await message.answer("Отправь PDF, Word или фото 📄📷")

@dp.message_handler(lambda msg: msg.text == "ℹ️ О боте")
async def handle_about(message: Message):
    await message.answer("Я юридический бот ЮрDecoder. GPT-4o анализирует договоры и помогает понять риски.")

@dp.message_handler(lambda msg: msg.text == "📞 Поддержка")
async def handle_support(message: Message):
    await message.answer("Свяжись с разработчиком: @ТВОЙ_ТЕЛЕГРАМ")

@dp.message_handler(content_types=ContentType.DOCUMENT)
async def handle_document(message: Message):
    document = message.document
    file_name = document.file_name.lower()
    if not (file_name.endswith('.pdf') or file_name.endswith('.docx')):
        await message.answer("Пришли PDF, DOCX или фото.")
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
            await message.answer(f"❌ Ошибка при PDF:\n{e}")
            return

    elif file_name.endswith('.docx'):
        await message.answer("📄 Извлекаю текст из Word...")
        try:
            doc = Document(path)
            text = "\n".join([p.text for p in doc.paragraphs])
        except Exception as e:
            await message.answer(f"❌ Ошибка при DOCX:\n{e}")
            return

    if text.strip():
        await message.answer("🤖 GPT анализирует договор...")
        result = analyze_with_gpt(text)
        await message.answer(result[:4000], parse_mode="Markdown")
    else:
        await message.answer("😕 Текст не извлечён.")

async def process_photo_buffer(chat_id):
    await asyncio.sleep(7)
    images = photo_buffer.pop(chat_id, [])
    if not images:
        return

    await bot.send_message(chat_id, "📷 Распознаю текст...")
    all_text = []
    for path in images:
        result = reader.readtext(path, detail=0, paragraph=True)
        all_text.append("\n".join(result))

    combined_text = "\n".join(all_text)

    if combined_text.strip():
        await bot.send_message(chat_id, "🤖 GPT анализирует договор...")
        result = analyze_with_gpt(combined_text)
        await bot.send_message(chat_id, result[:4000], parse_mode="Markdown")
    else:
        await bot.send_message(chat_id, "❌ Не удалось распознать текст.")

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

if __name__ == "__main__":
    print("Бот запущен ✅")
    executor.start_polling(dp, skip_updates=True)
