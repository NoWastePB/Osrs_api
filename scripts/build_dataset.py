import requests
import time
import json
import re
from pathlib import Path

BASE = "https://oldschool.runescape.wiki/api.php"

HEADERS = {
    "User-Agent": "OSRS-Dataset-Bot/1.0 (contact: your-email@example.com)"
}

OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------------
# API HELPERS
# ----------------------------

def get_all_pages(limit=5000):
    """Fetch all wiki pages (namespace 0 only)."""
    pages = []
    params = {
        "action": "query",
        "list": "allpages",
        "aplimit": "max",
        "format": "json"
    }

    while True:
        r = requests.get(BASE, params=params, headers=HEADERS).json()

        pages.extend(r["query"]["allpages"])

        if "continue" not in r:
            break

        params["apcontinue"] = r["continue"]["apcontinue"]

        time.sleep(0.2)

        if len(pages) >= limit:
            break

    return pages


def get_wikitext(title):
    url = BASE
    params = {
        "action": "parse",
        "page": title,
        "prop": "wikitext",
        "format": "json"
    }

    r = requests.get(url, params=params, headers=HEADERS).json()

    return r.get("parse", {}).get("wikitext", {}).get("*", "")


# ----------------------------
# INFBOX DETECTION
# ----------------------------

def detect_infobox(text):
    match = re.search(r"\{\{Infobox ([^\n|]+)", text)
    if match:
        return match.group(1).strip().lower()
    return None


def parse_infobox(text):
    """
    Very lightweight parser:
    converts |key=value pairs into dict
    """
    data = {}

    # isolate template
    match = re.search(r"\{\{Infobox.*?\n(.*?)\}\}", text, re.DOTALL)
    if not match:
        return data

    lines = match.group(1).split("\n")

    for line in lines:
        if "|" in line:
            try:
                key, value = line.split("=", 1)
                key = key.replace("|", "").strip()
                data[key] = value.strip()
            except:
                continue

    return data


# ----------------------------
# MAIN PIPELINE
# ----------------------------

def run(limit_pages=200):
    pages = get_all_pages(limit=limit_pages)

    print(f"Fetched {len(pages)} pages")

    dataset = {
        "items": [],
        "npcs": [],
        "monsters": [],
        "quests": []
    }

    for i, page in enumerate(pages):
        title = page["title"]

        try:
            text = get_wikitext(title)

            infobox_type = detect_infobox(text)

            if not infobox_type:
                continue

            data = parse_infobox(text)
            data["name"] = title
            data["type"] = infobox_type

            # router
            if "item" in infobox_type:
                dataset["items"].append(data)

            elif "monster" in infobox_type:
                dataset["monsters"].append(data)

            elif "npc" in infobox_type:
                dataset["npcs"].append(data)

            elif "quest" in infobox_type:
                dataset["quests"].append(data)

            print(f"[{i}] parsed {title}")

            time.sleep(0.2)  # wiki-safe rate limit

        except Exception as e:
            print("error:", title, e)

    # write files
    for key, value in dataset.items():
        with open(OUTPUT_DIR / f"{key}.json", "w") as f:
            json.dump(value, f, indent=2)

    print("DONE")


if __name__ == "__main__":
    run()
