
"""Работа с API GigaChat."""

import time


def call_gigachat(
    system_prompt: str,
    user_prompt: str,
    retries: int = 2,
) -> str:
    """Отправляет запрос в GigaChat и возвращает текст ответа."""

    from backend.config import (
        GIGA_KEY,
        GIGA_SCOPE,
        GIGA_MODEL,
        GIGA_BASE_URL,
    )

    if not GIGA_KEY:
        raise RuntimeError(
            "Не задан ключ GIGA_KEY. Добавьте его в Streamlit Secrets."
        )

    try:
        from gigachat import GigaChat
        from gigachat.models import Chat, Messages, MessagesRole
    except ImportError as error:
        raise RuntimeError(
            "Библиотека gigachat не установлена. "
            "Проверьте requirements.txt."
        ) from error

    kwargs = {
        "credentials": GIGA_KEY,
        "scope": GIGA_SCOPE,
        "model": GIGA_MODEL,
        "verify_ssl_certs": True,
        "timeout": 60,
    }

    if GIGA_BASE_URL:
        kwargs["base_url"] = GIGA_BASE_URL

    payload = Chat(
        messages=[
            Messages(
                role=MessagesRole.SYSTEM,
                content=system_prompt,
            ),
            Messages(
                role=MessagesRole.USER,
                content=user_prompt,
            ),
        ],
        temperature=0.1,
    )

    last_error = None
    attempts = max(1, retries + 1)

    for attempt in range(attempts):
        try:
            with GigaChat(**kwargs) as client:
                response = client.chat(payload)

            if not response or not getattr(response, "choices", None):
                raise RuntimeError("GigaChat вернул пустой ответ.")

            message = response.choices[0].message
            content = getattr(message, "content", None)

            if not isinstance(content, str) or not content.strip():
                raise RuntimeError(
                    "GigaChat вернул ответ без текстового содержимого."
                )

            return content.strip()

        except Exception as error:
            last_error = error

            if attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))

    raise RuntimeError(
        f"Не удалось получить ответ GigaChat: {last_error}"
    ) from last_error
