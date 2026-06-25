"""
OSRS Bestiary Scraper
Haalt alle monsters op van de OSRS Wiki Bestiary pagina's per level-range.
Output: osrs_monsters.json en osrs_monsters.csv
"""

import requests
from bs4 import BeautifulSoup
import json
import csv
import time

BASE_URL = "https://oldschool.runescape.wiki"

BESTIARY_PAGES = [
    "/w/Bestiary/Levels_1_to_10",
    "/w/Bestiary/Levels_11_to_20",
    "/w/Bestiary/Levels_21_to_30",
    "/w/Bestiary/Levels_31_to_40",
    "/w/Bestiary/Levels_41_to_50",
    "/w/Bestiary/Levels_51_to_60",
    "/w/Bestiary/Levels_61_to_70",
    "/w/Bestiary/Levels_71_to_80",
    "/w/Bestiary/Levels_81_to_90",
    "/w/Bestiary/Levels_91_to_100",
    "/w/Bestiary/Levels_101_to_110",
    "/w/Bestiary/Levels_111_to_120",
    "/w/Bestiary/Levels_121_to_130",
    "/w/Bestiary/Levels_131_to_140",
    "/w/Bestiary/Levels_141_to_150",
    "/w/Bestiary/Levels_151_to_160",
    "/w/Bestiary/Levels_161_to_170",
    "/w/Bestiary/Levels_171_to_180",
    "/w/Bestiary/Levels_181_to_190",
    "/w/Bestiary/Levels_191_to_200",
    "/w/Bestiary/Levels_201_to_400",
    "/w/Bestiary/Levels_higher_than_400",
]

HEADERS = {
    "User-Agent": "OSRSBestiaryScraper/1.0 (educational project; contact: piet@example.com)"
}

# Kolomnamen op basis van de tabelheaders
COLUMN_MAP = {
    "Monster": "name",
    "Members": "members",
    "Combat level": "combat_level",
    "Hitpoints": "hitpoints",
    "Attack level": "attack_level",
    "Defence level": "defence_level",
    "Magic level": "magic_level",
    "Ranged level": "ranged_level",
    "Stab defence": "stab_defence",
    "Slash defence": "slash_defence",
    "Crush defence": "crush_defence",
    "Magic defence": "magic_defence",
    "Light Ranged defence": "light_ranged_defence",
    "Standard Ranged defence": "standard_ranged_defence",
    "Heavy Ranged defence": "heavy_ranged_defence",
    "Flat armour": "flat_armour",
    "Elemental weakness": "elemental_weakness",
}


def parse_header_indices(header_row):
    """Bouw een mapping van kolomindex -> veldnaam op basis van de headerrij."""
    indices = {}
    cells = header_row.find_all("th")
    col = 0
    for cell in cells:
        colspan = int(cell.get("colspan", 1))
        text = cell.get_text(strip=True)
        field = COLUMN_MAP.get(text)
        if field:
            indices[col] = field
        col += colspan
    return indices


def parse_monster_row(row, col_map):
    """Parseer één monsterrij naar een dict."""
    cells = row.find_all(["td", "th"])
    if not cells:
        return None

    monster = {}
    col = 0

    for cell in cells:
        colspan = int(cell.get("colspan", 1))
        field = col_map.get(col)

        if field:
            if field == "name":
                # Naam staat in de tweede td (eerste is het plaatje)
                link = cell.find("a")
                if link:
                    monster["name"] = link.get_text(strip=True)
                    monster["wiki_url"] = BASE_URL + link["href"]
                else:
                    monster["name"] = cell.get_text(strip=True)
                    monster["wiki_url"] = ""
            elif field == "members":
                link = cell.find("a")
                if link:
                    monster["members"] = link.get_text(strip=True)
                else:
                    monster["members"] = cell.get_text(strip=True)
            else:
                monster[field] = cell.get_text(strip=True)

        col += colspan

    return monster if "name" in monster and monster["name"] else None


def scrape_page(path):
    """Haal alle monsters op van één bestiary-pagina."""
    url = BASE_URL + path
    print(f"  Scraping: {url}")

    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Zoek de hoofdtabel (de tabel met Monster als eerste header)
    table = None
    for tbl in soup.find_all("table", class_="wikitable"):
        first_th = tbl.find("th")
        if first_th and "Monster" in first_th.get_text():
            table = tbl
            break

    if not table:
        print(f"    ⚠ Geen tabel gevonden op {path}")
        return []

    rows = table.find_all("tr")
    if not rows:
        return []

    # Eerste rij = headers
    col_map = parse_header_indices(rows[0])

    monsters = []
    # Soms zijn er twee headerrijen (hoofdrij + subrij met afbeelding)
    data_start = 1
    if rows[1].find("th"):
        data_start = 2

    for row in rows[data_start:]:
        monster = parse_monster_row(row, col_map)
        if monster:
            monsters.append(monster)

    return monsters


def main():
    all_monsters = []
    seen_names = set()

    print(f"Start scrapen van {len(BESTIARY_PAGES)} pagina's...\n")

    for page in BESTIARY_PAGES:
        monsters = scrape_page(page)
        new_count = 0
        for m in monsters:
            key = (m.get("name", ""), m.get("combat_level", ""))
            if key not in seen_names:
                seen_names.add(key)
                all_monsters.append(m)
                new_count += 1
        print(f"    ✓ {new_count} monsters toegevoegd (totaal: {len(all_monsters)})")
        time.sleep(0.5)  # Wees vriendelijk voor de wiki

    print(f"\nTotaal unieke monsters gevonden: {len(all_monsters)}")

    # Sla op als JSON
    with open("osrs_monsters.json", "w", encoding="utf-8") as f:
        json.dump(all_monsters, f, ensure_ascii=False, indent=2)
    print("✓ Opgeslagen als osrs_monsters.json")

    # Sla op als CSV
    if all_monsters:
        fieldnames = list(all_monsters[0].keys())
        # Zorg dat alle records dezelfde velden hebben
        all_fields = set()
        for m in all_monsters:
            all_fields.update(m.keys())
        all_fields = ["name", "wiki_url", "members", "combat_level", "hitpoints",
                      "attack_level", "defence_level", "magic_level", "ranged_level",
                      "stab_defence", "slash_defence", "crush_defence", "magic_defence",
                      "light_ranged_defence", "standard_ranged_defence",
                      "heavy_ranged_defence", "flat_armour", "elemental_weakness"]

        with open("osrs_monsters.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_monsters)
        print("✓ Opgeslagen als osrs_monsters.csv")


if __name__ == "__main__":
    main()
