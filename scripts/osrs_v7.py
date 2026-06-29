import asyncio
import aiohttp
import requests
import json
import time
import hashlib
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime

BASE = "https://oldschool.runescape.wiki/api.php"

HEADERS = {
    "User-Agent": "OSRS-V7-Engine (contact: you@example.com)"
}

DATA_DIR = Path("data")
GRAPH_DIR = Path("graph")
META_DIR = Path("meta")

DATA_DIR.mkdir(parents=True, exist_ok=True)
GRAPH_DIR.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------------
# UTIL
# ----------------------------

def now():
    return datetime.utcnow().isoformat()


def safe_int(v):
    try:
        return int(v)
    except:
        return None


def make_id(name):
    return name.lower().replace(" ", "_")


def hash_data(obj):
    return hashlib.md5(str(obj).encode()).hexdigest()


# ----------------------------
# GE MAP
# ----------------------------

def load_ge():
    url = "https://prices.runescape.wiki/api/v1/osrs/mapping"
    data = requests.get(url).json()

    return {i["name"].lower(): i for i in data}


# ----------------------------
# CATEGORY FETCH
# ----------------------------

async def get_category(session, category):
    pages = []

    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": f"Category:{category}",
        "cmlimit": "max",
        "format": "json"
    }

    while True:
        async with session.get(BASE, params=params) as r:
            data = await r.json()

        pages.extend(data["query"]["categorymembers"])

        if "continue" not in data:
            break

        params["cmcontinue"] = data["continue"]["cmcontinue"]

    return pages


# ----------------------------
# PAGE FETCH
# ----------------------------

async def fetch_page(session, title):
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "format": "json"
    }

    async with session.get(BASE, params=params) as r:
        data = await r.json()

    return data["parse"]["text"]["*"]


# ----------------------------
# PARSERS
# ----------------------------

def extract_infobox(html):
    soup = BeautifulSoup(html, "html.parser")

    box = soup.find("table")
    if not box:
        return {}

    data = {}

    for row in box.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) == 2:
            k = cols[0].text.strip().lower()
            v = cols[1].text.strip()
            data[k] = v

    return data


def extract_drops(html):
    soup = BeautifulSoup(html, "html.parser")

    drops = []

    for table in soup.find_all("table"):
        text = table.get_text(" ", strip=True).lower()

        if "drop" not in text:
            continue

        rows = table.find_all("tr")

        headers = None

        for i, row in enumerate(rows):
            cols = [c.text.strip() for c in row.find_all(["td", "th"])]

            if not cols:
                continue

            if headers is None:
                headers = cols
                continue

            if len(cols) >= 2:
                item = cols[0]
                qty = cols[1]

                rate = None
                for c in cols:
                    if "%" in c:
                        rate = c

                drops.append({
                    "item": item,
                    "quantity": qty,
                    "rate": rate
                })

    return drops


# ----------------------------
# NORMALIZATION
# ----------------------------

def normalize_monster(name, infobox, drops, ge_map):

    ge = ge_map.get(name.lower(), {})

    return {
        "id": make_id(name),
        "name": name,
        "type": "monster",

        "combat": safe_int(infobox.get("combat")),
        "hp": safe_int(infobox.get("hitpoints")),

        "ge": ge if ge else None,

        "drops": [
            {
                "item": d["item"],
                "quantity": d["quantity"],
                "rate": d["rate"]
            }
            for d in drops
        ],

        "hash": hash_data(infobox) + hash_data(drops),
        "updated_at": now()
    }


# ----------------------------
# GRAPH BUILDER
# ----------------------------

def build_graph(monsters):

    npc_drops = {}
    item_sources = {}

    for m in monsters:

        npc = m["name"]
        npc_drops[npc] = []

        for d in m["drops"]:
            item = d["item"]

            npc_drops[npc].append(item)

            if item not in item_sources:
                item_sources[item] = []

            item_sources[item].append(npc)

    return {
        "npc_drops": npc_drops,
        "item_sources": item_sources
    }


# ----------------------------
# PIPELINE
# ----------------------------

async def run():

    ge_map = load_ge()

    async with aiohttp.ClientSession(headers=HEADERS) as session:

        pages = await get_category(session, "Bestiary")

        monsters = []

        for i, p in enumerate(pages[:300]):  # safe cap

            title = p["title"]

            try:
                html = await fetch_page(session, title)

                infobox = extract_infobox(html)
                drops = extract_drops(html)

                if not infobox and not drops:
                    continue

                monster = normalize_monster(
                    title,
                    infobox,
                    drops,
                    ge_map
                )

                monsters.append(monster)

                print(f"[{i}] {title}")

                await asyncio.sleep(0.1)

            except Exception as e:
                print("error", title, e)

        # GRAPH
        graph = build_graph(monsters)

        # SAVE DATA
        with open(DATA_DIR / "monsters.json", "w") as f:
            json.dump(monsters, f, indent=2)

        with open(GRAPH_DIR / "npc_drops.json", "w") as f:
            json.dump(graph["npc_drops"], f, indent=2)

        with open(GRAPH_DIR / "item_sources.json", "w") as f:
            json.dump(graph["item_sources"], f, indent=2)

        # META
        with open(META_DIR / "last_run.json", "w") as f:
            json.dump({
                "updated_at": now(),
                "monster_count": len(monsters)
            }, f, indent=2)


if __name__ == "__main__":
    asyncio.run(run())
