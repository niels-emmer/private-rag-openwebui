#!/usr/bin/env python3
"""
Reverse proxy in front of SearXNG that redacts PII from the `q` search
parameter via Microsoft Presidio before forwarding the request.

Only /search is implemented — the sole endpoint any caller in this stack
(OpenWebUI's built-in web search) actually needs.

Fails closed: if Presidio is unreachable, times out, or errors, the raw
query is never forwarded to SearXNG.

Environment variables (all optional):
  PRESIDIO_ANALYZER_URL     http://presidio-analyzer:3000
  PRESIDIO_ANONYMIZER_URL   http://presidio-anonymizer:3000
  SEARXNG_URL               http://searxng:8080
  PRESIDIO_TIMEOUT_SECONDS  5
"""

import logging
import os

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

PRESIDIO_ANALYZER_URL = os.getenv("PRESIDIO_ANALYZER_URL", "http://presidio-analyzer:3000")
PRESIDIO_ANONYMIZER_URL = os.getenv("PRESIDIO_ANONYMIZER_URL", "http://presidio-anonymizer:3000")
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://searxng:8080")
PRESIDIO_TIMEOUT_SECONDS = float(os.getenv("PRESIDIO_TIMEOUT_SECONDS", "5"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("searxng-pii-proxy")

app = FastAPI(title="SearXNG PII Redaction Proxy")


class PresidioUnavailable(Exception):
    pass


async def redact(client: httpx.AsyncClient, text: str) -> str:
    """Redact PII in `text` via Presidio. Raises PresidioUnavailable on any
    failure so the caller can fail closed rather than forward raw text."""
    if not text:
        return text

    try:
        analyze_resp = await client.post(
            f"{PRESIDIO_ANALYZER_URL}/analyze",
            json={"text": text, "language": "en"},
            timeout=PRESIDIO_TIMEOUT_SECONDS,
        )
        analyze_resp.raise_for_status()
        entities = analyze_resp.json()

        if not entities:
            return text

        anonymize_resp = await client.post(
            f"{PRESIDIO_ANONYMIZER_URL}/anonymize",
            json={"text": text, "analyzer_results": entities},
            timeout=PRESIDIO_TIMEOUT_SECONDS,
        )
        anonymize_resp.raise_for_status()
        return anonymize_resp.json()["text"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise PresidioUnavailable(str(exc)) from exc


@app.api_route("/search", methods=["GET", "POST"])
async def search(request: Request):
    if request.method == "GET":
        params = dict(request.query_params)
    else:
        form = await request.form()
        params = dict(form)

    query = params.get("q")
    if not isinstance(query, str) or not query.strip():
        return JSONResponse(status_code=400, content={"error": "missing or empty 'q' parameter"})

    async with httpx.AsyncClient() as client:
        try:
            params["q"] = await redact(client, query)
        except PresidioUnavailable as exc:
            logger.error("Presidio unavailable, failing closed: %s", exc)
            return JSONResponse(
                status_code=503,
                content={"error": "PII redaction service unavailable; query blocked to prevent leakage"},
            )

        try:
            upstream = await client.get(f"{SEARXNG_URL}/search", params=params, timeout=30.0)
        except httpx.HTTPError as exc:
            logger.error("SearXNG unreachable: %s", exc)
            return JSONResponse(status_code=502, content={"error": "search backend unavailable"})

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )
