


from backend.search import search_evidence


def test_search_empty_query():
    assert search_evidence("") == []
