import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GIGACHAT_API_KEY = os.getenv("GIGACHAT_API_KEY")
GIGACHAT_BASE_URL = os.getenv("GIGACHAT_BASE_URL", "https://foundation-models.api.cloud.ru/v1")
GIGACHAT_MODEL = os.getenv("GIGACHAT_MODEL", "GigaChat/GigaChat-2-Max")
DVGIS_API_KEY = os.getenv("DVGIS_API_KEY")

DATASET_PATH = os.getenv("DATASET_PATH", "data/cultural_objects_mnn.xlsx")

