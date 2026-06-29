"""
OSRS Clue Scroll Scraper
Fetches clue data from the OSRS Wiki MediaWiki API and outputs clues.json
for use in an OSRS companion app.
"""

import json
import re
import sys
import time
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": "OSRSCompanionApp/1.0 (https://github.com/your-org/osrs-companion)"
}
BASE_API = "https://oldschool.runescape.wiki/api.php"
REQUEST_DELAY = 1.5  # seconds between requests – be polite to the wiki

PAGES: dict[str, str] = {
    "anagrams":        "Treasure_Trails/Guide/Anagrams",
    "challenge_scrolls": "Treasure_Trails/Guide/Challenge_scrolls",
    "ciphers":         "Treasure_Trails/Guide/Ciphers",
    "coordinates":     "Treasure_Trails/Guide/Coordinates",
    "cryptic":         "Treasure_Trails/Guide/Cryptic_clues",
    "emote":           "Treasure_Trails/Guide/Emote_clues",
    "maps":            "Treasure_Trails/Guide/Maps",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean(text: str) -> str:
    """Strip extra whitespace and newlines."""
    return re.sub(r"\s+", " ", text or "").strip()


def fetch_html(page: str) -> BeautifulSoup:
    """Fetch a wiki page via the MediaWiki parse API and return parsed HTML."""
    params = {
        "action": "parse",
        "page": page,
        "prop": "text",
        "format": "json",
    }
    resp = requests.get(BASE_API, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"Wiki API error for '{page}': {data['error']}")

    html = data["parse"]["text"]["*"]
    return BeautifulSoup(html, "html.parser")


def rows_from_table(table: Tag) -> list[list[str]]:
    """Return a list of cell-text lists for every <tr> in a table, skipping the header."""
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        # Skip header rows (all th)
        if all(c.name == "th" for c in cells):
            continue
        rows.append([clean(c.get_text()) for c in cells])
    return rows


def first_table(soup: BeautifulSoup) -> Tag | None:
    return soup.find("table", class_="wikitable")


def all_tables(soup: BeautifulSoup) -> list[Tag]:
    return soup.find_all("table", class_="wikitable")


def difficulty_from_class(tag: Tag) -> str | None:
    """Some tables carry a class like 'easy', 'medium', 'hard', 'elite', 'master'."""
    classes = " ".join(tag.get("class", []))
    for diff in ("master", "elite", "hard", "medium", "easy"):
        if diff in classes.lower():
            return diff
    return None


# ---------------------------------------------------------------------------
# Per-page parsers
# ---------------------------------------------------------------------------

def parse_anagrams(soup: BeautifulSoup) -> list[dict]:
    """
    Columns: Anagram | Answer | Challenge answer (optional) | Location | Area
    """
    clues: list[dict] = []
    for table in all_tables(soup):
        for row in rows_from_table(table):
            if len(row) < 4:
                continue
            entry: dict[str, Any] = {
                "anagram": row[0],
                "answer":  row[1],
                "location": row[2] if len(row) == 4 else row[3],
            }
            # Some rows have a challenge-scroll answer in col 2
            if len(row) == 5:
                entry["challenge_answer"] = row[2]
                entry["area"] = row[4]
            elif len(row) == 4:
                entry["area"] = row[3]
            clues.append(entry)
    return clues


def parse_challenge_scrolls(soup: BeautifulSoup) -> list[dict]:
    """
    Columns: Clue | Challenge | Answer | Difficulty
    The page groups challenges under difficulty headings.
    """
    clues: list[dict] = []
    current_difficulty = "unknown"

    for element in soup.find_all(["h2", "h3", "table"]):
        if element.name in ("h2", "h3"):
            heading = clean(element.get_text())
            for diff in ("easy", "medium", "hard", "elite", "master"):
                if diff in heading.lower():
                    current_difficulty = diff
                    break
        elif element.name == "table" and "wikitable" in element.get("class", []):
            for row in rows_from_table(element):
                if len(row) < 3:
                    continue
                clues.append({
                    "difficulty": current_difficulty,
                    "clue":      row[0],
                    "challenge": row[1],
                    "answer":    row[2],
                })
    return clues


def parse_ciphers(soup: BeautifulSoup) -> list[dict]:
    """
    Columns: Cipher | Decoded | NPC | Challenge answer | Location
    """
    clues: list[dict] = []
    for table in all_tables(soup):
        for row in rows_from_table(table):
            if len(row) < 3:
                continue
            entry: dict[str, Any] = {
                "cipher":  row[0],
                "decoded": row[1],
                "npc":     row[2] if len(row) > 2 else "",
            }
            if len(row) > 3:
                entry["challenge_answer"] = row[3]
            if len(row) > 4:
                entry["location"] = row[4]
            clues.append(entry)
    return clues


def parse_coordinates(soup: BeautifulSoup) -> list[dict]:
    """
    Columns: Coordinate | Location | Closest teleport | Wilderness?
    """
    clues: list[dict] = []
    for table in all_tables(soup):
        for row in rows_from_table(table):
            if len(row) < 2:
                continue
            entry: dict[str, Any] = {
                "coordinate": row[0],
                "location":   row[1],
            }
            if len(row) > 2:
                entry["closest_teleport"] = row[2]
            if len(row) > 3:
                entry["wilderness"] = row[3].lower() in ("yes", "true", "✓")
            clues.append(entry)
    return clues


def parse_cryptic(soup: BeautifulSoup) -> list[dict]:
    """
    Columns: Clue | Solution | Difficulty (sometimes)
    Difficulty is indicated by section headers.
    """
    clues: list[dict] = []
    current_difficulty = "unknown"

    for element in soup.find_all(["h2", "h3", "table"]):
        if element.name in ("h2", "h3"):
            heading = clean(element.get_text())
            for diff in ("easy", "medium", "hard", "elite", "master"):
                if diff in heading.lower():
                    current_difficulty = diff
                    break
        elif element.name == "table" and "wikitable" in element.get("class", []):
            for row in rows_from_table(element):
                if len(row) < 2:
                    continue
                clues.append({
                    "difficulty": current_difficulty,
                    "clue":       row[0],
                    "solution":   row[1],
                    "extra":      row[2] if len(row) > 2 else "",
                })
    return clues


def parse_emote(soup: BeautifulSoup) -> list[dict]:
    """
    Columns: Clue text | Location | Emote(s) | Item(s) required | Ugly duckling hint (elite)
    """
    clues: list[dict] = []
    current_difficulty = "unknown"

    for element in soup.find_all(["h2", "h3", "table"]):
        if element.name in ("h2", "h3"):
            heading = clean(element.get_text())
            for diff in ("easy", "medium", "hard", "elite", "master"):
                if diff in heading.lower():
                    current_difficulty = diff
                    break
        elif element.name == "table" and "wikitable" in element.get("class", []):
            for row in rows_from_table(element):
                if len(row) < 3:
                    continue
                entry: dict[str, Any] = {
                    "difficulty": current_difficulty,
                    "clue":       row[0],
                    "location":   row[1],
                    "emotes":     [e.strip() for e in row[2].split(",") if e.strip()],
                }
                if len(row) > 3:
                    entry["items_required"] = [i.strip() for i in row[3].split(",") if i.strip()]
                if len(row) > 4:
                    entry["extra"] = row[4]
                clues.append(entry)
    return clues


def parse_maps(soup: BeautifulSoup) -> list[dict]:
    """
    Maps pages typically list map clues with an image and a location text.
    We capture whatever tabular data is available.
    """
    clues: list[dict] = []
    current_difficulty = "unknown"

    for element in soup.find_all(["h2", "h3", "table"]):
        if element.name in ("h2", "h3"):
            heading = clean(element.get_text())
            for diff in ("easy", "medium", "hard", "elite", "master"):
                if diff in heading.lower():
                    current_difficulty = diff
                    break
        elif element.name == "table" and "wikitable" in element.get("class", []):
            for row in rows_from_table(element):
                if not any(row):
                    continue
                entry: dict[str, Any] = {"difficulty": current_difficulty}
                # Columns vary; capture them positionally
                if len(row) >= 1:
                    entry["map_description"] = row[0]
                if len(row) >= 2:
                    entry["location"] = row[1]
                if len(row) >= 3:
                    entry["extra"] = row[2]
                clues.append(entry)
    return clues


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

PARSERS = {
    "anagrams":          parse_anagrams,
    "challenge_scrolls": parse_challenge_scrolls,
    "ciphers":           parse_ciphers,
    "coordinates":       parse_coordinates,
    "cryptic":           parse_cryptic,
    "emote":             parse_emote,
    "maps":              parse_maps,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    output: dict[str, Any] = {
        "meta": {
            "source": "https://oldschool.runescape.wiki",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    }

    for key, page in PAGES.items():
        print(f"[{key}] Fetching '{page}' …", flush=True)
        try:
            soup = fetch_html(page)
            parser = PARSERS[key]
            clues = parser(soup)
            output[key] = clues
            print(f"[{key}] ✓  {len(clues)} entries", flush=True)
        except Exception as exc:
            print(f"[{key}] ✗  {exc}", file=sys.stderr, flush=True)
            output[key] = []

        time.sleep(REQUEST_DELAY)

    out_path = "clues.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)

    total = sum(len(v) for v in output.values() if isinstance(v, list))
    print(f"\nDone – {total} clues written to {out_path}")


if __name__ == "__main__":
    main()
