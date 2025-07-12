"""
Scrape the Revo Fitness live-member page and output state-segmented counts.
"""
import csv
import sys
import requests
from bs4 import BeautifulSoup

URL = "https://revofitness.com.au/livemembercount/"


def fetch_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def extract_state_map(select_tag) -> dict[str, list[str]]:
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


def extract_counts(soup) -> dict[str, int]:
    counts = {}
    for tag in soup.select("span[data-live-count]"):
        gym = tag["data-live-count"].strip()
        try:
            counts[gym] = int(tag.get_text(strip=True) or 0)
        except ValueError:
            counts[gym] = -1
    return counts


def fetch_gym_data():
    soup = fetch_soup(URL)
    select = soup.select_one("#gymSelect")
    if not select:
        raise RuntimeError("Could not find <select id='gymSelect'> on page")
    state_map = extract_state_map(select)
    counts = extract_counts(soup)
    return state_map, counts


def csv_out(out):
    state_map, counts = fetch_gym_data()
    writer = csv.writer(out)
    writer.writerow(("state", "gym", "live_members"))
    for state in sorted(state_map):
        for gym in sorted(state_map[state]):
            writer.writerow((state, gym, counts.get(gym, "")))


def get_gym_count_by_state_dict() -> dict[str, dict[str, int]]:
    state_map, counts = fetch_gym_data()
    gym_count_by_state: dict[str, dict[str, int]] = {state: {} for state in state_map}
    for state, gyms in state_map.items():
        for gym in gyms:
            gym_count_by_state[state][gym] = counts.get(gym, 0)
    return gym_count_by_state


def main(out=sys.stdout):
    try:
        # csv_out(out)
        gym_count_by_state = get_gym_count_by_state_dict()
        print(gym_count_by_state)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
