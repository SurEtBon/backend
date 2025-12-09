#!/usr/bin/env bash

# =============================================================================
# Script: initialize_backend.sh
# =============================================================================
# Purpose:     Initialize the complete SûrEtBon backend infrastructure on Supabase.
#              Orchestrates one-time setup of storage, database schemas, and initial
#              data loading. Ongoing data updates handled by data-pipeline project.
#
# Author:      Jonathan About
# Version:     0.0.2
# Date:        2025-12-03
# Shell:       Bash 4.0+ (uses associative arrays and modern bash features)
# POSIX:       Partially compliant (uses bash-specific features for robustness)
#
# Description:
#   This script automates the one-time backend infrastructure initialization,
#   ensuring all components are properly configured and populated with initial
#   data. It implements comprehensive error handling, logging, and rollback
#   capabilities for production-grade reliability. Data updates are handled
#   separately by the data-pipeline project using Apache Airflow.
#
#   Supports both hosted Supabase (via --linked) and self-hosted instances
#   (via --db-url). The script auto-detects the deployment type.
#
# Components Initialized:
#   1. Storage: Supabase Storage bucket for data lake operations
#   2. Database: All schemas, tables, and extensions via migrations:
#      - Medallion architecture schemas (bronze, silver, gold)
#      - API response tables (Google Places, Tripadvisor)
#      - PostgreSQL extensions (PostGIS, fuzzystrmatch) and GeoHash functions
#   3. OSM Data: Initial OpenStreetMap France food service dataset
#   4. Alim'confiance: Initial government food safety inspection data
#
# Environment Requirements:
#   - SUPABASE_URL: Project URL (required)
#   - SUPABASE_SERVICE_ROLE_KEY: Admin key (required)
#   - SUPABASE_DB_URI: Database connection string (required)
#
# Exit Codes:
#   0 - Success: All components initialized successfully
#   1 - Environment Error: Missing configuration or prerequisites
#   2 - Supabase Error: CLI or service issues
#   3 - Python Error: Script execution failures
#   4 - Migration Error: Database schema creation failed
#
# Usage:
#   ./initialize_backend.sh [OPTIONS]
#
# Options:
#   -h, --help     Show help message
#   -d, --debug    Enable debug logging
#
# Examples:
#   # Normal execution
#   ./initialize_backend.sh
#
#   # Debug mode for troubleshooting
#   ./initialize_backend.sh --debug
#
# Rollback Procedure:
#   To rollback a failed initialization:
#   1. Reset database:
#      - Hosted Supabase: supabase db reset --linked
#      - Self-hosted: supabase db reset --db-url "postgres://$SUPABASE_DB_URI" --debug
#   2. Delete bucket: supabase storage delete data_lake
#   3. Remove .env file and reconfigure
#   4. Re-run this script after fixing issues
#
# Execution:
#   Logs are written to: logs/backend_initialization_YYYYMMDD_HHMMSS.log
#   Expected values:
#   - Execution time: 5-10 minutes for initialization
#   - Data row counts (OSM: ~165K, Alim'confiance: ~80K)
#   - Storage usage: ~20-30MB total
#
# Security Considerations:
#   - Service role key provides admin access - handle with care
#   - Ensure .env file has restrictive permissions (600)
#   - Never commit credentials to version control
#   - Use environment variables for sensitive data
#
# Performance Notes:
#   - Downloads may be slow on limited bandwidth
#   - Database operations use batch inserts for efficiency
#   - Temporary files cleaned up automatically
#   - Consider running during off-peak hours
#
# Known Limitations:
#   - One-time initialization only (updates via data-pipeline project)
#   - Full data load (no incremental initialization)
#   - Single-threaded execution (sequential operations)
#
# Support:
#   For issues or questions, contact me
#   Documentation: See README.md for detailed information
#   Troubleshooting: Check logs/backend_initialization_*.log
# =============================================================================

# Enable strict error handling
# -e: Exit on error
# -u: Exit on undefined variable
# -o pipefail: Exit on pipe failure
set -euo pipefail

# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================
# Define immutable configuration values used throughout the script.
# Using 'readonly' ensures these values cannot be accidentally modified,
# improving script reliability and security.

# Script metadata - Used for logging and error reporting
readonly SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"          # Script filename
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"  # Script directory (absolute)
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"         # Project root directory
readonly TIMESTAMP="$(date -u +"%Y%m%d_%H%M%S")"               # UTC timestamp for unique identification
readonly LOG_DIR="${PROJECT_ROOT}/logs"                         # Log directory path
readonly LOG_FILE="${LOG_DIR}/backend_initialization_${TIMESTAMP}.log"  # Unique log file per execution

# Exit codes - Standardized for monitoring and automation
# These codes allow external systems to understand failure reasons
readonly EXIT_SUCCESS=0              # All operations completed successfully
readonly EXIT_ENV_ERROR=1           # Environment configuration issues
readonly EXIT_SUPABASE_ERROR=2      # Supabase CLI or service failures
readonly EXIT_PYTHON_ERROR=3        # Python script execution failures
readonly EXIT_MIGRATION_ERROR=4     # Database migration failures

# ANSI color codes for enhanced terminal output
# Colors improve readability and help identify message types quickly
readonly COLOR_RED='\033[0;31m'     # Error messages
readonly COLOR_GREEN='\033[0;32m'   # Success messages
readonly COLOR_YELLOW='\033[1;33m'  # Warning messages
readonly COLOR_BLUE='\033[0;34m'    # Debug/info messages
readonly COLOR_RESET='\033[0m'      # Reset to default color

# =============================================================================
# LOGGING FRAMEWORK
# =============================================================================
# Provides structured logging capabilities with both file and console output.
# Implements log levels, colored output, and ISO 8601 timestamps for
# observability and debugging.

# Ensure log directory exists with proper permissions
mkdir -p "${LOG_DIR}"

# Log level constants - Used for filtering and formatting messages
readonly LOG_LEVEL_ERROR="ERROR"    # Critical errors requiring immediate attention
readonly LOG_LEVEL_WARN="WARN"      # Warning conditions that may need investigation
readonly LOG_LEVEL_INFO="INFO"      # Informational messages about normal operations
readonly LOG_LEVEL_DEBUG="DEBUG"    # Detailed debugging information (verbose mode)

# log() - Core logging function with structured output
#
# Purpose:
#   Provides centralized logging with consistent formatting, dual output
#   (file and console), and level-based filtering.
#
# Arguments:
#   $1 - Log level (ERROR, WARN, INFO, DEBUG)
#   $@ - Message to log (remaining arguments)
#
# Outputs:
#   - Writes timestamped entry to log file
#   - Displays colored message to console based on level
#   - ERROR and WARN messages go to stderr
#   - INFO messages go to stdout
#   - DEBUG messages only shown if DEBUG=true
#
# Example:
#   log "INFO" "Starting database migration"
#   log "ERROR" "Failed to connect:" "$error_message"
#
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp
    # ISO 8601 format with milliseconds for precise timing
    timestamp="$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ")"

    # Always write to log file for audit trail
    echo "[${timestamp}] [${level}] [${SCRIPT_NAME}] ${message}" >> "${LOG_FILE}"

    # Console output with appropriate coloring and stream direction
    case "${level}" in
        "${LOG_LEVEL_ERROR}")
            # Errors to stderr in red
            echo -e "${COLOR_RED}[ERROR]${COLOR_RESET} ${message}" >&2
            ;;
        "${LOG_LEVEL_WARN}")
            # Warnings to stderr in yellow
            echo -e "${COLOR_YELLOW}[WARN]${COLOR_RESET} ${message}" >&2
            ;;
        "${LOG_LEVEL_INFO}")
            # Info to stdout in green
            echo -e "${COLOR_GREEN}[INFO]${COLOR_RESET} ${message}"
            ;;
        "${LOG_LEVEL_DEBUG}")
            # Debug only if enabled, to stdout in blue
            [[ "${DEBUG:-false}" == "true" ]] && echo -e "${COLOR_BLUE}[DEBUG]${COLOR_RESET} ${message}"
            ;;
    esac
}

# Convenience logging functions for cleaner code
# These wrappers make the code more readable and reduce repetition
log_error() { log "${LOG_LEVEL_ERROR}" "$@"; }  # Log error message
log_warn() { log "${LOG_LEVEL_WARN}" "$@"; }    # Log warning message
log_info() { log "${LOG_LEVEL_INFO}" "$@"; }    # Log info message
log_debug() { log "${LOG_LEVEL_DEBUG}" "$@"; }  # Log debug message (verbose only)

# =============================================================================
# ERROR HANDLING & CLEANUP
# =============================================================================
# Implements robust error handling with stack traces and cleanup procedures.
# Ensures resources are properly released and failures are clearly logged.

# cleanup() - Exit handler for resource cleanup and final logging
#
# Purpose:
#   Performs cleanup operations when the script exits (success or failure).
#   Ensures logs are properly finalized and status is recorded.
#
# Triggers:
#   Called automatically on script exit via EXIT trap.
#
# Actions:
#   - Logs final script status
#   - Preserves exit code for proper propagation
#   - Could be extended for resource cleanup (temp files, connections)
#
# Exit Code:
#   Preserves and returns the original exit code
#
cleanup() {
    local exit_code=$?  # Capture exit code immediately

    log_debug "Executing cleanup routine (exit code: ${exit_code})"

    # Log final status with appropriate level
    if [[ ${exit_code} -eq ${EXIT_SUCCESS} ]]; then
        log_info "Script completed successfully"
    else
        log_error "Script failed with exit code: ${exit_code}"

        # Map exit codes to human-readable descriptions
        case ${exit_code} in
            ${EXIT_ENV_ERROR})
                log_error "Failure type: Environment configuration error"
                ;;
            ${EXIT_SUPABASE_ERROR})
                log_error "Failure type: Supabase service error"
                ;;
            ${EXIT_PYTHON_ERROR})
                log_error "Failure type: Python script execution error"
                ;;
            ${EXIT_MIGRATION_ERROR})
                log_error "Failure type: Database migration error"
                ;;
            *)
                log_error "Failure type: Unknown error"
                ;;
        esac
    fi

    return ${exit_code}  # Preserve original exit code
}

# error_handler() - Detailed error reporting with stack trace
#
# Purpose:
#   Provides comprehensive error diagnostics when commands fail.
#   Captures context and call stack for effective debugging.
#
# Arguments:
#   $1 - Line number where error occurred
#   $2 - Bash line number (for function calls)
#   $3 - Last command executed
#   $4 - Exit code of failed command
#
# Triggers:
#   Called automatically on command failure via ERR trap.
#
# Outputs:
#   - Error location and command
#   - Full stack trace
#   - Contextual information for debugging
#
error_handler() {
    local line_no=$1
    local bash_lineno=$2
    local last_command=$3
    local exit_code=$4

    # Log primary error information
    log_error "Command failed with exit code ${exit_code} at line ${line_no}: ${last_command}"
    log_error "Stack trace:"

    # Generate and log stack trace for debugging
    local frame=0
    while caller ${frame}; do
        ((frame++))
    done | while read -r line_number function_name source_file; do
        log_error "  at ${function_name} (${source_file}:${line_number})"
    done

    # Additional context for common issues
    log_error "Working directory: $(pwd)"
    log_error "User: $(whoami)"
    log_error "Shell: ${SHELL}"
}

# Configure trap handlers for robust error management
# EXIT trap ensures cleanup always runs
trap cleanup EXIT
# ERR trap provides detailed error diagnostics
trap 'error_handler ${LINENO} ${BASH_LINENO} "${BASH_COMMAND}" $?' ERR

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

# Check if command exists
command_exists() {
    command -v "$1" &>/dev/null
}

# Validate required environment variables
validate_environment() {
    log_info "Validating environment configuration"

    local env_file="${PROJECT_ROOT}/.env"

    # Check if .env file exists
    if [[ ! -f "${env_file}" ]]; then
        log_error "Environment file not found: ${env_file}"
        log_error "Please copy .env.sample to .env and configure it"
        exit ${EXIT_ENV_ERROR}
    fi

    # Source environment file
    set -a
    # shellcheck disable=SC1090
    source "${env_file}"
    set +a

    # Required environment variables
    local required_vars=(
        "SUPABASE_URL"
        "SUPABASE_SERVICE_ROLE_KEY"
        "SUPABASE_DB_URI"
    )

    local missing_vars=()
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var:-}" ]]; then
            missing_vars+=("${var}")
        fi
    done

    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        log_error "Missing required environment variables: ${missing_vars[*]}"
        log_error "Please configure these in your .env file"
        exit ${EXIT_ENV_ERROR}
    fi

    log_info "Environment validation successful"
}

# Check required tools
check_requirements() {
    log_info "Checking required tools"

    local missing_tools=()

    # Check Supabase CLI
    if ! command_exists supabase; then
        missing_tools+=("supabase")
    else
        local supabase_version
        supabase_version=$(supabase --version | awk '{print $1}')
        log_info "Found Supabase CLI: ${supabase_version}"
    fi

    # Check Python and uv
    if ! command_exists python3; then
        missing_tools+=("python3")
    else
        local python_version
        python_version=$(python3 --version | awk '{print $2}')
        log_info "Found Python: ${python_version}"
    fi

    if ! command_exists uv; then
        log_warn "uv not found - Python scripts will use pip for dependencies"
    else
        local uv_version
        uv_version=$(uv --version | awk '{print $2}')
        log_info "Found uv: ${uv_version}"
    fi

    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        log_error "Missing required tools: ${missing_tools[*]}"
        log_error "Please install these tools before running this script"
        exit ${EXIT_ENV_ERROR}
    fi

    log_info "All required tools are available"
}

# Run Python script with uv if available
run_python_script() {
    local script_path="$1"
    local script_name
    script_name="$(basename "${script_path}")"

    log_info "Running ${script_name}..."

    if command_exists uv; then
        log_debug "Executing with uv run"
        if ! uv run "${script_path}"; then
            log_error "Failed to run ${script_name}"
            return 1
        fi
    else
        log_debug "Executing with python3"
        if ! python3 "${script_path}"; then
            log_error "Failed to run ${script_name}"
            return 1
        fi
    fi

    log_info "✓ ${script_name} completed successfully"
    return 0
}

# =============================================================================
# MAIN TASKS
# =============================================================================

# Task 1: Setup storage bucket
setup_storage_bucket() {
    log_info "Setting up Supabase Storage bucket"

    local script_path="${SCRIPT_DIR}/setup_bucket.py"

    if [[ ! -f "${script_path}" ]]; then
        log_error "Script not found: ${script_path}"
        exit ${EXIT_PYTHON_ERROR}
    fi

    if ! run_python_script "${script_path}"; then
        exit ${EXIT_PYTHON_ERROR}
    fi
}

# Task 2: Apply database migrations
apply_migrations() {
    log_info "Applying database migrations"

    # Check if local Supabase is running
    if ! supabase status &>/dev/null; then
        log_warn "Local Supabase is not running. Starting it now..."
        if ! supabase start; then
            log_error "Failed to start local Supabase"
            exit ${EXIT_SUPABASE_ERROR}
        fi
    fi

    # Apply migrations to the database using db reset
    # This command executes SQL files in supabase/migrations/ directory
    # Try --linked first (hosted Supabase), fallback to --db-url (self-hosted)
    log_info "Applying migrations to database (schemas, tables, and extensions)..."
    if ! supabase db reset --linked 2>/dev/null; then
        log_warn "Linked reset not available. Using --db-url for self-hosted Supabase..."
        if ! supabase db reset --db-url "postgres://${SUPABASE_DB_URI}" --debug; then
            log_error "Failed to apply migrations"
            exit ${EXIT_MIGRATION_ERROR}
        fi
    fi

    log_info "✓ All migrations applied successfully"
    log_info "  Created schemas: bronze, silver, gold"
    log_info "  Created tables: google_places, tripadvisor_location_details"
    log_info "  Enabled extensions: PostGIS, fuzzystrmatch, geohash functions"
}

# Task 3: Download and import initial OpenStreetMap data
import_osm_data() {
    log_info "Importing initial OpenStreetMap France food service data"

    local script_path="${SCRIPT_DIR}/download_osm_data.py"

    if [[ ! -f "${script_path}" ]]; then
        log_error "Script not found: ${script_path}"
        exit ${EXIT_PYTHON_ERROR}
    fi

    if ! run_python_script "${script_path}"; then
        log_error "Failed to import OSM data"
        exit ${EXIT_PYTHON_ERROR}
    fi
}

# Task 4: Download and import initial Alim'confiance data
import_alimconfiance_data() {
    log_info "Importing initial Alim'confiance data"

    local script_path="${SCRIPT_DIR}/download_alimconfiance_data.py"

    if [[ ! -f "${script_path}" ]]; then
        log_error "Script not found: ${script_path}"
        exit ${EXIT_PYTHON_ERROR}
    fi

    if ! run_python_script "${script_path}"; then
        log_error "Failed to import Alim'confiance data"
        exit ${EXIT_PYTHON_ERROR}
    fi
}


# =============================================================================
# MAIN EXECUTION
# =============================================================================

main() {
    local start_time
    start_time=$(date +%s)

    echo "=========================================="
    echo "SûrEtBon Backend Initialization"
    echo "=========================================="
    echo "Timestamp: ${TIMESTAMP}"
    echo "Log file: ${LOG_FILE}"
    echo ""

    # Step 1: Validate environment
    log_info "Step 1: Validating environment"
    validate_environment

    # Step 2: Check requirements
    log_info "Step 2: Checking requirements"
    check_requirements

    # Step 3: Setup storage bucket
    log_info "Step 3: Setting up storage bucket"
    setup_storage_bucket

    # Step 4: Apply all database migrations (schemas and tables)
    log_info "Step 4: Applying all database migrations"
    apply_migrations

    # Step 5: Import OpenStreetMap data
    log_info "Step 5: Importing OpenStreetMap data"
    import_osm_data

    # Step 6: Import Alim'confiance data
    log_info "Step 6: Importing Alim'confiance data"
    import_alimconfiance_data

    # Calculate duration
    local end_time duration
    end_time=$(date +%s)
    duration=$((end_time - start_time))

    echo ""
    echo "=========================================="
    echo "✓ Backend initialization completed!"
    echo "=========================================="
    echo "Duration: ${duration} seconds"
    echo ""
    echo "Resources created:"
    echo "  - Storage bucket: data_lake"
    echo "  - Database schemas: bronze, silver, gold"
    echo "  - Data tables: bronze.osm_france_food_service, bronze.export_alimconfiance"
    echo "  - API response tables: bronze.google_places, bronze.tripadvisor_location_details"
    echo "  - Database extensions: PostGIS, fuzzystrmatch, geohash functions"
    echo ""

    return ${EXIT_SUCCESS}
}

# =============================================================================
# SCRIPT ENTRY POINT
# =============================================================================

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            cat <<EOF
Usage: ${SCRIPT_NAME} [OPTIONS]

Initialize the SûrEtBon backend infrastructure on Supabase.

This script performs the following one-time initialization operations:
  1. Validates environment configuration
  2. Creates/configures data_lake storage bucket
  3. Applies database migrations (schemas, tables, and extensions):
     - Medallion architecture: bronze, silver, gold schemas
     - API response tables: Google Places, Tripadvisor Location Search/Details
     - PostgreSQL extensions: PostGIS, fuzzystrmatch, GeoHash functions
  4. Imports initial OpenStreetMap France food service data
  5. Imports initial Alim'confiance data

Note: Ongoing data updates are handled by the data-pipeline project.

OPTIONS:
    -h, --help      Show this help message
    -d, --debug     Enable debug logging

ENVIRONMENT:
    This script requires a properly configured .env file in the project root.
    See .env.sample for required variables.

REQUIREMENTS:
    - Supabase CLI (authenticated and linked to project)
    - Python >= 3.9.24
    - uv (optional but recommended)

EXAMPLES:
    ${SCRIPT_NAME}                  # Normal execution
    ${SCRIPT_NAME} --debug           # Run with debug output

EOF
            exit ${EXIT_SUCCESS}
            ;;
        -d|--debug)
            export DEBUG=true
            log_debug "Debug mode enabled"
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            log_error "Use --help for usage information"
            exit ${EXIT_ENV_ERROR}
            ;;
    esac
done

# Execute main function
main "$@"