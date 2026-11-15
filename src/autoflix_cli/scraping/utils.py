import re
from typing import List, Optional, Union

from bs4 import BeautifulSoup

from .objects import Episode, Player, SamaSeasonPage


class NoEpisodesFoundError(Exception):
    """Raised when an episode list contains no playable links.

    On Anime-Sama, a catalogue entry can exist before its content is
    released: the pages exist but the season data carries no player link,
    which means the content has probably not aired / been released yet.
    """

    def __init__(self, message: str | None = None):
        super().__init__(
            message
            or "No playable links found for this content: it is probably not released yet."
        )


def parse_episode(code):
    """
    Parse an episode code into its components.
    """
    match = re.fullmatch(r"ep(\d+)([a-zA-Z]+)", code)
    if match:
        numero = int(match.group(1))
        suffixe = match.group(2)
        return numero, suffixe
    else:
        return None


def parse_episodes_from_js(js_code: str) -> List[Episode]:
    """
    Parse a JavaScript code into a list of episodes.
    """
    matches = re.findall(r"var\s+eps(\d+)\s*=\s*\[(.*?)\];", js_code, re.DOTALL)

    lecteurs = {}
    for lecteur_num, content in matches:
        urls = re.findall(r"'(https?://.*?)'", content)
        lecteurs[int(lecteur_num)] = urls

    lecteurs = dict(sorted(lecteurs.items()))

    if not lecteurs:
        # No player URLs at all in the episode list: on Anime-Sama this
        # usually means the content is listed in the catalogue but has
        # not been released yet.
        raise NoEpisodesFoundError()

    max_episodes = max(len(lst) for lst in lecteurs.values())

    lecteur_names = [f"Lecteur {i+1}" for i in range(len(lecteurs))]

    episodes = []
    for i in range(max_episodes):
        players = []
        for name, urls in zip(lecteur_names, lecteurs.values(), strict=False):
            url = urls[i] if i < len(urls) else None
            if url:
                players.append(Player(name, url))
        episodes.append(Episode(title=f"Épisode {i+1}", players=players))

    return episodes


def parse_season_page(html: str) -> Optional[SamaSeasonPage]:
    """Parse an Anime-Sama season page into its episode references.

    The page stores the episode list in a ``<script data-source="bdd">``
    block: ``eps1``..``epsN`` are the player columns, each episode holding
    either ``lien:<id>`` (resolved later through :func:`anime_sama.resolve_players`),
    a direct URL, or an empty string. ``epsJeton`` is the API token and
    ``languesDispo`` lists the available languages.

    Returns ``None`` when the page does not carry the inline block (older
    mirrors still serve the legacy ``episodes.js`` file).
    """
    soup = BeautifulSoup(html, "html5lib")
    script = soup.find("script", {"data-source": "bdd"})
    if script is None:
        return None

    code = script.string or script.get_text()
    columns = {}
    for number, content in re.findall(
        r"var\s+eps(\d+)\s*=\s*\[(.*?)\]\s*;", code, re.DOTALL
    ):
        columns[int(number)] = re.findall(r"""['"]([^'"]*)['"]""", content)

    if not columns:
        return None

    ordered = [columns[number] for number in sorted(columns)]

    ordre_final = True
    match = re.search(r"var\s+epsOrdreFinal\s*=\s*(true|false)", code)
    if match:
        ordre_final = match.group(1) == "true"

    if not ordre_final and len(ordered) >= 2:
        # The site swaps the two first players when the page is not final.
        ordered[0], ordered[1] = ordered[1], ordered[0]

    jeton_match = re.search(r"""var\s+epsJeton\s*=\s*['"]([^'"]*)['"]""", code)
    jeton = jeton_match.group(1) if jeton_match else ""

    langs: list[str] = []
    langs_match = re.search(r"var\s+languesDispo\s*=\s*\[(.*?)\]", html, re.DOTALL)
    if langs_match:
        langs = re.findall(r"""['"]([^'"]+)['"]""", langs_match.group(1))

    size = max(len(column) for column in ordered)
    episodes = [
        [column[index] if index < len(column) else "" for column in ordered]
        for index in range(size)
    ]

    return SamaSeasonPage(episodes, jeton, langs, ordre_final)


def get_value_by_key(ul_html: Union[str, BeautifulSoup], key: str) -> Optional[str]:
    """
    Return the value associated with *key* inside a <ul> movie‑info block.

    Parameters
    ----------
    ul_html : str | BeautifulSoup
        Either the raw <ul>...</ul> HTML string or an already‑parsed
        BeautifulSoup object.
    key : str
        The exact text inside <div class="mov-label"> you’re looking for
        (e.g. "Release date:").

    Returns
    -------
    str | None
        The text contained in the matching <div class="mov-desc">,
        stripped of whitespace, or None if the key is not present.

    Example
    -------
    >>> html = '''
    ... <ul>
    ...   <li><div class="mov-label">Release date:</div><div class="mov-desc">2025</div></li>
    ...   <li><div class="mov-label">Director:</div><div class="mov-desc">Jane Doe</div></li>
    ... </ul>'''
    >>> get_value_by_key(html, "Release date:")
    '2025'
    """
    # Accept either HTML text or a pre‑built soup object.
    soup = BeautifulSoup(ul_html, "html5lib") if isinstance(ul_html, str) else ul_html

    # 1) Modern approach: CSS selector with :has() and :-soup-contains().
    node = soup.select_one(f"li:has(.mov-label:-soup-contains('{key}')) .mov-desc")

    # 2) Fallback for BeautifulSoup versions < 4.8 (no :has() support).
    if node is None:
        for li in soup.select("li"):
            label = li.select_one(".mov-label")
            if label and label.get_text(strip=True) == key:
                node = li.select_one(".mov-desc")
                break

    return node.get_text(strip=True) if node else None
