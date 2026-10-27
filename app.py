import streamlit as st

# set_page_config должен быть первой командой Streamlit
st.set_page_config(page_title="SwampEditor MVP", page_icon="🐸", layout="wide")

import json
import os
import re
import time
from urllib.parse import quote_plus

import firebase_admin
from firebase_admin import credentials, firestore
from json_repair import repair_json

# ==========================================
# 1. FIREBASE
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
 _cred = _get_firebase_cred()
 if _cred is None:
 st.error("Firebase не инициализирован: проверь секреты [firebase] или firebase-key.json.")
 st.stop()
 firebase_admin.initialize_app(_cred)

db = firestore.client()

# ==========================================
# 2. НАСТРОЙКИ
# ==========================================
def _secret(name, default=None):
 try:
 return st.secrets[name]
 except Exception:
 return os.environ.get(name, default)

GIGA_KEY = _secret("GIGA_KEY")
GIGA_SCOPE = _secret("GIGA_SCOPE", "GIGACHAT_API_PERS")
GIGA_MODEL = _secret("GIGA_MODEL", "GigaChat-2")
MAX_CLAIMS = 5

STATUSES = ["confirmed", "contradicted", "no_source"]
ICONS = {"confirmed": "✅", "contradicted": "❌", "no_source": "⚠️"}

def yandex_link(query: str) -> str:
 return f"https://yandex.ru/search/?text={quote_plus(query)}"

# ==========================================
# 3. GIGACHAT
# ==========================================
def call_gigachat(system_prompt: str, user_prompt: str, retries: int = 2) -> str:
 from gigachat import GigaChat
 from gigachat.models import Chat, Messages, MessagesRole

 last_err = None
 for attempt in range(retries + 1):
 try:
 with GigaChat(
 credentials=GIGA_KEY,
 scope=GIGA_SCOPE,
 model=GIGA_MODEL,
 verify_ssl_certs=False, # у GigaChat сертификаты Минцифры
 timeout=60,
 ) as client:
 response = client.chat(
 Chat(
 messages=[
 Messages(role=MessagesRole.SYSTEM, content=system_prompt),
 Messages(role=MessagesRole.USER, content=user_prompt),
 ],
 temperature=0.1,
 )
 )
 return response.choices[0].message.content
 except Exception as e:
 last_err = e
 time.sleep(2 * (attempt + 1))
 raise last_err

def parse_json_array(raw: str):
 raw = raw.replace("```json", "").replace("```", "").strip()
 match = re.search(r"\[.*\]", raw, re.DOTALL)
 if not match:
 raise ValueError("Модель вернула текст вместо JSON")
 chunk = match.group(0)
 try:
 data = json.loads(chunk)
 except json.JSONDecodeError:
 data = json.loads(repair_json(chunk))
 if not isinstance(data, list) or not data:
 raise ValueError("Модель вернула пустой список")
 return data

# ==========================================
# 4. ПОИСК ИСТОЧНИКОВ (без ключей, через DuckDuckGo)
# ==========================================
def search_evidence(query: str, max_results: int = 4):
 try:
 try:
 from ddgs import DDGS
 except ImportError:
 from duckduckgo_search import DDGS
 with DDGS() as d:
 hits = list(d.text(query, region="ru-ru", max_results=max_results))
 return [
 {
 "title": h.get("title", ""),
 "url": h.get("href", ""),
 "snippet": (h.get("body") or "")[:400],
 }
 for h in hits
 if h.get("href")
 ]
 except Exception:
 return []

# ==========================================
# 5. ПАЙПЛАЙН ПРОВЕРКИ
# ==========================================
EXTRACT_SYSTEM = (
 "Ты — редактор-фактчекер. Отвечай только валидным JSON без пояснений и без markdown."
)

VERIFY_SYSTEM = (
 "Ты — строгий фактчекер. Ты можешь опираться ТОЛЬКО на переданные фрагменты источников. "
 "Не используй собственные знания для подтверждения. Отвечай только валидным JSON."
)

def extract_claims(text: str):
 prompt = (
 f"Выдели из текста до {MAX_CLAIMS} проверяемых утверждений "
 "(цифры, даты, имена, события, цитаты). Каждое утверждение — дословная цитата или краткий пересказ.\n"
 'Верни JSON-массив строк, например: ["утверждение 1", "утверждение 2"].\n\n'
 f"Текст:\n{text}"
 )
 data = parse
