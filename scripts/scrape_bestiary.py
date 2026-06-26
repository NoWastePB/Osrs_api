"""
OSRS Bestiary Scraper
Haalt alle monsters op van de OSRS Wiki Bestiary pagina's per level-range.
Output: data/monsters.json

Fix: tabelheaders bevatten alleen afbeeldingen met title-attributen,
     geen zichtbare tekst. We lezen de img alt of de span title.
"""

import json
import time
import requests
from bs4 import BeautifulSoup

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
    "User-Agent": "OSRSBestiaryScraper/1.0 (educational project)"
}

# Mapping van de img alt / zichtbare tekst naar veldnaam
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


def clean(text):
    return " ".join(text.strip().split())


def get_th_label(th):
    """
    Haal de kolomlabel op uit een <th>-element.
    Probeert in volgorde:
      1. Zichtbare tekst (voor 'Monster', 'Members', 'Flat armour')
      2. img[alt] attribuut
      3. span[title] attribuut
    """
    text = clean(th.get_text())
    if text and text in COLUMN_MAP:
        return text

    img = th.find("img")
    if img:
        for attr in ("alt", "title"):
            val = img.get(attr, "").strip()
            if val and val in COLUMN_MAP:
                return val

    span = th.find("span", title=True)
    if span:
        val = span["title"].strip()
        if val and val in COLUMN_MAP:
            return val

    return None


def parse_header_indices(header_row):
    """Bouw een mapping van kolomindex -> veldnaam op basis van de headerrij."""
    indices = {}
    col = 0
    for cell in header_row.find_all("th"):
        colspan = int(cell.get("colspan", 1))
        label = get_th_label(cell)
        if label:
            indices[col] = COLUMN_MAP[label]
        col += colspan
    return indices


def parse_members(cell):
    """Bepaal F2P of Members op basis van de afbeelding in de cel."""
    img = cell.find("img")
    if not img:
        return ""
    alt = img.get("alt", "")
    if "Members" in alt:
        return "Members"
    if "Free" in alt or "F2P" in alt:
        return "F2P"
    return alt


def parse_elemental_weakness(cell):
    """Extraheer zwakheid type en percentage uit de laatste kolom."""
    img = cell.find("img")
    if not img:
        return ""
    weakness_type = img.get("alt", "").replace(" elemental weakness", "").strip()
    text = clean(cell.get_text())
    if weakness_type and text:
        return f"{weakness_type} {text}"
    return weakness_type


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
                link = cell.find("a")
                if link:
                    monster["name"] = clean(link.get_text())
                    monster["wiki_url"] = BASE_URL + link.get("href", "")
                    italic = cell.find("i")
                    monster["variant"] = clean(italic.get_text()) if italic else ""
                else:
                    monster["name"] = clean(cell.get_text())
                    monster["wiki_url"] = ""
                    monster["variant"] = ""
            elif field == "members":
                monster["members"] = parse_members(cell)
            elif field == "elemental_weakness":
                monster["elemental_weakness"] = parse_elemental_weakness(cell)
            else:
                monster[field] = clean(cell.get_text())

        col += colspan

    return monster if monster.get("name") else None


def scrape_page(path):
    """Haal alle monsters op van één bestiary-pagina."""
    url = BASE_URL + path
    print(f"  Scraping: {url}")

    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Zoek de wikitable waarvan de eerste header 'Monster' is
    table = None
    for tbl in soup.find_all("table", class_="wikitable"):
        header_row = tbl.find("tr")
        if not header_row:
            continue
        for th in header_row.find_all("th"):
            if get_th_label(th) == "Monster":
                table = tbl
                break
        if table:
            break

    if not table:
        print(f"    ⚠ Geen tabel gevonden op {path}")
        return []

    rows = table.find_all("tr")
    col_map = parse_header_indices(rows[0])

    monsters = []
    for row in rows[1:]:
        if row.find("th"):  # sla extra headerrijen over
            continue
        monster = parse_monster_row(row, col_map)
        if monster:
            monsters.append(monster)

    return monsters


# ── Hoofdscript ──────────────────────────────────────────────────────────────

all_monsters = []
seen = set()

print(f"Start scrapen van {len(BESTIARY_PAGES)} pagina's...\n")

for page in BESTIARY_PAGES:
    monsters = scrape_page(page)
    new_count = 0
    for m in monsters:
        key = (m.get("name", ""), m.get("variant", ""), m.get("combat_level", ""))
        if key not in seen:
            seen.add(key)
            all_monsters.append(m)
            new_count += 1
    print(f"    ✓ {new_count} monsters toegevoegd (totaal: {len(all_monsters)})")
    time.sleep(0.5)

print(f"\nGevonden: {len(all_monsters)} monsters")

import os
os.makedirs("data", exist_ok=True)

with open("data/monsters.json", "w", encoding="utf-8") as f:
    json.dump(all_monsters, f, indent=2, ensure_ascii=False)

print(f"Saved {len(all_monsters)} monsters naar data/monsters.json")
