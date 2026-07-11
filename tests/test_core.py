import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRAPER = ROOT / "scraper"
sys.path.insert(0, str(SCRAPER))

from adapters import canonicalize_url, parse_price
from database import product_content_hash, stable_hash


class AdapterHelperTests(unittest.TestCase):
    def test_canonicalize_url_removes_query_fragment_and_trailing_slash(self):
        actual = canonicalize_url("HTTPS://Example.COM/products/123/?utm_source=test#details")
        self.assertEqual(actual, "https://example.com/products/123")

    def test_parse_price_handles_currency_and_commas(self):
        self.assertEqual(parse_price("$1,249.95"), Decimal("1249.95"))
        self.assertEqual(parse_price("USD 19"), Decimal("19"))
        self.assertIsNone(parse_price("Contact us"))


class ContentHashTests(unittest.TestCase):
    def test_stable_hash_ignores_dictionary_order(self):
        self.assertEqual(stable_hash({"a": 1, "b": 2}), stable_hash({"b": 2, "a": 1}))

    def test_product_hash_ignores_runtime_metadata(self):
        base = {
            "title": "Receiver",
            "current_price": Decimal("99.99"),
            "images": [{"url": "https://example.com/a.jpg"}],
            "specifications": [{"name": "Power", "value": "50W"}],
        }
        with_metadata = dict(base, scraped_at="2026-07-11T00:00:00Z", attempts=3)
        self.assertEqual(product_content_hash(base), product_content_hash(with_metadata))

    def test_product_hash_changes_when_tracked_field_changes(self):
        first = {"title": "Receiver", "current_price": Decimal("99.99")}
        second = {"title": "Receiver", "current_price": Decimal("109.99")}
        self.assertNotEqual(product_content_hash(first), product_content_hash(second))


class WorkflowTests(unittest.TestCase):
    def test_n8n_workflow_has_required_nodes_and_loop(self):
        workflow_path = ROOT / "n8n" / "product-catalog-monitor.json"
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        names = {node["name"] for node in workflow["nodes"]}
        required = {
            "Manual Run",
            "Weekly Monday 09:00",
            "Create Catalog Run",
            "Get Run Status",
            "Run Finished?",
            "Run Summary",
            "Failure Summary",
        }
        self.assertTrue(required.issubset(names))
        unfinished_branch = workflow["connections"]["Run Finished?"]["main"][1]
        self.assertEqual(unfinished_branch[0]["node"], "Wait 10 Seconds")


if __name__ == "__main__":
    unittest.main()
