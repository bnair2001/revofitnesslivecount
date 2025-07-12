import datetime as dt
import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State
import pandas as pd
from sqlalchemy import select

from models import Gym, LiveCount
from db import Session
from fetcher import start_scheduler, scrape_once
from prediction import predict

# spin up background job
start_scheduler()

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.title = "Revo Fitness - Live Crowd"

def _state_options():
    ses = Session()
    states = sorted({row.state for row, in ses.query(Gym.state).distinct()})
    ses.close()
    return [{"label": s, "value": s} for s in states]


app.layout = dbc.Container(
    [
        html.H2("Revo Fitness - Live Member Counts"),
        dbc.Row(
            [
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
                dbc.Col(
                    [
                        dbc.Checklist(
                            options=[{"label": "Show prediction", "value": "pred"}],
                            value=[],
                            id="pred-toggle",
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
                    dbc.Button("Refresh now", id="refresh-btn", n_clicks=0, color="primary"),
                    md="auto",
                ),
            ],
            className="my-2",
        ),
        dcc.Graph(id="crowd-graph"),
        dcc.Interval(id="auto-int", interval=60_000, n_intervals=0),
    ],
    fluid=True,
)


def _get_latest_counts(state: str):
    ses = Session()
    sub = (
        ses.query(
            LiveCount.gym_id,
            LiveCount.count,
            LiveCount.ts
        )
        .join(Gym)
        .filter(Gym.state == state)
        .order_by(LiveCount.gym_id, LiveCount.ts.desc())
        .distinct(LiveCount.gym_id)
        .subquery()
    )
    query = (
        select(Gym.name, sub.c.count, sub.c.ts)
        .join_from(Gym, sub, Gym.id == sub.c.gym_id)
        .order_by(Gym.name)
    )
    df = pd.read_sql(query, ses.bind, parse_dates=["ts"])
    ses.close()
    return df


@app.callback(
    Output("crowd-graph", "figure"),
    Input("state-dropdown", "value"),
    Input("auto-int", "n_intervals"),
    Input("refresh-btn", "n_clicks"),
    Input("pred-toggle", "value"),
    State("pred-date", "date"),
    State("pred-hour", "value"),
    prevent_initial_call=False,
)
def update_graph(state, _auto, _n_clicks, toggle_vals, date, hour):
    # manual scrape if Refresh button was hit
    ctx = dash.callback_context
    if ctx.triggered and ctx.triggered[0]["prop_id"].startswith("refresh-btn"):
        scrape_once()

    show_pred = "pred" in toggle_vals

    if show_pred:
        when = dt.datetime.fromisoformat(date) + dt.timedelta(hours=hour)
        data = predict(state, when)
        title = f"Predicted crowd @ {when:%A %H:00}"
        df = pd.Series(data).reset_index()
        df.columns = ["Gym", "Count"]
    else:
        df = _get_latest_counts(state)
        title = f"Latest live counts ({df.ts.max():%d-%b %H:%M})"
        df = df[["name", "count"]].rename(columns={"name": "Gym", "count": "Count"})

    fig = {
        "data": [
            {
                "x": df["Gym"],
                "y": df["Count"],
                "type": "bar",
            }
        ],
        "layout": {
            "title": title,
            "xaxis": {"tickangle": -45},
            "yaxis": {"title": "Members in gym"},
            "margin": {"b": 200},
        },
    }
    return fig


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=False)