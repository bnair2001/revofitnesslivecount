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
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
)
app.title = "Revo Fitness Live Crowd"


# ────────────────── helpers ──────────────────
def _state_options():
    """Return dropdown options [{label,value}, …] from distinct Gym.state."""
    ses = Session()
    states = [row[0] for row in ses.query(Gym.state).distinct().all() if row[0]]
    ses.close()
    return [{"label": s, "value": s} for s in sorted(states)]


def _get_latest_counts(state: str) -> pd.DataFrame:
    """
    One row per gym (name, count, ts) the most recent LiveCount for that gym.
    """
    ses = Session()

    sub = (
        ses.query(
            LiveCount.gym_id.label("gym_id"),
            LiveCount.count.label("count"),
            LiveCount.ts.label("ts"),
            # rank() OVER (PARTITION BY gym_id ORDER BY ts DESC) AS r
        )
        .join(Gym)
        .filter(Gym.state == state)
        .order_by(LiveCount.gym_id, LiveCount.ts.desc())
        .distinct(LiveCount.gym_id)
        .subquery()
    )

    q = (
        select(Gym.name, sub.c.count, sub.c.ts)
        .join_from(Gym, sub, Gym.id == sub.c.gym_id)
        .order_by(Gym.name)
    )

    df = pd.read_sql(q, ses.bind, parse_dates=["ts"])
    ses.close()
    return df


# ────────────────── layout ──────────────────
app.layout = dbc.Container(
    [
        html.H2("Revo Fitness Live Member Counts"),
        dbc.Row(
            [
                # State selector
                dbc.Col(
                    [
                        dbc.Label("State"),
                        dcc.Dropdown(
                            id="state-dropdown",
                            options=_state_options(),
                            value="SA",
                            clearable=False,
                        ),
                    ],
                    md=3,
                ),
                # Prediction controls
                dbc.Col(
                    [
                        dbc.Checklist(
                            id="pred-toggle",
                            options=[{"label": "Show prediction", "value": "pred"}],
                            value=[],
                            switch=True,
                        ),
                        dcc.DatePickerSingle(
                            id="pred-date",
                            date=dt.datetime.now().date(),
                        ),
                        dcc.Input(
                            id="pred-hour",
                            type="number",
                            min=0,
                            max=23,
                            step=1,
                            value=dt.datetime.now().hour,
                            style={"width": "4em"},
                        ),
                    ],
                    md=3,
                ),
                # Manual refresh
                dbc.Col(
                    dbc.Button(
                        "Refresh now",
                        id="refresh-btn",
                        n_clicks=0,
                        color="primary",
                    ),
                    md="auto",
                ),
            ],
            className="my-2",
        ),
        html.Div(id="crowd-cards"),
        dcc.Interval(id="auto-int", interval=60_000, n_intervals=0),
    ],
    fluid=True,
)


# ────────────────── callbacks ──────────────────
@app.callback(
    Output("crowd-cards", "children"),
    Input("state-dropdown", "value"),
    Input("auto-int", "n_intervals"),
    Input("refresh-btn", "n_clicks"),
    Input("pred-toggle", "value"),
    State("pred-date", "date"),
    State("pred-hour", "value"),
    prevent_initial_call=False,
)
def update_cards(state, _auto, _btn, toggle_vals, date, hour):
    if ctx.triggered_id == "refresh-btn":
        scrape_once()

    show_pred = "pred" in toggle_vals

    if show_pred:
        when = dt.datetime.fromisoformat(date) + dt.timedelta(hours=hour)
        pred_map = predict(state, when)
        df = pd.Series(pred_map).reset_index()
        df.columns = ["Gym", "Count"]
        ts_label = f"Predicted @ {when:%A %H:00}"
    else:
        df = _get_latest_counts(state)
        if df.empty or df["ts"].dropna().empty:
            return html.Div("No data available.")
        df = df[["name", "count", "ts"]].rename(
            columns={"name": "Gym", "count": "Count"}
        )
        ts = df["ts"].max()
        ts_label = f"Updated @ {ts:%d-%b %H:%M}"

    # Build card grid
    cards = []
    for _, row in df.iterrows():
        cards.append(
            dbc.Col(
                dbc.Card(
                    [
                        dbc.CardHeader(row["Gym"]),
                        dbc.CardBody(
                            [
                                html.H4(f"{int(row['Count'])}", className="card-title"),
                                html.P(ts_label, className="card-text text-muted"),
                            ]
                        ),
                    ],
                    className="mb-3 shadow-sm",
                ),
                xs=12,
                sm=6,
                md=4,
                lg=3,
            )
        )

    return dbc.Row(cards, className="gy-3")


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
            .card-title {
                font-size: 2em;
                text-align: center;
            }
            .card-header {
                font-weight: bold;
                text-align: center;
            }
            .card-text {
                font-size: 0.9em;
                text-align: center;
            }
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
