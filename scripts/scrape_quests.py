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
    current = current.find_next_sibling()
    while current:
        if current.name == "table":
            return current
        table = current.find("table")
        if table:
            return table
        if current.name in ("h2", "h3"):
            break
        current = current.find_next_sibling()

    raise Exception(f"Tabel na '{heading_text}' niet gevonden")

def parse_table(table, category):
    quests = []
    rows = table.find_all("tr")
    for row in rows[1:]:
        cols = row.find_all("td")
        if len(cols) < 7:
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
    return quests

headers = {
    "User-Agent": "OsrsQuestScraper/1.0 (contact: jouw@email.com)"
}

response = requests.get(URL, headers=headers, timeout=30)
print("Status:", response.status_code)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

free_table = get_table_after_heading(soup, "Free-to-play_quests")
members_table = get_table_after_heading(soup, "Members'_quests")
miniquests_table = get_table_after_heading(soup, "Miniquests")

all_quests = []
all_quests.extend(parse_table(free_table, "free_to_play"))
all_quests.extend(parse_table(members_table, "members"))
all_quests.extend(parse_table(miniquests_table, "miniquest"))

with open("data/quests.json", "w", encoding="utf-8") as f:
    json.dump(all_quests, f, indent=2, ensure_ascii=False)

print(f"Saved {len(all_quests)} quests")
