
import json
import re

from json_repair import repair_json

from backend.config import GIGA_KEY, MAX_CLAIMS, yandex_link
from backend.gigachat import call_gigachat
from backend.search import search_evidence


EXTRACT_SYSTEM = (
    "Ты — редактор-фактчекер. "
    "Отвечай только валидным JSON без пояснений и markdown."
)

VERIFY_SYSTEM = (
    "Ты — строгий фактчекер. Опирайся только на переданные "
    "фрагменты источников. Не используй собственные знания "
    "для подтверждения. Отвечай только валидным JSON."
)


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


def parse_json_array(raw):
    """Извлекает JSON-массив из ответа модели."""

    raw = (raw or "").replace("```json", "")
    raw = raw.replace("```", "").strip()

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
    """Разбивает текст на отдельные проверяемые утверждения."""

    if not isinstance(text, str) or not text.strip():
        return []

    parts = re.split(r"(?<=[.!?])\s+|\n+", text)

    claims = []

    for part in parts:
        part = part.strip(" .!?\t")

        if len(part.split()) >= 3:
            claims.append(part[:300])

    if not claims:
        claims = [text.strip()[:300]]

    return claims[:MAX_CLAIMS]


def verify_claims(claims, evidence):
    """Сверяет утверждения с найденными фрагментами источников."""

    if not claims:
        return []

    blocks = []

    for index, claim in enumerate(claims):
        sources = (
            evidence[index]
            if index < len(evidence)
            else []
        )

        if sources:
            source_text = "\n".join(
                f"[{j}] {source.get('title', '')} — "
                f"{source.get('snippet', '')}"
                for j, source in enumerate(sources)
            )
        else:
            source_text = "(источники не найдены)"

        blocks.append(
            f"Утверждение {index}: {claim}\n"
            f"Источники:\n{source_text}"
        )

    prompt = (
        "Сопоставь каждое утверждение с переданными фрагментами источников.\n"
        "Верни JSON-массив, по одному объекту на утверждение:\n"
        '[{"id": 0, "status": "confirmed" | "contradicted" | "no_source", '
        '"comment": "1-2 предложения", "source": 0 или null}]\n\n'
        "ВАЖНО: номера источников начинаются с нуля. "
        "Используй только номера в квадратных скобках перед источниками.\n\n"
        "Правила проверки:\n"
        "1. Убедись, что источник относится к тому же событию.\n"
        "2. Сравни даты, места, числа, участников и другие важные детали.\n"
        "3. confirmed — источник о том же событии и подтверждает утверждение.\n"
        "4. contradicted — источник о том же событии, но прямо противоречит "
        "проверяемой детали.\n"
        "5. no_source — данных недостаточно или источник относится к другому событию.\n"
        "6. Не используй собственные знания вместо источников.\n"
        "7. Если подходящего источника нет, укажи source: null "
        "и status: no_source.\n"
        "8. Не выбирай источник только из-за совпадения отдельных слов.\n"
        "9. Не придумывай доказательства и цитаты.\n\n"
        + "\n\n".join(blocks)
    )

    response = call_gigachat(VERIFY_SYSTEM, prompt)

    verdicts = parse_json_array(response)

    return verdicts


def check_news_stub(text):
    """Демонстрационный режим без настоящего AI-фактчекинга."""

    sentences = [
        sentence.strip()
        for sentence in re.split(r"[.!?]", text)
        if sentence.strip()
    ]

    risky_words = [
        "первый",
        "самый",
        "вырос",
        "упал",
        "процент",
        "миллион",
        "умер",
        "заявил",
    ]

    results = []

    for sentence in sentences:
        risky = bool(re.search(r"\d+", sentence)) or any(
            word in sentence.lower()
            for word in risky_words
        )

        if risky:
            results.append({
                "claim": sentence,
                "status": "no_source",
                "comment": (
                    "Демо-режим: в предложении есть цифры или "
                    "громкое заявление — нужна проверка."
                ),
                "url": None,
                "search_url": yandex_link(sentence),
                "sources": [],
            })

    if not results and sentences:
        sentence = sentences[0]

        results.append({
            "claim": sentence,
            "status": "no_source",
            "comment": (
                "Демо-режим: без AI это утверждение не проверено."
            ),
            "url": None,
            "search_url": yandex_link(sentence),
            "sources": [],
        })

    return results


def normalize_status(value):
    """Приводит разные варианты ответа модели к трём статусам."""

    status_text = str(value or "").strip().lower().replace("-", "_")

    for key, status in STATUS_ALIASES:
        if key in status_text:
            return status

    return "no_source"


def parse_source_index(value, sources):
    """Проверяет номер источника. Нумерация начинается с нуля."""

    if value is None or not sources:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        index = value

    elif isinstance(value, str):
        text = value.strip()

        for index, source in enumerate(sources):
            if source.get("url") and source["url"] == text:
                return index

        if not re.fullmatch(r"\d+", text):
            return None

        index = int(text)

    else:
        return None

    if 0 <= index < len(sources):
        return index

    return None


def best_matching_source(claim, sources):
    """Вспомогательный поиск похожего источника по словам."""

    words = set(re.findall(r"\w{4,}", claim.lower()))

    best_index = None
    best_score = 0

    for index, source in enumerate(sources):
        source_text = (
            source.get("title", "")
            + " "
            + source.get("snippet", "")
        ).lower()

        score = sum(
            1 for word in words if word[:5] in source_text
        )

        if score > best_score:
            best_index = index
            best_score = score

    return best_index


def check_news(text):
    """Полный процесс проверки новости."""

    if not isinstance(text, str) or not text.strip():
        return [], "demo"

    if not GIGA_KEY:
        return check_news_stub(text), "demo"

    try:
        claims = extract_claims(text)

        if not claims:
            return [], "demo"

        evidence = [
            search_evidence(claim)
            for claim in claims
        ]

        verdicts = verify_claims(claims, evidence)

        by_id = {}

        for position, verdict in enumerate(verdicts):
            if not isinstance(verdict, dict):
                continue

            raw_id = verdict.get("id")

            if isinstance(raw_id, int) and not isinstance(raw_id, bool):
                claim_id = raw_id
            elif isinstance(raw_id, str) and raw_id.isdigit():
                claim_id = int(raw_id)
            else:
                claim_id = position

            if 0 <= claim_id < len(claims):
                by_id.setdefault(claim_id, verdict)

        results = []

        for index, claim in enumerate(claims):
            verdict = by_id.get(index, {})

            sources = evidence[index]

            status = normalize_status(
                verdict.get("status")
            )

            source_index = parse_source_index(
                verdict.get("source"),
                sources,
            )

            # Без конкретного источника нельзя считать утверждение
            # подтверждённым или опровергнутым.
            if status in ("confirmed", "contradicted"):
                if source_index is None:
                    status = "no_source"

            url = (
                sources[source_index]["url"]
                if source_index is not None
                else None
            )

            comment = str(
                verdict.get("comment") or ""
            ).strip()

            if not comment:
                if status == "no_source":
                    comment = (
                        "Не удалось получить достаточно данных "
                        "для обоснованного вывода."
                    )
                else:
                    comment = "Результат требует проверки редактором."

            results.append({
                "claim": claim,
                "status": status,
                "comment": comment,
                "url": url,
                "search_url": yandex_link(claim),
                "sources": sources,
                "raw_verdict": json.dumps(
                    verdict,
                    ensure_ascii=False,
                ),
            })

        return results, "ai"

    except Exception:
        # При ошибке API или обработки не выдаём ложный результат.
        return check_news_stub(text), "demo"
