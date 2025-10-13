import datetime as dt

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output
import pandas as pd
import plotly.graph_objects as go
from sqlalchemy import func, and_, desc

from models import Gym, LiveCount
from db import Session
from fetcher import start_scheduler, scrape_once
from prediction import predict
from analytics import (
    create_trends_chart,
    create_heatmap_chart,
    get_peak_hours_analysis,
    get_gym_rankings,
    get_summary_stats,
)

# Initial scrape and setup
scrape_once()  # Initial scrape to populate DB
_last_fetch = dt.datetime.now()  # Track last fetch time
start_scheduler()  # spin up background job

# Initialize single-page app with tabs
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.title = "Revo Fitness Live Crowd"


# ────────────────── helpers ──────────────────
def _state_options():
    """Return dropdown options [{label,value}, …] from distinct Gym.state."""
    ses = Session()
    res = [r[0] for r in ses.query(Gym.state).distinct().all() if r[0]]
    ses.close()
    return [{"label": s, "value": s} for s in sorted(res)]


def _gym_options(state: str):
    """Return gym dropdown options for a specific state"""
    if not state:
        return [{"label": "All Gyms", "value": "all"}]
    
    ses = Session()
    try:
        gyms = ses.query(Gym.name).filter_by(state=state).order_by(Gym.name).all()
        options = [{"label": "All Gyms", "value": "all"}]
        options.extend([{"label": gym.name, "value": gym.name} for gym in gyms])
        return options
    finally:
        ses.close()


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


# ─── App layout with tabs ──────────────────────────────────────────────────
layout = dbc.Container(
    [
        html.H2("Revo Fitness Tracker", className="display-6 text-center mb-4"),
        # Navigation tabs
        dbc.Tabs(
            id="main-tabs",
            active_tab="live-tab",
            children=[
                dbc.Tab(label="Live Dashboard", tab_id="live-tab"),
                dbc.Tab(label="Analytics", tab_id="analytics-tab"),
            ],
            className="mb-4",
        ),
        # Tab content
        html.Div(id="tab-content"),
        # Global stores and intervals
        dcc.Store(id="tz-offset", storage_type="memory"),
        dcc.Store(id="loading-state", storage_type="memory", data=False),
        dcc.Interval(id="auto-int", interval=60_000, n_intervals=0),
        # Toast notifications
        html.Div(
            id="toast-container",
            style={"position": "fixed", "top": "20px", "right": "20px", "zIndex": 9999},
        ),
    ],
    fluid=True,
)

# ─── browser offset every minute ───────────────────────────────────────────
app.clientside_callback(
    "function(n){return -new Date().getTimezoneOffset();}",
    Output("tz-offset", "data"),
    Input("auto-int", "n_intervals"),
)

# ─── Show spinner when refresh button is clicked ───────────────────────────
app.clientside_callback(
    """
    function(n_clicks) {
        if (n_clicks > 0) {
            return {'display': 'inline-block'};
        }
        return {'display': 'none'};
    }
    """,
    Output("refresh-spinner", "style"),
    Input("refresh-btn", "n_clicks"),
)

# ─── Hide spinner when data is loaded ───────────────────────────────────────
app.clientside_callback(
    """
    function(children) {
        return {'marginLeft': '10px', 'display': 'none'};
    }
    """,
    Output("refresh-spinner", "style", allow_duplicate=True),
    Input("crowd-cards", "children"),
    prevent_initial_call=True
)


# ─── Update gym dropdown when state changes ───────────────────────────────
@app.callback(
    Output("analytics-gym-dropdown", "options"),
    Input("analytics-state-dropdown", "value"),
)
def update_gym_options(state):
    return _gym_options(state)


# ─── Show loading toast when refresh starts ───────────────────────────────
@app.callback(
    Output("toast-container", "children"),
    Input("refresh-btn", "n_clicks"),
    prevent_initial_call=True,
)
def show_loading_toast(n_clicks):
    if n_clicks:
        return dbc.Toast(
            [
                html.Div(
                    [dbc.Spinner(size="sm", className="me-2"), "Updating gym data..."],
                    className="d-flex align-items-center",
                )
            ],
            id="loading-toast",
            header="Data Update",
            is_open=True,
            dismissible=True,
            duration=3000,  # Auto-dismiss after 3 seconds
            icon="info",
            style={"minWidth": "300px"},
        )
    return []


# ─── Tab content callback ──────────────────────────────────────────────────
@app.callback(Output("tab-content", "children"), Input("main-tabs", "active_tab"))
def render_tab_content(active_tab):
    if active_tab == "analytics-tab":
        return create_analytics_tab()
    else:
        return create_live_tab()


def create_live_tab():
    """Create the live dashboard tab content"""
    return [
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
                            {"label": " Show next hour prediction", "value": "pred"}
                        ],
                        value=[],
                        switch=True,
                    ),
                    xs="auto",
                    className="pt-3",
                ),
                dbc.Col(
                    html.Div(
                        [
                            dbc.Button(
                                "Refresh now",
                                id="refresh-btn",
                                n_clicks=0,
                                color="primary",
                            ),
                            html.Div(
                                dbc.Spinner(size="sm"),
                                id="refresh-spinner",
                                style={"marginLeft": "10px", "display": "none"},
                            ),
                        ],
                        style={"display": "flex", "alignItems": "center"},
                    ),
                    xs="auto",
                    className="pt-3",
                ),
            ],
            className="g-3 justify-content-center mb-4",
        ),
        # Loading indicator
        dcc.Loading(
            id="loading-live",
            type="default",
            children=html.Div(id="crowd-cards"),
            style={"minHeight": "200px"},
        ),
    ]


def create_analytics_tab():
    """Create the analytics tab content"""
    return [
        dbc.Row(
            [
                dbc.Col(
                    [
                        dbc.Label("State", className="fw-semibold"),
                        dcc.Dropdown(
                            id="analytics-state-dropdown",
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
                    [
                        dbc.Label("Gym", className="fw-semibold"),
                        dcc.Dropdown(
                            id="analytics-gym-dropdown",
                            options=[{"label": "All Gyms", "value": "all"}],
                            value="all",
                            clearable=False,
                        ),
                    ],
                    xs=12,
                    sm=6,
                    md=3,
                ),
                dbc.Col(
                    [
                        dbc.Label("Time Period", className="fw-semibold"),
                        dcc.Dropdown(
                            id="analytics-period-dropdown",
                            options=[
                                {"label": "Last 7 days", "value": 7},
                                {"label": "Last 30 days", "value": 30},
                                {"label": "Last 90 days", "value": 90},
                            ],
                            value=30,
                            clearable=False,
                        ),
                    ],
                    xs=12,
                    sm=6,
                    md=3,
                ),
            ],
            className="mb-4",
        ),
        # Summary stats cards
        dcc.Loading(
            id="loading-summary", type="default", children=html.Div(id="summary-cards")
        ),
        # Charts
        dbc.Row(
            [
                dbc.Col(
                    [
                        dcc.Loading(
                            id="loading-trends",
                            type="default",
                            children=dcc.Graph(id="trends-chart"),
                        )
                    ],
                    md=6,
                ),
                dbc.Col(
                    [
                        dcc.Loading(
                            id="loading-heatmap",
                            type="default",
                            children=dcc.Graph(id="heatmap-chart"),
                        )
                    ],
                    md=6,
                ),
            ],
            className="mb-4",
        ),
        # Peak hours analysis
        dcc.Loading(
            id="loading-peak", type="default", children=html.Div(id="peak-analysis")
        ),
        # Gym rankings table
        dcc.Loading(
            id="loading-rankings", type="default", children=html.Div(id="gym-rankings")
        ),
    ]


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
        try:
            base_utc = dt.datetime.now(dt.timezone.utc).replace(
                minute=0, second=0, microsecond=0
            )

            # Get prediction for next hour only (much faster)
            next_hour = base_utc + dt.timedelta(hours=1)
            predictions = predict(state, next_hour)

            if not predictions:
                return html.Div(
                    "No prediction data available yet. Need more historical data.",
                    className="text-center fs-4 text-muted",
                )

            # Convert to DataFrame
            df = pd.DataFrame(list(predictions.items()), columns=["Gym", "Next Hour"])
            ts_label = f"Predicted for {_localise(next_hour, offset)}"
            colour_col = "Next Hour"

        except Exception as e:
            return html.Div(
                f"Prediction temporarily unavailable: {str(e)}",
                className="text-center fs-4 text-muted",
            )
    else:
        live = _get_latest_counts(state)
        if live.empty or live["ts"].dropna().empty:
            return html.Div("No data yet.", className="text-center fs-4 text-muted")

        # Check if data is fresh (within last 2 minutes)
        latest_ts = live["ts"].max()
        if (
            latest_ts
            and (dt.datetime.now(dt.timezone.utc) - latest_ts).total_seconds() > 120
        ):
            scrape_once()  # Force a refresh if data is stale
            live = _get_latest_counts(state)  # Get fresh data
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
                                "height": f"{int(percent * 100)}%",
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
                                            f"{int(percent * 100)}% full",
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


# ─── Analytics callback ────────────────────────────────────────────────────
@app.callback(
    [
        Output("summary-cards", "children"),
        Output("trends-chart", "figure"),
        Output("heatmap-chart", "figure"),
        Output("peak-analysis", "children"),
        Output("gym-rankings", "children"),
    ],
    [
        Input("analytics-state-dropdown", "value"),
        Input("analytics-gym-dropdown", "value"),
        Input("analytics-period-dropdown", "value"),
    ],
)
def update_analytics(state, gym, days):
    try:
        # Summary stats
        gym_filter = None if gym == 'all' else gym
        stats = get_summary_stats(state, days, gym_filter)

        summary_cards = []
        if stats:
            summary_cards = dbc.Row(
                [
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardBody(
                                        [
                                            html.H4(
                                                stats["total_gyms"],
                                                className="card-title text-primary",
                                            ),
                                            html.P(
                                "Gym Count" if stats.get("is_single_gym", False) else "Total Gyms",
                                className="card-text"
                            ),
                                        ]
                                    )
                                ]
                            )
                        ],
                        md=2,
                    ),
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardBody(
                                        [
                                            html.H4(
                                                f"{stats['avg_total_count']}",
                                                className="card-title text-success",
                                            ),
                                            html.P(
                                                "Avg Total Count", className="card-text"
                                            ),
                                        ]
                                    )
                                ]
                            )
                        ],
                        md=2,
                    ),
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardBody(
                                        [
                                            html.H4(
                                                stats["peak_total_count"],
                                                className="card-title text-warning",
                                            ),
                                            html.P(
                                                "Peak Total Count",
                                                className="card-text",
                                            ),
                                        ]
                                    )
                                ]
                            )
                        ],
                        md=2,
                    ),
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardBody(
                                        [
                                            html.H4(
                                                stats.get("avg_capacity_pct", stats.get("busiest_gym", "N/A")),
                                                className="card-title text-info",
                                            ),
                                            html.P(
                                                "Avg Capacity %" if stats.get("is_single_gym", False) else "Busiest Gym",
                                                className="card-text"
                                            ),
                                        ]
                                    )
                                ]
                            )
                        ],
                        md=6,
                    ),
                ],
                className="mb-4",
            )

        # Charts
        trends_fig = create_trends_chart(
            state, min(days, 7), gym_filter
        )  # Limit trends to 7 days for performance
        heatmap_fig = create_heatmap_chart(state, gym_filter, days)

        # Peak hours analysis
        peak_data = get_peak_hours_analysis(state, days, gym_filter)
        peak_analysis = html.Div()

        if peak_data:
            peak_hour = peak_data["peak_hour"]
            quiet_hour = peak_data["quietest_hour"]
            peak_count = peak_data["peak_count"]

            peak_analysis = dbc.Card(
                [
                    dbc.CardHeader(html.H5("Peak Hours Analysis")),
                    dbc.CardBody(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(
                                        [
                                            html.P(
                                                [
                                                    html.Strong("Peak Hour: "),
                                                    f"{peak_hour}:00",
                                                ]
                                            ),
                                            html.P(
                                                [
                                                    html.Strong("Peak Count: "),
                                                    str(peak_count),
                                                ]
                                            ),
                                            html.P(
                                                [
                                                    html.Strong("Quietest: "),
                                                    f"{quiet_hour}:00",
                                                ]
                                            ),
                                        ],
                                        md=6,
                                    ),
                                    dbc.Col(
                                        [
                                            html.H6("Visit Planning Tips"),
                                            html.Ul(
                                                [
                                                    html.Li(
                                                        [
                                                            "Busiest: ",
                                                            html.Strong(
                                                                f"{peak_hour}:00"
                                                            ),
                                                            " (avoid crowds)",
                                                        ]
                                                    ),
                                                    html.Li(
                                                        [
                                                            "Quietest: ",
                                                            html.Strong(
                                                                f"{quiet_hour}:00",
                                                                className="text-success",
                                                            ),
                                                            " (ideal time!)",
                                                        ]
                                                    ),
                                                ],
                                                className="mb-2",
                                            ),
                                            html.Small(
                                                "Weekend peaks shift later",
                                                className="text-muted",
                                            ),
                                        ],
                                        md=6,
                                    ),
                                ]
                            )
                        ]
                    ),
                ],
                className="mb-4",
            )

        # Gym rankings
        rankings = get_gym_rankings(state, days, gym_filter)
        rankings_table = html.Div()

        if not rankings.empty:
            rankings_table = dbc.Card(
                [
                    dbc.CardHeader(html.H5("Gym Rankings")),
                    dbc.CardBody(
                        [
                            dbc.Table.from_dataframe(
                                rankings[
                                    [
                                        "name",
                                        "size_sqm",
                                        "avg_count",
                                        "peak_count",
                                        "avg_capacity_pct",
                                    ]
                                ].round(1),
                                striped=True,
                                bordered=True,
                                hover=True,
                                responsive=True,
                                class_name="mt-2",
                            )
                        ]
                    ),
                ]
            )

        return summary_cards, trends_fig, heatmap_fig, peak_analysis, rankings_table

    except Exception as e:
        error_msg = html.Div(
            [
                dbc.Alert(f"Error loading analytics: {str(e)}", color="danger"),
            ]
        )
        empty_fig = go.Figure()
        return error_msg, empty_fig, empty_fig, html.Div(), html.Div()


# ─── App layout ────────────────────────────────────────────────────────────
app.layout = layout

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
