import streamlit as st

import base64
from pathlib import Path

# set_page_config должен быть первой командой Streamlit
st.set_page_config(page_title="SwampEditor MVP", page_icon="🐸", layout="wide")

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"


def get_image_base64(filename):
    path = ASSETS_DIR / filename
    return base64.b64encode(path.read_bytes()).decode()

import re

from backend.config import ICONS
from backend.fact_checker import check_news
from backend.firebase import save_to_firebase, load_from_firebase

# ==========================================
# 11. ИНТЕРФЕЙС
# ==========================================
logo = get_image_base64("swamp_logo.png")
background = get_image_base64("home_bg.png")

st.markdown(f"""
<style>

/* =====================================
   ФОНОВОЕ ИЗОБРАЖЕНИЕ
   ===================================== */

.stApp {{
    background-image:
        linear-gradient(rgba(2, 20, 35, 0.30),
                        rgba(2, 20, 35, 0.40)),
        url("data:image/png;base64,{background}");
    background-size: cover;
    background-position: center;
    background-attachment: fixed;
}}

/* =====================================
   БЕЛЫЙ ТЕКСТ
   ===================================== */

.stApp,
.stApp p,
.stApp h1,
.stApp h2,
.stApp h3,
.stApp h4,
.stApp h5,
.stApp h6,
.stApp li,
.stApp label,
.stApp a,
[data-testid="stMarkdownContainer"] * {{
    color: #FFFFFF !important;
}}

/* Подписи и названия полей */

[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p,
[data-testid="stCaptionContainer"] * {{
    color: #FFFFFF !important;
}}

/* Боковая панель */

[data-testid="stSidebar"],
[data-testid="stSidebar"] * {{
    color: #FFFFFF !important;
}}

/* =====================================
   ТЁМНЫЕ ПОЛУПРОЗРАЧНЫЕ ПОДЛОЖКИ
   ===================================== */

/* Контейнеры с рамками */

[data-testid="stVerticalBlockBorderWrapper"] {{
    background: rgba(2, 20, 35, 0.76) !important;
    border: 1px solid rgba(255, 255, 255, 0.22) !important;
    border-radius: 16px !important;
    padding: 16px !important;
    backdrop-filter: blur(8px);
}}

/* Формы регистрации и личного кабинета */

[data-testid="stForm"] {{
    background: rgba(2, 20, 35, 0.80) !important;
    border: 1px solid rgba(255, 255, 255, 0.22) !important;
    border-radius: 16px !important;
    padding: 20px !important;
    backdrop-filter: blur(8px);
}}

/* Раскрывающиеся блоки */

[data-testid="stExpander"] {{
    background: rgba(2, 20, 35, 0.76) !important;
    border: 1px solid rgba(255, 255, 255, 0.22) !important;
    border-radius: 14px !important;
    backdrop-filter: blur(8px);
}}

[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary p {{
    color: #FFFFFF !important;
}}

/* =====================================
   ПОЛЯ ВВОДА
   ===================================== */

.stApp input,
.stApp textarea {{
    background-color: #FFFFFF !important;
    color: #263238 !important;
    border-radius: 8px !important;
}}

.stApp input::placeholder,
.stApp textarea::placeholder {{
    color: #64748B !important;
}}

/* Выпадающие списки */

[data-baseweb="select"] * {{
    color: #263238 !important;
}}

/* =====================================
   КНОПКИ
   ===================================== */

.stButton button {{
    color: #FFFFFF !important;
}}

/* Тёмный фон боковой панели */
[data-testid="stSidebar"] {{
    background: rgba(2, 20, 35, 0.94) !important;
}}

/* Тёмная информационная плашка */
[data-testid="stSidebar"] [data-testid="stAlert"] {{
    background: rgba(2, 20, 35, 0.82) !important;
    border: 1px solid rgba(255, 255, 255, 0.22) !important;
}}

</style>
""", unsafe_allow_html=True)


# Логотип и название проекта
st.markdown(
    f"""
    <div style="display: flex; align-items: center; gap: 18px; margin-bottom: 25px;">
        <img src="data:image/png;base64,{logo}"
             style="width: 76px; height: 76px; object-fit: contain;">
        <span style="font-size: 38px; font-weight: 700; color: white;">
            SwampEditor
        </span>
    </div>
    """,
    unsafe_allow_html=True
)


st.caption("AI-ассистент проверки новостей · GigaChat + поиск источников + Firebase")

with st.sidebar:
    st.header("О проекте")
    st.write("**Команда:** Source? Trust Me Bro")
    st.write("MVP для проверки новостей перед публикацией.")
    st.divider()
    st.info(
        "1) Система разбивает текст на предложения.\n\n"
        "2) Ищет по ним источники.\n\n"
        "3) GigaChat сверяет утверждения только с найденными фрагментами.\n\n"
        "Финальное решение — за редактором."
    )
    st.divider()
    page = st.radio(
        "РАЗДЕЛЫ",
        ["Проверка новости", "Личный кабинет"],
        key="app_navigation"
    )



# ==========================================
# 12. ЛИЧНЫЙ КАБИНЕТ РЕДАКТОРА
# ==========================================

EDITIONS = [
    "Mash",
    "SHOT",
    "LIFE",
    "Mash Регионы",
    "Five Public",
    "Mash на Мойке",
    "Super",
    "Алёна, блин!",
    "Жизнь",
    "SHOT Проверка",
    "Mash Room",
    "Black Science",
    "GEEKОБРАЗ",
    "Mash на спорте",
    "Gigarama",
    "News Media Special",
    "Другое"
]

if "editor_profile" not in st.session_state:
    st.session_state["editor_profile"] = {
        "name": "",
        "email": "",
        "edition": "Mash",
        "custom_edition": ""
    }

profile = st.session_state["editor_profile"]

# Совместимость с предыдущей версией профиля
profile.setdefault("name", "")
profile.setdefault("email", "")
profile.setdefault("edition", "Mash")
profile.setdefault("custom_edition", "")

if page == "Личный кабинет":

    st.title("Личный кабинет")
    st.caption("Профиль редактора SwampEditor")

    left, right = st.columns([1.2, 0.8])

    with left:
        with st.container(border=True):
            st.subheader("Данные профиля")

            with st.form("profile_form"):

                name = st.text_input(
                    "Имя",
                    value=profile["name"],
                    placeholder="Введите ваше имя"
                )

                email = st.text_input(
                    "Рабочая почта",
                    value=profile["email"],
                    placeholder="example@company.ru"
                )

                current_edition = (
                    profile["edition"]
                    if profile["edition"] in EDITIONS
                    else "Другое"
                )

                edition = st.selectbox(
                    "Редакция",
                    EDITIONS,
                    index=EDITIONS.index(current_edition)
                )

                custom_edition = ""

                if edition == "Другое":
                    custom_edition = st.text_input(
                        "Название редакции",
                        value=profile["custom_edition"],
                        placeholder="Введите название"
                    )

                save = st.form_submit_button(
                    "Сохранить изменения",
                    type="primary",
                    use_container_width=True
                )

                if save:
                    if not name.strip():
                        st.warning("Введите имя.")
                    elif not re.fullmatch(
                        r"[^@\s]+@[^@\s]+\.[^@\s]+",
                        email.strip()
                    ):
                        st.warning("Введите корректную почту.")
                    elif edition == "Другое" and not custom_edition.strip():
                        st.warning("Укажите название редакции.")
                    else:
                        st.session_state["editor_profile"] = {
                            "name": name.strip(),
                            "email": email.strip(),
                            "edition": edition,
                            "custom_edition": custom_edition.strip()
                        }
                        st.success("Профиль успешно обновлён!")

    with right:
        with st.container(border=True):
            st.subheader("Мой профиль")

            st.image("frog_cabinet.png", width=180)

            st.markdown(
                f"### {profile['name'] or 'Новый редактор'}"
            )

            st.caption(profile["email"] or "Почта не указана")

            display_edition = (
                profile["custom_edition"]
                if profile["edition"] == "Другое"
                else profile["edition"]
            )

            st.divider()

            st.markdown("**Редакция**")
            st.write(display_edition)

            st.divider()
            st.caption("SwampEditor · Editor Workspace")

    st.stop()

# ======================================
# Конец моего кода
# =======================================

text_input = st.text_area(
    "Вставь черновик новости:",
    height=200,
    placeholder="Например: Мэр заявил, что бюджет вырос на 40%. Встреча прошла 15 марта.",
)

if st.button("Проверить", type="primary"):
    if not text_input.strip():
        st.warning("Сначала вставь текст")
    else:
        with st.spinner("Разбиваю текст, ищу источники, сверяю..."):
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

        if contradicted > 0:
            st.error("❌ Общий вывод: в новости есть утверждения, противоречащие источникам.")
        elif results and confirmed == len(results):
            st.success("✅ Общий вывод: все утверждения подтверждены найденными источниками.")
        else:
            st.warning("⚠️ Общий вывод: часть утверждений не удалось подтвердить — нужна проверка редактора.")

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
st.subheader("Последние проверки (из Firebase)")

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
