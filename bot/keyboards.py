from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup


def get_interests_keyboard():
    """Клавиатура с популярными категориями интересов"""
    keyboard = [
        [
            KeyboardButton("Стрит-арт"),
            KeyboardButton("Кофейни")
        ],
        [
            KeyboardButton("История"),
            KeyboardButton("Панорамы")
        ],
        [
            KeyboardButton("Архитектура"),
            KeyboardButton("Парки")
        ],
        [
            KeyboardButton("Набережная"),
            KeyboardButton("Музеи")
        ],
        [
            KeyboardButton("Свои интересы")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_time_keyboard():
    """Клавиатура с вариантами времени"""
    keyboard = [
        [
            KeyboardButton("1 час"),
            KeyboardButton("2 часа")
        ],
        [
            KeyboardButton("3 часа"),
            KeyboardButton("4 часа")
        ],
        [
            KeyboardButton("5+ часов")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_location_keyboard():
    """Клавиатура для запроса геолокации"""
    keyboard = [
        [
            KeyboardButton("📍 Отправить геолокацию", request_location=True)
        ],
        [
            KeyboardButton("Ввести адрес вручную")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)


def get_after_route_keyboard():
    """Клавиатура после генерации маршрута"""
    keyboard = [
        [
            InlineKeyboardButton("🗺️ Открыть карту", callback_data="open_map"),
            InlineKeyboardButton("🔄 Новый маршрут", callback_data="new_route")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

