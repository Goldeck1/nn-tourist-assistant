from enum import Enum


class UserState(Enum):
    """Состояния FSM для диалога с пользователем"""
    WAITING_INTERESTS = "waiting_interests"
    WAITING_TIME = "waiting_time"
    WAITING_LOCATION = "waiting_location"
    ROUTE_GENERATED = "route_generated"

