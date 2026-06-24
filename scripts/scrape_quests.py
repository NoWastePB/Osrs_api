import requests
from bs4 import BeautifulSoup
import json

URL = "https://oldschool.runescape.wiki/w/Quests/List"

BASE_URL = "https://oldschool.runescape.wiki"


def clean(text):
    return " ".join(text.strip().split())


def parse_table(table, category):
    quests = []

    rows = table.find_all("tr")[1:]

    for row in rows:
        cols = row.find_all("td")

        if len(cols) < 7:
            continue

        link = cols[1].find("a")

        quest = {
            "category": category,
            "id": clean(cols[0].text),
            "name": clean(cols[1].text),
            "difficulty": clean(cols[2].text),
            "length": clean(cols[3].text),
            "quest_points": clean(cols[4].text),
            "series": clean(cols[5].text),
            "release_date": clean(cols[6].text),
            "url": BASE_URL + link["href"]
        }

        quests.append(quest)

    return quests


headers = {
    "User-Agent": "Mozilla/5.0"
}

html = requests.get(URL, headers=headers).text

soup = BeautifulSoup(html, "html.parser")

tables = soup.select("table.oqg-table")

all_quests = []

all_quests.extend(
    parse_table(tables[0], "free_to_play")
)

all_quests.extend(
    parse_table(tables[1], "members")
)

all_quests.extend(
    parse_table(tables[2], "miniquest")
)

with open("data/quests.json", "w", encoding="utf-8") as f:
    json.dump(
        all_quests,
        f,
        indent=2,
        ensure_ascii=False
    )

print(f"Saved {len(all_quests)} quests")
