import json
import requests
from bs4 import BeautifulSoup

URL = "https://oldschool.runescape.wiki/w/Quests/List"
BASE_URL = "https://oldschool.runescape.wiki"


def clean(text):
    return " ".join(text.strip().split())


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

        # Miniquests: name, difficulty, length, series, release_date, leagues_region (laatste overslaan)
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


headers = {
    "User-Agent": "OsrsQuestScraper/1.0 (contact: jouw@email.com)"
}

response = requests.get(URL, headers=headers, timeout=30)
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

with open("data/quests.json", "w", encoding="utf-8") as f:
    json.dump(all_quests, f, indent=2, ensure_ascii=False)

print(f"Saved {len(all_quests)} quests")
