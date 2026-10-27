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
                verify_ssl_certs=False,
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

# ==========================================
# 4. ПОИСК ИСТОЧНИКОВ (DuckDuckGo, без ключей)
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
# 5. ПАЙПЛАЙН ПРОВЕРКИ (НОВЫЕ ФУНКЦИИ)
# ==========================================
EXTRACT_SYSTEM = "Ты — редактор-фактчекер. Отвечай только валидным JSON без пояснений и без markdown."
VERIFY_SYSTEM = (
    "Ты — строгий фактчекер. Опирайся ТОЛЬКО на переданные фрагменты источников, "
    "не используй собственные знания для подтверждения. Отвечай только валидным JSON."
)

def parse_json_array(raw):
    raw = (raw or "").replace("```json", "").replace("```", "").strip()
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        raise ValueError("Модель вернула текст вместо JSON")
    chunk = match.group(0)
    try:
        data = json.loads(chunk)
    except json.JSONDecodeError:
        data = json.loads(repair_json(chunk))
    if not isinstance(data, list):
        raise ValueError("Модель вернула не список")
    return data

def extract_claims(text):
    prompt = (
        f"Выдели из текста до {MAX_CLAIMS} проверяемых утверждений "
        "(цифры, даты, имена, события, цитаты).\n"
        "Если текст короткий — верни его целиком как одно утверждение.\n"
        'Верни JSON-массив строк, например: ["утверждение 1", "утверждение 2"].\n\n'
        f"Текст:\n{text}"
    )
    claims = []
    for attempt in range(2):
        data = parse_json_array(call_gigachat(EXTRACT_SYSTEM, prompt))
        for item in data:
            if isinstance(item, str):
                claims.append(item.strip())
            elif isinstance(item, dict) and item.get("claim"):
                claims.append(str(item["claim"]).strip())
        claims = [c for c in claims if c][:MAX_CLAIMS]
        if claims:
            break

    if not claims:
        claims = [s.strip() for s in re.split(r"[.!?\n]", text) if len(s.strip()) > 3][:MAX_CLAIMS]
    if not claims:
        raise ValueError("Не удалось выделить утверждения")
    return claims

def verify_claims(claims, evidence):
    blocks = []
    for i, claim in enumerate(claims):
        sources = evidence[i]
        if sources:
            src_text = "\n".join(
                f" [{j}] {s['title']} — {s['snippet']}" for j, s in enumerate(sources)
            )
        else:
            src_text = " (источники не найдены)"
        blocks.append(f"Утверждение {i}: {claim}\nИсточники:\n{src_text}")

    prompt = (
        "Сопоставь каждое утверждение с переданными фрагментами источников.\n"
        "Верни JSON-массив, по одному объекту на утверждение:\n"
        '[{"id": 0, "status": "confirmed" | "contradicted" | "no_source", '
        '"comment": "1-2 предложения", "source": номер источника или null}]\n'
        "ПРАВИЛА:\n"
        "- confirmed — только если фрагмент прямо подтверждает утверждение.\n"
        "- contradicted — только если фрагмент прямо ему противоречит.\n"
        "- Если данных недостаточно или источников нет — no_source.\n"
        "- Поле source — ТОЛЬКО число, номер источника из списка, например 1.\n\n"
        + "\n\n".join(blocks)
    )

    verdicts = []
    for attempt in range(2):
        verdicts = parse_json_array(call_gigachat(VERIFY_SYSTEM, prompt))
        if verdicts:
            break
    return verdicts

# ==========================================
# 5a. СОВМЕСТИМЫЙ ВЫЗОВ GIGACHAT
# ==========================================
GIGA_BASE_URL = _secret("GIGA_BASE_URL") # необязательно, например https://api.giga.chat/v1

def call_gigachat(system_prompt: str, user_prompt: str, retries: int = 2) -> str:
    from gigachat import GigaChat

    kwargs = {
        "credentials": GIGA_KEY,
        "scope": GIGA_SCOPE,
        "model": GIGA_MODEL,
        "verify_ssl_certs": False,
    }
    if GIGA_BASE_URL:
        kwargs["base_url"] = GIGA_BASE_URL

    last_err = None
    for attempt in range(retries + 1):
        try:
            with GigaChat(**kwargs) as client:
                chat_api = getattr(client, "chat")

                # Новый SDK — как в документации Сбера
                if hasattr(chat_api, "create"):
                    response = chat_api.create(f"{system_prompt}\n\n{user_prompt}")
                    return response.messages[0].content[0].text

                # Старый SDK
                from gigachat.models import Chat, Messages, MessagesRole
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
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise last_err

# ==========================================
# 5b. ДЕМО-РЕЖИМ (без AI, ничего не подтверждает)
# ==========================================
def check_news_stub(text: str):
    sentences = [s.strip() for s in re.split(r"[.!?]", text) if s.strip()]
    risky_words = ["первый", "самый", "вырос", "упал", "процент", "миллион", "умер", "заявил"]
    results = []
    for s in sentences:
        risky = bool(re.search(r"\d+", s)) or any(w in s.lower() for w in risky_words)
        if risky:
            results.append(
                {
                    "claim": s,
                    "status": "no_source",
                    "comment": "Демо-режим: в предложении есть цифры или громкое заявление — нужна проверка.",
                    "url": None,
                    "search_url": yandex_link(s),
                    "sources": [],
                }
            )
    if not results and sentences:
        results.append(
            {
                "claim": sentences[0],
                "status": "no_source",
                "comment": "Демо-режим: явных рисков не найдено, но без AI утверждение не проверено.",
                "url": None,
                "search_url": yandex_link(sentences[0]),
                "sources": [],
            }
        )
    return results

# ==========================================
# 6. ОСНОВНАЯ ПРОВЕРКА (ОСТАВЛЕНА КАК ЕСТЬ)
# ==========================================
STATUS_ALIASES = [
    ("no_source", "no_source"),
    ("no source", "no_source"),
    ("нет источник", "no_source"),
    ("не подтвержд", "no_source"),
    ("unconfirmed", "no_source"),
    ("not confirmed", "no_source"),
    ("contradicted", "contradicted"),
    ("противоречит", "contradicted"),
    ("опроверг", "contradicted"),
    ("неверно", "contradicted"),
    ("false", "contradicted"),
    ("confirmed", "confirmed"),
    ("подтвержд", "confirmed"),
    ("верно", "confirmed"),
    ("true", "confirmed"),
]

def normalize_status(value):
    s = str(value or "").strip().lower().replace("-", "_")
    for key, status in STATUS_ALIASES:
        if key in s:
            return status
    return "no_source"

def parse_source_index(value, sources):
    if value is None or not sources:
        return None
    if isinstance(value, list):
        if not value:
            return None
        value = value[0]
    if isinstance(value, (int, float)):
        idx = int(value)
    else:
        text = str(value).strip()
        for i, s in enumerate(sources):
            if s.get("url") and s["url"] in text:
                return i
        m = re.search(r"\d+", text)
        if not m:
            return None
        idx = int(m.group())
    if 0 <= idx < len(sources):
        return idx
    if idx == len(sources):
        return idx - 1
    return None

def best_matching_source(claim, sources):
    words = set(re.findall(r"\w{4,}", claim.lower()))
    best, best_score = None, 0
    for i, s in enumerate(sources):
        text = (s.get("title", "") + " " + s.get("snippet", "")).lower()
        score = sum(1 for w in words if w[:5] in text)
        if score > best_score:
            best, best_score = i, score
    return best

def check_news(text):
    if not GIGA_KEY:
        st.warning("Ключ GIGA_KEY не найден в Secrets — работает демо-режим без AI.")
        return check_news_stub(text), "demo"

    try:
        claims = extract_claims(text)
        evidence = [search_evidence(claim) for claim in claims]
        verdicts = verify_claims(claims, evidence)

        by_id = {}
        for pos, v in enumerate(verdicts):
            if not isinstance(v, dict):
                continue
            try:
                by_id[int(re.search(r"\d+", str(v.get("id"))).group())] = v
            except Exception:
                by_id.setdefault(pos, v)

        results = []
        for i, claim in enumerate(claims):
            v = by_id.get(i, {})
            sources = evidence[i]
            status = normalize_status(v.get("status"))

            idx = parse_source_index(v.get("source"), sources)
            if idx is None and status != "no_source":
                idx = best_matching_source(claim, sources)

            url = sources[idx]["url"] if idx is not None else None

            if status != "no_source" and not url:
                status = "no_source"

            comment = str(v.get("comment") or "").strip()
            if not comment:
                comment = (
                    "Источники по утверждению не найдены."
                    if not sources
                    else "В найденных фрагментах недостаточно данных для вывода."
                )

            results.append({
                "claim": claim,
                "status": status,
                "comment": comment,
                "url": url,
                "search_url": yandex_link(claim),
                "sources": sources,
                "raw_verdict": json.dumps(v, ensure_ascii=False),
            })
        return results, "ai"

    except Exception as e:
        st.error(f"Ошибка GigaChat: {type(e).__name__}: {e}")
        st.caption("Показан демо-режим без AI. Проверьте GIGA_KEY, GIGA_SCOPE, GIGA_MODEL и версию gigachat.")
        return check_news_stub(text), "demo"

# ==========================================
# 7. FIREBASE: СОХРАНЕНИЕ И ИСТОРИЯ
# ==========================================
def save_to_firebase(text, results, mode):
    try:
        db.collection("checks").add(
            {
                "text": text,
                "results": results,
                "mode": mode,
                "created_at": firestore.SERVER_TIMESTAMP,
            }
        )
        return True
    except Exception as e:
        st.warning(f"Не удалось сохранить проверку: {e}")
        return False

def load_from_firebase(limit=10):
    try:
        docs = (
            db.collection("checks")
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        history = []
        for doc in docs:
            data = doc.to_dict() or {}
            created = data.get("created_at")
            data["created_at"] = created.strftime("%Y-%m-%d %H:%M") if hasattr(created, "strftime") else "Недавно"
            history.append(data)
        return history
    except Exception:
        return []

# ==========================================
# 8. ИНТЕРФЕЙС
# ==========================================
st.title("🐸 SwampEditor")
st.caption("AI-ассистент проверки новостей · GigaChat + поиск источников + Firebase")

with st.sidebar:
    st.header("О проекте")
    st.write("**Команда:** Source? Trust Me Bro")
    st.write("MVP для проверки новостей перед публикацией.")
    st.divider()
    st.info(
        "1) GigaChat выделяет проверяемые утверждения.\n\n"
        "2) Система ищет по ним источники.\n\n"
        "3) GigaChat сверяет утверждения только с найденными фрагментами.\n\n"
        "Финальное решение — за редактором."
    )

text_input = st.text_area(
    "Вставь черновик новости:",
    height=200,
    placeholder="Например: Мэр заявил, что бюджет вырос на 40%. Встреча прошла 15 марта.",
)

if st.button("Проверить", type="primary"):
    if not text_input.strip():
        st.warning("Сначала вставь текст")
    else:
        with st.spinner("Выделяю утверждения, ищу источники, сверяю..."):
            results, mode = check_news(text_input)

        if mode == "demo":
            st.warning("⚠️ Демо-режим: результат получен без AI и не является фактчекингом.")
        else:
            st.success("Проверка выполнена с помощью GigaChat и найденных источников.")

        if save_to_firebase(text_input, results, mode):
            st.caption("Результат сохранён в Firebase.")

        confirmed = sum(r["status"] == "confirmed" for r in results)
        contradicted = sum(r["status"] == "contradicted" for r in results)
        no_source = sum(r["status"] == "no_source" for r in results)

        c1, c2, c3 = st.columns(3)
        c1.metric("✅ Подтверждено", confirmed)
        c2.metric("⚠️ Нет источника", no_source)
        c3.metric("❌ Противоречит", contradicted)

        st.divider()

        for r in results:
            with st.container(border=True):
                st.markdown(f"### {ICONS.get(r['status'], '•')} {r['claim']}")
                st.write(r.get("comment", ""))

                links = []
                if r.get("url"):
                    links.append(f"[Источник]({r['url']})")
                if r.get("search_url"):
                    links.append(f"[Искать в Яндексе]({r['search_url']})")
                if links:
                    st.markdown(" · ".join(links))

                if r.get("sources"):
                    with st.expander(f"Найденные материалы ({len(r['sources'])})"):
                        for s in r["sources"]:
                            st.markdown(f"**[{s['title'] or s['url']}]({s['url']})**")
                            st.caption(s.get("snippet", ""))

st.divider()
st.subheader("📚 Последние проверки (из Firebase)")

history = load_from_firebase()
if not history:
    st.caption("Пока пусто. Проверь первую новость, чтобы она появилась здесь.")
else:
    for item in history:
        text = item.get("text", "")
        mode_label = " · демо" if item.get("mode") == "demo" else ""
        with st.expander(f"{item.get('created_at', 'Недавно')}{mode_label} — {text[:60]}..."):
            st.write(text)
            for res in item.get("results", []):
                st.caption(f"{ICONS.get(res.get('status'), '•')} {res.get('claim', '')}")
