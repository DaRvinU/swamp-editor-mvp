
from backend.fact_checker import (
    extract_claims,
    normalize_status,
    parse_source_index,
    best_matching_source,
)


def test_extract_claims_splits_text():
    claims = extract_claims(
        "Первое важное утверждение. Второе важное утверждение."
    )

    assert len(claims) == 2


def test_extract_claims_limits_number():
    text = " ".join(
        f"Это проверяемое утверждение номер {i}."
        for i in range(10)
    )

    claims = extract_claims(text)

    assert len(claims) <= 5


def test_normalize_status_confirmed():
    assert normalize_status("confirmed") == "confirmed"


def test_normalize_status_contradicted():
    assert normalize_status("contradicted") == "contradicted"


def test_normalize_status_unknown():
    assert normalize_status("что-то неизвестное") == "no_source"


def test_parse_source_index():
    sources = [
        {"url": "https://example.com/1"},
        {"url": "https://example.com/2"},
    ]

    assert parse_source_index(0, sources) == 0


def test_best_matching_source():
    sources = [
        {
            "title": "Новости спорта",
            "snippet": "Матч прошёл в Москве",
            "url": "https://example.com/sport",
        },
        {
            "title": "Экономика",
            "snippet": "Цены на продукты выросли",
            "url": "https://example.com/economy",
        },
    ]

    index = best_matching_source(
        "Цены на продукты выросли",
        sources,
    )

    assert index == 1
