# SûrEtBon Backend Infrastructure

## Executive Summary

SûrEtBon is a backend infrastructure for restaurant safety assessment, combining government health inspection data with public ratings to provide comprehensive food establishment evaluation. Built on Supabase and following medallion architecture patterns, it delivers scalable, secure, and maintainable data processing capabilities.

## Important Note: Initialization vs Data Updates

This backend project provides **one-time initialization scripts** to set up the infrastructure and load initial data. Ongoing data updates are handled by a separate project (`data-pipeline`) using Apache Airflow for scheduled ETL operations.

- **This project (`backend`)**: Initial setup, migrations, and infrastructure maintenance
- **data-pipeline project**: Scheduled data updates, ETL pipelines, and data refresh operations

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Detailed Setup](#detailed-setup)
- [Project Structure](#project-structure)
- [Data Architecture](#data-architecture)

## Architecture Overview

### System Design

SûrEtBon implements a modern data platform architecture with separated initialization and update processes:

```
┌───────────────────────────────────────────────────────────────────────────┐
│                        External Data Sources                              │
│  ┌──────────────┐  ┌───────────────┐  ┌───────────────┐  ┌─────────────┐  │
│  │ OpenStreetMap│  │ Alim'confiance│  │ Google Places │  │ Tripadvisor │  │
│  └──────┬───────┘  └───────┬───────┘  └───────┬───────┘  └──────┬──────┘  │
└─────────┼──────────────────┼──────────────────┼─────────────────┼─────────┘
          ▼                  ▼                  ▼                 ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                     Data Ingestion (Two Projects)                         │
│         ┌────────────────────────┐  ┌──────────────────────────┐          │
│         │  Backend (This Project)│  │  data-pipeline (Airflow) │          │
│         │  • Initial data load   │  │  • Scheduled updates     │          │
│         │  • One-time setup      │  │  • ETL pipelines         │          │
│         │  • Infrastructure      │  │  • Data refresh          │          │
│         └────────────┬───────────┘  └───────────┬──────────────┘          │
└──────────────────────┼──────────────────────────┼─────────────────────────┘
                       ▼                          ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                           Supabase Platform                               │
│         ┌──────────────────────────────────────────────────────┐          │
│         │                  Storage (Data Lake)                 │          │
│         │                  Parquet File Archive                │          │
│         └────────────────────────┬─────────────────────────────┘          │
│                                  ▼                                        │
│         ┌──────────────────────────────────────────────────────┐          │
│         │              PostgreSQL Database                     │          │
│         │  ┌────────────┐  ┌────────────┐  ┌────────────┐      │          │
│         │  │   Bronze   │→ │   Silver   │→ │    Gold    │      │          │
│         │  │   Schema   │  │   Schema   │  │   Schema   │      │          │
│         │  └────────────┘  └────────────┘  └────────────┘      │          │
│         └──────────────────────────────────────────────────────┘          │
└───────────────────────────────────────────────────────────────────────────┘
```

### Medallion Architecture

The system implements a three-layer medallion architecture for progressive data refinement:

- **Bronze Layer**: Raw data ingestion with minimal transformation
- **Silver Layer**: Cleansed, validated, and standardized data
- **Gold Layer**: Business-ready aggregations and metrics

## Prerequisites

### Required Tools

#### 1. Supabase CLI

The Supabase CLI manages local development and deployment:

📚 **Installation Guide**: https://supabase.com/docs/guides/cli/getting-started

#### 2. Python Environment Manager (uv)

I recommend `uv` for fast, reliable Python dependency management:

📚 **Installation Guide**: https://docs.astral.sh/uv/getting-started/installation/

#### 3. Authentication

Authenticate with your Supabase account:

```bash
supabase login
```

📚 **Authentication Guide**: https://supabase.com/docs/reference/cli/supabase-login

## Setup

### Step 1: Create Hosted Supabase Project

Create a new project on the Supabase platform:

```bash
supabase projects create SurEtBon \
  --db-password <strong-password> \
  --org-id <your-org-id> \
  --region eu-west-3
```

**Parameters:**
- `--db-password`: Strong password (16+ chars, mixed case, numbers, symbols)
- `--org-id`: Organization ID (run `supabase orgs list` to find)
- `--region`: Geographic region (`eu-west-3` for Paris)

**Important:** Save the displayed `REFERENCE ID` - you'll need it throughout setup.

### Step 2: Start Local Development Environment

Initialize the local Supabase stack:

```bash
supabase start
```

### Step 3: Link Local to Hosted Project

Connect your local environment to the cloud project:

```bash
supabase link --project-ref <reference-id>
```

### Step 4: Configure Environment Variables

1. **Copy template:**
   ```bash
   cp .env.sample .env
   chmod 600 .env  # Secure file permissions
   ```

2. **Set SUPABASE_URL:**
   ```bash
   SUPABASE_URL=https://<reference-id>.supabase.co
   ```

3. **Get API keys:**
   ```bash
   supabase projects api-keys --project-ref <reference-id>
   ```
   Copy the `service_role` key to `SUPABASE_SERVICE_ROLE_KEY`

4. **Configure database URI:**
   - Navigate to: `https://supabase.com/dashboard/project/<reference-id>?showConnect=true`
   - Select "Session pooler" connection type
   - Copy URI and remove `postgresql://` prefix
   - Set in `.env` as `SUPABASE_DB_URI`

### Step 5: Initialize Backend Infrastructure

Run the comprehensive initialization script:

```bash
./bin/initialize_backend.sh
```

This performs:
- Storage bucket creation with security policies
- Database setup via migrations (all schemas and tables)
- Initial data import (OSM + Alim'confiance) for bootstrap

Expected runtime: 5-10 minutes

**Note:** This is a one-time initialization. Subsequent data updates will be handled by the data-pipeline project.

## Project Structure

```
backend/
├── bin/                                                                       # Executable scripts
│   ├── initialize_backend.sh                                                  # Main orchestrator (Bash)
│   ├── setup_bucket.py                                                        # Storage configuration (Python)
│   ├── download_osm_data.py                                                   # OSM initial data loader (Python)
│   └── download_alimconfiance_data.py                                         # Government initial data loader (Python)
│
├── supabase/                                                                  # Supabase configuration
│   ├── config.toml                                                            # Service configuration
│   ├── migrations/                                                            # Database migrations
│   │   ├── 20251008212033_create_medallion_architecture.sql                   # Schemas: bronze, silver, gold
│   │   └── 20251008230529_create_restaurant_ratings_enrichment_tables.sql     # API response tables
│   └── functions/                                                             # Edge Functions (future)
│
├── logs/                                                                      # Execution logs (gitignored)
│   └── backend_initialization_*.log                                           # Timestamped logs
│
├── .env.sample                                                                # Environment template
├── .env                                                                       # Local configuration (gitignored)
├── .gitignore                                                                 # Git exclusions
├── pyproject.toml                                                             # Python dependencies
└── README.md                                                                  # This documentation
```

## Data Architecture

### Storage Layer

**Bucket:** `data_lake`
- **Access:** Private (service role only)
- **File Types:** Parquet, CSV
- **Size Limit:** 50MB per file
- **Organization:** Date-partitioned folders

### Database Schemas

#### Bronze Schema (Raw Data)

| Table                          | Description                     | Initial Data                           | Row Count |
|--------------------------------|---------------------------------|----------------------------------------|-----------|
| `osm_france_food_service`      | OpenStreetMap restaurants       | Latest snapshot at initialization      | ~165K     |
| `export_alimconfiance`         | Health inspections              | Static snapshot (2025-05-06)           | ~80K      |
| `google_places`                | Google Maps restaurant ratings  | Populated by data-pipeline via Airflow | Variable* |
| `tripadvisor_location_details` | Tripadvisor restaurant ratings  | Populated by data-pipeline via Airflow | Variable* |

*API-based tables: Row counts vary based on monthly query budget. Airflow prioritizes new restaurants first, then oldest updates. Historical data is preserved.

#### Silver Schema (Cleansed Data)

Populated by the data-pipeline project using DBT transformations. Contains validated and standardized datasets where OpenStreetMap restaurant data is linked with official health inspection results, enabling accurate matching for rating enrichment.

#### Gold Schema (Business Layer)

Populated by the data-pipeline project using DBT transformations. Contains the final aggregated dataset with all restaurant data enriched with Google Maps and Tripadvisor ratings, providing comprehensive metrics and KPIs for food establishment assessment.

### Data Sources

#### OpenStreetMap France

- **Provider:** OpenDataSoft
- **Coverage:** Metropolitan France + overseas
- **Initial Load:** Latest available snapshot at initialization (dated to most recent Monday)
- **Format:** Parquet
- **License:** ODbL
- **Note:** Regular updates handled by data-pipeline project. The initialization script calculates the most recent Monday date for consistency with OpenDataSoft's weekly refresh cycle.

#### Alim'confiance

- **Provider:** Ministry of Agriculture
- **Coverage:** All French food establishments
- **Initial Load:** 2025-05-06 snapshot (API under maintenance)
- **Format:** Parquet
- **License:** Open License 2.0
- **Note:** Updates will resume via data-pipeline when API restored

---

**Version:** 0.0.1
**Last Updated:** 2025-10-20
**Maintainers:** Jonathan About