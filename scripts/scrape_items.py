import argparse
import asyncio
import aiohttp
import json
import os
import random
from bs4 import BeautifulSoup

MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
WIKI_API = "https://oldschool.runescape.wiki/api.php"

OUTPUT_FILE = "data/items.json"

CONCURRENCY = 4  # lager gezet; wiki rate-limit is streng, vooral zonder geldige UA
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)

# MediaWiki vraagt expliciet om een identificerende User-Agent.
# Zet hier je eigen repo/contact info in.
USER_AGENT = "OsrsCompanionApp-ItemScraper/1.0 (+https://github.com/PietJetse/Osrs_api; contact: replace-with-your-email)"

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Encoding": "gzip",
}

semaphore = asyncio.Semaphore(CONCURRENCY)

# Simpele teller voor diagnose
stats = {"ok": 0, "429": 0, "error": 0, "timeout": 0, "skipped": 0}


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


def load_existing():
    if not os.path.exists(OUTPUT_FILE):
        return {}
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {item["id"]: item for item in data if item and item.get("id") is not None}
    except (json.JSONDecodeError, OSError):
        return {}


# -----------------------------
# FETCH MAPPING
# -----------------------------

async def fetch_mapping(session):
    async with session.get(MAPPING_URL) as r:
        return await r.json()


# -----------------------------
# WIKI FETCH (SAFE + RETRY, semaphore NIET vastgehouden tijdens sleep)
# -----------------------------

async def fetch_wiki(session, name):
    params = {
        "action": "parse",
        "page": name,
        "prop": "text",
        "format": "json",
    }

    for attempt in range(5):
        wait = None

        try:
            async with semaphore:
                async with session.get(WIKI_API, params=params) as r:
                    if r.status == 429:
                        wait = 2 + attempt * 2
                        stats["429"] += 1
                    elif r.status != 200:
                        wait = 1 + attempt
                        stats["error"] += 1
                    else:
                        stats["ok"] += 1
                        return await r.json()
        except (asyncio.TimeoutError, aiohttp.ClientError):
            wait = 1 + attempt
            stats["timeout"] += 1

        # sleep gebeurt BUITEN de semaphore, zodat andere workers door kunnen
        if wait is not None:
            await asyncio.sleep(wait)

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
    stats_out = {}

    for table in soup.find_all("table"):
        text = table.get_text(" ").lower()

        if "attack bonus" in text or "defence bonus" in text:
            for row in table.find_all("tr"):
                cols = row.find_all(["th", "td"])
                if len(cols) == 2:
                    stats_out[cols[0].get_text(strip=True)] = cols[1].get_text(strip=True)

    return stats_out


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
            "sources": sources,
        },
    }


# -----------------------------
# WORKER
# -----------------------------

async def worker(queue, session, results, progress, total):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break

        try:
            result = await process_item(session, item)
            if result:
                results[result.get("id", item.get("id"))] = result
        except Exception as e:
            print(f"[ERROR] {item.get('name')}: {e}")

        progress["done"] += 1

        if progress["done"] % 50 == 0:
            save_json_atomic(OUTPUT_FILE, list(results.values()))
            print(
                f"[SAVE] {progress['done']}/{total} "
                f"(ok={stats['ok']} 429={stats['429']} err={stats['error']} timeout={stats['timeout']})"
            )

        queue.task_done()
        await asyncio.sleep(random.uniform(0.15, 0.35))


# -----------------------------
# MAIN
# -----------------------------

async def main(limit=None, rescrape_all=False):
    ensure_dir()

    existing = {} if rescrape_all else load_existing()
    results = dict(existing)  # id -> item, blijft behouden als checkpoint

    timeout = REQUEST_TIMEOUT
    connector = aiohttp.TCPConnector(limit=CONCURRENCY)

    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout, connector=connector) as session:

        print("Fetching mapping...")
        mapping = await fetch_mapping(session)
        print(f"Items in mapping: {len(mapping)}")

        if not rescrape_all:
            before = len(mapping)
            mapping = [i for i in mapping if i.get("id") not in existing]
            skipped = before - len(mapping)
            stats["skipped"] = skipped
            print(f"Skipping {skipped} already-scraped items (resume mode)")

        if limit:
            mapping = mapping[:limit]
            print(f"--limit actief: alleen eerste {limit} items")

        total = len(mapping)
        if total == 0:
            print("Niets te doen. Klaar.")
            save_json_atomic(OUTPUT_FILE, list(results.values()))
            return

        queue = asyncio.Queue()
        for item in mapping:
            await queue.put(item)

        progress = {"done": 0}

        workers = [
            asyncio.create_task(worker(queue, session, results, progress, total))
            for _ in range(CONCURRENCY)
        ]

        for _ in range(CONCURRENCY):
            await queue.put(None)

        await queue.join()

        for w in workers:
            w.cancel()

        save_json_atomic(OUTPUT_FILE, list(results.values()))

        print(f"DONE. Totaal opgeslagen: {len(results)}")
        print(f"Stats: {stats}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OSRS item scraper")
    parser.add_argument("--limit", type=int, default=None, help="Alleen eerste N items scrapen (voor testen)")
    parser.add_argument("--rescrape-all", action="store_true", help="Negeer bestaande data/items.json en scrape alles opnieuw")
    args = parser.parse_args()

    asyncio.run(main(limit=args.limit, rescrape_all=args.rescrape_all))
