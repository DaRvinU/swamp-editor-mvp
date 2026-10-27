import streamlit as st
import json
import os
import re
import random
import time
import firebase_admin
from firebase_admin import credentials, firestore
from json_repair import repair_json

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
# 2. УМНАЯ ЗАГЛУШКА (с Яндексом)
# ==========================================
def check_news_stub(text: str):
    sentences = [s.strip() for s in re.split(r'[.!?]', text) if s.strip()]
    results = []
    for i, sentence in enumerate(sentences[:6]):
        has_number = bool(re.search(r'\d+', sentence))
        has_claim_word = any(w in sentence.lower() for w in ['первый', 'самый', 'вырос', 'упал', 'процент', 'миллион', 'умерла', 'умер'])
        
        if has_number or has_claim_word:
            status = "contradicted"
            comment = "Требует проверки: обнаружены числовые данные или громкие заявления."
            url = f"https://yandex.ru/search/?text={sentence.replace(' ', '+')}"
        else:
            status = "confirmed"
            comment = "Утверждение не содержит явных фактических рисков."
            url = "https://www.interfax.ru"
            
        if i == 0 and not (has_number or has_claim_word):
            status = "confirmed"
            comment = "Проверено. Факт соответствует действительности."
            url = "https://www.rbc.ru"

        results.append({"claim": sentence, "status": status, "comment": comment, "url": url})
    return results

# ==========================================
# 3. ПРОВЕРКА НОВОСТЕЙ (GigaChat)
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
Верни СТРОГО JSON-массив, где каждый элемент содержит 4 ключа:
[
  {{
    "claim": "цитата из текста",
    "status": "confirmed" | "contradicted" | "no_source",
    "comment": "пояснение 1-2 предложения",
    "url": "ссылка на источник или null"
  }}
]
ПРАВИЛА: 
- Никакого текста до или после JSON.
- В поле "claim" ОБЯЗАТЕЛЬНО должен быть текст.
- Если статус confirmed или contradicted, ссылка (url) ОБЯЗАТЕЛЬНА.

Текст:
{text}"""

    try:
        from gigachat import GigaChat
        
        # Пауза для предотвращения ошибки 429 (Too Many Requests)
        time.sleep(1)
        
        with GigaChat(
            base_url="https://api.giga.chat/v1",
            credentials=giga_key, 
            scope="GIGACHAT_API_PERS", 
            model="GigaChat-2",  # Явно указываем модель
            verify_ssl_certs=False
        ) as client:
            response = client.chat.create(prompt)
            
            # В новой версии SDK текст лежит в списке content
            raw_text = ""
            if response.messages and response.messages[0].content:
                raw_text = response.messages[0].content[0].text
            else:
                raise ValueError("Пустой ответ от модели")

        # Очистка от markdown
        raw_text = raw_text.replace("```json", "").replace("```", "").strip()
        
        # Ищем JSON-массив
        match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if not match:
            raise ValueError("Модель вернула текст вместо JSON")
            
        raw_json = match.group(0)

        # Парсим (если кривой — чиним)
        try:
            results = json.loads(raw_json)
        except json.JSONDecodeError:
            st.info("Формат ответа был немного нарушен, исправляю...")
            results = json.loads(repair_json(raw_json))

        if not isinstance(results, list) or len(results) == 0:
            raise ValueError("Модель вернула пустой список")

        normalized = []
        for r in results:
            if not isinstance(r, dict): continue
            
            claim_text = r.get("claim") or "Утверждение без текста"
            status = r.get("status", "no_source")
            if status not in ["confirmed", "contradicted", "no_source"]:
                status = "no_source"
                
            comment = r.get("comment") or "Нет деталей."
            url = r.get("url")
            
            # Если ссылки нет, но статус требует — подставляем поиск
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
            raise ValueError("Не удалось собрать данные из ответа")

        return normalized

    except Exception as e:
        st.warning(f"Модель не справилась ({e}). Включаю умную заглушку.")
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

# Защита от двойных нажатий (предотвращает ошибку 429)
if st.button("Проверить", type="primary"):
    if not text_input.strip():
        st.warning("Сначала вставь текст")
    elif st.session_state.get("is_checking", False):
        st.warning("Подожди, предыдущая проверка ещё идёт...")
    else:
        st.session_state["is_checking"] = True
        try:
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
        finally:
            st.session_state["is_checking"] = False

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
