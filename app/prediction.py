"""
Optimized forecaster with caching and better data usage:
- Uses recent data (last 90 days) for predictions
- Caches median calculations
- Provides multiple prediction methods
- Shows confidence levels and trends
"""

import datetime as dt
from collections import defaultdict
import logging

import pandas as pd
from sqlalchemy import select, desc
from models import LiveCount, Gym
from db import Session

# Cache for prediction data - refreshed every hour
_prediction_cache = {}
_cache_timestamp = None
_cache_duration = 3600  # 1 hour


def _get_recent_data(days=90):
    """Get recent data for predictions - much more efficient than all data"""
    ses = Session()
    try:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)

        stmt = (
            select(Gym.name, Gym.state, Gym.size_sqm, LiveCount.ts, LiveCount.count)
            .join(LiveCount.gym)
            .where(LiveCount.ts >= cutoff)
            .order_by(desc(LiveCount.ts))
        )

        df = pd.read_sql(stmt, ses.bind, parse_dates=["ts"])
        return df
    finally:
        ses.close()


def _build_prediction_model():
    """Build optimized prediction model with recent data only"""
    try:
        df = _get_recent_data(days=90)  # Last 90 days only

        if df.empty:
            logging.warning("No recent data for predictions")
            return {}, {}, {}

        # Add time features
        df["wkday"] = df.ts.dt.weekday
        df["hour"] = df.ts.dt.hour
        df["is_weekend"] = df["wkday"].isin([5, 6])

        # Calculate medians by gym, weekday, hour
        medians = (
            df.groupby(["name", "wkday", "hour"])["count"]
            .agg(["median", "count", "std"])
            .fillna(0)
            .reset_index()
        )

        # Build fast lookup dictionaries
        median_index = defaultdict(dict)
        confidence_index = defaultdict(dict)

        for row in medians.itertuples():
            key = (row.wkday, row.hour)
            median_index[row.name][key] = int(row.median)
            # Confidence based on sample size and std dev
            confidence = min(100, (row.count * 10) - (row.std * 5))
            confidence_index[row.name][key] = max(0, confidence)

        # Get latest values as fallback
        latest = df.groupby("name")["count"].last().to_dict()

        # Calculate trends (last 7 days vs previous 7 days)
        now = dt.datetime.now(dt.timezone.utc)
        last_week = df[df.ts >= (now - dt.timedelta(days=7))]
        prev_week = df[
            (df.ts >= (now - dt.timedelta(days=14)))
            & (df.ts < (now - dt.timedelta(days=7)))
        ]

        trends = {}
        if not last_week.empty and not prev_week.empty:
            last_avg = last_week.groupby("name")["count"].mean()
            prev_avg = prev_week.groupby("name")["count"].mean()
            trends = ((last_avg - prev_avg) / prev_avg * 100).fillna(0).to_dict()

        logging.info(
            f"Built prediction model with {len(df)} records, {len(median_index)} gyms"
        )
        return median_index, latest, confidence_index, trends

    except Exception as e:
        logging.error(f"Error building prediction model: {e}")
        return {}, {}, {}, {}


def _get_cached_model():
    """Get cached prediction model or rebuild if stale"""
    global _prediction_cache, _cache_timestamp

    now = dt.datetime.now(dt.timezone.utc)

    # Check if cache is stale or empty
    if (
        _cache_timestamp is None
        or (now - _cache_timestamp).total_seconds() > _cache_duration
        or not _prediction_cache
    ):
        logging.info("Rebuilding prediction cache")
        medians, latest, confidence, trends = _build_prediction_model()
        _prediction_cache = {
            "medians": medians,
            "latest": latest,
            "confidence": confidence,
            "trends": trends,
        }
        _cache_timestamp = now

    return _prediction_cache


def predict(state: str, when: dt.datetime) -> dict[str, int]:
    """Fast prediction using cached model"""
    try:
        cache = _get_cached_model()
        medians = cache.get("medians", {})
        latest = cache.get("latest", {})

        target = (when.weekday(), when.hour)

        # Get gyms for this state
        ses = Session()
        try:
            gyms = ses.query(Gym.name).filter_by(state=state).all()
            gym_names = [g.name for g in gyms]
        finally:
            ses.close()

        # Generate predictions
        preds = {}
        for gym_name in gym_names:
            # Try median for this time slot
            pred = medians.get(gym_name, {}).get(target)
            if pred is None:
                # Fallback to latest value
                pred = latest.get(gym_name, 0)
            preds[gym_name] = max(0, int(pred))

        return preds

    except Exception as e:
        logging.error(f"Prediction error: {e}")
        return {}


def get_prediction_insights(state: str) -> dict:
    """Get additional insights about predictions"""
    try:
        cache = _get_cached_model()
        confidence = cache.get("confidence", {})
        trends = cache.get("trends", {})

        # Get gyms for this state
        ses = Session()
        try:
            gyms = ses.query(Gym.name).filter_by(state=state).all()
            gym_names = [g.name for g in gyms]
        finally:
            ses.close()

        insights = {}
        for gym_name in gym_names:
            gym_confidence = confidence.get(gym_name, {})
            avg_confidence = (
                sum(gym_confidence.values()) / len(gym_confidence)
                if gym_confidence
                else 0
            )

            insights[gym_name] = {
                "confidence": round(avg_confidence, 1),
                "trend": round(trends.get(gym_name, 0), 1),
                "data_points": len(gym_confidence),
            }

        return insights

    except Exception as e:
        logging.error(f"Insights error: {e}")
        return {}
