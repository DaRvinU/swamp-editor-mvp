

"""Поиск источников для проверки утверждений."""

import time
from urllib.parse import urlparse


def _ddg_search(query: str, max_results: int):
    """Выполняет поиск через DuckDuckGo."""

    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    with DDGS() as search:
        return list(
            search.text(
                query,
                region="ru-ru",
                max_results=max_results,
            )
        )


def search_evidence(query: str, max_results: int = 4) -> list:
    """
    Ищет источники по проверяемому утверждению.

    Возвращает список словарей:
    title, url, snippet.
    При ошибке поиска возвращает пустой список.
    """

    if not isinstance(query, str) or not query.strip():
        return []

    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        max_results = 4

    max_results = max(1, min(max_results, 10))

    words = query.split()
    queries = [" ".join(words[:15])]

    if len(words) > 6:
        shorter_query = " ".join(words[:6])
        if shorter_query not in queries:
            queries.append(shorter_query)

    results = []
    seen_urls = set()

    for search_query in queries:
        for attempt in range(3):
            try:
                hits = _ddg_search(search_query, max_results)

                for hit in hits:
                    if not isinstance(hit, dict):
                        continue

                    url = (hit.get("href") or "").strip()

                    if not url.startswith(("http://", "https://")):
                        continue

                    parsed_url = urlparse(url)
                    normalized_url = (
                        f"{parsed_url.scheme.lower()}://"
                        f"{parsed_url.netloc.lower()}"
                        f"{parsed_url.path.rstrip('/')}"
                    )

                    if normalized_url in seen_urls:
                        continue

                    seen_urls.add(normalized_url)

                    results.append({
                        "title": (hit.get("title") or "").strip(),
                        "url": url,
                        "snippet": (hit.get("body") or "").strip()[:400],
                    })

                    if len(results) >= max_results:
                        return results

                # Если поиск отработал без ошибок, повторять его не нужно.
                break

            except Exception:
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))

    return results
