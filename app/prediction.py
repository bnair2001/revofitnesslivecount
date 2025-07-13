"""
A lightweight forecaster:
for each gym it stores the median crowd for every (weekday, hour)
combination seen so far.  If no median exists it falls back to
the most recent observed value, then to 0.
"""
import datetime as dt
from collections import defaultdict

import pandas as pd
from sqlalchemy import select
from models import LiveCount, Gym
from db import Session


# recomputed on demand – not a heavy model
def _build_index():
    ses = Session()
    stmt = select(Gym.name, Gym.state, LiveCount.ts, LiveCount.count).join(
        LiveCount.gym
    )
    df = pd.read_sql(stmt, ses.bind, parse_dates=["ts"])
    ses.close()

    if df.empty:
        return {}, {}

    df["wkday"] = df.ts.dt.weekday
    df["hour"] = df.ts.dt.hour

    med = (
        df.groupby(["name", "wkday", "hour"])["count"]
        .median()
        .rename("median")
        .reset_index()
    )

    latest = df.sort_values("ts").groupby("name")["count"].last().to_dict()

    index = defaultdict(dict)
    for row in med.itertuples():
        index[row.name][(row.wkday, row.hour)] = int(row.median)
    return index, latest


def predict(state: str, when: dt.datetime) -> dict[str, int]:
    index, last = _build_index()
    target = (when.weekday(), when.hour)

    ses = Session()
    gyms = ses.query(Gym).filter_by(state=state).all()
    ses.close()

    preds = {}
    for g in gyms:
        preds[g.name] = index.get(g.name, {}).get(target) or last.get(g.name) or 0
    return preds
