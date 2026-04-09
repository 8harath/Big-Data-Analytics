# End-to-End Data Engineering Pipeline

A fully containerized, production-quality local data engineering pipeline built around the French government's **RappelConso** product-recall open dataset. The pipeline ingests recall records from a public REST API, publishes them to Kafka, processes and deduplicates them with Spark Structured Streaming, persists them in PostgreSQL, and orchestrates the entire flow with Apache Airflow — all running locally via Docker Compose.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture](#architecture)
- [Data Source](#data-source)
- [Technology Stack](#technology-stack)
- [Repository Structure](#repository-structure)
- [Data Pipeline Deep Dive](#data-pipeline-deep-dive)
  - [Step 1 — Schema Creation](#step-1--schema-creation)
  - [Step 2 — API Ingestion & Kafka Publishing](#step-2--api-ingestion--kafka-publishing)
  - [Step 3 — Spark Streaming Consumer](#step-3--spark-streaming-consumer)
  - [Airflow DAG Orchestration](#airflow-dag-orchestration)
- [Data Transformations](#data-transformations)
- [Deduplication Strategy](#deduplication-strategy)
- [Incremental Processing & State Management](#incremental-processing--state-management)
- [Configuration & Environment Variables](#configuration--environment-variables)
- [Exposed Ports & Service URLs](#exposed-ports--service-urls)
- [Prerequisites](#prerequisites)
- [Setup & Running the Project](#setup--running-the-project)
- [Expected Outputs](#expected-outputs)
- [Troubleshooting](#troubleshooting)
- [Project Design Notes](#project-design-notes)
- [License](#license)

---

## Project Overview

RappelConso is a French government open-data platform that publishes product-recall notices across all consumer categories (food, cosmetics, vehicles, electronics, etc.). This project builds a streaming ETL pipeline that:

1. **Ingests** recall records incrementally from the RappelConso REST API (tracks last processed date to avoid re-fetching)
2. **Transforms** raw records — normalizes text, merges related columns, parses date ranges, removes duplicates
3. **Publishes** cleaned records as JSON messages to a Kafka topic
4. **Consumes** those messages with a PySpark Structured Streaming job
5. **Deduplicates** at the Spark layer (left anti-join against the existing PostgreSQL table)
6. **Persists** final records into a PostgreSQL table
7. **Orchestrates** all steps daily via an Apache Airflow DAG

The primary Big Data tool is **Apache Spark**. Kafka, Airflow, PostgreSQL, and Docker are the surrounding ecosystem.

---

## Architecture

```
┌──────────────────────────┐
│   RappelConso REST API   │  (French Government Open Data)
│   (External Data Source) │
└────────────┬─────────────┘
             │  HTTP GET  (incremental, paginated by date)
             ▼
┌────────────────────────────────────────────────────┐
│  Airflow Task 2: kafka_data_stream                 │
│  (PythonOperator — kafka_stream_data.py)           │
│  · Reads last_processed.json for incremental state │
│  · Paginates through API (100 records / request)   │
│  · Deduplicates by reference_fiche                 │
│  · Normalizes text & transforms columns            │
│  · Publishes JSON records to Kafka                 │
└────────────┬───────────────────────────────────────┘
             │  JSON over port 9092 (internal)
             ▼
┌────────────────────────────────────────────────────┐
│  Kafka Topic: rappel_conso                         │
│  · Decouples producer from consumer                │
│  · External access on port 9094                    │
│  · Monitored via Kafka UI on port 8000             │
└────────────┬───────────────────────────────────────┘
             │  Kafka Structured Streaming protocol
             ▼
┌────────────────────────────────────────────────────┐
│  Airflow Task 3: pyspark_consumer                  │
│  (DockerOperator — spark_streaming.py)             │
│  · Reads Kafka topic from earliest offset          │
│  · Parses JSON with 25-column StringType schema    │
│  · Left anti-join against existing PostgreSQL rows │
│  · Writes only new (non-duplicate) rows to DB      │
│  · Checkpoints saved to /tmp/spark-checkpoints/    │
└────────────┬───────────────────────────────────────┘
             │  JDBC (psycopg2 / PostgreSQL driver)
             ▼
┌────────────────────────────────────────────────────┐
│  PostgreSQL Table: rappel_conso_table              │
│  · 25 text columns, PK: reference_fiche            │
│  · Final deduplicated recall record store          │
│  · Port 5432                                       │
└────────────────────────────────────────────────────┘

Airflow Task Order:
  create_target_table  ──►  kafka_data_stream  ──►  pyspark_consumer
```

---

## Data Source

**RappelConso** — French Government Product Recall Database

- **Publisher:** French Ministry of Economy and Finance
- **License:** Open Data (Licence Ouverte / Open Licence)
- **Update frequency:** Near real-time (new recalls published daily)
- **API pagination:** 100 records per request, maximum 10,000 records per date window
- **Primary key:** `reference_fiche` — a unique identifier per recall notice

**Record categories include:** Food & beverages, cosmetics, household appliances, motor vehicles, children's toys, clothing, and more.

---

## Technology Stack

| Technology | Version | Role |
|---|---|---|
| Apache Spark (PySpark) | 3.5.0 / 3.5.7 | Core Big Data processing engine — Structured Streaming consumer |
| Apache Kafka | 3.x (KRaft mode) | Message queue — decouples producer from consumer |
| Apache Airflow | 2.7.3 | Pipeline orchestration and scheduling (daily DAG) |
| PostgreSQL | 13 | Final data storage for recall records |
| Python | 3.x | Producer logic, transformations, Airflow DAGs |
| Docker & Docker Compose | Latest | Full local infrastructure containerization |
| kafka-python | 2.0.2 | Kafka producer client |
| psycopg2-binary | 2.9.9 | PostgreSQL client driver |
| requests | 2.31.0 | HTTP client for RappelConso API |
| unidecode | 1.3.7 | Text normalization (accent removal) |
| Kafka UI (provectuslabs) | Latest | Web UI for Kafka topic monitoring |

**Spark packages loaded at runtime:**
- `org.postgresql:postgresql:42.5.4` — JDBC driver for PostgreSQL
- `org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0` — Kafka integration for Spark

---

## Repository Structure

```
data-engineering-project/
│
├── airflow_resources/               # Airflow container configuration
│   ├── Dockerfile                   # Extends apache/airflow:2.7.3, installs deps
│   ├── requirements-airflow.txt     # Airflow-specific Python dependencies
│   ├── dags/
│   │   ├── dag_kafka_spark.py       # Main Airflow DAG (3 tasks, daily schedule)
│   │   └── __init__.py
│   └── __init__.py
│
├── config/                          # Airflow config directory (mounted)
│
├── data/
│   └── last_processed.json          # Incremental state file (tracks last API date)
│
├── logs/                            # Airflow task logs (mounted)
│
├── scripts/
│   ├── create_table.py              # Creates rappel_conso_table in PostgreSQL
│   └── __init__.py
│
├── spark/
│   └── Dockerfile                   # Extends spark:3.5.7-java17-python3
│
├── src/
│   ├── constants.py                 # Centralized config (API URL, Kafka, PG settings)
│   ├── kafka_client/
│   │   ├── kafka_stream_data.py     # API ingestion & Kafka producer
│   │   ├── transformations.py       # Data normalization & column transformation
│   │   └── __init__.py
│   ├── spark_pgsql/
│   │   └── spark_streaming.py       # PySpark Kafka consumer & PostgreSQL writer
│   └── __init__.py
│
├── .env.example                     # Template for all environment variables
├── .gitignore
├── docker-compose.yml               # Kafka + Kafka UI + Spark + Docker proxy
├── docker-compose-airflow.yaml      # PostgreSQL + Airflow (webserver, scheduler, init)
├── requirements.txt                 # Full Python dependency list
├── PROJECT_GUIDE.md                 # Detailed technical guide
└── LICENSE                          # MIT License
```

---

## Data Pipeline Deep Dive

### Step 1 — Schema Creation

**File:** `scripts/create_table.py`  
**Airflow Task:** `create_target_table` (PythonOperator)

On every DAG run, the first task calls `create_table()`, which connects to PostgreSQL via psycopg2 and issues a `CREATE TABLE IF NOT EXISTS` statement for `rappel_conso_table`. The table has 25 text columns with `reference_fiche` as the primary key. The `IF NOT EXISTS` guard makes this task fully idempotent — safe to run on every pipeline execution.

---

### Step 2 — API Ingestion & Kafka Publishing

**File:** `src/kafka_client/kafka_stream_data.py`  
**Airflow Task:** `kafka_data_stream` (PythonOperator)

The producer follows this sequence:

1. **Read state** — loads `last_processed.json` to determine the date from which to start fetching (defaults to `2000-01-01` on first run)
2. **Paginate API** — fetches 100 records per request, rolling forward through dates when the 10,000-record API limit per date is reached
3. **Deduplicate** — filters out duplicate `reference_fiche` values within the current batch
4. **Transform** — calls `transform_row()` from `transformations.py` on each record
5. **Publish** — serializes each record to JSON and sends it to the `rappel_conso` Kafka topic
6. **Update state** — writes the new `last_processed` date (max date minus 1 day, to handle partial days) back to `last_processed.json`

The producer falls back to `localhost:9094` if the internal `kafka:9092` address is unreachable, supporting both in-container and local execution.

---

### Step 3 — Spark Streaming Consumer

**File:** `src/spark_pgsql/spark_streaming.py`  
**Airflow Task:** `pyspark_consumer` (DockerOperator — runs `rappel-conso/spark:latest` container)

The Spark job runs in its own Docker container (spawned by Airflow's DockerOperator via the `docker-proxy` sidecar):

1. **Create SparkSession** — loads Kafka and PostgreSQL JDBC packages
2. **Create streaming DataFrame** — subscribes to `rappel_conso` topic, reads from `earliest` offset
3. **Parse JSON** — applies a 25-field `StringType` schema using `from_json`
4. **Deduplicate via left anti-join** — reads the existing `rappel_conso_table` from PostgreSQL and joins against new Kafka records on `reference_fiche`; only rows absent from the database pass through
5. **Write to PostgreSQL** — uses `foreachBatch` with JDBC append mode
6. **Checkpoint** — stores Spark streaming checkpoints at `/tmp/spark-checkpoints/rappel_conso`

`trigger(once=True)` is used — Spark processes all currently available Kafka messages in one shot (effectively a batch job) rather than running as a continuous stream.

---

### Airflow DAG Orchestration

**File:** `airflow_resources/dags/dag_kafka_spark.py`  
**DAG ID:** `kafka_spark_dag`

| Property | Value |
|---|---|
| Schedule | Daily (`timedelta(days=1)`) |
| Start date | 1 day before deployment |
| Catchup | Disabled |
| Retries per task | 1 |
| Retry delay | 5 seconds |

**Task graph:**

```
create_target_table  ──►  kafka_data_stream  ──►  pyspark_consumer
     (PythonOperator)         (PythonOperator)        (DockerOperator)
```

The DockerOperator communicates with the Docker daemon through the `docker-proxy` service (alpine/socat on port 2375), avoiding the need to mount `/var/run/docker.sock` directly into the Airflow container.

---

## Data Transformations

**File:** `src/kafka_client/transformations.py`

Each API record goes through `transform_row()`, which applies the following in sequence:

| Transformation | Description |
|---|---|
| **Accent normalization** | `unidecode` removes accents from 12 text columns (brand, category, distribution, etc.) — e.g., `"café"` → `"cafe"` |
| **Column merging — risk** | Two raw risk-level columns are merged into a single `risques_encourus_par_le_consommateur` field, joined with newlines |
| **Column merging — health** | Two raw health-recommendation columns are merged into `conduites_a_tenir_par_le_consommateur` |
| **Column merging — info** | Two supplementary info columns are merged into `informations_complementaires` |
| **Date parsing** | `separate_commercialisation_dates()` uses regex `(\d{2}/\d{2}/\d{4})` to extract start and end commercialization dates from a free-text field, handling "depuis le" (from) and "jusqu" (until) patterns |
| **Column selection** | 8 columns (links, reference IDs, raw dates) are passed through unchanged |

The raw API response has more fields than the 25 stored — transformation reduces and restructures the schema for clean storage.

---

## Deduplication Strategy

Deduplication happens at two independent layers, using `reference_fiche` as the unique key:

**Layer 1 — Producer (in-memory, within batch)**
`deduplicate_data()` in `kafka_stream_data.py` filters out any records with a `reference_fiche` already seen in the current API fetch batch before publishing to Kafka.

**Layer 2 — Spark (cross-run, against database)**
`start_streaming()` in `spark_streaming.py` reads the full existing `rappel_conso_table` from PostgreSQL and performs a left anti-join against the incoming Kafka batch. Only records whose `reference_fiche` is absent from the database are written — this prevents any duplicate insertions across multiple DAG runs.

---

## Incremental Processing & State Management

**File:** `data/last_processed.json`

The pipeline avoids re-fetching all historical data on each run by maintaining a state file:

```json
{"last_processed": "YYYY-MM-DD"}
```

- On first run (or if the file is empty `{}`), the producer defaults to `2000-01-01` and fetches the full history
- After each successful run, the file is updated to the max publication date from the current batch (minus 1 day as a safety buffer for partial day records)
- The file is volume-mounted into the Airflow container at `/opt/airflow/data/last_processed.json`

---

## Configuration & Environment Variables

Copy `.env.example` to `.env` before starting:

```bash
cp .env.example .env
```

| Variable | Default Value | Description |
|---|---|---|
| `AIRFLOW_UID` | `50000` | Linux UID for Airflow container user |
| `_AIRFLOW_WWW_USER_USERNAME` | `airflow` | Airflow web UI username |
| `_AIRFLOW_WWW_USER_PASSWORD` | `airflow` | Airflow web UI password |
| `APP_POSTGRES_HOST` | `postgres` | PostgreSQL hostname (container name) |
| `APP_POSTGRES_PORT` | `5432` | PostgreSQL port |
| `APP_POSTGRES_DB` | `airflow` | PostgreSQL database name |
| `APP_POSTGRES_USER` | `airflow` | PostgreSQL username |
| `APP_POSTGRES_PASSWORD` | `airflow` | PostgreSQL password |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Kafka address (internal, container-to-container) |
| `KAFKA_BOOTSTRAP_SERVERS_LOCAL` | `localhost:9094` | Kafka address (external, host machine access) |
| `KAFKA_TOPIC` | `rappel_conso` | Kafka topic name |
| `LAST_PROCESSED_PATH` | `/opt/airflow/data/last_processed.json` | Path to incremental state file |
| `INITIAL_LAST_PROCESSED` | `2000-01-01` | Default start date for first run |
| `SPARK_IMAGE` | `rappel-conso/spark:latest` | Docker image used by DockerOperator |

---

## Exposed Ports & Service URLs

| Port | Service | URL |
|---|---|---|
| `8080` | Airflow Web UI | http://localhost:8080 |
| `8000` | Kafka UI | http://localhost:8000 |
| `9094` | Kafka (external listener) | `localhost:9094` |
| `5432` | PostgreSQL | `localhost:5432` |
| `2376` | Docker socket proxy | `tcp://localhost:2376` |

---

## Prerequisites

- **Docker** and **Docker Compose** installed and running
- At least **8 GB RAM** allocated to Docker (Spark + Airflow + Kafka are memory-intensive)
- **Git** for cloning the repository
- Internet access to pull Docker images and reach the RappelConso API

---

## Setup & Running the Project

### 1. Clone the repository

```bash
git clone https://github.com/8harath/data-engineering-project.git
cd data-engineering-project
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env if you want to change any default credentials or paths
```

### 3. Build the custom Spark image

The DockerOperator in Airflow requires the Spark image to be pre-built on the host:

```bash
docker build -f spark/Dockerfile -t rappel-conso/spark:latest .
```

Keep the final `.` on the same line. That `.` is the Docker build context. If you see `docker: 'docker buildx build' requires 1 argument`, Docker did not receive the context argument.

With BuildKit enabled, a successful build may end with `naming to docker.io/rappel-conso/spark:latest` and `DONE` rather than the older `Successfully tagged ...` output.

### 4. Start the infrastructure stack (Kafka, Kafka UI, Docker proxy)

```bash
docker compose -f docker-compose.yml up -d
```

### 5. Start the Airflow stack (PostgreSQL, Airflow webserver, scheduler)

```bash
docker compose -f docker-compose-airflow.yaml up -d
```

Wait for Airflow to finish initializing (the `airflow-init` container will exit with code 0 when done):

```bash
docker compose -f docker-compose-airflow.yaml logs -f airflow-init
```

### 6. Access the Airflow UI

Open http://localhost:8080 in your browser.

- **Username:** `airflow`
- **Password:** `airflow`

### 7. Trigger the DAG

In the Airflow UI, locate `kafka_spark_dag`, enable it (toggle on), and trigger a manual run — or wait for the daily schedule to fire.

### 8. Monitor the pipeline

- **Airflow UI** — http://localhost:8080 — task-by-task execution status and logs
- **Kafka UI** — http://localhost:8000 — inspect the `rappel_conso` topic, view message count, browse records

### 9. Query the results in PostgreSQL

Connect with any PostgreSQL client (psql, DBeaver, TablePlus, etc.):

```bash
psql -h localhost -p 5432 -U airflow -d airflow
```

```sql
SELECT COUNT(*) FROM rappel_conso_table;
SELECT * FROM rappel_conso_table LIMIT 10;
```

### 10. Shut down

```bash
docker compose -f docker-compose-airflow.yaml down
docker compose -f docker-compose.yml down
```

To also remove persistent volumes (this will delete all stored data):

```bash
docker compose -f docker-compose-airflow.yaml down -v
docker compose -f docker-compose.yml down -v
```

---

## Expected Outputs

After a successful DAG run:

- **`rappel_conso_table`** in PostgreSQL is populated with deduplicated recall records
- **`data/last_processed.json`** is updated to the latest processed date
- **Kafka UI** shows messages in the `rappel_conso` topic
- **Airflow task graph** shows all three tasks green (success)

The first run fetches the full historical dataset (from 2000-01-01 to today), which may take several minutes. Subsequent daily runs are much faster — only new records since the last run are fetched.

---

## Troubleshooting

**Airflow tasks fail with "connection refused" to Kafka**
- Ensure the infrastructure stack (`docker-compose.yml`) is fully started before the Airflow stack
- Kafka readiness can take ~30 seconds after the container starts

**DockerOperator fails with "Cannot connect to Docker daemon"**
- The `docker-proxy` service must be running. Verify: `docker ps | grep socat`
- The DockerOperator uses `tcp://docker-proxy:2375` — ensure both containers are on the `airflow-kafka` network

**Spark job fails with "ClassNotFoundException" for JDBC or Kafka**
- The Spark packages are downloaded at runtime by `spark-submit --packages`. Ensure the Spark container has internet access
- Package versions are pinned in `spark_streaming.py`; do not change them without testing

**`last_processed.json` causes date issues**
- Delete or reset the file contents to `{}` to force a full re-fetch: `echo '{}' > data/last_processed.json`

**PostgreSQL table already exists error**
- This should never occur because `CREATE TABLE IF NOT EXISTS` is used — but if you see it, check for psycopg2 version mismatches

**Out of memory errors**
- Increase Docker's memory limit to at least 8 GB in Docker Desktop settings
- Spark is configured with `local[*]` (uses all available cores); reduce parallelism if needed

---

## Project Design Notes

- **KRaft mode Kafka** — No ZooKeeper dependency; the `soldevelo/kafka` image runs Kafka in combined controller+broker mode with KRaft, making setup simpler and more modern
- **Trigger once** — The Spark job uses `trigger(once=True)`, making it behave as a batch job rather than a long-running stream. This integrates cleanly with Airflow's task model
- **Left anti-join deduplication** — More efficient than `INSERT ... ON CONFLICT` for large batches; the Spark join runs distributed across partitions
- **Docker-proxy pattern** — The `alpine/socat` proxy forwards TCP to the Docker socket, letting the DockerOperator inside Airflow reach the host Docker daemon without privileged socket mounts
- **Dual bootstrap server config** — `KAFKA_BOOTSTRAP_SERVERS` (internal) and `KAFKA_BOOTSTRAP_SERVERS_LOCAL` (external) allow the producer to work both inside and outside Docker with automatic fallback
- **Stateless containers** — All state is externalized: PostgreSQL for data, `last_processed.json` for pipeline state, Spark checkpoints for streaming offsets. Containers can be destroyed and recreated freely

---

## License

MIT License — Copyright (c) 2023 Hamza Gharbi

See [LICENSE](LICENSE) for full terms.
