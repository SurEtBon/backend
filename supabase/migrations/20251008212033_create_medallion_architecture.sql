-- =============================================================================
-- Migration: 20251008212033_create_medallion_architecture
-- =============================================================================
-- Purpose:     Establish medallion data architecture for the SûrEtBon data platform.
--              Implements a three-layer data lake architecture pattern following
--              best practices for data engineering and analytics workloads.
--              This is a one-time initialization migration executed during backend setup.
--
-- Author:      Jonathan About
-- Date:        2025-12-09
-- Version:     0.0.2
-- Since:       2025-10-20
--
-- Initialization Context:
--   This migration is executed automatically with all other migrations when
--   initialize_backend.sh runs 'supabase db reset --linked' during one-time
--   backend setup. It creates the foundational schema structure for the medallion
--   architecture. Ongoing data updates and transformations are handled by the
--   separate data-pipeline project using Apache Airflow for scheduled ETL operations.
--
-- Data Sources (Initial Load):
--   - OpenStreetMap France: Latest snapshot at initialization (~165K rows)
--   - Alim'confiance: Latest snapshot at initialization (~80K rows)
--   Note: Regular updates handled by data-pipeline project
--
-- Technical Design:
--   - Bronze Layer: Raw data ingestion with minimal transformation
--     Initial data: ~165K OSM France restaurants, ~80K Alim'confiance inspections
--   - Silver Layer: Validated, cleansed, and conformed data
--     Populated by data-pipeline project using DBT transformations
--   - Gold Layer: Business-aligned aggregations and metrics
--     Final enriched dataset with Google Maps and Tripadvisor ratings
-- =============================================================================

-- =============================================================================
-- BRONZE SCHEMA: Raw Data Layer
-- =============================================================================
-- Purpose: Store immutable raw data exactly as received from source systems.
--          Maintains data lineage and enables reprocessing capabilities.
-- Access Pattern: Write-heavy during ingestion, read during ETL processing
CREATE SCHEMA IF NOT EXISTS bronze;
COMMENT ON SCHEMA bronze IS 'Raw data layer - stores data in its original format from various sources';

-- =============================================================================
-- SILVER SCHEMA: Cleansed and Conformed Data Layer
-- =============================================================================
-- Purpose: Store validated, standardized, and enriched data ready for analytics.
--          Implements data quality rules and business logic transformations.
-- Access Pattern: Balanced read/write for continuous processing and querying
-- Quality Controls: Data validation, deduplication, standardization, enrichment
CREATE SCHEMA IF NOT EXISTS silver;
COMMENT ON SCHEMA silver IS 'Cleansed and conformed data layer - validated, standardized, and enriched data ready for analytics';

-- =============================================================================
-- GOLD SCHEMA: Business-Ready Analytical Layer
-- =============================================================================
-- Purpose: Provide optimized datasets for specific business use cases and KPIs.
--          Pre-aggregated metrics and denormalized structures for performance.
-- Access Pattern: Read-heavy with periodic batch updates
-- Optimization: Materialized views, pre-computed aggregations, dimensional models
CREATE SCHEMA IF NOT EXISTS gold;
COMMENT ON SCHEMA gold IS 'Business-ready data layer - aggregated metrics and optimized datasets for direct consumption by applications and BI tools';

-- =============================================================================
-- SECURITY PERMISSIONS
-- =============================================================================
-- Implements role-based access control (RBAC) following principle of least privilege.
-- authenticated: Read-only access for application users
-- service_role: Full access for backend services and ETL processes
GRANT USAGE ON SCHEMA bronze TO authenticated, service_role;
GRANT USAGE ON SCHEMA silver TO authenticated, service_role;
GRANT USAGE ON SCHEMA gold TO authenticated, service_role;

-- =============================================================================
-- DEFAULT PRIVILEGES FOR TABLES
-- =============================================================================
-- Ensures all future tables inherit appropriate permissions automatically.
-- This eliminates manual permission management and reduces security risks.

-- Bronze layer: Service role has full control for ETL; authenticated users read-only
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze GRANT SELECT ON TABLES TO authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze GRANT ALL ON TABLES TO service_role;

-- Silver layer: Same pattern - write for ETL, read for consumers
ALTER DEFAULT PRIVILEGES IN SCHEMA silver GRANT SELECT ON TABLES TO authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA silver GRANT ALL ON TABLES TO service_role;

-- Gold layer: Optimized for read access with controlled write permissions
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT ALL ON TABLES TO service_role;

-- =============================================================================
-- DEFAULT PRIVILEGES FOR SEQUENCES
-- =============================================================================
-- Grants access to auto-increment sequences for ID generation.
-- Required for tables with SERIAL/BIGSERIAL primary keys.
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze GRANT USAGE ON SEQUENCES TO authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA silver GRANT USAGE ON SEQUENCES TO authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT USAGE ON SEQUENCES TO authenticated, service_role;

-- =============================================================================
-- DEFAULT PRIVILEGES FOR FUNCTIONS
-- =============================================================================
-- Enables execution of stored procedures and user-defined functions.
-- Critical for data transformation logic and business rule enforcement.
ALTER DEFAULT PRIVILEGES IN SCHEMA bronze GRANT EXECUTE ON FUNCTIONS TO authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA silver GRANT EXECUTE ON FUNCTIONS TO authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT EXECUTE ON FUNCTIONS TO authenticated, service_role;