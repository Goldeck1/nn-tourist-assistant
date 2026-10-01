from typing import Dict, List, Optional, Tuple
from math import sqrt, radians, cos, sin, asin
from datetime import datetime, timedelta
import pytz
import logging
from services.dataset_service import DatasetService
from services.gigachat import GigaChatService
from services.maps_2gis import Maps2GISService
from utils.helpers import validate_time

logger = logging.getLogger(__name__)


def _is_in_nizhny_novgorod(lon: float, lat: float) -> bool:
    """
    Проверяет, находятся ли координаты в пределах Нижнего Новгорода
    Границы города: примерно 56.15-56.45°N, 43.75-44.35°E
    """
    # Границы Нижнего Новгорода
    min_lat, max_lat = 56.15, 56.45
    min_lon, max_lon = 43.75, 44.35
    
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


class RouteGenerator:
    """Генератор персонализированных маршрутов"""
    
    def __init__(self):
        self.dataset_service = DatasetService()
        self.gigachat_service = GigaChatService()
        self.maps_service = Maps2GISService()
    
    def generate_route(self, interests: str, time_input: str, 
                      location: str, user_id: Optional[int] = None) -> Dict[str, any]:
        """
        Генерирует персонализированный маршрут
        
        Args:
            interests: Интересы пользователя
            time_input: Время на прогулку
            location: Начальное местоположение
            user_id: ID пользователя Telegram (опционально)
        
        Returns:
            dict с ключами: route_text, map_link, success, error
        """
        try:
            # Логирование запроса пользователя
            user_id_str = str(user_id) if user_id is not None else "не указан"
            logger.info(
                f"Запрос маршрута | user_id: {user_id_str} | "
                f"интересы: '{interests}' | время: '{time_input}' | "
                f"место: '{location}'"
            )
            # Валидация времени
            time_minutes = validate_time(time_input)
            if not time_minutes:
                return {
                    'success': False,
                    'error': 'Неверный формат времени. Укажите время в часах (например: 2, 2.5, 3).'
                }
            
            # Геокодирование местоположения
            user_coords = None
            location_str = location
            
            if location:
                # Проверяем, не координаты ли это (формат "lat,lon" или "lon,lat")
                import re
                coord_pattern = r'^[\d.]+,[\d.]+$'
                if re.match(coord_pattern, location.replace(' ', '')):
                    # Это координаты
                    parts = location.replace(' ', '').split(',')
                    if len(parts) == 2:
                        try:
                            coord1 = float(parts[0])
                            coord2 = float(parts[1])
                            
                            # Определяем порядок: широта НН ~56.3, долгота ~44.0
                            # Если первое число в диапазоне 50-60, это скорее всего широта
                            if 50 <= coord1 <= 60:
                                # Формат: lat,lon
                                lat = coord1
                                lon = coord2
                            elif 50 <= coord2 <= 60:
                                # Формат: lon,lat
                                lon = coord1
                                lat = coord2
                            elif 40 <= coord1 <= 50:
                                # Первое число похоже на долготу, второе - на широту
                                lon = coord1
                                lat = coord2
                            else:
                                # По умолчанию считаем первое широтой
                                lat = coord1
                                lon = coord2
                            
                            user_coords = (lon, lat)  # Сохраняем как (lon, lat)
                            location_str = f"Координаты ({lat:.6f}, {lon:.6f})"
                            
                            # Проверяем, что координаты в Нижнем Новгороде
                            if not _is_in_nizhny_novgorod(lon, lat):
                                return {
                                    'success': False,
                                    'error': 'Укажите точку в нижнем новгороде'
                                }
                        except ValueError:
                            pass
                
                # Если не координаты и не удалось определить, пробуем геокодирование
                if not user_coords:
                    user_coords = self.maps_service.geocode_address(location)
                    if user_coords:
                        location_str = f"{location} ({user_coords[1]:.6f}, {user_coords[0]:.6f})"
                        
                        # Проверяем, что координаты в Нижнем Новгороде
                        lon, lat = user_coords
                        if not _is_in_nizhny_novgorod(lon, lat):
                            return {
                                'success': False,
                                'error': 'Укажите точку в нижнем новгороде'
                            }
            
            if not user_coords:
                user_coords = (44.002045, 56.326887)
                location_str = location if location else "Нижний Новгород, центр города"
            
            keyword_data = self.gigachat_service.analyze_user_interests(interests)
            user_intent = keyword_data.get('intent', 'general') if isinstance(keyword_data, dict) else 'general'
            
            filtered_objects = []
            
            dataset_objects = self.dataset_service.filter_by_interests(interests, limit=20)
            if dataset_objects:
                filtered_objects = dataset_objects
                for obj in filtered_objects:
                    obj['source'] = 'dataset'
                logger.debug(f"Найдено {len(filtered_objects)} объектов в датасете")
            
            # Ищем в 2ГИС если нужно
            should_search_2gis = (
                user_intent in ['venue', 'shopping', 'sports', 'entertainment'] or
                len(filtered_objects) < 3
            )
            
            if should_search_2gis:
                logger.debug(f"Поиск в 2ГИС API (намерение: {user_intent})")
                interests_for_api = interests.replace('☕', '').replace('☕ ', '').strip() if '☕' in interests else interests
                external_places = self._search_external_sources(interests_for_api, user_coords, user_intent)
                
                if external_places:
                    logger.debug(f"2ГИС API вернул {len(external_places)} мест до валидации для запроса '{interests_for_api}' (исходный: '{interests}')")
                    # Если уже были объекты из датасета, объединяем (удаляем дубликаты)
                    if filtered_objects:
                        dataset_titles = {obj.get('title', '').lower() for obj in filtered_objects}
                        added_count = 0
                        for obj in external_places:
                            if obj.get('title', '').lower() not in dataset_titles:
                                filtered_objects.append(obj)
                                added_count += 1
                        logger.debug(f"Добавлено {added_count} мест из 2ГИС (после удаления дубликатов)")
                    else:
                        filtered_objects = external_places
                        logger.debug(f"Найдено {len(filtered_objects)} мест в 2ГИС API")
                else:
                    if not filtered_objects:
                        logger.warning(f"⚠️ Не найдено мест ни в датасете, ни в 2ГИС для '{interests}'")
                    else:
                        logger.debug(f"2ГИС API не вернул мест, но есть {len(filtered_objects)} из датасета")
            
            # ШАГ 3: Если все равно ничего нет, позволяем GigaChat предложить общие рекомендации
            if not filtered_objects:
                logger.warning(f"Не найдено мест ни в датасете, ни в 2ГИС для запроса: {interests}")
                logger.debug("GigaChat предложит известные места")
                # Продолжаем с пустым списком - GigaChat может предложить общие рекомендации
            
            # КРИТИЧЕСКИ ВАЖНО: Валидация объектов по намерению пользователя ДО отправки в GigaChat
            # Фильтруем объекты, которые НЕ соответствуют запросу пользователя
            if filtered_objects:
                initial_count = len(filtered_objects)
                logger.debug(f"Начало валидации: {initial_count} объектов")
                
                # Дедупликация и валидация
                filtered_objects = self._remove_duplicates(filtered_objects)
                after_dedup_count = len(filtered_objects)
                logger.debug(f"После дедупликации: {after_dedup_count} объектов (удалено {initial_count - after_dedup_count} дубликатов)")
                
                # КРИТИЧЕСКИ ВАЖНО: Если объектов мало (≤3), не используем валидацию - все равно все включаем
                if after_dedup_count <= 3:
                    logger.debug(f"Объектов мало ({after_dedup_count} ≤ 3), пропускаем валидацию для гарантии минимума")
                else:
                    filtered_objects = self._validate_objects_by_intent(filtered_objects, interests, user_intent)
                    after_validation_count = len(filtered_objects)
                    logger.debug(f"После валидации по намерению: {after_validation_count} объектов (исключено {after_dedup_count - after_validation_count} нерелевантных)")
                
                
                # КРОСС-ПРОВЕРКА: Отключаем для максимальной скорости (занимает много времени)
                # Если объектов слишком много - просто берем топ по рейтингу и расстоянию
                # if len(filtered_objects) > 30:
                #     filtered_objects = self._cross_validate_with_gigachat(...)
                
                # КРИТИЧЕСКИ ВАЖНО: Фильтруем объекты по расстоянию 5км ПЕРЕД отправкой в GigaChat
                # Расширенный радиус 5км, чтобы найти больше вариантов, потом выберем ближайшие с лучшим рейтингом
                filtered_objects = self._filter_by_distance(filtered_objects, user_coords, max_distance=5000)
                
                # КРИТИЧЕСКИ ВАЖНО: Если нет мест в радиусе 5км - возвращаем ошибку!
                if not filtered_objects:
                    logger.warning(f"⚠️ Не найдено мест в радиусе 5км от пользователя для '{interests}'")
                    return {
                        'success': False,
                        'error': f'К сожалению, в радиусе 5 км от вашего местоположения не найдено мест по запросу "{interests}". Попробуйте указать другие интересы или изменить местоположение.'
                    }
                
                # Логируем топ-3 ближайших места для проверки
                for i, obj in enumerate(filtered_objects[:3]):
                    distance = obj.get('distance_from_user', 0)
                    title = obj.get('title', 'Без названия')
                    logger.debug(f"Ближайшее место #{i+1}: '{title}' на расстоянии {distance/1000:.2f}км")
                
                # Сортируем по расстоянию от пользователя ДО отправки в GigaChat
                # Это поможет GigaChat выбрать ближайшие места
                filtered_objects = self._sort_by_distance_from_user(filtered_objects, user_coords)
                
                # КРИТИЧЕСКИ ВАЖНО: Ограничиваем количество объектов для GigaChat только ближайшими!
                # Отправляем только первые 12 ближайших объектов, чтобы GigaChat выбирал именно ближайшие
                # Если отправить все, GigaChat может выбрать дальние места
                max_objects_for_gigachat = 12  # Только ближайшие 12 мест
                filtered_objects_for_gigachat = filtered_objects[:max_objects_for_gigachat]
                logger.debug(f"Отправляем в GigaChat только {len(filtered_objects_for_gigachat)} ближайших мест из {len(filtered_objects)}")
                
                # Объекты отсортированы по расстоянию (ближайшие первыми)
            else:
                filtered_objects_for_gigachat = []
            
            # Генерация маршрута через GigaChat
            route_text = self.gigachat_service.generate_route(
                interests=interests,
                time_minutes=time_minutes,
                start_location=location_str,
                filtered_objects=filtered_objects_for_gigachat if 'filtered_objects_for_gigachat' in locals() else filtered_objects
            )
            
            # Валидация и извлечение объектов из маршрута GigaChat
            # Если filtered_objects пуст, GigaChat мог предложить места сам - принимаем их
            selected_objects = []
            
            if filtered_objects:
                # КРИТИЧЕСКИ ВАЖНО: Используем тот же отсортированный список для извлечения
                # filtered_objects уже отсортированы по расстоянию (ближайшие первыми)
                sorted_filtered_objects = filtered_objects if 'filtered_objects_for_gigachat' not in locals() else filtered_objects
                
                # КРИТИЧЕСКИ ВАЖНО: Сначала извлекаем объяснения из ответа GigaChat для ВСЕХ объектов
                # Создаем словарь объяснений: {normalized_title: explanation_text}
                gigachat_explanations = self._extract_explanations_from_route_text(route_text)
                
                # Пытаемся извлечь объекты из ответа GigaChat
                selected_objects = self._extract_and_validate_objects(route_text, sorted_filtered_objects)
                
                # Валидация и дедупликация
                selected_objects = self._validate_objects_by_intent(selected_objects, interests, user_intent)
                selected_objects = self._remove_duplicates(selected_objects)
                
                # Анализ результатов валидации
                validation_rate = len(selected_objects) / len(filtered_objects) if filtered_objects else 0
                
                # КРИТИЧЕСКИ ВАЖНО: Дополнительная фильтрация по расстоянию после извлечения
                # Расширенный радиус 5км для поиска больше вариантов
                selected_objects = self._filter_by_distance(selected_objects, user_coords, max_distance=5000)
                
                # Если валидация не прошла или найдено мало объектов, используем топ из отфильтрованных
                if not selected_objects or validation_rate < 0.5:
                    if sorted_filtered_objects:
                        # КРИТИЧЕСКИ ВАЖНО: filtered_objects уже отсортированы по расстоянию (ближайшие первыми)
                        # Просто берем первые N ближайших мест - они уже отсортированы!
                        
                        # Минимум 3 места, максимум 5 мест, но учитываем доступное время
                        estimated_time_per_place = 40  # минут на место с переходами
                        max_places_by_time = int(time_minutes / estimated_time_per_place)
                        
                        # Обеспечиваем минимум 3 места, максимум 5 мест
                        # Берем первые ближайшие места (уже отсортированы по расстоянию)
                        num_places = min(5, len(sorted_filtered_objects), max(3, max_places_by_time))
                        selected_objects = sorted_filtered_objects[:num_places]
                
                # КРИТИЧЕСКИ ВАЖНО: Присваиваем объяснения из GigaChat ко ВСЕМ объектам
                # Применяем объяснения независимо от того, как были выбраны объекты
                self._assign_gigachat_explanations(selected_objects, gigachat_explanations)
            else:
                # Если filtered_objects пуст, GigaChat сам предложил места из своих знаний
                # Извлекаем названия мест из текста маршрута для дальнейшей обработки
                logger.debug("GigaChat предложил места из своих знаний")
                # Продолжаем с пустым selected_objects - будем работать с маршрутом напрямую
            
            # Если selected_objects пуст, но есть route_text от GigaChat - продолжаем
            # GigaChat мог предложить места из своих знаний
            
            # Если есть selected_objects, ограничиваем и строим оптимальный маршрут
            if selected_objects:
                # Ограничиваем до разумного количества (минимум 3, максимум 5 мест)
                if len(selected_objects) < 3:
                    logger.warning(f"Найдено только {len(selected_objects)} мест, требуется минимум 3. Маршрут может быть неполным.")
                elif len(selected_objects) > 5:
                    selected_objects = selected_objects[:5]
                    logger.debug("Ограничено до 5 мест")
                
                # КРИТИЧЕСКИ ВАЖНО: Фильтруем по расстоянию ПЕРЕД построением маршрута
                # Расширенный радиус 5км, но потом выберем ближайшие с лучшим рейтингом
                selected_objects = self._filter_by_distance(selected_objects, user_coords, max_distance=5000)
                
                # КРИТИЧЕСКИ ВАЖНО: Если после фильтрации нет мест - возвращаем ошибку!
                if not selected_objects:
                    logger.warning(f"⚠️ После фильтрации не осталось мест в радиусе 5км для '{interests}'")
                    return {
                        'success': False,
                        'error': f'К сожалению, в радиусе 5 км от вашего местоположения не найдено мест по запросу "{interests}". Попробуйте указать другие интересы или изменить местоположение.'
                    }
                
                # Проверяем расстояния для логирования
                for i, obj in enumerate(selected_objects[:3]):
                    distance = obj.get('distance_from_user', 0)
                    title = obj.get('title', 'Без названия')
                    lon = obj.get('lon')
                    lat = obj.get('lat')
                    logger.debug(f"Место для маршрута #{i+1}: '{title}' на расстоянии {distance/1000:.2f}км, координаты ({lon}, {lat})")
                
                # КРИТИЧЕСКИ ВАЖНО: Построение оптимального маршрута от ближайшего места к пользователю
                # Функция гарантирует, что первое место - ближайшее к user_coords в радиусе 5км
                # Затем каждое следующее место - ближайшее к предыдущему
                selected_objects = self._build_optimal_route(user_coords, selected_objects)
                logger.debug(f"Маршрут построен: {len(selected_objects)} мест")
            # Формируем маршрут для карты и обработки времени
            if selected_objects and len(selected_objects) > 0:
                # Есть объекты с координатами - строим полный маршрут
                route_points = [user_coords]  # Начало от пользователя
                from math import radians, cos, sin, asin, sqrt
                
                def haversine_distance(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
                    """Вычисляет расстояние между двумя точками в метрах"""
                    lon1, lat1 = coord1
                    lon2, lat2 = coord2
                    R = 6371000
                    dlat = radians(lat2 - lat1)
                    dlon = radians(lon2 - lon1)
                    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
                    c = 2 * asin(sqrt(a))
                    return R * c
                
                for obj in selected_objects:
                    lon = obj.get('lon')
                    lat = obj.get('lat')
                    if lon is not None and lat is not None:
                        # КРИТИЧЕСКИ ВАЖНО: Проверяем расстояние от пользователя!
                        distance_from_user = haversine_distance(user_coords, (lon, lat))
                        
                        # КРИТИЧЕСКИ ВАЖНО: Проверяем, что координаты в пределах Нижнего Новгорода
                        if not _is_in_nizhny_novgorod(lon, lat):
                            logger.warning(f"Пропускаем место '{obj.get('title')}' - координаты ({lat}, {lon}) вне Нижнего Новгорода")
                            continue
                        
                        # КРИТИЧЕСКИ ВАЖНО: Проверяем, что место в радиусе 5км (расширенный радиус)
                        if distance_from_user > 5000:
                            logger.warning(f"⚠️ ПРОБЛЕМА: Место '{obj.get('title')}' на расстоянии {distance_from_user/1000:.2f}км от пользователя (>5км)! ИСКЛЮЧАЕМ из маршрута!")
                            continue
                        
                        # Все проверки пройдены - добавляем в маршрут
                        route_points.append((lon, lat))
                        logger.debug(f"✓ Добавлено место '{obj.get('title')}' на расстоянии {distance_from_user/1000:.2f}км от пользователя")
                
                # КРИТИЧЕСКИ ВАЖНО: Проверяем, что есть хотя бы одно место после пользователя
                if len(route_points) < 2:
                    logger.error(f"⚠️ КРИТИЧЕСКАЯ ОШИБКА: Не осталось мест в маршруте после фильтрации! Было {len(selected_objects)} объектов.")
                    return {
                        'success': False,
                        'error': f'К сожалению, не удалось построить маршрут. Все найденные места находятся слишком далеко от вашего местоположения (>5 км). Попробуйте указать другие интересы или изменить местоположение.'
                    }
                
                # Очищаем текст маршрута от выдуманных мест и лишнего текста ПЕРЕД расчетом времени
                route_text = self._clean_route_text(route_text, selected_objects)
                
                # Перегенерируем текст маршрута с правильной нумерацией объектов (Место 1, Место 2, Место 3...)
                route_text = self._regenerate_route_with_order(selected_objects, interests, time_minutes, location_str)
                
                # Вычисляем точное время между точками с учетом транспорта и времени посещения
                route_with_times = self._calculate_complete_route_times(route_points, selected_objects, time_minutes)
                
                # Форматируем маршрут с реальным временем
                route_text_with_times = self._add_real_times_to_route(route_text, route_with_times)
                
                # Строим маршрут через 2ГИС с объектами для получения firm_id
                map_link = self.maps_service.get_route_map_link(route_points, selected_objects)
            else:
                # Нет объектов с координатами - GigaChat предложил места из знаний
                # Используем маршрут как есть, без точного расчета времени
                logger.debug("Используем маршрут от GigaChat")
                route_text_with_times = route_text
                route_points = [user_coords]  # Только начальная точка
                route_with_times = []
                
                # Пытаемся найти координаты для мест из маршрута через геокодирование адресов
                # Парсим адреса из текста маршрута и геокодируем их
                route_points_from_text = self._extract_coordinates_from_route_text(route_text, user_coords)
                # КРИТИЧЕСКИ ВАЖНО: Фильтруем координаты - только Нижний Новгород!
                route_points_from_text = self._filter_coordinates_in_nizhny(route_points_from_text)
                if len(route_points_from_text) > 1:
                    route_points = route_points_from_text
                    # Для маршрута из текста не используем firm_id (объекты не найдены)
                    map_link = self.maps_service.get_route_map_link(route_points, None)
                else:
                    map_link = self.maps_service.get_map_link([user_coords])
            
            # Получаем текущее время (МСК)
            msk_timezone = pytz.timezone('Europe/Moscow')
            current_time = datetime.now(msk_timezone)
            
            # Проверяем, что есть хотя бы какой-то текст маршрута
            final_route_text = route_text_with_times if route_text_with_times else route_text
            
            # КРИТИЧЕСКИ ВАЖНО: Всегда добавляем заголовок, если его нет
            if final_route_text and not final_route_text.strip().startswith('МАРШРУТ ПО НИЖНЕМУ НОВГОРОДУ'):
                final_route_text = "МАРШРУТ ПО НИЖНЕМУ НОВГОРОДУ\n\n" + final_route_text.strip()
            
            if not final_route_text or len(final_route_text.strip()) < 50:
                logger.error(f"Сгенерированный маршрут слишком короткий или пустой: {final_route_text[:100] if final_route_text else 'пусто'}")
                return {
                    'success': False,
                    'error': f'Не удалось сгенерировать маршрут по интересу "{interests}". Попробуйте указать другие интересы.'
                }
            
            return {
                'success': True,
                'route_text': final_route_text,
                'map_link': map_link if map_link else "",
                'route_points': route_points,
                'route_with_times': route_with_times if route_with_times else [],
                'current_time': current_time.strftime('%H:%M'),
                'time_minutes': time_minutes,
                'interests': interests,
                'location': location
            }
        
        except Exception as e:
            import traceback
            return {
                'success': False,
                'error': f'Произошла ошибка при генерации маршрута: {str(e)}\n{traceback.format_exc()}'
            }
    
    def _add_real_times_to_route(self, route_text: str, route_with_times: List[Dict]) -> str:
        """
        Добавляет реальное время перемещения в текст маршрута
        Заменяет примерное время на точное время между точками
        """
        if not route_with_times:
            return route_text
        
        # Получаем текущее время (МСК)
        msk_timezone = pytz.timezone('Europe/Moscow')
        current_time = datetime.now(msk_timezone)
        current_dt = current_time
        
        # Парсим маршрут
        lines = route_text.split('\n')
        result_lines = []
        time_index = 0  # Индекс текущего сегмента маршрута
        in_timeline_section = False
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Пропускаем пустые строки в начале
            if not line and len(result_lines) == 0:
                i += 1
                continue
            
            # Обработка заголовка таймлайна
            if 'ОБЩИЙ ТАЙМЛАЙН' in line or 'ТАЙМЛАЙН' in line:
                result_lines.append(line)
                result_lines.append(f"{current_time.strftime('%H:%M')} (МСК) - Старт от начальной точки")
                current_dt = current_time
                in_timeline_section = True
                i += 1
                continue
            
            # Пропускаем старые шаблоны времени
            if any(pattern in line for pattern in ['12:00', '12:45', '13:25', '13:40', '14:20', '14:40', '15:20', '15:30']):
                i += 1
                continue
            
            # Пропускаем строки "Начало маршрута от..." (уже обработали)
            if 'Начало маршрута от' in line and in_timeline_section:
                i += 1
                continue
            
            # Обработка перехода к месту
            if ('Переход к' in line or ('переход' in line.lower() and 'место' in line.lower())) and time_index < len(route_with_times):
                time_info = route_with_times[time_index]
                duration = time_info['duration_minutes']
                distance = time_info['distance_meters']
                transport = time_info.get('transport_type', 'пешком')
                visit_time = time_info.get('visit_time_minutes', 20)
                
                # Время начала перехода
                time_str = current_dt.strftime('%H:%M')
                current_dt += timedelta(minutes=duration)
                time_str_end = current_dt.strftime('%H:%M')
                
                # Форматируем информацию о транспорте
                transport_info = f" {transport}" if transport != "пешком" else ""
                
                # Ищем номер места из строки
                place_num = ""
                if 'Место' in line:
                    import re
                    place_match = re.search(r'Место\s*(\d+)', line, re.IGNORECASE)
                    if place_match:
                        place_num = f"Места {place_match.group(1)}"
                
                # Извлекаем номер места для правильного отображения
                if not place_num:
                    place_num = f"Месту {time_index + 1}" if time_index < len(route_with_times) else ""
                
                # ВСЕГДА пешком - явно указываем для всех переходов
                result_lines.append(f"{time_str} - Переход пешком к {place_num} ({duration} мин, {int(distance)} м) → прибытие в {time_str_end}")
                
                # Сразу добавляем время посещения места
                place_time_str = time_str_end
                place_num_visit = f"Места {time_index + 1}" if time_index < len(route_with_times) else ""
                result_lines.append(f"{place_time_str} - Посещение {place_num_visit} (время на месте: {visit_time} мин)")
                
                # Обновляем время после посещения
                current_dt += timedelta(minutes=visit_time)
                
                time_index += 1
                i += 1
                continue
            
            # Обработка места в основной части маршрута (не в таймлайне)
            if 'Место' in line and ':' in line and not in_timeline_section:
                result_lines.append(lines[i])  # Сохраняем оригинальную строку с форматированием
                i += 1
                continue
            
            # Пропускаем старые строки таймлайна, которые уже обработали
            if in_timeline_section:
                if ('Место' in line and ('X минут' in line or line.count(':') > 1)) or 'Завершение' in line:
                    i += 1
                    continue
            
            # Сохраняем остальные строки
            if line or len(result_lines) > 0:
                # Не добавляем пустые строки в начале, но добавляем форматирование
                result_lines.append(lines[i])
            i += 1
        
        # Добавляем финальное время
        if route_with_times:
            result_lines.append(f"\n{current_dt.strftime('%H:%M')} (МСК) - Завершение маршрута")
        
        return '\n'.join(result_lines)
    
    def _extract_explanations_from_route_text(self, route_text: str) -> Dict[str, str]:
        """
        Извлекает все объяснения "Почему идем сюда" из текста маршрута GigaChat
        Возвращает словарь {normalized_title: explanation_text}
        """
        explanations = {}
        route_lines = route_text.split('\n')
        
        current_place_name = None
        current_explanation = []
        collecting_explanation = False
        
        for line in route_lines:
            line_clean = line.strip()
            
            # Убираем markdown форматирование (**, *, эмодзи)
            line_clean = line_clean.replace('**', '').replace('*', '').replace('❣', '').replace('📍', '').replace('✉', '').replace('🏠', '').replace('☕️', '')
            line_clean = line_clean.strip()
            
            # Ищем "Место X: Название" или вариации (Место №1, Место 1, и т.д.)
            if (line_clean.startswith('Место') or line_clean.startswith('Место №') or 'Место' in line_clean[:10]) and ':' in line_clean:
                # Сохраняем предыдущее объяснение
                if current_place_name and current_explanation:
                    explanations[current_place_name] = '\n'.join(current_explanation).strip()
                
                # Начинаем новое место
                parts = line_clean.split(':', 1)
                if len(parts) > 1:
                    place_name = parts[-1].strip().replace('*', '').replace('_', '').strip()
                    current_place_name = self._normalize_text(place_name)
                    current_explanation = []
                    collecting_explanation = False
            
            # Ищем "Почему идем сюда:" (также ищем вариации с markdown)
            elif 'Почему идем сюда' in line_clean or 'Почему идеем сюда' in line_clean or 'почему идем сюда' in line_clean.lower():
                collecting_explanation = True
                # Ищем текст после "Почему идем сюда:"
                if ':' in line_clean:
                    parts = line_clean.split(':', 1)
                    if len(parts) > 1:
                        explanation_text = parts[-1].strip()
                        # Убираем markdown
                        explanation_text = explanation_text.replace('**', '').replace('*', '').replace('_', '')
                        if explanation_text:
                            current_explanation.append(explanation_text)
                else:
                    # Если нет двоеточия, весь текст после "Почему идем сюда" - это начало объяснения
                    if 'Почему идем сюда' in line_clean:
                        explanation_text = line_clean.split('Почему идем сюда', 1)[-1].strip()
                    elif 'Почему идеем сюда' in line_clean:
                        explanation_text = line_clean.split('Почему идеем сюда', 1)[-1].strip()
                    else:
                        explanation_text = line_clean
                    explanation_text = explanation_text.replace('**', '').replace('*', '').replace('_', '').strip()
                    if explanation_text:
                        current_explanation.append(explanation_text)
            
            # Собираем объяснение
            elif collecting_explanation:
                if (line_clean.startswith('Время на посещение:') or line_clean.startswith('Место') or
                    line_clean.startswith('ОБЩИЙ ТАЙМЛАЙН:')):
                    # КРИТИЧЕСКИ ВАЖНО: Сохраняем объяснение перед остановкой сбора!
                    if current_place_name and current_explanation:
                        explanations[current_place_name] = '\n'.join(current_explanation).strip()
                    collecting_explanation = False
                    current_explanation = []
                else:
                    if line_clean:
                        current_explanation.append(line_clean)
        
        # Сохраняем последнее объяснение
        if current_place_name and current_explanation:
            explanations[current_place_name] = '\n'.join(current_explanation).strip()
        
        return explanations
    
    def _assign_gigachat_explanations(self, selected_objects: List[Dict], gigachat_explanations: Dict[str, str]):
        """
        Присваивает объяснения от GigaChat к объектам, используя улучшенное сопоставление названий
        """
        if not gigachat_explanations or not selected_objects:
            return
        
        for obj in selected_objects:
            # Если объяснение уже есть, пропускаем
            if 'gigachat_explanation' in obj and obj['gigachat_explanation']:
                continue
            
            title = obj.get('title', '')
            title_normalized = self._normalize_text(title)
            
            # Пытаемся найти объяснение по точному совпадению
            best_match = None
            best_score = 0
            best_match_title = None
            
            for normalized_title, explanation in gigachat_explanations.items():
                # Точное совпадение
                if title_normalized == normalized_title:
                    obj['gigachat_explanation'] = explanation
                    best_match = None  # Уже присвоили
                    break
                
                # Проверяем, содержит ли одно название другое
                if normalized_title in title_normalized or title_normalized in normalized_title:
                    # Вычисляем схожесть (длина совпадающей части / общая длина)
                    common_length = min(len(normalized_title), len(title_normalized))
                    if common_length > 0:
                        score = common_length / max(len(normalized_title), len(title_normalized))
                        if score > best_score and score > 0.5:  # Минимум 50% совпадение
                            best_score = score
                            best_match = explanation
                            best_match_title = normalized_title
                
                # Проверяем совпадение ключевых слов (первые слова)
                title_words = set(title_normalized.split()[:3])  # Первые 3 слова
                explanation_title_words = set(normalized_title.split()[:3])
                if title_words and explanation_title_words:
                    common_words = title_words.intersection(explanation_title_words)
                    if len(common_words) >= 2:  # Минимум 2 общих слова
                        score = len(common_words) / max(len(title_words), len(explanation_title_words))
                        if score > best_score:
                            best_score = score
                            best_match = explanation
                            best_match_title = normalized_title
            
            # Присваиваем лучшее совпадение
            if best_match:
                obj['gigachat_explanation'] = best_match
    
    def _extract_and_validate_objects(self, route_text: str, filtered_objects: List[Dict]) -> List[Dict]:
        """
        Извлекает и валидирует объекты из ответа GigaChat
        Использует улучшенный алгоритм сопоставления названий
        КРИТИЧЕСКИ ВАЖНО: Также извлекает уникальный текст "Почему идем сюда" от GigaChat для каждого места
        """
        if not filtered_objects:
            return []
        
        selected_objects = []
        route_lines = route_text.split('\n')
        
        # Создаем индексы для быстрого поиска
        title_index = {}  # {normalized_title: obj}
        address_index = {}  # {normalized_address: obj}
        
        for obj in filtered_objects:
            title = self._normalize_text(obj.get('title', ''))
            address = self._normalize_text(obj.get('address', ''))
            
            if title:
                title_index[title] = obj
                # Добавляем варианты без префиксов
                title_words = [w for w in title.split() if len(w) > 2]
                for word in title_words:
                    if word not in title_index:
                        title_index[word] = obj
            
            if address:
                address_index[address] = obj
        
        current_place = None
        current_address = None
        current_obj_index = -1  # Индекс текущего объекта в selected_objects
        current_explanation = []  # Собираем текст "Почему идем сюда"
        collecting_explanation = False  # Флаг, что собираем объяснение
        
        for i, line in enumerate(route_lines):
            line_clean = line.strip()
            
            # Ищем строку "Место X: Название"
            if line_clean.startswith('Место') and ':' in line_clean:
                # Сохраняем предыдущее объяснение перед переходом к новому месту
                if current_obj_index >= 0 and current_explanation:
                    last_obj = selected_objects[current_obj_index]
                    explanation_text = '\n'.join(current_explanation).strip()
                    # Сохраняем уникальное объяснение от GigaChat в объекте
                    last_obj['gigachat_explanation'] = explanation_text
                
                # Начинаем новое место
                parts = line_clean.split(':', 1)
                if len(parts) > 1:
                    place_name = parts[-1].strip()
                    place_name = place_name.replace('*', '').replace('_', '').strip()
                    current_place = self._normalize_text(place_name)
                    current_explanation = []
                    collecting_explanation = False
                    current_obj_index = -1
            
            # Ищем строку "Адрес: ..."
            elif line_clean.startswith('Адрес:') or line_clean.startswith('адрес:'):
                # Сохраняем предыдущее объяснение, если собирали
                if collecting_explanation and current_obj_index >= 0:
                    last_obj = selected_objects[current_obj_index]
                    explanation_text = '\n'.join(current_explanation).strip()
                    last_obj['gigachat_explanation'] = explanation_text
                    current_explanation = []
                    collecting_explanation = False
                
                parts = line_clean.split(':', 1)
                if len(parts) > 1:
                    current_address = self._normalize_text(parts[-1].strip())
                    
                    # Ищем объект по названию и/или адресу
                    found_obj = None
                    
                    # Точное совпадение
                    if current_place and current_place in title_index:
                        found_obj = title_index[current_place]
                    elif current_address and current_address in address_index:
                        found_obj = address_index[current_address]
                    
                    # Нечеткое совпадение
                    if not found_obj:
                        best_match = self._fuzzy_match(current_place or current_address, filtered_objects)
                        if best_match:
                            found_obj = best_match
                    
                    if found_obj and found_obj not in selected_objects:
                        # Создаем копию объекта, чтобы не изменять оригинал
                        found_obj_copy = found_obj.copy()
                        selected_objects.append(found_obj_copy)
                        current_obj_index = len(selected_objects) - 1  # Сохраняем индекс для сохранения объяснения
                        current_place = None
                        current_address = None
            
            # Ищем строку "Почему идем сюда:" или "Почему идеем сюда:"
            elif line_clean.startswith('Почему идем сюда:') or line_clean.startswith('Почему идеем сюда:'):
                # Начинаем собирать объяснение (объяснение идет ПОСЛЕ адреса)
                collecting_explanation = True
                parts = line_clean.split(':', 1)
                if len(parts) > 1:
                    explanation_text = parts[-1].strip()
                    if explanation_text:
                        current_explanation.append(explanation_text)
            
            # Продолжаем собирать объяснение до следующего поля (Время на посещение, Место и т.д.)
            elif collecting_explanation:
                # Если встречаем новое поле (Время, Место, ОБЩИЙ ТАЙМЛАЙН), останавливаем сбор и сохраняем
                if (line_clean.startswith('Время на посещение:') or line_clean.startswith('Место') or
                    line_clean.startswith('ОБЩИЙ ТАЙМЛАЙН:')):
                    collecting_explanation = False
                    # Сохраняем объяснение в текущий объект
                    if current_obj_index >= 0 and current_explanation:
                        current_obj = selected_objects[current_obj_index]
                        explanation_text = '\n'.join(current_explanation).strip()
                        current_obj['gigachat_explanation'] = explanation_text
                        current_explanation = []
                else:
                    # Продолжаем собирать текст объяснения
                    if line_clean:
                        current_explanation.append(line_clean)
        
        # Сохраняем последнее объяснение
        if current_explanation and current_obj_index >= 0:
            last_obj = selected_objects[current_obj_index]
            explanation_text = '\n'.join(current_explanation).strip()
            last_obj['gigachat_explanation'] = explanation_text
        
        return selected_objects
    
    def _validate_objects_by_intent(self, objects: List[Dict], interests: str, user_intent: str) -> List[Dict]:
        """
        Валидирует объекты по намерению пользователя
        Фильтрует объекты, которые НЕ соответствуют запросу пользователя
        
        Args:
            objects: Список объектов для валидации
            interests: Интересы пользователя (например, "кофейни", "музеи")
            user_intent: Намерение пользователя ('venue', 'culture', 'art', и т.д.)
        
        Returns:
            Отфильтрованный список объектов, соответствующих намерению
        """
        if not objects:
            return []
        
        interests_lower = interests.lower()
        validated_objects = []
        
        # Ключевые слова для фильтрации по намерению
        venue_keywords = ['кафе', 'кофейн', 'ресторан', 'бар', 'заведен', 'столовая', 'бистро', 'трактир']
        venue_exclude = ['памятник', 'скульптур', 'мозаик', 'вывеск', 'монумент', 'обезьянк', 'произведен']
        
        culture_keywords = ['музей', 'театр', 'галерея', 'выставка', 'культурн', 'историческ']
        art_keywords = ['граффити', 'стрит-арт', 'мурал', 'арт', 'уличн']
        architecture_keywords = ['собор', 'храм', 'кремль', 'церковь', 'монастыр', 'архитектур']
        shopping_keywords = ['торгов', 'магазин', 'тц', 'бутик', 'шоппинг']
        sports_keywords = ['спорт', 'стадион', 'фитнес', 'тренажер', 'спортзал']
        entertainment_keywords = ['кино', 'клуб', 'развлеч', 'боулинг', 'бильярд']
        
        for obj in objects:
            title = obj.get('title', '').lower()
            description = obj.get('description', '').lower()
            address = obj.get('address', '').lower()
            category = obj.get('category', '').lower()
            
            # Объединяем все текстовые поля для проверки
            text_combined = f"{title} {description} {address} {category}"
            
            is_valid = False
            
            # Валидация для venue (заведения)
            if user_intent == 'venue':
                # Специальная проверка для конкретных запросов
                interests_lower = interests.lower()
                
                # Исключаем нерелевантные объекты для конкретных запросов
                if any(word in interests_lower for word in ['стейк', 'стейк-хаус', 'стейкхаус', 'мясо']):
                    # Для стейк-хаус исключаем кинотеатры, развлечения и т.д.
                    exclude_keywords = ['кинотеатр', 'кино', 'театр', 'клуб', 'развлечен', 'музей', 'выставка']
                    if any(ex in text_combined for ex in exclude_keywords):
                        is_valid = False
                    elif any(kw in text_combined for kw in ['стейк', 'мясо', 'кафе', 'ресторан', 'бар', 'хаус']):
                        is_valid = True
                    else:
                        is_valid = False
                elif any(word in interests_lower for word in ['ресторан', 'рестораны']):
                    # Для ресторанов ищем ТОЛЬКО рестораны, исключаем все остальное
                    # КРИТИЧЕСКИ ВАЖНО: НЕ исключаем "кафе" и "кофейн", так как многие рестораны имеют эти слова в названии!
                    exclude_keywords = ['кинотеатр', 'кино', 'развлечен', 'музей', 'выставка', 'театр']
                    if any(ex in text_combined for ex in exclude_keywords):
                        is_valid = False
                    elif any(kw in text_combined for kw in ['ресторан', 'заведен', 'кафе', 'траттори', 'пиццери', 'хинкал', 'барбек', 'стейк']):
                        is_valid = True
                    else:
                        is_valid = False
                elif any(word in interests_lower for word in ['суши', 'суши-бар', 'сушибар', 'sushi', 'роллы', 'японская кухня']):
                    # Для суши-баров проверяем наличие слов в названии/категории
                    sushi_keywords = ['суши', 'sushi', 'японск', 'ролл', 'сашими']
                    if any(kw in text_combined for kw in sushi_keywords):
                        is_valid = True
                    else:
                        is_valid = False
                elif any(word in interests_lower for word in ['музей искусств', 'музеи искусств', 'художественный музей', 'галерея искусств']):
                    # Для музеев искусств проверяем наличие слов в названии/категории
                    art_museum_keywords = ['музей искусств', 'художественн', 'галерея', 'искусств']
                    if any(kw in text_combined for kw in art_museum_keywords):
                        # Исключаем обычные музеи без упоминания искусств
                        exclude_keywords = ['музей', 'краеведческ', 'историческ', 'техническ']
                        if any(ex in text_combined for ex in exclude_keywords) and 'искусств' not in text_combined:
                            is_valid = False
                        else:
                            is_valid = True
                    else:
                        is_valid = False
                elif any(word in interests_lower for word in ['кафе', 'кофейня', 'кофейни', 'кофе']) or '☕' in interests:
                    # Для кофеен ищем ТОЛЬКО кофейни и кофейные заведения
                    # КРИТИЧЕСКИ ВАЖНО: Исключаем рестораны, бары, бистро с кухней, рестораны национальной кухни
                    # НО делаем валидацию более мягкой - если в названии/категории есть "кафе" или "кофейня", принимаем
                    exclude_keywords = ['кинотеатр', 'кино', 'клуб', 'развлечен', 'музей', 'выставка', 'театр', 
                                        'израильской', 'японской', 'итальянской', 'европейской', 'грузинской', 
                                        'русской', 'азиатской']
                    
                    # МЯГКАЯ ВАЛИДАЦИЯ: Если в названии или категории есть "кафе" или "кофейня", принимаем
                    # Исключаем только явные рестораны, если они явно указаны в названии
                    has_explicit_restaurant = any(ex in text_combined for ex in ['ресторан', 'бар', 'бистро', 'столов', 'трактир'])
                    has_cafe_or_coffee = any(kw in text_combined for kw in ['кафе', 'кофейн', 'кофе'])
                    
                    if has_explicit_restaurant and not has_cafe_or_coffee:
                        # Явный ресторан без упоминания кафе - исключаем
                        is_valid = False
                    elif has_cafe_or_coffee:
                        # Есть упоминание кафе/кофейни - принимаем (даже если есть другие слова)
                        is_valid = True
                    elif any(ex in text_combined for ex in exclude_keywords):
                        # Есть исключающие слова и нет кафе/кофейни - исключаем
                        is_valid = False
                    
                    # Проверяем категорию из 2ГИС
                    category_lower = obj.get('category', '').lower()
                    if category_lower:
                        # МЯГКАЯ ВАЛИДАЦИЯ: Если категория содержит "кафе" или "кофейня", принимаем
                        has_cafe_in_category = any(kw in category_lower for kw in ['кафе', 'кофейн', 'кофе'])
                        has_explicit_restaurant_category = any(ex_cat in category_lower for ex_cat in ['ресторан', 'бар', 'бистро', 'столовая', 'трактир'])
                        
                        if has_cafe_in_category:
                            # Есть упоминание кафе в категории - валидно (переопределяем результат валидации)
                            is_valid = True
                        elif has_explicit_restaurant_category and not has_cafe_in_category:
                            # Явная категория ресторана без кафе - исключаем (переопределяем)
                            is_valid = False
                    # Если категория не помогла, оставляем результат предыдущей проверки (is_valid уже установлен выше)
                else:
                    # Общая валидация для других venue запросов
                    has_venue_keyword = any(kw in text_combined for kw in venue_keywords)
                    has_exclude = any(ex in text_combined for ex in venue_exclude)
                    
                    if has_venue_keyword and not has_exclude:
                        is_valid = True
                    # Если это из 2ГИС с категорией или рейтингом - тоже валидно
                    elif obj.get('source') == '2gis' and (obj.get('rating', 0) > 0 or 'кафе' in text_combined or 'ресторан' in text_combined):
                        is_valid = True
                    else:
                        is_valid = False
            
            # Валидация для других намерений
            elif user_intent == 'culture':
                # Для культуры ищем ТОЛЬКО музеи, театры, выставки - исключаем заведения
                if any(word in interests_lower for word in ['музей', 'музеи']):
                    # Для музеев ищем ТОЛЬКО музеи
                    exclude_keywords = ['кафе', 'ресторан', 'бар', 'кинотеатр', 'клуб', 'развлечен']
                    has_culture = any(kw in text_combined for kw in ['музей', 'галерея', 'выставка'])
                    has_exclude = any(ex in text_combined for ex in exclude_keywords)
                    is_valid = has_culture and not has_exclude
                else:
                    # Для других культурных запросов
                    is_valid = any(kw in text_combined for kw in culture_keywords)
            elif user_intent == 'art':
                is_valid = any(kw in text_combined for kw in art_keywords)
            elif user_intent == 'architecture':
                is_valid = any(kw in text_combined for kw in architecture_keywords)
            elif user_intent == 'shopping':
                is_valid = any(kw in text_combined for kw in shopping_keywords)
            elif user_intent == 'sports':
                is_valid = any(kw in text_combined for kw in sports_keywords)
            elif user_intent == 'entertainment':
                is_valid = any(kw in text_combined for kw in entertainment_keywords)
            elif user_intent == 'nature':
                # Для nature проверяем конкретные запросы
                if any(word in interests_lower for word in ['набережная', 'набережные', 'набережн']):
                    # Для набережных - ТОЛЬКО набережные! Строгая проверка
                    # Проверяем наличие слова "набережная" в названии (приоритет) или адресе
                    has_embankment_in_title = any(kw in title for kw in ['набережная', 'набережн', 'набережна'])
                    has_embankment_in_address = any(kw in address for kw in ['набережная', 'набережн', 'набережна'])
                    
                    # Если в названии есть "набережная" - это точно набережная, принимаем
                    if has_embankment_in_title:
                        is_valid = True
                    # Если только в адресе - принимаем, но проверяем, что это не другое здание
                    elif has_embankment_in_address:
                        # Исключаем объекты, которые точно НЕ являются набережными
                        exclude_keywords = ['мечеть', 'трамплин', 'собор', 'храм', 'церковь', 'мост', 'памятник', 
                                           'подъёмник', 'кресельный']
                        # Если в названии есть исключающие слова - не принимаем
                        if any(ex in title for ex in exclude_keywords):
                            is_valid = False
                        else:
                            is_valid = True
                    else:
                        # Нет упоминания набережной ни в названии, ни в адресе - не принимаем
                        is_valid = False
                else:
                    # Для других nature запросов (парки, скверы)
                    nature_keywords = ['парк', 'сквер', 'сад', 'набережная', 'набережн', 'прогулк']
                    is_valid = any(kw in text_combined for kw in nature_keywords)
            else:
                # Для general, view - принимаем все объекты
                is_valid = True
            
            if is_valid:
                validated_objects.append(obj)
        
        return validated_objects
    
    def _filter_by_distance(self, objects: List[Dict], user_coords: Tuple[float, float], max_distance: int = 5000) -> List[Dict]:
        """
        Фильтрует объекты по расстоянию от пользователя.
        Оставляет только объекты в пределах max_distance метров.
        """
        if not objects or not user_coords:
            return objects
        
        from math import radians, cos, sin, asin, sqrt
        
        def haversine_distance(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
            """Вычисляет расстояние между двумя точками в метрах"""
            lon1, lat1 = coord1
            lon2, lat2 = coord2
            R = 6371000
            dlat = radians(lat2 - lat1)
            dlon = radians(lon2 - lon1)
            a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return R * c
        
        filtered = []
        excluded_count = 0
        for obj in objects:
            # Используем сохраненное расстояние, если есть
            distance = obj.get('distance_from_user')
            
            if distance is None:
                # Вычисляем расстояние если не было сохранено
                obj_lon = obj.get('lon')
                obj_lat = obj.get('lat')
                if obj_lon is not None and obj_lat is not None:
                    distance = haversine_distance(user_coords, (obj_lon, obj_lat))
                else:
                    # Нет координат - пропускаем
                    excluded_count += 1
                    continue
            
            # КРИТИЧЕСКИ ВАЖНО: Оставляем только объекты в пределах max_distance
            if distance <= max_distance:
                # Обновляем distance_from_user для дальнейшего использования
                obj['distance_from_user'] = distance
                filtered.append(obj)
            else:
                excluded_count += 1
                logger.debug(f"Исключаем место '{obj.get('title')}' - расстояние {distance/1000:.1f}км превышает лимит {max_distance/1000:.1f}км")
        
        if excluded_count > 0:
            logger.debug(f"Отфильтровано: {len(filtered)} мест в радиусе {max_distance/1000:.1f}км, исключено {excluded_count} дальних мест")
        
        return filtered
    
    def _sort_by_distance_from_user(self, objects: List[Dict], user_coords: Tuple[float, float]) -> List[Dict]:
        """
        Сортирует объекты по расстоянию от пользователя и рейтингу.
        Приоритет: ближайшие объекты с хорошим рейтингом в начале списка.
        
        Args:
            objects: Список объектов для сортировки
            user_coords: Координаты пользователя (lon, lat)
        
        Returns:
            Отсортированный список объектов (ближайшие с хорошим рейтингом первыми)
        """
        if not objects or not user_coords:
            return objects
        
        def haversine_distance(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
            """Вычисляет расстояние между двумя точками в метрах по формуле гаверсинуса"""
            lon1, lat1 = coord1
            lon2, lat2 = coord2
            
            R = 6371000  # Радиус Земли в метрах
            dlat = radians(lat2 - lat1)
            dlon = radians(lon2 - lon1)
            a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return R * c
        
        # КРИТИЧЕСКИ ВАЖНО: Правильная логика - сначала ближайшие, потом лучшие среди них!
        # ШАГ 1: Вычисляем расстояние для всех объектов
        objects_with_distance = []
        for obj in objects:
            obj_lon = obj.get('lon')
            obj_lat = obj.get('lat')
            
            if obj_lon is not None and obj_lat is not None:
                # Используем сохраненное расстояние, если есть, иначе вычисляем
                distance = obj.get('distance_from_user')
                if distance is None:
                    distance = haversine_distance(user_coords, (obj_lon, obj_lat))
                obj['distance_from_user'] = distance
                objects_with_distance.append(obj)
            else:
                # Объекты без координат - в конец списка
                obj['distance_from_user'] = float('inf')
        
        # ШАГ 2: Сортируем: сначала по расстоянию (ближайшие), потом по рейтингу (лучшие среди ближайших)
        def sort_key(obj):
            distance = obj.get('distance_from_user', float('inf'))
            rating = obj.get('rating', 0)
            reviews_count = obj.get('reviews_count', 0)
            # Сортировка: сначала по расстоянию (возрастание), потом по рейтингу (убывание), потом по отзывам (убывание)
            # Это гарантирует: ближайшее место первым, среди одинакового расстояния - лучший рейтинг
            return (distance, -rating, -reviews_count)
        
        sorted_objects = sorted(objects_with_distance, key=sort_key)
        
        # Добавляем объекты без координат в конец
        objects_without_coords = [obj for obj in objects if obj.get('distance_from_user') == float('inf')]
        sorted_objects.extend(objects_without_coords)
        
        return sorted_objects
    
    def _remove_duplicates(self, objects: List[Dict]) -> List[Dict]:
        """
        Удаляет повторяющиеся места из списка
        Проверяет по названию, адресу и координатам
        """
        if not objects:
            return []
        
        seen = set()
        unique_objects = []
        
        for obj in objects:
            # Нормализуем данные для сравнения
            title = self._normalize_text(obj.get('title', ''))
            address = self._normalize_text(obj.get('address', ''))
            lon = obj.get('lon')
            lat = obj.get('lat')
            
            # Создаем уникальные ключи для проверки дубликатов
            keys_to_check = []
            
            # Ключ по названию (основной)
            if title:
                keys_to_check.append(f"title:{title}")
            
            # Ключ по координатам (если есть)
            if lon is not None and lat is not None:
                # Округляем координаты до 4 знаков после запятой для сравнения
                # Это позволяет обнаружить дубликаты в одном здании
                rounded_lon = round(float(lon), 4)
                rounded_lat = round(float(lat), 4)
                keys_to_check.append(f"coords:{rounded_lon},{rounded_lat}")
            
            # Ключ по адресу (если есть координат нет)
            if address and (lon is None or lat is None):
                # Берем только основную часть адреса (без комментария)
                address_main = address.split(',')[0] if ',' in address else address
                keys_to_check.append(f"address:{self._normalize_text(address_main)}")
            
            # Проверяем, видели ли мы уже этот объект
            is_duplicate = False
            for key in keys_to_check:
                if key in seen:
                    is_duplicate = True
                    # Дубликат пропущен
                    break
            
            # Если не дубликат, добавляем
            if not is_duplicate:
                unique_objects.append(obj)
                # Добавляем все ключи в seen
                for key in keys_to_check:
                    seen.add(key)
        
        removed_count = len(objects) - len(unique_objects)
        if removed_count > 0:
            logger.debug(f"Удалено {removed_count} дубликатов")
        
        return unique_objects
    
    def _normalize_text(self, text: str) -> str:
        """Нормализует текст для сравнения"""
        if not text:
            return ""
        # Убираем лишние пробелы, приводим к нижнему регистру
        return ' '.join(text.lower().split())
    
    def _fuzzy_match(self, search_text: str, objects: List[Dict]) -> Optional[Dict]:
        """Нечеткое сопоставление названия с объектами"""
        if not search_text:
            return None
        
        search_words = [w for w in search_text.split() if len(w) > 2]
        if not search_words:
            return None
        
        best_score = 0
        best_obj = None
        
        for obj in objects:
            obj_title = self._normalize_text(obj.get('title', ''))
            obj_address = self._normalize_text(obj.get('address', ''))
            
            # Подсчитываем совпадения слов
            title_score = sum(1 for word in search_words if word in obj_title)
            address_score = sum(1 for word in search_words if word in obj_address)
            
            # Проверяем обратное вхождение
            if search_text in obj_title or obj_title in search_text:
                title_score += 5
            
            total_score = title_score * 2 + address_score
            
            if total_score > best_score and total_score > 0:
                best_score = total_score
                best_obj = obj
        
        return best_obj if best_score > 0 else None
    
    def _cross_validate_with_gigachat(self, objects: List[Dict], interests: str, 
                                       user_intent: str, limit: int = 15) -> List[Dict]:
        """
        Использует GigaChat для кросс-проверки релевантности объектов
        GigaChat анализирует объекты и отбирает наиболее подходящие для запроса пользователя
        
        Args:
            objects: Список объектов для проверки
            interests: Интересы пользователя
            user_intent: Намерение пользователя
            limit: Максимальное количество объектов для возврата
        
        Returns:
            Отфильтрованный список наиболее релевантных объектов
        """
        if not objects or len(objects) <= limit:
            return objects[:limit] if len(objects) > limit else objects
        
        try:
            # Формируем краткий список объектов для проверки
            objects_text = "\n---\n".join([
                f"Объект {i+1}: {obj.get('title', 'Без названия')}"
                for i, obj in enumerate(objects[:30])  # Ограничиваем до 30 для проверки
            ])
            
            validation_prompt = f"""Ты анализируешь список объектов для запроса пользователя.

Запрос пользователя: "{interests}"
Намерение: {user_intent}

Список объектов:
{objects_text}

ЗАДАЧА: Выбери ТОЛЬКО те объекты, которые РЕАЛЬНО соответствуют запросу "{interests}".
Правила:
1. Для запроса "стрит-арт" или "граффити" выбирай ТОЛЬКО объекты, которые явно связаны с уличным искусством, граффити, муралами
2. Для запроса "кофейни" или "кафе" выбирай ТОЛЬКО реальные заведения, не памятники или вывески
3. Исключай объекты, которые не соответствуют намерению пользователя
4. Верни ТОЛЬКО номера объектов через запятую (например: 1,3,5,7)

Ответ (только номера через запятую):"""
            
            response = self.gigachat_service.client.chat.completions.create(
                model=self.gigachat_service.model,
                max_tokens=200,
                temperature=0.3,  # Низкая температура для более точной валидации
                messages=[{"role": "user", "content": validation_prompt}]
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Парсим номера объектов
            import re
            numbers = re.findall(r'\d+', result_text)
            selected_indices = [int(n) - 1 for n in numbers if 1 <= int(n) <= len(objects)]
            
            # Возвращаем отобранные объекты
            validated_objects = [objects[i] for i in selected_indices if 0 <= i < len(objects)]
            
            # Если GigaChat не отобрал объекты или их мало, возвращаем топ по релевантности
            if len(validated_objects) < 3:
                logger.warning("GigaChat отобрал мало объектов, используем исходный список")
                return objects[:limit]
            
            return validated_objects[:limit]
            
        except Exception as e:
            logger.warning(f"Ошибка кросс-проверки с GigaChat: {e}")
            # В случае ошибки возвращаем исходный список
            return objects[:limit]
    
    def _search_external_sources(self, interests: str, location: Tuple[float, float], 
                                user_intent: str) -> List[Dict]:
        """
        Ищет места в открытых источниках (2ГИС API)
        
        Args:
            interests: Интересы пользователя
            location: Координаты пользователя (lon, lat)
            user_intent: Намерение пользователя
        
        Returns:
            Список найденных мест
        """
        external_places = []
        
        # Маппинг категорий для поиска в 2ГИС (для обратной совместимости в запросах)
        category_mapping = {
            'venue': {
                'queries': ['ресторан', 'рестораны', 'кафе', 'кофейня', 'бар', 'столовая', 'бистро', 'трактир', 'еда', 'кухня', 'заведение'],
                'category': None  # 2ГИС не использует category параметр, используем в тексте запроса
            },
            'shopping': {
                'queries': ['торговый центр', 'тц', 'молл', 'магазин', 'шоппинг'],
                'category': None
            },
            'sports': {
                'queries': ['спорт', 'спортивная площадка', 'стадион', 'фитнес', 'спортзал'],
                'category': None
            },
            'entertainment': {
                'queries': ['кинотеатр', 'клуб', 'развлечения', 'боулинг', 'бильярд', 'аттракцион'],
                'category': None
            },
            'culture': {
                'queries': ['музей', 'театр', 'выставка'],
                'category': 'museum'
            },
            'art': {
                'queries': ['граффити', 'стрит-арт', 'муралы', 'уличное искусство', 'street art'],
                'category': None  # Нет специальной категории в POI, но ищем через 2ГИС API
            },
            'view': {
                'queries': ['смотровая площадка', 'панорама'],
                'category': None
            },
            'nature': {
                'queries': ['парк', 'сквер', 'набережная'],
                'category': 'park'
            },
            'architecture': {
                'queries': ['собор', 'храм', 'кремль'],
                'category': 'church'
            }
        }
        
        intent_config = category_mapping.get(user_intent, {})
        queries = intent_config.get('queries', [interests])
        category = intent_config.get('category')
        
        # Формируем оптимальные запросы для поиска популярных мест
        if user_intent == 'venue':
            # Для заведений используем запросы, которые найдут лучшие места
            interests_lower = interests.lower()
            if any(word in interests_lower for word in ['ресторан', 'рестораны']):
                # КРИТИЧЕСКИ ВАЖНО: НЕ добавляем "Нижний Новгород" - он добавится автоматически в maps_2gis.py
                search_query = 'ресторан'
                # Добавляем варианты для поиска лучших мест
                additional_queries = ['рестораны', 'лучшие рестораны']
            elif any(word in interests_lower for word in ['кафе', 'кофейня', 'кофейни', 'кофе']) or '☕' in interests:
                # Для кофеен используем более специфичные запросы, исключая рестораны
                # КРИТИЧЕСКИ ВАЖНО: Убираем эмодзи из запроса для API
                # КРИТИЧЕСКИ ВАЖНО: НЕ добавляем "Нижний Новгород" - он добавится автоматически в maps_2gis.py
                search_query = 'кофейни'
                additional_queries = ['кофейня', 'лучшие кофейни', 'кофе-шоп']
            elif any(word in interests_lower for word in ['бар', 'бары']):
                search_query = 'бар'
                additional_queries = ['бары', 'лучшие бары']
            elif any(word in interests_lower for word in ['суши', 'суши-бар', 'сушибар', 'sushi', 'роллы']):
                # Для суши-баров используем точный запрос
                search_query = 'суши-бар'
                additional_queries = ['суши', 'японская кухня', 'сушибар']
            elif any(word in interests_lower for word in ['стейк', 'стейк-хаус', 'стейкхаус']):
                search_query = 'стейк-хаус'
                additional_queries = ['стейк', 'стейкхаус', 'мясо', 'стейки']
            else:
                # Используем точный запрос пользователя, добавляя "Нижний Новгород" для точности поиска
                search_query = f"{interests.strip()} Нижний Новгород"
                additional_queries = [f"лучшие {interests.strip()} Нижний Новгород"]
        elif user_intent == 'entertainment':
            # Для развлечений
            interests_lower = interests.lower()
            if any(word in interests_lower for word in ['кино', 'кинотеатр']):
                search_query = 'кинотеатр Нижний Новгород'
                additional_queries = ['лучшие кинотеатры Нижний Новгород', 'популярные кинотеатры центр Нижний Новгород']
            elif any(word in interests_lower for word in ['клуб', 'клубы']):
                search_query = 'клуб Нижний Новгород'
                additional_queries = ['лучшие клубы Нижний Новгород', 'популярные клубы центр Нижний Новгород']
            else:
                search_query = f"{interests} Нижний Новгород"
                additional_queries = [f"лучшие {interests} Нижний Новгород"]
        elif user_intent == 'culture':
            # Для культуры (музеи, театры)
            interests_lower = interests.lower()
            if any(word in interests_lower for word in ['музей искусств', 'музеи искусств', 'художественный музей', 'галерея искусств']):
                # Для музеев искусств используем точный запрос
                search_query = 'музей искусств Нижний Новгород'
                additional_queries = ['художественный музей Нижний Новгород', 'галерея искусств Нижний Новгород']
            elif any(word in interests_lower for word in ['музей', 'музеи']):
                search_query = 'музей Нижний Новгород'
                additional_queries = ['музеи Нижний Новгород', 'лучшие музеи Нижний Новгород']
            elif any(word in interests_lower for word in ['театр', 'театры']):
                search_query = 'театр Нижний Новгород'
                additional_queries = ['театры Нижний Новгород', 'лучшие театры Нижний Новгород']
            else:
                search_query = f"{interests.strip()} Нижний Новгород"
                additional_queries = [f"лучшие {interests.strip()} Нижний Новгород"]
        else:
            # Используем основной запрос пользователя или первый из списка, добавляя "Нижний Новгород"
            if user_intent == 'general':
                search_query = f"{interests.strip()} Нижний Новгород"
            else:
                search_query = f"{queries[0]} Нижний Новгород"
            additional_queries = [f"лучшие {search_query.replace(' Нижний Новгород', '')} Нижний Новгород"]
        
        # Ищем через 2ГИС API с несколькими попытками
        try:
            # Пробуем несколько вариантов запросов для лучших результатов
            search_queries = [search_query]
            if additional_queries:
                search_queries.extend(additional_queries[:2])  # Берем максимум 2 дополнительных запроса
            
            # КРИТИЧЕСКИ ВАЖНО: Ограничиваем лимит для ускорения работы!
            # Для ближайших мест достаточно 100 результатов
            search_limit = 100  # Достаточно для поиска ближайших мест
            
            logger.debug(f"Поиск в 2ГИС: запрос='{search_query}', location={location}, limit={search_limit}")
            
            all_places = []
            seen_titles = set()
            
            # Оптимизация: используем только первый (самый точный) запрос для ускорения
            if search_queries:
                places = self.maps_service.search_places(
                    query=search_queries[0],
                    location=location,
                    category=category,
                    limit=search_limit
                )
                
                logger.debug(f"2ГИС API вернул {len(places) if places else 0} мест для запроса '{search_queries[0]}'")
                
                # Добавляем только уникальные места
                for place in places:
                    title_lower = place.get('title', '').lower()
                    if title_lower not in seen_titles:
                        seen_titles.add(title_lower)
                        all_places.append(place)
            
            places = all_places
            logger.debug(f"Всего уникальных мест после дедупликации: {len(places)}")
            
            if places:
                # КРИТИЧЕСКИ ВАЖНО: Правильная логика - сначала ближайшие, потом лучшие среди них!
                # ШАГ 1: Фильтруем по расстоянию СНАЧАЛА (только в пределах 5км)
                nearby_places = []
                for place in places:
                    distance = place.get('distance_from_user')
                    if distance is None and location:
                        # Вычисляем расстояние если не было вычислено
                        place_lon = place.get('lon')
                        place_lat = place.get('lat')
                        if place_lon and place_lat:
                            from math import radians, cos, sin, asin, sqrt
                            lon1, lat1 = location
                            lon2, lat2 = place_lon, place_lat
                            R = 6371000
                            dlat = radians(lat2 - lat1)
                            dlon = radians(lon2 - lon1)
                            a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
                            c = 2 * asin(sqrt(a))
                            distance = R * c
                            place['distance_from_user'] = distance
                    
                    # Оставляем только места в пределах 5км
                    if distance is not None and distance <= 5000:
                        nearby_places.append(place)
                
                # ШАГ 2: Из ближайших выбираем лучшие (сортируем: сначала по расстоянию, потом по рейтингу)
                # КРИТИЧЕСКИ ВАЖНО: Сначала ближайшие, потом лучшие среди них!
                def sort_nearby_by_quality(place):
                    """
                    Сортировка ближайших мест: сначала по расстоянию, потом по рейтингу и отзывам
                    """
                    distance = place.get('distance_from_user', float('inf'))
                    rating = place.get('rating', 0)
                    reviews_count = place.get('reviews_count', 0)
                    
                    # Возвращаем кортеж: (расстояние, -рейтинг, -отзывы)
                    # Сортировка по возрастанию расстояния, по убыванию рейтинга и отзывов
                    # Это гарантирует: ближайшее место первым, среди одинакового расстояния - лучший рейтинг
                    return (distance, -rating, -reviews_count)
                
                # Сортируем: ближайшие первыми, среди одинакового расстояния - лучшие по рейтингу
                nearby_places = sorted(nearby_places, key=sort_nearby_by_quality)
                
                places = nearby_places  # Используем только ближайшие места
                logger.debug(f"Отфильтровано до {len(places)} ближайших мест (≤5км) из {len(all_places)} найденных, отсортировано по расстоянию, затем по рейтингу")
                
                if not places:
                    logger.warning(f"⚠️ После фильтрации по 5км не осталось мест! Было найдено {len(all_places)} мест, но все дальше 5км")
                
                external_places.extend(places)
                
        except Exception as e:
            logger.warning(f"Ошибка поиска во внешних источниках: {e}")
        
        # Удаляем дубликаты по координатам и названию
        seen = set()
        unique_places = []
        for place in external_places:
            key = (place.get('title', ''), place.get('lon'), place.get('lat'))
            if key not in seen and place.get('title'):
                seen.add(key)
                unique_places.append(place)
        
        return unique_places[:20]  # Ограничиваем до 20 мест
    
    def _filter_coordinates_in_nizhny(self, route_points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """
        Фильтрует координаты, оставляя только те, что находятся в Нижнем Новгороде
        """
        if not route_points:
            return route_points
        
        filtered_points = [route_points[0]]  # Всегда оставляем первую точку (пользователя)
        
        for point in route_points[1:]:  # Проверяем остальные точки
            lon, lat = point
            if _is_in_nizhny_novgorod(lon, lat):
                filtered_points.append(point)
            else:
                logger.warning(f"Пропускаем координаты ({lat}, {lon}) - вне Нижнего Новгорода")
        
        return filtered_points
    
    def _extract_coordinates_from_route_text(self, route_text: str, user_coords: Tuple[float, float]) -> List[Tuple[float, float]]:
        """
        Извлекает адреса из текста маршрута и геокодирует их для построения карты
        """
        route_points = [user_coords]  # Начало от пользователя
        
        # Парсим адреса из текста маршрута
        lines = route_text.split('\n')
        addresses = []
        
        for i, line in enumerate(lines):
            if 'Адрес:' in line or 'адрес:' in line.lower():
                parts = line.split(':', 1)
                if len(parts) > 1:
                    address = parts[1].strip()
                    if address and address != 'Адрес не указан':
                        # Добавляем "Нижний Новгород" если адрес не содержит город
                        if 'нижний новгород' not in address.lower():
                            address = f"{address}, Нижний Новгород"
                        addresses.append(address)
        
        # Геокодируем адреса
        for address in addresses[:5]:  # Ограничиваем до 5 адресов
            coords = self.maps_service.geocode_address(address)
            if coords:
                lon, lat = coords
                # КРИТИЧЕСКИ ВАЖНО: Проверяем координаты перед добавлением
                if _is_in_nizhny_novgorod(lon, lat):
                    route_points.append(coords)
                else:
                    logger.warning(f"Пропускаем адрес '{address}' - геокодированные координаты ({lat}, {lon}) вне Нижнего Новгорода")
        
        return route_points
    
    def _generate_place_explanation(self, obj: Dict, interests: str, place_num: int) -> str:
        """
        Генерирует детальное объяснение, почему место подходит интересам пользователя
        """
        title = obj.get('title', '').lower()
        description = obj.get('description_clean', obj.get('description', '')).lower()
        interests_lower = interests.lower()
        
        # Определяем тип места и действие
        place_type = "интересное место"
        action = "провести время"
        
        if any(word in title for word in ['кафе', 'кофейня', 'ресторан', 'бар', 'столовая', 'бистро']):
            place_type = "заведение общественного питания"
            if 'ресторан' in title:
                action = "отведать изысканные блюда местной и европейской кухни"
            elif 'кафе' in title or 'кофейня' in title:
                action = "выпить кофе и перекусить в уютной атмосфере"
            elif 'бар' in title:
                action = "попробовать напитки и закуски, провести время в компании"
            else:
                action = "отведать блюда и напитки"
        elif any(word in title for word in ['торговый центр', 'тц', 'молл']):
            place_type = "торговый центр"
            action = "совершить покупки, прогуляться по магазинам и бутикам"
        elif any(word in title for word in ['спорт', 'стадион', 'фитнес', 'спортзал', 'площадка']):
            place_type = "спортивный объект"
            action = "заняться спортом или посмотреть спортивные мероприятия"
        elif any(word in title for word in ['кинотеатр', 'клуб', 'боулинг', 'бильярд', 'развлечения']):
            place_type = "развлекательное заведение"
            if 'кинотеатр' in title:
                action = "посмотреть новый фильм в современном кинотеатре"
            elif 'клуб' in title:
                action = "отдохнуть и развлечься в атмосфере ночного клуба"
            else:
                action = "отлично провести время и развлечься"
        elif any(word in title for word in ['музей', 'галерея', 'выставка']):
            place_type = "культурный объект"
            action = "узнать новое и получить культурный опыт"
        elif any(word in title for word in ['парк', 'сад', 'сквер', 'набережная']):
            place_type = "место для прогулки"
            action = "прогуляться и отдохнуть на свежем воздухе"
        elif any(word in title for word in ['собор', 'храм', 'церковь']):
            place_type = "архитектурный и духовный объект"
            action = "увидеть архитектуру и почувствовать атмосферу"
        elif any(word in title for word in ['кремль', 'крепость', 'башня']):
            place_type = "исторический и архитектурный памятник"
            action = "погрузиться в историю и увидеть архитектуру"
        elif any(word in title for word in ['театр']):
            place_type = "культурное заведение"
            action = "приобщиться к театральному искусству"
        
        # Формируем объяснение
        explanation = f"Это {place_type}, которое отлично подходит для ваших интересов '{interests}'. "
        explanation += f"Здесь вы сможете {action}. "
        
        # Добавляем связь с конкретными интересами
        if any(kw in interests_lower for kw in ['история', 'историческ']):
            explanation += "Место связано с историей Нижнего Новгорода и поможет лучше понять город."
        elif any(kw in interests_lower for kw in ['архитектура', 'архитектурн']):
            explanation += "Здесь вы увидите интересную архитектуру и узнаете об архитектурных особенностях."
        elif any(kw in interests_lower for kw in ['культура', 'культурн']):
            explanation += "Это место богато культурным наследием и представляет значительный интерес."
        else:
            explanation += "Место идеально соответствует вашим интересам и предпочтениям."
        
        return explanation
    
    def _regenerate_route_with_order(self, selected_objects: List[Dict], interests: str, 
                                    time_minutes: int, start_location: str) -> str:
        """
        Генерирует текст маршрута с правильной нумерацией объектов в порядке посещения
        Обеспечивает минимум 3 места, максимум 5 мест
        """
        if not selected_objects:
            return "Не удалось найти подходящие места в датасете."
        
        # Обеспечиваем минимум 3 места, максимум 5 мест
        num_places = len(selected_objects)
        if num_places < 3:
            # Если меньше 3, берем из доступных (но это не должно происходить)
            logger.warning(f"Найдено только {num_places} мест, требуется минимум 3")
        elif num_places > 5:
            # Ограничиваем до 5
            selected_objects = selected_objects[:5]
            num_places = 5
        
        route_text = "МАРШРУТ ПО НИЖНЕМУ НОВГОРОДУ\n\n"
        
        for i, obj in enumerate(selected_objects, 1):
            title = obj.get('title', 'Без названия')
            address = obj.get('address', 'Адрес не указан')
            description = obj.get('description_clean', obj.get('description', ''))
            
            # Очищаем описание от HTML и ограничиваем длину
            if description:
                desc_clean = description.replace('<p>', '').replace('</p>', '').strip()[:250]
                if len(description) > 250:
                    desc_clean += '...'
            else:
                desc_clean = f"Интересное место, связанное с '{interests}'"
            
            route_text += f"Место {i}: {title}\n"
            route_text += f"Адрес: {address}\n"
            
            # КРИТИЧЕСКИ ВАЖНО: Сначала проверяем уникальное объяснение от GigaChat!
            gigachat_explanation = obj.get('gigachat_explanation', '')
            if gigachat_explanation and len(gigachat_explanation.strip()) > 50:
                # Используем уникальное объяснение от GigaChat (оно уже развернутое и уникальное для каждого места)
                route_text += f"Почему идем сюда: {gigachat_explanation.strip()}\n"
            elif desc_clean and len(desc_clean) > 80:
                # Если нет объяснения от GigaChat, используем описание из датасета
                route_text += f"Почему идем сюда: {desc_clean}\n"
            else:
                # Если описания нет или оно короткое, формируем объяснение на основе интересов
                explanation = self._generate_place_explanation(obj, interests, i)
                route_text += f"Почему идем сюда: {explanation}\n"
            
            # Оцениваем время посещения на основе типа объекта
            visit_time = 30  # По умолчанию 30 минут
            title_lower = title.lower()
            
            # Заведения общественного питания
            if any(word in title_lower for word in ['кафе', 'кофейня', 'ресторан', 'бар', 'столовая', 'бистро']):
                visit_time = 45  # 30-60 минут
            # Торговые центры
            elif any(word in title_lower for word in ['торговый центр', 'тц', 'молл', 'магазин']):
                visit_time = 45  # 30-60 минут
            # Спортивные объекты
            elif any(word in title_lower for word in ['спорт', 'стадион', 'фитнес', 'спортзал', 'площадка']):
                visit_time = 30  # 20-40 минут
            # Развлечения
            elif any(word in title_lower for word in ['кинотеатр', 'клуб', 'боулинг', 'бильярд', 'развлечения']):
                visit_time = 60  # 60+ минут
            # Культурные объекты
            elif any(word in title_lower for word in ['музей', 'галерея', 'выставка']):
                visit_time = 45
            elif any(word in title_lower for word in ['парк', 'сад', 'сквер', 'набережная']):
                visit_time = 30  # 20-40 минут
            elif any(word in title_lower for word in ['театр']):
                visit_time = 60  # Для спектакля
            elif any(word in title_lower for word in ['собор', 'церковь', 'храм']):
                visit_time = 25  # 15-30 минут
            elif any(word in title_lower for word in ['кремль', 'крепость', 'башня']):
                visit_time = 40  # 30-45 минут
            elif any(word in title_lower for word in ['памятник', 'скульптура']):
                visit_time = 15
            
            route_text += f"Время на посещение: {visit_time} минут\n\n"
        
        route_text += "ОБЩИЙ ТАЙМЛАЙН:\n"
        route_text += f"Начало маршрута от {start_location}\n"
        
        # Добавляем переходы и места в правильном порядке
        for i in range(1, len(selected_objects) + 1):
            if i == 1:
                route_text += f"Переход к Месту {i}\n"
            else:
                route_text += f"Переход к Месту {i}\n"
            route_text += f"Место {i}\n"
        
        route_text += "\nЗавершение маршрута"
        
        return route_text
    
    def _regenerate_route_text(self, selected_objects: List[Dict], interests: str, 
                               time_minutes: int, start_location: str) -> str:
        """
        Генерирует текст маршрута на основе реальных объектов из датасета
        """
        if not selected_objects:
            return "Не удалось найти подходящие места в датасете."
        
        route_text = "МАРШРУТ ПО НИЖНЕМУ НОВГОРОДУ\n\n"
        
        for i, obj in enumerate(selected_objects, 1):
            title = obj.get('title', 'Без названия')
            address = obj.get('address', 'Адрес не указан')
            description = obj.get('description_clean', obj.get('description', ''))
            
            # Очищаем описание от HTML и ограничиваем длину
            if description:
                desc_clean = description.replace('<p>', '').replace('</p>', '').strip()[:250]
                if len(description) > 250:
                    desc_clean += '...'
            else:
                desc_clean = f"Интересное место, связанное с '{interests}'"
            
            route_text += f"Место {i}: {title}\n"
            route_text += f"Адрес: {address}\n"
            route_text += f"Почему идем сюда: {desc_clean}\n"
            
            # Оцениваем время посещения на основе типа объекта
            visit_time = 20
            title_lower = title.lower()
            
            if any(word in title_lower for word in ['музей', 'галерея', 'выставка']):
                visit_time = 45
            elif any(word in title_lower for word in ['парк', 'сад', 'сквер']):
                visit_time = 30
            elif any(word in title_lower for word in ['театр', 'кинотеатр']):
                visit_time = 60
            elif any(word in title_lower for word in ['собор', 'церковь', 'храм']):
                visit_time = 25
            elif any(word in title_lower for word in ['кремль', 'башня']):
                visit_time = 40
            elif any(word in title_lower for word in ['памятник', 'скульптура']):
                visit_time = 15
            
            route_text += f"Время на посещение: {visit_time} минут\n\n"
        
        route_text += "ОБЩИЙ ТАЙМЛАЙН:\n"
        route_text += f"Начало маршрута от {start_location}\n"
        route_text += "Переход к Месту 1\n"
        route_text += "Место 1\n"
        
        if len(selected_objects) > 1:
            for i in range(2, len(selected_objects) + 1):
                route_text += f"Переход к Месту {i}\n"
                route_text += f"Место {i}\n"
        
        route_text += "\nЗавершение маршрута"
        
        return route_text
    
    def _clean_route_text(self, route_text: str, selected_objects: List[Dict]) -> str:
        """
        Очищает текст маршрута от выдуманных мест и лишних объяснений
        Оставляет только реальные объекты из датасета
        """
        # Список реальных названий объектов
        real_titles = {obj.get('title', '').lower() for obj in selected_objects}
        real_addresses = {obj.get('address', '').lower() for obj in selected_objects}
        
        lines = route_text.split('\n')
        cleaned_lines = []
        skip_until_next_place = False
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Пропускаем вступления и объяснения GigaChat
            if any(phrase in line.lower() for phrase in [
                'извиняюсь',
                'из предоставленного списка',
                'ни одно место',
                'альтернативную версию',
                'популярных кофейнях',
                'кофейням нижнего новгорода',
                'позволит насладиться',
                'вкусом отличного кофе',
                'подходящих мест под категорию',
                'среди указанного списка нет',
                'поэтому предлагаю',
                'интересным объектам города',
                'будет интересен любому туристу'
            ]):
                skip_until_next_place = True
                i += 1
                continue
            
            # Если видим "МАРШРУТ ПО НИЖНЕМУ НОВГОРОДУ", начинаем записывать
            if 'МАРШРУТ ПО НИЖНЕМУ НОВГОРОДУ' in line:
                skip_until_next_place = False
                cleaned_lines.append(line)
                i += 1
                continue
            
            # Пропускаем пустые строки в начале
            if not line.strip() and len(cleaned_lines) == 0:
                i += 1
                continue
            
            # Проверяем, является ли строка описанием места
            if skip_until_next_place:
                if line.strip().startswith('Место') and ':' in line:
                    # Проверяем, есть ли это место в реальных объектах
                    place_name = line.split(':', 1)[-1].strip().lower()
                    if any(place_name in title or title in place_name for title in real_titles):
                        skip_until_next_place = False
                    else:
                        i += 1
                        continue
                else:
                    i += 1
                    continue
            
            cleaned_lines.append(line)
            i += 1
        
        return '\n'.join(cleaned_lines)
    
    def _build_optimal_route(self, start_coords: Tuple[float, float], objects: List[Dict]) -> List[Dict]:
        """
        Строит оптимальный маршрут, начиная с ближайших объектов к начальной точке пользователя
        Использует жадный алгоритм (ближайший сосед): каждый раз выбираем ближайший непосещенный объект
        Использует формулу гаверсинуса для точного расчета расстояний
        Гарантирует, что первое место - ближайшее к пользователю
        """
        if not objects:
            return []
        
        def haversine_distance(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
            """
            Вычисляет расстояние между двумя точками в метрах по формуле гаверсинуса
            """
            lon1, lat1 = coord1
            lon2, lat2 = coord2
            
            R = 6371000  # Радиус Земли в метрах
            dlat = radians(lat2 - lat1)
            dlon = radians(lon2 - lon1)
            a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return R * c
        
        # Разделяем объекты на те, что с координатами и без
        objects_with_coords = []
        objects_without_coords = []
        
        for obj in objects:
            obj_lon = obj.get('lon')
            obj_lat = obj.get('lat')
            if obj_lon is not None and obj_lat is not None:
                # КРИТИЧЕСКИ ВАЖНО: Проверяем, что координаты в пределах Нижнего Новгорода
                if _is_in_nizhny_novgorod(obj_lon, obj_lat):
                    objects_with_coords.append(obj)
                else:
                    logger.warning(f"Исключаем место '{obj.get('title')}' из маршрута - координаты ({obj_lat}, {obj_lon}) вне Нижнего Новгорода")
                    objects_without_coords.append(obj)
            else:
                objects_without_coords.append(obj)
        
        if not objects_with_coords:
            # Если нет объектов с координатами, возвращаем как есть
            logger.warning("Нет объектов с координатами для построения оптимального маршрута")
            return objects
        
        # КРИТИЧЕСКИ ВАЖНО: Гарантируем минимум 3 места в маршруте!
        MIN_PLACES_REQUIRED = 3
        
        # КРИТИЧЕСКИ ВАЖНО: Фильтруем объекты по расстоянию от пользователя ПЕРЕД построением маршрута
        # Расширенный радиус 5км, потом выберем ближайшие с лучшим рейтингом
        MAX_DISTANCE_FOR_FIRST_PLACE = 5000  # 5км - расширенный радиус поиска
        nearby_objects = []
        far_objects = []
        
        for obj in objects_with_coords:
            obj_lon = obj.get('lon')
            obj_lat = obj.get('lat')
            if obj_lon is not None and obj_lat is not None:
                obj_coords = (obj_lon, obj_lat)
                distance = haversine_distance(start_coords, obj_coords)
                obj['distance_from_user'] = distance
                
                if distance <= MAX_DISTANCE_FOR_FIRST_PLACE:
                    nearby_objects.append(obj)
                else:
                    far_objects.append(obj)
        
        # КРИТИЧЕСКИ ВАЖНО: Если ближайших объектов недостаточно для минимума (3 места) - расширяем радиус!
        # Это гарантирует, что у нас будет достаточно мест для построения маршрута
        if len(nearby_objects) < MIN_PLACES_REQUIRED:
            logger.warning(f"⚠️ Ближайших объектов недостаточно ({len(nearby_objects)} из {MIN_PLACES_REQUIRED}). Расширяем поиск до 10км")
            # Расширяем радиус до 10км для поиска больше мест
            EXPANDED_RADIUS = 10000  # 10км
            for obj in far_objects[:]:
                distance = obj.get('distance_from_user', 0)
                if distance <= EXPANDED_RADIUS:
                    nearby_objects.append(obj)
                    far_objects.remove(obj)
                    logger.debug(f"Добавлен объект '{obj.get('title')}' в ближайшие (расстояние: {distance/1000:.2f}км) для достижения минимума")
            
            logger.debug(f"После расширения: {len(nearby_objects)} ближайших объектов, {len(far_objects)} дальних объектов")
        
        # КРИТИЧЕСКИ ВАЖНО: Сортируем ближайшие объекты по расстоянию, потом по рейтингу
        # Это гарантирует: сначала ближайшие, потом лучшие среди них
        nearby_objects = sorted(
            nearby_objects,
            key=lambda x: (
                x.get('distance_from_user', float('inf')),  # Сначала по расстоянию (возрастание)
                -x.get('rating', 0),  # Потом по рейтингу (убывание)
                -x.get('reviews_count', 0)  # Потом по количеству отзывов (убывание)
            )
        )
        
        # КРИТИЧЕСКИ ВАЖНО: Строим маршрут, минимизируя общее расстояние и избегая возвратов
        # Логика: первое место - ближайшее к пользователю, затем выбираем места так, чтобы двигаться вперед
        route = []
        
        # Используем только ближайшие объекты (уже отсортированы по расстоянию от пользователя, потом по рейтингу)
        # Дальние объекты полностью исключены!
        remaining = nearby_objects.copy()
        current_coords = start_coords  # Начинаем от точки пользователя
        
        logger.debug(f"Построение оптимального маршрута: {len(nearby_objects)} ближайших мест (≤{MAX_DISTANCE_FOR_FIRST_PLACE/1000:.1f}км от пользователя, отсортированы по расстоянию и рейтингу), {len(far_objects)} дальних мест ИСКЛЮЧЕНЫ")
        
        # КРИТИЧЕСКИ ВАЖНО: Улучшенный алгоритм построения маршрута
        # 1. Первое место - ближайшее к пользователю (из всех в радиусе 5км)
        # 2. Последующие места - ближайшие к предыдущему, но НЕ дальше 2км!
        # 3. Штраф за возврат назад (к начальной точке пользователя)
        
        # КРИТИЧЕСКИ ВАЖНО: Ограничение на максимальное расстояние между соседними местами
        # Начинаем с 1500м, расширяем при необходимости до 3км для оптимизации маршрута
        INITIAL_MAX_DISTANCE_BETWEEN_PLACES = 1500  # Начинаем с 1.5км между местами
        MAX_EXPANDED_DISTANCE = 3000  # Максимальное расширение до 3км между местами
        
        max_places_in_route = min(5, len(nearby_objects))  # Максимум 5 мест
        
        # Текущее максимальное расстояние между соседними местами (динамически расширяется)
        current_max_distance = INITIAL_MAX_DISTANCE_BETWEEN_PLACES
        
        while remaining and len(route) < max_places_in_route:
            best_obj = None
            best_score = float('inf')  # Меньше = лучше
            best_coords = None
            found_in_current_radius = False  # Найдено ли место в текущем радиусе
            
            # Пробуем найти место в текущем радиусе
            for obj in remaining:
                obj_lon = obj.get('lon')
                obj_lat = obj.get('lat')
                
                if obj_lon is not None and obj_lat is not None:
                    obj_coords = (obj_lon, obj_lat)
                    distance = haversine_distance(current_coords, obj_coords)
                    
                    # Получаем рейтинг и количество отзывов объекта
                    rating = obj.get('rating', 0)
                    reviews_count = obj.get('reviews_count', 0)
                    distance_from_user = obj.get('distance_from_user', distance)  # Используем сохраненное расстояние или вычисляем
                    
                    # КРИТИЧЕСКИ ВАЖНО: Для первого места выбираем ПРОСТО БЛИЖАЙШЕЕ к пользователю!
                    # Все объекты уже отсортированы по расстоянию, просто берем первое!
                    if len(route) == 0:
                        # Первое место: ПРОСТО БЛИЖАЙШЕЕ к пользователю (все объекты уже отсортированы по расстоянию)
                        user_distance = distance_from_user if distance_from_user else haversine_distance(start_coords, obj_coords)
                        
                        # КРИТИЧЕСКИ ВАЖНО: Все объекты в remaining уже отсортированы по расстоянию от пользователя!
                        # Просто используем расстояние как score - ближайшее будет первым
                        # Добавляем небольшой бонус за хороший рейтинг, но приоритет БЛИЗОСТИ
                        max_first_place_distance = 5000  # 5 км максимум
                        
                        # Дополнительная проверка (на всякий случай)
                        if user_distance > max_first_place_distance:
                            score = 10000000 + user_distance  # Максимальный штраф
                        else:
                            # Нормализуем расстояние (0-1, где 0 = ближайший)
                            normalized_user_distance = user_distance / max_first_place_distance
                            
                            # Небольшой бонус за рейтинг (только если рейтинг хороший)
                            rating_bonus = 0.0
                            if rating >= 4.0:
                                rating_bonus = -0.05  # Небольшой бонус за хороший рейтинг (вычитаем, так как меньше = лучше)
                            elif rating > 0 and rating < 3.5:
                                rating_bonus = 0.02  # Небольшой штраф за плохой рейтинг
                            
                            # Score = расстояние (приоритет 99%) + небольшой бонус/штраф за рейтинг (1%)
                            score = normalized_user_distance * 0.99 + rating_bonus
                    else:
                        # КРИТИЧЕСКИ ВАЖНО: Проверяем расстояние с учетом текущего лимита
                        # Если место дальше текущего лимита от предыдущего - пропускаем
                        if distance > current_max_distance:
                            # Слишком далеко для текущего радиуса - пропускаем
                            continue
                        
                        found_in_current_radius = True  # Найдено место в текущем радиусе
                        
                        # Для последующих мест: учитываем расстояние к предыдущему И общее направление движения
                        # Нормализуем расстояние (максимум current_max_distance между местами)
                        normalized_distance = min(distance / current_max_distance, 1.0)  # 0-1, где 0 = ближайший
                        
                        # КРИТИЧЕСКИ ВАЖНО: Штраф за возврат назад к пользователю!
                        # Если место ближе к начальной точке, чем текущее - это плохо (возврат назад)
                        user_distance_from_obj = distance_from_user if distance_from_user else haversine_distance(start_coords, obj_coords)
                        user_distance_from_current = haversine_distance(start_coords, current_coords)
                        
                        # Штраф за возврат: если новое место ближе к пользователю, чем текущее - штраф
                        backward_penalty = 0.0
                        if user_distance_from_obj < user_distance_from_current:
                            # Возвращаемся назад - штраф пропорционален разнице
                            distance_saved = user_distance_from_current - user_distance_from_obj
                            backward_penalty = min(distance_saved / 1000.0, 0.3)  # Максимальный штраф 0.3 (30%)
                        
                        # Нормализуем рейтинг
                        normalized_rating = rating / 5.0 if rating > 0 else 0.3
                        
                        # Нормализуем количество отзывов
                        if reviews_count > 0:
                            reviews_score = min(1.0, 0.3 + (min(reviews_count, 1000) / 1000) * 0.7)
                        else:
                            reviews_score = 0.2
                        
                        # Комбинированный балл популярности: рейтинг 60%, отзывы 40%
                        popularity_score = normalized_rating * 0.6 + reviews_score * 0.4
                        
                        # Штраф за низкий рейтинг
                        if rating > 0 and rating < 3.5:
                            popularity_score = popularity_score * 0.5
                        
                        # КРИТИЧЕСКИ ВАЖНО: Максимальный приоритет близости!
                        # Расстояние к предыдущему 95%, популярность 4%, штраф за возврат 1%
                        # Это гарантирует выбор САМЫХ ближайших мест!
                        score = normalized_distance * 0.95 - popularity_score * 0.04 + backward_penalty * 0.01
                    
                    if score < best_score:
                        best_score = score
                        best_obj = obj
                        best_coords = obj_coords
            
            # Добавляем лучший объект в маршрут
            if best_obj:
                route.append(best_obj)
                remaining.remove(best_obj)
                
                # Логируем информацию о выборе с рейтингом и отзывами
                distance_info = haversine_distance(start_coords, best_coords) if len(route) == 1 else haversine_distance(current_coords, best_coords)
                rating = best_obj.get('rating', 0)
                reviews_count = best_obj.get('reviews_count', 0)
                rating_info = f", рейтинг {rating:.1f}" if rating > 0 else ""
                reviews_info = f", отзывов {reviews_count}" if reviews_count > 0 else ""
                
                logger.debug(f"Выбрано место #{len(route)}: '{best_obj.get('title')}' на расстоянии {distance_info/1000:.2f}км от предыдущего (лимит: {current_max_distance/1000:.1f}км){rating_info}{reviews_info}")
                
                # Обновляем текущую позицию для следующей итерации
                current_coords = best_coords
                
                # Сбрасываем радиус для следующего места (начинаем поиск с 2км снова)
                current_max_distance = INITIAL_MAX_DISTANCE_BETWEEN_PLACES
            else:
                # КРИТИЧЕСКИ ВАЖНО: Если не нашли место в текущем радиусе - расширяем радиус!
                # Гарантируем минимум 3 места в маршруте!
                if len(route) > 0 and remaining:
                    if current_max_distance < MAX_EXPANDED_DISTANCE:
                        # Расширяем радиус поиска
                        old_radius = current_max_distance
                        current_max_distance = min(current_max_distance + 500, MAX_EXPANDED_DISTANCE)  # Увеличиваем на 500м
                        logger.debug(f"Не найдено мест в пределах {old_radius/1000:.1f}км от '{route[-1].get('title')}', расширяем радиус до {current_max_distance/1000:.1f}км")
                        # Продолжаем цикл - попробуем найти с расширенным радиусом
                        continue
                    else:
                        # Уже дошли до максимального радиуса - ищем ближайшее из оставшихся
                        logger.debug(f"Достигнут максимальный радиус {MAX_EXPANDED_DISTANCE/1000:.1f}км, ищем ближайшее место из оставшихся")
                        best_obj = None
                        best_distance = float('inf')
                        for obj in remaining:
                            obj_lon = obj.get('lon')
                            obj_lat = obj.get('lat')
                            if obj_lon is not None and obj_lat is not None:
                                obj_coords = (obj_lon, obj_lat)
                                distance = haversine_distance(current_coords, obj_coords)
                                if distance < best_distance:
                                    best_distance = distance
                                    best_obj = obj
                        
                        if best_obj:
                            route.append(best_obj)
                            remaining.remove(best_obj)
                            logger.debug(f"Добавлено место #{len(route)}: '{best_obj.get('title')}' на расстоянии {best_distance/1000:.2f}км (максимальный радиус)")
                            current_coords = (best_obj.get('lon'), best_obj.get('lat'))
                            current_max_distance = INITIAL_MAX_DISTANCE_BETWEEN_PLACES  # Сбрасываем для следующего места
                        else:
                            # Нет больше мест - проверяем, достигли ли минимума
                            if len(route) < MIN_PLACES_REQUIRED:
                                logger.warning(f"⚠️ КРИТИЧЕСКАЯ ПРОБЛЕМА: Найдено только {len(route)} мест, требуется минимум {MIN_PLACES_REQUIRED}!")
                            else:
                                logger.debug(f"Построен маршрут из {len(route)} мест (минимум {MIN_PLACES_REQUIRED} достигнут)")
                            break
                else:
                    # Нет больше мест или это первое место
                    if len(route) < MIN_PLACES_REQUIRED:
                        logger.warning(f"⚠️ КРИТИЧЕСКАЯ ПРОБЛЕМА: Не удалось найти минимум {MIN_PLACES_REQUIRED} мест! Найдено только {len(route)}")
                    break
        
        # КРИТИЧЕСКИ ВАЖНО: Гарантируем минимум 3 места!
        # Если недостаточно мест - добавляем из оставшихся, даже если они дальше
        places_needed = MIN_PLACES_REQUIRED - len(route)
        
        if places_needed > 0:
            logger.warning(f"⚠️ ВНИМАНИЕ: Маршрут содержит только {len(route)} мест, требуется минимум {MIN_PLACES_REQUIRED}. Добавляем недостающие {places_needed} мест")
            
            # ПЕРВАЯ ПОПЫТКА: Добавляем из оставшихся ближайших объектов
            if len(remaining) > 0:
                logger.debug(f"Попытка 1: Добавляем {places_needed} мест из оставшихся ближайших ({len(remaining)} доступно)")
                added_count = 0
                for obj in remaining:
                    if len(route) >= MIN_PLACES_REQUIRED:
                        break
                    obj_lon = obj.get('lon')
                    obj_lat = obj.get('lat')
                    if obj_lon is not None and obj_lat is not None:
                        # Проверяем расстояние - если слишком далеко, все равно добавляем для минимума
                        distance_to_last = haversine_distance(current_coords, (obj_lon, obj_lat)) if len(route) > 0 else obj.get('distance_from_user', 0)
                        route.append(obj)
                        added_count += 1
                        logger.debug(f"Добавлено дополнительное место #{len(route)}: '{obj.get('title')}' (расстояние от предыдущего: {distance_to_last/1000:.2f}км) для достижения минимума")
                
                places_needed = MIN_PLACES_REQUIRED - len(route)
            
            # ВТОРАЯ ПОПЫТКА: Если все еще недостаточно - добавляем дальние объекты
            if places_needed > 0 and len(far_objects) > 0:
                logger.debug(f"Попытка 2: Добавляем {places_needed} мест из дальних объектов ({len(far_objects)} доступно)")
                # Сортируем дальние объекты: сначала по рейтингу, потом по расстоянию от пользователя
                sorted_far = sorted(far_objects, key=lambda x: (-x.get('rating', 0), x.get('distance_from_user', float('inf'))))
                added_count = 0
                for obj in sorted_far:
                    if len(route) >= MIN_PLACES_REQUIRED:
                        break
                    obj_lon = obj.get('lon')
                    obj_lat = obj.get('lat')
                    if obj_lon is not None and obj_lat is not None:
                        route.append(obj)
                        added_count += 1
                        distance_from_user = obj.get('distance_from_user', 0)
                        logger.debug(f"Добавлено дальнее место #{len(route)}: '{obj.get('title')}' (расстояние от пользователя: {distance_from_user/1000:.2f}км) для достижения минимума")
                
                places_needed = MIN_PLACES_REQUIRED - len(route)
            
            # ТРЕТЬЯ ПОПЫТКА: Если все еще недостаточно - используем все доступные объекты (даже вне радиуса 5км)
            if places_needed > 0:
                logger.warning(f"⚠️ КРИТИЧЕСКАЯ ПРОБЛЕМА: Все еще недостаточно мест ({len(route)} из {MIN_PLACES_REQUIRED}). Пытаемся использовать все доступные объекты")
                # Используем все объекты с координатами, которые были в исходном списке
                all_available = nearby_objects + far_objects
                for obj in all_available:
                    if len(route) >= MIN_PLACES_REQUIRED:
                        break
                    # Проверяем, не добавлен ли уже объект в маршрут
                    if obj not in route:
                        obj_lon = obj.get('lon')
                        obj_lat = obj.get('lat')
                        if obj_lon is not None and obj_lat is not None:
                            route.append(obj)
                            logger.warning(f"Добавлено любое доступное место #{len(route)}: '{obj.get('title')}' для достижения минимума")
        
        # ФИНАЛЬНАЯ ПРОВЕРКА: Гарантируем минимум 3 места любой ценой!
        if len(route) < MIN_PLACES_REQUIRED:
            logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось найти минимум {MIN_PLACES_REQUIRED} мест! Маршрут содержит только {len(route)} мест")
            # В крайнем случае возвращаем то, что есть, но это нежелательно
        elif far_objects:
            logger.debug(f"Дальние объекты ({len(far_objects)}) исключены - достаточно ближайших ({len(route)})")
        
        # Добавляем объекты без координат в конец маршрута
        if objects_without_coords:
            logger.warning(f"Добавляем {len(objects_without_coords)} объектов без координат в конец маршрута")
            route.extend(objects_without_coords)
        
        logger.debug(f"Маршрут построен: {len(route)} мест (первые {len([r for r in route if r.get('distance_from_user', float('inf')) <= 5000])} в радиусе 5км)")
        return route
    
    def _calculate_complete_route_times(self, route_points: List[Tuple[float, float]], 
                                       selected_objects: List[Dict], total_time_minutes: int) -> List[Dict]:
        """
        Вычисляет полное время маршрута с учетом:
        - Времени перемещения ПЕШКОМ (всегда пешеходный маршрут)
        - Времени посещения каждого места
        - ВСЕГДА использует пешеходный режим для расчетов (не использует транспорт)
        """
        route_with_times = []
        remaining_time = total_time_minutes
        
        for i in range(len(route_points) - 1):
            point1 = route_points[i]
            point2 = route_points[i + 1]
            
            # Получаем информацию об объекте назначения для времени посещения
            visit_time = 20  # По умолчанию
            obj = None
            
            # Объект в точке назначения - это selected_objects[i] (point2 соответствует объекту с индексом i)
            if i < len(selected_objects):
                obj = selected_objects[i]
                title = obj.get('title', '').lower()
                description = obj.get('description_clean', obj.get('description', '')).lower()
                
                # Умное определение времени на основе типа объекта
                if any(word in title for word in ['музей', 'галерея', 'выставка']):
                    visit_time = 45
                elif any(word in title for word in ['парк', 'сад', 'сквер', 'набережная']) or any(word in description for word in ['парк', 'сад']):
                    visit_time = 30
                elif any(word in title for word in ['театр', 'кинотеатр']):
                    visit_time = 60  # Театры требуют больше времени
                elif any(word in title for word in ['памятник', 'скульптура', 'монумент']):
                    visit_time = 15
                elif any(word in title for word in ['собор', 'церковь', 'храм', 'монастырь']):
                    visit_time = 25
                elif any(word in title for word in ['кремль', 'башня', 'крепость']):
                    visit_time = 40
                else:
                    visit_time = 20
            
            # Для пеших маршрутов используем формулу гаверсинуса напрямую
            # Это избегает ошибок 429 от 2ГИС API и быстрее
            # API Routing используем только для авто/общественного транспорта
            from math import radians, cos, sin, asin, sqrt
            
            def haversine_distance(lon1, lat1, lon2, lat2):
                R = 6371000  # Радиус Земли в метрах
                dlat = radians(lat2 - lat1)
                dlon = radians(lon2 - lon1)
                a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
                c = 2 * asin(sqrt(a))
                return R * c
            
            # Вычисляем расстояние напрямую по формуле гаверсинуса
            walking_distance = haversine_distance(point1[0], point1[1], point2[0], point2[1])
            walking_time = self.maps_service.estimate_walking_time(walking_distance)
            
            # Опционально: можно попробовать получить более точные данные от API (но редко работает из-за лимитов)
            # route_data_walking = self.maps_service.build_route([point1, point2], route_type="pedestrian")
            # if route_data_walking and route_data_walking.get('total_duration'):
            #     walking_time = max(1, int(route_data_walking['total_duration'] / 60))
            #     walking_distance = route_data_walking.get('total_distance', walking_distance)
            
            # ВСЕГДА пешком - пользователь хочет пешеходную прогулку
            transport_type = "пешком"
            transport_time = walking_time
            
            # Проверяем, что расстояние разумное для пешей прогулки (максимум 2.5 км между местами)
            if walking_distance and walking_distance > 2500:
                # Расстояние слишком большое для комфортной пешей прогулки
                # Логируем предупреждение, но оставляем пешком
                logger.warning(f"Большое расстояние между местами: {walking_distance:.0f}м ({walking_distance/1000:.1f}км) - все равно оставляем пешком")
            
            # Проверяем, укладываемся ли во время
            segment_total_time = transport_time + visit_time
            if remaining_time < segment_total_time:
                # Не хватает времени, уменьшаем время посещения (но оставляем минимум 10 минут)
                visit_time = max(10, remaining_time - transport_time)
                segment_total_time = transport_time + visit_time
                if visit_time < 10:
                    # Даже на переход не хватает времени, пропускаем это место
                    break
            
            remaining_time -= segment_total_time
            
            # КРИТИЧЕСКИ ВАЖНО: Если остается много времени в конце маршрута, увеличиваем время посещения последних мест
            # Это обеспечит использование всего доступного бюджета времени
            if i == len(route_points) - 2:  # Последнее место в маршруте
                if remaining_time > 15:  # Если остается больше 15 минут
                    # Увеличиваем время посещения последнего места на оставшееся время (но не более чем в 2 раза)
                    max_visit_time = visit_time * 2
                    additional_time = min(remaining_time, max_visit_time - visit_time)
                    if additional_time > 0:
                        visit_time += additional_time
                        segment_total_time += additional_time
                        remaining_time -= additional_time
                        logger.debug(f"Время посещения скорректировано")
            
            route_with_times.append({
                'from': point1,
                'to': point2,
                'distance_meters': walking_distance or 0,
                'duration_minutes': transport_time,
                'transport_type': transport_type,
                'visit_time_minutes': visit_time,
                'total_segment_time': segment_total_time
            })
        
        return route_with_times

