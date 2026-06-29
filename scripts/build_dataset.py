import requests
import time
import json
import re
from pathlib import Path

BASE = "https://oldschool.runescape.wiki/api.php"

HEADERS = {
    "User-Agent": "OSRS-Dataset-Bot/1.0 (contact: you@example.com)"
}

OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# -------------------------
# CATEGORY FETCHER
# -------------------------

def get_category_pages(category):
    pages = []
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": f"Category:{category}",
        "cmlimit": "max",
        "format": "json"
    }

    while True:
        r = requests.get(BASE, params=params, headers=HEADERS).json()

        pages.extend(r["query"]["categorymembers"])

        if "continue" not in r:
            break

        params["cmcontinue"] = r["continue"]["cmcontinue"]

        time.sleep(0.2)

    return pages


# -------------------------
# PAGE FETCHER
# -------------------------

def get_wikitext(title):
    params = {
        "action": "parse",
        "page": title,
        "prop": "wikitext",
        "format": "json"
    }

    r = requests.get(BASE, params=params, headers=HEADERS).json()

    return r.get("parse", {}).get("wikitext", {}).get("*", "")


# -------------------------
# INFBOX DETECTION
# -------------------------

def detect_infobox(text):
    match = re.search(r"\{\{Infobox ([^\n|]+)", text)
    return match.group(1).lower() if match else None


# -------------------------
# SIMPLE PARSER
# -------------------------

def parse_infobox(text):
    data = {}

    match = re.search(r"\{\{Infobox.*?\n(.*?)\}\}", text, re.DOTALL)
    if not match:
        return data

    lines = match.group(1).split("\n")

    for line in lines:
        if "=" in line:
            try:
                key, value = line.split("=", 1)
                key = key.replace("|", "").strip()
                data[key] = value.strip()
            except:
                pass

    return data


# -------------------------
# PIPELINE
# -------------------------

def process_category(name, limit=None):
    print(f"\nProcessing {name}")

    pages = get_category_pages(name)

    if limit:
        pages = pages[:limit]

    output = []

    for i, page in enumerate(pages):
        title = page["title"]

        try:
            text = get_wikitext(title)

            infobox_type = detect_infobox(text)

            # skip junk pages
            if not infobox_type:
                continue

            data = parse_infobox(text)

            if not data:
                continue

            data["name"] = title
            data["type"] = infobox_type

            output.append(data)

            print(f"[{i}] {title}")

            time.sleep(0.2)

        except Exception as e:
            print("error:", title, e)

    return output


# -------------------------
# MAIN
# -------------------------

def main():

    dataset = {
        "items": process_category("Items"),
        "npcs": process_category("NPCs"),
        "monsters": process_category("Bestiary"),
        "quests": process_category("Quests"),
    }

    for key, value in dataset.items():
        with open(OUTPUT_DIR / f"{key}.json", "w") as f:
            json.dump(value, f, indent=2)

        print(f"Saved {key}: {len(value)} entries")


if __name__ == "__main__":
    main()
