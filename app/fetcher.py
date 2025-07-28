import re
import logging
import datetime as dt
from collections import defaultdict

import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler

from models import Base, Gym, LiveCount
from db import engine, Session

def _extract_gym_area_and_address(soup):
    AREA_RE = re.compile(r"(\d[\d,]*)")
    AREA_LABELS = ("sq/m", "sqm", "m²")
    address = {}
    area = {}
    for card in soup.select("[data-counter-card]"):
        gym_name = card.get("data-counter-card")
        if not gym_name:
            continue
        # Address
        addr_span = card.select_one("div[data-address] span")
        if addr_span:
            address[gym_name] = addr_span.get_text(strip=True)
        # Area
        area_span = next(
            (
                span
                for span in card.select("span.is-h6")
                if any(lbl in span.get_text().lower() for lbl in AREA_LABELS)
            ),
            None,
        )
        if area_span is None and addr_span:
            area_span = addr_span.find_parent().find_next("span", class_="is-h6")
        if area_span:
            m = AREA_RE.search(area_span.get_text())
            area[gym_name] = int(m.group(1).replace(",", "")) if m else 0
        else:
            area[gym_name] = 0
    return address, area


"""
Periodically scrape the Revo Fitness live-member page
and store counts in PostgreSQL.
"""

import logging
from collections import defaultdict

import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler

from models import Base, Gym, LiveCount
from db import engine, Session

URL = "https://revofitness.com.au/livemembercount/"
logging.basicConfig(level=logging.INFO)


def _fetch_soup() -> BeautifulSoup:
    resp = requests.get(URL, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _extract_state_map(select_tag):
    """
    Returns {"WA": ["Australind", …], "SA": […], …}
    """
    state_map = defaultdict(list)
    current_state = "UNKNOWN"
    for opt in select_tag.find_all("option"):
        if opt.has_attr("disabled") or not opt.get("value"):
            current_state = opt.get_text(strip=True)
        else:
            gym = (opt.get("value") or opt.get_text()).strip()
            state_map[current_state].append(gym)
    return dict(state_map)


def _extract_counts(soup):
    """
    Returns {"GymName": 42, …}.  If the span's text won't parse → -1 (sentinel).
    """
    counts = {}
    for tag in soup.select("span[data-live-count]"):
        gym = tag["data-live-count"].strip()
        try:
            counts[gym] = int(tag.get_text(strip=True) or 0)
        except ValueError:
            counts[gym] = -1
    return counts


def scrape_once():
    """
    Single scrape:
      • insert any new gyms
      • write one row per gym to live_counts
    """
    # Ensure tables exist before scraping
    Base.metadata.create_all(engine)

    soup = _fetch_soup()
    select = soup.select_one("#gymSelect")
    if not select:
        logging.error("#gymSelect not found skipping scrape")
        return

    state_map = _extract_state_map(select)
    counts = _extract_counts(soup)
    address, area = _extract_gym_area_and_address(soup)

    ses = Session()
    try:
        # ensure all gyms exist, update area if changed
        for state, gyms in state_map.items():
            for gym_name in gyms:
                gym = ses.query(Gym).filter_by(name=gym_name).first()
                gym_size = area.get(gym_name, 0)
                gym_address = address.get(gym_name, "")
                if not gym:
                    ses.add(
                        Gym(
                            state=state,
                            name=gym_name,
                            size_sqm=gym_size,
                            address=gym_address,
                        )
                    )
                else:
                    updated = False
                    if gym.size_sqm != gym_size:
                        gym.size_sqm = gym_size
                        updated = True
                    if gym.address != gym_address:
                        gym.address = gym_address
                        updated = True
                    if updated:
                        ses.add(gym)
        ses.flush()

        # Insert live counts (get-or-create for gyms found only in <span>)
        for gym_name, cnt in counts.items():
            gym = ses.query(Gym).filter_by(name=gym_name).first()
            if not gym:
                guessed_state = next(
                    (st for st, gyms in state_map.items() if gym_name in gyms),
                    "UNKNOWN",
                )
                gym_size = area.get(gym_name, 0)
                gym_address = address.get(gym_name, "")
                gym = Gym(
                    state=guessed_state,
                    name=gym_name,
                    size_sqm=gym_size,
                    address=gym_address,
                )
                ses.add(gym)
                ses.flush()
            ses.add(LiveCount(gym_id=gym.id, count=cnt))

        ses.commit()
        logging.info(
            "scrape_once: %d gyms, %d counts inserted",
            ses.query(Gym).count(),
            len(counts),
        )

    except Exception as exc:
        ses.rollback()
        logging.exception("scrape_once failed rolled back")
        raise exc
    finally:
        ses.close()


def start_scheduler():
    """
    Create tables (if first run) and schedule scrape_every_minute.
    """
    Base.metadata.create_all(engine)

    scheduler = BackgroundScheduler(daemon=True)
    # Run immediately when started and then every minute
    scheduler.add_job(scrape_once, "interval", minutes=5, next_run_time=dt.datetime.now())
    scheduler.start()
    logging.info("Scheduler started - will scrape every 5 minutes")
