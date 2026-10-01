import re


def parse_coordinates(coord_str: str) -> tuple[float, float] | None:
    """
    Парсит координаты из формата 'POINT (lon lat)' в (longitude, latitude)
    """
    if not coord_str:
        return None
    
    match = re.search(r'POINT\s*\(([\d.]+)\s+([\d.]+)\)', coord_str)
    if match:
        lon = float(match.group(1))
        lat = float(match.group(2))
        return (lon, lat)
    return None


def clean_html(text: str) -> str:
    """Удаляет HTML теги из текста"""
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text).strip()


def extract_keywords(text: str) -> dict:
    """
    Извлекает и анализирует ключевые слова из текста интересов пользователя
    Возвращает словарь с ключевыми словами и контекстом намерения
    """
    if not text:
        return {'keywords': [], 'categories': [], 'intent': 'general'}
    
    # Приведение к нижнему регистру и очистка
    text_lower = text.lower().strip()
    
    # Удаляем эмодзи и специальные символы, оставляем только слова
    text_clean = re.sub(r'[^\w\s-]', ' ', text_lower)
    
    # Расширенный словарь категорий с пониманием контекста и специфичных запросов
    category_mapping = {
        'стрит-арт': {
            'keywords': ['стрит-арт', 'стритарт', 'street art', 'уличное искусство', 'мурал', 'муралы', 'граффити', 'уличн'],
            'intent': 'art',
            'exact_match': False,
            'priority': 1  # Высокий приоритет
        },
        'граффити': {
            'keywords': ['граффити', 'граффит'],
            'intent': 'art',
            'priority': 1
        },
        'музеи искусств': {
            'keywords': ['музей искусств', 'музей искусства', 'музеи искусств', 'художественный музей', 'галерея', 'музей художеств'],
            'intent': 'culture',
            'exact_match': True  # Требуем точное соответствие
        },
        'кофейни': {
            'keywords': ['кафе', 'кофейня', 'кофе', 'кофейный', 'кафешоп', 'ресторан', 'бар', 'общепит'],
            'intent': 'venue',  # Заведения
            'exclude_context': ['скульптур', 'вывеска', 'памятник', 'мозаик', 'искусств']
        },
        'суши-бар': {
            'keywords': ['суши', 'суши-бар', 'сушибар', 'sushi', 'японская кухня', 'японск', 'роллы', 'сашими'],
            'intent': 'venue',
            'exact_match': True  # Требуем точное соответствие
        },
        'суши': {
            'keywords': ['суши', 'суши-бар', 'сушибар', 'sushi', 'японская кухня', 'японск', 'роллы'],
            'intent': 'venue'
        },
        'рестораны': {
            'keywords': ['ресторан', 'кафе', 'столовая', 'трактир', 'бистро', 'еда', 'кухня'],
            'intent': 'venue'
        },
        'бары': {
            'keywords': ['бар', 'паб', 'клуб', 'ресторан', 'развлечения', 'ночная жизнь'],
            'intent': 'venue'
        },
        'торговые центры': {
            'keywords': ['торговый центр', 'тц', 'молл', 'магазин', 'шоппинг', 'торговля', 'бутик'],
            'intent': 'shopping'
        },
        'шоппинг': {
            'keywords': ['шоппинг', 'магазин', 'торговый', 'тц', 'бутик', 'покупки'],
            'intent': 'shopping'
        },
        'спорт': {
            'keywords': ['спорт', 'спортивная', 'площадка', 'стадион', 'тренажер', 'фитнес', 'спортзал'],
            'intent': 'sports'
        },
        'развлечения': {
            'keywords': ['развлечения', 'кино', 'клуб', 'дискотека', 'бильярд', 'боулинг', 'аттракцион'],
            'intent': 'entertainment'
        },
        'панорамы': {
            'keywords': ['вид', 'обзор', 'смотровая', 'панорама', 'видовая', 'смотровая площадка', 'обзорная'],
            'intent': 'view'
        },
        'история': {
            'keywords': ['исторический', 'музей', 'памятник', 'история', 'историческое', 'музейный', 'историческ'],
            'intent': 'culture'
        },
        'архитектура': {
            'keywords': ['здание', 'собор', 'храм', 'церковь', 'архитектура', 'архитектурный', 'постройка', 'сооружен'],
            'intent': 'architecture'
        },
        'парки': {
            'keywords': ['парк', 'сквер', 'сад', 'парковый', 'скверы', 'парки', 'парков'],
            'intent': 'nature'
        },
        'набережная': {
            'keywords': ['набережная', 'набережные', 'набережн', 'набережна'],
            'intent': 'nature',
            'exact_match': False
        },
        'театры': {
            'keywords': ['театр', 'театральный', 'спектакль', 'театры', 'театральн'],
            'intent': 'culture'
        },
        'музеи искусств': {
            'keywords': ['музей искусств', 'музей искусства', 'музеи искусств', 'художественный музей', 'галерея искусств', 'музей художеств'],
            'intent': 'culture',
            'exact_match': True,
            'priority': 1  # Высокий приоритет - проверяем первым
        },
        'музеи': {
            'keywords': ['музей', 'музеи', 'музейный', 'выставка'],
            'intent': 'culture',
            'exclude_context': ['искусств', 'художественн']  # Исключаем, если есть "искусств"
        },
        'кремль': {
            'keywords': ['кремль', 'крепость', 'башня', 'кремлев'],
            'intent': 'architecture'
        },
        'соборы': {
            'keywords': ['собор', 'церковь', 'храм', 'монастырь', 'соборы'],
            'intent': 'architecture'
        },
    }
    
    # Извлекаем слова
    words = re.findall(r'\b\w+\b', text_clean)
    
    keywords = []
    matched_categories = []
    detected_intents = set()
    
    # Сортируем категории по приоритету (сначала проверяем высокоприоритетные)
    sorted_categories = sorted(category_mapping.items(), 
                               key=lambda x: x[1].get('priority', 99), 
                               reverse=False)
    
    # Проверяем сначала точные совпадения, потом общие
    for category, config in sorted_categories:
        synonyms = config['keywords']
        exact_match = config.get('exact_match', False)
        
        # Проверяем наличие ключевых слов в тексте
        matches_found = False
        
        if exact_match:
            # Для точного совпадения проверяем, есть ли точная фраза
            for syn in synonyms:
                if syn.lower() in text_lower:
                    matches_found = True
                    break
        else:
            # Для обычных - проверяем отдельные слова
            for syn in synonyms:
                if len(syn) > 3 and syn.lower() in text_lower:
                    # Проверяем контекстные исключения
                    if 'exclude_context' in config:
                        has_exclude = any(excl in text_lower for excl in config['exclude_context'])
                        if has_exclude:
                            continue
                    matches_found = True
                    break
        
        if matches_found:
            if category not in matched_categories:
                matched_categories.append(category)
                detected_intents.add(config.get('intent', 'general'))
                keywords.append(category)
                keywords.extend(synonyms[:3])
    
    # Добавляем отдельные слова
    for word in words:
        if len(word) >= 3:
            keywords.append(word)
    
    # Определяем общий intent
    main_intent = 'general'
    if detected_intents:
        # Приоритет: venue > shopping > sports > entertainment > culture > architecture > art > nature > view > general
        priority = ['venue', 'shopping', 'sports', 'entertainment', 'culture', 'architecture', 'art', 'nature', 'view', 'general']
        for intent in priority:
            if intent in detected_intents:
                main_intent = intent
                break
    
    return {
        'keywords': list(set(keywords)),  # Уникальные ключевые слова
        'categories': matched_categories,  # Найденные категории
        'intent': main_intent  # Основное намерение пользователя
    }


def validate_time(time_str: str) -> int | None:
    """
    Валидирует время прогулки и возвращает в минутах
    """
    if not time_str:
        return None
    
    # Извлечение чисел
    numbers = re.findall(r'\d+\.?\d*', time_str)
    if not numbers:
        return None
    
    hours = float(numbers[0])
    if hours <= 0 or hours > 24:
        return None
    
    return int(hours * 60)  # Конвертация в минуты

