"""
Analytics dashboard for Revo Fitness data
Shows trends, patterns, and detailed insights from historical data
"""

import datetime as dt
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from sqlalchemy import select, and_
from models import LiveCount, Gym
from db import Session


def get_gym_trends(state: str, days: int = 30) -> pd.DataFrame:
    """Get trend data for gyms in a state over specified days"""
    ses = Session()
    try:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)

        stmt = (
            select(
                Gym.name, Gym.size_sqm, LiveCount.ts.label("timestamp"), LiveCount.count
            )
            .join(LiveCount.gym)
            .where(and_(Gym.state == state, LiveCount.ts >= cutoff))
            .order_by(LiveCount.ts)
        )

        df = pd.read_sql(stmt, ses.bind, parse_dates=["timestamp"])

        if not df.empty:
            # Add derived columns
            df["hour"] = df.timestamp.dt.hour
            df["weekday"] = df.timestamp.dt.day_name()
            df["is_weekend"] = df.timestamp.dt.weekday.isin([5, 6])
            df["capacity_pct"] = 0.0  # Initialize as float

            # Calculate capacity percentage where area is available
            mask = df.size_sqm.notna() & (df.size_sqm > 0)
            if mask.any():
                capacity_values = (
                    df.loc[mask, "count"] / (df.loc[mask, "size_sqm"] / 10) * 100
                ).astype("float64")
                df.loc[mask, "capacity_pct"] = capacity_values

        return df

    finally:
        ses.close()


def get_peak_hours_analysis(state: str, days: int = 30) -> dict:
    """Analyze peak hours across all gyms"""
    df = get_gym_trends(state, days)

    if df.empty:
        return {}

    # Average by hour across all gyms and days
    hourly_avg = df.groupby("hour")["count"].mean()
    peak_hour = hourly_avg.idxmax()

    # Weekend vs weekday patterns
    weekend_pattern = df[df.is_weekend].groupby("hour")["count"].mean()
    weekday_pattern = df[~df.is_weekend].groupby("hour")["count"].mean()

    return {
        "peak_hour": int(peak_hour),
        "peak_count": round(hourly_avg.max(), 1),
        "quietest_hour": int(hourly_avg.idxmin()),
        "hourly_averages": hourly_avg.to_dict(),
        "weekend_pattern": weekend_pattern.to_dict(),
        "weekday_pattern": weekday_pattern.to_dict(),
    }


def create_trends_chart(state: str, days: int = 7):
    """Create a trend chart for recent days"""
    df = get_gym_trends(state, days)

    if df.empty:
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )

    # Resample to hourly averages to reduce noise
    df_hourly = (
        df.set_index("timestamp")
        .groupby("name")
        .resample("h")["count"]
        .mean()
        .reset_index()
    )

    fig = px.line(
        df_hourly,
        x="timestamp",
        y="count",
        color="name",
        title=f"7-Day Crowd Trends - {state}",
        labels={"count": "People Count", "timestamp": "Time"},
    )

    fig.update_layout(
        height=400, showlegend=True, legend=dict(orientation="v", x=1.02, y=1)
    )

    return fig


def create_heatmap_chart(state: str, days: int = 30):
    """Create hour vs weekday heatmap"""
    df = get_gym_trends(state, days)

    if df.empty:
        return go.Figure()

    # Average by hour and weekday
    heatmap_data = df.groupby(["weekday", "hour"])["count"].mean().unstack(fill_value=0)

    # Reorder weekdays
    day_order = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    heatmap_data = heatmap_data.reindex(day_order)

    fig = go.Figure(
        data=go.Heatmap(
            z=heatmap_data.values,
            x=heatmap_data.columns,
            y=heatmap_data.index,
            colorscale="RdYlBu_r",
            hoverongaps=False,
        )
    )

    fig.update_layout(
        title=f"Average Crowd by Hour and Day - {state}",
        xaxis_title="Hour of Day",
        yaxis_title="Day of Week",
        height=400,
    )

    return fig


def get_gym_rankings(state: str, days: int = 30) -> pd.DataFrame:
    """Get gym rankings by various metrics"""
    df = get_gym_trends(state, days)

    if df.empty:
        return pd.DataFrame()

    # Calculate metrics per gym
    rankings = (
        df.groupby(["name", "size_sqm"])
        .agg({"count": ["mean", "max", "std"], "capacity_pct": "mean"})
        .round(1)
    )

    rankings.columns = ["avg_count", "peak_count", "variability", "avg_capacity_pct"]
    rankings = rankings.reset_index()

    # Add rankings
    rankings["popularity_rank"] = rankings["avg_count"].rank(ascending=False)
    rankings["peak_rank"] = rankings["peak_count"].rank(ascending=False)

    return rankings.sort_values("avg_count", ascending=False)


def get_summary_stats(state: str, days: int = 30) -> dict:
    """Get summary statistics for the state"""
    df = get_gym_trends(state, days)

    if df.empty:
        return {}

    total_gyms = df["name"].nunique()
    total_records = len(df)
    date_range = (df["timestamp"].min(), df["timestamp"].max())

    # Overall stats
    avg_total = df.groupby("timestamp")["count"].sum().mean()
    peak_total = df.groupby("timestamp")["count"].sum().max()

    # Busiest gym
    gym_avg = df.groupby("name")["count"].mean()
    busiest_gym = gym_avg.idxmax()

    return {
        "total_gyms": total_gyms,
        "total_records": total_records,
        "date_range": date_range,
        "avg_total_count": round(avg_total, 1),
        "peak_total_count": int(peak_total),
        "busiest_gym": busiest_gym,
        "busiest_gym_avg": round(gym_avg.max(), 1),
    }
