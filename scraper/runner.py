"""Catalog run orchestration with checkpoints, retries, and incremental comparison."""

import logging
import time
from collections import Counter
from typing import Any, Dict, Optional

from adapters import create_adapter
from browser import AccessBlockedError, BrowserManager
from config import settings
from database import Database

logger = logging.getLogger(__name__)


class CatalogRunner:
    def __init__(self, database: Optional[Database] = None):
        self.database = database or Database(settings.database_url)

    def execute(self, run_id: int) -> Dict[str, Any]:
        run = self.database.get_run(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")
        if run["status"] in {"completed", "completed_with_errors", "cancelled"}:
            return run.get("summary") or {}

        options = run.get("options") or {}
        max_products = options.get("max_products")
        delay = float(options.get("request_delay_seconds", settings.request_delay_seconds))
        self.database.start_run(run_id)
        self.database.reset_interrupted_items(run_id)

        try:
            with BrowserManager() as browser:
                adapter = create_adapter(browser, run)
                existing_items = self.database.pending_items(run_id, limit=1)
                checkpoint = run.get("checkpoint") or {}

                if not checkpoint.get("discovery_complete"):
                    urls = adapter.discover_product_urls(max_products=max_products)
                    self.database.enqueue_urls(run_id, urls)
                    self.database.update_run(
                        run_id,
                        products_discovered=len(urls),
                        checkpoint={"discovery_complete": True, "discovered_urls": len(urls)},
                    )
                elif not existing_items:
                    # A resumed run can have no pending items because all work was already persisted.
                    urls = []
                else:
                    urls = []

                pending = self.database.pending_items(run_id)
                for index, item in enumerate(pending, start=1):
                    self.database.mark_item_processing(item["id"])
                    try:
                        product = adapter.extract_product(item["url"])
                        outcome = self.database.upsert_product(run_id, run["site_id"], product)
                        self.database.complete_item(item["id"], outcome["status"], outcome)
                    except AccessBlockedError as error:
                        self.database.rollback()
                        logger.warning("Blocked page %s: %s", item["url"], error)
                        self.database.fail_item(item["id"], "access_blocked", str(error), blocked=True)
                    except Exception as error:
                        self.database.rollback()
                        logger.exception("Product processing failed: %s", item["url"])
                        self.database.fail_item(item["id"], type(error).__name__, str(error))

                    counts = self.database.run_items_summary(run_id)
                    processed = sum(counts.get(key, 0) for key in ("new", "updated", "unchanged", "failed", "blocked", "skipped"))
                    self.database.update_run(
                        run_id,
                        products_processed=processed,
                        products_new=counts.get("new", 0),
                        products_updated=counts.get("updated", 0),
                        products_unchanged=counts.get("unchanged", 0),
                        errors=counts.get("failed", 0) + counts.get("blocked", 0),
                        checkpoint={
                            "discovery_complete": True,
                            "last_item_id": item["id"],
                            "processed": processed,
                        },
                    )
                    if delay > 0 and index < len(pending):
                        time.sleep(delay)

                current_urls = self._successful_urls(run_id)
                unavailable = 0
                if not max_products:
                    unavailable = self.database.mark_missing_products(
                        run_id,
                        run["site_id"],
                        current_urls,
                        threshold=int(options.get("missing_threshold", settings.missing_threshold)),
                    )
                self.database.update_run(run_id, products_unavailable=unavailable)

            counts = self.database.run_items_summary(run_id)
            errors = counts.get("failed", 0) + counts.get("blocked", 0)
            status = "completed_with_errors" if errors else "completed"
            summary = {
                "run_id": run_id,
                "site": run["site_code"],
                "run_type": run["run_type"],
                "status": status,
                "items": counts,
                "unavailable": unavailable,
                "resumable": True,
            }
            self.database.finish_run(run_id, status, summary)
            return summary
        except Exception as error:
            self.database.rollback()
            logger.exception("Run %s failed", run_id)
            summary = {
                "run_id": run_id,
                "site": run["site_code"],
                "run_type": run["run_type"],
                "status": "failed",
                "error": str(error),
                "resumable": True,
            }
            self.database.finish_run(run_id, "failed", summary)
            raise

    def _successful_urls(self, run_id: int):
        with self.database.cursor() as cursor:
            cursor.execute(
                """
                SELECT url FROM scrape_items
                WHERE run_id = %s AND status IN ('new', 'updated', 'unchanged')
                """,
                (run_id,),
            )
            return [row["url"] for row in cursor.fetchall()]
