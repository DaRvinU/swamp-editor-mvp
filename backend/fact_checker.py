
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

    parts = re.split(r"(?<=[.!?])\s+|\n+", text)

    claims = []

    for part in parts:
        part = part.strip(" .!?\t")

        if len(part.split()) >= 3:
            claims.append(part[:300])

    if not claims and text.strip():
        claims = [text.strip()[:300]]

    return claims[:MAX_CLAIMS]


def verify_claims(claims, evidence):
    """Сверяет утверждения с найденными фрагментами источников."""

    blocks = []

    for index, claim in enumerate(claims):
        sources = evidence[index]

        if sources:
            source_text = "\n".join(
                f"[{j}] {source['title']} — {source['snippet']}"
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
        '"comment": "1-2 предложения", "source": номер источника или null}]\n\n'
        "Для каждого утверждения:\n"
        "1. Проверь, относится ли источник к тому же событию.\n"
        "2. Сравни даты, места, числа и участников.\n"
        "3. confirmed — источник поддерживает утверждение.\n"
        "4. contradicted — источник противоречит утверждению.\n"
        "5. no_source — данных недостаточно или источник не о том событии.\n"
        "Не придумывай доказательства.\n"
        "Поле source должно содержать номер источника или null.\n\n"
        + "\n\n".join(blocks)
    )

    response = call_gigachat(VERIFY_SYSTEM, prompt)

    return parse_json_array(response)


def check_news_stub(text: str):
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
    """Определяет индекс источника, указанный моделью."""

    if value is None or not sources:
        return None

    if isinstance(value, list):
        if not value:
            return None
        value = value[0]

    if isinstance(value, (int, float)):
        index = int(value)
    else:
        text = str(value).strip()

        for index, source in enumerate(sources):
            if source.get("url") and source["url"] in text:
                return index

        match = re.search(r"\d+", text)

        if not match:
            return None

        index = int(match.group())

    if 0 <= index < len(sources):
        return index

    if index == len(sources):
        return index - 1

    return None


def best_matching_source(claim, sources):
    """Ищет источник с наибольшим совпадением слов."""

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

    if not GIGA_KEY:
        return check_news_stub(text), "demo"

    try:
        claims = extract_claims(text)

        evidence = [
            search_evidence(claim)
            for claim in claims
        ]

        verdicts = verify_claims(claims, evidence)

        by_id = {}

        for position, verdict in enumerate(verdicts):
            if not isinstance(verdict, dict):
                continue

            match = re.search(
                r"\d+",
                str(verdict.get("id", ""))
            )

            if match:
                by_id[int(match.group())] = verdict
            else:
                by_id.setdefault(position, verdict)

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

            if source_index is None and status != "no_source":
                source_index = best_matching_source(
                    claim,
                    sources,
                )

            url = (
                sources[source_index]["url"]
                if source_index is not None
                else None
            )

            if status != "no_source" and not url:
                status = "no_source"

            comment = str(
                verdict.get("comment") or ""
            ).strip()

            if not comment:
                comment = (
                    "Источники по утверждению не найдены."
                    if not sources
                    else "В найденных фрагментах недостаточно данных."
                )

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
        # Ошибка AI не должна останавливать приложение.
        return check_news_stub(text), "demo"
