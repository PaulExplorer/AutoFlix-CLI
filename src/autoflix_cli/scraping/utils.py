from typing import Optional, Union, List
import re, json
from bs4 import BeautifulSoup
from .objects import Player, Episode


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

    max_episodes = max(len(lst) for lst in lecteurs.values())

    lecteur_names = [f"Lecteur {i+1}" for i in range(len(lecteurs))]

    episodes = []
    for i in range(max_episodes):
        players = []
        for name, urls in zip(lecteur_names, lecteurs.values()):
            url = urls[i] if i < len(urls) else None
            if url:
                players.append(Player(name, url))
        episodes.append(Episode(title=f"Épisode {i+1}", players=players))

    return episodes


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


def parse_dirty_json(js_obj: str):
    regex = r"([{,])\s*([a-zA-Z0-9_]+)\s*:"
    json_str = re.sub(regex, r'\1"\2":', js_obj)
    json_str = re.sub(r",(\s*})", r"\1", json_str)
    return json.loads(json_str)
