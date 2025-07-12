"""
Periodically scrape the Revo Fitness live-member page
and store counts in PostgreSQL.
"""
import logging
import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler

from models import Base, Gym, LiveCount
from db import engine, Session

URL = "https://revofitness.com.au/livemembercount/"
logging.basicConfig(level=logging.INFO)


def fetch_soup():
    resp = requests.get(URL, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def extract_state_map(select_tag):
    state_map = {}
    current_state = "UNKNOWN"
    for opt in select_tag.find_all("option"):
        if opt.has_attr("disabled") or not opt.get("value"):
            current_state = opt.get_text(strip=True)
            state_map.setdefault(current_state, [])
        else:
            gym = (opt.get("value") or opt.get_text()).strip()
            state_map.setdefault(current_state, []).append(gym)
    return state_map


def extract_counts(soup):
    counts = {}
    for tag in soup.select("span[data-live-count]"):
        gym = tag["data-live-count"].strip()
        try:
            counts[gym] = int(tag.get_text(strip=True) or 0)
        except ValueError:
            counts[gym] = -1
    return counts


def scrape_once():
    soup = fetch_soup()
    select = soup.select_one("#gymSelect")
    if not select:
        logging.error("gymSelect not found")
        return

    state_map = extract_state_map(select)
    counts = extract_counts(soup)

    ses = Session()
    try:
        # ensure all gyms exist
        for state, gyms in state_map.items():
            for gym_name in gyms:
                gym = ses.query(Gym).filter_by(name=gym_name).first()
                if not gym:
                    gym = Gym(state=state, name=gym_name)
                    ses.add(gym)
        ses.commit()

        # insert counts
        for gym_name, cnt in counts.items():
            gym = ses.query(Gym).filter_by(name=gym_name).one()
            ses.add(LiveCount(gym_id=gym.id, count=cnt))
        ses.commit()
        logging.info("Inserted %d live counts", len(counts))
    except Exception:
        ses.rollback()
        logging.exception("scrape_once failed")
    finally:
        ses.close()


def start_scheduler():
    Base.metadata.create_all(engine)
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(scrape_once, "interval", minutes=1, next_run_time=None)
    scheduler.start()
