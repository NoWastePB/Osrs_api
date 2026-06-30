import asyncio
import aiohttp
import json
import os
import random
from bs4 import BeautifulSoup

MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
WIKI_API = "https://oldschool.runescape.wiki/api.php"

OUTPUT_FILE = "data/items.json"

CONCURRENCY = 10
semaphore = asyncio.Semaphore(CONCURRENCY)


# -----------------------------
# FILE HANDLING (SAFE)
# -----------------------------

def ensure_dir():
    os.makedirs("data", exist_ok=True)


def save_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# -----------------------------
# FETCH MAPPING
# -----------------------------

async def fetch_mapping(session):
    async with session.get(MAPPING_URL) as r:
        return await r.json()


# -----------------------------
# WIKI FETCH (SAFE + RETRY)
# -----------------------------

async def fetch_wiki(session, name):
    params = {
        "action": "parse",
        "page": name,
        "prop": "text",
        "format": "json"
    }

    for attempt in range(5):
        async with semaphore:
            async with session.get(WIKI_API, params=params) as r:

                if r.status == 429:
                    await asyncio.sleep(2 + attempt * 2)
                    continue

                if r.status != 200:
                    await asyncio.sleep(1)
                    continue

                return await r.json()

    return None


# -----------------------------
# HTML PARSERS
# -----------------------------

def parse_infobox(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="infobox")

    if not table:
        return {}

    data = {}

    for row in table.find_all("tr"):
        th = row.find("th")
        td = row.find("td")

        if th and td:
            key = th.get_text(" ", strip=True)
            value = td.get_text(" ", strip=True)
            data[key] = value

    return data


def parse_combat_stats(soup):
    stats = {}

    for table in soup.find_all("table"):
        text = table.get_text(" ").lower()

        if "attack bonus" in text or "defence bonus" in text:
            for row in table.find_all("tr"):
                cols = row.find_all(["th", "td"])
                if len(cols) == 2:
                    stats[cols[0].get_text(strip=True)] = cols[1].get_text(strip=True)

    return stats


def parse_sources(soup):
    sources = []

    for h in soup.find_all(["h2", "h3"]):
        if "source" in h.get_text().lower():
            ul = h.find_next("ul")
            if ul:
                for li in ul.find_all("li"):
                    sources.append(li.get_text(" ", strip=True))

    return sources


# -----------------------------
# PROCESS ITEM
# -----------------------------

async def process_item(session, item):
    name = item.get("name")
    if not name:
        return None

    wiki = await fetch_wiki(session, name)

    if not wiki or "parse" not in wiki:
        return item

    html = wiki["parse"]["text"]["*"]
    soup = BeautifulSoup(html, "html.parser")

    infobox = parse_infobox(html)
    combat = parse_combat_stats(soup)
    sources = parse_sources(soup)

    return {
        "id": item.get("id"),
        "name": name,
        "examine": item.get("examine"),
        "members": item.get("members"),
        "limit": item.get("limit"),
        "value": item.get("value"),
        "high_alch": item.get("highalch"),
        "low_alch": item.get("lowalch"),

        "wiki": {
            "released": infobox.get("Released"),
            "members": infobox.get("Members"),
            "quest_item": infobox.get("Quest item"),
            "tradeable": infobox.get("Tradeable"),
            "equipable": infobox.get("Equipable"),
            "stackable": infobox.get("Stackable"),
            "noteable": infobox.get("Noteable"),
            "options": infobox.get("Options"),
            "examine": infobox.get("Examine"),
            "value": infobox.get("Value"),
            "high_alch": infobox.get("High alch"),
            "low_alch": infobox.get("Low alch"),
            "weight": infobox.get("Weight"),
            "combat_stats": combat,
            "sources": sources
        }
    }


# -----------------------------
# WORKER
# -----------------------------

async def worker(queue, session, results, progress):
    while True:
        item = await queue.get()
        if item is None:
            break

        try:
            result = await process_item(session, item)
            if result:
                results.append(result)

            progress["done"] += 1

            if progress["done"] % 100 == 0:
                save_json_atomic(OUTPUT_FILE, results)
                print(f"[SAVE] {progress['done']} items")

        except Exception as e:
            print(f"[ERROR] {e}")

        queue.task_done()

        await asyncio.sleep(random.uniform(0.05, 0.15))


# -----------------------------
# MAIN
# -----------------------------

async def main():
    ensure_dir()

    results = []

    async with aiohttp.ClientSession() as session:

        print("Fetching mapping...")
        mapping = await fetch_mapping(session)

        print(f"Items: {len(mapping)}")

        queue = asyncio.Queue()

        for item in mapping:
            await queue.put(item)

        workers = [
            asyncio.create_task(worker(queue, session, results, {"done": 0}))
            for _ in range(CONCURRENCY)
        ]

        for _ in range(CONCURRENCY):
            await queue.put(None)

        await queue.join()

        for w in workers:
            w.cancel()

        save_json_atomic(OUTPUT_FILE, results)

        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
