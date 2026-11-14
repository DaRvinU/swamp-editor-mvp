
"""Firebase Firestore: события, утверждения, источники и история проверок."""

import os
from datetime import datetime, timezone

import streamlit as st

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    firebase_admin = None
    credentials = None
    firestore = None


def _get_firebase_cred():
    """Получает Firebase credentials из Secrets или локального файла."""

    if credentials is None:
        return None

    try:
        if "firebase" in st.secrets:
            data = dict(st.secrets["firebase"])

            if "private_key" in data:
                data["private_key"] = data["private_key"].replace(
                    "\\n", "\n"
                )

            return credentials.Certificate(data)
    except Exception:
        pass

    if os.path.exists("firebase-key.json"):
        try:
            return credentials.Certificate("firebase-key.json")
        except Exception:
            return None

    return None


def initialize_firebase():
    """Инициализирует Firestore. Firebase необязателен для запуска."""

    if firebase_admin is None or firestore is None:
        return None

    try:
        try:
            app = firebase_admin.get_app()
        except ValueError:
            credential = _get_firebase_cred()

            if credential is None:
                return None

            app = firebase_admin.initialize_app(credential)

        return firestore.client(app=app)

    except Exception:
        return None


db = initialize_firebase()


def _now():
    return datetime.now(timezone.utc)


def _serialize_document(document):
    """Преобразует документ Firestore в обычный словарь."""

    data = document.to_dict() or {}
    data["id"] = document.id

    for key, value in data.items():
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat()

    return data


# -------------------------
# EVENTS — редакционные события
# -------------------------

def create_event(title, category="Другое", description="", entities=None):
    """Создаёт новое редакционное событие и возвращает его ID."""

    if db is None or not title or not title.strip():
        return None

    try:
        data = {
            "title": title.strip(),
            "category": category,
            "description": description,
            "entities": entities or [],
            "monitoring_enabled": False,
            "created_at": _now(),
            "updated_at": _now(),
        }

        ref = db.collection("events").add(data)
        return ref[1].id

    except Exception:
        return None


def get_event(event_id):
    """Получает событие по ID."""

    if db is None or not event_id:
        return None

    try:
        doc = db.collection("events").document(event_id).get()

        if not doc.exists:
            return None

        return _serialize_document(doc)

    except Exception:
        return None


def list_events(limit=50):
    """Возвращает последние редакционные события."""

    if db is None:
        return []

    try:
        limit = max(1, min(int(limit), 100))

        docs = (
            db.collection("events")
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )

        return [_serialize_document(doc) for doc in docs]

    except Exception:
        return []


def set_event_monitoring(event_id, enabled):
    """Включает или выключает мониторинг события."""

    if db is None or not event_id:
        return False

    try:
        db.collection("events").document(event_id).update({
            "monitoring_enabled": bool(enabled),
            "updated_at": _now(),
        })
        return True

    except Exception:
        return False


# -------------------------
# CLAIMS — утверждения
# -------------------------

def save_claim(event_id, claim):
    """Сохраняет утверждение, связанное с событием."""

    if db is None or not event_id or not isinstance(claim, dict):
        return None

    try:
        data = {
            "event_id": event_id,
            "text": claim.get("claim", claim.get("text", "")),
            "status": claim.get("status", "no_source"),
            "comment": claim.get("comment", ""),
            "last_checked_at": _now(),
            "created_at": _now(),
        }

        if not data["text"]:
            return None

        ref = db.collection("claims").add(data)
        return ref[1].id

    except Exception:
        return None


def get_event_claims(event_id):
    """Получает утверждения конкретного события."""

    if db is None or not event_id:
        return []

    try:
        docs = (
            db.collection("claims")
            .where("event_id", "==", event_id)
            .stream()
        )

        return [_serialize_document(doc) for doc in docs]

    except Exception:
        return []


# -------------------------
# SOURCES — источники
# -------------------------

def save_source(event_id, claim_id, source):
    """Сохраняет источник, связанный с событием и утверждением."""

    if db is None or not event_id or not isinstance(source, dict):
        return None

    url = source.get("url")

    if not url:
        return None

    try:
        data = {
            "event_id": event_id,
            "claim_id": claim_id,
            "title": source.get("title", ""),
            "url": url,
            "snippet": source.get("snippet", ""),
            "source_type": source.get("source_type", "unknown"),
            "found_at": _now(),
        }

        ref = db.collection("sources").add(data)
        return ref[1].id

    except Exception:
        return None


def get_event_sources(event_id):
    """Получает источники конкретного события."""

    if db is None or not event_id:
        return []

    try:
        docs = (
            db.collection("sources")
            .where("event_id", "==", event_id)
            .stream()
        )

        return [_serialize_document(doc) for doc in docs]

    except Exception:
        return []


# -------------------------
# CHECK RUNS — история проверок
# -------------------------

def save_check_run(event_id, mode, claims_count, summary=""):
    """Сохраняет факт запуска проверки."""

    if db is None or not event_id:
        return False

    try:
        db.collection("check_runs").add({
            "event_id": event_id,
            "mode": mode,
            "claims_count": int(claims_count),
            "summary": summary,
            "created_at": _now(),
        })

        return True

    except Exception:
        return False


def get_event_history(event_id, limit=20):
    """Возвращает историю проверок события."""

    if db is None or not event_id:
        return []

    try:
        limit = max(1, min(int(limit), 100))

        docs = (
            db.collection("check_runs")
            .where("event_id", "==", event_id)
            .order_by(
                "created_at",
                direction=firestore.Query.DESCENDING,
            )
            .limit(limit)
            .stream()
        )

        return [_serialize_document(doc) for doc in docs]

    except Exception:
        return []


# -------------------------
# СОВМЕСТИМОСТЬ СО СТАРЫМ APP.PY
# -------------------------

def save_to_firebase(text, results, mode):
    """Сохраняет старую проверку в новой структуре базы."""

    event_id = create_event(
        title=(text or "Проверка новости")[:150],
        category="Не классифицировано",
        description=text or "",
    )

    if not event_id:
        return False

    claims_count = 0

    for result in results or []:
        claim_id = save_claim(event_id, result)

        if not claim_id:
            continue

        claims_count += 1

        for source in result.get("sources", []):
            save_source(event_id, claim_id, source)

        if result.get("url"):
            save_source(
                event_id,
                claim_id,
                {
                    "title": result.get("comment", ""),
                    "url": result["url"],
                    "snippet": "",
                },
            )

    return save_check_run(
        event_id=event_id,
        mode=mode,
        claims_count=claims_count,
        summary=f"Проверено утверждений: {claims_count}",
    )


def load_from_firebase(limit=10):
    """Возвращает историю для старого интерфейса."""

    if db is None:
        return []

    try:
        limit = max(1, min(int(limit), 100))

        docs = (
            db.collection("check_runs")
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )

        history = []

        for doc in docs:
            data = _serialize_document(doc)
            event = get_event(data.get("event_id"))

            data["text"] = (
                event.get("title", "Проверка")
                if event else "Проверка"
            )

            created = data.get("created_at", "")
            data["created_at"] = (
                created[:16].replace("T", " ")
                if isinstance(created, str)
                else "Недавно"
            )

            history.append(data)

        return history

    except Exception:
        return []
