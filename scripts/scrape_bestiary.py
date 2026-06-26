"""
OSRS Bestiary Scraper
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


def scrape_page(path):
    """Haal alle monsters op van één bestiary-pagina."""
    url = BASE_URL + path
    print(f"  Scraping: {url}")

    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Zoek de wikitable met monsterdata
    table = None
    for tbl in soup.find_all("table", class_="wikitable"):
        # De monstertabel heeft altijd een img met alt="Members" of "Free-to-play"
        # in de derde kolom van data-rijen. Veiliger: zoek de tabel met
        # veel kolommen (17+) in de headerrij.
        header_row = tbl.find("tr")
        if not header_row:
            continue
        ths = header_row.find_all("th")
        # Tel het totaal aantal kolommen (rekening houdend met colspan)
        total_cols = sum(int(th.get("colspan", 1)) for th in ths)
        if total_cols >= 17:
            table = tbl
            break

    if not table:
        print(f"    ⚠ Geen tabel gevonden op {path}")
        return []

    rows = table.find_all("tr")

    # Bouw kolomindices op basis van img alt-teksten in de headerrij
    # De tabel heeft colspan=2 op "Monster" dus kolom 0 = afbeelding, kolom 1 = naam
    # We slaan de colspan correct bij door de werkelijke td-positie te gebruiken.
    # Eenvoudiger: we parsen elke data-rij direct op positie van de tds.
    #
    # Kolomvolgorde (bepaald uit de HTML):
    # td[0] = monster afbeelding (overslaan)
    # td[1] = naam + variant
    # td[2] = members icon
    # td[3] = combat level
    # td[4] = hitpoints
    # td[5] = attack level
    # td[6] = defence level
    # td[7] = magic level
    # td[8] = ranged level
    # td[9] = stab defence
    # td[10] = slash defence
    # td[11] = crush defence
    # td[12] = magic defence
    # td[13] = light ranged defence
    # td[14] = standard ranged defence
    # td[15] = heavy ranged defence
    # td[16] = flat armour
    # td[17] = elemental weakness

    monsters = []

    for row in rows[1:]:
        # Sla headerrijen over
        if row.find("th"):
            continue

        tds = row.find_all("td")

        # Verwacht minimaal 17 kolommen
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
        members_cell = tds[2]
        members_img = members_cell.find("img")
        if members_img:
            alt = members_img.get("alt", "")
            members = "Members" if "Members" in alt else "F2P"
        else:
            members = ""

        # td[17]: elemental weakness (optioneel)
        elemental_weakness = ""
        if len(tds) >= 18:
            weak_cell = tds[17]
            weak_img = weak_cell.find("img")
            if weak_img:
                weakness_type = weak_img.get("alt", "").replace(" elemental weakness", "").strip()
                percentage = clean(weak_cell.get_text())
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
