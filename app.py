import streamlit as st
import json
import os
import re
import random
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# ==========================================
# 1. ИНИЦИАЛИЗАЦИЯ FIREBASE (безопасно для повторных запусков)
# ==========================================
def _get_firebase_cred():
    """Возвращает credentials: сначала из secrets (Streamlit Cloud), потом из файла (Colab)."""
    # 1) Streamlit Cloud / Hugging Face
    try:
        if "firebase" in st.secrets:
            cred_dict = dict(st.secrets["firebase"])
            if "private_key" in cred_dict:
                cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
            return credentials.Certificate(cred_dict)
    except Exception:
        pass

    # 2) Локальный файл (Colab)
    if os.path.exists("firebase-key.json"):
        return credentials.Certificate("firebase-key.json")

    return None

# Инициализируем только если приложение ещё не создано
try:
    firebase_admin.get_app()
except ValueError:
    cred = _get_firebase_cred()
    if cred is None:
        st.error("Firebase не инициализирован: нет ни секретов, ни файла firebase-key.json")
        st.stop()
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ==========================================
# 2. ФУНКЦИЯ ПРОВЕРКИ (GIGACHAT + ЗАГЛУШКА)
# ==========================================
def check_news_stub(text: str):
    """Заглушка, если API не доступен."""
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

        results.append({
            "claim": sentence, "status": status, "comment": comment, "url": url
        })
    return results

def check_news(text: str):
    """Реальная проверка через GigaChat API с откатом на заглушку."""
    # Ищем ключ в секретах или окружении
    try:
        giga_key = st.secrets["GIGA_KEY"]
    except Exception:
        giga_key = os.environ.get("GIGA_KEY")
    
    if not giga_key:
        st.warning("Ключ GigaChat не найден. Работает демо-режим.")
        return check_news_stub(text)

    prompt = f"""Ты фактчекер новостей. Из текста ниже выпиши 3-5 проверяемых утверждений.
Верни ТОЛЬКО JSON-массив без пояснений, строго такого вида:
[{{"claim":"текст утверждения","status":"confirmed|contradicted|no_source","comment":"1-2 предложения почему","url":null}}]

Текст:
{text}"""

    try:
        from gigachat import GigaChat
        with GigaChat(credentials=giga_key, model="GigaChat-2",
                      scope="GIGACHAT_API_PERS", verify_ssl_certs=False) as client:
            resp = client.chat.create({"messages":[{"role":"user","content":prompt}], "temperature":0})
            raw = resp.messages[0].content

        raw = raw.replace("```json", "").replace("```", "").strip()
        results = json.loads(raw)

        if isinstance(results, dict):
            results = results.get("results", results.get("claims", []))

        normalized = []
        for r in results:
            normalized.append({
                "claim": r.get("claim", "Без названия"),
                "status": r.get("status", "no_source"),
                "comment": r.get("comment", "Нет комментария"),
                "url": r.get("url")
            })
        return normalized

    except Exception as e:
        st.warning(f"GigaChat недоступен (Ошибка: {e}). Переключаюсь на демо-режим.")
        return check_news_stub(text)

# ==========================================
# 3. РАБОТА С FIREBASE
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
# 4. ИНТЕРФЕЙС
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
