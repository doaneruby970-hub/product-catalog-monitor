-- Product Catalog Monitor - PostgreSQL schema
-- All runtime state, checkpoints, relations, and history are stored here.

CREATE TABLE IF NOT EXISTS sites (
    id BIGSERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    adapter TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id BIGSERIAL PRIMARY KEY,
    site_id BIGINT NOT NULL REFERENCES sites(id),
    run_type TEXT NOT NULL CHECK (run_type IN ('full', 'incremental')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'completed_with_errors', 'failed', 'cancelled')),
    requested_by TEXT NOT NULL DEFAULT 'api',
    options JSONB NOT NULL DEFAULT '{}'::jsonb,
    checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb,
    products_discovered INTEGER NOT NULL DEFAULT 0,
    products_processed INTEGER NOT NULL DEFAULT 0,
    products_new INTEGER NOT NULL DEFAULT 0,
    products_updated INTEGER NOT NULL DEFAULT 0,
    products_unchanged INTEGER NOT NULL DEFAULT 0,
    products_unavailable INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    site_id BIGINT NOT NULL REFERENCES sites(id),
    external_id TEXT,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    brand TEXT,
    model_number TEXT,
    sku TEXT,
    current_price NUMERIC(14,2),
    original_price NUMERIC(14,2),
    currency TEXT NOT NULL DEFAULT 'USD',
    availability TEXT,
    category TEXT,
    subcategory TEXT,
    highlights JSONB NOT NULL DEFAULT '[]'::jsonb,
    whats_in_the_box JSONB NOT NULL DEFAULT '[]'::jsonb,
    rating NUMERIC(4,2),
    review_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    unavailable_since TIMESTAMPTZ,
    consecutive_missing_runs INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (site_id, canonical_url)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_products_external_id
    ON products(site_id, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_products_site_sku ON products(site_id, sku);
CREATE INDEX IF NOT EXISTS idx_products_last_seen ON products(site_id, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_products_availability ON products(site_id, availability);

CREATE TABLE IF NOT EXISTS product_images (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    image_url TEXT NOT NULL,
    high_resolution_url TEXT,
    image_type TEXT NOT NULL DEFAULT 'gallery',
    display_order INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, image_url)
);

CREATE TABLE IF NOT EXISTS product_specifications (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    section TEXT NOT NULL DEFAULT 'General',
    spec_name TEXT NOT NULL,
    spec_value TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, section, spec_name, spec_value)
);

CREATE TABLE IF NOT EXISTS product_reviews (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    external_review_id TEXT,
    reviewer_name TEXT,
    review_date DATE,
    rating NUMERIC(3,2),
    review_title TEXT,
    review_text TEXT,
    verified_purchase BOOLEAN,
    review_hash TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, review_hash)
);

CREATE TABLE IF NOT EXISTS product_relations (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL CHECK (relation_type IN ('compatible', 'recommended', 'related')),
    related_external_id TEXT,
    related_name TEXT NOT NULL,
    related_url TEXT,
    related_sku TEXT,
    related_price NUMERIC(14,2),
    currency TEXT DEFAULT 'USD',
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, relation_type, related_name, related_url)
);

CREATE TABLE IF NOT EXISTS product_variants (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    variant_name TEXT NOT NULL,
    variant_value TEXT NOT NULL,
    variant_sku TEXT,
    variant_url TEXT,
    price NUMERIC(14,2),
    availability TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product_id, variant_name, variant_value, variant_sku)
);

CREATE TABLE IF NOT EXISTS price_history (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    run_id BIGINT REFERENCES scrape_runs(id) ON DELETE SET NULL,
    old_price NUMERIC(14,2),
    new_price NUMERIC(14,2),
    currency TEXT NOT NULL DEFAULT 'USD',
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS availability_history (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    run_id BIGINT REFERENCES scrape_runs(id) ON DELETE SET NULL,
    old_status TEXT,
    new_status TEXT,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scrape_items (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    external_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'new', 'updated', 'unchanged', 'failed', 'blocked', 'skipped')),
    attempts INTEGER NOT NULL DEFAULT 0,
    error_type TEXT,
    error_message TEXT,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, url)
);

CREATE INDEX IF NOT EXISTS idx_scrape_items_resume
    ON scrape_items(run_id, status, id);

CREATE TABLE IF NOT EXISTS failed_urls (
    id BIGSERIAL PRIMARY KEY,
    site_id BIGINT NOT NULL REFERENCES sites(id),
    run_id BIGINT REFERENCES scrape_runs(id) ON DELETE SET NULL,
    url TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    next_retry_at TIMESTAMPTZ,
    last_retry_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (site_id, url, run_id)
);

CREATE TABLE IF NOT EXISTS exports (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
    format TEXT NOT NULL CHECK (format IN ('json', 'csv', 'xlsx')),
    file_path TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE VIEW latest_run_summary AS
SELECT
    r.id AS run_id,
    s.code AS site_code,
    r.run_type,
    r.status,
    r.products_discovered,
    r.products_processed,
    r.products_new,
    r.products_updated,
    r.products_unchanged,
    r.products_unavailable,
    r.errors,
    r.started_at,
    r.completed_at
FROM scrape_runs r
JOIN sites s ON s.id = r.site_id;

INSERT INTO sites (code, name, base_url, adapter, settings)
VALUES (
    'webscraper-demo',
    'WebScraper.io Demo Store',
    'https://webscraper.io/test-sites/e-commerce/allinone',
    'webscraper_demo',
    '{"respect_robots": true, "default_delay_seconds": 2}'::jsonb
)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    base_url = EXCLUDED.base_url,
    adapter = EXCLUDED.adapter,
    settings = EXCLUDED.settings,
    updated_at = NOW();

INSERT INTO sites (code, name, base_url, adapter, settings)
VALUES (
    'amazon-us',
    'Amazon US Car Audio Catalog',
    'https://www.amazon.com/',
    'amazon',
    '{"respect_robots": true, "default_delay_seconds": 5, "catalog_urls": ["https://www.amazon.com/s?k=car+audio+receiver"], "catalog_max_pages": 20, "discovery_delay_seconds": 3, "seed_urls": []}'::jsonb
)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    base_url = EXCLUDED.base_url,
    adapter = EXCLUDED.adapter,
    settings = EXCLUDED.settings,
    updated_at = NOW();
