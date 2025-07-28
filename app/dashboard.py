import datetime as dt

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output
import pandas as pd
from sqlalchemy import func, and_, desc

from models import Gym, LiveCount
from db import Session
from fetcher import start_scheduler, scrape_once
from prediction import predict

# Initial scrape and setup
scrape_once()  # Initial scrape to populate DB
_last_fetch = dt.datetime.now()  # Track last fetch time
start_scheduler()  # spin up background job
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.title = "Revo Fitness Live Crowd"


# ────────────────── helpers ──────────────────
def _state_options():
    """Return dropdown options [{label,value}, …] from distinct Gym.state."""
    ses = Session()
    res = [r[0] for r in ses.query(Gym.state).distinct().all() if r[0]]
    ses.close()
    return [{"label": s, "value": s} for s in sorted(res)]


def _get_latest_counts(state: str) -> pd.DataFrame:
    """
    Returns latest LiveCount per gym using PostgreSQL DISTINCT ON
    """
    ses = Session()

    subq = ses.query(
        LiveCount.id,
        LiveCount.gym_id,
        LiveCount.count,
        LiveCount.ts,
        func.row_number()
        .over(partition_by=LiveCount.gym_id, order_by=desc(LiveCount.ts))
        .label("rn"),
    ).subquery()
    # Join Gym with latest LiveCount per gym
    q = (
        ses.query(Gym.name, subq.c.count, subq.c.ts, Gym.size_sqm)
        .join(subq, Gym.id == subq.c.gym_id)
        .filter(and_(subq.c.rn == 1, Gym.state == state))
        .order_by(Gym.name)
    )
    df = pd.DataFrame(q.all(), columns=["name", "count", "ts", "size_sqm"])
    ses.close()
    return df


def _colour(crowd: int, area: int | None) -> str:
    """
    Returns a color based on crowd percentage using area and count.
    10 sqm per person is ideal. If area is missing, fallback to old logic.
    """
    if area and area > 0:
        ideal_capacity = area // 10
        if ideal_capacity == 0:
            ideal_capacity = 1
        percent = crowd / ideal_capacity
        if percent < 0.5:
            return "success"
        elif percent < 0.8:
            return "warning"
        else:
            return "danger"
    # fallback if area is not available
    return "success" if crowd < 40 else "warning" if crowd < 60 else "danger"


def _localise(utc_dt: dt.datetime, offset_min: int | None) -> str:
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=dt.timezone.utc)
    if offset_min is None:
        return utc_dt.strftime("%d-%b %H:%M UTC")
    return (utc_dt + dt.timedelta(minutes=offset_min)).strftime("%d-%b %H:%M")


# ─── layout ───────────────────────────────────────────────────────────────
app.layout = dbc.Container(
    [
        html.H2("Revo Fitness Live Crowd", className="display-6 text-center mb-4"),
        dbc.Row(
            [
                dbc.Col(
                    [
                        dbc.Label("State", className="fw-semibold"),
                        dcc.Dropdown(
                            id="state-dropdown",
                            options=_state_options(),
                            value="SA",
                            clearable=False,
                        ),
                    ],
                    xs=12,
                    sm=6,
                    md=3,
                ),
                dbc.Col(
                    dbc.Checklist(
                        id="pred-toggle",
                        options=[
                            {"label": " Show 15-60 min prediction", "value": "pred"}
                        ],
                        value=[],
                        switch=True,
                    ),
                    xs="auto",
                    className="pt-3",
                ),
                dbc.Col(
                    dbc.Button(
                        "Refresh now", id="refresh-btn", n_clicks=0, color="primary"
                    ),
                    xs="auto",
                    className="pt-3",
                ),
            ],
            className="g-3 justify-content-center mb-4",
        ),
        html.Div(id="crowd-cards"),
        dcc.Store(id="tz-offset", storage_type="memory"),
        dcc.Interval(id="auto-int", interval=60_000, n_intervals=0),
    ],
    fluid=True,
)

# ─── browser offset every minute ───────────────────────────────────────────
app.clientside_callback(
    "function(n){return -new Date().getTimezoneOffset();}",
    Output("tz-offset", "data"),
    Input("auto-int", "n_intervals"),
)


@app.callback(
    Output("crowd-cards", "children"),
    Input("state-dropdown", "value"),
    Input("auto-int", "n_intervals"),
    Input("refresh-btn", "n_clicks"),
    Input("pred-toggle", "value"),
    Input("tz-offset", "data"),
    prevent_initial_call=False,
)
def update_cards(state, _auto, _btn, toggle_vals, tz_offset):
    global _last_fetch
    # Only fetch if it's been more than 60 seconds since last fetch
    now = dt.datetime.now()
    if (now - _last_fetch).total_seconds() >= 60:
        scrape_once()
        _last_fetch = now

    offset = int(tz_offset or 0)
    show_pred = "pred" in toggle_vals

    # ── prediction ────────────────────────────────────────────────────────
    if show_pred:
        base_utc = dt.datetime.utcnow().replace(
            minute=0, second=0, microsecond=0, tzinfo=dt.timezone.utc
        )
        horizons = [15, 30, 45, 60]
        frames = [
            pd.Series(
                predict(state, base_utc + dt.timedelta(minutes=h)), name=f"in {h} mins"
            )
            for h in horizons
        ]
        df = pd.concat(frames, axis=1).reset_index()
        df.rename(columns={"index": "Gym"}, inplace=True)
        ts_label = f"Predicted from {_localise(base_utc, offset)}"
        colour_col = df.columns[1]
    else:
        live = _get_latest_counts(state)
        if live.empty or live["ts"].dropna().empty:
            return html.Div("No data yet.", className="text-center fs-4 text-muted")
        df = (
            live[["name", "count", "size_sqm"]]
            .rename(columns={"name": "Gym", "count": "Now", "size_sqm": "Area (sqm)"})
            .set_index("Gym")
        )
        df["Now"] = df["Now"].astype(int)
        df.reset_index(inplace=True)
        ts_label = f"Updated {_localise(live['ts'].max(), offset)}"
        colour_col = "Now"

    # ── build cards ───────────────────────────────────────────────────────
    cards = []
    for _, row in df.iterrows():
        area = row.get("Area (sqm)", None)
        crowd = int(row[colour_col])
        percent = 0
        if area and area > 0:
            ideal_capacity = area // 7 if area // 7 > 0 else 1
            percent = min(1.0, crowd / ideal_capacity)
        rows = []
        for col in df.columns[1:]:
            if col == "Area (sqm)":
                rows.append(
                    html.Tr(
                        [
                            html.Td("Area (sqm)"),
                            html.Td(
                                f"{row[col]:,}" if row[col] else "-",
                                className="fs-5 fw-normal",
                            ),
                        ]
                    )
                )
            else:
                rows.append(
                    html.Tr(
                        [html.Td(col), html.Td(int(row[col]), className="fs-2 fw-bold")]
                    )
                )
        # Water animation wraps the card
        water_id = f"water-{row['Gym'].replace(' ', '-')}-card"
        # Choose card background color based on crowd percentage
        crowd_color = _colour(crowd, area)
        bg_map = {
            "success": "linear-gradient(160deg,#e3fce3 0%,#b2f5ea 100%)",
            "warning": "linear-gradient(160deg,#fffde4 0%,#ffe0b2 100%)",
            "danger": "linear-gradient(160deg,#ffe3e3 0%,#ffb2b2 100%)",
        }
        card_bg = bg_map.get(crowd_color, "#e3f2fd")
        cards.append(
            dbc.Col(
                html.Div(
                    id=water_id,
                    style={
                        "position": "relative",
                        "height": "320px",
                        "width": "100%",
                        "background": card_bg,
                        "borderRadius": "18px",
                        "overflow": "hidden",
                        "boxShadow": "0 4px 24px 0 rgba(60,60,60,0.08), 0 1.5px 6px 0 rgba(60,60,60,0.04)",
                    },
                    children=[
                        # Water fill
                        html.Div(
                            style={
                                "position": "absolute",
                                "bottom": 0,
                                "left": 0,
                                "width": "100%",
                                "height": f"{int(percent*100)}%",
                                "background": "linear-gradient(180deg,#42a5f5 0%,#90caf9 100%)",
                                "transition": "height 0.8s cubic-bezier(.4,0,.2,1)",
                                "borderBottomLeftRadius": "18px",
                                "borderBottomRightRadius": "18px",
                                "zIndex": 1,
                                "opacity": 0.85,
                            },
                        ),
                        # Card content
                        html.Div(
                            style={
                                "position": "absolute",
                                "top": 0,
                                "left": 0,
                                "width": "100%",
                                "height": "100%",
                                "zIndex": 2,
                                "pointerEvents": "none",
                                "display": "flex",
                                "flexDirection": "column",
                                "justifyContent": "space-between",
                            },
                            children=[
                                # Header and badge
                                html.Div(
                                    [
                                        html.Div(
                                            row["Gym"],
                                            style={
                                                "fontWeight": "600",
                                                "fontSize": "1.35em",
                                                "textAlign": "center",
                                                "marginTop": "10px",
                                            },
                                        ),
                                        html.Span(
                                            f"{int(percent*100)}% full",
                                            style={
                                                "position": "absolute",
                                                "right": 18,
                                                "top": 18,
                                                "background": "#1565c0",
                                                "color": "#fff",
                                                "borderRadius": "12px",
                                                "padding": "2px 12px",
                                                "fontWeight": "bold",
                                                "fontSize": "1em",
                                                "boxShadow": "0 2px 8px #90caf9",
                                                "zIndex": 3,
                                            },
                                        ),
                                    ],
                                    style={"position": "relative"},
                                ),
                                # Stats table
                                html.Table(
                                    rows,
                                    className="table table-borderless mb-3 text-center",
                                    style={"marginTop": "8px", "marginBottom": "0"},
                                ),
                                # Timestamp
                                html.Small(
                                    ts_label,
                                    className="text-muted",
                                    style={"marginBottom": "10px", "marginLeft": "8px"},
                                ),
                            ],
                        ),
                    ],
                ),
                xs=12,
                sm=6,
                md=4,
                lg=3,
            )
        )

    return dbc.Row(cards, className="gy-4")


# ─── bare-bones index (adds subtle bg gradient) ───────────────────────────
if __name__ == "__main__":
    app.index_string = """
<!DOCTYPE html>
<html>
<head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <style>
        body{
            font-family:system-ui,Roboto,sans-serif;
            background:linear-gradient(160deg,#f8f9fa 0%,#e9ecef 100%);
        }
        .card-header{background:rgba(0,0,0,.03)}
        .table td{padding:.25rem .5rem}
    </style>
</head>
<body>
    {%app_entry%}
    <footer>
        {%config%}
        {%scripts%}
        {%renderer%}
    </footer>
    <script>
    // Gyroscope water animation for all water-* elements
    function animateWaterGyro() {
        const waterDivs = document.querySelectorAll('[id^="water-"]');
        let tiltX = 0, tiltY = 0;
        let hasGyro = false;
        function updateWater() {
            waterDivs.forEach(div => {
                const fill = div.querySelector('div');
                if (fill) {
                    // Tilt the water fill using rotateZ
                    fill.style.transform = `skewX(${tiltY/6}deg) skewY(${tiltX/8}deg)`;
                }
            });
        }
        if (window.DeviceOrientationEvent) {
            window.addEventListener('deviceorientation', function(e) {
                hasGyro = true;
                tiltX = e.beta || 0;
                tiltY = e.gamma || 0;
                updateWater();
            });
        }
        // Fallback: gentle wave animation if no gyroscope
        if (!hasGyro) {
            let t = 0;
            setInterval(() => {
                t += 0.05;
                tiltX = Math.sin(t) * 6;
                tiltY = Math.cos(t) * 4;
                updateWater();
            }, 60);
        }
    }
    document.addEventListener('DOMContentLoaded', animateWaterGyro);
    </script>
</body>
</html>
"""
    app.run(host="0.0.0.0", port=8050, debug=False)
