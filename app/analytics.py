"""
Analytics dashboard for Revo Fitness data
Shows trends, patterns, and detailed insights from historical data
"""

import datetime as dt
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pytz

from sqlalchemy import select, and_
from models import LiveCount, Gym
from db import Session


def get_local_timezone(state: str) -> str:
    """Get appropriate timezone for Australian state"""
    timezone_map = {
        "SA": "Australia/Adelaide",  # South Australia (UTC+9:30/+10:30)
        "WA": "Australia/Perth",  # Western Australia (UTC+8)
        "NSW": "Australia/Sydney",  # New South Wales (UTC+10/+11)
        "VIC": "Australia/Melbourne",  # Victoria (UTC+10/+11)
        "QLD": "Australia/Brisbane",  # Queensland (UTC+10)
        "NT": "Australia/Darwin",  # Northern Territory (UTC+9:30)
        "TAS": "Australia/Hobart",  # Tasmania (UTC+10/+11)
        "ACT": "Australia/Sydney",  # Australian Capital Territory (UTC+10/+11)
    }
    return timezone_map.get(state, "Australia/Sydney")  # Default to Sydney


def convert_to_local_time(df: pd.DataFrame, state: str) -> pd.DataFrame:
    """Convert UTC timestamps to local timezone for the given state"""
    if df.empty:
        return df

    local_tz = pytz.timezone(get_local_timezone(state))

    # Ensure timestamp is timezone-aware (assume UTC if naive)
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")

    # Convert to local timezone
    df["timestamp"] = df["timestamp"].dt.tz_convert(local_tz)

    return df


def get_gym_trends(state: str, days: int = 30, gym_name: str = None) -> pd.DataFrame:
    """Get trend data for gyms in a state over specified days"""
    ses = Session()
    try:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)

        # Build conditions
        conditions = [Gym.state == state, LiveCount.ts >= cutoff]
        if gym_name and gym_name != "all":
            conditions.append(Gym.name == gym_name)

        stmt = (
            select(
                Gym.name, Gym.size_sqm, LiveCount.ts.label("timestamp"), LiveCount.count
            )
            .join(LiveCount.gym)
            .where(and_(*conditions))
            .order_by(LiveCount.ts)
        )

        df = pd.read_sql(stmt, ses.bind, parse_dates=["timestamp"])

        if not df.empty:
            # Convert to local timezone for accurate hour analysis
            df = convert_to_local_time(df, state)

            # Add derived columns (now using local time)
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


def get_peak_hours_analysis(state: str, days: int = 30, gym_name: str = None) -> dict:
    """Analyze peak hours across gyms"""
    df = get_gym_trends(state, days, gym_name)

    if df.empty:
        return {}

    # Average by hour across all gyms and days
    hourly_avg = df.groupby("hour")["count"].mean()
    peak_hour = hourly_avg.idxmax()

    # Weekend vs weekday patterns
    weekend_pattern = df[df.is_weekend].groupby("hour")["count"].mean()
    weekday_pattern = df[~df.is_weekend].groupby("hour")["count"].mean()

    # Detailed weekend vs weekday analysis
    weekend_peak = weekend_pattern.idxmax() if not weekend_pattern.empty else None
    weekday_peak = weekday_pattern.idxmax() if not weekday_pattern.empty else None
    weekend_quiet = weekend_pattern.idxmin() if not weekend_pattern.empty else None
    weekday_quiet = weekday_pattern.idxmin() if not weekday_pattern.empty else None

    # Compare peak hours
    peak_shift = None
    if weekend_peak is not None and weekday_peak is not None:
        peak_shift = int(weekend_peak) - int(weekday_peak)

    # Find busiest day type
    weekend_avg = weekend_pattern.mean() if not weekend_pattern.empty else 0
    weekday_avg = weekday_pattern.mean() if not weekday_pattern.empty else 0
    busier_time = "weekends" if weekend_avg > weekday_avg else "weekdays"

    # Calculate percentage difference
    if weekday_avg > 0:
        pct_diff = round(((weekend_avg - weekday_avg) / weekday_avg) * 100, 1)
    else:
        pct_diff = 0

    return {
        "peak_hour": int(peak_hour),
        "peak_count": round(hourly_avg.max(), 1),
        "quietest_hour": int(hourly_avg.idxmin()),
        "hourly_averages": hourly_avg.to_dict(),
        "weekend_pattern": weekend_pattern.to_dict(),
        "weekday_pattern": weekday_pattern.to_dict(),
        "weekend_peak": int(weekend_peak) if weekend_peak is not None else None,
        "weekday_peak": int(weekday_peak) if weekday_peak is not None else None,
        "weekend_quiet": int(weekend_quiet) if weekend_quiet is not None else None,
        "weekday_quiet": int(weekday_quiet) if weekday_quiet is not None else None,
        "peak_shift": peak_shift,
        "busier_time": busier_time,
        "crowd_difference_pct": pct_diff,
        "weekend_avg": round(weekend_avg, 1),
        "weekday_avg": round(weekday_avg, 1),
    }


def create_trends_chart(state: str, days: int = 7, gym_name: str = None):
    """Create a trend chart for recent days"""
    df = get_gym_trends(state, days, gym_name)

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

    # Set title based on gym selection
    title = "7-Day Crowd Trends"
    if gym_name and gym_name != "all":
        title += f" - {gym_name}"
    else:
        title += f" - {state}"

    fig = px.line(
        df_hourly,
        x="timestamp",
        y="count",
        color="name",
        title=title,
        labels={"count": "People Count", "timestamp": "Time"},
    )

    fig.update_layout(
        height=400, showlegend=True, legend=dict(orientation="v", x=1.02, y=1)
    )

    return fig


def create_heatmap_chart(state: str, gym_name: str = None, days: int = 30):
    """Create heatmap of peak hours analysis"""
    df = get_gym_trends(state, days, gym_name)

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

    # Set title based on gym selection
    title = "Average Crowd by Hour and Day"
    if gym_name and gym_name != "all":
        title += f" - {gym_name}"
    else:
        title += f" - {state}"

    fig.update_layout(
        title=title,
        xaxis_title="Hour of Day",
        yaxis_title="Day of Week",
        height=400,
    )

    return fig


def get_gym_rankings(state: str, days: int = 30, gym_name: str = None) -> pd.DataFrame:
    """Get gym rankings by various metrics"""
    df = get_gym_trends(state, days, gym_name)

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


def get_summary_stats(state: str, days: int = 30, gym_name: str = None) -> dict:
    """Get summary statistics for the state"""
    df = get_gym_trends(state, days, gym_name)

    if df.empty:
        return {}

    total_gyms = df["name"].nunique()
    total_records = len(df)
    date_range = (df["timestamp"].min(), df["timestamp"].max())

    # Overall stats
    avg_total = df.groupby("timestamp")["count"].sum().mean()
    peak_total = df.groupby("timestamp")["count"].sum().max()

    # Context-specific stats
    if gym_name and gym_name != "all":
        # Single gym stats
        gym_data = df[df["name"] == gym_name]
        avg_capacity = gym_data["capacity_pct"].mean() if not gym_data.empty else 0

        return {
            "total_gyms": 1,
            "total_records": total_records,
            "date_range": date_range,
            "avg_total_count": round(avg_total, 1),
            "peak_total_count": int(peak_total),
            "gym_name": gym_name,
            "avg_capacity_pct": round(avg_capacity, 1),
            "is_single_gym": True,
        }
    else:
        # Multi-gym stats
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
            "is_single_gym": False,
        }
