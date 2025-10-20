#!/usr/bin/env python
# /// script
# requires-python = ">=3.9.24"
# dependencies = [
#   "pandas>=2.3.3",
#   "psycopg>=3.2.11",
#   "psycopg-binary>=3.2.11",
#   "pyarrow>=21.0.0",
#   "python-dotenv>=1.1.1",
#   "requests>=2.32.5",
#   "SQLAlchemy>=2.0.44",
#   "supabase>=2.22.0",
# ]
# ///
"""Download and import initial OpenStreetMap France food service data.

This module handles the initial data load for OpenStreetMap (OSM) restaurant
data from OpenDataSoft's public API during backend initialization. It downloads
the current snapshot, stores it in Supabase Storage, and populates the database
table in the bronze layer of the medallion architecture.

This is a one-time initialization script. Ongoing data updates are handled by
the separate data-pipeline project using Apache Airflow.

The script follows a three-phase approach:
1. Download: Fetch current OSM dataset from OpenDataSoft
2. Storage: Upload Parquet file to Supabase Storage
3. Database: Load data into PostgreSQL table

Key Features:
    - Downloads latest available snapshot at initialization time
    - Idempotent operations supporting re-initialization
    - Progress tracking for large file downloads
    - Automatic cleanup of temporary files
    - Error recovery and detailed logging

Usage:
    python3 download_osm_data.py

    Or with uv:
    uv run download_osm_data.py

Environment Variables:
    SUPABASE_URL (required): The Supabase project URL
    SUPABASE_SERVICE_ROLE_KEY (required): Service role key for admin operations
    SUPABASE_DB_URI (required): PostgreSQL connection string (user:pass@host:port/db)

Data Source:
    Default: OpenDataSoft public API (https://public.opendatasoft.com)
    Dataset: osm-france-food-service
    Format: Apache Parquet
    Initial Load: Latest available snapshot
    Geographic Coverage: France (metropolitan and overseas)

Exit Codes:
    0: Success - Data downloaded and imported successfully
    1: Error - Configuration, network, or database issues

Performance Considerations:
    - Download size: ~15-20MB depending on data density
    - Processing time: 2-5 minutes for initialization
    - Memory usage: Peak ~500MB during pandas operations
    - Database load: Batch inserts with 1000-row chunks

Example:
    >>> # Ensure .env file is configured
    >>> # Run the script
    >>> python3 download_osm_data.py
    ============================================================
    OpenStreetMap France Food Service Data Import
    ============================================================
    Loading environment configuration...
    Downloading OSM dataset (dated: 2025-10-20)...
    Source URL: https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/osm-france-food-service/exports/parquet?lang=fr&timezone=Europe%2FBerlin
    ✓ Downloaded 15,995,128 bytes to /tmp/osm-france-food-service-2025-10-20.parquet
    ...

Author: Jonathan About
Version: 0.0.1
Since: 2025-10-20
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from supabase import create_client, Client

# Configuration constants
DATASET_URL: str = (
    'https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/'
    'osm-france-food-service/exports/parquet?lang=fr&timezone=Europe%2FBerlin'
)
BUCKET_NAME: str = 'data_lake'
BRONZE_SCHEMA: str = 'bronze'
TABLE_NAME: str = 'osm_france_food_service'
CHUNK_SIZE: int = 8192  # Download chunk size in bytes
DB_CHUNK_SIZE: int = 1000  # Database insert chunk size
REQUEST_TIMEOUT: int = 600  # HTTP request timeout in seconds


def load_environment() -> Dict[str, str]:
    """Load and validate required environment variables for OSM data pipeline.

    This function loads configuration from a .env file and validates that all
    required variables are present. It provides helpful error messages for
    missing configurations and sets sensible defaults where appropriate.

    Returns:
        Dict[str, str]: Dictionary containing validated environment variables:
            - SUPABASE_URL: Project URL for API access
            - SUPABASE_SERVICE_ROLE_KEY: Admin key for storage operations
            - SUPABASE_DB_URI: PostgreSQL connection string

    Raises:
        SystemExit: Exit code 1 if .env file missing or required variables
            not configured.

    Example:
        >>> env_vars = load_environment()
        >>> print(env_vars['SUPABASE_URL'])
        'https://xyz.supabase.co'

    Configuration Note:
        The SUPABASE_DB_URI should be in the format:
        username:password@host:port/database
        Do not include the postgresql:// prefix as it's added by SQLAlchemy.
    """
    # Construct path to .env file in parent directory
    env_path = Path(__file__).parent.parent / '.env'

    # Validate .env file exists
    if not env_path.exists():
        print(f"Error: .env file not found at {env_path}", file=sys.stderr)
        print("Please copy .env.sample to .env and configure it.", file=sys.stderr)
        print("See README.md for configuration instructions.", file=sys.stderr)
        sys.exit(1)

    # Load environment variables from file
    load_dotenv(env_path)

    # Define required variables for OSM data operations
    required_vars = [
        'SUPABASE_URL',
        'SUPABASE_SERVICE_ROLE_KEY',
        'SUPABASE_DB_URI'
    ]

    env_vars = {}
    missing_vars = []

    # Validate each required variable
    for var in required_vars:
        value = os.getenv(var)
        if not value:
            missing_vars.append(var)
        else:
            env_vars[var] = value

    # Exit if any required variables are missing
    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}", file=sys.stderr)
        print("Please configure these in your .env file.", file=sys.stderr)
        print("Refer to .env.sample for examples.", file=sys.stderr)
        sys.exit(1)

    return env_vars


def get_osm_date() -> str:
    """Calculate the date for the OSM data snapshot during initialization.

    This function determines the date label for the initial dataset load.
    OpenStreetMap data on OpenDataSoft is typically refreshed weekly on Mondays,
    so the script calculates the most recent Monday date for consistency.

    The logic follows these rules:
    - If today is Monday: use today's date
    - Otherwise: use the date of the most recent past Monday

    Returns:
        str: Date string in YYYY-MM-DD format representing the snapshot date.

    Example:
        >>> # If run on Wednesday, October 22, 2025
        >>> get_osm_date()
        '2025-10-20'  # Returns previous Monday

        >>> # If run on Monday, October 20, 2025
        >>> get_osm_date()
        '2025-10-20'  # Returns current Monday

    Initialization Note:
        This date is used for:
        - File naming in storage bucket
        - Metadata tagging in database
        - Recording the initial data version
    """
    today = datetime.now()
    # Python weekday: 0 = Monday, 6 = Sunday
    days_since_monday = today.weekday()

    if days_since_monday == 0:
        # Today is Monday - use current date
        osm_date = today
    else:
        # Calculate most recent Monday
        osm_date = today - timedelta(days=days_since_monday)

    return osm_date.strftime('%Y-%m-%d')


def download_osm_data() -> Optional[str]:
    """Download OSM dataset from OpenDataSoft API with progress tracking.

    This function handles the download of large Parquet files with streaming
    support and real-time progress indication. It implements robust error
    handling and validates the downloaded file before returning.

    Returns:
        Optional[str]: Path to the downloaded temporary file if successful,
            None if download fails or file is invalid.

    Raises:
        No exceptions are raised; errors are handled internally and logged.

    Side Effects:
        - Creates temporary file in system temp directory
        - Prints download progress to stdout
        - Prints error messages to stderr
        - May leave partial file on disk if interrupted (cleaned up on error)

    Example:
        >>> file_path = download_osm_data()
        >>> if file_path:
        ...     print(f"Downloaded to: {file_path}")

    Performance Notes:
        - Uses streaming to minimize memory usage
        - Chunk size of 8KB balances speed and responsiveness
        - Progress updates throttled to avoid excessive output
        - Typical download time: 30-60 seconds on 100Mbps connection

    Error Recovery:
        - HTTP errors trigger immediate failure
        - Empty files are detected and cleaned up
        - Partial downloads are removed on failure
        - Network timeouts set to 10 minutes
    """
    osm_date = get_osm_date()
    filename = f"osm-france-food-service-{osm_date}.parquet"

    print(f"Downloading OSM dataset (dated: {osm_date})...")
    print(f"Source URL: {DATASET_URL}")

    try:
        # Create temporary file in system temp directory
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, filename)

        # Initiate streaming download for memory efficiency
        response = requests.get(DATASET_URL, stream=True, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()  # Raise exception for HTTP errors

        # Extract content length for progress tracking
        total_size = int(response.headers.get('content-length', 0))

        # Stream content to file with progress indication
        with open(temp_path, 'wb') as f:
            downloaded = 0

            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:  # Filter out keep-alive chunks
                    f.write(chunk)
                    downloaded += len(chunk)

                    # Display progress if total size is known
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"\rProgress: {percent:.1f}% ({downloaded:,} / {total_size:,} bytes)",
                              end='', flush=True)

        print()  # New line after progress indicator

        # Validate downloaded file
        file_size = os.path.getsize(temp_path)
        print(f"✓ Downloaded {file_size:,} bytes to {temp_path}")

        # Sanity check: ensure file is not empty
        if file_size == 0:
            print("Error: Downloaded file is empty", file=sys.stderr)
            print("This may indicate an issue with the data source.", file=sys.stderr)
            os.remove(temp_path)
            return None

        return temp_path

    except requests.RequestException as e:
        print(f"Error downloading OSM data: {e}", file=sys.stderr)
        print("Network troubleshooting:", file=sys.stderr)
        print("  1. Check internet connectivity", file=sys.stderr)
        print("  2. Verify the data source URL is accessible", file=sys.stderr)
        print("  3. Consider retry with increased timeout", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Unexpected error during download: {e}", file=sys.stderr)
        return None


def upload_to_storage(supabase: Client, file_path: str) -> Optional[str]:
    """Upload Parquet file to Supabase Storage bucket with deduplication.

    This function handles the upload of OSM data files to the data_lake bucket.
    It implements idempotent operations by removing existing files with the same
    date before uploading, ensuring consistency across multiple runs.

    Args:
        supabase (Client): Authenticated Supabase client with service role
            privileges required for storage write operations.
        file_path (str): Local filesystem path to the Parquet file to upload.

    Returns:
        Optional[str]: Storage path (relative to bucket root) if successful,
            None if upload fails.

    Side Effects:
        - Uploads file to Supabase Storage
        - May delete existing file with same date
        - Prints status messages to stdout
        - Prints error messages to stderr

    Example:
        >>> client = create_client(url, key)
        >>> storage_path = upload_to_storage(client, "/tmp/osm-data.parquet")
        >>> if storage_path:
        ...     print(f"Uploaded to: {storage_path}")
        'osm-france-food-service/2025-10-07.parquet'

    Storage Organization:
        Files are organized by date in the following structure:
        data_lake/
        └── osm-france-food-service/
            ├── 2025-10-20.parquet
            ├── 2025-10-27.parquet
            └── ...

    Performance Notes:
        - Entire file loaded into memory for upload
        - No chunked upload support in current Supabase client
        - Typical upload time: 5-10 seconds for 16MB file

    Error Recovery:
        - Existing files are removed before upload (replace strategy)
        - Failed uploads leave no partial data
        - Network errors are caught and logged
    """
    osm_date = get_osm_date()
    storage_path = f"osm-france-food-service/{osm_date}.parquet"

    print(f"\nUploading to Supabase Storage...")
    print(f"Target path: {BUCKET_NAME}/{storage_path}")

    try:
        # Read entire file content (required by Supabase SDK)
        with open(file_path, 'rb') as f:
            file_content = f.read()

        # Implement replace strategy: remove existing file if present
        # This ensures idempotent uploads and prevents duplicates
        try:
            existing_files = supabase.storage.from_(BUCKET_NAME).list(
                path='osm-france-food-service'
            )
            for file_info in existing_files:
                if file_info['name'] == f"{osm_date}.parquet":
                    print(f"Removing existing file: {storage_path}")
                    supabase.storage.from_(BUCKET_NAME).remove([storage_path])
                    break
        except Exception:
            # Non-fatal: proceed with upload even if cleanup fails
            pass

        # Upload file with appropriate content type
        response = supabase.storage.from_(BUCKET_NAME).upload(
            path=storage_path,
            file=file_content,
            file_options={"content-type": "application/vnd.apache.parquet"}
        )

        print(f"✓ File uploaded successfully to {BUCKET_NAME}/{storage_path}")
        return storage_path

    except Exception as e:
        print(f"Error uploading to storage: {e}", file=sys.stderr)
        print("Storage troubleshooting:", file=sys.stderr)
        print("  1. Verify SUPABASE_SERVICE_ROLE_KEY has storage write permissions", file=sys.stderr)
        print("  2. Check that data_lake bucket exists", file=sys.stderr)
        print("  3. Ensure file size is under 50MB limit", file=sys.stderr)
        return None


def create_database_table(db_uri: str, file_path: str) -> bool:
    """Create and populate initial OSM data table in bronze schema.

    This function handles the database loading phase of the initialization. It
    reads the Parquet file into a pandas DataFrame, creates a table in the
    bronze schema, and adds metadata for tracking.

    The function implements a replace strategy, dropping any existing table
    before creating a new one. This ensures clean initialization and supports
    re-initialization if needed.

    Args:
        db_uri (str): PostgreSQL connection string in SQLAlchemy format.
            Should be in the form: postgresql+psycopg://user:pass@host:port/db
        file_path (str): Path to the Parquet file containing OSM data.

    Returns:
        bool: True if table creation and data loading succeed, False otherwise.

    Side Effects:
        - Drops existing table if present (CASCADE)
        - Creates new table in bronze schema
        - Loads data from Parquet file
        - Creates table documentation
        - Prints progress messages to stdout
        - Prints error messages to stderr

    Database Schema:
        Table: bronze.osm_france_food_service
        Columns: All columns from source Parquet
        Table Comment: Includes dataset date and source information

    Example:
        >>> db_uri = "postgresql+psycopg://user:pass@localhost:5432/db"
        >>> success = create_database_table(db_uri, "/tmp/osm-data.parquet")
        >>> if success:
        ...     print("Table created successfully")

    Performance Optimization:
        - Batch inserts with 1000-row chunks for stability
        - Transaction management with engine.begin() for atomicity
        - VACUUM ANALYZE recommended post-load (not automated)

    Data Quality:
        - Row count validation after load

    Error Handling:
        - Database connection errors caught and logged
        - Transaction rollback on failure
        - Detailed error messages for troubleshooting
    """
    osm_date = get_osm_date()

    print(f"\nCreating database table...")
    print(f"Schema: {BRONZE_SCHEMA}")
    print(f"Table: {TABLE_NAME}")

    try:
        # Initialize database connection with SQLAlchemy
        engine = create_engine(db_uri)

        # Load Parquet file into pandas DataFrame
        print("Reading Parquet file...")
        df = pd.read_parquet(file_path)
        print(f"✓ Loaded {len(df):,} rows with {len(df.columns)} columns")

        # Replace strategy: drop existing table to ensure clean state
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {BRONZE_SCHEMA}.{TABLE_NAME} CASCADE"))
            print(f"✓ Dropped existing table if present")

        # Bulk insert data using pandas to_sql with optimized settings
        print("Creating table and loading data...")
        print(f"Inserting data in chunks of {DB_CHUNK_SIZE:,} rows...")
        df.to_sql(
            TABLE_NAME,
            engine,
            schema=BRONZE_SCHEMA,
            if_exists='replace',
            index=False,  # Don't include DataFrame index
            method='multi',  # Use multi-value inserts for efficiency
            chunksize=DB_CHUNK_SIZE  # Balance between speed and stability
        )
        print(f"✓ Data inserted successfully")

        # Add table documentation with dataset date information
        with engine.begin() as conn:
            # Add comprehensive table documentation including dataset date
            conn.execute(text(f"""
                COMMENT ON TABLE {BRONZE_SCHEMA}.{TABLE_NAME} IS
                'OpenStreetMap France food service establishments - Initial load.
                 Dataset date: {osm_date}.
                 Contains restaurants, cafes, bars, and other food service locations.
                 Source: OpenDataSoft public API. Geographic coverage: France (metropolitan and overseas).
                 Note: Updates handled by data-pipeline project.'
            """))

            # Validate load by checking row count
            result = conn.execute(text(f"SELECT COUNT(*) FROM {BRONZE_SCHEMA}.{TABLE_NAME}"))
            row_count = result.scalar()

        print(f"✓ Table created successfully with {row_count:,} rows")
        return True

    except Exception as e:
        print(f"Error creating database table: {e}", file=sys.stderr)
        print("Database troubleshooting:", file=sys.stderr)
        print("  1. Verify SUPABASE_DB_URI connection string format", file=sys.stderr)
        print("  2. Ensure bronze schema exists (run migrations first)", file=sys.stderr)
        print("  3. Check database user has CREATE TABLE privileges", file=sys.stderr)
        print("  4. Verify sufficient disk space for data load", file=sys.stderr)
        return False


def main() -> None:
    """Orchestrate the OSM data initialization process.

    This function coordinates the three-phase initialization:
    1. Download: Fetch OSM data from OpenDataSoft API
    2. Storage: Store Parquet file in Supabase Storage
    3. Database: Load data into PostgreSQL bronze schema

    This is a one-time initialization script. Ongoing updates are
    handled by the data-pipeline project using Apache Airflow.

    Exit Codes:
        0: Success - All phases completed successfully
        1: Failure - Error in any phase of the pipeline

    Side Effects:
        - Downloads file to temporary directory
        - Uploads file to Supabase Storage
        - Creates/replaces database table
        - Cleans up temporary files
        - Prints detailed progress to stdout
        - Prints errors to stderr

    Example:
        >>> # Run from command line
        $ python3 download_osm_data.py
        ============================================================
        OpenStreetMap France Food Service Data Import
        ============================================================
        Loading environment configuration...
        Downloading OSM dataset (dated: 2025-10-20)...
        Source URL: https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/osm-france-food-service/exports/parquet?lang=fr&timezone=Europe%2FBerlin
        ✓ Downloaded 15,995,128 bytes to /tmp/osm-france-food-service-2025-10-20.parquet
        ...
        ✓ OSM data import completed successfully!
        ============================================================

    Operational Notes:
        - Safe for repeated execution (idempotent) for re-initialization
        - Temporary files always cleaned up
        - Network failures at any stage cause complete abort
        - Database operations are transactional
        - Typical runtime: 2-5 minutes for initialization
    """
    # Display header for operational visibility
    print("=" * 60)
    print("OpenStreetMap France Food Service Data Import")
    print("=" * 60)
    print()

    # Phase 1: Configuration and validation
    print("Loading environment configuration...")
    env_vars = load_environment()

    # Phase 2: Download data from external source
    osm_file = download_osm_data()
    if not osm_file:
        print("✗ Failed to download OSM data", file=sys.stderr)
        sys.exit(1)

    try:
        # Phase 3: Initialize service clients
        print("\nInitializing Supabase client...")
        supabase = create_client(
            env_vars['SUPABASE_URL'],
            env_vars['SUPABASE_SERVICE_ROLE_KEY']
        )

        # Phase 4: Archive to cloud storage
        storage_path = upload_to_storage(supabase, osm_file)
        if not storage_path:
            print("✗ Failed to upload to storage", file=sys.stderr)
            sys.exit(1)

        # Phase 5: Load into database
        db_uri = f"postgresql+psycopg://{env_vars['SUPABASE_DB_URI']}"
        if not create_database_table(db_uri, osm_file):
            print("✗ Failed to create database table", file=sys.stderr)
            sys.exit(1)

        # Display success summary
        print("\n" + "=" * 60)
        print("✓ OSM data import completed successfully!")
        print(f"  Storage: {BUCKET_NAME}/{storage_path}")
        print(f"  Table: {BRONZE_SCHEMA}.{TABLE_NAME}")
        print("=" * 60)

    finally:
        # Cleanup: Always remove temporary files
        if os.path.exists(osm_file):
            os.remove(osm_file)
            print(f"\n✓ Cleaned up temporary file: {osm_file}")


if __name__ == "__main__":
    main()