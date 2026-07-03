import argparse
import asyncio
import aiohttp
import json
import os
import random
import time
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
        print(f"[LOAD] Geen bestaand bestand gevonden op {OUTPUT_FILE}, start vanaf 0.")
        return {}
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        loaded = {item["id"]: item for item in data if item and item.get("id") is not None}
        print(f"[LOAD] {len(loaded)} bestaande items geladen uit {OUTPUT_FILE} (checkpoint).")
        return loaded
    except (json.JSONDecodeError, OSError) as e:
        print(f"[LOAD] Kon {OUTPUT_FILE} niet lezen ({e}), start vanaf 0.")
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


KNOWN_BONUS_LABELS = {
    "stab", "slash", "crush", "magic", "ranged",
    "strength", "ranged_strength", "magic_damage", "prayer",
}


def _to_number(text):
    """'+17' -> 17, '-4' -> -4, '+0%' -> 0. Returns None if not numeric."""
    cleaned = text.strip().replace(",", "").rstrip("%")
    try:
        return int(cleaned)
    except ValueError:
        return None


def _find_section_heading(soup, heading_id):
    """
    Locate the heading element for a given section id, e.g. 'Combat_stats'.

    Older MediaWiki output puts the id on a <span class="mw-headline"> nested
    inside the <h2>/<h3>, so you need to walk up to the parent heading.
    Newer MediaWiki (this wiki runs 1.45.x) puts the id directly on the
    <h2>/<h3> itself, wrapped in a <div class="mw-heading">. This helper
    handles both cases instead of assuming the older structure.
    """
    el = soup.find(id=heading_id)
    if not el:
        return None

    if el.name in ("h2", "h3", "h4"):
        return el

    return el.find_parent(["h2", "h3", "h4"])


def parse_combat_stats(soup):
    """
    Anchors on the 'Combat stats' heading (id='Combat_stats') and only looks at
    the table immediately following it, instead of scanning every table on the
    page for the text 'attack bonus' (which can also match unrelated tables,
    e.g. the Changes/update-history table).

    The bonuses table alternates: a row of stat icons (identified via <img alt=...>)
    followed by a row of plain-text values in the same column order. We pair those
    two rows up rather than assuming a fixed 2-column layout.
    """
    heading = _find_section_heading(soup, "Combat_stats")
    if not heading:
        return {}

    table = heading.find_next("table")
    if not table:
        return {}

    result = {"attack_bonuses": {}, "defence_bonuses": {}, "other_bonuses": {}, "slot": None}
    section = None
    rows = table.find_all("tr")

    i = 0
    while i < len(rows):
        row_text = rows[i].get_text(" ", strip=True)

        if "Attack bonuses" in row_text:
            section = "attack_bonuses"
        elif "Defence bonuses" in row_text:
            section = "defence_bonuses"
        elif "Other bonuses" in row_text:
            section = "other_bonuses"

        # Collect stat labels from <img alt="..."> icons in this row —
        # but only ones matching a known stat name, so the section-header
        # icon itself (e.g. an icon next to "Attack bonuses") isn't mistaken
        # for a stat label.
        labels = []
        for cell in rows[i].find_all(["th", "td"]):
            img = cell.find("img")
            if img and img.get("alt"):
                candidate = img["alt"].strip()
                key = candidate.lower().replace(" ", "_")
                if key in KNOWN_BONUS_LABELS or key.endswith("_slot_table"):
                    labels.append(candidate)

        if labels and section:
            # Walk forward to the next row that actually has plain-text values
            j = i + 1
            values = []
            while j < len(rows):
                texts = [c.get_text(" ", strip=True) for c in rows[j].find_all(["th", "td"])]
                texts = [t for t in texts if t]
                if texts:
                    values = texts
                    break
                j += 1

            for label, value in zip(labels, values):
                key = label.lower().replace(" ", "_")

                if "slot" in key:
                    result["slot"] = key.replace("_slot_table", "")
                    continue

                num = _to_number(value)
                result[section][key] = num if num is not None else value

            i = j + 1
        else:
            i += 1

    return result


def parse_sources(soup):
    """
    Anchors on the 'Item sources' heading (id='Item_sources') and parses the
    table that follows it. Item sources on the wiki are rendered as a table
    (Source / Level / Quantity / Rarity / ...), not a <ul>, so searching for
    the nearest <ul> after the heading (the old approach) can walk straight
    past this section and pick up an unrelated list further down the page
    (e.g. navbox 'v/t/e' links).
    """
    heading = _find_section_heading(soup, "Item_sources")
    if not heading:
        return []

    table = heading.find_next("table")
    if not table:
        return []

    rows = table.find_all("tr")
    if not rows:
        return []

    headers = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
    if not headers:
        return []

    sources = []
    for row in rows[1:]:
        cells = row.find_all(["th", "td"])
        if not cells:
            continue
        entry = {}
        for header, cell in zip(headers, cells):
            key = header.lower().replace(" ", "_") or "value"
            entry[key] = cell.get_text(" ", strip=True)
        sources.append(entry)

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

async def worker(queue, session, results, progress, total, verbose=False):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break

        name = item.get("name")

        try:
            result = await process_item(session, item)
            if result:
                results[result.get("id", item.get("id"))] = result
            if verbose:
                print(f"[ITEM] {name} -> ok")
        except Exception as e:
            print(f"[ERROR] {name}: {e}")

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
# PROGRESS TICKER (debug)
# -----------------------------

async def progress_reporter(progress, total, start_time, interval=10):
    """
    Print elke `interval` seconden een voortgangsregel met snelheid en ETA.
    Draait als losse achtergrondtaak zolang de queue nog niet leeg is.
    """
    try:
        while True:
            await asyncio.sleep(interval)

            done = progress["done"]
            elapsed = time.monotonic() - start_time
            rate = done / elapsed if elapsed > 0 else 0
            remaining = total - done
            eta_seconds = remaining / rate if rate > 0 else None

            pct = (done / total * 100) if total else 0

            if eta_seconds is not None:
                eta_str = time.strftime("%H:%M:%S", time.gmtime(eta_seconds))
            else:
                eta_str = "onbekend"

            print(
                f"[PROGRESS] {done}/{total} ({pct:.1f}%) | "
                f"{rate:.2f} items/sec | verstreken {time.strftime('%H:%M:%S', time.gmtime(elapsed))} | "
                f"ETA {eta_str} | "
                f"ok={stats['ok']} 429={stats['429']} err={stats['error']} timeout={stats['timeout']}"
            )
    except asyncio.CancelledError:
        pass


# -----------------------------
# MAIN
# -----------------------------

async def main(limit=None, rescrape_all=False, verbose=False, progress_interval=10):
    ensure_dir()

    existing = {} if rescrape_all else load_existing()
    results = dict(existing)  # id -> item, blijft behouden als checkpoint

    timeout = REQUEST_TIMEOUT
    connector = aiohttp.TCPConnector(limit=CONCURRENCY)

    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout, connector=connector) as session:

        print("Fetching mapping van Wiki Prices API...")
        t0 = time.monotonic()
        mapping = await fetch_mapping(session)
        print(f"[LOAD] Mapping geladen: {len(mapping)} items in {time.monotonic() - t0:.2f}s")

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
        start_time = time.monotonic()

        workers = [
            asyncio.create_task(worker(queue, session, results, progress, total, verbose=verbose))
            for _ in range(CONCURRENCY)
        ]

        reporter = asyncio.create_task(progress_reporter(progress, total, start_time, interval=progress_interval))

        for _ in range(CONCURRENCY):
            await queue.put(None)

        await queue.join()

        reporter.cancel()
        for w in workers:
            w.cancel()

        save_json_atomic(OUTPUT_FILE, list(results.values()))

        elapsed = time.monotonic() - start_time
        print(f"DONE. Totaal opgeslagen: {len(results)} in {time.strftime('%H:%M:%S', time.gmtime(elapsed))}")
        print(f"Stats: {stats}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OSRS item scraper")
    parser.add_argument("--limit", type=int, default=None, help="Alleen eerste N items scrapen (voor testen)")
    parser.add_argument("--rescrape-all", action="store_true", help="Negeer bestaande data/items.json en scrape alles opnieuw")
    parser.add_argument("--verbose", action="store_true", help="Print elk item apart zodra het klaar is (naast de periodieke progress-regel)")
    parser.add_argument("--progress-interval", type=int, default=10, help="Aantal seconden tussen [PROGRESS]-regels (default: 10)")
    args = parser.parse_args()

    asyncio.run(main(
        limit=args.limit,
        rescrape_all=args.rescrape_all,
        verbose=args.verbose,
        progress_interval=args.progress_interval,
    ))
