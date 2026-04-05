# Project Guide

## 1. What This Project Is About

This repository is a local end-to-end data engineering pipeline built around a real public dataset. The project collects consumer product recall records from the French government `RappelConso` API, publishes those records into Kafka, processes them with Apache Spark Structured Streaming, stores the final rows in PostgreSQL, and coordinates the execution with Apache Airflow.

From an academic perspective, the project demonstrates how a modern Big Data ecosystem is assembled around one main processing engine. In this repository, the best choice for the central Big Data tool is **Apache Spark**. Kafka is used for ingestion and transport, Airflow is used for orchestration, PostgreSQL is used as the serving/storage layer, and Docker Compose is used to make local deployment reproducible.

The project represents a complete pipeline with:

- a real external source
- incremental ingestion state
- a message queue
- transformation logic
- orchestration
- a database sink
- containerized local execution

## 2. Dataset Used

### Dataset Name

`RappelConso` product recall records.

### Dataset Source

The dataset is fetched from the French government API endpoint configured in [src/constants.py](src/constants.py).

### What the Dataset Contains

Each record describes a recalled consumer product and includes fields such as:

- recall reference ID
- publication date
- product category and sub-category
- brand/product naming
- identifiers and packaging details
- distribution zone and distributors
- recall motive
- health risks and consumer recommendations
- links to recall documents and images

### Why This Dataset Is Good for the Project

It is a good fit because:

- it comes from a real public API
- it is structured but still messy enough to require cleaning
- it contains enough fields to justify transformation work
- it can be incrementally ingested based on publication date
- it supports a meaningful case study around product safety and consumer-health alerts

### Suggested Academic Domain Mapping

The cleanest assignment mapping is **Healthcare / Consumer Safety** because the data concerns recalls, health risks, and consumer safety recommendations.

## 3. Repository Structure

Top-level structure:

```text
data-engineering-project/
|-- airflow_resources/
|   |-- Dockerfile
|   `-- dags/
|       `-- dag_kafka_spark.py
|-- config/
|-- data/
|   `-- last_processed.json
|-- logs/
|-- scripts/
|   |-- __init__.py
|   `-- create_table.py
|-- spark/
|   `-- Dockerfile
|-- src/
|   |-- __init__.py
|   |-- constants.py
|   |-- kafka_client/
|   |   |-- __init__.py
|   |   |-- kafka_stream_data.py
|   |   `-- transformations.py
|   `-- spark_pgsql/
|       `-- spark_streaming.py
|-- .env.example
|-- docker-compose-airflow.yaml
|-- docker-compose.yml
|-- PROJECT_GUIDE.md
|-- README.md
`-- requirements.txt
```

## 4. Role of Each Major File

### [README.md](README.md)

Short entry point into the project and pointer to this detailed guide.

### [PROJECT_GUIDE.md](PROJECT_GUIDE.md)

This detailed project explanation and runbook.

### [requirements.txt](requirements.txt)

Python dependencies used for local development and the custom Airflow image.

### [docker-compose.yml](docker-compose.yml)

Infrastructure compose file for:

- Kafka broker
- Kafka UI
- Docker proxy for Airflow `DockerOperator`
- Spark image bootstrap service

### [docker-compose-airflow.yaml](docker-compose-airflow.yaml)

Airflow and PostgreSQL compose file for:

- PostgreSQL
- Airflow webserver
- Airflow scheduler
- Airflow initialization
- optional Airflow CLI profile

### [airflow_resources/Dockerfile](airflow_resources/Dockerfile)

Builds a custom Airflow image with the dependencies required by the DAG.

### [airflow_resources/dags/dag_kafka_spark.py](airflow_resources/dags/dag_kafka_spark.py)

Defines the Airflow DAG that orchestrates the full workflow:

1. create the target PostgreSQL table
2. pull and publish records to Kafka
3. launch the Spark consumer container

### [scripts/create_table.py](scripts/create_table.py)

Creates the target table `rappel_conso_table` in PostgreSQL. This now runs as part of the DAG so the database is bootstrapped automatically.

### [src/constants.py](src/constants.py)

Centralized configuration for:

- dataset URL
- Kafka topic and bootstrap servers
- PostgreSQL connection parameters
- persisted state file path
- field lists used in transformation and schema creation

### [src/kafka_client/kafka_stream_data.py](src/kafka_client/kafka_stream_data.py)

Producer-side ingestion logic:

- read last processed date
- call the remote API
- handle pagination
- deduplicate records
- transform each row
- publish JSON records to Kafka

### [src/kafka_client/transformations.py](src/kafka_client/transformations.py)

Transformation logic:

- normalize selected text fields
- merge related risk and recommendation columns
- split commercialization date ranges

### [src/spark_pgsql/spark_streaming.py](src/spark_pgsql/spark_streaming.py)

Spark Structured Streaming job:

- read messages from Kafka
- parse JSON into a schema
- compare against existing PostgreSQL rows
- insert only records not already stored

### [spark/Dockerfile](spark/Dockerfile)

Builds the Spark runtime image used by the Airflow `DockerOperator`.

### [data/last_processed.json](data/last_processed.json)

State file for incremental ingestion. It tracks the latest processed publication date so future runs only fetch newer recall records.

## 5. End-to-End Functional Flow

This is the full operational sequence.

### Step 1: Airflow starts the workflow

Airflow schedules the DAG defined in [dag_kafka_spark.py](airflow_resources/dags/dag_kafka_spark.py).

### Step 2: PostgreSQL table is created

The DAG first runs the `create_target_table` task, which executes the logic in [create_table.py](scripts/create_table.py). This creates the table `rappel_conso_table` if it does not already exist.

### Step 3: The producer queries the API

The producer task runs `stream()` from [kafka_stream_data.py](src/kafka_client/kafka_stream_data.py).

That function:

- loads the last processed date from `last_processed.json`
- calls the `RappelConso` API
- paginates through all results newer than the saved date
- deduplicates records by `reference_fiche`
- updates `last_processed.json`

### Step 4: Records are transformed

Before publishing, each API record goes through [transformations.py](src/kafka_client/transformations.py).

Important transformations:

- accents are removed from selected textual columns
- risk-related columns are merged
- health-recommendation columns are merged
- commercialization date ranges are split into start/end values

### Step 5: Records are published to Kafka

The transformed JSON payloads are written to the Kafka topic `rappel_conso`.

### Step 6: Spark consumes Kafka messages

The Airflow `DockerOperator` starts a Spark container using the image `rappel-conso/spark:latest`.

Inside that container, [spark_streaming.py](src/spark_pgsql/spark_streaming.py) performs the streaming job:

- connect to Kafka
- subscribe to topic `rappel_conso`
- parse JSON payloads into a structured DataFrame
- read the current PostgreSQL table
- anti-join against already stored `reference_fiche` values
- append only new rows into PostgreSQL

### Step 7: Data is available in PostgreSQL

The final output is stored in the table `rappel_conso_table`.

## 6. Pipeline Mapping

This is the simplest academic pipeline representation:

### Input

- French government `RappelConso` API

### Processing

- incremental fetch by publication date
- pagination
- deduplication
- normalization
- merge/split transformation logic
- Kafka-based transport
- Spark Structured Streaming parsing and persistence

### Output

- PostgreSQL table `rappel_conso_table`

## 7. Big Data Tool Positioning

If your assignment asks for one Big Data tool, position the report like this:

- **Main tool:** Apache Spark
- **Role:** distributed processing and streaming engine
- **Supporting ecosystem:** Kafka for ingestion, Airflow for orchestration, PostgreSQL for storage, Docker for deployment

Spark is the best focal point because it is the component that turns a raw event stream into structured persisted output. The repository uses Spark Structured Streaming, schema parsing, Kafka integration, and JDBC output. That makes Spark the strongest academic anchor for a Big Data tool discussion.

## 8. Technologies Used

- Python
- Apache Kafka
- Apache Spark 3.5.0
- Apache Airflow 2.7.3
- PostgreSQL 13
- Docker
- Docker Compose
- Kafka UI

## 9. Configuration Model

The repository now uses environment-driven configuration rather than hardcoded connection settings.

Main environment variables:

- `APP_POSTGRES_HOST`
- `APP_POSTGRES_PORT`
- `APP_POSTGRES_DB`
- `APP_POSTGRES_USER`
- `APP_POSTGRES_PASSWORD`
- `KAFKA_BOOTSTRAP_SERVERS`
- `KAFKA_BOOTSTRAP_SERVERS_LOCAL`
- `KAFKA_TOPIC`
- `LAST_PROCESSED_PATH`
- `INITIAL_LAST_PROCESSED`
- `SPARK_IMAGE`

Example values are provided in [.env.example](.env.example).

## 10. How to Run the Project

### Prerequisites

You need:

- Docker Desktop or Docker Engine
- Docker Compose v2
- internet access to pull container images and query the source API

Optional but useful:

- `psql` for querying PostgreSQL
- Python if you want to run helper scripts outside containers

Note on database host values:

- inside Docker containers, the PostgreSQL host is `postgres`
- from your local machine, the PostgreSQL host is `localhost` because the container publishes port `5432`

### Recommended Startup Sequence

1. Create a local `.env` file from [.env.example](.env.example).
2. Start the full stack with both compose files.
3. Open Airflow and trigger the DAG.
4. Inspect Kafka UI and PostgreSQL output.

### Command 1: Copy the environment file

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

### Command 2: Start the full stack

```powershell
docker compose -f docker-compose.yml -f docker-compose-airflow.yaml up -d --build
```

This command:

- starts Kafka
- starts Kafka UI
- builds the Spark image
- starts the Docker proxy
- starts PostgreSQL
- builds the Airflow image
- initializes Airflow
- starts Airflow webserver and scheduler

### Command 3: Check running containers

```powershell
docker compose -f docker-compose.yml -f docker-compose-airflow.yaml ps
```

### Command 4: Open the Airflow UI

Airflow runs at:

`http://localhost:8080`

Default credentials from the current compose configuration:

- username: `airflow`
- password: `airflow`

### Command 5: Open Kafka UI

Kafka UI runs at:

`http://localhost:8000`

### Command 6: Trigger the DAG manually

From the Airflow UI, trigger:

- `kafka_spark_dag`

Or from the CLI:

```powershell
docker compose -f docker-compose.yml -f docker-compose-airflow.yaml run --rm airflow-cli airflow dags trigger kafka_spark_dag
```

### Command 7: Inspect Airflow task logs

```powershell
docker compose -f docker-compose.yml -f docker-compose-airflow.yaml logs -f airflow-scheduler
```

### Command 8: Query PostgreSQL output

If `psql` is available locally:

```powershell
psql -h localhost -U airflow -d airflow -c "SELECT COUNT(*) FROM rappel_conso_table;"
```

If you prefer running inside the container:

```powershell
docker compose -f docker-compose.yml -f docker-compose-airflow.yaml exec postgres psql -U airflow -d airflow -c "SELECT COUNT(*) FROM rappel_conso_table;"
```

### Command 9: Inspect sample rows

```powershell
docker compose -f docker-compose.yml -f docker-compose-airflow.yaml exec postgres psql -U airflow -d airflow -c "SELECT reference_fiche, date_de_publication, categorie_de_produit, motif_du_rappel FROM rappel_conso_table LIMIT 10;"
```

### Command 10: Stop the stack

```powershell
docker compose -f docker-compose.yml -f docker-compose-airflow.yaml down
```

### Command 11: Reset the full local environment

Use this only if you want a clean rerun from scratch:

```powershell
docker compose -f docker-compose.yml -f docker-compose-airflow.yaml down -v
```

After that, if you also want to replay historical API records from an older date, clear or reset [data/last_processed.json](data/last_processed.json).

## 11. What Was Fixed in This Repository

The repository originally had several reproducibility problems. These are the main fixes.

### Airflow DAG path issue

Problem:

- Airflow mounted a non-existent root `dags/` directory while the real DAG lived under `airflow_resources/dags/`

Fix:

- the compose file now mounts `./airflow_resources/dags` directly into `/opt/airflow/dags`

### Missing Spark image build path

Problem:

- the DAG referenced `rappel-conso/spark:latest`, but the repository did not build that image automatically

Fix:

- the infrastructure compose file now defines a `spark-app` service that builds the same image tag locally

### Inconsistent database settings

Problem:

- the Python scripts and the compose file used different PostgreSQL users and database targets

Fix:

- connection settings are now driven from shared environment variables

### Fragile last processed path

Problem:

- `last_processed.json` depended on a relative path that was unsafe inside containers

Fix:

- the path is now configurable using `LAST_PROCESSED_PATH`

### Manual table creation dependency

Problem:

- the target table had to be created manually before the pipeline could succeed

Fix:

- table creation is now the first Airflow task in the DAG

### Missing Airflow Docker provider

Problem:

- the DAG used `DockerOperator` but the provider package was not explicitly installed

Fix:

- the Airflow image now installs the required provider from `requirements.txt`

## 12. Expected Outputs and What to Screenshot

If you need evidence for an academic report, capture screenshots of:

- Docker containers running successfully
- Airflow DAG graph view
- Airflow task success states
- Kafka UI topic list showing `rappel_conso`
- Kafka UI message preview
- PostgreSQL query output with inserted rows

Good screenshot candidates:

- `docker compose ... ps`
- Airflow DAG run success screen
- `SELECT COUNT(*) FROM rappel_conso_table;`
- `SELECT ... LIMIT 10;`

## 13. How to Explain the Project to Someone New

The shortest correct explanation is:

This project collects real product-recall data from a government API, publishes it to Kafka, processes it with Spark, stores it in PostgreSQL, and uses Airflow to orchestrate the whole workflow.

The slightly more detailed explanation is:

The system is an incremental streaming-style data pipeline. A producer fetches only the newest recall records, normalizes them, and sends them to Kafka. Spark Structured Streaming then consumes that event stream and writes clean, deduplicated records into a PostgreSQL table. Airflow automates table creation, ingestion, and Spark execution so the pipeline can be run repeatedly in a controlled way.

## 14. Advantages of This Project Design

- uses a real-world public dataset
- demonstrates a full ingestion-to-storage pipeline
- separates ingestion, orchestration, processing, and storage concerns
- uses Spark Structured Streaming instead of only batch scripts
- is containerized for local reproducibility
- uses persisted state to support incremental ingestion
- contains transformations that are non-trivial enough for academic explanation

## 15. Current Limitations

These are still reasonable points to mention honestly in a submission.

- it is a local development pipeline, not a production deployment
- Spark runs in a local container rather than a full cluster
- PostgreSQL is used as a sink, not a large-scale analytical warehouse
- Kafka retention and checkpointing strategy are minimal
- there is no formal test suite yet
- there is no observability stack beyond container logs, Airflow, and Kafka UI

## 16. Troubleshooting

### Airflow UI is not reachable

Check:

```powershell
docker compose -f docker-compose.yml -f docker-compose-airflow.yaml logs airflow-webserver
```

### DAG does not appear

Check:

- the Airflow containers were started with both compose files
- the DAG file is mounted from `airflow_resources/dags`
- Airflow finished initialization

### Spark task fails in Airflow

Check:

- the `spark-app` image was built
- the `docker-proxy` service is healthy
- the Airflow task log contains the `spark-submit` error details

### No rows appear in PostgreSQL

Check:

- Kafka topic received messages
- the source API returned records newer than `last_processed.json`
- the Spark task completed successfully
- the DB connection settings in `.env` are correct

### The pipeline appears to skip data

Inspect [data/last_processed.json](data/last_processed.json).

If you want to replay older data, reset the file contents or set a lower `INITIAL_LAST_PROCESSED` value before running again.

## 17. Suggested Improvements for Future Work

- add automated tests for transformation functions
- add schema validation for incoming API payloads
- add a dashboard or notebook for downstream analytics
- store Spark checkpoints on a mounted persistent volume
- add monitoring and alerting
- separate Airflow metadata DB from application output DB
- publish the final dataset into a data warehouse or lakehouse sink

## 18. Final One-Paragraph Summary

This repository is a Dockerized local data engineering project that ingests real recall data from the `RappelConso` public API, streams it through Kafka, transforms and persists it with Apache Spark Structured Streaming, stores the cleaned records in PostgreSQL, and coordinates the process with Airflow. For a Big Data assignment, Apache Spark should be presented as the main tool, while Kafka, Airflow, PostgreSQL, and Docker should be described as the supporting ecosystem that makes the end-to-end pipeline operational.
