"""
OSRS Bestiary Scraper
Haalt alle monsters op van de OSRS Wiki Bestiary pagina's per level-range.
Voor elk monster worden ook de detailpagina (infobox + drops) opgehaald.
Output: data/monsters.json
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


def clean(text):
    return " ".join(text.strip().split())


# ── Bestiary lijst scraper ────────────────────────────────────────────────────

def scrape_page(path):
    """Haal alle monsters op van één bestiary-pagina."""
    url = BASE_URL + path
    print(f"  Scraping: {url}")

    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Zoek de wikitable met 17+ kolommen in de headerrij
    table = None
    for tbl in soup.find_all("table", class_="wikitable"):
        header_row = tbl.find("tr")
        if not header_row:
            continue
        total_cols = sum(int(th.get("colspan", 1)) for th in header_row.find_all("th"))
        if total_cols >= 17:
            table = tbl
            break

    if not table:
        print(f"    ⚠ Geen tabel gevonden op {path}")
        return []

    rows = table.find_all("tr")
    monsters = []

    for row in rows[1:]:
        if row.find("th"):
            continue
        tds = row.find_all("td")
        if len(tds) < 17:
            continue

        # td[1]: naam en variant
        name_cell = tds[1]
        link = name_cell.find("a")
        if not link:
            continue

        name = clean(link.get_text())
        wiki_url = BASE_URL + link.get("href", "")
        italic = name_cell.find("i")
        variant = clean(italic.get_text()) if italic else ""

        # td[2]: members
        members_img = tds[2].find("img")
        if members_img:
            alt = members_img.get("alt", "")
            members = "Members" if "Members" in alt else "F2P"
        else:
            members = ""

        # td[17]: elemental weakness
        elemental_weakness = ""
        if len(tds) >= 18:
            weak_img = tds[17].find("img")
            if weak_img:
                weakness_type = weak_img.get("alt", "").replace(" elemental weakness", "").strip()
                percentage = clean(tds[17].get_text())
                elemental_weakness = f"{weakness_type} {percentage}" if weakness_type else ""

        monsters.append({
            "name": name,
            "variant": variant,
            "wiki_url": wiki_url,
            "members": members,
            "combat_level": clean(tds[3].get_text()),
            "hitpoints": clean(tds[4].get_text()),
            "attack_level": clean(tds[5].get_text()),
            "defence_level": clean(tds[6].get_text()),
            "magic_level": clean(tds[7].get_text()),
            "ranged_level": clean(tds[8].get_text()),
            "stab_defence": clean(tds[9].get_text()),
            "slash_defence": clean(tds[10].get_text()),
            "crush_defence": clean(tds[11].get_text()),
            "magic_defence": clean(tds[12].get_text()),
            "light_ranged_defence": clean(tds[13].get_text()),
            "standard_ranged_defence": clean(tds[14].get_text()),
            "heavy_ranged_defence": clean(tds[15].get_text()),
            "flat_armour": clean(tds[16].get_text()),
            "elemental_weakness": elemental_weakness,
        })

    return monsters


# ── Detail pagina scraper ─────────────────────────────────────────────────────

def parse_infobox(soup):
    """Parse de infobox-monster tabel voor extra velden."""
    info = {}
    infobox = soup.find("table", class_="infobox-monster")
    if not infobox:
        return info

    for row in infobox.find_all("tr"):
        th = row.find("th")
        td = row.find("td")
        if not th or not td:
            continue
        # Haal de tekst van de header op (soms alleen een afbeelding)
        key = clean(th.get_text())
        if not key:
            continue
        value = clean(td.get_text())

        key_map = {
            "XP bonus": "xp_bonus",
            "Max hit": "max_hit",
            "Aggressive": "aggressive",
            "Poisonous": "poisonous",
            "Attack style": "attack_style",
            "Attack speed": "attack_speed",
            "Respawn time": "respawn_time",
            "Size": "size",
            "Examine": "examine",
            "Monster ID": "monster_id",
        }
        mapped = key_map.get(key)
        if mapped:
            info[mapped] = value

    return info


def parse_drops(soup):
    """Parse de drops tabel op basis van de drops-img-header klasse."""
    drops = []

    # Zoek de tabel met de drops-img-header th
    drop_table = None
    for tbl in soup.find_all("table"):
        if tbl.find("th", class_="drops-img-header"):
            drop_table = tbl
            break

    if not drop_table:
        return drops

    for row in drop_table.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 5:
            continue

        # td[0] = afbeelding, td[1] = itemnaam, td[2] = quantity,
        # td[3] = rarity, td[4] = GE price, td[5] = high alch
        item_cell = tds[1]
        item_link = item_cell.find("a")
        item_name = clean(item_link.get_text()) if item_link else clean(item_cell.get_text())
        item_url = BASE_URL + item_link.get("href", "") if item_link else ""

        quantity = clean(tds[2].get_text())

        # Rarity: lees de data-drop-fraction of data-drop-percent attributen
        rarity_span = tds[3].find("span", attrs={"data-drop-fraction": True})
        if rarity_span:
            rarity_fraction = rarity_span.get("data-drop-fraction", "")
            rarity_percent = rarity_span.get("data-drop-percent", "")
        else:
            rarity_fraction = clean(tds[3].get_text())
            rarity_percent = ""

        ge_price = clean(tds[4].get_text()) if len(tds) > 4 else ""
        high_alch = clean(tds[5].get_text()) if len(tds) > 5 else ""

        if not item_name:
            continue

        drops.append({
            "item": item_name,
            "item_url": item_url,
            "quantity": quantity,
            "rarity_fraction": rarity_fraction,
            "rarity_percent": rarity_percent,
            "ge_price": ge_price,
            "high_alch": high_alch,
        })

    return drops


def fetch_monster_details(url):
    """Haal detailpagina op en parse infobox en drops."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        info = parse_infobox(soup)
        info["drops"] = parse_drops(soup)
        return info
    except Exception as e:
        print(f"  [WARN] Fout bij ophalen {url}: {e}")
        return {"drops": []}


# ── Hoofdscript ───────────────────────────────────────────────────────────────

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

print(f"\nGevonden: {len(all_monsters)} monsters. Details ophalen...\n")

for i, monster in enumerate(all_monsters):
    if not monster.get("wiki_url"):
        print(f"  [{i+1}/{len(all_monsters)}] Geen URL voor '{monster['name']}', overgeslagen")
        continue

    print(f"  [{i+1}/{len(all_monsters)}] {monster['name']} {monster.get('variant', '')}")
    details = fetch_monster_details(monster["wiki_url"])
    monster.update(details)
    time.sleep(0.5)

import os
os.makedirs("data", exist_ok=True)

with open("data/monsters.json", "w", encoding="utf-8") as f:
    json.dump(all_monsters, f, indent=2, ensure_ascii=False)

print(f"\nSaved {len(all_monsters)} monsters naar data/monsters.json")
