import os
import json
from openai import OpenAI
from typing import List, Dict, Optional
import config


class GigaChatService:
    """Сервис для работы с GigaChat API"""
    
    def __init__(self):
        self.client = OpenAI(
            api_key=config.GIGACHAT_API_KEY,
            base_url=config.GIGACHAT_BASE_URL
        )
        self.model = config.GIGACHAT_MODEL
    
    def generate_route(self, interests: str, time_minutes: int, 
                      start_location: str, filtered_objects: List[Dict]) -> str:
        """
        Генерирует персонализированный маршрут с помощью GigaChat
        """
        if filtered_objects:
            objects_text = "\n---\n".join([
                f"Объект {i+1}:\n{self._format_object(obj)}"
                for i, obj in enumerate(filtered_objects[:6])
            ])
        else:
            objects_text = "СПИСОК ПУСТ - используй свои знания о Нижнем Новгороде для построения маршрута по намерению пользователя."
        
        prompt = f"""Ты AI-помощник туриста в Нижнем Новгороде. Построй маршрут из 3-5 мест.

КОНТЕКСТ:
- Запрос: {interests}
- Время: {time_minutes} минут
- Старт: {start_location}

СПИСОК МЕСТ (ближайшие первыми):
{objects_text}

ПРАВИЛА ФОРМАТА:

1. Формат ответа - следуй точно этому формату:
   НЕ используй markdown, эмодзи, курсив!
   ТОЛЬКО простой текст:

МАРШРУТ ПО НИЖНЕМУ НОВГОРОДУ

Место 1: [ТОЧНОЕ название из списка]
Адрес: [ТОЧНЫЙ адрес из списка]
Почему идем сюда: [4-6 предложений, уникальное описание]
Время на посещение: 30 минут

Место 2: [ТОЧНОЕ название из списка]
Адрес: [ТОЧНЫЙ адрес из списка]
Почему идем сюда: [4-6 предложений, уникальное описание]
Время на посещение: 30 минут

Место 3: [ТОЧНОЕ название из списка]
Адрес: [ТОЧНЫЙ адрес из списка]
Почему идем сюда: [4-6 предложений, уникальное описание]
Время на посещение: 30 минут

2. Выбор мест: только первые 3-5 мест из списка. Используй точные названия и адреса.

3. Описание "Почему идем сюда":
   - 4-6 предложений для каждого места
   - Каждое описание уникальное, начинается по-разному
   - Используй конкретное название места в каждом предложении
   - Опиши уникальные особенности: атмосферу, расположение, что особенного
   - НЕ повторяй одни и те же фразы для разных мест

ПРИМЕР ПРАВИЛЬНОГО ФОРМАТА:
Место 1: Проект 56, кофейня
Адрес: Нижний Новгород, Большая Печёрская улица, 56, 1 этаж
Почему идем сюда: Кофейня "Проект 56" расположена на центральной улице города и славится качественным кофе. Интерьер выполнен в современном стиле с уютной атмосферой. Здесь можно насладиться ароматным напитком и легкими закусками. Место популярно среди местных жителей и туристов. Удобное расположение позволяет легко добраться от начальной точки маршрута.
Время на посещение: 30 минут

Начни ответ СРАЗУ с "МАРШРУТ ПО НИЖНЕМУ НОВГОРОДУ", без вступлений."""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=800,
                temperature=1.3,
                presence_penalty=1.2,
                frequency_penalty=1.0,
                top_p=0.85,
                messages=[
                    {
                        "role": "system",
                        "content": "Ты помощник для создания маршрутов. Отвечай ТОЛЬКО простым текстом без markdown, эмодзи и форматирования. Строго следуй указанному формату."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            
            response_text = response.choices[0].message.content
            return response_text
        except Exception as e:
            return f"❌ Ошибка при генерации маршрута: {str(e)}"
    
    def _format_object(self, obj: Dict) -> str:
        """
        Форматирует объект для промпта
        """
        title = obj.get('title', 'Без названия')
        address = obj.get('address', 'Адрес не указан')
        
        if address and address.startswith(title):
            address = 'Адрес уточняется'
        
        description = obj.get('description_clean', obj.get('description', ''))
        description_short = description[:60] + '...' if len(description) > 60 else description
        
        category = obj.get('category', '')
        rating = obj.get('rating', 0)
        reviews_count = obj.get('reviews_count', 0)
        
        result = f"Название: {title}\nАдрес: {address}\n"
        
        if description_short:
            result += f"Описание: {description_short}\n"
        
        if category:
            result += f"Категория: {category}\n"
        
        if rating and rating > 0:
            result += f"Рейтинг: {rating:.1f}"
            if reviews_count and reviews_count > 0:
                result += f" ({reviews_count} отзывов)"
            result += "\n"
        
        return result.strip()
    
    def _understand_user_intent(self, interests: str) -> str:
        """
        Понимает намерение пользователя на основе его запроса (использует GigaChat)
        """
        keyword_data = self.analyze_user_interests(interests)
        
        if isinstance(keyword_data, dict):
            intent = keyword_data.get('intent', 'general')
            categories = keyword_data.get('categories', [])
            
            intent_descriptions = {
                'venue': 'посетить заведения (кафе, рестораны, бары, кофейни)',
                'culture': 'посетить культурные объекты (музеи, театры, выставки)',
                'architecture': 'увидеть архитектурные объекты',
                'art': 'увидеть произведения уличного искусства',
                'nature': 'прогуляться на природе',
                'view': 'увидеть красивые виды',
                'general': 'увидеть достопримечательности города',
                'shopping': 'заняться шоппингом',
                'sports': 'заняться спортом',
                'entertainment': 'развлечься'
            }
            
            description = intent_descriptions.get(intent, 'увидеть достопримечательности города')
            
            if categories:
                description += f" | Категории: {', '.join(categories)}"
            
            return description
        
        return 'увидеть достопримечательности города'
    
    def analyze_user_interests(self, interests: str) -> Dict[str, any]:
        """
        Анализирует интересы пользователя с помощью GigaChat
        Возвращает структурированный ответ с категориями и intent
        
        Args:
            interests: Запрос пользователя (например, "кофейни", "музеи искусств", "набережные")
        
        Returns:
            Словарь с ключами:
            - intent: основное намерение ('venue', 'culture', 'art', 'nature', 'architecture', etc.)
            - categories: список категорий (['кофейни'], ['набережные'], ['музеи искусств'], etc.)
            - keywords: список ключевых слов
        """
        prompt = f"""Проанализируй запрос пользователя и определи его намерение и категории.

Запрос пользователя: "{interests}"

Определи:
1. Основное намерение (intent) - выбери ОДНО из: venue, culture, art, nature, architecture, shopping, sports, entertainment, view, general
2. Конкретные категории - что именно ищет пользователь

ВОЗМОЖНЫЕ КАТЕГОРИИ:
- venue: кофейни, рестораны, бары, суши-бар, кафе
- culture: музеи, музеи искусств, театры, выставки
- art: стрит-арт, граффити, муралы, уличное искусство
- nature: набережные, парки, скверы
- architecture: соборы, храмы, кремль, архитектурные памятники
- shopping: торговые центры, магазины, шоппинг
- sports: спорт, стадионы, фитнес
- entertainment: кинотеатры, клубы, развлечения
- view: панорамы, смотровые площадки
- general: общие достопримечательности

ПРАВИЛА:
- Если запрос содержит "музей искусств" или "художественный музей" → intent: culture, категории: ["музеи искусств"]
- Если запрос содержит "набережная" или "набережные" → intent: nature, категории: ["набережные"]
- Если запрос содержит "стрит-арт" или "граффити" → intent: art, категории: ["стрит-арт"]
- Если запрос содержит "кофейни" или "кафе" → intent: venue, категории: ["кофейни"]
- Если запрос содержит "рестораны" → intent: venue, категории: ["рестораны"]
- Если запрос содержит "суши" или "суши-бар" → intent: venue, категории: ["суши-бар"]
- Анализируй смысл, а не только слова!

Ответь ТОЛЬКО в формате JSON без дополнительного текста:
{{
    "intent": "venue",
    "categories": ["кофейни"],
    "keywords": ["кофе", "кофейня", "кафе"]
}}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=200,
                temperature=0.3,
                messages=[
                    {
                        "role": "system",
                        "content": "Ты помощник для анализа туристических запросов. Отвечай ТОЛЬКО в формате JSON без дополнительного текста."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            
            response_text = response.choices[0].message.content.strip()
            
            if response_text.startswith('```'):
                lines = response_text.split('\n')
                response_text = '\n'.join(lines[1:-1]) if len(lines) > 2 else response_text
            response_text = response_text.strip().strip('```').strip()
            
            try:
                result = json.loads(response_text)
                
                intent = result.get('intent', 'general')
                categories = result.get('categories', [])
                keywords = result.get('keywords', [])
                
                valid_intents = ['venue', 'culture', 'art', 'nature', 'architecture', 'shopping', 'sports', 'entertainment', 'view', 'general']
                if intent not in valid_intents:
                    intent = 'general'
                
                return {
                    'intent': intent,
                    'categories': categories if isinstance(categories, list) else [],
                    'keywords': keywords if isinstance(keywords, list) else []
                }
            except json.JSONDecodeError:
                return self._fallback_analyze_interests(interests)
                
        except Exception:
            return self._fallback_analyze_interests(interests)
    
    def _fallback_analyze_interests(self, interests: str) -> Dict[str, any]:
        """Fallback метод для анализа интересов при недоступности GigaChat"""
        interests_lower = interests.lower()
        if any(word in interests_lower for word in ['кофейн', 'кафе', 'ресторан', 'бар', 'суши']):
            intent = 'venue'
            if 'суши' in interests_lower:
                categories = ['суши-бар']
            elif 'ресторан' in interests_lower:
                categories = ['рестораны']
            elif any(word in interests_lower for word in ['кофейн', 'кафе', 'кофе']):
                categories = ['кофейни']
            else:
                categories = ['venue']
        elif any(word in interests_lower for word in ['музей искусств', 'художественный музей']):
            intent = 'culture'
            categories = ['музеи искусств']
        elif any(word in interests_lower for word in ['набережн']):
            intent = 'nature'
            categories = ['набережные']
        elif any(word in interests_lower for word in ['стрит-арт', 'граффити', 'мурал']):
            intent = 'art'
            categories = ['стрит-арт']
        elif any(word in interests_lower for word in ['музей', 'театр', 'выставка']):
            intent = 'culture'
            categories = ['музеи']
        elif any(word in interests_lower for word in ['парк', 'сквер', 'сад']):
            intent = 'nature'
            categories = ['парки']
        else:
            intent = 'general'
            categories = []
        
        return {
            'intent': intent,
            'categories': categories,
            'keywords': interests_lower.split()
        }
