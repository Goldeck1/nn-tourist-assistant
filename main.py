import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from bot.handlers import (
    start_command, help_command, handle_message, handle_callback, handle_location
)
import config

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.ERROR
)

logging.getLogger('httpx').setLevel(logging.ERROR)
logging.getLogger('telegram').setLevel(logging.ERROR)
logging.getLogger('httpcore').setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


def main():
    """Запуск Telegram бота"""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не установлен! Создайте файл .env и добавьте токен.")
        return
    
    if not config.GIGACHAT_API_KEY:
        logger.error("GIGACHAT_API_KEY не установлен! Добавьте его в .env файл.")
        return
    
    if not config.DVGIS_API_KEY:
        logger.warning("DVGIS_API_KEY не установлен! Некоторые функции могут не работать.")
    
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    
    logger.info("Бот запущен")
    application.run_polling()


if __name__ == '__main__':
    main()

