import requests
import logging
import re
from typing import Optional, Tuple, Dict, List
import urllib.parse
import config

logger = logging.getLogger(__name__)


class Maps2GISService:
    """
    Сервис для работы с 2ГИС API
    
    Используемые API:
    - Places API: https://docs.2gis.com/ru/api/search/overview
    - Geocoder API: https://docs.2gis.com/ru/api/search/geocode/overview
    - Routing API: https://docs.2gis.com/ru/api/navigation/route/overview
    
    Регион: Нижний Новгород (region_id = 4 или используется поиск по названию)
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.DVGIS_API_KEY
        # Базовые URL для 2ГИС API согласно документации
        # Catalog API v3.0 для поиска и геокодирования
        self.catalog_url = "https://catalog.api.2gis.com/3.0"
        # Routing API для построения маршрутов
        self.routing_url = "https://routing.api.2gis.com/routing/7.0.0/global"
        # Регион: Нижний Новгород (slug для API)
        self.region = "nnovgorod"  # Нижний Новгород в 2ГИС
    
    def _normalize_address(self, address: str) -> List[str]:
        """
        Нормализует адрес и создает варианты для исправления опечаток
        Возвращает список вариантов адреса для попыток геокодирования
        """
        if not address:
            return []
        
        # Нормализуем базовый адрес
        address_normalized = ' '.join(address.split())
        address_lower = address_normalized.lower()
        
        # Варианты для попыток
        variants = []
        
        # 1. Базовый вариант с нормализацией сокращений
        normalized = address_normalized
        
        # Исправляем типичные опечатки и сокращения
        replacements = {
            # Сокращения улиц
            r'\bул\s+': 'улица ',
            r'\bул\.': 'улица ',
            r'\bулица\s+': 'улица ',
            r'\bулиц\s+': 'улица ',
            # Сокращения проспектов
            r'\bпр\s+': 'проспект ',
            r'\bпр\.': 'проспект ',
            r'\bпр-т\s+': 'проспект ',
            # Сокращения площадей
            r'\bпл\s+': 'площадь ',
            r'\bпл\.': 'площадь ',
            # Сокращения домов
            r'\bд\s+': 'дом ',
            r'\bд\.': 'дом ',
            # Исправление типичных опечаток в популярных улицах Нижнего Новгорода
            r'\bпокровка\b': 'Покровка',
            r'\bбольшая\s+покровская': 'Большая Покровская',
            r'\bварварская': 'Варварская',
            r'\bильинская': 'Ильинская',
            r'\bрождественская': 'Рождественская',
            r'\bрождestвенская': 'Рождественская',  # Исправление опечатки
            r'\bпискунова': 'Пискунова',
            r'\bбольшая\s+печерская': 'Большая Печёрская',
            r'\bпечерская': 'Печёрская',
            r'\bминина': 'Минина',
            r'\bкостина': 'Костина',
            r'\bванеева': 'Ванеева',
            r'\bсоветская': 'Советская',
            r'\bленина': 'Ленина',
        }
        
        for pattern, replacement in replacements.items():
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        
        variants.append(normalized)
        
        # 2. Вариант без номера дома (если есть)
        # Убираем номер дома для более гибкого поиска
        address_no_house = re.sub(r',?\s*(д\.|дом)\s*\d+', '', normalized, flags=re.IGNORECASE)
        address_no_house = re.sub(r',\s*\d+$', '', address_no_house)  # Убираем номер в конце
        if address_no_house.strip() != normalized.strip():
            variants.append(address_no_house.strip())
        
        # 3. Вариант с добавлением города (если нет)
        city_variants = ['нижний новгород', 'н.новгород', 'н. новгород', 'нн']
        has_city = any(variant in address_lower for variant in city_variants)
        
        if not has_city:
            for variant in variants:
                if ', Нижний Новгород' not in variant:
                    variants.append(f"{variant}, Нижний Новгород")
        
        # Убираем дубликаты, сохраняя порядок
        seen = set()
        unique_variants = []
        for variant in variants:
            if variant.lower() not in seen:
                seen.add(variant.lower())
                unique_variants.append(variant)
        
        return unique_variants
    
    def geocode_address(self, address: str) -> Optional[Tuple[float, float]]:
        """
        Геокодирует адрес в координаты (longitude, latitude)
        Автоматически исправляет типичные опечатки в названиях улиц
        
        Использует 2ГИС Geocoder API:
        https://docs.2gis.com/ru/api/search/geocode/overview
        
        Args:
            address: Адрес для геокодирования (например, "ул. Покровка, 1" или "Нижний Новгород, ул. Покровка, 1")
        
        Returns:
            Tuple[lon, lat] или None в случае ошибки
        """
        if not self.api_key:
            return None
        
        # Получаем нормализованные варианты адреса для исправления опечаток
        address_variants = self._normalize_address(address)
        
        if not address_variants:
            return None
        
        # 2ГИС Geocoder API согласно документации
        url = f"{self.catalog_url}/items/geocode"
        
        # Пробуем каждый вариант адреса
        for variant_address in address_variants:
            try:
                params = {
                    "key": self.api_key,
                    "q": variant_address,
                    "region": self.region,
                    "fields": "items.point"
                }
                
                response = requests.get(url, params=params, timeout=5)
                response.raise_for_status()
                
                data = response.json()
                
                if 'result' in data and 'items' in data['result']:
                    items = data['result']['items']
                    if items:
                        # Первый результат
                        point = items[0].get('point', {})
                        if point:
                            lon = point.get('lon')
                            lat = point.get('lat')
                            if lon and lat:
                                coords = (float(lon), float(lat))
                                # Проверяем, что координаты в Нижнем Новгороде
                                if self._is_in_nizhny_novgorod(coords[0], coords[1]):
                                    logger.debug(f"Адрес '{address}' успешно геокодирован как '{variant_address}' -> ({lat:.6f}, {lon:.6f})")
                                    return coords
                                else:
                                    logger.debug(f"Геокодированный адрес '{variant_address}' находится вне Нижнего Новгорода")
                                    continue  # Пробуем следующий вариант
            except Exception as e:
                logger.debug(f"Ошибка при геокодировании варианта '{variant_address}': {e}")
                continue  # Пробуем следующий вариант
        
        # Если ни один вариант не сработал
        logger.warning(f"Не удалось геокодировать адрес '{address}' (попробовано {len(address_variants)} вариантов)")
        return None
    
    def build_route(self, points: List[Tuple[float, float]], 
                   route_type: str = "pedestrian") -> Optional[Dict]:
        """
        Строит маршрут между точками
        
        Использует 2ГИС Routing API:
        https://docs.2gis.com/ru/api/navigation/route/overview
        
        Args:
            points: список кортежей (lon, lat) - точки маршрута
            route_type: "pedestrian" (пешком), "transit" (общественный транспорт), "auto" (автомобиль)
        
        Returns:
            dict с ключами:
            - total_distance: общее расстояние в метрах
            - total_duration: общее время в секундах
            - segments: список сегментов маршрута
            или None в случае ошибки
        """
        if not self.api_key or len(points) < 2:
            return None
        
        try:
            # 2ГИС Routing API использует JSON body
            url = f"{self.routing_url}"
            
            # Формируем точки маршрута
            # 2ГИС Routing API требует формат: [{"lon": ..., "lat": ...}, ...]
            waypoints = []
            for lon, lat in points:
                waypoints.append({
                    "lon": lon,
                    "lat": lat
                })
            
            # Определяем тип маршрута
            routing_type = "pedestrian"
            if route_type == "auto":
                routing_type = "car"
            elif route_type == "transit":
                routing_type = "transit"
            else:
                routing_type = "pedestrian"
            
            # 2ГИС Routing API согласно документации
            # https://docs.2gis.com/ru/api/navigation/route/overview
            # 2ГИС Routing API может использовать ключ как параметр или в header
            # Попробуем оба варианта
            payload = {
                "type": routing_type,
                "points": waypoints,
                "locale": "ru_RU"
            }
            
            # Вариант 1: ключ в параметрах
            params_route = {"key": self.api_key}
            
            response = requests.post(url, json=payload, params=params_route, timeout=5)  # Уменьшен для ускорения
            
            # Если не сработало, пробуем вариант с Authorization header
            if response.status_code == 401 or response.status_code == 403:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                response = requests.post(url, json=payload, headers=headers, timeout=5)  # Уменьшен для ускорения
            
            # Обрабатываем ошибку 429 (too many requests)
            if response.status_code == 429:
                logger.warning(f"2ГИС Routing API вернул 429 (too many requests) - используем оценку по формуле гаверсинуса")
                return None  # Вернем None, чтобы использовалась оценка по гаверсинусу
            
            # Логируем другие ошибки для отладки
            if response.status_code != 200:
                logger.warning(f"2ГИС Routing API вернул код {response.status_code}: {response.text}")
            
            # Только для не-429 ошибок делаем raise_for_status
            if response.status_code != 429:
                response.raise_for_status()
            else:
                return None  # Для 429 возвращаем None без исключения
            
            data = response.json()
            
            # 2ГИС Routing API возвращает result как массив маршрутов
            if 'result' in data and isinstance(data['result'], list) and len(data['result']) > 0:
                route_info = data['result'][0]
                
                # Извлекаем информацию о маршруте
                # В 2ГИС API distance и duration находятся в maneuvers[].outcoming_path
                total_distance = 0
                total_duration = 0
                
                maneuvers = route_info.get('maneuvers', [])
                for maneuver in maneuvers:
                    outcoming_path = maneuver.get('outcoming_path', {})
                    if outcoming_path:
                        total_distance += outcoming_path.get('distance', 0)
                        total_duration += outcoming_path.get('duration', 0)
                
                # Сегменты маршрута
                segments = []
                if 'segments' in route_info:
                    for segment in route_info['segments']:
                        segments.append({
                            'distance': segment.get('distance', 0),
                            'duration': segment.get('duration', 0)
                        })
                elif 'maneuvers' in route_info:
                    # Используем maneuvers как сегменты
                    for maneuver in route_info['maneuvers']:
                        outcoming_path = maneuver.get('outcoming_path', {})
                        if outcoming_path:
                            segments.append({
                                'distance': outcoming_path.get('distance', 0),
                                'duration': outcoming_path.get('duration', 0)
                            })
                
                return {
                    'total_distance': total_distance,
                    'total_duration': total_duration,
                    'segments': segments
                }
            
            return None
        except Exception as e:
            logger.warning(f"Ошибка построения маршрута 2ГИС: {e}")
            return None
    
    def search_places(self, query: str, location: Optional[Tuple[float, float]] = None, 
                     category: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """
        Ищет места через 2ГИС Places API с поддержкой пагинации
        
        Использует 2ГИС Places API:
        https://docs.2gis.com/ru/api/search/places/overview
        
        Args:
            query: Поисковый запрос (например, "кофейни", "музеи")
            location: Координаты для поиска рядом (lon, lat)
            category: Категория поиска (опционально)
            limit: Максимальное количество результатов (может быть больше через пагинацию)
        
        Returns:
            Список найденных мест с координатами и адресами, отсортированный по популярности и расстоянию
        """
        if not self.api_key:
            return []
        
        all_places = []
        # КРИТИЧЕСКИ ВАЖНО: Ограничиваем количество страниц для ускорения работы!
        # 2ГИС API ограничивает page_size до 10
        # Получаем только первые страницы для скорости, затем фильтруем по расстоянию и рейтингу
        max_pages = 10  # Максимум 10 страниц (100 результатов) - достаточно для ближайших мест
        page_size = 10
        
        try:
            url = f"{self.catalog_url}/items"
            
            # Формируем запрос - добавляем "Нижний Новгород" для поиска в нужном городе
            # API не работает с параметром region, нужно указывать город в запросе
            if 'нижний новгород' not in query.lower():
                search_query = f"{query.strip()} Нижний Новгород"
            else:
                search_query = query.strip()
            
            # КРИТИЧЕСКИ ВАЖНО: НЕ используем radius в запросе API!
            # Получаем ВСЕ места по запросу, потом фильтруем по расстоянию сами
            # Параметры point/radius в 2ГИС API могут ограничивать результаты
            point_param = None
            radius = None
            # location используем только для вычисления расстояния после получения результатов
            
            # Загружаем данные с нескольких страниц (до 100 страниц = 1000 результатов)
            for page in range(1, max_pages + 1):
                if page % 10 == 0:  # Логируем каждую 10-ю страницу
                    logger.debug(f"Загрузка страницы {page}/{max_pages} (найдено {len(all_places)} мест)")
                
                params = {
                    "key": self.api_key,
                    "q": search_query,
                    "page_size": page_size,
                    "page": page,
                    "fields": "items.point,items.reviews"  # Получаем координаты и отзывы с рейтингом
                }
                
                # КРИТИЧЕСКИ ВАЖНО: Добавляем сортировку по расстоянию для получения ближайших мест!
                if location:
                    # Используем location для сортировки по расстоянию
                    lon, lat = location
                    params["location"] = f"{lon},{lat}"
                    params["sort"] = "distance"  # Сортировка по расстоянию
                
                # Пробуем без параметров point/radius сначала, если они не работают
                # 2ГИС API может не поддерживать эти параметры или требовать другой формат
                # if point_param:
                #     params["point"] = point_param
                #     params["radius"] = radius
                
                response = requests.get(url, params=params, timeout=5)  # Уменьшен таймаут для ускорения
                response.raise_for_status()
                
                data = response.json()
                
                # Проверяем код ответа
                api_code = data.get('meta', {}).get('code', 0)
                
                # Отладка структуры ответа
                # API ответ получен
                
                # Если код ошибки, логируем и пропускаем эту страницу
                if api_code != 200:
                    error_msg = data.get('error', {}).get('message', 'Unknown error')
                    # Для страниц > 5 логируем как debug (это нормально - API может не возвращать больше страниц)
                    if page <= 5:
                        logger.warning(f"Ошибка API на странице {page}: {error_msg}")
                    
                    # Если это первая страница и ошибка, прекращаем поиск
                    if page == 1:
                        break
                    # Для других страниц - просто прекращаем пагинацию (нет больше результатов)
                    break
                
                if 'result' in data and 'items' in data['result']:
                    items = data['result']['items']
                    # Элементы получены
                    if not items:
                        break  # Больше результатов нет
                    
                    for item in items:
                        name = item.get('name', 'Без названия')
                        if not name:
                            continue
                        
                        # Получаем рубрики (категории) - они могут быть не в ответе, используем type или name
                        rubrics = item.get('rubrics', [])
                        category_name = ''
                        # Собираем все категории из рубрик для более точной фильтрации
                        if rubrics:
                            category_names = [r.get('name', '') for r in rubrics if r.get('name')]
                            category_name = ', '.join(category_names) if category_names else ''
                        # Если рубрик нет, используем type как категорию
                        if not category_name:
                            category_name = item.get('type', '')
                        
                        # Получаем рейтинг и количество отзывов из отзывов
                        # 2ГИС возвращает рейтинг в reviews.general_rating или reviews.org_rating
                        # Количество отзывов в reviews.count или reviews.review_count
                        reviews = item.get('reviews', {})
                        rating = 0
                        reviews_count = 0
                        if isinstance(reviews, dict):
                            # Пробуем разные варианты извлечения рейтинга
                            rating = reviews.get('general_rating', 0)  # Основной рейтинг
                            if not rating:
                                rating = reviews.get('org_rating', 0)  # Альтернативный рейтинг
                            # Проверяем, что это число
                            if not isinstance(rating, (int, float)):
                                rating = 0
                            
                            # Извлекаем количество отзывов
                            reviews_count = reviews.get('count', 0)  # Основное поле
                            if not reviews_count:
                                reviews_count = reviews.get('review_count', 0)  # Альтернативное поле
                            if not reviews_count:
                                reviews_count = reviews.get('total_reviews', 0)  # Еще один вариант
                            # Проверяем, что это число
                            if not isinstance(reviews_count, (int, float)):
                                reviews_count = 0
                        elif isinstance(reviews, (int, float)):
                            rating = reviews
                            reviews_count = 0
                        
                        # Получаем координаты из ответа API (если доступны)
                        point = item.get('point')
                        lon, lat = None, None
                        
                        # Проверяем разные форматы point
                        if point:
                            if isinstance(point, dict):
                                # Координаты уже в ответе как словарь
                                lon = point.get('lon')
                                lat = point.get('lat')
                            elif isinstance(point, (list, tuple)) and len(point) >= 2:
                                # Координаты как список [lon, lat]
                                lon, lat = point[0], point[1]
                        
                        # Если координат нет в ответе, пытаемся через геокодирование
                        if not lon or not lat:
                            # Пробуем геокодирование
                            geocode_query = f"{name}, Нижний Новгород"
                            coords = self.geocode_address(geocode_query)
                            if coords:
                                lon, lat = coords
                                # Координаты получены
                            else:
                                logger.warning(f"Не удалось получить координаты для '{name}' - пропускаем")
                                continue
                        
                        # Проверяем, что координаты валидные
                        try:
                            lon = float(lon)
                            lat = float(lat)
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Некорректные координаты для '{name}': lon={lon}, lat={lat}, ошибка: {e}")
                            continue
                        
                        # КРИТИЧЕСКИ ВАЖНО: Проверяем, что место находится в Нижнем Новгороде
                        if not self._is_in_nizhny_novgorod(lon, lat):
                            # Место вне города, пропущено
                            continue
                        
                        # Получаем ID организации из API (нужен для ссылок на карту)
                        firm_id = item.get('id', '')
                        
                        # Вычисляем расстояние от пользователя, если указано местоположение
                        distance = None
                        if location:
                            from math import radians, cos, sin, asin, sqrt
                            lon1, lat1 = location
                            lon2, lat2 = lon, lat
                            R = 6371000  # Радиус Земли в метрах
                            dlat = radians(lat2 - lat1)
                            dlon = radians(lon2 - lon1)
                            a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
                            c = 2 * asin(sqrt(a))
                            distance = R * c
                        
                        # Формируем точный адрес из данных API
                        address_name = item.get('address_name', '')
                        address_comment = item.get('address_comment', '')
                        
                        # Очищаем от None и лишних пробелов
                        if address_name:
                            address_name = str(address_name).strip()
                        else:
                            address_name = ''
                        
                        if address_comment and address_comment != 'None':
                            address_comment = str(address_comment).strip()
                        else:
                            address_comment = ''
                        
                        # Собираем полный адрес
                        if address_name:
                            # Используем точный адрес из API
                            full_address = f"Нижний Новгород, {address_name}"
                            if address_comment:
                                full_address += f", {address_comment}"
                        else:
                            # Если адреса нет в API, используем название как адрес
                            full_address = f"{name}, Нижний Новгород"
                        
                        # КРИТИЧЕСКИ ВАЖНО: Фильтруем по минимальному рейтингу 4.1!
                        rating_value = float(rating) if rating else 0
                        if rating_value > 0 and rating_value < 4.1:
                            # Пропускаем место с низким рейтингом
                            continue
                        
                        # Формируем объект места
                        place = {
                            'title': name,
                            'address': full_address,  # Точный адрес из API
                            'lon': float(lon),
                            'lat': float(lat),
                            'source': '2gis',
                            'description': category_name,
                            'category': category_name,
                            'rating': rating_value,  # Рейтинг из API
                            'reviews_count': int(reviews_count) if reviews_count else 0,  # Количество отзывов из API
                            'distance_from_user': distance,  # Расстояние от пользователя в метрах
                            'firm_id': str(firm_id) if firm_id else None,  # ID организации для ссылки на карту
                        }
                        
                        all_places.append(place)
                    
                    # Если получили меньше результатов, чем запросили, значит больше страниц нет
                    if len(items) < page_size:
                        logger.debug(f"Получено меньше результатов ({len(items)}) на странице {page}, прекращаем пагинацию")
                        break
                else:
                    logger.debug(f"Структура ответа API неожиданная, прекращаем пагинацию на странице {page}")
                    break
            
            logger.debug(f"Всего найдено мест до фильтрации: {len(all_places)}")
            
            # КРИТИЧЕСКИ ВАЖНО: Правильная логика - сначала ближайшие, потом лучшие среди них!
            if location:
                # ШАГ 1: Фильтруем: оставляем только места в радиусе 4-5км от пользователя
                # Увеличено до 4-5км, чтобы найти больше вариантов, потом выберем ближайшие с лучшим рейтингом
                MAX_SEARCH_RADIUS = 5000  # 5 км - расширенный радиус поиска
                filtered_places = [
                    place for place in all_places
                    if place.get('distance_from_user') is not None and place.get('distance_from_user') <= MAX_SEARCH_RADIUS
                ]
                
                logger.debug(f"После фильтрации по {MAX_SEARCH_RADIUS/1000:.1f}км: {len(filtered_places)} мест из {len(all_places)}")
                
                # Если после фильтрации есть места - используем их
                if filtered_places:
                    all_places = filtered_places
                    logger.debug(f"Отфильтровано до {len(all_places)} мест в радиусе {MAX_SEARCH_RADIUS/1000:.1f}км")
                
                # ШАГ 2: Сортируем: сначала по расстоянию (ближайшие первыми), затем по рейтингу (лучшие среди ближайших)
                # Это гарантирует: сначала находим ближайшие места, потом среди них выбираем лучшие по рейтингу
                all_places = sorted(
                    all_places, 
                    key=lambda x: (
                        x.get('distance_from_user', float('inf')),  # Сначала по расстоянию (возрастание) - ПРИОРИТЕТ!
                        -x.get('rating', 0),  # Потом по рейтингу (убывание)
                        -x.get('reviews_count', 0)  # Потом по количеству отзывов (убывание)
                    )
                )
            else:
                # Только по рейтингу
                all_places = sorted(all_places, key=lambda x: x.get('rating', 0), reverse=True)
            
            logger.debug(f"Найдено {len(all_places)} мест через 2ГИС API (после фильтрации и сортировки)")
            # КРИТИЧЕСКИ ВАЖНО: Возвращаем ВСЕ места после фильтрации, не ограничиваем лимитом!
            # Лимит был нужен только для ограничения количества запросов к API, но теперь мы получаем все
            return all_places  # Возвращаем ВСЕ отфильтрованные и отсортированные места
            
        except Exception as e:
            logger.warning(f"Ошибка поиска мест через 2ГИС: {e}")
            return []
    
    def _is_in_nizhny_novgorod(self, lon: float, lat: float) -> bool:
        """
        Проверяет, находятся ли координаты в пределах Нижнего Новгорода
        Границы города: примерно 56.15-56.45°N, 43.75-44.35°E
        """
        # Границы Нижнего Новгорода
        min_lat, max_lat = 56.15, 56.45
        min_lon, max_lon = 43.75, 44.35
        
        return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon
    
    def estimate_walking_time(self, distance_meters: float) -> int:
        """
        Оценивает время пешей ходьбы (в минутах)
        Средняя скорость пешехода: ~5 км/ч = ~83 м/мин
        """
        if distance_meters <= 0:
            return 0
        
        # Добавляем 10% запас
        time_minutes = int((distance_meters / 83) * 1.1)
        return max(1, time_minutes)  # Минимум 1 минута
    
    def get_map_link(self, points: List[Tuple[float, float]]) -> str:
        """
        Генерирует ссылку на 2ГИС карту с отмеченными точками
        """
        if not points:
            return ""
        
        # 2ГИС использует формат: https://2gis.ru/nnovgorod/firm/...
        # Для множественных точек можно использовать поиск
        # Формируем ссылку на карту с координатами
        if len(points) == 1:
            lon, lat = points[0]
            map_url = f"https://2gis.ru/nnovgorod/?m={lon},{lat}&zoom=13"
        else:
            # Для нескольких точек используем первый как центр
            lon, lat = points[0]
            map_url = f"https://2gis.ru/nnovgorod/?m={lon},{lat}&zoom=13"
        
        return map_url
    
    def get_route_map_link(self, points: List[Tuple[float, float]], 
                           objects: Optional[List[Dict]] = None) -> str:
        """
        Генерирует ссылку на 2ГИС карту с проложенным маршрутом между точками
        Использует формат: https://2gis.ru/n_novgorod/directions/points/...
        
        Args:
            points: список координат [(lon, lat), ...]
            objects: список объектов с информацией о местах (для получения firm_id)
        
        Returns:
            Ссылка на карту 2ГИС с маршрутом
        """
        if len(points) < 2:
            return self.get_map_link(points)
        
        # Формат 2ГИС для маршрута:
        # https://2gis.ru/n_novgorod/directions/points/{lon1,lat1;firm_id1|lon2,lat2;firm_id2|...}?m={center_lon,center_lat}/{zoom}
        # ВАЖНО: координаты в формате lon,lat (как в примере: 44.00235,56.327244)
        # ВАЖНО: первая точка тоже включается в маршрут (начальная точка пользователя)
        
        route_points = []
        for i, (lon, lat) in enumerate(points):
            # Формируем точку маршрута
            # ВАЖНО: 2ГИС использует формат lon,lat (как в примере: 44.00235,56.327244)
            point_str = f"{lon},{lat}"
            
            # Если есть объект с firm_id для этой точки, добавляем его
            # objects соответствуют точкам маршрута начиная с points[1] (первая точка - пользователь без объекта)
            if objects and i > 0:
                # Для точек маршрута (начиная с i=1) берем соответствующие объекты
                obj_index = i - 1  # objects[0] соответствует points[1], objects[1] - points[2], и т.д.
                if obj_index < len(objects):
                    obj = objects[obj_index]
                    firm_id = obj.get('firm_id')
                    if firm_id:
                        point_str += f";{firm_id}"
            # Для первой точки (i=0, начало маршрута пользователя) firm_id обычно нет
            # Но если в примере он есть - возможно это первое место, а не начальная точка
            
            route_points.append(point_str)
        
        # Кодируем точки для URL
        points_encoded = urllib.parse.quote("|".join(route_points))
        
        # Вычисляем центр карты (средняя точка маршрута)
        # Формат параметра m: lon,lat/zoom (как в примере: m=43.996555,56.306949/13.26)
        if len(points) > 1:
            # Пропускаем первую точку (пользователь) для расчета центра
            route_points_only = points[1:]
            center_lon = sum(lon for lon, _ in route_points_only) / len(route_points_only)
            center_lat = sum(lat for _, lat in route_points_only) / len(route_points_only)
            zoom = "13.26"  # Стандартный зум для маршрута
        else:
            center_lon, center_lat = points[0]  # lon, lat
            zoom = "13"
        
        # Формируем ссылку для ПЕШЕХОДНОГО маршрута
        # Добавляем параметр mode=walk для явного указания пешеходного режима
        map_url = f"https://2gis.ru/n_novgorod/directions/points/{points_encoded}?m={center_lon},{center_lat}/{zoom}&mode=walk"
        
        return map_url

