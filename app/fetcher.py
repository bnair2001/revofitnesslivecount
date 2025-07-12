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
    soup = _fetch_soup()
    select = soup.select_one("#gymSelect")
    if not select:
        logging.error("#gymSelect not found skipping scrape")
        return

    state_map = _extract_state_map(select)
    counts = _extract_counts(soup)

    ses = Session()
    try:
        # ensure all gyms exist
        for state, gyms in state_map.items():
            for gym_name in gyms:
                if not ses.query(Gym.id).filter_by(name=gym_name).first():
                    ses.add(Gym(state=state, name=gym_name))
        ses.flush()  # lets us query Gym ids without committing yet

        # Insert live counts (get-or-create for gyms found only in <span>)
        for gym_name, cnt in counts.items():
            gym = ses.query(Gym).filter_by(name=gym_name).first()
            if not gym:
                # seen in <span> but missing from dropdown
                # try to guess state from state_map, else UNKNOWN
                guessed_state = next(
                    (st for st, gyms in state_map.items() if gym_name in gyms),
                    "UNKNOWN",
                )
                gym = Gym(state=guessed_state, name=gym_name)
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
    scheduler.add_job(scrape_once, "interval", minutes=1, next_run_time=None)
    scheduler.start()
