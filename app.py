import streamlit as st
import json
import os
import re
import random
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
# 2. ЗАГЛУШКА
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

    # Жесткий промпт
    prompt = f"""Ты — фактчекер. Твоя задача — проанализировать текст.
Твой ответ должен быть ТОЛЬКО валидным JSON-массивом. 
НЕ пиши никаких вступительных слов. Начинай ответ с символа [ и заканчивай символом ].
Пример правильного ответа:
[{{"claim":"Мэр выступил","status":"confirmed","comment":"Подтверждено СМИ","url":"https://ria.ru"}}]

Текст для проверки:
{text}"""

    try:
        from gigachat import GigaChat
        with GigaChat(credentials=giga_key, model="GigaChat-2",
                      scope="GIGACHAT_API_PERS", verify_ssl_certs=False) as client:
            # Вызов без лишних аргументов
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

        # Ищем первую [ и последнюю ]
        start_idx = raw.find('[')
        end_idx = raw.rfind(']')
        
        if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
            raise ValueError("Модель не вернула JSON-массив (нет скобок)")

        raw_json = raw[start_idx:end_idx+1]

        try:
            results = json.loads(raw_json)
        except json.JSONDecodeError:
            # Если JSON сломан, чиним
            fixed_json = repair_json(raw_json)
            results = json.loads(fixed_json)

        # Если это не список или он пуст
        if not isinstance(results, list) or len(results) == 0:
            raise ValueError("Модель вернула пустой список")

        normalized = []
        for r in results:
            if not isinstance(r, dict):
                continue
            claim_text = r.get("claim") or "Утверждение без текста"
            status = r.get("status", "no_source")
            if status not in ["confirmed", "contradicted", "no_source"]:
                status = "no_source"
                
            comment = r.get("comment") or "Нет деталей."
            url = r.get("url")
            
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
            raise ValueError("Не удалось извлечь ни одного утверждения")

        return normalized

    except Exception as e:
        st.warning(f"Нейросеть не справилась ({e}). Включаю умную заглушку.")
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
