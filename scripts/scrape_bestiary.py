"""
OSRS Bestiary Scraper
Gebruikt de MediaWiki API om bot-detectie te vermijden.
Output: data/monsters.json
"""

import json
import time
import random
import requests
from urllib.parse import unquote
from bs4 import BeautifulSoup

BASE_URL = "https://oldschool.runescape.wiki"
API_URL = "https://oldschool.runescape.wiki/api.php"

BESTIARY_PAGES = [
    "Bestiary/Levels_1_to_10",
    "Bestiary/Levels_11_to_20",
    "Bestiary/Levels_21_to_30",
    "Bestiary/Levels_31_to_40",
    "Bestiary/Levels_41_to_50",
    "Bestiary/Levels_51_to_60",
    "Bestiary/Levels_61_to_70",
    "Bestiary/Levels_71_to_80",
    "Bestiary/Levels_81_to_90",
    "Bestiary/Levels_91_to_100",
    "Bestiary/Levels_101_to_110",
    "Bestiary/Levels_111_to_120",
    "Bestiary/Levels_121_to_130",
    "Bestiary/Levels_131_to_140",
    "Bestiary/Levels_141_to_150",
    "Bestiary/Levels_151_to_160",
    "Bestiary/Levels_161_to_170",
    "Bestiary/Levels_171_to_180",
    "Bestiary/Levels_181_to_190",
    "Bestiary/Levels_191_to_200",
    "Bestiary/Levels_201_to_400",
    "Bestiary/Levels_higher_than_400",
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "OSRSBestiaryScraper/1.0 "
        "(https://github.com/pietjetse/osrs-data; educational project)"
    ),
    "Accept": "application/json",
})


def clean(text):
    return " ".join(text.strip().split())


def api_get(page, retries=3):
    """
    Haal een wikipagina op via de MediaWiki API.
    Geeft een BeautifulSoup object terug van de geparsede HTML.
    """
    params = {
        "action": "parse",
        "page": page,
        "prop": "text",
        "format": "json",
        "formatversion": "2",
    }

    for attempt in range(retries):
        time.sleep(random.uniform(0.3, 0.6))
        try:
            resp = SESSION.get(API_URL, params=params, timeout=20)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                print(f"  [429] Rate limited. Wacht {retry_after}s...")
                time.sleep(retry_after)
                continue

            if resp.status_code == 503:
                wait = 10 * (attempt + 1)
                print(f"  [503] Server onbeschikbaar. Wacht {wait}s...")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            data = resp.json()

            if "error" in data:
                print(f"  [API ERROR] {data['error'].get('info', data['error'])}")
                return None

            html = data["parse"]["text"]
            return BeautifulSoup(html, "html.parser")

        except requests.exceptions.ConnectionError as e:
            wait = 5 * (attempt + 1)
            print(f"  [WARN] Verbindingsfout ({e}). Wacht {wait}s...")
            time.sleep(wait)
        except (KeyError, ValueError) as e:
            print(f"  [WARN] Onverwachte API response ({e})")
            return None

    return None


# ── Bestiary lijst scraper ────────────────────────────────────────────────────

def scrape_page(page):
    """Haal alle monsters op van één bestiary-pagina via de API."""
    print(f"  Scraping: {page}")

    soup = api_get(page)
    if not soup:
        print(f"    ⚠ Kon {page} niet ophalen")
        return []

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
        all_tables = soup.find_all("table")
        print(f"    ⚠ Geen tabel gevonden op {page} ({len(all_tables)} tabellen op pagina)")
        for i, tbl in enumerate(all_tables[:5]):
            header_row = tbl.find("tr")
            ths = header_row.find_all("th") if header_row else []
            total_cols = sum(int(th.get("colspan", 1)) for th in ths)
            print(f"       Tabel {i}: class={tbl.get('class', [])}, header_cols={total_cols}")
        return []

    rows = table.find_all("tr")
    monsters = []

    for row in rows[1:]:
        if row.find("th"):
            continue
        tds = row.find_all("td")
        if len(tds) < 17:
            continue

        name_cell = tds[1]
        link = name_cell.find("a")
        if not link:
            continue

        name = clean(link.get_text())
        # De API geeft relatieve links terug, haal de paginanaam op
        href = link.get("href", "")
        # href is bv "/w/Goblin" — strip de /w/ prefix voor de API
        # Decodeer URL-encoding (%27 -> ', %28 -> (, etc.) voor de API
        wiki_page = unquote(href.replace("/w/", "")).replace("_", " ") if href.startswith("/w/") else ""
        wiki_url = BASE_URL + href

        italic = name_cell.find("i")
        variant = clean(italic.get_text()) if italic else ""

        members_img = tds[2].find("img")
        if members_img:
            alt = members_img.get("alt", "")
            members = "Members" if "Members" in alt else "F2P"
        else:
            members = ""

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
            "wiki_page": wiki_page,
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

    for row in infobox.find_all("tr"):
        th = row.find("th")
        td = row.find("td")
        if not th or not td:
            continue
        key = clean(th.get_text())
        mapped = key_map.get(key)
        if mapped:
            info[mapped] = clean(td.get_text())

    return info


def get_section_name(tbl):
    """Zoek de dichtstbijzijnde h2/h3 boven de tabel voor de sectienaam."""
    for sibling in tbl.find_all_previous(["h2", "h3"]):
        for edit in sibling.find_all("span", class_="mw-editsection"):
            edit.decompose()
        text = clean(sibling.get_text())
        if text:
            return text
    return ""


def parse_single_drop_table(tbl):
    """Parse één drop tabel en geef een lijst van drops terug."""
    drops = []
    section = get_section_name(tbl)

    for row in tbl.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 5:
            continue

        item_link = tds[1].find("a")
        item_name = clean(item_link.get_text()) if item_link else clean(tds[1].get_text())
        item_url = BASE_URL + item_link.get("href", "") if item_link else ""

        quantity = clean(tds[2].get_text())

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
            "section": section,
        })

    return drops


def parse_drops(soup):
    """Verzamel drops uit ALLE drop tabellen op de pagina."""
    all_drops = []
    seen_keys = set()

    for tbl in soup.find_all("table"):
        if not tbl.find("th", class_="drops-img-header"):
            continue
        for drop in parse_single_drop_table(tbl):
            key = (drop["item"], drop["quantity"], drop["rarity_fraction"])
            if key not in seen_keys:
                seen_keys.add(key)
                all_drops.append(drop)

    return all_drops


def fetch_monster_details(wiki_page):
    """Haal detailpagina op via API en parse infobox en drops."""
    if not wiki_page:
        return {"drops": []}
    soup = api_get(wiki_page)
    if not soup:
        print(f"  [WARN] Kon '{wiki_page}' niet ophalen")
        return {"drops": []}
    info = parse_infobox(soup)
    info["drops"] = parse_drops(soup)
    return info


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

print(f"\nGevonden: {len(all_monsters)} monsters. Details ophalen...\n")

# Groepeer monsters op wiki_page zodat elke pagina maar één keer opgehaald wordt.
# Bijvoorbeeld: "Goblin (Level 2)", "Goblin (Level 5)" etc. delen dezelfde pagina.
page_cache = {}  # wiki_page -> details dict
unique_pages = sorted(set(
    m["wiki_page"] for m in all_monsters if m.get("wiki_page")
))

print(f"Unieke wiki pagina's te ophalen: {len(unique_pages)}\n")

for i, wiki_page in enumerate(unique_pages):
    print(f"  [{i+1}/{len(unique_pages)}] {wiki_page}")
    page_cache[wiki_page] = fetch_monster_details(wiki_page)

# Wijs de gecachede details toe aan alle monsters
for monster in all_monsters:
    wiki_page = monster.get("wiki_page", "")
    if wiki_page and wiki_page in page_cache:
        monster.update(page_cache[wiki_page])

import os
os.makedirs("data", exist_ok=True)

with open("data/monsters.json", "w", encoding="utf-8") as f:
    json.dump(all_monsters, f, indent=2, ensure_ascii=False)

print(f"\nSaved {len(all_monsters)} monsters naar data/monsters.json")
