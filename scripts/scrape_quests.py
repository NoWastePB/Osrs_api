import json
import time
import requests
from bs4 import BeautifulSoup, Tag
from urllib.parse import urlparse, unquote

URL = "https://oldschool.runescape.wiki/w/Quests/List"
BASE_URL = "https://oldschool.runescape.wiki"
API_URL = "https://oldschool.runescape.wiki/api.php"

HEADERS = {
    "User-Agent": "OsrsQuestScraper/1.0 (contact: jouw@email.com)"
}


def clean(text):
    return " ".join(text.strip().split())


def url_to_page_title(url):
    """Zet een wiki-URL om naar een paginatitel voor de API.
    Bijv. https://oldschool.runescape.wiki/w/The_Feud -> 'The Feud'
    """
    path = urlparse(url).path          # /w/The_Feud
    title = path.removeprefix("/w/")   # The_Feud
    return unquote(title).replace("_", " ")


def fetch_html_via_api(page_title):
    """Haal de geparsede HTML op via de MediaWiki API."""
    params = {
        "action": "parse",
        "page": page_title,
        "prop": "text",
        "format": "json",
        "formatversion": "2",   # geeft text direct als string, niet als {"*": ...}
    }
    response = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        raise ValueError(f"API-fout voor '{page_title}': {data['error'].get('info', data['error'])}")

    return data["parse"]["text"]   # formatversion=2 geeft dit direct als string


# ── Lijst-parsing (ongewijzigd: blijft van de HTML-pagina) ───────────────────

def get_tables_after_heading(soup, heading_text):
    """Geeft ALLE tabellen terug na een heading, tot de volgende h2."""
    h2 = soup.find("h2", id=heading_text)
    if not h2:
        raise Exception(f"Heading '{heading_text}' niet gevonden")

    tables = []
    current = h2.parent.find_next_sibling()
    while current:
        if current.name == "table":
            tables.append(current)
        else:
            for t in current.find_all("table"):
                tables.append(t)
        if current.name == "div" and "mw-heading" in " ".join(current.get("class", [])):
            break
        current = current.find_next_sibling()

    return tables


def parse_quest_table(table, category):
    """Parse tabel op basis van aantal kolommen."""
    quests = []
    rows = table.find_all("tr")

    for row in rows[1:]:
        cols = row.find_all("td")

        # Free-to-play: id, name, difficulty, length, qp, series, release_date (7 cols)
        if len(cols) == 7:
            link = cols[1].find("a")
            quests.append({
                "category": category,
                "id": clean(cols[0].get_text()),
                "name": clean(cols[1].get_text()),
                "difficulty": clean(cols[2].get_text()),
                "length": clean(cols[3].get_text()),
                "quest_points": clean(cols[4].get_text()),
                "series": clean(cols[5].get_text()),
                "release_date": clean(cols[6].get_text()),
                "url": BASE_URL + link["href"] if link else ""
            })

        # Members: id, name, difficulty, length, qp, series, release_date + 1 extra (8 cols)
        elif len(cols) == 8:
            link = cols[1].find("a")
            quests.append({
                "category": category,
                "id": clean(cols[0].get_text()),
                "name": clean(cols[1].get_text()),
                "difficulty": clean(cols[2].get_text()),
                "length": clean(cols[3].get_text()),
                "quest_points": clean(cols[4].get_text()),
                "series": clean(cols[5].get_text()),
                "release_date": clean(cols[6].get_text()),
                "url": BASE_URL + link["href"] if link else ""
            })

        # Miniquests: name, difficulty, length, series, release_date, leagues_region
        elif len(cols) == 6:
            link = cols[0].find("a")
            quests.append({
                "category": category,
                "id": "",
                "name": clean(cols[0].get_text()),
                "difficulty": clean(cols[1].get_text()),
                "length": clean(cols[2].get_text()),
                "quest_points": "N/A",
                "series": clean(cols[3].get_text()),
                "release_date": clean(cols[4].get_text()),
                "url": BASE_URL + link["href"] if link else ""
            })

    return quests


# ── Detail-parsing (werkt op de HTML die de API teruggeeft) ─────────────────

def get_questdetails_field(soup, field_name):
    """Zoek een specifiek veld in de questdetails tabel."""
    table = soup.find("table", class_="questdetails")
    if not table:
        return None
    for row in table.find_all("tr"):
        th = row.find("th", class_="questdetails-header")
        td = row.find("td", class_="questdetails-info")
        if th and td and field_name.lower() in clean(th.get_text()).lower():
            return td
    return None


def parse_start_point(soup):
    td = get_questdetails_field(soup, "Start point")
    if not td:
        return ""
    for img in td.find_all("img"):
        img.decompose()
    for a in td.find_all("a", class_="mw-kartographer-maplink"):
        a.decompose()
    return clean(td.get_text())


def parse_skill_requirements(soup):
    skills = []
    seen = set()

    def extract_skills_from_td(td):
        for span in td.find_all("span", class_="scp"):
            skill = span.get("data-skill", "")
            level = span.get("data-level", "")
            if not skill or not level:
                continue
            if skill == "Quest points":
                continue
            key = (skill, level)
            if key in seen:
                continue
            seen.add(key)
            sup_texts = [clean(s.get_text()) for s in span.find_next_siblings("sup")]
            boostable = not any("not boostable" in t for t in sup_texts)
            try:
                skills.append({
                    "skill": skill,
                    "level": int(level.replace(",", "")),
                    "boostable": boostable
                })
            except ValueError:
                pass

    td_req = get_questdetails_field(soup, "Requirements")
    if td_req:
        extract_skills_from_td(td_req)

    td_items = get_questdetails_field(soup, "Items required")
    if td_items:
        extract_skills_from_td(td_items)

    return skills


def parse_quest_requirements(soup):
    td = get_questdetails_field(soup, "Requirements")
    if not td:
        return []
    quests = []
    for li in td.find_all("li"):
        text = clean(li.get_text())
        if li.find("span", class_="scp"):
            continue
        if any(skip in text for skip in ["Completion of", "Started the", "Kudos", "Quest points"]):
            continue
        link = li.find("a")
        if not link:
            continue
        href = link.get("href", "")
        if not href.startswith("/w/"):
            continue
        non_quest_prefixes = [
            "/w/Miniquest", "/w/Barbarian_Training", "/w/Ancient_Cavern",
            "/w/Chat", "/w/Update", "/w/File", "/w/Help", "/w/Category",
            "/w/Template", "/w/User", "/w/RuneScape", "/w/Kudos",
        ]
        if any(href.startswith(p) for p in non_quest_prefixes):
            continue
        name = clean(link.get_text())
        if not name or name[0].islower():
            continue
        quests.append({
            "name": name,
            "url": BASE_URL + href
        })
    return quests


def parse_item_requirements(soup):
    td = get_questdetails_field(soup, "Items required")
    if not td:
        return []
    items = []
    ul = td.find("ul")
    if not ul:
        return []
    for li in ul.find_all("li", recursive=False):
        li_copy = BeautifulSoup(str(li), "html.parser").find("li")
        nested_ul = li_copy.find("ul")
        if nested_ul:
            nested_ul.decompose()
        text = clean(li_copy.get_text())
        if text:
            items.append(text)
    return items


def parse_top_level_li(ul):
    """Pak alleen de directe <li> children van een <ul>, sla geneste <ul> over."""
    items = []
    for li in ul.find_all("li", recursive=False):
        li_copy = BeautifulSoup(str(li), "html.parser").find("li")
        for nested in li_copy.find_all("ul"):
            nested.decompose()
        text = clean(li_copy.get_text())
        if text:
            items.append(text)
    return items


def parse_rewards(soup):
    td = get_questdetails_field(soup, "Rewards")
    if not td:
        rewards_heading = soup.find("h2", id="Rewards")
        if not rewards_heading:
            return []
        current = rewards_heading.parent.find_next_sibling()
        while current:
            if current.name == "div" and "mw-heading" in " ".join(current.get("class", [])):
                break
            if current.name == "table" and "navbox" in " ".join(current.get("class", [])):
                current = current.find_next_sibling()
                continue
            if current.name == "ul":
                for navbox in current.find_all("table"):
                    navbox.decompose()
                return parse_top_level_li(current)
            current = current.find_next_sibling()
        return []
    for navbox in td.find_all("table"):
        navbox.decompose()
    ul = td.find("ul")
    if ul:
        return parse_top_level_li(ul)
    return [clean(li.get_text()) for li in td.find_all("li") if clean(li.get_text())]


def parse_enemies(soup):
    td = get_questdetails_field(soup, "Enemies to defeat")
    if not td:
        return []
    enemies = []
    for li in td.find_all("li"):
        enemies.append(clean(li.get_text()))
    return enemies


def fetch_quest_details(url):
    """Haal detailpagina op via de MediaWiki API en parse alle gevraagde velden."""
    page_title = url_to_page_title(url)
    try:
        html = fetch_html_via_api(page_title)
        soup = BeautifulSoup(html, "html.parser")
        return {
            "start_point": parse_start_point(soup),
            "skill_requirements": parse_skill_requirements(soup),
            "quest_requirements": parse_quest_requirements(soup),
            "item_requirements": parse_item_requirements(soup),
            "rewards": parse_rewards(soup),
            "enemies_to_defeat": parse_enemies(soup),
        }
    except Exception as e:
        print(f"  [WARN] Fout bij ophalen '{page_title}': {e}")
        return {
            "start_point": "",
            "skill_requirements": [],
            "quest_requirements": [],
            "item_requirements": [],
            "rewards": [],
            "enemies_to_defeat": [],
        }


# ── Hoofdscript ──────────────────────────────────────────────────────────────

response = requests.get(URL, headers=HEADERS, timeout=30)
print("Status:", response.status_code)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

# Zoek de exacte members heading ID dynamisch op
members_heading = None
for h2 in soup.find_all("h2"):
    h2_id = h2.get("id", "")
    if "embers" in h2_id:
        members_heading = h2_id
        break

if not members_heading:
    raise Exception("Geen members heading gevonden op de pagina!")

all_quests = []

for heading, category in [
    ("Free-to-play_quests", "free_to_play"),
    (members_heading, "members"),
    ("Miniquests", "miniquest"),
]:
    tables = get_tables_after_heading(soup, heading)
    for t in tables:
        parsed = parse_quest_table(t, category)
        all_quests.extend(parsed)

print(f"Gevonden: {len(all_quests)} quests. Details ophalen via API...")

for i, quest in enumerate(all_quests):
    if not quest.get("url"):
        print(f"  [{i+1}/{len(all_quests)}] Geen URL voor '{quest['name']}', overgeslagen")
        continue

    print(f"  [{i+1}/{len(all_quests)}] {quest['name']}")
    details = fetch_quest_details(quest["url"])
    quest.update(details)
    time.sleep(0.5)

with open("data/quests.json", "w", encoding="utf-8") as f:
    json.dump(all_quests, f, indent=2, ensure_ascii=False)

print(f"\nSaved {len(all_quests)} quests naar data/quests.json")# ---------------------------------------------------------------------------
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
