
import time

from gigachat import GigaChat

from backend.config import (
    GIGA_KEY,
    GIGA_SCOPE,
    GIGA_MODEL,
    GIGA_BASE_URL,
)


def call_gigachat(
    system_prompt: str,
    user_prompt: str,
    retries: int = 2,
) -> str:
    """Отправляет запрос в GigaChat и возвращает текст ответа."""

    if not GIGA_KEY:
        raise RuntimeError("Не задан ключ GIGA_KEY")

    kwargs = {
        "credentials": GIGA_KEY,
        "scope": GIGA_SCOPE,
        "model": GIGA_MODEL,
        "verify_ssl_certs": False,
        "timeout": 60,
    }

    if GIGA_BASE_URL:
        kwargs["base_url"] = GIGA_BASE_URL

    last_error = None

    for attempt in range(retries + 1):
        try:
            with GigaChat(**kwargs) as client:
                chat_api = getattr(client, "chat")

                # Совместимость с вариантом SDK, где есть chat.create()
                if hasattr(chat_api, "create"):
                    response = chat_api.create(
                        f"{system_prompt}\n\n{user_prompt}"
                    )
                    return response.messages[0].content[0].text

                # Вариант SDK с объектами Chat и Messages
                from gigachat.models import Chat, Messages, MessagesRole

                response = client.chat(
                    Chat(
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
                )

                return response.choices[0].message.content

        except Exception as error:
            last_error = error

            if attempt < retries:
                time.sleep(2 * (attempt + 1))

    raise RuntimeError(
        f"Не удалось получить ответ GigaChat: {last_error}"
    ) from last_error
