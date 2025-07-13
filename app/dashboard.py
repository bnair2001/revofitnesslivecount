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


def _colour(count: int) -> str:
    if count < 40:
        return "success"
    if count < 60:
        return "warning"
    return "danger"


def _localise(utc_dt: dt.datetime, offset_min):
    # ensure the incoming value is timezone-aware UTC
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=dt.timezone.utc)

    if offset_min is None:
        return utc_dt.strftime("%d-%b %H:%M UTC")

    local_dt = utc_dt + dt.timedelta(minutes=offset_min)
    return local_dt.strftime("%d-%b %H:%M")


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
        dcc.Store(id="tz-offset", storage_type="memory"),
        dcc.Interval(id="auto-int", interval=60_000, n_intervals=0),
    ],
    fluid=True,
)

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
    State("pred-date", "date"),
    State("pred-hour", "value"),
    State("tz-offset", "data"),
    prevent_initial_call=False,
)
def update_cards(state, _auto, _btn, toggle_vals, date, hour, tz_offset):
    if ctx.triggered_id == "refresh-btn":
        scrape_once()

    show_pred = "pred" in toggle_vals
    offset = tz_offset or 0

    if show_pred:
        base_local = dt.datetime.fromisoformat(date).replace(hour=hour, minute=0, second=0, microsecond=0)
        base_utc = base_local - dt.timedelta(minutes=offset)
        base_utc = base_utc.replace(tzinfo=dt.timezone.utc)    # make it timezone-aware
        horizons = [15, 30, 45, 60]
        frames = []
        for h in horizons:
            when = base_utc + dt.timedelta(minutes=h)
            frames.append(pd.Series(predict(state, when), name=f"+{h}"))
        df = pd.concat(frames, axis=1).reset_index()
        df.rename(columns={"index": "Gym"}, inplace=True)
        ts_label = f"Predicted from {_localise(base_utc, offset)}"
        colour_col = df.columns[1]
    else:
        df_live = _get_latest_counts(state)
        if df_live.empty or df_live["ts"].dropna().empty:
            return html.Div("No data available.")
        df = (
            df_live[["name", "count"]]
            .rename(columns={"name": "Gym", "count": "Now"})
            .set_index("Gym")
        )
        df["Now"] = df["Now"].astype(int)
        df.reset_index(inplace=True)
        ts_label = f"Updated {_localise(df_live['ts'].max(), offset)}"
        colour_col = "Now"

    cards = []
    for _, row in df.iterrows():
        rows = [
            html.Tr([html.Td(col), html.Td(int(row[col]))]) for col in df.columns[1:]
        ]
        cards.append(
            dbc.Col(
                dbc.Card(
                    [
                        dbc.CardHeader(row["Gym"], className="text-center fw-bold"),
                        dbc.CardBody(
                            [
                                html.Table(
                                    rows,
                                    className="table table-sm mb-2 text-center",
                                ),
                                html.Small(
                                    ts_label, className="text-muted d-block text-center"
                                ),
                            ]
                        ),
                    ],
                    color=_colour(int(row[colour_col])),
                    outline=True,
                    className="shadow-sm mb-3",
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
    <style>.card-header{text-align:center;font-weight:bold}.table td{text-align:center}</style>
</head>
<body>
    {%app_entry%}
    <footer>
        {%config%}
        {%scripts%}
        {%renderer%}
    </footer>
</body>
</html>"""
    app.run(host="0.0.0.0", port=8050, debug=False)
