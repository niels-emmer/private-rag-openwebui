import httpx
import respx
from fastapi.testclient import TestClient

from app import PRESIDIO_ANALYZER_URL, PRESIDIO_ANONYMIZER_URL, SEARXNG_URL, app

client = TestClient(app)


def _mock_no_pii(router: respx.MockRouter, text: str):
    router.post(f"{PRESIDIO_ANALYZER_URL}/analyze").mock(
        return_value=httpx.Response(200, json=[])
    )
    router.get(f"{SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json={"results": [], "query": text})
    )


def _mock_with_pii(router: respx.MockRouter, entities, redacted_text: str):
    router.post(f"{PRESIDIO_ANALYZER_URL}/analyze").mock(
        return_value=httpx.Response(200, json=entities)
    )
    router.post(f"{PRESIDIO_ANONYMIZER_URL}/anonymize").mock(
        return_value=httpx.Response(200, json={"text": redacted_text})
    )
    router.get(f"{SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json={"results": [], "query": redacted_text})
    )


@respx.mock
def test_query_without_pii_passes_through_unchanged():
    query = "best terraform module for aks"
    _mock_no_pii(respx, query)

    resp = client.get("/search", params={"q": query, "format": "json"})

    assert resp.status_code == 200
    forwarded_call = respx.calls.last
    assert forwarded_call.request.url.params["q"] == query


@respx.mock
def test_query_with_name_and_email_gets_redacted():
    raw = "Find user John Doe at john@example.com"
    redacted = "Find user <PERSON> at <EMAIL_ADDRESS>"
    entities = [
        {"entity_type": "PERSON", "start": 10, "end": 18, "score": 0.9},
        {"entity_type": "EMAIL_ADDRESS", "start": 22, "end": 38, "score": 0.9},
    ]
    _mock_with_pii(respx, entities, redacted)

    resp = client.get("/search", params={"q": raw})

    assert resp.status_code == 200
    forwarded_call = respx.calls.last
    assert forwarded_call.request.url.params["q"] == redacted
    assert "John Doe" not in forwarded_call.request.url.params["q"]
    assert "john@example.com" not in forwarded_call.request.url.params["q"]


@respx.mock
def test_query_with_phone_and_address_gets_redacted():
    raw = "call 555-123-4567 or visit 123 Main St"
    redacted = "call <PHONE_NUMBER> or visit <LOCATION>"
    entities = [
        {"entity_type": "PHONE_NUMBER", "start": 5, "end": 17, "score": 0.85},
        {"entity_type": "LOCATION", "start": 28, "end": 39, "score": 0.8},
    ]
    _mock_with_pii(respx, entities, redacted)

    resp = client.get("/search", params={"q": raw})

    assert resp.status_code == 200
    forwarded_call = respx.calls.last
    assert forwarded_call.request.url.params["q"] == redacted


def test_empty_query_returns_400():
    resp = client.get("/search", params={"q": ""})
    assert resp.status_code == 400


def test_missing_query_param_returns_400():
    resp = client.get("/search")
    assert resp.status_code == 400


@respx.mock
def test_presidio_analyzer_unreachable_fails_closed():
    respx.post(f"{PRESIDIO_ANALYZER_URL}/analyze").mock(side_effect=httpx.ConnectError("refused"))
    searxng_route = respx.get(f"{SEARXNG_URL}/search")

    resp = client.get("/search", params={"q": "John Doe at john@example.com"})

    assert resp.status_code == 503
    assert not searxng_route.called


@respx.mock
def test_presidio_anonymizer_error_fails_closed():
    respx.post(f"{PRESIDIO_ANALYZER_URL}/analyze").mock(
        return_value=httpx.Response(200, json=[{"entity_type": "PERSON", "start": 0, "end": 8, "score": 0.9}])
    )
    respx.post(f"{PRESIDIO_ANONYMIZER_URL}/anonymize").mock(return_value=httpx.Response(500))
    searxng_route = respx.get(f"{SEARXNG_URL}/search")

    resp = client.get("/search", params={"q": "John Doe searching something"})

    assert resp.status_code == 503
    assert not searxng_route.called


@respx.mock
def test_searxng_unreachable_returns_502():
    _mock_no_pii(respx, "plain query")
    respx.get(f"{SEARXNG_URL}/search").mock(side_effect=httpx.ConnectError("refused"))

    resp = client.get("/search", params={"q": "plain query"})

    assert resp.status_code == 502
