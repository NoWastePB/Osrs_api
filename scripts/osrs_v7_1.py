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
    "User-Agent": "OSRS-V7.1-Engine (contact: you@example.com)"
}

DATA = Path("data")
GRAPH = Path("graph")
META = Path("meta")

DATA.mkdir(exist_ok=True, parents=True)
GRAPH.mkdir(exist_ok=True, parents=True)
META.mkdir(exist_ok=True, parents=True)


# ----------------------------
# UTIL
# ----------------------------

def now():
    return datetime.utcnow().isoformat()


def make_id(name):
    return name.lower().replace(" ", "_")


# ----------------------------
# GE MAP
# ----------------------------

def load_ge():
    url = "https://prices.runescape.wiki/api/v1/osrs/mapping"
    return {i["name"].lower(): i for i in requests.get(url).json()}


# ----------------------------
# FIX 1: REAL CATEGORY CRAWLER (RECURSIVE SAFE)
# ----------------------------

async def get_category(session, category):
    pages = []
    seen = set()

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

        for p in data["query"]["categorymembers"]:
            title = p["title"]

            if title not in seen:
                seen.add(title)
                pages.append(title)

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
# FIX 2: ROBUST INFBOX
# ----------------------------

def extract_infobox(html):
    soup = BeautifulSoup(html, "html.parser")

    box = soup.find("table", class_=lambda x: x and "infobox" in x)

    if not box:
        return {}

    data = {}

    for row in box.find_all("tr"):
        th = row.find("th")
        td = row.find("td")

        if th and td:
            key = th.text.strip().lower()
            val = td.text.strip()
            data[key] = val

    return data


# ----------------------------
# FIX 3: DROP PARSER (LESS FALSE POSITIVES)
# ----------------------------

def extract_drops(html):
    soup = BeautifulSoup(html, "html.parser")

    drops = []

    for table in soup.find_all("table"):
        text = table.get_text(" ", strip=True).lower()

        if "quantity" not in text and "drop" not in text:
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
# NORMALIZER
# ----------------------------

def normalize(name, infobox, drops, ge):

    ge_data = ge.get(name.lower())

    return {
        "id": make_id(name),
        "name": name,
        "infobox": infobox,
        "drops": drops,
        "ge": ge_data,
        "updated_at": now()
    }


# ----------------------------
# GRAPH BUILDER
# ----------------------------

def build_graph(monsters):

    npc_to_items = {}
    item_to_npcs = {}

    for m in monsters:

        npc = m["name"]
        npc_to_items[npc] = []

        for d in m["drops"]:
            item = d["item"]

            npc_to_items[npc].append(item)

            item_to_npcs.setdefault(item, []).append(npc)

    return {
        "npc_to_items": npc_to_items,
        "item_to_npcs": item_to_npcs
    }


# ----------------------------
# PIPELINE FIXED (IMPORTANT)
# ----------------------------

async def run():

    ge = load_ge()

    async with aiohttp.ClientSession(headers=HEADERS) as session:

        # FIXED CATEGORIES (THIS WAS YOUR MAIN ISSUE)
        categories = [
            "Monsters",
            "NPCs",
            "Items",
            "Quests"
        ]

        all_monsters = []

        for cat in categories:

            print("CATEGORY:", cat)

            pages = await get_category(session, cat)

            print("FOUND:", len(pages))

            for i, title in enumerate(pages[:300]):

                try:
                    html = await fetch_page(session, title)

                    infobox = extract_infobox(html)
                    drops = extract_drops(html)

                    # IMPORTANT FIX: DO NOT SKIP EVERYTHING
                    if not infobox and not drops:
                        continue

                    entity = normalize(title, infobox, drops, ge)

                    all_monsters.append(entity)

                    print(f"[{i}] {title}")

                    await asyncio.sleep(0.05)

                except Exception as e:
                    print("error:", title, e)

        graph = build_graph(all_monsters)

        # SAVE DATA
        DATA.joinpath("entities.json").write_text(
            json.dumps(all_monsters, indent=2)
        )

        GRAPH.joinpath("npc_to_items.json").write_text(
            json.dumps(graph["npc_to_items"], indent=2)
        )

        GRAPH.joinpath("item_to_npcs.json").write_text(
            json.dumps(graph["item_to_npcs"], indent=2)
        )

        META.joinpath("run.json").write_text(json.dumps({
            "updated_at": now(),
            "entities": len(all_monsters)
        }, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
