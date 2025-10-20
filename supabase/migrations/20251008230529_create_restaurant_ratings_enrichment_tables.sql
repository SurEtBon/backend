-- =============================================================================
-- Migration: 20251008230529_create_restaurant_ratings_enrichment_tables
-- =============================================================================
-- Purpose:     Create storage infrastructure for third-party restaurant ratings
--              data from Google Places and Tripadvisor APIs. These tables store
--              raw API responses for subsequent processing and enrichment.
--              Tables are created during one-time backend initialization but
--              populated by the separate data-pipeline project.
--
-- Author:      Jonathan About
-- Date:        2025-10-20
-- Version:     0.0.1
-- Since:       2025-10-20
--
-- Initialization Context:
--   This migration is executed automatically with all other migrations when
--   initialize_backend.sh runs 'supabase db reset --linked' during one-time
--   backend setup. It creates empty tables for API response storage. Data population
--   is handled by the data-pipeline project using Apache Airflow with scheduled
--   ETL operations that respect API quotas and monthly query budgets.
--
-- Business Context:
--   Enriches OpenStreetMap restaurant data with real-time ratings and reviews
--   from major platforms. This enables comprehensive restaurant quality assessment
--   combining official health inspections with public sentiment analysis.
--
-- Dependencies:
--   - Migration: 20251008212033_create_medallion_architecture (bronze schema)
--   - External: bronze.osm_france_food_service table (meta_osm_id reference)
-- =============================================================================

-- =============================================================================
-- TABLE: bronze.google_places
-- =============================================================================
-- Storage for Google Places API responses containing restaurant ratings,
-- reviews, photos, and business information. Designed for high-throughput
-- ingestion with minimal processing overhead.
CREATE TABLE IF NOT EXISTS bronze.google_places (
    meta_osm_id BIGINT NOT NULL,        -- Foreign key to OSM restaurant data
    response JSONB NOT NULL,             -- Complete API response payload
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index: Optimize lookups by restaurant identifier
-- Usage: JOIN operations with osm_france_food_service, deduplication checks
-- Performance: B-tree index suitable for equality and range queries
CREATE INDEX IF NOT EXISTS idx_google_places_meta_osm_id
ON bronze.google_places (meta_osm_id);

-- Index: Support time-based data management and freshness queries
-- Usage: Data retention policies, incremental processing, monitoring
-- Performance: DESC order optimizes recent data access patterns
CREATE INDEX IF NOT EXISTS idx_google_places_created_at
ON bronze.google_places (created_at DESC);

-- Table documentation for schema introspection and data catalog
COMMENT ON TABLE bronze.google_places IS
'Google Places API responses for restaurant ratings enrichment.';

COMMENT ON COLUMN bronze.google_places.meta_osm_id IS
'OpenStreetMap unique identifier linking to bronze.osm_france_food_service. Not enforced as foreign key to allow flexible data loading.';

COMMENT ON COLUMN bronze.google_places.response IS
'Complete JSON response from Google Places API including place details, ratings, reviews, photos, and operational information. Schema varies by place type and data availability.';

COMMENT ON COLUMN bronze.google_places.created_at IS
'Timestamp when the API response was captured. Used for data freshness tracking, incremental processing, and retention policy enforcement. Immutable after insert.';

-- =============================================================================
-- TABLE: bronze.tripadvisor_location_details
-- =============================================================================
-- Storage for Tripadvisor Location Details API responses containing comprehensive
-- restaurant ratings, rankings, awards, and traveler reviews. Provides deeper
-- insights into restaurant quality from travel and dining perspectives.
CREATE TABLE IF NOT EXISTS bronze.tripadvisor_location_details (
    meta_osm_id BIGINT NOT NULL,        -- Foreign key to OSM restaurant data
    response JSONB NOT NULL,             -- Complete API response payload
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index: Optimize lookups by restaurant identifier
-- Usage: JOIN operations, data enrichment pipelines, deduplication
-- Performance: B-tree index with high cardinality efficiency
CREATE INDEX IF NOT EXISTS idx_tripadvisor_location_details_meta_osm_id
ON bronze.tripadvisor_location_details (meta_osm_id);

-- Index: Support temporal queries and data lifecycle management
-- Usage: Freshness monitoring, incremental updates, archival processes
-- Performance: DESC order for efficient recent data access
CREATE INDEX IF NOT EXISTS idx_tripadvisor_location_details_created_at
ON bronze.tripadvisor_location_details (created_at DESC);

-- Table documentation for schema introspection and data governance
COMMENT ON TABLE bronze.tripadvisor_location_details IS
'Tripadvisor Location Details API responses with ratings, rankings, awards, and reviews.';

COMMENT ON COLUMN bronze.tripadvisor_location_details.meta_osm_id IS
'OpenStreetMap unique identifier linking to bronze.osm_france_food_service. Soft reference allows partial data loading.';

COMMENT ON COLUMN bronze.tripadvisor_location_details.response IS
'Complete JSON response from Tripadvisor Location Details API. Rich metadata for quality assessment.';

COMMENT ON COLUMN bronze.tripadvisor_location_details.created_at IS
'Timestamp of API response capture. Critical for tracking data freshness, managing API quotas, and ensuring temporal consistency in analytics. Append-only pattern preserves historical data.';

-- =============================================================================
-- SECURITY CONFIGURATION
-- =============================================================================
-- Implements principle of least privilege with role-based access control.
-- service_role: Full CRUD operations for ETL and maintenance
-- authenticated: Read-only for application queries and analytics

-- Grant full permissions to service role for ETL operations
GRANT ALL ON bronze.google_places TO service_role;
GRANT ALL ON bronze.tripadvisor_location_details TO service_role;

-- Grant read-only permissions for authenticated application users
GRANT SELECT ON bronze.google_places TO authenticated;
GRANT SELECT ON bronze.tripadvisor_location_details TO authenticated;