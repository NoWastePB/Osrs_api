import json
import requests
from bs4 import BeautifulSoup

URL = "https://oldschool.runescape.wiki/w/Quests/List"
BASE_URL = "https://oldschool.runescape.wiki"


def clean(text):
    return " ".join(text.strip().split())


def get_table_after_heading(soup, heading_text):
    h2 = soup.find("h2", id=heading_text)
    if not h2:
        raise Exception(f"Heading '{heading_text}' niet gevonden")

    current = h2.parent  # de <div class="mw-heading mw-heading2">
    print(f"\n[DEBUG] Gevonden heading: '{heading_text}'")
    print(f"[DEBUG] Parent tag: <{current.name} class='{current.get('class')}'>")

    sibling_count = 0
    current = current.find_next_sibling()
    while current:
        sibling_count += 1
        print(f"[DEBUG]   Sibling #{sibling_count}: <{current.name}> class='{current.get('class', '')}'")

        if current.name == "table":
            print(f"[DEBUG]   -> Directe tabel gevonden!")
            return current

        table = current.find("table")
        if table:
            print(f"[DEBUG]   -> Tabel gevonden binnen <{current.name}>")
            return table

        if current.name == "div" and "mw-heading" in " ".join(current.get("class", [])):
            print(f"[DEBUG]   -> Volgende heading bereikt, stoppen")
            break

        current = current.find_next_sibling()

    raise Exception(f"Tabel na '{heading_text}' niet gevonden")


def parse_table(table, category):
    quests = []
    rows = table.find_all("tr")
    print(f"\n[DEBUG] parse_table '{category}': {len(rows)} rijen gevonden")

    for i, row in enumerate(rows[1:], start=1):
        cols = row.find_all("td")
        print(f"[DEBUG]   Rij {i}: {len(cols)} kolommen | tekst: {[clean(c.get_text())[:20] for c in cols[:3]]}")
        if len(cols) < 7:
            print(f"[DEBUG]   -> Overgeslagen (minder dan 7 kolommen)")
            continue
        link = cols[1].find("a")
        quest = {
            "category": category,
            "id": clean(cols[0].get_text()),
            "name": clean(cols[1].get_text()),
            "difficulty": clean(cols[2].get_text()),
            "length": clean(cols[3].get_text()),
            "quest_points": clean(cols[4].get_text()),
            "series": clean(cols[5].get_text()),
            "release_date": clean(cols[6].get_text()),
            "url": BASE_URL + link["href"] if link else ""
        }
        quests.append(quest)

    print(f"[DEBUG]   -> {len(quests)} quests geparsed voor '{category}'")
    return quests


headers = {
    "User-Agent": "OsrsQuestScraper/1.0 (contact: jouw@email.com)"
}

response = requests.get(URL, headers=headers, timeout=30)
print("Status:", response.status_code)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

# Debug: print alle h2 IDs op de pagina
print("\n[DEBUG] Alle h2 elementen op de pagina:")
for h2 in soup.find_all("h2"):
    print(f"  id='{h2.get('id')}' | tekst='{h2.get_text().strip()}'")

free_table = get_table_after_heading(soup, "Free-to-play_quests")
members_table = get_table_after_heading(soup, "Members'_quests")
miniquests_table = get_table_after_heading(soup, "Miniquests")

all_quests = []
all_quests.extend(parse_table(free_table, "free_to_play"))
all_quests.extend(parse_table(members_table, "members"))
all_quests.extend(parse_table(miniquests_table, "miniquest"))

with open("data/quests.json", "w", encoding="utf-8") as f:
    json.dump(all_quests, f, indent=2, ensure_ascii=False)

print(f"\nSaved {len(all_quests)} quests")
