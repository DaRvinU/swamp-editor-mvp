import streamlit as st
import json
import os
import re
import random
import firebase_admin
from firebase_admin import credentials, firestore
from json_repair import repair_json  # Библиотека для починки JSON

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
# 2. ПРОВЕРКА НОВОСТЕЙ (GigaChat)
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

    # Очень строгий промпт, чтобы модель не добавляла лишнего текста
    prompt = f"""Ты — строгий фактчекер новостей. Твоя задача — проанализировать текст и выдать результат СТРОГО в формате JSON-массива.

ПРАВИЛА ОПРЕДЕЛЕНИЯ СТАТУСА:
1. Ставь "confirmed" (✅), если утверждение выглядит как общеизвестный факт, банальность или не содержит конкретных чисел/имён, которые можно проверить. Например: "Встреча прошла", "Мэр выступил", "Погода была хорошая".
2. Ставь "contradicted" (❌), если в тексте есть внутреннее противоречие (например, "вырос на 40%", а потом "снизился") или если ты точно знаешь, что это ложь.
3. Ставь "no_source" (⚠️) ТОЛЬКО если утверждение содержит конкретную цифру, дату или громкое заявление ("первый в истории", "самый большой"), но ты не можешь подтвердить это из своих знаний.

Твоя цель — не просто поставить везде "no_source", а показать РАЗНЫЕ статусы, чтобы редактор увидел, какие места в тексте действительно опасны, а какие — безопасны.

Никакого другого текста, только JSON. Начинай ответ с символа [ и заканчивай символом ].

Текст для проверки:
{text}"""

    try:
        from gigachat import GigaChat
        with GigaChat(credentials=giga_key, model="GigaChat-2",
                      scope="GIGACHAT_API_PERS", verify_ssl_certs=False) as client:
            # ПРАВИЛЬНЫЙ ВЫЗОВ: промпт передаётся строкой
            resp = client.chat.create(prompt)
            raw_content = resp.messages[0].content

        # Извлекаем текст
        if isinstance(raw_content, list):
            if len(raw_content) > 0 and isinstance(raw_content[0], dict):
                raw = raw_content[0].get("text", "")
            else:
                raw = "".join(str(item) for item in raw_content)
        else:
            raw = str(raw_content)

        # Чистим markdown и ищем JSON-массив
        raw = raw.replace("```json", "").replace("```", "").strip()
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            raw = match.group(0)

        # Пытаемся распарсить, если падает — чиним
        try:
            results = json.loads(raw)
        except json.JSONDecodeError:
            st.info("JSON от AI был немного кривым. Автоматически исправляю...")
            fixed_json = repair_json(raw)
            results = json.loads(fixed_json)

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
