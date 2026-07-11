# Product Catalog Monitor

A production-oriented catalog extraction and monitoring system built with n8n, Python, Playwright, and PostgreSQL.

This project monitors the Amazon.com car-audio catalog with a hybrid architecture. It discovers catalog pages, extracts JavaScript-rendered product details, records change history, and exports normalized JSON or CSV data.

## Highlights

- **n8n workflow:** manual execution, weekly scheduling, status polling, and run summaries.
- **Playwright extraction:** Amazon pagination, ASIN normalization, JavaScript-rendered detail pages, lazy-loaded content, and individual reviews.
- **PostgreSQL persistence:** products, images, specifications, reviews, relations, variants, checkpoints, failures, price history, and availability history.
- **Incremental monitoring:** deterministic content hashes classify records as `new`, `updated`, `unchanged`, or `unavailable`.
- **Operational recovery:** per-URL checkpoints, bounded retries, failed-URL tracking, and resume support.
- **Portable results:** JSON and CSV exports for downstream websites or product databases.
- **Adapter-based design:** a site adapter isolates target-specific discovery and extraction rules from the shared run engine.

## Architecture

```text
Manual Trigger / Weekly Schedule
              |
              v
       n8n workflow
 Create -> Poll -> Summarize
              |
              v
       Flask Run API
              |
              v
 CatalogRunner + Checkpoints
      |              |
      v              v
Site Adapter      Playwright Browser
      |              |
      +--------------+
              |
              v
         PostgreSQL
```

## Requirement Coverage

| Requirement | Implementation |
|---|---|
| Complete catalog discovery | Amazon search pagination with ASIN normalization and deduplication |
| JavaScript-rendered pages | Playwright connected to persistent Chrome or container Chromium |
| Duplicate prevention | Canonical URL and external-ID database constraints |
| Incremental updates | Stable product content hash with price and availability history |
| Retry and recovery | Bounded retries, per-URL checkpoints, failed URL queue, resume endpoint |
| Manual and weekly runs | Importable n8n workflow with both triggers |
| Structured storage | Normalized PostgreSQL plus JSON and CSV exports |
| Responsible operation | Configurable request pacing; challenge pages are recorded, not bypassed |

## Quick Start

### Requirements

- Windows with Google Chrome
- Docker Desktop with Docker Compose v2
- At least 4 GB free memory

### 1. Prepare the Browser Profile

For Amazon runs, use the project-owned persistent Chrome profile:

1. Run `start-browser.bat`.
2. In the visible Chrome window, sign in to the operator's own Google account.
3. Open Amazon and confirm that a normal product page loads.
4. Close Chrome and run `start-browser.bat` again to confirm the session persists.

The local `browser-profile` directory contains browser session data. It is excluded from source control and must not be copied or distributed. Each operator creates and controls their own profile.

### 2. Start the Stack

```powershell
.\start.bat
```

This starts the visible Chrome browser, PostgreSQL, the catalog API, and n8n.

```powershell
docker compose ps
curl http://localhost:5000/health
```

Services:

- n8n: `http://localhost:5678`
- Catalog API: `http://localhost:5000`
- PostgreSQL: `localhost:5432`

### 3. Import and Run the n8n Workflow

1. Open `http://localhost:5678`.
2. Choose **Import from File** and select `n8n/product-catalog-monitor.json`.
3. Open **Product Catalog Monitor** and select **Run Configuration**.
4. Set `site` to `amazon-us`.
5. Use `full` for an initial snapshot or `incremental` for an update.
6. Set `max_products` to `3` for a short validation, or `0` for the complete configured catalog scope.
7. Click **Execute Workflow**.

The visible Chrome navigates search and product pages while n8n polls the API. The final n8n output includes discovered, new, updated, unchanged, unavailable, and error counts together with JSON and CSV export URLs.

### 4. Weekly Automation

After a successful manual validation, leave `run_type` as `incremental`, set `max_products` to `0`, and activate the workflow. The included schedule runs every Monday at 09:00 in the configured n8n timezone.

Stop the Docker services with:

```powershell
docker compose down
```

## Run Configuration

| Parameter | Value | Purpose |
|---|---:|---|
| `site` | `amazon-us` | Amazon US car-audio catalog adapter |
| `run_type` | `full` | Initial catalog snapshot |
| `run_type` | `incremental` | Compare against stored records |
| `max_products` | `3` | Short validation scope |
| `max_products` | `0` | Complete configured catalog scope |
| `request_delay_seconds` | `5` | Delay between product pages |
| `missing_threshold` | `2` | Mark unavailable after two qualifying complete runs |

For each Amazon detail page, the scraper waits for the title, waits an additional 15 seconds, applies 25% zoom, scrolls until page height stabilizes, then extracts lazy-loaded fields.

## Data and Exports

The normalized data model supports:

- product title, description, brand, model, SKU, pricing, stock state, category, and highlights;
- high-resolution images and specifications;
- individual reviews with reviewer name, date, rating, title, text, and Verified Purchase status;
- related product records, variants, price history, availability history, and raw structured data.

Run exports are available at:

```text
http://localhost:5000/runs/RUN_ID/export/json
http://localhost:5000/runs/RUN_ID/export/csv
```

The API also supports `GET /health`, `POST /runs`, `GET /runs/RUN_ID`, and `POST /runs/RUN_ID/resume`.

## Implementation Notes

The Amazon adapter starts at `https://www.amazon.com/s?k=car+audio+receiver`, traverses up to 20 configured result pages, reads `data-asin` values, removes duplicates, and normalizes product URLs to `https://www.amazon.com/dp/{ASIN}`.

The extraction engine separates stable product fields from rotating recommendation, review, and variant modules. This prevents changing page modules from creating false core-product updates. The review parser supports Amazon's newer `reviewText`, `reviewRichContentContainer`, and `reviewTitle` markup.

To add a client site, implement `SiteAdapter` in `scraper/adapters.py`, register the adapter, and add a `sites` record. The n8n workflow and API do not need redesign.

## Validation

```powershell
python -m py_compile scraper\config.py scraper\database.py scraper\browser.py scraper\adapters.py scraper\runner.py scraper\main.py
python -m unittest discover -s tests -v
```

Validated in the deployed environment:

- Python compilation and six core tests pass.
- Docker Compose, PostgreSQL, and catalog API health checks pass.
- Persistent Chrome communicates with the Docker scraper over CDP against real Amazon product pages.
- Amazon search discovery, normalized relational writes, individual review storage, JSON export, and CSV export were verified with real product data.

## Privacy and Ownership

All custom source code, workflow JSON, schema, and documentation are included in this repository. The local deployment does not require a developer-owned account, private token, or paid scraping platform.

Do not commit or distribute `browser-profile/` or local `.env` files. They are excluded by `.gitignore`.
