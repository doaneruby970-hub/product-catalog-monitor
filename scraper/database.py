"""PostgreSQL persistence for catalog runs, products, relations, and checkpoints."""

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

import psycopg2
from psycopg2.extras import Json, RealDictCursor, execute_values


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def product_content_hash(product: Dict[str, Any]) -> str:
    tracked = {
        key: product.get(key)
        for key in (
            "title", "description", "brand", "model_number", "sku", "current_price",
            "original_price", "currency", "availability", "category", "subcategory",
            "highlights", "whats_in_the_box", "rating", "review_count", "images",
            "specifications",
        )
    }
    return stable_hash(tracked)


class Database:
    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/upwork_demo",
        )
        self.connection = None

    def connect(self):
        if self.connection is None or self.connection.closed:
            self.connection = psycopg2.connect(self.dsn, cursor_factory=RealDictCursor)
            self.connection.autocommit = False
        return self.connection

    def close(self):
        if self.connection is not None and not self.connection.closed:
            self.connection.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.connection is not None and not self.connection.closed:
            if exc_type:
                self.connection.rollback()
            else:
                self.connection.commit()
        self.close()

    @contextmanager
    def cursor(self):
        connection = self.connect()
        cursor = connection.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    def commit(self):
        self.connect().commit()

    def rollback(self):
        self.connect().rollback()

    def health(self) -> Dict[str, Any]:
        with self.cursor() as cursor:
            cursor.execute("SELECT NOW() AS server_time, current_database() AS database")
            return dict(cursor.fetchone())

    def get_site(self, code: str) -> Dict[str, Any]:
        with self.cursor() as cursor:
            cursor.execute("SELECT * FROM sites WHERE code = %s AND enabled = TRUE", (code,))
            site = cursor.fetchone()
            if not site:
                raise ValueError(f"Unknown or disabled site: {code}")
            return dict(site)

    def create_run(
        self,
        site_code: str,
        run_type: str,
        options: Optional[Dict[str, Any]] = None,
        requested_by: str = "api",
    ) -> int:
        site = self.get_site(site_code)
        with self.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO scrape_runs (site_id, run_type, status, requested_by, options)
                VALUES (%s, %s, 'pending', %s, %s)
                RETURNING id
                """,
                (site["id"], run_type, requested_by, Json(options or {})),
            )
            run_id = cursor.fetchone()["id"]
        self.commit()
        return run_id

    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.*, s.code AS site_code, s.name AS site_name, s.base_url, s.adapter,
                       s.settings AS site_settings
                FROM scrape_runs r
                JOIN sites s ON s.id = r.site_id
                WHERE r.id = %s
                """,
                (run_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def start_run(self, run_id: int):
        with self.cursor() as cursor:
            cursor.execute(
                "UPDATE scrape_runs SET status = 'running', started_at = COALESCE(started_at, NOW()) WHERE id = %s",
                (run_id,),
            )
        self.commit()

    def update_run(self, run_id: int, **values):
        allowed = {
            "status", "checkpoint", "products_discovered", "products_processed", "products_new",
            "products_updated", "products_unchanged", "products_unavailable", "errors", "summary",
            "completed_at",
        }
        fields = []
        params = []
        for key, value in values.items():
            if key not in allowed:
                continue
            fields.append(f"{key} = %s")
            params.append(Json(value) if key in {"checkpoint", "summary"} else value)
        if not fields:
            return
        params.append(run_id)
        with self.cursor() as cursor:
            cursor.execute(f"UPDATE scrape_runs SET {', '.join(fields)} WHERE id = %s", params)
        self.commit()

    def finish_run(self, run_id: int, status: str, summary: Dict[str, Any]):
        with self.cursor() as cursor:
            cursor.execute(
                """
                UPDATE scrape_runs
                SET status = %s, summary = %s, completed_at = NOW()
                WHERE id = %s
                """,
                (status, Json(summary), run_id),
            )
        self.commit()

    def enqueue_urls(self, run_id: int, urls: Iterable[str]):
        rows = [(run_id, url) for url in dict.fromkeys(urls)]
        if not rows:
            return
        with self.cursor() as cursor:
            execute_values(
                cursor,
                "INSERT INTO scrape_items (run_id, url) VALUES %s ON CONFLICT (run_id, url) DO NOTHING",
                rows,
            )
        self.commit()

    def reset_interrupted_items(self, run_id: int):
        with self.cursor() as cursor:
            cursor.execute(
                """
                UPDATE scrape_items SET status = 'pending', updated_at = NOW()
                WHERE run_id = %s AND status = 'processing'
                """,
                (run_id,),
            )
        self.commit()

    def pending_items(self, run_id: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM scrape_items WHERE run_id = %s AND status = 'pending' ORDER BY id"
        params: List[Any] = [run_id]
        if limit:
            query += " LIMIT %s"
            params.append(limit)
        with self.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def mark_item_processing(self, item_id: int):
        with self.cursor() as cursor:
            cursor.execute(
                """
                UPDATE scrape_items
                SET status = 'processing', attempts = attempts + 1,
                    started_at = COALESCE(started_at, NOW()), updated_at = NOW()
                WHERE id = %s
                """,
                (item_id,),
            )
        self.commit()

    def complete_item(self, item_id: int, status: str, result: Optional[Dict[str, Any]] = None):
        with self.cursor() as cursor:
            cursor.execute(
                """
                UPDATE scrape_items
                SET status = %s, result = %s, completed_at = NOW(), updated_at = NOW(),
                    error_type = NULL, error_message = NULL
                WHERE id = %s
                """,
                (status, Json(result or {}), item_id),
            )
        self.commit()

    def fail_item(self, item_id: int, error_type: str, message: str, blocked: bool = False):
        status = "blocked" if blocked else "failed"
        with self.cursor() as cursor:
            cursor.execute(
                """
                UPDATE scrape_items
                SET status = %s, error_type = %s, error_message = %s,
                    completed_at = NOW(), updated_at = NOW()
                WHERE id = %s
                RETURNING run_id, url
                """,
                (status, error_type, message[:4000], item_id),
            )
            item = cursor.fetchone()
            cursor.execute("SELECT site_id FROM scrape_runs WHERE id = %s", (item["run_id"],))
            site_id = cursor.fetchone()["site_id"]
            cursor.execute(
                """
                INSERT INTO failed_urls (site_id, run_id, url, error_type, error_message)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (site_id, url, run_id) DO UPDATE SET
                    error_type = EXCLUDED.error_type,
                    error_message = EXCLUDED.error_message,
                    retry_count = failed_urls.retry_count + 1,
                    last_retry_at = NOW(),
                    updated_at = NOW()
                """,
                (site_id, item["run_id"], item["url"], error_type, message[:4000]),
            )
        self.commit()

    def get_product_by_url(self, site_id: int, canonical_url: str) -> Optional[Dict[str, Any]]:
        with self.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM products WHERE site_id = %s AND canonical_url = %s",
                (site_id, canonical_url),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def all_product_urls(self, site_id: int) -> List[str]:
        with self.cursor() as cursor:
            cursor.execute("SELECT canonical_url FROM products WHERE site_id = %s", (site_id,))
            return [row["canonical_url"] for row in cursor.fetchall()]

    def upsert_product(self, run_id: int, site_id: int, product: Dict[str, Any]) -> Dict[str, Any]:
        canonical_url = product["canonical_url"]
        content_hash = product_content_hash(product)
        existing = self.get_product_by_url(site_id, canonical_url)
        change_status = "new" if existing is None else "unchanged"
        if existing and existing["content_hash"] != content_hash:
            change_status = "updated"

        with self.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO products (
                    site_id, external_id, canonical_url, title, description, brand, model_number, sku,
                    current_price, original_price, currency, availability, category, subcategory,
                    highlights, whats_in_the_box, rating, review_count, content_hash, raw_data
                ) VALUES (
                    %(site_id)s, %(external_id)s, %(canonical_url)s, %(title)s, %(description)s,
                    %(brand)s, %(model_number)s, %(sku)s, %(current_price)s, %(original_price)s,
                    %(currency)s, %(availability)s, %(category)s, %(subcategory)s, %(highlights)s,
                    %(whats_in_the_box)s, %(rating)s, %(review_count)s, %(content_hash)s, %(raw_data)s
                )
                ON CONFLICT (site_id, canonical_url) DO UPDATE SET
                    external_id = EXCLUDED.external_id,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    brand = EXCLUDED.brand,
                    model_number = EXCLUDED.model_number,
                    sku = EXCLUDED.sku,
                    current_price = EXCLUDED.current_price,
                    original_price = EXCLUDED.original_price,
                    currency = EXCLUDED.currency,
                    availability = EXCLUDED.availability,
                    category = EXCLUDED.category,
                    subcategory = EXCLUDED.subcategory,
                    highlights = EXCLUDED.highlights,
                    whats_in_the_box = EXCLUDED.whats_in_the_box,
                    rating = EXCLUDED.rating,
                    review_count = EXCLUDED.review_count,
                    content_hash = EXCLUDED.content_hash,
                    raw_data = EXCLUDED.raw_data,
                    last_seen_at = NOW(),
                    last_scraped_at = NOW(),
                    unavailable_since = NULL,
                    consecutive_missing_runs = 0,
                    updated_at = NOW()
                RETURNING id
                """,
                {
                    "site_id": site_id,
                    "external_id": product.get("external_id"),
                    "canonical_url": canonical_url,
                    "title": product.get("title") or "Untitled product",
                    "description": product.get("description"),
                    "brand": product.get("brand"),
                    "model_number": product.get("model_number"),
                    "sku": product.get("sku"),
                    "current_price": product.get("current_price"),
                    "original_price": product.get("original_price"),
                    "currency": product.get("currency") or "USD",
                    "availability": product.get("availability"),
                    "category": product.get("category"),
                    "subcategory": product.get("subcategory"),
                    "highlights": Json(product.get("highlights") or []),
                    "whats_in_the_box": Json(product.get("whats_in_the_box") or []),
                    "rating": product.get("rating"),
                    "review_count": product.get("review_count") or 0,
                    "content_hash": content_hash,
                    "raw_data": Json(product.get("raw_data") or {}),
                },
            )
            product_id = cursor.fetchone()["id"]

            if existing and existing.get("current_price") != product.get("current_price"):
                cursor.execute(
                    """
                    INSERT INTO price_history (product_id, run_id, old_price, new_price, currency)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        product_id, run_id, existing.get("current_price"), product.get("current_price"),
                        product.get("currency") or "USD",
                    ),
                )
            if existing and existing.get("availability") != product.get("availability"):
                cursor.execute(
                    """
                    INSERT INTO availability_history (product_id, run_id, old_status, new_status)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (product_id, run_id, existing.get("availability"), product.get("availability")),
                )

            self._sync_children(cursor, product_id, product)

        self.commit()
        return {"product_id": product_id, "status": change_status, "content_hash": content_hash}

    def _sync_children(self, cursor, product_id: int, product: Dict[str, Any]):
        cursor.execute(
            "DELETE FROM product_images WHERE product_id = %s AND image_url <> ALL(%s)",
            (product_id, [image["url"] for image in product.get("images", [])] or [""]),
        )
        for position, image in enumerate(product.get("images", [])):
            cursor.execute(
                """
                INSERT INTO product_images (
                    product_id, image_url, high_resolution_url, image_type, display_order, content_hash
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (product_id, image_url) DO UPDATE SET
                    high_resolution_url = EXCLUDED.high_resolution_url,
                    image_type = EXCLUDED.image_type,
                    display_order = EXCLUDED.display_order,
                    content_hash = EXCLUDED.content_hash,
                    last_seen_at = NOW()
                """,
                (
                    product_id, image["url"], image.get("high_resolution_url"),
                    image.get("type", "gallery"), position, stable_hash(image),
                ),
            )

        for table in ("product_specifications", "product_reviews", "product_relations", "product_variants"):
            cursor.execute(f"DELETE FROM {table} WHERE product_id = %s", (product_id,))

        for spec in product.get("specifications", []):
            cursor.execute(
                """
                INSERT INTO product_specifications (product_id, section, spec_name, spec_value)
                VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (product_id, spec.get("section", "General"), spec["name"], spec["value"]),
            )
        for review in product.get("reviews", []):
            review_hash = review.get("review_hash") or stable_hash(review)
            cursor.execute(
                """
                INSERT INTO product_reviews (
                    product_id, external_review_id, reviewer_name, review_date, rating,
                    review_title, review_text, verified_purchase, review_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    product_id, review.get("external_id"), review.get("reviewer_name"),
                    review.get("review_date"), review.get("rating"), review.get("title"),
                    review.get("text"), review.get("verified_purchase"), review_hash,
                ),
            )
        for relation in product.get("relations", []):
            cursor.execute(
                """
                INSERT INTO product_relations (
                    product_id, relation_type, related_external_id, related_name, related_url,
                    related_sku, related_price, currency
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    product_id, relation["type"], relation.get("external_id"), relation["name"],
                    relation.get("url"), relation.get("sku"), relation.get("price"),
                    relation.get("currency", "USD"),
                ),
            )
        for variant in product.get("variants", []):
            cursor.execute(
                """
                INSERT INTO product_variants (
                    product_id, variant_name, variant_value, variant_sku, variant_url, price, availability
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    product_id, variant["name"], variant["value"], variant.get("sku"),
                    variant.get("url"), variant.get("price"), variant.get("availability"),
                ),
            )

    def mark_missing_products(self, run_id: int, site_id: int, current_urls: Iterable[str], threshold: int = 2) -> int:
        urls = list(current_urls)
        with self.cursor() as cursor:
            cursor.execute(
                """
                UPDATE products
                SET consecutive_missing_runs = consecutive_missing_runs + 1,
                    unavailable_since = CASE
                        WHEN consecutive_missing_runs + 1 >= %s THEN COALESCE(unavailable_since, NOW())
                        ELSE unavailable_since
                    END,
                    availability = CASE
                        WHEN consecutive_missing_runs + 1 >= %s THEN 'unavailable'
                        ELSE availability
                    END,
                    updated_at = NOW()
                WHERE site_id = %s AND NOT (canonical_url = ANY(%s))
                RETURNING id, availability
                """,
                (threshold, threshold, site_id, urls or [""]),
            )
            changed = cursor.fetchall()
            unavailable_count = sum(1 for row in changed if row["availability"] == "unavailable")
        self.commit()
        return unavailable_count

    def run_items_summary(self, run_id: int) -> Dict[str, int]:
        with self.cursor() as cursor:
            cursor.execute(
                "SELECT status, COUNT(*) AS count FROM scrape_items WHERE run_id = %s GROUP BY status",
                (run_id,),
            )
            return {row["status"]: row["count"] for row in cursor.fetchall()}

    def export_rows(self, run_id: int) -> List[Dict[str, Any]]:
        with self.cursor() as cursor:
            cursor.execute(
                """
                SELECT p.*, s.code AS site_code
                FROM products p
                JOIN sites s ON s.id = p.site_id
                JOIN scrape_runs r ON r.site_id = p.site_id
                WHERE r.id = %s
                ORDER BY p.id
                """,
                (run_id,),
            )
            rows = []
            for row in cursor.fetchall():
                normalized = dict(row)
                for key, value in normalized.items():
                    if isinstance(value, (datetime, Decimal)):
                        normalized[key] = str(value)
                rows.append(normalized)
            return rows
