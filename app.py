import streamlit as st
import json
import os
import re
import random
import firebase_admin
from firebase_admin import credentials, firestore
from pydantic import BaseModel, Field
from typing import List, Optional

# ==========================================
# 1. ИНИЦИАЛИЗАЦИЯ FIREBASE
# ==========================================
def _get_firebase_cred():
    try:
        if "firebase" in st.secrets:
            cred_dict = dict(st.secrets["firebase"])
            if "private_key" in cred_dict:
                cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            return credentials.Certificate(cred_dict)
    except Exception:
        pass
    if os.path.exists("firebase-key.json"):
        return credentials.Certificate("firebase-key.json")
    return None

try:
    firebase_admin.get_app()
except ValueError:
    cred = _get_firebase_cred()
    if cred is None:
        st.error("Firebase не инициализирован.")
        st.stop()
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ==========================================
# 2. СХЕМА ДЛЯ СТРОГОГО ВЫВОДА (Pydantic)
# ==========================================
class ClaimItem(BaseModel):
    claim: str = Field(description="Текст утверждения из новости")
    status: str = Field(description="Статус: confirmed, contradicted или no_source")
    comment: str = Field(description="Пояснение, почему такой статус")
    url: Optional[str] = Field(default=None, description="Ссылка на источник или null")

class CheckResult(BaseModel):
    results: List[ClaimItem] = Field(description="Список проверенных утверждений")

# ==========================================
# 3. ПРОВЕРКА НОВОСТЕЙ (Structured Output)
# ==========================================
def check_news(text: str):
    try:
        giga_key = st.secrets["GIGA_KEY"]
    except Exception:
        giga_key = os.environ.get("GIGA_KEY")
    
    if not giga_key:
        st.warning("Ключ GigaChat не найден. Работает демо-режим.")
        return check_news_stub(text)

    prompt = f"""Ты — строгий фактчекер. Проанализируй текст ниже.
Выпиши 3-5 проверяемых утверждений и для каждого определи статус.

Текст:
{text}"""

    try:
        from gigachat import GigaChat
        from pydantic import BaseModel, Field
        from typing import List, Optional

        # Схема (можно оставить ту же)
        class ClaimItem(BaseModel):
            claim: str = Field(description="Текст утверждения")
            status: str = Field(description="confirmed, contradicted или no_source")
            comment: str = Field(description="Пояснение")
            url: Optional[str] = Field(default=None, description="Ссылка или null")

        class CheckResult(BaseModel):
            results: List[ClaimItem]

        # ИСПОЛЬЗУЕМ chat_parse — официальный хелпер
        with GigaChat(
            credentials=giga_key,
            model="GigaChat-2-Max",  # Важно: Max поддерживает схему
            scope="GIGACHAT_API_PERS",
            verify_ssl_certs=False,
            base_url="https://api.giga.chat/v2",  # Явно указываем v2
        ) as client:
            completion, parsed = client.chat_parse(
                prompt,
                response_format=CheckResult,
                strict=True,
            )

        # parsed — это уже объект CheckResult
        results = []
        for item in parsed.results:
            url = item.url
            if not url and item.status != "no_source":
                url = f"https://yandex.ru/search/?text={item.claim.replace(' ', '+')}"
            
            results.append({
                "claim": item.claim,
                "status": item.status,
                "comment": item.comment,
                "url": url,
            })

        if not results:
            raise ValueError("Модель вернула пустой список")

        return results

    except Exception as e:
        st.warning(f"GigaChat (structured) error: {e}. Включаю заглушку.")
        return check_news_stub(text)

def check_news(text: str):
    try:
        giga_key = st.secrets["GIGA_KEY"]
    except Exception:
        giga_key = os.environ.get("GIGA_KEY")
    
    if not giga_key:
        st.warning("Ключ GigaChat не найден. Работает демо-режим.")
        return check_news_stub(text)

    prompt = f"""Ты — строгий фактчекер. Проанализируй текст ниже.
Выпиши 3-5 проверяемых утверждений и для каждого определи статус.

Текст:
{text}"""

    try:
        from gigachat import GigaChat
        from gigachat.models import ChatCompletionRequest, ChatMessage, ChatModelOptions, ChatResponseFormat

        # Формируем запрос со строгой схемой (Structured Output)
        request = ChatCompletionRequest(
            model="GigaChat-2",
            messages=[ChatMessage(role="user", content=prompt)],
            model_options=ChatModelOptions(
                response_format=ChatResponseFormat(
                    type="json_schema",
                    schema=CheckResult,
                    strict=True
                )
            )
        )

        with GigaChat(credentials=giga_key, scope="GIGACHAT_API_PERS", verify_ssl_certs=False) as client:
            response = client.chat.create(request)
            raw_content = response.messages[0].content

        # Извлекаем текст (на случай, если SDK вернул список)
        if isinstance(raw_content, list):
            if len(raw_content) > 0 and isinstance(raw_content[0], dict):
                raw = raw_content[0].get("text", "")
            else:
                raw = "".join(str(item) for item in raw_content)
        else:
            raw = str(raw_content)

        # Строгий вывод обычно возвращает чистый JSON, но на всякий случай чистим markdown
        raw = raw.replace("```json", "").replace("```", "").strip()
        
        # Парсим
        data = json.loads(raw)
        
        # Достаем список results (так как схема CheckResult содержит ключ results)
        if isinstance(data, dict) and "results" in data:
            results = data["results"]
        else:
            results = data

        normalized = []
        for r in results:
            claim_text = r.get("claim", "Утверждение без текста")
            status = r.get("status", "no_source")
            if status not in ["confirmed", "contradicted", "no_source"]:
                status = "no_source"
                
            comment = r.get("comment", "Нет деталей.")
            url = r.get("url")
            
            # Если ссылки нет, но она нужна — подставляем поиск
            if not url and status != "no_source":
                search_query = claim_text.replace(" ", "+")
                url = f"https://yandex.ru/search/?text={search_query}"

            normalized.append({
                "claim": claim_text,
                "status": status,
                "comment": comment,
                "url": url
            })
            
        if not normalized:
            raise ValueError("Модель вернула пустой список")

        return normalized

    except Exception as e:
        st.warning(f"Строгий вывод не сработал ({e}). Включаю умную заглушку.")
        return check_news_stub(text)

# ==========================================
# 4. РАБОТА С FIREBASE
# ==========================================
def save_to_firebase(text, results):
    try:
        db.collection("checks").add({
            "text": text,
            "results": results,
            "created_at": firestore.SERVER_TIMESTAMP,
        })
        return True
    except Exception as e:
        st.error(f"Ошибка сохранения: {e}")
        return False

def load_from_firebase(limit=10):
    try:
        docs = db.collection("checks").order_by(
            "created_at", direction=firestore.Query.DESCENDING
        ).limit(limit).stream()
        history = []
        for doc in docs:
            data = doc.to_dict()
            if data.get("created_at"):
                data["created_at"] = data["created_at"].strftime("%Y-%m-%d %H:%M")
            history.append(data)
        return history
    except Exception:
        return []

# ==========================================
# 5. ИНТЕРФЕЙС
# ==========================================
st.set_page_config(page_title="SwampEditor MVP", page_icon="🐸", layout="wide")

st.title("🐸 SwampEditor")
st.caption("AI-ассистент проверки новостей · (GigaChat Structured Output + Firebase)")

with st.sidebar:
    st.header("О проекте")
    st.write("**Команда:** Source? Trust Me Bro")
    st.write("MVP для проверки новостей перед публикацией.")
    st.divider()
    st.info("Данные сохраняются в Firebase Firestore. Проверка текста выполняется через GigaChat API (Structured Output).")

text_input = st.text_area(
    "Вставь черновик новости:",
    height=200,
    placeholder="Например: Мэр заявил, что бюджет вырос на 40%. Встреча прошла 15 марта.",
)

if st.button("Проверить", type="primary"):
    if not text_input.strip():
        st.warning("Сначала вставь текст")
    else:
        with st.spinner("Анализирую..."):
            results = check_news(text_input)
            save_to_firebase(text_input, results)
            st.success("Результат сохранён в облачную базу!")

        confirmed = sum(1 for r in results if r["status"] == "confirmed")
        contradicted = sum(1 for r in results if r["status"] == "contradicted")
        no_source = sum(1 for r in results if r["status"] == "no_source")

        c1, c2, c3 = st.columns(3)
        c1.metric("✅ Подтверждено", confirmed)
        c2.metric("⚠️ Нет источника", no_source)
        c3.metric("❌ Противоречит", contradicted)

        st.divider()

        icons = {"confirmed": "✅", "contradicted": "❌", "no_source": "⚠️"}
        for r in results:
            with st.container(border=True):
                st.markdown(f"### {icons.get(r['status'], '•')} {r['claim']}")
                st.caption(r.get("comment", ""))
                if r.get("url"):
                    st.markdown(f"[Источник]({r['url']})")

st.divider()
st.subheader("📚 Последние проверки (из Firebase)")
history = load_from_firebase()
if not history:
    st.caption("Пока пусто. Проверь первую новость, чтобы она появилась здесь.")
else:
    icons = {"confirmed": "✅", "contradicted": "❌", "no_source": "⚠️"}
    for item in history:
        with st.expander(f"{item.get('created_at', 'Недавно')} — {item['text'][:60]}..."):
            st.write(item["text"])
            for res in item["results"]:
                st.caption(f"{icons.get(res['status'], '•')} {res['claim']}")
