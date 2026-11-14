

"""Необязательное подключение Firebase для истории проверок."""

import os

import streamlit as st

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    firebase_admin = None
    credentials = None
    firestore = None


def _get_firebase_cred():
    """Получает Firebase credentials из Streamlit Secrets или файла."""

    if credentials is None:
        return None

    try:
        if "firebase" in st.secrets:
            cred_dict = dict(st.secrets["firebase"])

            if "private_key" in cred_dict:
                cred_dict["private_key"] = (
                    cred_dict["private_key"].replace("\\n", "\n")
                )

            return credentials.Certificate(cred_dict)
    except Exception:
        pass

    if os.path.exists("firebase-key.json"):
        try:
            return credentials.Certificate("firebase-key.json")
        except Exception:
            return None

    return None


def initialize_firebase():
    """Подключает Firebase или возвращает None, если он недоступен."""

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


def save_to_firebase(text, results, mode):
    """Сохраняет проверку. Возвращает False при недоступности Firebase."""

    if db is None or firestore is None:
        return False

    try:
        db.collection("checks").add({
            "text": text,
            "results": results,
            "mode": mode,
            "created_at": firestore.SERVER_TIMESTAMP,
        })
        return True

    except Exception:
        return False


def load_from_firebase(limit=10):
    """Загружает последние проверки из истории."""

    if db is None or firestore is None:
        return []

    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        limit = 10

    try:
        documents = (
            db.collection("checks")
            .order_by(
                "created_at",
                direction=firestore.Query.DESCENDING,
            )
            .limit(limit)
            .stream()
        )

        history = []

        for document in documents:
            data = document.to_dict() or {}
            created = data.get("created_at")

            data["created_at"] = (
                created.strftime("%Y-%m-%d %H:%M")
                if hasattr(created, "strftime")
                else "Недавно"
            )

            history.append(data)

        return history

    except Exception:
        return []
