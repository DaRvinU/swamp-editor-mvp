
import os

import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore


def _get_firebase_cred():
    """Получает Firebase credentials из Streamlit Secrets или файла."""

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
        return credentials.Certificate("firebase-key.json")

    return None


def initialize_firebase():
    """Подключает Firebase. Возвращает None, если подключение недоступно."""

    try:
        app = firebase_admin.get_app()
    except ValueError:
        credential = _get_firebase_cred()

        if credential is None:
            return None

        try:
            app = firebase_admin.initialize_app(credential)
        except Exception:
            return None

    try:
        return firestore.client(app=app)
    except Exception:
        return None


db = initialize_firebase()


def save_to_firebase(text, results, mode):
    """Сохраняет проверку. Возвращает False, если Firebase недоступен."""

    if db is None:
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
    """Загружает последние проверки."""

    if db is None:
        return []

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
