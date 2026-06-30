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

BASE_API = "https://oldschool.runescape.wiki/api.php"

HEADERS = {
    "User-Agent": "OsrsClueScraper/1.0 (contact: jouw@email.com)"
}

REQUEST_DELAY = 1.0  # seconden tussen API-calls

# Wiki-paginatitels per clue-type
PAGES = {
    "anagrams":          "Anagram",
    "challenge_scrolls": "Challenge_scroll",
    "ciphers":           "Cipher",
    "coordinates":       "Coordinate",
    "cryptic":           "Cryptic_clue",
    "emote":             "Emote_clue",
    "maps":              "Map_clue",
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


def rows_from_table_raw(table: Tag) -> list[list[Tag]]:
    """Like rows_from_table but returns Tag objects instead of text."""
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        if all(c.name == "th" for c in cells):
            continue
        rows.append(cells)
    return rows


def extract_image_url(cell: Tag) -> str | None:
    """
    Return the full image URL from a table cell, or None.
    The OSRS Wiki uses lazy-loading: the real URL is in data-src,
    with a fallback to src. Thumbnail paths are converted to full-size.
    """
    img = cell.find("img")
    if not img:
        return None
    # Prefer data-src (lazy-load), fall back to src
    src = img.get("data-src") or img.get("src") or ""
    if not src:
        return None
    # Strip thumbnail sizing: /images/thumb/a/ab/File.png/120px-File.png
    # → /images/a/ab/File.png
    src = re.sub(r"/thumb(/[^/]+/[^/]+/[^/]+)/\d+px-[^/]+$", r"\1", src)
    # Make absolute
    if src.startswith("//"):
        src = "https:" + src
    elif src.startswith("/"):
        src = "https://oldschool.runescape.wiki" + src
    return src


def parse_coordinates(soup: BeautifulSoup) -> list[dict]:
    """
    Columns: Coordinate | Image (optional) | Location | Closest teleport | Wilderness?
    Rows where coordinate and location are both empty are skipped.
    """
    clues: list[dict] = []
    for table in all_tables(soup):
        for cells in rows_from_table_raw(table):
            texts = [clean(c.get_text()) for c in cells]
            if len(texts) < 2:
                continue
            coordinate = texts[0]
            # Skip completely empty rows
            if not any(texts):
                continue
            if not coordinate and not texts[1]:
                continue

            entry: dict[str, Any] = {"coordinate": coordinate}

            # Check every cell for an image; attach the first one found
            for cell in cells:
                image_url = extract_image_url(cell)
                if image_url:
                    entry["image_url"] = image_url
                    break

            # Remaining text columns — skip cells that only contained an image
            text_cols = [t for t in texts[1:] if t]
            if len(text_cols) >= 1:
                entry["location"] = text_cols[0]
            if len(text_cols) >= 2:
                entry["closest_teleport"] = text_cols[1]
            if len(text_cols) >= 3:
                entry["wilderness"] = text_cols[2].lower() in ("yes", "true", "✓")

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
    Table columns: Clue | Items | Notes | Map
    Difficulty comes from the preceding <h3> heading.
    Items are icon-links — extract item names from <a title="..."> attributes.
    The map image is in the last (4th) column.
    """
    clues: list[dict] = []
    current_difficulty = "unknown"

    for element in soup.find_all(["h2", "h3", "table"]):
        if element.name in ("h2", "h3"):
            heading = clean(element.get_text())
            for diff in ("beginner", "easy", "medium", "hard", "elite", "master"):
                if diff in heading.lower():
                    current_difficulty = diff
                    break

        elif element.name == "table" and "wikitable" in element.get("class", []):
            for cells in rows_from_table_raw(element):
                if len(cells) < 3:
                    continue

                # Col 0: clue text (includes emote instruction + gear to equip)
                clue_text = clean(cells[0].get_text())
                if not clue_text:
                    continue

                # Col 1: items required — extract from <a title="..."> links
                item_links = cells[1].find_all("a", title=True)
                items: list[str] = []
                seen: set[str] = set()
                for a in item_links:
                    name = clean(a.get("title", ""))
                    if name and name not in seen:
                        items.append(name)
                        seen.add(name)
                # Fallback for plain-text cells like "Nothing" / "None"
                if not items:
                    fallback = clean(cells[1].get_text())
                    if fallback:
                        items = [fallback]

                # Col 2: notes / location hints
                notes = clean(cells[2].get_text()) if len(cells) > 2 else ""

                # Col 3: map image
                map_image_url = None
                if len(cells) > 3:
                    map_image_url = extract_image_url(cells[3])

                entry: dict[str, Any] = {
                    "difficulty": current_difficulty,
                    "clue":       clue_text,
                    "items":      items,
                    "notes":      notes,
                }
                if map_image_url:
                    entry["map_image_url"] = map_image_url

                clues.append(entry)
    return clues


def parse_maps(soup: BeautifulSoup) -> list[dict]:
    """
    Maps page: each row has a map image, a location description, and
    optionally a solution/extra column.
    image_url is extracted from the <img> tag in the first cell.
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
            for cells in rows_from_table_raw(element):
                if not cells:
                    continue
                texts = [clean(c.get_text()) for c in cells]
                # Skip completely empty rows
                if not any(texts):
                    continue

                entry: dict[str, Any] = {"difficulty": current_difficulty}

                # First cell: try to get the image, fall back to text
                image_url = extract_image_url(cells[0])
                if image_url:
                    entry["image_url"] = image_url
                else:
                    entry["map_description"] = texts[0]

                if len(cells) >= 2:
                    entry["location"] = texts[1]
                if len(cells) >= 3:
                    entry["extra"] = texts[2]

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

    import os
    os.makedirs("data", exist_ok=True)
    out_path = "data/clues.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)

    total = sum(len(v) for v in output.values() if isinstance(v, list))
    print(f"\nDone – {total} clues written to {out_path}")


if __name__ == "__main__":
    main()
