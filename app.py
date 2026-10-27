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
# 2. СХЕМА ОТВЕТА ДЛЯ GIGACHAT (Pydantic)
# ==========================================
class ClaimResult(BaseModel):
    claim: str = Field(description="Текст утверждения из новости")
    status: str = Field(description="Статус: confirmed, contradicted или no_source")
    comment: str = Field(description="Короткое пояснение, почему такой статус")
    url: Optional[str] = Field(default=None, description="Ссылка на источник, если есть")

class CheckResponse(BaseModel):
    results: List[ClaimResult] = Field(description="Список проверенных утверждений")

# ==========================================
# 3. ПРОВЕРКА НОВОСТЕЙ
# ==========================================
def check_news_stub(text: str):
    sentences = [s.strip() for s in re.split(r'[.!?]', text) if s.strip()]
    results = []
    for i, sentence in enumerate(sentences[:6]):
        has_number = bool(re.search(r'\d+', sentence))
        has_claim_word = any(w in sentence.lower() for w in ['первый', 'самый', 'вырос', 'упал', 'процент', 'миллион'])
        
        if has_number or has_claim_word:
            status = random.choice(["contradicted", "no_source", "no_source"])
            comment = "Требует проверки: обнаружены числовые данные (демо-режим)."
            url = "https://www.rbc.ru" if status == "contradicted" else None
        else:
            status = "confirmed"
            comment = "Утверждение не содержит явных фактических рисков (демо-режим)."
            url = "https://www.interfax.ru"
            
        if i == 0:
            status = "contradicted"
            comment = "Найдено расхождение с открытыми источниками (демо-режим)."
            url = "https://www.rbc.ru"

        results.append({"claim": sentence, "status": status, "comment": comment, "url": url})
    return results

def check_news(text: str):
    try:
        giga_key = st.secrets["GIGA_KEY"]
    except Exception:
        giga_key = os.environ.get("GIGA_KEY")
    
    if not giga_key:
        st.warning("Ключ GigaChat не найден. Работает демо-режим.")
        return check_news_stub(text)

    prompt = f"""Ты фактчекер новостей. Из текста ниже выпиши 3-5 проверяемых утверждений.
Для каждого определи статус (confirmed, contradicted, no_source) и напиши короткий комментарий.

Текст:
{text}"""

    try:
        from gigachat import GigaChat
        
        with GigaChat(credentials=giga_key, model="GigaChat-2",
                      scope="GIGACHAT_API_PERS", verify_ssl_certs=False) as client:
            
            # Используем chat_parse для автоматической валидации по схеме
            completion, parsed_response = client.chat_parse(
                messages=[{"role": "user", "content": prompt}],
                response_format=CheckResponse,
                strict=True,
                temperature=0
            )
            
            results = []
            for item in parsed_response.results:
                results.append({
                    "claim": item.claim,
                    "status": item.status,
                    "comment": item.comment,
                    "url": item.url
                })
            
            if not results:
                st.warning("GigaChat вернул пустой список. Переключаюсь на демо.")
                return check_news_stub(text)
                
            return results

    except Exception as e:
        st.warning(f"GigaChat недоступен (Ошибка: {e}). Переключаюсь на демо-режим.")
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
        st.error(f"Ошибка сохранения в Firebase: {e}")
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
    except Exception as e:
        st.error(f"Ошибка загрузки из Firebase: {e}")
        return []

# ==========================================
# 5. ИНТЕРФЕЙС
# ==========================================
st.set_page_config(page_title="SwampEditor MVP", page_icon="🐸", layout="wide")

st.title("🐸 SwampEditor")
st.caption("AI-ассистент проверки новостей · (GigaChat + Firebase)")

with st.sidebar:
    st.header("О проекте")
    st.write("**Команда:** Source? Trust Me Bro")
    st.write("MVP для проверки новостей перед публикацией.")
    st.divider()
    st.info("Данные сохраняются в Firebase Firestore. Проверка текста выполняется через GigaChat API.")

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
