import datetime as dt

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, ctx
import pandas as pd
from sqlalchemy import select

from models import Gym, LiveCount
from db import Session
from fetcher import start_scheduler, scrape_once
from prediction import predict

# spin up background job
start_scheduler()
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
    query = """
        SELECT g.name, lc.count, lc.ts
        FROM gyms g
        JOIN (
            SELECT DISTINCT ON (gym_id) *
            FROM live_counts
            ORDER BY gym_id, ts DESC
        ) lc ON g.id = lc.gym_id
        WHERE g.state = %s
        ORDER BY g.name;
    """
    df = pd.read_sql(query, ses.bind, params=(state,), parse_dates=["ts"])
    ses.close()
    return df


def _colour(c: int) -> str:
    return "success" if c < 40 else "warning" if c < 60 else "danger"


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
    if ctx.triggered_id == "refresh-btn":
        scrape_once()

    offset = int(tz_offset or 0)
    show_pred = "pred" in toggle_vals

    # ── prediction ────────────────────────────────────────────────────────
    if show_pred:
        base_utc = dt.datetime.utcnow().replace(
            minute=0, second=0, microsecond=0, tzinfo=dt.timezone.utc
        )
        horizons = [15, 30, 45, 60]
        frames = [
            pd.Series(predict(state, base_utc + dt.timedelta(minutes=h)), name=f"in {h} mins")
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
            live[["name", "count"]]
            .rename(columns={"name": "Gym", "count": "Now"})
            .set_index("Gym")
        )
        df["Now"] = df["Now"].astype(int)
        df.reset_index(inplace=True)
        ts_label = f"Updated {_localise(live['ts'].max(), offset)}"
        colour_col = "Now"

    # ── build cards ───────────────────────────────────────────────────────
    cards = []
    for _, row in df.iterrows():
        rows = [
            html.Tr(
                [html.Td(col), html.Td(int(row[col]), className="fs-2 fw-bold")],
            )
            for col in df.columns[1:]
        ]
        cards.append(
            dbc.Col(
                dbc.Card(
                    [
                        dbc.CardHeader(row["Gym"], className="text-center fw-semibold"),
                        dbc.CardBody(
                            [
                                html.Table(
                                    rows,
                                    className="table table-borderless mb-3 text-center",
                                ),
                                html.Small(ts_label, className="text-muted"),
                            ],
                            className="p-3",
                        ),
                    ],
                    color=_colour(int(row[colour_col])),
                    outline=True,
                    className="shadow h-100 border-3",
                    style={"borderColor": "var(--bs-card-bg)"},
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
</body>
</html>
"""
    app.run(host="0.0.0.0", port=8050, debug=False)
