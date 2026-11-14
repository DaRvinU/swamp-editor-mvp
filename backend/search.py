
import time


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


def search_evidence(query: str, max_results: int = 4):
    """Ищет источники по проверяемому утверждению."""

    words = query.split()

    if not words:
        return []

    queries = [" ".join(words[:15])]

    if len(words) > 6:
        queries.append(" ".join(words[:6]))

    for search_query in queries:
        for attempt in range(3):
            try:
                hits = _ddg_search(search_query, max_results)

                results = []

                for hit in hits:
                    url = hit.get("href")

                    if not url:
                        continue

                    results.append({
                        "title": hit.get("title", ""),
                        "url": url,
                        "snippet": (hit.get("body") or "")[:400],
                    })

                if results:
                    return results

                break

            except Exception:
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))

    return []
