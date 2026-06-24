import json
import time
import requests
from bs4 import BeautifulSoup

URL = "https://oldschool.runescape.wiki/w/Quests/List"
BASE_URL = "https://oldschool.runescape.wiki"

HEADERS = {
    "User-Agent": "OsrsQuestScraper/1.0 (contact: jouw@email.com)"
}


def clean(text):
    return " ".join(text.strip().split())


def get_tables_after_heading(soup, heading_text):
    """Geeft ALLE tabellen terug na een heading, tot de volgende h2."""
    h2 = soup.find("h2", id=heading_text)
    if not h2:
        raise Exception(f"Heading '{heading_text}' niet gevonden")

    tables = []
    current = h2.parent.find_next_sibling()
    while current:
        if current.name == "table":
            tables.append(current)
        else:
            for t in current.find_all("table"):
                tables.append(t)
        if current.name == "div" and "mw-heading" in " ".join(current.get("class", [])):
            break
        current = current.find_next_sibling()

    return tables


def parse_quest_table(table, category):
    """Parse tabel op basis van aantal kolommen."""
    quests = []
    rows = table.find_all("tr")

    for row in rows[1:]:
        cols = row.find_all("td")

        # Free-to-play: id, name, difficulty, length, qp, series, release_date (7 cols)
        if len(cols) == 7:
            link = cols[1].find("a")
            quests.append({
                "category": category,
                "id": clean(cols[0].get_text()),
                "name": clean(cols[1].get_text()),
                "difficulty": clean(cols[2].get_text()),
                "length": clean(cols[3].get_text()),
                "quest_points": clean(cols[4].get_text()),
                "series": clean(cols[5].get_text()),
                "release_date": clean(cols[6].get_text()),
                "url": BASE_URL + link["href"] if link else ""
            })

        # Members: id, name, difficulty, length, qp, series, release_date + 1 extra (8 cols)
        elif len(cols) == 8:
            link = cols[1].find("a")
            quests.append({
                "category": category,
                "id": clean(cols[0].get_text()),
                "name": clean(cols[1].get_text()),
                "difficulty": clean(cols[2].get_text()),
                "length": clean(cols[3].get_text()),
                "quest_points": clean(cols[4].get_text()),
                "series": clean(cols[5].get_text()),
                "release_date": clean(cols[6].get_text()),
                "url": BASE_URL + link["href"] if link else ""
            })

        # Miniquests: name, difficulty, length, series, release_date, leagues_region (laatste overslaan)
        elif len(cols) == 6:
            link = cols[0].find("a")
            quests.append({
                "category": category,
                "id": "",
                "name": clean(cols[0].get_text()),
                "difficulty": clean(cols[1].get_text()),
                "length": clean(cols[2].get_text()),
                "quest_points": "N/A",
                "series": clean(cols[3].get_text()),
                "release_date": clean(cols[4].get_text()),
                "url": BASE_URL + link["href"] if link else ""
            })

    return quests


def get_questdetails_field(soup, field_name):
    """Zoek een specifiek veld in de questdetails tabel."""
    table = soup.find("table", class_="questdetails")
    if not table:
        return None
    for row in table.find_all("tr"):
        th = row.find("th", class_="questdetails-header")
        td = row.find("td", class_="questdetails-info")
        if th and td and field_name.lower() in clean(th.get_text()).lower():
            return td
    return None


def parse_start_point(soup):
    td = get_questdetails_field(soup, "Start point")
    if not td:
        return ""
    # Verwijder de map icon img en haal tekst op
    for img in td.find_all("img"):
        img.decompose()
    # Verwijder "Show on map" link
    for a in td.find_all("a", class_="mw-kartographer-maplink"):
        a.decompose()
    return clean(td.get_text())


def parse_skill_requirements(soup):
    td = get_questdetails_field(soup, "Requirements")
    if not td:
        return []
    skills = []
    for span in td.find_all("span", class_="scp"):
        skill = span.get("data-skill", "")
        level = span.get("data-level", "")
        if skill and level:
            # Bepaal of het boostable is
            sup_texts = [clean(s.get_text()) for s in span.find_next_siblings("sup")]
            boostable = not any("not boostable" in t for t in sup_texts)
            skills.append({
                "skill": skill,
                "level": int(level),
                "boostable": boostable
            })
    return skills


def parse_quest_requirements(soup):
    td = get_questdetails_field(soup, "Requirements")
    if not td:
        return []
    quests = []
    for li in td.find_all("li"):
        text = clean(li.get_text())
        # Sla skill requirements over (die hebben een scp span)
        if li.find("span", class_="scp"):
            continue
        # Sla beschrijvende teksten over
        if any(skip in text for skip in ["Completion of", "Started the", "Kudos", "Quest points"]):
            continue
        link = li.find("a")
        if not link:
            continue
        href = link.get("href", "")
        # Alleen /w/ links die geen speciale wiki-pagina's zijn
        if not href.startswith("/w/"):
            continue
        # Filter bekende niet-quest pagina's
        non_quest_prefixes = [
            "/w/Miniquest", "/w/Barbarian_Training", "/w/Ancient_Cavern",
            "/w/Chat", "/w/Update", "/w/File", "/w/Help", "/w/Category",
            "/w/Template", "/w/User", "/w/RuneScape", "/w/Kudos",
        ]
        if any(href.startswith(p) for p in non_quest_prefixes):
            continue
        # Alleen links waarvan de tekst een questnaam-achtige waarde heeft
        # (begint met hoofdletter, geen lowercase utility-woorden)
        name = clean(link.get_text())
        if not name or name[0].islower():
            continue
        quests.append({
            "name": name,
            "url": BASE_URL + href
        })
    return quests


def parse_item_requirements(soup):
    td = get_questdetails_field(soup, "Items required")
    if not td:
        return []
    items = []
    for li in td.find_all("li"):
        items.append(clean(li.get_text()))
    return items


def parse_rewards(soup):
    td = get_questdetails_field(soup, "Rewards")
    if not td:
        # Probeer de Rewards sectie op de pagina
        rewards_heading = soup.find("h2", id="Rewards") or soup.find("span", id="Rewards")
        if not rewards_heading:
            return []
        current = rewards_heading.parent.find_next_sibling() if rewards_heading.name == "h2" else rewards_heading.find_parent("h2").find_next_sibling()
        while current:
            # Sla navbox tabellen over
            if current.name == "table" and "navbox" in " ".join(current.get("class", [])):
                current = current.find_next_sibling()
                continue
            ul = current.find("ul")
            if ul:
                # Verwijder eventuele navbox tabellen binnen de ul
                for navbox in ul.find_all("table", class_="navbox"):
                    navbox.decompose()
                return [clean(li.get_text()) for li in ul.find_all("li") if clean(li.get_text())]
            if current.name in ("h2", "h3"):
                break
            current = current.find_next_sibling()
        return []
    # Verwijder navbox tabellen uit de td
    for navbox in td.find_all("table"):
        navbox.decompose()
    rewards = []
    for li in td.find_all("li"):
        text = clean(li.get_text())
        if text:
            rewards.append(text)
    return rewards


def parse_enemies(soup):
    td = get_questdetails_field(soup, "Enemies to defeat")
    if not td:
        return []
    enemies = []
    for li in td.find_all("li"):
        enemies.append(clean(li.get_text()))
    return enemies


def fetch_quest_details(url):
    """Haal detailpagina op en parse alle gevraagde velden."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        return {
            "start_point": parse_start_point(soup),
            "skill_requirements": parse_skill_requirements(soup),
            "quest_requirements": parse_quest_requirements(soup),
            "item_requirements": parse_item_requirements(soup),
            "rewards": parse_rewards(soup),
            "enemies_to_defeat": parse_enemies(soup),
        }
    except Exception as e:
        print(f"  [WARN] Fout bij ophalen {url}: {e}")
        return {
            "start_point": "",
            "skill_requirements": [],
            "quest_requirements": [],
            "item_requirements": [],
            "rewards": [],
            "enemies_to_defeat": [],
        }


# ── Hoofdscript ──────────────────────────────────────────────────────────────

response = requests.get(URL, headers=HEADERS, timeout=30)
print("Status:", response.status_code)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

# Zoek de exacte members heading ID dynamisch op
members_heading = None
for h2 in soup.find_all("h2"):
    h2_id = h2.get("id", "")
    if "embers" in h2_id:
        members_heading = h2_id
        break

if not members_heading:
    raise Exception("Geen members heading gevonden op de pagina!")

all_quests = []

for heading, category in [
    ("Free-to-play_quests", "free_to_play"),
    (members_heading, "members"),
    ("Miniquests", "miniquest"),
]:
    tables = get_tables_after_heading(soup, heading)
    for t in tables:
        parsed = parse_quest_table(t, category)
        all_quests.extend(parsed)

print(f"Gevonden: {len(all_quests)} quests. Details ophalen...")

for i, quest in enumerate(all_quests):
    if not quest.get("url"):
        print(f"  [{i+1}/{len(all_quests)}] Geen URL voor '{quest['name']}', overgeslagen")
        continue

    print(f"  [{i+1}/{len(all_quests)}] {quest['name']}")
    details = fetch_quest_details(quest["url"])
    quest.update(details)
    time.sleep(0.5)

with open("data/quests.json", "w", encoding="utf-8") as f:
    json.dump(all_quests, f, indent=2, ensure_ascii=False)

print(f"\nSaved {len(all_quests)} quests naar data/quests.json")
