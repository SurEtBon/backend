#!/usr/bin/env python
# /// script
# requires-python = ">=3.9.24"
# dependencies = [
#   "supabase>=2.22.0",
#   "python-dotenv>=1.1.1",
# ]
# ///
"""Setup and configure Supabase Storage bucket for backend initialization.

This module creates and configures a private 'data_lake' bucket in Supabase Storage
with strict file type restrictions and size limits. The bucket serves as the
storage layer for raw data files in the medallion architecture.

This is a one-time initialization script. The script implements idempotent
operations, allowing safe re-execution for re-initialization if needed. It handles
both creation of new buckets and updates to existing bucket configurations.

Usage:
    python3 setup_bucket.py

    Or with uv:
    uv run setup_bucket.py

Environment Variables:
    SUPABASE_URL (required): The Supabase project URL
    SUPABASE_SERVICE_ROLE_KEY (required): Service role key for admin operations

Exit Codes:
    0: Success - Bucket created or updated successfully
    1: Configuration error - Missing environment variables or invalid config

Example:
    >>> # Ensure .env file is configured
    >>> # Run the script
    >>> python3 setup_bucket.py
    Loading environment configuration...
    Initializing Supabase client...
    Configuring data_lake bucket...
    ✓ Bucket 'data_lake' already exists
    ✓ Updated bucket 'data_lake' configuration
    ...

Author: Jonathan About
Version: 0.0.1
Since: 2025-10-20
"""

import os
import sys
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv
from supabase import create_client, Client

# Configuration constants
BUCKET_NAME: str = 'data_lake'
ALLOWED_MIME_TYPES: list[str] = ['text/csv', 'application/vnd.apache.parquet']
FILE_SIZE_LIMIT: str = '50MB'


def load_environment() -> Dict[str, str]:
    """Load and validate required environment variables.

    This function loads environment variables from a .env file located in the
    parent directory and validates that all required variables are present.
    It implements fail-fast validation to ensure the script doesn't proceed
    with incomplete configuration.

    The function looks for the .env file at: ../backend/.env relative to
    this script's location.

    Returns:
        Dict[str, str]: Dictionary containing validated environment variables
            with keys 'SUPABASE_URL' and 'SUPABASE_SERVICE_ROLE_KEY'.

    Raises:
        SystemExit: If the .env file is not found (exit code 1) or if any
            required environment variables are missing (exit code 1).

    Example:
        >>> env_vars = load_environment()
        >>> print(env_vars['SUPABASE_URL'])
        'https://xyz.supabase.co'

    Security Note:
        The service role key loaded by this function has elevated privileges
        and should never be exposed in client-side code or logs.
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

    # Define required variables for bucket operations
    required_vars = [
        'SUPABASE_URL',
        'SUPABASE_SERVICE_ROLE_KEY'
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


def create_data_lake_bucket(supabase: Client) -> None:
    """Create or update the data_lake bucket with security configurations.

    This function implements idempotent bucket creation/configuration. If the
    bucket already exists, it updates its configuration to ensure consistency.
    If the bucket doesn't exist, it creates a new one with the specified settings.

    The bucket is configured with:
    - Private access (no public URLs)
    - Restricted MIME types (CSV and Parquet only)
    - File size limit (50MB per file)

    Args:
        supabase (Client): Authenticated Supabase client with service role
            privileges required for bucket management operations.

    Raises:
        SystemExit: If bucket creation or update fails (exit code 1).
            Common causes include network errors, invalid credentials,
            or insufficient permissions.

    Side Effects:
        - Creates a new bucket in Supabase Storage if it doesn't exist
        - Updates existing bucket configuration if it exists
        - Prints status messages to stdout
        - Prints error messages to stderr

    Example:
        >>> client = create_client(url, key)
        >>> create_data_lake_bucket(client)
        ✓ Bucket 'data_lake' already exists
        ✓ Updated bucket 'data_lake' configuration

    Performance Note:
        Bucket operations typically complete in <500ms but may take longer
        during high API load or network latency.
    """
    try:
        # Retrieve list of existing buckets
        buckets = supabase.storage.list_buckets()
        existing_bucket_names = [bucket.name for bucket in buckets]

        if BUCKET_NAME in existing_bucket_names:
            print(f"✓ Bucket '{BUCKET_NAME}' already exists")

            # Update bucket configuration to ensure consistency
            # This is idempotent and safe to run multiple times
            try:
                supabase.storage.update_bucket(
                    BUCKET_NAME,
                    options={
                        'public': False,  # Private bucket for security
                        'allowed_mime_types': ALLOWED_MIME_TYPES,
                        'file_size_limit': FILE_SIZE_LIMIT
                    }
                )
                print(f"✓ Updated bucket '{BUCKET_NAME}' configuration")
            except Exception as e:
                # Non-fatal: bucket exists but couldn't update config
                print(f"⚠ Could not update bucket configuration: {e}")
                print("  Bucket is functional but may have outdated settings")
        else:
            # Create new bucket with security configurations
            response = supabase.storage.create_bucket(
                BUCKET_NAME,
                options={
                    'public': False,  # Enforce private access
                    'allowed_mime_types': ALLOWED_MIME_TYPES,
                    'file_size_limit': FILE_SIZE_LIMIT
                }
            )
            print(f"✓ Created private bucket '{BUCKET_NAME}'")

    except Exception as e:
        print(f"✗ Error managing bucket: {e}", file=sys.stderr)
        print("Troubleshooting tips:", file=sys.stderr)
        print("  1. Check your SUPABASE_URL is correct", file=sys.stderr)
        print("  2. Verify SUPABASE_SERVICE_ROLE_KEY has admin privileges", file=sys.stderr)
        print("  3. Ensure your Supabase project is active", file=sys.stderr)
        sys.exit(1)


def verify_bucket_configuration(supabase: Client) -> None:
    """Verify and display the bucket configuration for validation.

    This function retrieves the current bucket configuration from Supabase
    and displays it for verification. It's useful for confirming that the
    bucket was created with the correct settings and for troubleshooting
    configuration issues.

    The function displays:
    - Basic bucket metadata (name, ID, creation time)
    - Security settings (public/private status)
    - File restrictions (MIME types, size limits)

    Args:
        supabase (Client): Authenticated Supabase client with at least
            read access to storage bucket metadata.

    Raises:
        SystemExit: If the bucket is not found (exit code 1) or if
            verification fails due to API errors (exit code 1).

    Side Effects:
        - Prints bucket configuration to stdout
        - Prints error messages to stderr

    Example:
        >>> client = create_client(url, key)
        >>> verify_bucket_configuration(client)

        Bucket Configuration:
          Name: data_lake
          ID: abc123...
          Public: False
          Created: 2025-10-20T12:00:00Z
          Updated: 2025-10-20T12:00:00Z
          Allowed MIME types: text/csv, application/vnd.apache.parquet
          File size limit: 50 MB

    Re-initialization Note:
        This function can be used to verify bucket configuration
        after re-initialization or infrastructure changes.
    """
    try:
        # Retrieve all buckets to find the data_lake bucket
        buckets = supabase.storage.list_buckets()

        for bucket in buckets:
            if bucket.name == BUCKET_NAME:
                # Display comprehensive bucket configuration
                print("\nBucket Configuration:")
                print(f"  Name: {bucket.name}")
                print(f"  ID: {bucket.id}")
                print(f"  Public: {bucket.public}")
                print(f"  Created: {bucket.created_at}")
                print(f"  Updated: {bucket.updated_at}")

                # Display file type restrictions
                if bucket.allowed_mime_types:
                    print(f"  Allowed MIME types: {', '.join(bucket.allowed_mime_types)}")
                else:
                    print("  Allowed MIME types: All (not restricted)")

                # Display file size limit
                if bucket.file_size_limit:
                    size_mb = bucket.file_size_limit / (1024 * 1024)
                    print(f"  File size limit: {size_mb:.0f} MB")
                else:
                    print("  File size limit: No limit")

                return

        # Bucket not found - critical error
        print(f"✗ Bucket '{BUCKET_NAME}' not found", file=sys.stderr)
        print("The bucket may have been deleted or not created properly.", file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        print(f"✗ Error verifying bucket: {e}", file=sys.stderr)
        print("Unable to retrieve bucket configuration.", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Main execution function orchestrating bucket setup workflow.

    This function coordinates the complete bucket setup process:
    1. Loads and validates environment configuration
    2. Initializes authenticated Supabase client
    3. Creates or updates the data_lake bucket
    4. Verifies the final configuration

    The function implements a fail-fast approach where any error in the
    setup process immediately terminates execution with an appropriate
    exit code.

    Exit Codes:
        0: Success - Bucket setup completed successfully
        1: Error - Configuration, network, or permission issues

    Side Effects:
        - Creates or modifies Supabase Storage bucket
        - Prints progress messages to stdout
        - Prints error messages to stderr

    Example:
        >>> # Run from command line
        $ python3 setup_bucket.py
        ============================================================
        Supabase Storage Bucket Setup
        ============================================================
        Loading environment configuration...
        Initializing Supabase client...
        Configuring data_lake bucket...
        ✓ Bucket 'data_lake' already exists
        ✓ Updated bucket 'data_lake' configuration
        ...
        ✓ Bucket setup completed successfully!
        ============================================================

    Operational Notes:
        - Safe to run multiple times (idempotent) for re-initialization
        - Requires network connectivity to Supabase
        - Typically completes in 2-5 seconds
        - One-time initialization script for backend setup
    """
    # Display header for visual clarity
    print("=" * 60)
    print("Supabase Storage Bucket Setup")
    print("=" * 60)
    print()

    # Step 1: Load and validate environment configuration
    print("Loading environment configuration...")
    env_vars = load_environment()

    # Step 2: Initialize Supabase client with admin privileges
    print("Initializing Supabase client...")
    supabase = create_client(
        env_vars['SUPABASE_URL'],
        env_vars['SUPABASE_SERVICE_ROLE_KEY']
    )

    # Step 3: Create or update the data_lake bucket
    print("\nConfiguring data_lake bucket...")
    create_data_lake_bucket(supabase)

    # Step 4: Verify the final configuration
    print("\nVerifying bucket configuration...")
    verify_bucket_configuration(supabase)

    # Display success message
    print("\n" + "=" * 60)
    print("✓ Bucket setup completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()