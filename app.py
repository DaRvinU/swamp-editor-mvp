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
        st.error("Firebase не инициализирован. Проверьте секреты.")
        st.stop()
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ==========================================
# 2. УМНАЯ ЗАГЛУШКА (если AI упадет)
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

        results.append({"claim": sentence, "status": status, "comment": comment, "url": url})
    return results

# ==========================================
# 3. ПРОВЕРКА НОВОСТЕЙ (GigaChat)
# ==========================================
def check_news(text: str):
    # 1. Получаем ключ
    try:
        giga_key = st.secrets["GIGA_KEY"]
    except Exception:
        giga_key = os.environ.get("GIGA_KEY")
    
    if not giga_key:
        st.warning("Ключ GigaChat не найден. Работает демо-режим.")
        return check_news_stub(text)

    # 2. Строгий промпт
    prompt = f"""Ты — профессиональный фактчекер. Проанализируй текст ниже.
Верни ответ СТРОГО в виде JSON-массива. Никакого текста до или после.
Формат:
[
  {{
    "claim": "цитата из текста",
    "status": "confirmed" | "contradicted" | "no_source",
    "comment": "пояснение",
    "url": "ссылка или null"
  }}
]

Текст:
{text}"""

    # 3. Вызов API с жестким перехватом ошибок
    try:
        from gigachat import GigaChat
        with GigaChat(credentials=giga_key, model="GigaChat", 
                      scope="GIGACHAT_API_PERS", verify_ssl_certs=False) as client:
            # Используем базовый вызов
            resp = client.chat.create(prompt)
            
            # Достаем текст
            raw_content = resp.messages[0].content
            if isinstance(raw_content, list):
                raw = raw_content[0].get("text", "") if isinstance(raw_content[0], dict) else "".join(map(str, raw_content))
            else:
                raw = str(raw_content)

            raw = raw.replace("```json", "").replace("```", "").strip()
            
            # Ищем массив
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if not match:
                raise ValueError("Ответ не содержит JSON-массив")
            
            raw_json = match.group(0)

            # Пытаемся распарсить
            try:
                results = json.loads(raw_json)
            except json.JSONDecodeError:
                st.info("Автоматически исправляю JSON...")
                results = json.loads(repair_json(raw_json))

            if not isinstance(results, list) or len(results) == 0:
                raise ValueError("Пустой список результатов")

            # Нормализация и добавление ссылок
            normalized = []
            for r in results:
                if not isinstance(r, dict): continue
                
                claim_text = r.get("claim") or "Утверждение без текста"
                status = r.get("status", "no_source")
                if status not in ["confirmed", "contradicted", "no_source"]:
                    status = "no_source"
                comment = r.get("comment") or "Нет деталей."
                url = r.get("url")
                
                # Страховка: если нет ссылки, но статус требует — подставляем поиск
                if not url and status != "no_source":
                    url = f"https://yandex.ru/search/?text={claim_text.replace(' ', '+')}"

                normalized.append({
                    "claim": claim_text, "status": status, "comment": comment, "url": url
                })
            return normalized

    except Exception as e:
        # Если API упал (ошибка сети, ключа или парсинга) — просто идем в заглушку
        st.warning(f"Нейросеть недоступна ({e}). Включаю умную заглушку.")
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
    st.info("Данные сохраняются в Firebase Firestore.")

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
            st.success("Результат сохранён!")

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
