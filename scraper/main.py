"""HTTP API used by n8n to create, monitor, resume, and export catalog runs."""

import csv
import json
import logging
import os
import threading
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

from config import settings
from database import Database
from runner import CatalogRunner

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)
_active_runs = set()
_active_lock = threading.Lock()


def database() -> Database:
    return Database(settings.database_url)


def execute_in_background(run_id: int):
    with _active_lock:
        if run_id in _active_runs:
            return
        _active_runs.add(run_id)

    def worker():
        try:
            CatalogRunner(database()).execute(run_id)
        except Exception:
            logger.exception("Background run failed: %s", run_id)
        finally:
            with _active_lock:
                _active_runs.discard(run_id)

    threading.Thread(target=worker, name=f"catalog-run-{run_id}", daemon=True).start()


@app.get("/health")
def health():
    try:
        with database() as db:
            db_health = db.health()
        return jsonify({"status": "ok", "service": "catalog-monitor", "database": db_health})
    except Exception as error:
        return jsonify({"status": "degraded", "service": "catalog-monitor", "error": str(error)}), 503


@app.post("/runs")
def create_run():
    payload = request.get_json(silent=True) or {}
    site_code = payload.get("site", "webscraper-demo")
    run_type = payload.get("run_type", "incremental")
    if run_type not in {"full", "incremental"}:
        return jsonify({"error": "run_type must be full or incremental"}), 400
    options = payload.get("options") or {}
    with database() as db:
        run_id = db.create_run(site_code, run_type, options, payload.get("requested_by", "api"))
    execute_in_background(run_id)
    return jsonify({"run_id": run_id, "status": "pending", "status_url": f"/runs/{run_id}"}), 202


@app.get("/runs/<int:run_id>")
def get_run(run_id: int):
    with database() as db:
        run = db.get_run(run_id)
        if not run:
            return jsonify({"error": "run not found"}), 404
        item_counts = db.run_items_summary(run_id)
    run["items"] = item_counts
    return jsonify(run)


@app.post("/runs/<int:run_id>/resume")
def resume_run(run_id: int):
    with database() as db:
        run = db.get_run(run_id)
        if not run:
            return jsonify({"error": "run not found"}), 404
        if run["status"] in {"completed", "cancelled"}:
            return jsonify({"error": f"run cannot resume from status {run['status']}"}), 409
        if run["status"] == "completed_with_errors":
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE scrape_items
                    SET status = 'pending', completed_at = NULL, updated_at = NOW()
                    WHERE run_id = %s AND status IN ('failed', 'blocked')
                    """,
                    (run_id,),
                )
            db.commit()
        db.update_run(run_id, status="pending", completed_at=None)
    execute_in_background(run_id)
    return jsonify({"run_id": run_id, "status": "pending"}), 202


@app.get("/runs/<int:run_id>/export/<string:file_format>")
def export_run(run_id: int, file_format: str):
    if file_format not in {"json", "csv"}:
        return jsonify({"error": "supported formats: json, csv"}), 400
    with database() as db:
        run = db.get_run(run_id)
        if not run:
            return jsonify({"error": "run not found"}), 404
        rows = db.export_rows(run_id)

    export_dir = Path(settings.export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    output_path = export_dir / f"run-{run_id}.{file_format}"
    if file_format == "json":
        output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    else:
        columns = list(rows[0].keys()) if rows else []
        with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value for key, value in row.items()})
    return send_file(output_path, as_attachment=True)


@app.post("/scrape")
def backward_compatible_scrape():
    payload = request.get_json(silent=True) or {}
    payload = {
        "site": payload.get("site", "webscraper-demo"),
        "run_type": payload.get("mode", "incremental"),
        "options": {"max_products": payload.get("max_products")},
        "requested_by": "legacy-api",
    }
    with database() as db:
        run_id = db.create_run(payload["site"], payload["run_type"], payload["options"], payload["requested_by"])
    execute_in_background(run_id)
    return jsonify({"run_id": run_id, "status": "pending", "status_url": f"/runs/{run_id}"}), 202


if __name__ == "__main__":
    app.run(host=settings.api_host, port=settings.api_port, threaded=True)
