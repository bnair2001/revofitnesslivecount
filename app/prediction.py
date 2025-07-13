import datetime as dt
from functools import lru_cache

import numpy as np
import pandas as pd
from sqlalchemy import select

from models import LiveCount, Gym
from db import Session


@lru_cache(maxsize=1)
def _build_index() -> (
    tuple[
        dict[str, dict[tuple[int, int], int]],  # weekday-hour medians
        dict[str, dict[int, int]],  # hour-only medians
        dict[str, int],  # global medians
        dict[str, int],  # most-recent counts
    ]
):
    """
    Pull the latest data from the DB and prepare several lookup tables:

    1. median count by (weekday, hour)
    2. median count by hour (all weekdays combined)
    3. overall median per gym
    4. latest observed count per gym

    All numeric values are cast to `int` so the rest of the code can assume
    integers and avoid pandas/NumPy scalars leaking out.
    """
    ses = Session()
    stmt = select(Gym.name, Gym.state, LiveCount.ts, LiveCount.count).join(
        LiveCount.gym
    )
    df = pd.read_sql(stmt, ses.bind, parse_dates=["ts"])
    ses.close()

    if df.empty:
        return {}, {}, {}, {}

    # Basic time-of-day features
    df["wkday"] = df.ts.dt.weekday
    df["hour"] = df.ts.dt.hour

    # 1. weekday-hour medians
    wk_hr_med = (
        df.groupby(["name", "wkday", "hour"])["count"]
        .median()
        .astype(int)
        .unstack(level=[1, 2])
    )
    by_wk_hr = {
        gym: {(wk, hr): int(val) for (wk, hr), val in row.dropna().items()}
        for gym, row in wk_hr_med.iterrows()
    }

    # 2. hour-only medians (weekdays collapsed)
    hr_med = df.groupby(["name", "hour"])["count"].median().astype(int).unstack(level=1)
    by_hr = {
        gym: {int(hr): int(val) for hr, val in row.dropna().items()}
        for gym, row in hr_med.iterrows()
    }

    # 3. global median per gym
    global_med = df.groupby("name")["count"].median().astype(int).to_dict()

    # 4. latest observed count per gym
    latest = df.sort_values("ts").groupby("name")["count"].last().astype(int).to_dict()

    return by_wk_hr, by_hr, global_med, latest


def _blend(historical: int | None, latest: int | None, w_hist: float = 0.65) -> int:
    """
    Combine a historical estimate with the most recent observation.
    If one component is missing, fall back to the other.
    """
    if historical is None and latest is None:
        return 0
    if historical is None:
        return latest
    if latest is None:
        return historical
    return int(round(w_hist * historical + (1 - w_hist) * latest))


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------


def predict(state: str, when: dt.datetime) -> dict[str, int]:
    """
    Predict the live counts for every gym in *state* at the datetime *when*.

    Strategy (per gym):
        1. Try the median for the exact (weekday, hour).
        2. If unavailable, average the medians for the neighbouring hours
           (-1 h and +1 h) that exist.
        3. Fall back to the median for that hour across all weekdays.
        4. Fall back to the overall median for the gym.
        5. Finally, if everything is missing, use the latest observed count
           (might be zero if no data).
        6. Blend the chosen historical value with the latest observation
           (default 65 % historical, 35 % recent) to account for short-term
           swings such as public holidays or local events.

    Returns
    -------
    dict[str, int]
        Mapping gym name ➜ predicted live count (non-negative integer).
    """
    by_wk_hr, by_hr, global_med, latest = _build_index()
    target = when.weekday(), when.hour

    # Fetch gyms for the requested state
    ses = Session()
    gyms = ses.query(Gym).filter_by(state=state).all()
    ses.close()

    preds: dict[str, int] = {}

    for g in gyms:
        name = g.name

        # 1. exact match
        hist_val: int | None = by_wk_hr.get(name, {}).get(target)

        # 2. neighbouring hours
        if hist_val is None:
            neighbours = [
                by_wk_hr.get(name, {}).get((target[0], h))
                for h in (target[1] - 1, target[1] + 1)
                if 0 <= h < 24
            ]
            neighbours = [n for n in neighbours if n is not None]
            if neighbours:
                hist_val = int(np.median(neighbours))

        # 3. hour-only median
        if hist_val is None:
            hist_val = by_hr.get(name, {}).get(target[1])

        # 4. global median
        if hist_val is None:
            hist_val = global_med.get(name)

        # 5. (may still be None)
        latest_val = latest.get(name)

        # 6. blend & floor at zero
        preds[name] = max(0, _blend(hist_val, latest_val))

    return preds
