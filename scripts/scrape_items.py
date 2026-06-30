import asyncio
import aiohttp
import json
import os
import time
import random
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional

MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
WIKI_API = "https://oldschool.runescape.wiki/api.php"

OUTPUT_FILE = "data/items.json"
CHECKPOINT_FILE = "data/checkpoint.json"

CONCURRENCY = 10
RETRIES = 5


# ---------------------------
# Utils
# ---------------------------

def ensure_dirs():
    os.makedirs("data", exist_ok=True)


def load_json(path: str, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: str, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def clean_text(x: str) -> str:
    return x.replace("\xa0", " ").strip() if x else ""


def to_int(x: str) -> Optional[int]:
    try:
        return int(x.replace(",", "").strip())
    except:
        return None


# ---------------------------
# HTTP layer
# ---------------------------

class HTTPClient:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(CONCURRENCY)

    async def fetch(self, session, url, params=None):
        for attempt in range(RETRIES):
            try:
                async with self.semaphore:
                    async with session.get(url, params=params, timeout=30) as r:
                        if r.status == 429:
                            await asyncio.sleep(2 + attempt * 2)
                            continue
                        if r.status >= 500:
                            await asyncio.sleep(1 + attempt)
                            continue
                        return await r.text()
            except Exception:
                await asyncio.sleep(1 + attempt)
        return None

    async def fetch_json(self, session, url, params=None):
        text = await self.fetch(session, url, params)
        if not text:
            return None
        try:
            return json.loads(text)
        except:
            return None


# ---------------------------
# Wiki Parser
# ---------------------------

class WikiParser:

    @staticmethod
    def parse_infobox(html: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_="infobox")

        if not table:
            return {}

        data = {}

        for row in table.find_all("tr"):
            th = row.find("th")
            td = row.find("td")

            if not th or not td:
                continue

            key = clean_text(th.get_text(" "))
            value = clean_text(td.get_text(" "))

            data[key] = value

        return data

    @staticmethod
    def parse_combat_stats(soup: BeautifulSoup) -> Dict[str, Any]:
        stats = {}

        for table in soup.find_all("table"):
            text = table.get_text(" ").lower()
            if "attack bonus" in text or "defence bonus" in text:
                for row in table.find_all("tr"):
                    cells = row.find_all(["th", "td"])
                    if len(cells) == 2:
                        k = clean_text(cells[0].get_text(" "))
                        v = clean_text(cells[1].get_text(" "))
                        stats[k] = v

        return stats

    @staticmethod
    def extract_sources(soup: BeautifulSoup) -> List[str]:
        sources = []

        headers = soup.find_all(["h2", "h3"])
        for h in headers:
            if "source" in h.get_text().lower():
                ul = h.find_next("ul")
                if ul:
                    for li in ul.find_all("li"):
                        sources.append(clean_text(li.get_text(" ")))

        return sources


# ---------------------------
# API Layer
# ---------------------------

async def get_mapping(client, session):
    return await client.fetch_json(session, MAPPING_URL)


async def get_wiki_html(client, session, name: str):
    return await client.fetch_json(session, WIKI_API, {
        "action": "parse",
        "page": name,
        "prop": "text",
        "format": "json"
    })


# ---------------------------
# Core processing
# ---------------------------

async def process_item(client, session, item):
    name = item.get("name")
    if not name:
        return None

    wiki = await get_wiki_html(client, session, name)
    if not wiki or "parse" not in wiki:
        return item

    html = wiki["parse"]["text"]["*"]
    soup = BeautifulSoup(html, "html.parser")

    infobox = WikiParser.parse_infobox(html)
    combat = WikiParser.parse_combat_stats(soup)
    sources = WikiParser.extract_sources(soup)

    merged = {
        "id": item.get("id"),
        "name": name,
        "examine": item.get("examine"),
        "members": item.get("members"),
        "tradeable": item.get("tradeable"),
        "limit": item.get("limit"),
        "value": item.get("value"),
        "high_alch": item.get("highalch"),
        "low_alch": item.get("lowalch"),

        # wiki extras
        "released": infobox.get("Released"),
        "quest_item": infobox.get("Quest item"),
        "equipable": infobox.get("Equipable"),
        "stackable": infobox.get("Stackable"),
        "noteable": infobox.get("Noteable"),
        "options": infobox.get("Options"),
        "weight": infobox.get("Weight"),

        "combat_stats": combat,
        "sources": sources,
    }

    await asyncio.sleep(random.uniform(0.05, 0.15))
    return merged


# ---------------------------
# Worker system
# ---------------------------

async def worker(name, queue, client, session, results, progress):
    while True:
        item = await queue.get()
        if item is None:
            break

        try:
            result = await process_item(client, session, item)
            if result:
                results.append(result)

            progress["done"] += 1

            if progress["done"] % 100 == 0:
                save_json(OUTPUT_FILE, results)
                save_json(CHECKPOINT_FILE, progress)

                print(f"[SAVE] {progress['done']} items")

        except Exception as e:
            print(f"[ERROR] {e}")

        queue.task_done()


# ---------------------------
# Main
# ---------------------------

async def main():
    ensure_dirs()

    client = HTTPClient()
    progress = load_json(CHECKPOINT_FILE, {"done": 0})

    async with aiohttp.ClientSession() as session:

        print("Fetching mapping...")
        mapping = await get_mapping(client, session)

        if not mapping:
            print("Failed to fetch mapping")
            return

        results = load_json(OUTPUT_FILE, [])

        processed_ids = {x["id"] for x in results if "id" in x}

        queue = asyncio.Queue()

        for item in mapping:
            if item.get("id") not in processed_ids:
                await queue.put(item)

        workers = []
        for i in range(CONCURRENCY):
            w = asyncio.create_task(worker(
                f"worker-{i}",
                queue,
                client,
                session,
                results,
                progress
            ))
            workers.append(w)

        for _ in range(CONCURRENCY):
            await queue.put(None)

        await queue.join()

        for w in workers:
            w.cancel()

        save_json(OUTPUT_FILE, results)
        save_json(CHECKPOINT_FILE, progress)

        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
