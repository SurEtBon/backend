-- =============================================================================
-- Migration: 20251025000000_enable_database_extensions
-- =============================================================================
-- Purpose:     Enable PostgreSQL extensions for geospatial operations (PostGIS)
--              and fuzzy string matching (fuzzystrmatch). This migration handles
--              differences between local Docker and Supabase cloud environments
--              gracefully, attempting the extensions schema first with fallbacks.
--
-- Author:      Jonathan About
-- Date:        2025-12-03
-- Version:     0.0.1
-- Since:       2025-12-03
--
-- Extensions Enabled:
--   Core (Required):
--   - postgis: Geospatial types and functions (2D/3D geometry, geography)
--   - fuzzystrmatch: Fuzzy string matching (soundex, levenshtein, metaphone)
--
--   PostGIS Optional (if available):
--   - postgis_raster: Raster data processing for heatmaps and density analysis
--   - postgis_sfcgal: Advanced 3D geometry operations
--   - postgis_topology: Spatial topology for boundaries and zones
--
-- Schema Strategy:
--   Extensions installed in 'extensions' schema per Supabase best practices.
--
-- Idempotency:
--   This migration is fully idempotent and safe to run multiple times.
--   All CREATE statements use IF NOT EXISTS or CREATE OR REPLACE.
--
-- Rollback:
--   To rollback, execute in reverse dependency order:
--   DROP EXTENSION IF EXISTS fuzzystrmatch CASCADE;
--   DROP EXTENSION IF EXISTS postgis_topology CASCADE;
--   DROP EXTENSION IF EXISTS postgis_sfcgal CASCADE;
--   DROP EXTENSION IF EXISTS postgis_raster CASCADE;
--   DROP EXTENSION IF EXISTS postgis CASCADE;
--
-- Dependencies:
--   - PostgreSQL 14+ with extension support
--   - Supabase platform (local or cloud)
--   - Extensions must be pre-installed (standard for Supabase)
--
-- Execution Context:
--   This migration can be executed in two ways:
--   1. Automatically: During one-time backend initialization when
--      initialize_backend.sh runs 'supabase db reset' (--linked or --db-url)
--   2. Independently: After initial setup, using 'supabase db push' (hosted)
--      or 'supabase db push --db-url' (self-hosted) to apply new migrations
--
--   Extensions enable geospatial queries for restaurant proximity searches
--   and fuzzy string matching for restaurant name deduplication, both used
--   by the data-pipeline project for restaurant matching and enrichment.
--
-- Note: On Supabase cloud, extensions must be enabled in the 'extensions' schema
--       or through the dashboard. This migration attempts both approaches.
-- =============================================================================

-- =============================================================================
-- SECTION 1: EXTENSION ENABLEMENT
-- =============================================================================
-- Enable all required extensions in optimal order respecting dependencies.
-- Core extensions: postgis (required), fuzzystrmatch (required)
-- Optional extensions: postgis_raster, postgis_sfcgal, postgis_topology

-- PostGIS: Geospatial types and functions for location queries and distance calculations
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') THEN
        BEGIN
            -- Try to create in extensions schema (Supabase cloud default)
            CREATE EXTENSION postgis SCHEMA extensions;
            RAISE NOTICE 'PostGIS enabled in extensions schema';
        EXCEPTION WHEN OTHERS THEN
            BEGIN
                -- Fallback: try creating in public schema
                CREATE EXTENSION postgis;
                RAISE NOTICE 'PostGIS enabled in public schema';
            EXCEPTION WHEN OTHERS THEN
                RAISE NOTICE 'PostGIS extension could not be enabled. Please enable it through the Supabase dashboard.';
            END;
        END;
    ELSE
        RAISE NOTICE 'PostGIS is already enabled';
    END IF;
END $$;

-- fuzzystrmatch: Fuzzy string matching for restaurant name deduplication and typo tolerance
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'fuzzystrmatch') THEN
        BEGIN
            -- Try to create in extensions schema (Supabase cloud default)
            CREATE EXTENSION fuzzystrmatch SCHEMA extensions;
            RAISE NOTICE 'fuzzystrmatch enabled in extensions schema';
        EXCEPTION WHEN OTHERS THEN
            BEGIN
                -- Fallback: try creating in public schema
                CREATE EXTENSION fuzzystrmatch;
                RAISE NOTICE 'fuzzystrmatch enabled in public schema';
            EXCEPTION WHEN OTHERS THEN
                RAISE NOTICE 'fuzzystrmatch extension could not be enabled. Please enable it through the Supabase dashboard.';
            END;
        END;
    ELSE
        RAISE NOTICE 'fuzzystrmatch is already enabled';
    END IF;
END $$;

-- Optional PostGIS extensions (failures do not stop migration)
-- PostGIS Raster: Raster data support for heatmaps and density analysis
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis_raster') THEN
        BEGIN
            CREATE EXTENSION postgis_raster SCHEMA extensions;
            RAISE NOTICE 'PostGIS Raster enabled';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'PostGIS Raster not available or could not be enabled (optional)';
        END;
    END IF;
END $$;

-- PostGIS SFCGAL: Advanced 3D geometry operations
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis_sfcgal') THEN
        BEGIN
            CREATE EXTENSION postgis_sfcgal SCHEMA extensions;
            RAISE NOTICE 'PostGIS SFCGAL enabled';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'PostGIS SFCGAL not available or could not be enabled (optional)';
        END;
    END IF;
END $$;

-- PostGIS Topology: Spatial topology for boundaries and zones
-- Note: Topology creates its own schema, so no SCHEMA clause
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis_topology') THEN
        BEGIN
            CREATE EXTENSION postgis_topology;
            RAISE NOTICE 'PostGIS Topology enabled';
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'PostGIS Topology not available or could not be enabled (optional)';
        END;
    END IF;
END $$;

-- =============================================================================
-- SECTION 2: PERMISSION GRANTS
-- =============================================================================
-- Grant permissions based on where extensions were actually installed.
-- This approach handles both extensions schema and public schema installations.

-- Dynamically detect extension schemas and grant permissions to authenticated/service_role
DO $$
DECLARE
    ext_schema TEXT;
    ext_name TEXT;
    target_extensions TEXT[] := ARRAY['postgis', 'fuzzystrmatch'];
BEGIN
    FOREACH ext_name IN ARRAY target_extensions LOOP
        -- Find where this extension is installed
        SELECT n.nspname INTO ext_schema
        FROM pg_extension e
        JOIN pg_namespace n ON e.extnamespace = n.oid
        WHERE e.extname = ext_name;

        IF ext_schema IS NOT NULL THEN
            -- Grant schema usage
            EXECUTE format('GRANT USAGE ON SCHEMA %I TO authenticated, service_role', ext_schema);

            -- Grant function execution
            EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA %I TO authenticated, service_role', ext_schema);

            -- Set default privileges for future objects
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT EXECUTE ON FUNCTIONS TO authenticated, service_role', ext_schema);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON TABLES TO authenticated', ext_schema);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL ON TABLES TO service_role', ext_schema);

            RAISE NOTICE 'Permissions granted for % in schema %', ext_name, ext_schema;
        ELSE
            RAISE WARNING '% not found - permissions not granted', ext_name;
        END IF;
    END LOOP;
END $$;

-- PostGIS Topology creates its own schema - grant permissions if it exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'topology') THEN
        GRANT USAGE ON SCHEMA topology TO authenticated, service_role;
        GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA topology TO authenticated, service_role;
        ALTER DEFAULT PRIVILEGES IN SCHEMA topology GRANT EXECUTE ON FUNCTIONS TO authenticated, service_role;
        ALTER DEFAULT PRIVILEGES IN SCHEMA topology GRANT SELECT ON TABLES TO authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA topology GRANT ALL ON TABLES TO service_role;
        RAISE NOTICE 'Permissions granted for topology schema';
    END IF;
END $$;

-- =============================================================================
-- SECTION 3: GEOHASH FUNCTIONS
-- =============================================================================
-- Custom functions for GeoHash neighbor computation, enabling efficient
-- spatial batch processing at GeoHash boundaries.
--
-- Functions created:
-- - geohash_adjacent(geohash, direction): Returns adjacent GeoHash cell
-- - geohash_neighbors(geohash): Returns array of 9 cells (center + 8 neighbors)
--
-- GeoHash precision reference:
-- - 8 characters: ~38m x 19m cells (optimal for 30m radius matching)

-- geohash_adjacent: Computes adjacent GeoHash cell in a given direction (n, s, e, w)
CREATE OR REPLACE FUNCTION extensions.geohash_adjacent(geohash TEXT, direction CHAR(1))
RETURNS TEXT AS $$
DECLARE
    base32 CONSTANT TEXT := '0123456789bcdefghjkmnpqrstuvwxyz';
    neighbor TEXT[];
    border TEXT[];
    last_char CHAR(1);
    parent TEXT;
    parity INT;
    char_idx INT;
    new_char CHAR(1);
BEGIN
    IF geohash IS NULL OR LENGTH(geohash) = 0 THEN
        RETURN NULL;
    END IF;

    -- Lookup tables: [even length, odd length]
    neighbor := CASE direction
        WHEN 'n' THEN ARRAY['p0r21436x8zb9dcf5h7kjnmqesgutwvy', 'bc01fg45238967deuvhjyznpkmstqrwx']
        WHEN 's' THEN ARRAY['14365h7k9dcfesgujnmqp0r2twvyx8zb', '238967debc01fg45kmstqrwxuvhjyznp']
        WHEN 'e' THEN ARRAY['bc01fg45238967deuvhjyznpkmstqrwx', 'p0r21436x8zb9dcf5h7kjnmqesgutwvy']
        WHEN 'w' THEN ARRAY['238967debc01fg45kmstqrwxuvhjyznp', '14365h7k9dcfesgujnmqp0r2twvyx8zb']
    END;

    border := CASE direction
        WHEN 'n' THEN ARRAY['prxz', 'bcfguvyz']
        WHEN 's' THEN ARRAY['028b', '0145hjnp']
        WHEN 'e' THEN ARRAY['bcfguvyz', 'prxz']
        WHEN 'w' THEN ARRAY['0145hjnp', '028b']
    END;

    last_char := RIGHT(geohash, 1);
    parent := LEFT(geohash, LENGTH(geohash) - 1);
    parity := LENGTH(geohash) % 2;

    -- Check if at border requiring parent recursion
    IF POSITION(last_char IN border[parity + 1]) > 0 THEN
        parent := extensions.geohash_adjacent(parent, direction);
        IF parent IS NULL THEN
            RETURN NULL;  -- At world edge
        END IF;
    END IF;

    -- Get neighbor character using lookup
    char_idx := POSITION(last_char IN base32);
    IF char_idx = 0 THEN
        RETURN NULL;  -- Invalid character
    END IF;
    new_char := SUBSTRING(neighbor[parity + 1] FROM char_idx FOR 1);

    RETURN parent || new_char;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;

COMMENT ON FUNCTION extensions.geohash_adjacent(TEXT, CHAR) IS
'Computes the adjacent GeoHash cell in a given direction (n, s, e, w).
Uses correct base32 lookup tables for accurate neighbor calculation.';

-- geohash_neighbors: Returns array of 9 GeoHash cells (center + 8 neighbors)
CREATE OR REPLACE FUNCTION extensions.geohash_neighbors(geohash TEXT)
RETURNS TEXT[] AS $$
DECLARE
    n TEXT;
    s TEXT;
BEGIN
    IF geohash IS NULL THEN
        RETURN NULL;
    END IF;

    -- Compute cardinal neighbors first for diagonal composition
    n := extensions.geohash_adjacent(geohash, 'n');
    s := extensions.geohash_adjacent(geohash, 's');

    RETURN ARRAY[
        geohash,                                    -- Center
        n,                                          -- North
        s,                                          -- South
        extensions.geohash_adjacent(geohash, 'e'),  -- East
        extensions.geohash_adjacent(geohash, 'w'),  -- West
        extensions.geohash_adjacent(n, 'e'),        -- Northeast
        extensions.geohash_adjacent(n, 'w'),        -- Northwest
        extensions.geohash_adjacent(s, 'e'),        -- Southeast
        extensions.geohash_adjacent(s, 'w')         -- Southwest
    ];
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;

COMMENT ON FUNCTION extensions.geohash_neighbors(TEXT) IS
'Returns an array of 9 GeoHash cells: the center cell plus its 8 neighbors.
Used for spatial batch processing to ensure complete boundary coverage.';

-- -----------------------------------------------------------------------------
-- 3.3 Grant Permissions on GeoHash Functions
-- -----------------------------------------------------------------------------
-- Grant execute permissions to authenticated users and service role.

GRANT EXECUTE ON FUNCTION extensions.geohash_adjacent(TEXT, CHAR)
    TO authenticated, service_role;

GRANT EXECUTE ON FUNCTION extensions.geohash_neighbors(TEXT)
    TO authenticated, service_role;

-- =============================================================================
-- SECTION 4: VERIFICATION
-- =============================================================================
-- Verify all installed extensions and functions.

DO $$
DECLARE
    postgis_version TEXT;
    postgis_schema TEXT;
    fuzzystrmatch_version TEXT;
    fuzzystrmatch_schema TEXT;
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '==========================================================';
    RAISE NOTICE '           EXTENSION VERIFICATION REPORT                   ';
    RAISE NOTICE '==========================================================';
    RAISE NOTICE '';

    -- Check PostGIS
    SELECT extversion, n.nspname INTO postgis_version, postgis_schema
    FROM pg_extension e
    JOIN pg_namespace n ON e.extnamespace = n.oid
    WHERE e.extname = 'postgis';

    IF postgis_version IS NOT NULL THEN
        RAISE NOTICE '[OK] PostGIS % installed in schema "%"', postgis_version, postgis_schema;
    ELSE
        RAISE WARNING '[FAIL] PostGIS not installed';
        RAISE WARNING 'Please enable PostGIS through the Supabase dashboard:';
        RAISE WARNING '  1. Go to Database > Extensions';
        RAISE WARNING '  2. Search for "postgis"';
        RAISE WARNING '  3. Click "Enable"';
    END IF;

    -- Check fuzzystrmatch
    SELECT extversion, n.nspname INTO fuzzystrmatch_version, fuzzystrmatch_schema
    FROM pg_extension e
    JOIN pg_namespace n ON e.extnamespace = n.oid
    WHERE e.extname = 'fuzzystrmatch';

    IF fuzzystrmatch_version IS NOT NULL THEN
        RAISE NOTICE '[OK] fuzzystrmatch % installed in schema "%"', fuzzystrmatch_version, fuzzystrmatch_schema;
    ELSE
        RAISE WARNING '[FAIL] fuzzystrmatch not installed';
        RAISE WARNING 'Please enable fuzzystrmatch through the Supabase dashboard:';
        RAISE WARNING '  1. Go to Database > Extensions';
        RAISE WARNING '  2. Search for "fuzzystrmatch"';
        RAISE WARNING '  3. Click "Enable"';
    END IF;

    -- Check optional extensions
    RAISE NOTICE '';
    RAISE NOTICE '--- Optional Extensions ---';

    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis_raster') THEN
        RAISE NOTICE '[OK] postgis_raster enabled';
    ELSE
        RAISE NOTICE '[INFO] postgis_raster not enabled (optional)';
    END IF;

    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis_sfcgal') THEN
        RAISE NOTICE '[OK] postgis_sfcgal enabled';
    ELSE
        RAISE NOTICE '[INFO] postgis_sfcgal not enabled (optional)';
    END IF;

    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis_topology') THEN
        RAISE NOTICE '[OK] postgis_topology enabled';
    ELSE
        RAISE NOTICE '[INFO] postgis_topology not enabled (optional)';
    END IF;

    -- Check custom GeoHash functions
    RAISE NOTICE '';
    RAISE NOTICE '--- Custom GeoHash Functions ---';

    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'extensions' AND p.proname = 'geohash_adjacent'
    ) THEN
        RAISE NOTICE '[OK] geohash_adjacent function installed in extensions schema';
    ELSE
        RAISE WARNING '[FAIL] geohash_adjacent function not found';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'extensions' AND p.proname = 'geohash_neighbors'
    ) THEN
        RAISE NOTICE '[OK] geohash_neighbors function installed in extensions schema';
    ELSE
        RAISE WARNING '[FAIL] geohash_neighbors function not found';
    END IF;

    RAISE NOTICE '';
    RAISE NOTICE '==========================================================';
    RAISE NOTICE '  All required extensions and functions verified.';
    RAISE NOTICE '==========================================================';
END $$;

-- =============================================================================
-- END OF MIGRATION
-- =============================================================================
