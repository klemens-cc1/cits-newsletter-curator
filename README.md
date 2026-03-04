# CITS Newsletter Curator

A curation tool for newsletter production. Aggregates keyword-matched articles from RSS feeds, presents them in a sortable/searchable UI, and exports selections for manual newsletter writing.

## Local Development

```bash
pip install -r requirements.txt
cp .env.example .env
python main.py
# Visit http://localhost:5000
```

## Deploy to Render

1. Push this repo to GitHub
2. Go to render.com → New → Blueprint
3. Connect your repo — Render reads `render.yaml` and provisions the web service + Postgres database automatically
4. Copy the generated `INGEST_API_KEY` from Render environment variables — you'll need it for the aggregator

## Aggregator Integration

Add these to your `energy-security-aggregator` GitHub Secrets:
- `CURATOR_URL` — your Render app URL e.g. `https://cits-newsletter-curator.onrender.com`
- `CURATOR_API_KEY` — the `INGEST_API_KEY` from Render

Then add a push step to `main.py` in the aggregator (Step 2 of the build).

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Curation UI |
| `/api/articles` | GET | List articles with filters |
| `/api/articles/<id>` | PATCH | Update status/note |
| `/api/ingest` | POST | Receive articles from aggregator |
| `/api/stats` | GET | Counts by category/status |
| `/api/export` | GET | Download CSV or Markdown |
| `/api/filters` | GET | Available categories and sources |

## Article Statuses

- `unreviewed` — default, not yet looked at
- `selected` — include in newsletter
- `maybe` — possible inclusion, review again
- `skip` — not relevant
