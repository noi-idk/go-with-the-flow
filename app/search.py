"""Live web-data layer.

Builds search queries from the current conversation state, queries a live search
backend, and normalises the hits into :class:`Candidate` objects carrying the
live details we care about (price, opening hours, event dates).

Backends are pluggable via ``SEARCH_PROVIDER``; the default needs no API key.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from selectolax.parser import HTMLParser

from .state import ConversationState

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DUCKDUCKGO_HTML = "https://html.duckduckgo.com/html/"
REQUEST_TIMEOUT = 20.0
# Below this a matched number is almost always a fragment, not an entry price.
MIN_PLAUSIBLE_PRICE = 5.0

_PRICE_RE = re.compile(
    r"(?:aed|dhs?|dirhams?)\s*(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s*(?:aed|dhs?|dirhams?)",
    re.IGNORECASE,
)
_FREE_RE = re.compile(r"\b(free (?:entry|admission|of charge)|no entry fee|free to (?:visit|enter))\b", re.I)
_HOURS_RE = re.compile(
    r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*(?:-|–|to|until|till)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm))",
    re.IGNORECASE,
)
_OPEN_24_RE = re.compile(r"\b(open 24 hours|24/7)\b", re.IGNORECASE)
# Article furniture that shows up as a heading but isn't something you can go and do.
_BOILERPLATE_HEADING_RE = re.compile(
    r"\b(pro tips|tips|faq|frequently asked|conclusion|final thoughts|table of contents|"
    r"how to get|getting (?:there|around)|when to (?:visit|go)|why (?:visit|you)|about (?:us|the)|"
    r"related|share this|newsletter|comments?|read more|you may also)\b",
    re.IGNORECASE,
)
_EMOJI_RE = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f]")


@dataclass
class Candidate:
    """One live web hit, normalised into something we can rank."""

    title: str
    url: str
    snippet: str
    source: str = "duckduckgo"
    query: str = ""
    price_aed: float | None = None
    is_free: bool = False
    opening_hours: str | None = None
    open_24h: bool = False
    verified_at: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        return f"{self.title} {self.snippet}".lower()

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "price_aed": self.price_aed,
            "is_free": self.is_free,
            "opening_hours": self.opening_hours,
            "open_24h": self.open_24h,
            "verified_at": self.verified_at,
        }


def build_queries(state: ConversationState) -> list[str]:
    """Turn the current slots into a handful of complementary live queries."""
    where = state.location or "Dubai"
    month = datetime.now(timezone.utc).strftime("%B %Y")
    vibe = state.vibe or ""
    env = "" if state.environment in (None, "either") else state.environment
    budget = f"under {state.budget_aed:g} AED" if state.budget_aed else "cheap"
    duration = f"{state.free_time_hours:g} hour" if state.free_time_hours else ""
    interests = " ".join(state.interests)

    queries = [
        f"{vibe} {env} things to do in {where} {budget} {month}".strip(),
        f"best {env} activities {where} {duration} {vibe} {month} prices".strip(),
        f"what's on in {where} {month} events tickets price".strip(),
        f"{vibe} {env} experience {where} tickets from AED opening hours".strip(),
    ]
    if interests:
        queries.append(f"{interests} in {where} {budget} {month}")
    if state.open_now:
        queries.append(f"places open now in {where} {vibe} {env}".strip())
    if state.age_group == "family":
        queries.append(f"family friendly {env} activities {where} {budget}".strip())
    return [re.sub(r"\s+", " ", q).strip() for q in queries if q.strip()]


class SearchBackend:
    async def search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[Candidate]:
        raise NotImplementedError


class DuckDuckGoBackend(SearchBackend):
    """Keyless live search via the ddgs metasearch client, falling back to DDG's HTML endpoint."""

    name = "duckduckgo"

    async def search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[Candidate]:
        hits = await asyncio.to_thread(self._ddgs, query, limit)
        if hits:
            return hits
        response = await client.post(
            DUCKDUCKGO_HTML,
            data={"q": query, "kl": "ae-en"},
            headers={"User-Agent": USER_AGENT, "Referer": "https://duckduckgo.com/"},
        )
        response.raise_for_status()
        return self._parse(response.text, query)[:limit]

    def _ddgs(self, query: str, limit: int) -> list[Candidate]:
        try:
            from ddgs import DDGS

            rows = DDGS().text(query, max_results=limit, region="ae-en")
        except Exception:
            return []
        return [
            Candidate(
                title=row.get("title", ""),
                url=row.get("href", ""),
                snippet=row.get("body", ""),
                source=self.name,
                query=query,
            )
            for row in rows
        ]

    def _parse(self, html: str, query: str) -> list[Candidate]:
        tree = HTMLParser(html)
        results: list[Candidate] = []
        for node in tree.css("div.result, div.web-result"):
            link = node.css_first("a.result__a")
            if link is None:
                continue
            snippet_node = node.css_first("a.result__snippet, div.result__snippet")
            snippet = snippet_node.text(strip=True) if snippet_node else ""
            results.append(
                Candidate(
                    title=link.text(strip=True),
                    url=_clean_url(link.attributes.get("href", "")),
                    snippet=snippet,
                    source=self.name,
                    query=query,
                )
            )
        return results


class TavilyBackend(SearchBackend):
    name = "tavily"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[Candidate]:
        response = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": self.api_key,
                "query": query,
                "max_results": limit,
                "search_depth": "advanced",
            },
        )
        response.raise_for_status()
        payload = response.json()
        return [
            Candidate(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                source=self.name,
                query=query,
            )
            for item in payload.get("results", [])
        ]


class SerperBackend(SearchBackend):
    name = "serper"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[Candidate]:
        response = await client.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": limit, "gl": "ae"},
            headers={"X-API-KEY": self.api_key},
        )
        response.raise_for_status()
        payload = response.json()
        return [
            Candidate(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                source=self.name,
                query=query,
            )
            for item in payload.get("organic", [])
        ]


class BraveBackend(SearchBackend):
    name = "brave"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(self, client: httpx.AsyncClient, query: str, limit: int) -> list[Candidate]:
        response = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": limit, "country": "AE"},
            headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
        return [
            Candidate(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=re.sub(r"<[^>]+>", "", item.get("description", "")),
                source=self.name,
                query=query,
            )
            for item in payload.get("web", {}).get("results", [])
        ]


def get_backend() -> SearchBackend:
    provider = os.getenv("SEARCH_PROVIDER", "").lower()
    tavily, serper, brave = (
        os.getenv("TAVILY_API_KEY"),
        os.getenv("SERPER_API_KEY"),
        os.getenv("BRAVE_API_KEY"),
    )
    if provider == "tavily" or (not provider and tavily):
        if tavily:
            return TavilyBackend(tavily)
    if provider == "serper" or (not provider and serper):
        if serper:
            return SerperBackend(serper)
    if provider == "brave" or (not provider and brave):
        if brave:
            return BraveBackend(brave)
    return DuckDuckGoBackend()


def _clean_url(href: str) -> str:
    if href.startswith("//duckduckgo.com/l/") or "duckduckgo.com/l/" in href:
        parsed = parse_qs(urlparse(href).query)
        if "uddg" in parsed:
            return parsed["uddg"][0]
    if href.startswith("//"):
        return "https:" + href
    return href


def enrich_from_text(candidate: Candidate, text: str) -> Candidate:
    """Pull live price / opening-hour signals out of a blob of page text."""
    if candidate.price_aed is None:
        prices = _prices_in(text)
        if prices:
            candidate.price_aed = min(prices)
    if _FREE_RE.search(text):
        candidate.is_free = True
        candidate.price_aed = 0.0
    hours = _HOURS_RE.search(text)
    if hours and not candidate.opening_hours:
        candidate.opening_hours = hours.group(1)
    if _OPEN_24_RE.search(text):
        candidate.open_24h = True
        candidate.opening_hours = candidate.opening_hours or "Open 24 hours"
    return candidate


def _clean_heading(title: str) -> str:
    return re.sub(r"\s+", " ", _EMOJI_RE.sub("", re.sub(r"^\d+[.)]\s*", "", title))).strip()


def _prices_in(text: str) -> list[float]:
    prices: list[float] = []
    for match in _PRICE_RE.finditer(text):
        raw = match.group(1) or match.group(2)
        try:
            value = float(raw.replace(",", ""))
        except (TypeError, ValueError):
            continue
        is_year = 1900 <= value <= 2100 and value == int(value)
        if MIN_PLAUSIBLE_PRICE <= value <= 5000 and not is_year:
            prices.append(value)
    return prices


async def fetch_page(client: httpx.AsyncClient, url: str) -> HTMLParser | None:
    try:
        response = await client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        response.raise_for_status()
        return HTMLParser(response.text)
    except Exception:
        return None


async def verify_candidate(client: httpx.AsyncClient, candidate: Candidate) -> Candidate:
    """Fetch the page to confirm price / opening hours before we recommend it."""
    tree = await fetch_page(client, candidate.url)
    if tree is None or tree.body is None:
        return candidate
    enrich_from_text(candidate, tree.body.text(separator=" ", strip=True)[:20000])
    candidate.verified_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    candidate.details["headings"] = _headings(tree)
    return candidate


def _headings(tree: HTMLParser) -> list[tuple[str, str]]:
    """(heading, following text) pairs \u2014 the individual entries inside a round-up page."""
    pairs: list[tuple[str, str]] = []
    for node in tree.css("h2, h3"):
        title = node.text(strip=True)
        if not (5 < len(title) < 90):
            continue
        following: list[str] = []
        sibling = node.next
        while sibling is not None and len(" ".join(following)) < 500:
            if sibling.tag in ("h2", "h3"):
                break
            if sibling.tag in ("p", "div", "ul", "span"):
                following.append(sibling.text(separator=" ", strip=True))
            sibling = sibling.next
        pairs.append((title, " ".join(following)))
    return pairs


def expand_roundup(candidate: Candidate, limit: int = 6) -> list[Candidate]:
    """Turn a "20 best things to do" page into individual, priceable suggestions."""
    expanded: list[Candidate] = []
    for title, body in candidate.details.get("headings", []):
        if _BOILERPLATE_HEADING_RE.search(title):
            continue
        if not _prices_in(body) and not _HOURS_RE.search(body) and not _FREE_RE.search(body):
            continue
        child = Candidate(
            title=_clean_heading(title),
            url=candidate.url,
            snippet=body[:400],
            source=candidate.source,
            query=candidate.query,
            verified_at=candidate.verified_at,
        )
        enrich_from_text(child, f"{child.title} {body}".lower())
        expanded.append(child)
        if len(expanded) >= limit:
            break
    return expanded


async def live_search(
    state: ConversationState,
    per_query: int = 8,
    verify_top: int = 6,
) -> list[Candidate]:
    """Run the live queries for ``state`` and return de-duplicated candidates."""
    backend = get_backend()
    queries = build_queries(state)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        batches = await asyncio.gather(*(backend.search(client, q, per_query) for q in queries), return_exceptions=True)
        candidates: list[Candidate] = []
        seen: set[str] = set()
        for batch in batches:
            if isinstance(batch, BaseException):
                continue
            for candidate in batch:
                key = candidate.url.split("?")[0].rstrip("/")
                if not key or key in seen:
                    continue
                seen.add(key)
                enrich_from_text(candidate, candidate.text())
                candidates.append(candidate)

        needs_check = [c for c in candidates if c.price_aed is None or c.opening_hours is None]
        await asyncio.gather(*(verify_candidate(client, c) for c in needs_check[:verify_top]), return_exceptions=True)

    # Round-up pages become individual suggestions with their own live price / hours.
    for candidate in list(candidates):
        candidates.extend(expand_roundup(candidate))
    return candidates
