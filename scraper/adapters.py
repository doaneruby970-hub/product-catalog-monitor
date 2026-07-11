"""Site adapters isolate website-specific discovery and extraction rules."""

import json
import logging
import re
import time
from datetime import datetime
from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

from browser import BrowserManager


logger = logging.getLogger(__name__)


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def parse_price(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    match = re.search(r"-?[\d,]+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def text_or_none(locator) -> Optional[str]:
    try:
        if locator.count() == 0:
            return None
        value = locator.first.inner_text(timeout=2000).strip()
        return value or None
    except Exception:
        return None


class SiteAdapter(ABC):
    def __init__(self, browser: BrowserManager, site: Dict[str, Any]):
        self.browser = browser
        self.site = site
        self.base_url = site["base_url"]

    @abstractmethod
    def discover_product_urls(self, max_products: Optional[int] = None) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def extract_product(self, url: str) -> Dict[str, Any]:
        raise NotImplementedError


class WebScraperDemoAdapter(SiteAdapter):
    """Stable public test-site adapter used for deterministic validation."""

    def discover_product_urls(self, max_products: Optional[int] = None) -> List[str]:
        page = self.browser.navigate(self.base_url, ".category-link")
        category_urls = {
            canonicalize_url(urljoin(self.base_url, href))
            for href in page.locator(".category-link").evaluate_all(
                "els => els.map(el => el.getAttribute('href')).filter(Boolean)"
            )
        }
        found = set()
        for category_url in sorted(category_urls):
            current_url = category_url
            visited_pages = set()
            while current_url and current_url not in visited_pages:
                visited_pages.add(current_url)
                page = self.browser.navigate(current_url, ".card.thumbnail")
                hrefs = page.locator(".card.thumbnail a.title, .card.thumbnail a").evaluate_all(
                    "els => els.map(el => el.getAttribute('href')).filter(Boolean)"
                )
                page_urls = sorted({canonicalize_url(urljoin(page.url, href)) for href in hrefs})
                found.update(page_urls)
                if max_products and len(found) >= max_products:
                    return sorted(found)[:max_products]
                next_href = None
                try:
                    next_href = page.locator("a[rel='next']").first.get_attribute("href")
                except Exception:
                    pass
                current_url = canonicalize_url(urljoin(page.url, next_href)) if next_href else None
        return sorted(found)

    def extract_product(self, url: str) -> Dict[str, Any]:
        page = self.browser.navigate(url, ".title")
        json_ld = self._json_ld(page)
        title = text_or_none(page.locator("h4.title, .title")) or json_ld.get("name") or "Untitled product"
        description = text_or_none(page.locator(".description")) or json_ld.get("description")
        price_text = text_or_none(page.locator(".price"))
        rating = self._rating(page)
        review_count = self._review_count(page)
        images = self._images(page, json_ld)
        category_parts = [
            value.strip()
            for value in page.locator(".breadcrumb li").all_inner_texts()
            if value.strip() and value.strip().lower() != "home"
        ]
        external_id = urlsplit(url).path.rstrip("/").split("/")[-1]
        brand = json_ld.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")

        product = {
            "external_id": external_id,
            "canonical_url": canonicalize_url(url),
            "title": title,
            "description": description,
            "brand": brand or title.split()[0],
            "model_number": json_ld.get("model"),
            "sku": json_ld.get("sku") or external_id,
            "current_price": parse_price(price_text or json_ld.get("offers", {}).get("price")),
            "original_price": None,
            "currency": json_ld.get("offers", {}).get("priceCurrency", "USD"),
            "availability": self._availability(json_ld),
            "category": category_parts[0] if category_parts else None,
            "subcategory": category_parts[1] if len(category_parts) > 1 else None,
            "highlights": [description] if description else [],
            "whats_in_the_box": [],
            "rating": rating,
            "review_count": review_count,
            "images": images,
            "specifications": self._specifications(page),
            "reviews": self._reviews(page),
            "relations": [],
            "variants": [],
            "raw_data": {"json_ld": json_ld, "source": "webscraper-demo"},
        }
        return product

    def _json_ld(self, page) -> Dict[str, Any]:
        for raw in page.locator("script[type='application/ld+json']").all_text_contents():
            try:
                value = json.loads(raw)
                candidates = value if isinstance(value, list) else [value]
                for candidate in candidates:
                    if isinstance(candidate, dict) and candidate.get("@type") == "Product":
                        return candidate
            except (json.JSONDecodeError, TypeError):
                continue
        return {}

    def _images(self, page, json_ld: Dict[str, Any]) -> List[Dict[str, Any]]:
        urls = []
        ld_images = json_ld.get("image") or []
        if isinstance(ld_images, str):
            ld_images = [ld_images]
        urls.extend(ld_images)
        for src in page.locator("img.image, img.product-img, .product-gallery img").evaluate_all(
            "els => els.map(el => el.currentSrc || el.src || el.getAttribute('data-src')).filter(Boolean)"
        ):
            urls.append(urljoin(page.url, src))
        unique = list(dict.fromkeys(urls))
        return [
            {"url": value, "high_resolution_url": value, "type": "main" if index == 0 else "gallery"}
            for index, value in enumerate(unique)
        ]

    def _specifications(self, page) -> List[Dict[str, str]]:
        specs = []
        for row in page.locator("table tr").all():
            cells = [value.strip() for value in row.locator("th, td").all_inner_texts() if value.strip()]
            if len(cells) >= 2:
                specs.append({"section": "General", "name": cells[0], "value": " | ".join(cells[1:])})
        return specs

    def _reviews(self, page) -> List[Dict[str, Any]]:
        reviews = []
        for element in page.locator(".review, [itemprop='review']").all():
            text = text_or_none(element.locator(".review-text, [itemprop='reviewBody']"))
            if not text:
                continue
            reviews.append({
                "reviewer_name": text_or_none(element.locator(".reviewer, [itemprop='author']")),
                "review_date": None,
                "rating": parse_price(text_or_none(element.locator(".rating, [itemprop='ratingValue']"))),
                "title": text_or_none(element.locator(".review-title, [itemprop='name']")),
                "text": text,
                "verified_purchase": None,
            })
        return reviews

    def _rating(self, page) -> Optional[Decimal]:
        locator = page.locator("[data-rating], .rating")
        try:
            data_rating = locator.first.get_attribute("data-rating", timeout=2000) if locator.count() else None
        except Exception:
            data_rating = None
        return parse_price(data_rating or text_or_none(locator))

    def _review_count(self, page) -> int:
        text = text_or_none(page.locator(".ratings p, .review-count")) or "0"
        match = re.search(r"\d+", text.replace(",", ""))
        return int(match.group()) if match else 0

    def _availability(self, json_ld: Dict[str, Any]) -> str:
        value = str((json_ld.get("offers") or {}).get("availability", "")).lower()
        if "outofstock" in value:
            return "out_of_stock"
        return "in_stock"


class AmazonAdapter(SiteAdapter):
    """Amazon public product-page adapter driven by configured ASIN/URL seeds."""

    ASIN_PATTERN = re.compile(r"/(?:dp|gp/product)/(?:product/)?([A-Z0-9]{10})(?:[/?]|$)", re.I)

    def discover_product_urls(self, max_products: Optional[int] = None) -> List[str]:
        settings = self.site.get("settings") or {}
        search_urls = settings.get("catalog_urls") or []
        max_pages = int(settings.get("catalog_max_pages", 20))
        discovery_delay = float(settings.get("discovery_delay_seconds", 3))
        asins = set()

        for search_url in search_urls:
            current_url = str(search_url)
            visited_pages = set()
            for page_number in range(1, max_pages + 1):
                if not current_url or current_url in visited_pages:
                    break
                visited_pages.add(current_url)
                page = self.browser.navigate(current_url, "div[data-component-type='s-search-result']")
                page_asins = page.locator(
                    "div[data-component-type='s-search-result'][data-asin]:not([data-asin=''])"
                ).evaluate_all("elements => elements.map(element => element.dataset.asin)")
                asins.update(
                    asin.upper() for asin in page_asins
                    if re.fullmatch(r"[A-Z0-9]{10}", asin or "", re.I)
                )
                logger.info(
                    "Amazon catalog discovery page %s: %s unique ASINs",
                    page_number,
                    len(asins),
                )
                if max_products and len(asins) >= max_products:
                    return [f"https://www.amazon.com/dp/{asin}" for asin in sorted(asins)[:max_products]]
                next_link = page.locator("a.s-pagination-next:not(.s-pagination-disabled)")
                current_url = next_link.first.get_attribute("href") if next_link.count() else None
                if current_url:
                    current_url = urljoin(page.url, current_url)
                    time.sleep(discovery_delay)

        for value in settings.get("seed_urls") or []:
            asin = self._asin(str(value))
            if asin:
                asins.add(asin)
        urls = [f"https://www.amazon.com/dp/{asin}" for asin in sorted(asins)]
        return urls[:max_products] if max_products else urls

    def extract_product(self, url: str) -> Dict[str, Any]:
        asin = self._asin(url)
        if not asin:
            raise ValueError(f"Amazon URL has no valid ASIN: {url}")
        canonical_url = f"https://www.amazon.com/dp/{asin}"
        page = self.browser.navigate(canonical_url, "#productTitle")
        self._load_lazy_content(page)
        title = text_or_none(page.locator("span#productTitle")) or "Untitled Amazon product"
        category_parts = [
            value.strip()
            for value in page.locator("#wayfinding-breadcrumbs_feature_div li a").all_inner_texts()
            if value.strip()
        ]
        specifications = self._specifications(page)
        spec_map = {item["name"].lower(): item["value"] for item in specifications}
        current_price = parse_price(text_or_none(page.locator(
            "#corePrice_feature_div .a-price .a-offscreen, #corePriceDisplay_desktop_feature_div .a-price .a-offscreen, #priceblock_ourprice"
        )))
        original_price = parse_price(text_or_none(page.locator(
            "#corePrice_feature_div .a-text-price .a-offscreen, #corePriceDisplay_desktop_feature_div .a-text-price .a-offscreen"
        )))
        availability_text = text_or_none(page.locator("#availability")) or ""
        brand = text_or_none(page.locator("#bylineInfo")) or spec_map.get("brand")
        if brand:
            brand = re.sub(r"^(Visit the |Brand:\s*)| Store$", "", brand, flags=re.I).strip()
        highlights = [
            value.strip()
            for value in page.locator("#feature-bullets li span.a-list-item").all_inner_texts()
            if value.strip() and "see more product details" not in value.lower()
        ]
        included = spec_map.get("included components", "")
        rating_text = text_or_none(page.locator("#acrPopover"))
        review_count_text = text_or_none(page.locator("#acrCustomerReviewText")) or "0"
        count_match = re.search(r"[\d,]+", review_count_text)

        return {
            "external_id": asin,
            "canonical_url": canonical_url,
            "title": title,
            "description": self._description(page),
            "brand": brand,
            "model_number": spec_map.get("model name") or spec_map.get("item model number"),
            "sku": asin,
            "current_price": current_price,
            "original_price": original_price,
            "currency": "USD",
            "availability": "out_of_stock" if "unavailable" in availability_text.lower() else "in_stock",
            "category": category_parts[0] if category_parts else None,
            "subcategory": category_parts[-1] if len(category_parts) > 1 else None,
            "highlights": highlights,
            "whats_in_the_box": [value.strip() for value in included.split(",") if value.strip()],
            "rating": parse_price(rating_text),
            "review_count": int(count_match.group().replace(",", "")) if count_match else 0,
            "images": self._images(page),
            "specifications": specifications,
            "reviews": self._reviews(page),
            "relations": self._relations(page, asin),
            "variants": self._variants(page, asin),
            "raw_data": {
                "source": "amazon.com",
                "asin": asin,
                "availability_text": availability_text,
            },
        }

    def _asin(self, value: str) -> Optional[str]:
        if re.fullmatch(r"[A-Z0-9]{10}", value.strip(), re.I):
            return value.strip().upper()
        match = self.ASIN_PATTERN.search(value)
        return match.group(1).upper() if match else None

    def _description(self, page) -> Optional[str]:
        parts = []
        for selector in ("#productDescription", "#aplus", "#bookDescription_feature_div"):
            value = text_or_none(page.locator(selector))
            if value and value not in parts:
                parts.append(value)
        return "\n\n".join(parts) or None

    def _specifications(self, page) -> List[Dict[str, str]]:
        specs = []
        selectors = (
            "#productOverview_feature_div tr",
            "#productDetails_techSpec_section_1 tr",
            "#productDetails_detailBullets_sections1 tr",
        )
        for selector in selectors:
            for row in page.locator(selector).all():
                cells = [value.strip() for value in row.locator("th, td").all_inner_texts() if value.strip()]
                if len(cells) >= 2:
                    item = {"section": "Amazon Product Details", "name": cells[0], "value": " | ".join(cells[1:])}
                    if item not in specs:
                        specs.append(item)
        return sorted(specs, key=lambda item: (item["section"], item["name"], item["value"]))

    def _images(self, page) -> List[Dict[str, Any]]:
        values = page.evaluate("""
            () => {
                const out = [];
                const main = document.querySelector('#landingImage');
                if (main) {
                    const dynamic = main.getAttribute('data-a-dynamic-image');
                    if (dynamic) {
                        try { out.push(...Object.keys(JSON.parse(dynamic))); } catch (e) {}
                    }
                    out.push(main.getAttribute('data-old-hires'), main.currentSrc, main.src);
                }
                document.querySelectorAll('#altImages img').forEach(img => out.push(img.currentSrc || img.src));
                return out.filter(Boolean);
            }
        """)
        high_resolution_urls = {
            re.sub(r"\._[^.]+_\.(jpg|jpeg|png|webp)$", r".\1", value, flags=re.I)
            for value in values
        }
        return [
            {
                "url": value,
                "high_resolution_url": value,
                "type": "main" if index == 0 else "gallery",
            }
            for index, value in enumerate(sorted(high_resolution_urls))
        ]

    def _load_lazy_content(self, page):
        page.evaluate("document.body.style.zoom = '25%'; window.scrollTo(0, 0)")
        stable_bottom_checks = 0
        previous_height = 0
        for _ in range(45):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(600)
            state = page.evaluate("""
                () => ({
                    height: document.body.scrollHeight,
                    atBottom: window.scrollY + window.innerHeight >= document.body.scrollHeight - 30
                })
            """)
            if state["atBottom"] and state["height"] == previous_height:
                stable_bottom_checks += 1
            else:
                stable_bottom_checks = 0
            previous_height = state["height"]
            if stable_bottom_checks >= 3:
                break
        page.wait_for_timeout(3000)

    def _reviews(self, page) -> List[Dict[str, Any]]:
        reviews = []
        for element in page.locator("[data-hook='review']").all():
            body = text_or_none(element.locator(
                "[data-hook='review-body'], [data-hook='reviewText'], [data-hook='reviewRichContentContainer']"
            ))
            if not body:
                continue
            verified = text_or_none(element.locator("[data-hook='avp-badge']"))
            reviews.append({
                "external_id": element.get_attribute("id"),
                "reviewer_name": text_or_none(element.locator(".a-profile-name")),
                "review_date": self._review_date(text_or_none(element.locator("[data-hook='review-date']"))),
                "rating": parse_price(text_or_none(element.locator(
                    "[data-hook='review-star-rating'], [data-hook='cmps-review-star-rating']"
                ))),
                "title": text_or_none(element.locator(
                    "[data-hook='review-title'], [data-hook='reviewTitle']"
                )),
                "text": body,
                "verified_purchase": bool(verified),
            })
        return sorted(reviews, key=lambda item: (item.get("external_id") or "", item.get("text") or ""))

    def _review_date(self, value: Optional[str]):
        if not value:
            return None
        match = re.search(r"on ([A-Z][a-z]+ \d{1,2}, \d{4})$", value)
        if not match:
            return None
        return datetime.strptime(match.group(1), "%B %d, %Y").date()

    def _relations(self, page, current_asin: str) -> List[Dict[str, Any]]:
        relations = []
        seen = set()
        for link in page.locator("a[href*='/dp/'], a[href*='/gp/product/']").all():
            href = link.get_attribute("href") or ""
            asin = self._asin(href)
            name = text_or_none(link)
            if not asin or asin == current_asin or not name or asin in seen:
                continue
            seen.add(asin)
            relations.append({
                "type": "related",
                "external_id": asin,
                "name": name[:500],
                "url": f"https://www.amazon.com/dp/{asin}",
                "sku": asin,
                "price": parse_price(name),
                "currency": "USD",
            })
        return sorted(relations, key=lambda item: item["external_id"])[:30]

    def _variants(self, page, current_asin: str) -> List[Dict[str, Any]]:
        variants = []
        seen = set()
        for element in page.locator("[data-asin]:not([data-asin=''])").all():
            asin = (element.get_attribute("data-asin") or "").upper()
            if not re.fullmatch(r"[A-Z0-9]{10}", asin) or asin in seen:
                continue
            label = (element.get_attribute("title") or text_or_none(element) or asin).strip()
            if asin == current_asin and label == asin:
                continue
            seen.add(asin)
            variants.append({
                "name": "Amazon option",
                "value": label[:500],
                "sku": asin,
                "url": f"https://www.amazon.com/dp/{asin}",
                "price": parse_price(label),
                "availability": None,
            })
        return sorted(variants, key=lambda item: (item["sku"], item["value"]))[:50]


ADAPTERS = {
    "webscraper_demo": WebScraperDemoAdapter,
    "amazon": AmazonAdapter,
}


def create_adapter(browser: BrowserManager, site: Dict[str, Any]) -> SiteAdapter:
    adapter_name = site["adapter"]
    adapter_class = ADAPTERS.get(adapter_name)
    if not adapter_class:
        raise ValueError(f"Unsupported adapter: {adapter_name}")
    normalized_site = dict(site)
    normalized_site["settings"] = site.get("settings") or site.get("site_settings") or {}
    return adapter_class(browser, normalized_site)
