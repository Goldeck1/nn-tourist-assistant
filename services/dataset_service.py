import pandas as pd
import logging
from typing import List, Dict, Optional
from utils.helpers import parse_coordinates, clean_html, extract_keywords
import config

logger = logging.getLogger(__name__)


class DatasetService:
    """Сервис для работы с датасетом культурных объектов"""
    
    def __init__(self, dataset_path: str = config.DATASET_PATH):
        self.dataset_path = dataset_path
        self.df: Optional[pd.DataFrame] = None
        self._load_dataset()
    
    def _load_dataset(self):
        """Загружает датасет из Excel файла"""
        try:
            self.df = pd.read_excel(self.dataset_path)
            # Парсинг координат
            self.df['lon'] = self.df['coordinate'].apply(
                lambda x: parse_coordinates(x)[0] if parse_coordinates(x) else None
            )
            self.df['lat'] = self.df['coordinate'].apply(
                lambda x: parse_coordinates(x)[1] if parse_coordinates(x) else None
            )
            # Очистка описаний от HTML
            self.df['description_clean'] = self.df['description'].apply(clean_html)
            logger.debug(f"Загружено {len(self.df)} объектов из датасета")
        except Exception as e:
            logger.error(f"Ошибка загрузки датасета: {e}")
            self.df = pd.DataFrame()
    
    def filter_by_interests(self, interests: str, limit: int = 20) -> List[Dict]:
        """
        Фильтрует объекты по интересам пользователя с умным анализом
        """
        if self.df is None or len(self.df) == 0:
            return []
        
        interests_lower = interests.lower()
        keyword_data = extract_keywords(interests_lower)
        
        # Поддерживаем обратную совместимость со старым форматом
        if isinstance(keyword_data, dict):
            keywords = keyword_data.get('keywords', [])
            detected_categories = keyword_data.get('categories', [])
            user_intent = keyword_data.get('intent', 'general')
        else:
            # Старый формат (список)
            keywords = keyword_data if keyword_data else []
            detected_categories = []
            user_intent = 'general'
        
        if not keywords:
            # Если ключевые слова не найдены, возвращаем популярные объекты
            return self.df.head(limit).to_dict('records')
        
        # Проверяем намерение пользователя
        is_venue_request = user_intent == 'venue' or any(kw in interests_lower for kw in ['ресторан', 'рестораны', 'кафе', 'кофейня', 'кофейни', 'бар', 'бары', 'еда', 'кухня', 'столовая', 'трактир', 'бистро'])
        is_coffee_request = user_intent == 'venue' or any(kw in interests_lower for kw in ['кофейни', 'кофейня', 'кафе', 'кофе'])
        is_culture_request = user_intent == 'culture' or any(kw in detected_categories for kw in ['музеи', 'театры', 'история'])
        is_art_request = user_intent == 'art' or any(kw in detected_categories for kw in ['стрит-арт', 'граффити'])
        is_architecture_request = user_intent == 'architecture' or any(kw in detected_categories for kw in ['архитектура', 'кремль', 'соборы'])
        is_view_request = user_intent == 'view' or any(kw in detected_categories for kw in ['панорамы'])
        is_nature_request = user_intent == 'nature' or any(kw in detected_categories for kw in ['парки', 'набережная'])
        
        # КРИТИЧЕСКИ ВАЖНО: Для запросов на заведения (venue) НЕ ищем в датасете культурных объектов
        # Датасет содержит только культурные объекты, не реальные заведения общественного питания
        if is_venue_request and user_intent == 'venue':
            # Возвращаем пустой список - заведения нужно искать только в открытых источниках
            logger.debug(f"Запрос на заведения - используем только 2ГИС API")
            return []
        
        # КРИТИЧЕСКИ ВАЖНО: Для запросов на стрит-арт НЕ ищем в датасете
        # Стрит-арт нужно искать только в открытых источниках (2ГИС API)
        if is_art_request and user_intent == 'art':
            # Возвращаем пустой список - стрит-арт нужно искать только в открытых источниках
            logger.debug(f"Запрос на стрит-арт - используем только 2ГИС API")
            return []
        
        # Поиск объектов по ключевым словам
        filtered_df = pd.DataFrame()
        
        # Создаем маску для поиска
        search_mask = pd.Series([False] * len(self.df))
        
        # Поиск по каждому ключевому слову
        for keyword in keywords:
            if len(keyword) < 3:
                continue
            
            # Для запросов заведений (venue) НЕ ищем в датасете - только в открытых источниках
            if is_venue_request:
                # Пропускаем поиск в датасете для заведений
                continue
            
            # Для запросов стрит-арта НЕ ищем в датасете - только в открытых источниках
            if is_art_request:
                # Пропускаем поиск в датасете для стрит-арта
                continue
            
            # Для запросов кофеен используем ОЧЕНЬ строгий фильтр (если все же ищем)
            if is_coffee_request and keyword in ['кофе', 'кафе', 'кофейня']:
                # Ищем ТОЛЬКО реальные заведения - названия начинаются с ключевых слов или содержат их отдельно
                # Паттерн: слово стоит отдельно или в начале названия (без групп захвата)
                pattern = r'\b(?:кафе|кофейня|ресторан|бар)\b'
                title_mask = self.df['title'].str.contains(pattern, case=False, na=False, regex=True)
                
                # Исключаем ВСЕ объекты, где кофе упоминается в контексте искусства/памятников/скульптур
                exclude_keywords = [
                    'вывеска', 'скульптур', 'памятник', 'мозаик', 'обезьянка', 
                    'произведен', 'реестр', 'монумент', 'искусств', 'декоративн',
                    'советск', 'монументальн', 'автор', 'создан', 'нижегородск'
                ]
                exclude_pattern = '|'.join(exclude_keywords)
                exclude_mask = self.df['title'].str.contains(exclude_pattern, case=False, na=False, regex=True)
                
                # Также исключаем по описанию, если там упоминается искусство
                desc_exclude_mask = self.df['description_clean'].str.contains(
                    exclude_pattern, case=False, na=False, regex=True
                )
                
                # Применяем исключения
                title_mask &= ~exclude_mask
                title_mask &= ~desc_exclude_mask
                
                search_mask |= title_mask
            else:
                # Обычный поиск для других запросов
                # Поиск в названии (высокий приоритет)
                title_mask = self.df['title'].str.contains(keyword, case=False, na=False, regex=False)
                
                # Поиск в описании
                desc_mask = self.df['description_clean'].str.contains(keyword, case=False, na=False, regex=False)
                
                # Поиск в адресе (для улиц, площадей)
                address_mask = self.df['address'].str.contains(keyword, case=False, na=False, regex=False)
                
                # Объединяем маски
                keyword_mask = title_mask | desc_mask | address_mask
                search_mask |= keyword_mask
        
        filtered_df = self.df[search_mask].copy() if search_mask.any() else pd.DataFrame()
        
        # Специальная обработка для разных категорий интересов
        category_filters = {
            'стрит-арт': {
                'keywords': ['граффити', 'стрит-арт', 'мурал', 'уличн', 'street art', 'mural', 'wall art'],
                'search_in': ['title', 'description_clean'],
                'require_keywords_in_title': True,  # Требуем ключевые слова в названии для большей релевантности
                'exclude': ['музей', 'галерея', 'выставка', 'коллекция', 'фонд', 'архив'],  # Исключаем музеи и галереи
                'prioritize': ['граффити', 'мурал', 'стрит-арт']  # Приоритет этим словам
            },
            'кофейни': {
                'keywords': ['кафе', 'кофейня', 'кофе', 'ресторан', 'бар'],
                'search_in': ['title'],
                'exclude': ['памятник', 'скульптура', 'вывеска', 'монумент', 'обезьянка', 'мозаик', 'скульптурн', 'произведен', 'реестр'],
                'require_exact': True  # Требуем точное соответствие - только реальные заведения
            },
            'панорамы': {
                'keywords': ['панорам', 'смотров', 'обзор', 'вид'],
                'search_in': ['title', 'description_clean']
            },
            'кремль': {
                'keywords': ['кремль', 'кремлев', 'крепость', 'башня'],
                'search_in': ['title', 'description_clean']
            },
            'театры': {
                'keywords': ['театр', 'театральн', 'спектакль'],
                'search_in': ['title', 'description_clean']
            },
            'музеи': {
                'keywords': ['музей', 'выставка', 'галерея'],
                'search_in': ['title', 'description_clean']
            },
        }
        
        # Применяем специальные фильтры для найденных категорий
        for category, config in category_filters.items():
            if any(kw == category or kw in config['keywords'] for kw in keywords):
                category_mask = pd.Series([False] * len(self.df))
                
                # Для категории "кофейни" используем строгий фильтр
                if category == 'кофейни' and config.get('require_exact', False):
                    # Ищем только объекты, где ключевое слово стоит в начале названия или отдельным словом
                    # Исключаем объекты, где это просто упоминание в контексте
                    for keyword in config['keywords']:
                        if keyword in ['кафе', 'кофейня', 'ресторан', 'бар']:
                            # Ищем названия, которые начинаются с ключевого слова или содержат его как отдельное слово
                            pattern = rf'\b{keyword}\b|^{keyword}'
                            title_mask = self.df['title'].str.contains(pattern, case=False, na=False, regex=True)
                            category_mask |= title_mask
                # Для стрит-арта - приоритет объектам с ключевыми словами в названии
                elif category == 'стрит-арт' and config.get('require_keywords_in_title', False):
                    prioritize_keywords = config.get('prioritize', config['keywords'])
                    for keyword in prioritize_keywords:
                        # Приоритет объектам, где ключевое слово в названии
                        title_mask = self.df['title'].str.contains(keyword, case=False, na=False, regex=False)
                        category_mask |= title_mask
                    # Также ищем в описании, но с меньшим приоритетом
                    for keyword in config['keywords']:
                        if keyword not in prioritize_keywords:
                            desc_mask = self.df['description_clean'].str.contains(keyword, case=False, na=False, regex=False)
                            category_mask |= desc_mask
                else:
                    # Обычный поиск для других категорий
                    for keyword in config['keywords']:
                        if 'title' in config['search_in']:
                            category_mask |= self.df['title'].str.contains(keyword, case=False, na=False, regex=False)
                        if 'description_clean' in config['search_in']:
                            category_mask |= self.df['description_clean'].str.contains(keyword, case=False, na=False, regex=False)
                
                # Применяем исключения если есть
                if 'exclude' in config:
                    for exclude_kw in config['exclude']:
                        # Исключаем из названия и описания
                        exclude_title = self.df['title'].str.contains(exclude_kw, case=False, na=False, regex=False)
                        exclude_desc = self.df['description_clean'].str.contains(exclude_kw, case=False, na=False, regex=False)
                        category_mask &= ~(exclude_title | exclude_desc)
                
                if category_mask.any():
                    filtered_df = pd.concat([filtered_df, self.df[category_mask]], ignore_index=True)
        
        # Удаление дубликатов и сортировка по релевантности
        if len(filtered_df) > 0:
            filtered_df = filtered_df.drop_duplicates(subset=['id'])
            
            # Вычисляем релевантность: приоритет объектам с ключевыми словами в названии
            def calculate_relevance(row):
                score = 0
                title_lower = str(row['title']).lower()
                desc_lower = str(row.get('description_clean', '')).lower()
                
                # Специальная обработка для стрит-арта
                if is_art_request:
                    # Приоритет объектам, где ключевые слова в названии
                    if any(kw in title_lower for kw in ['граффити', 'мурал', 'стрит-арт', 'street art']):
                        score += 10  # Максимальный приоритет
                    elif any(kw in desc_lower for kw in ['граффити', 'мурал', 'стрит-арт']):
                        score += 5
                    
                    # Штраф за нерелевантные слова
                    if any(exclude in title_lower or exclude in desc_lower 
                           for exclude in ['музей', 'галерея', 'выставка', 'коллекция']):
                        score -= 5
                
                for kw in keywords:
                    if len(kw) < 3:
                        continue
                    # Высокий балл за совпадение в названии
                    if kw in title_lower:
                        score += 3
                    # Средний балл за совпадение в описании
                    elif kw in desc_lower:
                        score += 1
                
                return score
            
            filtered_df['relevance'] = filtered_df.apply(calculate_relevance, axis=1)
            
            # Сортируем по релевантности (высший балл первым)
            filtered_df = filtered_df.sort_values('relevance', ascending=False)
        else:
            # Если ничего не найдено по интересам, возвращаем пустой список
            # (не случайные объекты - это будет обработано выше)
            return []
        
        return filtered_df.head(limit).to_dict('records')
    
    def get_object_by_id(self, obj_id: int) -> Optional[Dict]:
        """Получает объект по ID"""
        if self.df is None:
            return None
        
        obj = self.df[self.df['id'] == obj_id]
        if len(obj) > 0:
            return obj.iloc[0].to_dict()
        return None
    
    def get_all_objects(self) -> List[Dict]:
        """Возвращает все объекты"""
        if self.df is None:
            return []
        return self.df.to_dict('records')
    
    def format_object_for_prompt(self, obj: Dict) -> str:
        """Форматирует объект для промпта"""
        title = obj.get('title', 'Без названия')
        address = obj.get('address', 'Адрес не указан')
        description = obj.get('description_clean', obj.get('description', 'Описание отсутствует'))
        description_short = description[:200] + '...' if len(description) > 200 else description
        
        return f"Название: {title}\nАдрес: {address}\nОписание: {description_short}"

