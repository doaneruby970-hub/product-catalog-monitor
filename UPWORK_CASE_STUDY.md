# Upwork Case Study: Product Catalog Monitor

## Short Summary

Product Catalog Monitor is a Python, Playwright, PostgreSQL, and n8n system for collecting product catalog data from JavaScript-rendered pages, storing normalized records, detecting changes, and exporting structured JSON or CSV results.

It is most relevant for clients who need:

- recurring website or product monitoring;
- browser automation for dynamic pages;
- structured data extraction into CSV, JSON, or a database;
- n8n workflow orchestration around a Python service;
- retry, checkpoint, and resume behavior for long-running jobs;
- clean handoff documentation instead of a one-off script.

## Business Problem

Many product research and catalog-monitoring tasks start as manual browser work: search a website, open product pages, copy key fields, check price or stock changes, and repeat the process weekly.

This project turns that workflow into a maintainable automation system. The operator can start a run from n8n, watch status updates, and download structured exports after the scraper finishes.

## What Was Built

- A Python Flask API that starts and monitors catalog runs.
- A Playwright scraper that connects to Chrome and handles dynamic product pages.
- A PostgreSQL schema for products, images, specifications, reviews, relationships, variants, checkpoints, failures, price history, and availability history.
- An n8n workflow with manual run, weekly schedule, polling, success summary, and failure summary paths.
- JSON and CSV export endpoints for downstream use.
- Recovery logic with per-URL checkpoints, bounded retries, failed URL tracking, and resume support.
- Documentation for local setup, operation, validation, and walkthrough recording.

## Technical Proof Points

| Client need | Evidence in this project |
|---|---|
| Dynamic website automation | Playwright browser control and JavaScript-rendered page extraction |
| Reliable recurring jobs | n8n schedule, status polling, run summaries, and API health checks |
| Clean structured output | Normalized PostgreSQL tables plus JSON and CSV exports |
| Duplicate prevention | Canonical URLs, external IDs, content hashes, and database constraints |
| Failure handling | Retry limits, failed URL queue, checkpoints, and resume endpoint |
| Maintainability | Site adapter pattern separates target-specific scraping from shared run logic |
| Handoff quality | README, walkthrough script, sample run summary, Docker Compose, and tests |

## Example Proposal Paragraph

I have built a closely related automation system: Product Catalog Monitor, a Python + Playwright + PostgreSQL + n8n workflow that collects product data from dynamic pages, stores normalized records, tracks changes, handles retries and checkpoints, and exports JSON/CSV results. Your workflow is different in business domain, but the engineering requirements are similar: reliable browser/API automation, structured outputs, failure visibility, and clear handoff documentation.

## Good-Fit Upwork Jobs

This repository is strongest evidence for proposals involving:

- web scraping and browser automation;
- product, pricing, inventory, or market research tools;
- Python scripts that produce Excel, CSV, or JSON outputs;
- n8n workflows around Python services;
- API integrations with retries and logging;
- recurring monitoring systems;
- cleaning up or extending an existing scraper.

It is not direct proof of production DataForSEO, Clearbit, Salesforce, HubSpot, or machine-learning model work. For those jobs, it should be presented as comparable automation and data-pipeline experience, not as direct platform-specific experience.

## Validation

The repository includes unit tests for URL normalization, price parsing, stable content hashing, and n8n workflow structure. The README also documents Python compilation, Docker Compose, API health checks, and a short real-data validation run.

## Links

- Main README: [README.md](README.md)
- n8n workflow: [n8n/product-catalog-monitor.json](n8n/product-catalog-monitor.json)
- Sample run summary: [demo/sample-run-summary.json](demo/sample-run-summary.json)
- Walkthrough script: [demo/WALKTHROUGH.md](demo/WALKTHROUGH.md)
