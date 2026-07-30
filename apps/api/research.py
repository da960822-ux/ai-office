"""Pluggable public-web discovery with deterministic fallback."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree


class SearchError(RuntimeError):
    pass


def _read_json(url: str, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _brave(query: str, limit: int) -> list[dict]:
    key = os.getenv("BRAVE_SEARCH_API_KEY")
    if not key:
        return []
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": limit}
    )
    payload = _read_json(
        url,
        {"Accept": "application/json", "X-Subscription-Token": key, "User-Agent": "AI-Automation-Office/1.0"},
    )
    return [
        {
            "title": item.get("title", "")[:300],
            "url": item.get("url", "")[:2000],
            "snippet": item.get("description", "")[:1000],
            "provider": "brave",
        }
        for item in payload.get("web", {}).get("results", [])
        if item.get("title") and str(item.get("url", "")).startswith(("http://", "https://"))
    ]


def _searxng(query: str, limit: int) -> list[dict]:
    endpoint = os.getenv("AI_OFFICE_SEARCH_ENDPOINT", "").rstrip("/")
    if not endpoint:
        return []
    url = endpoint + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
    payload = _read_json(url, {"Accept": "application/json", "User-Agent": "AI-Automation-Office/1.0"})
    return [
        {
            "title": item.get("title", "")[:300],
            "url": item.get("url", "")[:2000],
            "snippet": item.get("content", "")[:1000],
            "provider": "searxng",
        }
        for item in payload.get("results", [])[:limit]
        if item.get("title") and str(item.get("url", "")).startswith(("http://", "https://"))
    ]


def _bing_rss(query: str, limit: int) -> list[dict]:
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote_plus(query)
    request = urllib.request.Request(url, headers={"User-Agent": "AI-Automation-Office/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        root = ElementTree.fromstring(response.read().decode("utf-8", errors="replace"))
    return [
        {
            "title": (item.findtext("title") or "").strip()[:300],
            "url": (item.findtext("link") or "").strip()[:2000],
            "snippet": (item.findtext("description") or "").strip()[:1000],
            "provider": "bing-rss-fallback",
        }
        for item in root.findall("./channel/item")[:limit]
        if (item.findtext("title") or "").strip()
        and (item.findtext("link") or "").strip().startswith(("http://", "https://"))
    ]


def search_public_web(query: str, limit: int = 10) -> list[dict]:
    normalized = " ".join(query.split())[:300]
    if not normalized:
        raise SearchError("Web search query is required")
    results: list[dict] = []
    errors = []
    for provider in (_brave, _searxng, _bing_rss):
        try:
            results.extend(provider(normalized, limit))
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError, ElementTree.ParseError) as error:
            errors.append(f"{provider.__name__}: {error}")
        if len(results) >= limit:
            break
    deduplicated = []
    seen = set()
    for item in results:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        deduplicated.append(item)
        if len(deduplicated) >= limit:
            break
    if not deduplicated:
        raise SearchError("; ".join(errors) or "Web search returned no usable sources")
    return deduplicated
