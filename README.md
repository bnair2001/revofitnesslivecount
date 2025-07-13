# Revo Fitness Live-Crowd Dashboard

Scrapes the Revo Fitness live-member page every minute, stores the data in PostgreSQL, and serves a Dash web app with:

* Live counts for all gyms in a selected state  
* A “Refresh now” button (manual scrape)  
* Optional crowd prediction for any future date/hour (median by weekday+hour)  

Dash 3.1.1 and dash-bootstrap-components 2.0.3.

---

## Quick start

```bash
git clone <repo>
cd revo-live-dashboard
docker compose up --build
```
Browse to http://localhost:8050
The first minute may show “no data yet” until an initial scrape completes.