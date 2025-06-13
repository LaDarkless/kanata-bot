import logging
import os
import json
import requests
from dotenv import load_dotenv
from telegram import Update, Document
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    CallbackContext,
    filters,
    ApplicationBuilder
)

# Загрузка переменных окружения
load_dotenv(dotenv_path="API.env")
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
F5AI_API_KEY = os.getenv('F5AI_API_KEY')

# Настройки API
F5AI_API_URL = "https://api.f5ai.ru/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_MAX_TOKENS = 1500
DEFAULT_TEMPERATURE = 0.7

# Логгирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Память диалога
user_conversations = {}
MAX_CONVERSATION_HISTORY = 10

# --- Запрос к F5AI ---
def call_f5ai_api(messages: list, model=DEFAULT_MODEL, max_tokens=DEFAULT_MAX_TOKENS, temperature=DEFAULT_TEMPERATURE) -> dict:
    if not F5AI_API_KEY:
        return {"error": "F5AI_API_KEY is not configured."}

    headers = {
        "Content-Type": "application/json",
        "X-Auth-Token": F5AI_API_KEY
    }
    data = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }

    try:
        logger.info(f"Sending request to F5AI: {json.dumps(data, ensure_ascii=False)}")
        response = requests.post(F5AI_API_URL, headers=headers, json=data, timeout=45)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        return {"error": f"Ошибка запроса: {e}"}
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {"error": f"Непредвиденная ошибка: {e}"}

# --- Обработчики Telegram ---
async def start_command(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    user_conversations[user.id] = [
        {"role": "system", "content": "Ты — дружелюбный и полезный ИИ-ассистент. Твое имя Kanata AI."}
    ]
    await update.message.reply_html(
        rf"Привет, {user.mention_html()}! Я — Kanata AI 🤖✨\n\n"
        "Просто напиши мне сообщение, и я постараюсь помочь.\n"
        "Команды:\n"
        "/help — помощь\n"
        "/reset — сбросить историю"
    )

async def help_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "/start — начать заново\n"
        "/reset — сбросить историю диалога\n"
        "Можно отправлять текст, вопросы или .txt файлы для анализа!"
    )

async def reset_command(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    user_conversations[user_id] = [
        {"role": "system", "content": "Ты — дружелюбный и полезный ИИ-ассистент. Твое имя Kanata AI."}
    ]
    await update.message.reply_text("История диалога сброшена! Можешь начать заново~")

async def handle_text(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    text = update.message.text

    if not F5AI_API_KEY:
        await update.message.reply_text("F5AI API ключ не настроен.")
        return

    if user_id not in user_conversations:
        user_conversations[user_id] = [
            {"role": "system", "content": "Ты — дружелюбный и полезный ИИ-ассистент. Твое имя Kanata AI."}
        ]

    user_conversations[user_id].append({"role": "user", "content": text})
    if len(user_conversations[user_id]) > MAX_CONVERSATION_HISTORY + 1:
        user_conversations[user_id] = [user_conversations[user_id][0]] + user_conversations[user_id][-MAX_CONVERSATION_HISTORY:]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    api_response = call_f5ai_api(user_conversations[user_id])

    if "error" in api_response:
        await update.message.reply_text(f"Ошибка: {api_response['error']}")
        return

    content = api_response.get("choices", [{}])[0].get("message", {}).get("content", "")
    if content:
        await update.message.reply_text(content)
        user_conversations[user_id].append({"role": "assistant", "content": content})
    else:
        await update.message.reply_text("Ответ пустой. Попробуй переформулировать запрос.")

async def handle_document(update: Update, context: CallbackContext) -> None:
    """Обрабатывает загрузку текстовых файлов .txt"""
    file = update.message.document
    if file.mime_type != 'text/plain':
        await update.message.reply_text("Пожалуйста, отправь обычный текстовый файл (.txt).")
        return

    file_obj = file.get_file()
    content = file_obj.download_as_bytearray().decode("utf-8")

    await update.message.reply_text("Файл получен! Обрабатываю его содержимое...")
    update.message.text = content  # Притворимся, что это обычное текстовое сообщение
    await handle_text(update, context)

async def error_handler(update: object, context: CallbackContext) -> None:
    logger.error(f"Exception: {context.error}", exc_info=context.error)
    if update and isinstance(update, Update) and update.message:
        await update.message.reply_text("Произошла ошибка. Попробуй снова позже.")

# --- Точка входа ---
def main() -> None:
    try:
        if not TELEGRAM_BOT_TOKEN:
            logger.critical("TELEGRAM_BOT_TOKEN отсутствует!")
            return

        logger.info("Запуск бота...")
        app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

        # Добавляем обработчики
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("reset", reset_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        app.add_error_handler(error_handler)

        logger.info("Бот запущен.")
        app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        raise

if __name__ == '__main__':
    main()