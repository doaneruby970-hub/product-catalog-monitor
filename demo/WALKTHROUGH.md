# Recorded Walkthrough Script

## 1. Architecture (30 seconds)

Show `start-browser.bat`, `docker-compose.yml`, the n8n workflow, the Python service, and PostgreSQL. Explain that the project starts its own visible persistent Chrome on Windows; Python and Playwright connect to it over CDP while n8n remains the operator-facing scheduler.

## 2. First-time browser setup (45 seconds)

Before the first Amazon run:

1. Run `start-browser.bat` to create the local persistent Chrome profile.
2. Sign in to the operator's own Google account in the visible Chrome window.
3. Open Amazon and confirm that a normal product page loads.
4. Close Chrome, run `start-browser.bat` again, and confirm that the session persists.

Do not open or display files inside `browser-profile` during the recording. Each operator creates their own local profile, and the directory is excluded from source control.

## 3. Start the stack (45 seconds)

Run:

```powershell
.\start.bat
docker compose ps
```

Show the visible project Chrome, the healthy Docker services, and the scraper health endpoint. Open `http://localhost:5678` and import `n8n/product-catalog-monitor.json`.

## 4. Amazon catalog run (60 seconds)

Show the `amazon-us` catalog settings. Select the desired `run_type` and scope, then execute the workflow manually. Show search pagination, the polling loop, normalized product records, and the final run summary.

## 5. Structured data (45 seconds)

Show PostgreSQL records for products, high-resolution images, specifications, related products, variants, run items, and history. Download JSON and CSV from the URLs in the workflow summary.

## 6. Incremental run (45 seconds)

Run the workflow again with `incremental`. Explain that stable core catalog fields drive the deterministic content hash, while Amazon's rotating recommendation, review, and variant modules are persisted separately to avoid false product updates.

## 7. Recovery (45 seconds)

Explain that every URL is stored in `scrape_items`; interrupted `processing` items are reset to `pending`. A `completed_with_errors` run can also be resumed, requeueing only failed or blocked URLs without repeating successful items.

## 8. Compliance and handoff (30 seconds)

Show the configurable request delay and challenge-page detection. State that the system records blocked pages rather than bypassing authentication, CAPTCHAs, or access controls. Confirm that all source code, workflow JSON, schema, and documentation are included.
