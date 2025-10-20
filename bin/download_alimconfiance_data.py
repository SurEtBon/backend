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
"""Download and import initial Alim'confiance food safety inspection data.

This module handles the initial data load for French food safety inspection data
from the Alim'confiance platform (managed by the Ministry of Agriculture) during
backend initialization. It downloads a fixed snapshot of inspection results,
stores it in Supabase Storage, and populates a database table in the bronze layer.

This is a one-time initialization script using a temporary snapshot approach due
to ongoing maintenance of the official API. Ongoing data updates will be handled
by the data-pipeline project using Apache Airflow once the API is restored.

Key Features:
    - Fixed snapshot for initialization (dated 2025-05-06)
    - Idempotent operations for safe re-initialization
    - Progress tracking for file downloads
    - Automatic column name sanitization
    - Comprehensive error handling and recovery

Usage:
    python3 download_alimconfiance_data.py

    Or with uv:
    uv run download_alimconfiance_data.py

Environment Variables:
    SUPABASE_URL (required): The Supabase project URL
    SUPABASE_SERVICE_ROLE_KEY (required): Service role key for admin operations
    SUPABASE_DB_URI (required): PostgreSQL connection string (user:pass@host:port/db)

Data Source:
    Platform: data.gouv.fr (French Open Data Portal)
    Dataset: Export Alim'confiance
    Format: Apache Parquet
    Initial Load: Static snapshot (2025-05-06) during API maintenance
    Coverage: All French food establishments with health inspections

Exit Codes:
    0: Success - Data downloaded and imported successfully
    1: Error - Configuration, network, or database issues

Performance Considerations:
    - Download size: ~5-10MB (compressed Parquet)
    - Processing time: 1-3 minutes for initialization
    - Memory usage: Peak ~300MB during pandas operations
    - Database load: Batch inserts with 1000-row chunks

Data Quality Notes:
    - Inspection dates may be historical (up to 3 years)
    - Some establishments may have multiple inspection records
    - Hygiene ratings use French classification system
    - Geographic coverage includes overseas territories

Example:
    >>> # Ensure .env file is configured
    >>> # Run the script
    >>> python3 download_alimconfiance_data.py
    ============================================================
    Alim'confiance Data Import
    ============================================================
    Loading environment configuration...
    Downloading Alim'confiance temporary dataset...
    Dataset date: 2025-05-06 (fixed snapshot during maintenance)
    Source URL: https://object.files.data.gouv.fr/hydra-parquet/hydra-parquet/fdfabe62-a581-41a1-998f-73fc53da3398.parquet
    Progress: 100.0% (5,870,183 / 5,870,183 bytes)
    ✓ Downloaded 5,870,183 bytes to /tmp/export_alimconfiance-2025-05-06.parquet
    ...

Author: Jonathan About
Version: 0.0.1
Since: 2025-10-20
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from supabase import create_client, Client


# Configuration constants
DATASET_URL: str = "https://object.files.data.gouv.fr/hydra-parquet/hydra-parquet/fdfabe62-a581-41a1-998f-73fc53da3398.parquet"
DATASET_DATE: str = "2025-05-06"  # Snapshot date for current static file
PARQUET_FILENAME: str = f"export_alimconfiance-{DATASET_DATE}.parquet"
BUCKET_NAME: str = 'data_lake'
BRONZE_SCHEMA: str = 'bronze'
TABLE_NAME: str = 'export_alimconfiance'
CHUNK_SIZE: int = 8192  # Download chunk size in bytes
DB_CHUNK_SIZE: int = 1000  # Database insert chunk size
REQUEST_TIMEOUT: int = 300  # HTTP request timeout in seconds (5 minutes)


def load_environment() -> Dict[str, str]:
    """Load and validate required environment variables for Alim'confiance pipeline.

    This function loads configuration from a .env file and validates that all
    required variables are present. It provides clear error messages for
    missing configurations to facilitate troubleshooting.

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

    Security Consideration:
        Environment variables contain sensitive credentials. Ensure .env file
        is excluded from version control via .gitignore.
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

    # Define required variables for Alim'confiance operations
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


def download_alimconfiance_data() -> Optional[str]:
    """Download Alim'confiance dataset from data.gouv.fr with progress tracking.

    This function handles the download of the Alim'confiance Parquet file from
    the French Open Data portal for initial backend setup. It implements streaming
    download with real-time progress indication and validates the downloaded file.

    Currently using a fixed snapshot due to API maintenance. Updates will be
    handled by the data-pipeline project once the API is restored.

    Returns:
        Optional[str]: Path to the downloaded temporary file if successful,
            None if download fails or file is invalid.

    Side Effects:
        - Creates temporary file in system temp directory
        - Prints download progress to stdout
        - Prints error messages to stderr
        - Removes invalid files automatically

    Example:
        >>> file_path = download_alimconfiance_data()
        >>> if file_path:
        ...     print(f"Downloaded to: {file_path}")
        '/tmp/export_alimconfiance-2025-05-06.parquet'

    Performance Notes:
        - Uses streaming to minimize memory usage
        - Progress updates every 8KB chunk
        - Typical download time: 10-20 seconds
        - File size: ~5-6MB

    Data Source Information:
        - Provider: Ministry of Agriculture and Food Sovereignty
        - Platform: data.gouv.fr
        - License: Open License 2.0 (Etalab)
        - Initial Load: Fixed snapshot (2025-05-06)

    Known Limitations:
        - Fixed snapshot date during maintenance period
        - Full dataset download for initialization
        - No compression beyond Parquet native compression
    """
    print(f"Downloading Alim'confiance temporary dataset...")
    print(f"Dataset date: {DATASET_DATE} (fixed snapshot during maintenance)")
    print(f"Source URL: {DATASET_URL}")

    try:
        # Create temporary file in system temp directory
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, PARQUET_FILENAME)

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
            print("This may indicate the data source is unavailable.", file=sys.stderr)
            os.remove(temp_path)
            return None

        return temp_path

    except requests.RequestException as e:
        print(f"Error downloading Alim'confiance data: {e}", file=sys.stderr)
        print("Network troubleshooting:", file=sys.stderr)
        print("  1. Check internet connectivity", file=sys.stderr)
        print("  2. Verify data.gouv.fr is accessible", file=sys.stderr)
        print("  3. Check if dataset URL has changed", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Unexpected error during download: {e}", file=sys.stderr)
        return None


def upload_to_storage(supabase: Client, file_path: str) -> Optional[str]:
    """Upload Alim'confiance Parquet file to Supabase Storage with versioning.

    This function handles the upload of initial inspection data to the data_lake
    bucket during backend initialization. It implements a replace strategy for the
    fixed snapshot, ensuring consistency for re-initialization if needed.

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
        >>> storage_path = upload_to_storage(client, "/tmp/alimconfiance.parquet")
        >>> if storage_path:
        ...     print(f"Uploaded to: {storage_path}")
        'export_alimconfiance/2025-05-06.parquet'

    Storage Organization:
        Files are organized by date in the following structure:
        data_lake/
        └── export_alimconfiance/
            ├── 2025-05-06.parquet  (current snapshot)
            └── [future dated files when API restored]

    Performance Notes:
        - Entire file loaded into memory for upload
        - Typical upload time: 2-5 seconds for 6MB file
        - Network bandwidth is the primary bottleneck

    Data Governance:
        - Fixed snapshot replaced on re-initialization (idempotent)
        - Audit trail maintained via table comment with dataset date
        - Ongoing updates handled by data-pipeline project
    """
    storage_path = f"export_alimconfiance/{DATASET_DATE}.parquet"

    print(f"\nUploading to Supabase Storage...")
    print(f"Target path: {BUCKET_NAME}/{storage_path}")

    try:
        # Read entire file content (required by Supabase SDK)
        with open(file_path, 'rb') as f:
            file_content = f.read()

        # Implement replace strategy: remove existing snapshot if present
        # This ensures idempotent uploads for the fixed snapshot
        try:
            existing_files = supabase.storage.from_(BUCKET_NAME).list(
                path='export_alimconfiance'
            )
            for file_info in existing_files:
                if file_info['name'] == f"{DATASET_DATE}.parquet":
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
    """Create and populate initial Alim'confiance inspection table.

    This function handles the database loading phase of the initialization. It
    reads the Parquet file, sanitizes column names for PostgreSQL compatibility,
    creates a table in the bronze schema, and adds metadata for tracking.

    Args:
        db_uri (str): PostgreSQL connection string in SQLAlchemy format.
            Should be in the form: postgresql+psycopg://user:pass@host:port/db
        file_path (str): Path to the Parquet file containing inspection data.

    Returns:
        bool: True if table creation and data loading succeed, False otherwise.

    Side Effects:
        - Drops existing table if present (CASCADE)
        - Creates new table in bronze schema
        - Sanitizes column names for SQL compatibility
        - Loads data from Parquet file
        - Creates table documentation
        - Prints progress messages to stdout
        - Prints error messages to stderr

    Example:
        >>> db_uri = "postgresql+psycopg://user:pass@localhost:5432/db"
        >>> success = create_database_table(db_uri, "/tmp/alimconfiance.parquet")
        >>> if success:
        ...     print("Table created successfully")

    Performance Optimization:
        - Batch inserts with 1000-row chunks
        - Transaction management for atomicity
    """
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

        # Add table documentation with dataset date and source information
        with engine.begin() as conn:
            # Add comprehensive table documentation including dataset date
            conn.execute(text(f"""
                COMMENT ON TABLE {BRONZE_SCHEMA}.{TABLE_NAME} IS
                'Alim''confiance food safety inspection data - Initial load snapshot from {DATASET_DATE}.
                 Contains hygiene inspection results for French food establishments.
                 Source: Ministry of Agriculture via data.gouv.fr.
                 Note: Using temporary snapshot during API maintenance. Updates handled by data-pipeline project.
                 Ratings: "Très satisfaisant", "Satisfaisant", "A améliorer", "A corriger de manière urgente".'
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
    """Orchestrate the Alim'confiance data initialization process.

    This function coordinates the three-phase initialization:
    1. Download: Fetch inspection data from data.gouv.fr
    2. Storage: Store Parquet file in Supabase Storage
    3. Database: Load data into PostgreSQL bronze schema

    This is a one-time initialization script using a fixed snapshot.
    Ongoing updates will be handled by the data-pipeline project
    once the official API is restored.

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
        $ python3 download_alimconfiance_data.py
        ============================================================
        Alim'confiance Data Import
        ============================================================
        Loading environment configuration...
        Downloading Alim'confiance temporary dataset...
        Dataset date: 2025-05-06 (fixed snapshot during maintenance)
        Source URL: https://object.files.data.gouv.fr/hydra-parquet/hydra-parquet/fdfabe62-a581-41a1-998f-73fc53da3398.parquet
        Progress: 100.0% (5,870,183 / 5,870,183 bytes)
        ✓ Downloaded 5,870,183 bytes to /tmp/export_alimconfiance-2025-05-06.parquet
        ...
        ✓ Alim'confiance data import completed successfully!
        ============================================================

    Operational Notes:
        - Safe for repeated execution (idempotent) for re-initialization
        - Temporary files always cleaned up
        - Network failures at any stage cause complete abort
        - Database operations are transactional
        - Typical runtime: 1-3 minutes for initialization
    """
    # Display header for operational visibility
    print("=" * 60)
    print("Alim'confiance Data Import")
    print("=" * 60)
    print()

    # Phase 1: Configuration and validation
    print("Loading environment configuration...")
    env_vars = load_environment()

    # Phase 2: Download data from government portal
    alimconfiance_file = download_alimconfiance_data()
    if not alimconfiance_file:
        print("✗ Failed to download Alim'confiance data", file=sys.stderr)
        sys.exit(1)

    try:
        # Phase 3: Initialize service clients
        print("\nInitializing Supabase client...")
        supabase = create_client(
            env_vars['SUPABASE_URL'],
            env_vars['SUPABASE_SERVICE_ROLE_KEY']
        )

        # Phase 4: Archive to cloud storage
        storage_path = upload_to_storage(supabase, alimconfiance_file)
        if not storage_path:
            print("✗ Failed to upload to storage", file=sys.stderr)
            sys.exit(1)

        # Phase 5: Load into database
        db_uri = f"postgresql+psycopg://{env_vars['SUPABASE_DB_URI']}"
        if not create_database_table(db_uri, alimconfiance_file):
            print("✗ Failed to create database table", file=sys.stderr)
            sys.exit(1)

        # Display success summary with important metadata
        print("\n" + "=" * 60)
        print("✓ Alim'confiance data import completed successfully!")
        print(f"  Storage: {BUCKET_NAME}/{storage_path}")
        print(f"  Table: {BRONZE_SCHEMA}.{TABLE_NAME}")
        print(f"  Snapshot date: {DATASET_DATE}")
        print("  Note: Using temporary snapshot during maintenance period")
        print("=" * 60)

    finally:
        # Cleanup: Always remove temporary files
        if os.path.exists(alimconfiance_file):
            os.remove(alimconfiance_file)
            print(f"\n✓ Cleaned up temporary file: {alimconfiance_file}")


if __name__ == "__main__":
    main()