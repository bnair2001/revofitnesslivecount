"""
Scrape the Revo Fitness live-member page and output state-segmented counts.
"""

import re
import csv
import sys
from typing import Dict, List, Tuple
import requests
from bs4 import BeautifulSoup

URL = "https://revofitness.com.au/livemembercount/"


def fetch_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def extract_state_map(select_tag) -> Dict[str, List[str]]:
    """
    Walk the <option> elements in #gymSelect.
    Whenever we see an option with the disabled attribute, we treat its text
    as the current STATE header; subsequent options belong to that state until
    the next disabled header.
    """
    state_map: dict[str, list[str]] = {}
    current_state = "UNKNOWN"

    for opt in select_tag.find_all("option"):
        if opt.has_attr("disabled") or not opt.get("value"):
            current_state = opt.get_text(strip=True)
            state_map.setdefault(current_state, [])
        else:
            gym = (opt.get("value") or opt.get_text()).strip()
            state_map.setdefault(current_state, []).append(gym)
    return state_map


def extract_counts(soup) -> Dict[str, int]:
    counts = {}
    for tag in soup.select("span[data-live-count]"):
        gym = tag["data-live-count"].strip()
        try:
            counts[gym] = int(tag.get_text(strip=True) or 0)
        except ValueError:
            counts[gym] = -1
    return counts


def extract_gym_area_and_address(soup) -> Tuple[Dict[str, str], Dict[str, int]]:
    """
    <div data-counter-card="Pitt St" class="hidden flex flex-col col-span-2 gap-6 h-fit w-full">
                                        <div class="flex flex-col gap-2">
                                                                        <div data-address="" class="flex items-center gap-4">
                                                <span class="is-h6">Westfield Sydney Shop 5001/Level 5, 188 Pitt St, Sydney 2000</span>
                                        </div>
                                                <span class="is-h6">975
                                                        sq/m
                                                </span>
                                        </div>
                                                        </div>
                                <a href="https://revofitness.com.au/gyms/pitt-st/" class="button mt-auto !w-full">View gym</a>
        </div>"""
    AREA_RE = re.compile(r"(\d[\d,]*)")  # 975  or 1,050
    AREA_LABELS = ("sq/m", "sqm", "m²")
    address: dict[str, str] = {}
    area: dict[str, int] = {}

    for card in soup.select(
        "[data-counter-card]"
    ):  # <div … data-counter-card="Pitt St">
        gym_name = card.get("data-counter-card")
        if not gym_name:
            continue

        # -------- Address --------
        addr_span = card.select_one("div[data-address] span")
        if addr_span:
            address[gym_name] = addr_span.get_text(strip=True)

        # -------- Area --------
        # prefer the span whose text contains a known area label
        area_span = next(
            (
                span
                for span in card.select("span.is-h6")
                if any(lbl in span.get_text().lower() for lbl in AREA_LABELS)
            ),
            None,
        )

        # if not found, fall back to “second .is-h6 after the address”
        if area_span is None and addr_span:
            area_span = addr_span.find_parent().find_next("span", class_="is-h6")

        # extract the number
        if area_span:
            m = AREA_RE.search(area_span.get_text())
            area[gym_name] = int(m.group(1).replace(",", "")) if m else 0
        else:
            area[gym_name] = 0

    return address, area


def fetch_gym_data():
    soup = fetch_soup(URL)
    select = soup.select_one("#gymSelect")
    if not select:
        raise RuntimeError("Could not find <select id='gymSelect'> on page")
    state_map = extract_state_map(select)
    counts = extract_counts(soup)
    address, area = extract_gym_area_and_address(soup)
    return state_map, counts, address, area


def csv_out(out):
    state_map, counts, address, area = fetch_gym_data()
    writer = csv.writer(out)
    writer.writerow(("state", "gym", "live_members", "address", "area"))
    for state in sorted(state_map):
        for gym in sorted(state_map[state]):
            writer.writerow(
                (
                    state,
                    gym,
                    counts.get(gym, ""),
                    address.get(gym, ""),
                    area.get(gym, 0),
                )
            )


def get_gym_count_by_state_dict() -> Dict[str, Dict[str, int]]:
    state_map, counts, address, area = fetch_gym_data()
    gym_count_by_state: Dict[str, Dict[str, int]] = {state: {} for state in state_map}
    for state, gyms in state_map.items():
        for gym in gyms:
            gym_count_by_state[state][gym] = counts.get(gym, 0)
    return gym_count_by_state


def main(out=sys.stdout):
    try:
        csv_out(out)
        # gym_count_by_state = get_gym_count_by_state_dict()
        # print(gym_count_by_state)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
