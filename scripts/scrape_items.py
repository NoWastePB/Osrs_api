import requests
import json
import os

URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
OUTPUT_FILE = "data/items.json"
TMP_FILE = "data/items.tmp.json"


def ensure_dir():
    os.makedirs("data", exist_ok=True)


def fetch_mapping():
    headers = {
        "User-Agent": "OSRS-Item-Scraper - GitHub Actions"
    }

    response = requests.get(URL, headers=headers, timeout=60)
    response.raise_for_status()

    return response.json()


def transform_item(item):
    """
    Normaliseert de mapping API naar een stabiel schema
    """

    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "examine": item.get("examine"),
        "members": item.get("members"),
        "limit": item.get("limit"),
        "value": item.get("value"),
        "high_alch": item.get("highalch"),
        "low_alch": item.get("lowalch"),
        "icon": item.get("icon")
    }


def save_atomic(data):
    """
    Voorkomt corrupte JSON in GitHub Actions
    """

    with open(TMP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    os.replace(TMP_FILE, OUTPUT_FILE)


def main():
    ensure_dir()

    print("Fetching OSRS mapping API...")

    raw = fetch_mapping()

    print(f"Items received: {len(raw)}")

    items = [transform_item(i) for i in raw]

    save_atomic(items)

    print(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
