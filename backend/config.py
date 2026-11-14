
import os
from urllib.parse import quote_plus

import streamlit as st


def secret(name, default=None):
    """Получает секрет из Streamlit Secrets или переменных окружения."""
    try:
        value = st.secrets.get(name)
        if value is not None:
            return value
    except Exception:
        pass

    return os.environ.get(name, default)


GIGA_KEY = secret("GIGA_KEY")
GIGA_SCOPE = secret("GIGA_SCOPE", "GIGACHAT_API_PERS")
GIGA_MODEL = secret("GIGA_MODEL", "GigaChat-2")
GIGA_BASE_URL = secret("GIGA_BASE_URL")

MAX_CLAIMS = 5

ICONS = {
    "confirmed": "✅",
    "contradicted": "❌",
    "no_source": "⚠️",
}


def yandex_link(query: str) -> str:
    """Формирует ссылку на поиск в Яндексе."""
    return f"https://yandex.ru/search/?text={quote_plus(query)}"
