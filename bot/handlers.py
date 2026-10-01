import logging
from telegram import Update
from telegram.ext import ContextTypes
from bot.states import UserState
from bot.keyboards import (
    get_interests_keyboard, get_time_keyboard, 
    get_location_keyboard, get_after_route_keyboard
)
from services.route_generator import RouteGenerator

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

route_generator = RouteGenerator()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    welcome_text = f"""
👋 Привет, {user.first_name}!

Я Нино, твой Ai-помощник туриста, и я помогу создать для тебя персональный маршрут прогулки по Нижнему Новгороду!

Для начала мне нужно узнать несколько вещей:
1️⃣ Твои интересы (что тебе интересно: стрит-арт, история, кофейни и т.д.)
2️⃣ Сколько времени у тебя есть на прогулку
3️⃣ Откуда ты начнешь маршрут

Давай начнем! 🚀

Какие места и темы тебе интересны? Можешь выбрать из вариантов ниже или написать свои интересы в свободной форме.
"""
    
    context.user_data['state'] = UserState.WAITING_INTERESTS.value
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_interests_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = """
📖 Справка по использованию бота:

🔹 /start - начать создание нового маршрута
🔹 /help - показать эту справку

Процесс создания маршрута:
1. Укажи свои интересы (можно выбрать из кнопок или написать свои)
2. Выбери или укажи время на прогулку
3. Укажи начальную точку маршрута (адрес или отправь геолокацию)

Бот создаст для тебя персонализированный маршрут с:
✅ 3-5 подходящими местами
✅ Объяснением выбора каждого места
✅ Оптимальным порядком посещения
✅ Подробным таймлайном

Приятной прогулки! 🚶‍♂️
"""
    await update.message.reply_text(help_text)


async def handle_interests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа о интересах"""
    interests = update.message.text
    
    if interests == "Свои интересы":
        await update.message.reply_text(
            "Напиши свои интересы в свободной форме, например: 'история, музеи, старинные здания'"
        )
        return
    
    context.user_data['interests'] = interests
    context.user_data['state'] = UserState.WAITING_TIME.value
    
    await update.message.reply_text(
        f"Отлично! Твои интересы: {interests}\n\n"
        "⏰ Сколько времени у тебя есть на прогулку?",
        reply_markup=get_time_keyboard()
    )


async def handle_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа о времени"""
    time_input = update.message.text
    
    from utils.helpers import validate_time
    time_minutes = validate_time(time_input)
    
    if not time_minutes:
        await update.message.reply_text(
            "Пожалуйста, укажи время корректно. Например: '2', '2.5', '3 часа' или выбери из кнопок."
        )
        return
    
    context.user_data['time'] = time_input
    context.user_data['time_minutes'] = time_minutes
    context.user_data['state'] = UserState.WAITING_LOCATION.value
    
    await update.message.reply_text(
        f"Понял! У тебя есть {time_input} на прогулку.\n\n"
        "📍 Откуда ты хочешь начать маршрут?\n"
        "Можешь отправить геолокацию или написать адрес вручную.",
        reply_markup=get_location_keyboard()
    )


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа о местоположении (геолокация)"""
    state = context.user_data.get('state')
    
    # Проверяем, что пользователь на этапе ввода местоположения
    if state != UserState.WAITING_LOCATION.value:
        await update.message.reply_text(
            "Сначала укажи свои интересы и время прогулки. Используй /start чтобы начать."
        )
        return
    
    if not update.message.location:
        await update.message.reply_text(
            "Пожалуйста, отправь геолокацию используя кнопку 📍 Отправить геолокацию"
        )
        return
    
    # Геолокация от пользователя (Telegram возвращает lat, lon)
    lat = update.message.location.latitude
    lon = update.message.location.longitude
    # Формат для RouteGenerator: "lat,lon"
    location = f"{lat},{lon}"
    context.user_data['location'] = location
    context.user_data['location_coords'] = (lon, lat)  # Сохраняем как (lon, lat) для внутреннего использования
    context.user_data['state'] = UserState.ROUTE_GENERATED.value
    
    # Показываем, что бот обрабатывает запрос
    processing_msg = await update.message.reply_text(
        "🔄 Создаю для тебя персонализированный маршрут...\n"
        "Это может занять несколько секунд ⏳"
    )
    
    # Генерация маршрута
    user_id = (update.effective_user.id if update.effective_user 
               else (update.message.from_user.id if update.message and update.message.from_user else None))
    result = route_generator.generate_route(
        interests=context.user_data.get('interests', ''),
        time_input=context.user_data.get('time', ''),
        location=location,
        user_id=user_id
    )
    
    if result['success']:
        route_text = result['route_text']
        map_link = result.get('map_link', '')
        current_time = result.get('current_time', '')
        
        # Форматируем ответ
        response = f"🎯 *Твой персональный маршрут по Нижнему Новгороду*\n\n"
        if current_time:
            response += f"⏰ Текущее время: {current_time} МСК\n\n"
        response += route_text
        
        # Всегда добавляем ссылку на карту
        if map_link:
            response += f"\n\n🗺️ [Открыть полный маршрут на карте 2ГИС]({map_link})"
        else:
            response += f"\n\n🗺️ Карта маршрута будет доступна после генерации"
        
        await processing_msg.edit_text(
            response,
            parse_mode='Markdown',
            reply_markup=get_after_route_keyboard()
        )
    else:
        error_msg = result.get('error', 'Неизвестная ошибка')
        await processing_msg.edit_text(
            f"❌ {error_msg}\n\n"
            "Попробуй начать заново командой /start"
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех текстовых сообщений"""
    state = context.user_data.get('state')
    
    if state == UserState.WAITING_INTERESTS.value:
        await handle_interests(update, context)
    elif state == UserState.WAITING_TIME.value:
        await handle_time(update, context)
    elif state == UserState.WAITING_LOCATION.value:
        # Обработка текстового адреса
        location = update.message.text
        
        if location == "Ввести адрес вручную":
            await update.message.reply_text(
                "Напиши адрес начальной точки маршрута, например:\n"
                "'Нижний Новгород, площадь Минина и Пожарского'\n"
                "или 'Кремль, Нижний Новгород'"
            )
            return
        
        # Сохраняем адрес и генерируем маршрут
        context.user_data['location'] = location
        context.user_data['state'] = UserState.ROUTE_GENERATED.value
        
        # Показываем, что бот обрабатывает запрос
        processing_msg = await update.message.reply_text(
            "🔄 Создаю для тебя персонализированный маршрут...\n"
            "Это может занять несколько секунд ⏳"
        )
        
        # Генерация маршрута
        user_id = update.effective_user.id if update.effective_user else None
        result = route_generator.generate_route(
            interests=context.user_data.get('interests', ''),
            time_input=context.user_data.get('time', ''),
            location=location,
            user_id=user_id
        )
        
        if result['success']:
            route_text = result['route_text']
            map_link = result.get('map_link', '')
            current_time = result.get('current_time', '')
            
            # Форматируем ответ
            response = f"🎯 *Твой персональный маршрут по Нижнему Новгороду*\n\n"
            if current_time:
                response += f"⏰ Текущее время: {current_time} МСК\n\n"
            response += route_text
            
            # Всегда добавляем ссылку на карту
            if map_link:
                response += f"\n\n🗺️ [Открыть полный маршрут на карте 2ГИС]({map_link})"
            else:
                response += f"\n\n🗺️ Карта маршрута будет доступна после генерации"
            
            await processing_msg.edit_text(
                response,
                parse_mode='Markdown',
                reply_markup=get_after_route_keyboard()
            )
        else:
            error_msg = result.get('error', 'Неизвестная ошибка')
            await processing_msg.edit_text(
                f"❌ {error_msg}\n\n"
                "Попробуй начать заново командой /start"
            )
    else:
        await update.message.reply_text(
            "Используй /start чтобы начать создание маршрута или /help для справки."
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик inline кнопок"""
    query = update.callback_query
    
    # Обрабатываем возможную ошибку истечения callback query
    try:
        await query.answer()
    except Exception as e:
        # Игнорируем ошибки истекшего callback query
        # Это нормально, если пользователь нажал кнопку давно
        pass
    
    if query.data == "new_route":
        # Очищаем данные пользователя
        context.user_data.clear()
        context.user_data['state'] = UserState.WAITING_INTERESTS.value
        
        # Отправляем приветствие
        user = query.from_user
        welcome_text = f"""
👋 Привет, {user.first_name}!

Я Нино, твой Ai-помощник туриста, и я помогу создать для тебя персональный маршрут прогулки по Нижнему Новгороду!

Для начала мне нужно узнать несколько вещей:
1️⃣ Твои интересы (что тебе интересно: стрит-арт, история, кофейни и т.д.)
2️⃣ Сколько времени у тебя есть на прогулку
3️⃣ Откуда ты начнешь маршрут

Давай начнем! 🚀

Какие места и темы тебе интересны? Можешь выбрать из вариантов ниже или написать свои интересы в свободной форме.
"""
        from bot.keyboards import get_interests_keyboard
        await query.message.reply_text(
            welcome_text,
            reply_markup=get_interests_keyboard()
        )
    elif query.data == "open_map":
        user_id = (query.from_user.id if query.from_user 
                  else (query.message.from_user.id if query.message and query.message.from_user else None))
        result = route_generator.generate_route(
            interests=context.user_data.get('interests', ''),
            time_input=context.user_data.get('time', ''),
            location=context.user_data.get('location', ''),
            user_id=user_id
        )
        if result['success'] and result.get('map_link'):
            await query.message.reply_text(
                f"🗺️ [Открыть карту с маршрутом]({result['map_link']})",
                parse_mode='Markdown'
            )
        else:
            await query.message.reply_text(
                "❌ Не удалось получить ссылку на карту. Попробуйте создать новый маршрут."
            )

