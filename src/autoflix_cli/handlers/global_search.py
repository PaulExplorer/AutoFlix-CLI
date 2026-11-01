"""Global search: query every search-capable provider at once.

Results are merged, re-ranked by relevance and tagged with their origin
provider. Selecting an entry hands it over to that provider's
``open_result`` flow, so navigation after selection is identical to the
standalone provider experience.
"""

import difflib
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from ..cli_utils import (
    get_user_input,
    pause,
    print_header,
    print_info,
    print_warning,
    select_from_list,
)
from ..providers_registry import registry
from ..tracker import tracker

from ..scraping import anime_sama as anime_sama_scraper
from ..scraping import arkanime as arkanime_scraper
from ..scraping import coflix as coflix_scraper
from ..scraping import franime as franime_scraper
from ..scraping import french_stream as french_stream_scraper
from . import anime_sama, arkanime, coflix, franime, french_stream


# provider key -> search/open entry points
_SOURCES = {
    "anime_sama": {
        "label": "Anime-Sama",
        "website": anime_sama_scraper.get_website_url,
        "search": anime_sama_scraper.search,
        "open": anime_sama.open_result,
    },
    "franime": {
        "label": "FRAnime",
        "website": franime_scraper.get_website_url,
        "search": franime_scraper.search,
        "open": franime.open_result,
    },
    "arkanime": {
        "label": "ArkAnime",
        "website": arkanime_scraper.get_website_url,
        "search": arkanime_scraper.search,
        "open": arkanime.open_result,
    },
    "coflix": {
        "label": "Coflix",
        "website": coflix_scraper.get_website_url,
        "search": coflix_scraper.search,
        "open": coflix.open_result,
    },
    "french_stream": {
        "label": "French-Stream",
        "search": french_stream_scraper.search,
        "open": french_stream.open_result,
    },
}


def _select_sources(allowed_keys):
    """Global sources restricted to the providers active for the user."""
    return [
        {"key": key, **spec} for key, spec in _SOURCES.items() if key in allowed_keys
    ]


def _normalize(text):
    """Lowercase, strip accents and punctuation-ready normalization."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return text.strip()


def similarity(query, title):
    """Relevance score of a result title against the query (higher is better)."""
    q, t = _normalize(query), _normalize(title)
    if not q or not t:
        return 0.0
    if q == t:
        return 3.0
    if q in t:
        return 2.0
    return difflib.SequenceMatcher(None, q, t).ratio()


def search_all(query, sources):
    """Search every provider concurrently.

    Returns an ordered list of ``(key, outcome)`` where outcome is the list
    of results, or an exception when that provider's search failed. The
    provider registration order is preserved.
    """
    outcomes = []

    def run(spec):
        try:
            website = spec.get("website")
            if website:
                website()
            return spec["key"], list(spec["search"](query))
        except Exception as e:
            return spec["key"], e

    if not sources:
        return outcomes

    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        outcomes = list(pool.map(run, sources))
    return outcomes


def rank_results(query, outcomes, sources):
    """Merge per-provider results and sort by relevance.

    Primary sort is the similarity to the query; ties keep the provider
    registration order.
    """
    order = {spec["key"]: i for i, spec in enumerate(sources)}
    labels = {spec["key"]: spec["label"] for spec in sources}

    items = []
    seen = set()
    for key, outcome in outcomes:
        if isinstance(outcome, Exception) or not outcome:
            continue
        for result in outcome:
            fingerprint = (key, result.title, result.url)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            items.append(
                {
                    "provider": key,
                    "label": labels.get(key, key),
                    "result": result,
                    "score": similarity(query, result.title),
                }
            )

    items.sort(key=lambda it: (-it["score"], order.get(it["provider"], len(order))))
    return items


def handle_global_search():
    """Handle the Global provider flow: one query, every provider."""
    print_header("🌐 Global")

    user_lang = tracker.get_language()
    allowed = {p["key"] for p in registry.get_providers(user_lang)}
    sources = _select_sources(allowed)
    opens = {spec["key"]: spec["open"] for spec in sources}

    if not sources:
        print_warning("No providers available for the global search.")
        pause()
        return

    while True:
        query = get_user_input("Search query (or 'exit' to back)")
        if not query or query.lower() == "exit":
            return

        print_info(f"Searching {len(sources)} providers for: [cyan]{query}[/cyan]")
        outcomes = search_all(query, sources)

        for key, outcome in outcomes:
            label = next(s["label"] for s in sources if s["key"] == key)
            if isinstance(outcome, Exception):
                print_warning(f"[{label}] search failed: {outcome}")
            elif outcome:
                print_info(f"[{label}] {len(outcome)} result(s)")

        items = rank_results(query, outcomes, sources)
        if not items:
            print_warning("No results found on any provider.")
            pause()
            continue

        options = [f"{it['result'].title}   ·  [{it['label']}]" for it in items] + [
            "← Back"
        ]
        choice_idx = select_from_list(options, "📺 Search Results (Global):")

        if choice_idx == len(items):
            continue

        item = items[choice_idx]
        print_info(f"Opening via [cyan]{item['label']}[/cyan]...")
        try:
            opens[item["provider"]](item["result"])
        except Exception as e:
            print_warning(f"Could not open via {item['label']}: {e}")
            pause()
