# Complete Technical Documentation
## End-to-End Data Engineering Pipeline — RappelConso

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
27. [Data Quality Layer — Pydantic Validation and Dead-Letter Queue](#27-data-quality-layer--pydantic-validation-and-dead-letter-queue)
28. [Previously Undocumented Implementation Details](#28-previously-undocumented-implementation-details)
2. [Project Background and Motivation](#2-project-background-and-motivation)
3. [Dataset: RappelConso in Depth](#3-dataset-rappelconso-in-depth)
4. [System Architecture Overview](#4-system-architecture-overview)
5. [Technology Stack — Deep Dive](#5-technology-stack--deep-dive)
6. [Repository Structure — File-by-File Breakdown](#6-repository-structure--file-by-file-breakdown)
7. [Infrastructure Layer — Docker Compose](#7-infrastructure-layer--docker-compose)
8. [Configuration and Environment Management](#8-configuration-and-environment-management)
9. [Component 1 — Database Schema Creation (scripts/create_table.py)](#9-component-1--database-schema-creation)
10. [Component 2 — Centralized Constants (src/constants.py)](#10-component-2--centralized-constants)
11. [Component 3 — Data Transformations (src/kafka_client/transformations.py)](#11-component-3--data-transformations)
12. [Component 4 — Kafka Producer (src/kafka_client/kafka_stream_data.py)](#12-component-4--kafka-producer)
13. [Component 5 — Spark Streaming Consumer (src/spark_pgsql/spark_streaming.py)](#13-component-5--spark-streaming-consumer)
14. [Component 6 — Airflow DAG (airflow_resources/dags/dag_kafka_spark.py)](#14-component-6--airflow-dag)
15. [Incremental Processing and State Management](#15-incremental-processing-and-state-management)
16. [Deduplication Strategy — Two-Layer Design](#16-deduplication-strategy--two-layer-design)
17. [Data Quality and Normalization](#17-data-quality-and-normalization)
18. [End-to-End Data Flow Walkthrough](#18-end-to-end-data-flow-walkthrough)
19. [Setup and Running the Project](#19-setup-and-running-the-project)
20. [Monitoring and Observability](#20-monitoring-and-observability)
21. [Known Limitations and Honest Constraints](#21-known-limitations-and-honest-constraints)
22. [Design Decisions and Architectural Trade-offs](#22-design-decisions-and-architectural-trade-offs)
23. [Troubleshooting Guide](#23-troubleshooting-guide)
24. [Reproducibility Fixes Applied to This Repository](#24-reproducibility-fixes-applied-to-this-repository)
25. [Future Improvements](#25-future-improvements)
26. [Conclusion](#26-conclusion)

---

## 1. Executive Summary

This project implements a fully containerized, end-to-end data engineering pipeline that ingests real product-recall records from the French government's RappelConso open dataset, routes them through a Kafka message queue, processes and deduplicates them with Apache Spark Structured Streaming, and persists the final clean records into a PostgreSQL database. The entire workflow is orchestrated daily by an Apache Airflow DAG and runs locally on any machine with Docker Compose installed.

The pipeline is incremental by design: a state file tracks the last processed publication date so each daily run fetches only records newer than the previous execution, avoiding redundant API calls and redundant database writes. Deduplication is applied at two independent layers — first in the Python producer (in-memory, within each batch) and again in the Spark job (via a left anti-join against the existing database table) — so that even partial reruns or pipeline restarts produce no duplicate rows in the output.

The primary Big Data tool at the center of this project is Apache Spark. Kafka serves as the intermediate message transport layer, Airflow provides orchestration and scheduling, PostgreSQL provides the final storage sink, and Docker Compose ensures that every component can be reproduced identically on any developer machine without manual dependency installation.

The project handles real-world concerns that simple tutorial pipelines ignore: incremental ingestion with rollover logic to handle the API's per-date record cap, normalization of French text including accent removal, intelligent merging of semantically related columns, regex-based date range parsing, idempotent schema creation, streaming checkpoint management, and a Docker socket proxy pattern to let Airflow's DockerOperator spawn containers without requiring privileged socket mounts.

This document covers every file, design decision, configuration value, data transformation, networking detail, and operational procedure in the repository. It is intended to give both a high-level understanding of what the pipeline does and a low-level understanding of how every component is implemented.

---

## 2. Project Background and Motivation

Modern data engineering is defined by the ability to move information reliably from external sources into analytical storage systems, in a way that is reproducible, scalable, and auditable. A pipeline that works once on a developer laptop but cannot be reproduced by a teammate, or that processes records correctly on the first run but produces duplicates on the second, is not fit for purpose.

This project was designed to demonstrate a complete and correct implementation of a streaming data pipeline by addressing exactly those concerns. The guiding principles were:

**Reproducibility first.** Every component runs inside a Docker container. There is no assumption about the host machine's installed software beyond Docker and Docker Compose. The compose files pin image versions, the Dockerfiles pin dependency versions, and the environment is fully described by a single `.env` file that is derived from `.env.example`.

**Real data, real messiness.** Using a synthetic or artificially clean dataset hides the fact that real pipelines spend most of their complexity budget on data quality. The RappelConso dataset is a good pedagogical choice because it is genuinely messy: free-text fields contain accents and inconsistent formatting, some columns need to be merged, date ranges are embedded inside prose strings, and the API has a hard pagination cap per date window that requires stateful rollover logic.

**Separation of concerns.** The pipeline is split into clearly bounded components: ingestion (the Kafka producer), transport (the Kafka topic), processing (the Spark consumer), storage (PostgreSQL), and orchestration (Airflow). Each component has a single responsibility and communicates with its neighbors through well-defined interfaces. This makes each piece testable and replaceable in isolation.

**Incremental correctness.** A pipeline that reprocesses the entire history on every run wastes resources and creates idempotency problems. This project implements incremental ingestion using a persisted state file and implements idempotent writes using deduplication at both the producer and consumer layers.

**Academic positioning.** The project is also designed to serve as a clean anchor for Big Data academic coursework. Apache Spark is the central tool, and the surrounding ecosystem is described in relation to Spark's role rather than as a collection of independent tools. The pipeline demonstrates Spark's ability to consume from a real event stream, apply schema validation, perform distributed joins, and write to a relational sink — all in a single coherent job.

---

## 3. Dataset: RappelConso in Depth

### What is RappelConso

RappelConso is a French government platform operated by the Direction Générale de la Concurrence, de la Consommation et de la Répression des Fraudes (DGCCRF), which translates to the Directorate General for Competition Policy, Consumer Affairs and Fraud Control. The platform publishes mandatory product-recall notices for all consumer categories sold in France. When a manufacturer, distributor, or regulatory authority identifies a safety risk in a product, a recall notice is published to this platform. The API is publicly accessible with no authentication requirement.

### Volume and frequency

The RappelConso dataset contains records going back to the early 2000s, and new recall notices are published on most business days. The total historical record count is in the tens of thousands, making it large enough to justify incremental ingestion logic and deduplication infrastructure, while being small enough to process completely within a single daily pipeline run without requiring cluster-scale resources. This balance is exactly what makes it ideal for a demonstration pipeline: the data volumes are representative of real operational pipelines without requiring cloud infrastructure to handle them.

### Why this dataset is well-suited for a data engineering pipeline

The dataset has several properties that make it genuinely appropriate for this project rather than a contrived fit:

The API is paginated at 100 records per request and capped at 10,000 total records per date window. This pagination cap forces the pipeline to implement proper rollover logic: when the offset for a given date window reaches its limit, the query must advance to the next date and reset the offset. This is a real-world API constraint, not a tutorial simplification.

Records are identified by a stable unique key (`reference_fiche`) that persists across API calls. This makes deduplication by key meaningful and reliable. Records can appear in multiple API responses due to updates or overlapping date windows, and the unique key ensures that only one version of each recall notice enters the database.

The data contains French-language text with accents, special characters, and inconsistent capitalization. Text normalization is therefore not optional cosmetic cleanup but a necessary step to ensure consistent storage and future searchability.

Several semantically related fields appear as separate columns in the raw API response but are better represented as merged single columns in the stored schema. For example, risk information appears in two separate fields that describe different aspects of the same risk. These need to be merged before storage to avoid downstream queries having to join half-information across two columns.

Commercialization dates appear as a free-text prose string rather than structured date fields. A recall notice might include language that translates roughly to "sold from 01/03/2023 until 15/06/2023" — and the pipeline must parse that prose string with a regex to extract structured start and end date values.

The dataset grows continuously: new recalls are published daily. This makes incremental ingestion by date meaningful, because each day's run genuinely has new records to fetch.

### Schema

The stored schema (`rappel_conso_table`) has 25 columns, all stored as text type to maximize compatibility across different PostgreSQL versions and to avoid type-coercion failures on messy input:

- `reference_fiche` — primary key, unique recall reference identifier
- `date_de_publication` — publication date of the recall notice
- `rappel_guid` — globally unique identifier for the recall
- `lien_vers_la_liste_des_produits` — URL to the product list
- `lien_vers_les_images` — URL to product images
- `categorie_de_produit` — product category (food, cosmetics, vehicles, etc.)
- `sous_categorie_de_produit` — product subcategory
- `nom_de_la_marque_du_produit` — brand name
- `noms_des_modeles_ou_references` — model names or reference numbers
- `identification_des_produits` — product identifiers and packaging
- `motif_du_rappel` — reason for recall
- `risques_encourus_par_le_consommateur` — risks faced by the consumer (merged column)
- `conduites_a_tenir_par_le_consommateur` — recommended consumer actions (merged column)
- `reference_fiche` (PK)
- `distributeurs` — distributors and retailers
- `zone_geographique_de_vente` — geographic sales zone
- `date_debut_fin_de_commercialisation_start` — commercialization start date (parsed)
- `date_debut_fin_de_commercialisation_end` — commercialization end date (parsed)
- `temperature_de_conservation` — storage temperature
- `marque_de_salubrite` — health mark / safety certification
- `informations_complementaires` — additional information (merged column)
- `numero_de_version` — recall version number
- `nature_juridique_du_rappel` — legal nature of recall
- `date_de_fin_de_la_procedure_de_rappel` — end date of recall procedure
- `date_de_creation_de_la_fiche` — record creation date

### Academic domain mapping

The closest academic domain for this dataset is Healthcare and Consumer Safety, as the data directly concerns public health risks, mandatory product removals, and institutional safety recommendations. It can also be framed under Supply Chain and Retail Operations, since the recall process involves distributors, geographic zones, and logistics tracking.

### API access pattern

The RappelConso API is a standard REST API that returns JSON responses. There is no API key, OAuth token, or rate-limiting policy documented in the public interface, making it straightforward to query from a Python script. Each request accepts query parameters for filtering by publication date and for pagination control (limit and offset). The response body is a JSON object containing a `results` array and a `total_count` field. The total count is used to detect when pagination has exhausted the available records for a given query window. The pipeline queries this count to determine when to stop paginating and advance to the next date window, making the ingestion logic robust against varying daily record volumes.

---

## 4. System Architecture Overview

The pipeline follows a Lambda-adjacent architecture: it is not a continuous streaming system in the strict sense, but it uses streaming components (Kafka and Spark Structured Streaming) in a daily-batch execution model. The result is a system that has the fault tolerance and decoupling benefits of a streaming architecture while being orchestrated by Airflow as a scheduled batch workflow.

### Component topology

```
External Data Source
    RappelConso REST API (French Government)
         |
         | HTTP GET (incremental by date, paginated)
         v
Ingestion Layer
    Airflow Task: kafka_data_stream
    Python Producer (kafka_stream_data.py)
    - Reads state from last_processed.json
    - Fetches new records from API
    - Applies transformations
    - Publishes JSON to Kafka
         |
         | JSON messages (Kafka protocol, port 9092 internal)
         v
Transport Layer
    Kafka Topic: rappel_conso
    - KRaft mode (no ZooKeeper)
    - External access on port 9094
    - Monitored via Kafka UI on port 8000
         |
         | Kafka Structured Streaming (earliest offset)
         v
Processing Layer
    Airflow Task: pyspark_consumer
    Docker container: rappel-conso/spark:latest
    Spark Job (spark_streaming.py)
    - Reads and parses Kafka messages
    - Left anti-join against PostgreSQL
    - Writes only new rows
         |
         | JDBC write (PostgreSQL driver)
         v
Storage Layer
    PostgreSQL Table: rappel_conso_table
    - 25 text columns
    - Primary key: reference_fiche
    - Port: 5432
```

### Orchestration layer

Above all components sits Apache Airflow, which schedules the entire workflow as a daily DAG (`kafka_spark_dag`). The DAG runs three tasks in strict sequential order:

1. `create_target_table` — ensures the PostgreSQL schema exists
2. `kafka_data_stream` — runs the Python producer
3. `pyspark_consumer` — runs the Spark consumer as a Docker container

### Networking

All services communicate over a shared Docker bridge network named `airflow-kafka`. This allows container-to-container name resolution: the Airflow container can reach `kafka:9092`, the Spark container can reach `postgres:5432`, and Airflow's DockerOperator can spawn new containers on the same network through the `docker-proxy` service.

The Docker proxy (`alpine/socat`) solves a specific problem: the Airflow DockerOperator needs to communicate with the Docker daemon to spawn the Spark container, but mounting the Docker socket directly into a container raises security concerns. The socat proxy forwards TCP connections on port 2375 to the Unix socket at `/var/run/docker.sock`, allowing Airflow to use `tcp://docker-proxy:2375` as a clean network endpoint instead of a socket mount.

---

## 5. Technology Stack — Deep Dive

### Apache Spark 3.5.0 / 3.5.7

Spark is the primary Big Data processing engine in this project. It is used specifically in its Structured Streaming mode, which treats a real-time data stream as an unbounded table and allows SQL-like operations to be applied continuously as new data arrives.

In this project, Spark subscribes to the Kafka topic `rappel_conso` from the earliest available offset, reads all accumulated messages as a micro-batch, applies a predefined schema via `from_json`, performs a distributed left anti-join against the existing PostgreSQL records, and writes the resulting filtered DataFrame to PostgreSQL using JDBC.

The key configuration decision is `trigger(once=True)`. Rather than running Spark as a continuously active streaming job (which would hold a long-running container open), the job uses the "trigger once" mode, which processes all available messages at the time of execution and then terminates. This integrates cleanly with Airflow's task model, where tasks are expected to start, run, and finish.

Spark loads two external packages at runtime via `spark-submit --packages`:
- `org.postgresql:postgresql:42.5.4` — the JDBC driver for writing to PostgreSQL
- `org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0` — Kafka integration for Spark Structured Streaming

These packages are downloaded by Maven at job startup, which means the Spark container does not need them pre-installed. The version pins are important: mismatching the Kafka integration package version against the Spark version will cause runtime class-not-found errors.

The Spark container is built from `spark:3.5.7-java17-python3`, which bundles Spark 3.5.7, Java 17 (required minimum for Spark 3.5.x), and Python 3. The image is built locally with the tag `rappel-conso/spark:latest` and referenced by Airflow's DockerOperator.

### Apache Kafka (KRaft mode)

Kafka is the message queue that decouples the producer from the consumer. Without Kafka, the Python producer would have to write directly to PostgreSQL or call the Spark job synchronously. Kafka provides buffering and fault tolerance: even if the Spark consumer is slow or temporarily unavailable, the producer can continue publishing messages and Spark will catch up when it runs.

This project uses the `soldevelo/kafka` image, which runs Kafka in KRaft (Kafka Raft) consensus mode. KRaft is the modern Kafka deployment model that eliminates the ZooKeeper dependency. In traditional Kafka deployments, ZooKeeper is required for cluster metadata management and leader election. KRaft integrates this responsibility directly into Kafka using the Raft consensus algorithm, reducing operational complexity significantly.

The Kafka broker in this project runs in combined mode: it acts as both a broker (handling produce and consume requests) and a controller (handling cluster metadata and leader election). This is appropriate for a single-node local deployment.

The broker exposes three listeners:
- `PLAINTEXT://kafka:9092` — internal listener for container-to-container communication
- `CONTROLLER://kafka:9093` — internal listener for KRaft controller communication
- `EXTERNAL://0.0.0.0:9094` — external listener mapped to port 9094 on the host for local debugging

### Apache Airflow 2.7.3

Airflow is the workflow orchestration engine. It provides scheduling (the DAG runs on a daily timedelta schedule), dependency management (tasks run in a defined order with strict sequential dependencies), retry logic (each task retries once with a 5-second delay on failure), monitoring (the web UI shows task status and logs), and manual control (DAGs can be triggered on demand from the UI or CLI).

Airflow is deployed using the LocalExecutor, which runs tasks in subprocesses on the same machine rather than distributing them across workers. This is appropriate for a local development environment. The Airflow image is extended from `apache/airflow:2.7.3` with a custom Dockerfile that installs the additional Python dependencies required by the DAG tasks.

The `apache-airflow-providers-docker` package must be explicitly installed to enable the DockerOperator. Without this provider, Airflow has no built-in support for spawning Docker containers from DAG tasks.

### PostgreSQL 13

PostgreSQL serves as the final storage layer. It is used for two distinct purposes in this project:

First, it stores Airflow's own metadata — DAG definitions, task run history, execution logs, connection configurations, and variables. This is the standard use of PostgreSQL as an Airflow metadata database.

Second, it stores the pipeline's output — the `rappel_conso_table` containing cleaned recall records. Both usages share the same PostgreSQL instance (using database name `airflow` and user `airflow`) for simplicity in local development. In a production setting, separating the Airflow metadata database from the application database would be a standard practice.

### Python (kafka-python, psycopg2, requests, unidecode)

Python is the language of the producer, the transformation layer, the table creation script, and the Airflow DAG definition. Key library choices:

`kafka-python 2.0.2` is the Kafka producer client. It provides a simple synchronous `KafkaProducer` interface that serializes Python objects to bytes and sends them to a Kafka topic. The producer is configured to serialize values using `json.dumps(...).encode('utf-8')`. The `kafka-python` library is a pure-Python implementation, which means it has no native compilation requirements and installs cleanly inside Docker images built on any base OS. The `flush()` call after publishing ensures all buffered messages are delivered before the producer returns — this is critical for correctness in a pipeline where the next task (Spark) depends on all messages being available in Kafka before it starts reading.

`psycopg2-binary 2.9.9` is the PostgreSQL client used in `create_table.py` and potentially in connection setup. The binary distribution includes the compiled C extension, avoiding the need for the libpq development headers to be present on the host. The alternative, `psycopg2` (non-binary), requires the PostgreSQL client libraries to be installed at the OS level, which complicates Docker image builds and is unnecessary given the containerized environment.

`requests 2.31.0` is the HTTP client used to call the RappelConso API. It handles HTTP GET requests, JSON response parsing, timeout handling, and retry-eligible error responses. The `timeout` parameter is set on each API call to prevent the producer from hanging indefinitely if the API is slow to respond — a common operational failure mode for publicly hosted government APIs that are not SLA-bound.

`unidecode 1.3.7` performs Unicode transliteration — converting characters with accents and diacritics to their closest ASCII equivalents. This is used to normalize French-language text fields so that, for example, `"Réseau"` becomes `"Reseau"` and `"Bœuf"` becomes `"Boeuf"`. Consistent ASCII storage prevents encoding mismatches in downstream tools. The library handles the full Unicode space, not just French-specific characters, making it suitable for any internationalized text that the API might return.

### Docker and Docker Compose

Docker provides container isolation, ensuring that each service (Kafka, Airflow, Spark, PostgreSQL) runs in a reproducible environment regardless of the host OS. Docker Compose orchestrates the multi-container deployment through two compose files that are designed to be used together: `docker-compose.yml` for the infrastructure stack and `docker-compose-airflow.yaml` for the Airflow stack.

The use of two separate compose files (rather than one monolithic file) is a deliberate structural decision. It allows the infrastructure stack to be started and stopped independently from the Airflow stack, which is valuable during development when you might want to inspect the Kafka topic manually without starting all of Airflow, or restart only the Airflow services without interrupting the Kafka broker. Both files declare services on the `airflow-kafka` network, so when both stacks are running simultaneously, all containers can reach each other by service name.

Image versioning is explicit throughout: `postgres:13`, `apache/airflow:2.7.3`, `spark:3.5.7-java17-python3`. Pinning exact versions prevents unexpected behavior from image updates. The `provectuslabs/kafka-ui:latest` and `soldevelo/kafka:latest` use `latest`, which is a pragmatic choice for UI tooling and the Kafka broker where the project is primarily concerned with API compatibility rather than feature-level stability.

Health checks are defined for the PostgreSQL and Airflow services, using `pg_isready` and HTTP probes respectively. These health checks are used as `depends_on: condition: service_healthy` dependencies, ensuring that Airflow does not attempt to connect to PostgreSQL before the database is fully ready to accept connections. This eliminates a class of race-condition failures that would otherwise occur when all containers start simultaneously.

---

## 6. Repository Structure — File-by-File Breakdown

```
data-engineering-project/
|
|-- airflow_resources/               # Everything specific to the Airflow container
|   |-- Dockerfile                   # Extends apache/airflow:2.7.3
|   |-- requirements-airflow.txt     # Python deps for the Airflow image
|   |-- dags/
|   |   |-- dag_kafka_spark.py       # The main Airflow DAG definition
|   |   `-- __init__.py
|   `-- __init__.py
|
|-- config/                          # Airflow config directory (empty, volume-mounted)
|
|-- data/
|   `-- last_processed.json          # Incremental state: last API fetch date
|
|-- logs/                            # Airflow task logs (volume-mounted, auto-populated)
|
|-- scripts/
|   |-- create_table.py              # Idempotent PostgreSQL schema creation
|   `-- __init__.py
|
|-- spark/
|   `-- Dockerfile                   # Spark container image definition
|
|-- src/
|   |-- constants.py                 # All configuration constants in one place
|   |-- kafka_client/
|   |   |-- kafka_stream_data.py     # API ingestion and Kafka producer logic
|   |   |-- transformations.py       # Row-level transformation functions
|   |   `-- __init__.py
|   |-- spark_pgsql/
|   |   `-- spark_streaming.py       # PySpark Structured Streaming consumer
|   `-- __init__.py
|
|-- .env.example                     # Template for all required env variables
|-- .gitignore                       # Standard Python gitignore
|-- docker-compose.yml               # Kafka + Kafka UI + Spark image + Docker proxy
|-- docker-compose-airflow.yaml      # PostgreSQL + Airflow services
|-- requirements.txt                 # Full Python dependency list for local dev
|-- PROJECT_GUIDE.md                 # Original technical guide
|-- DOCUMENTATION.md                 # This file
|-- README.md                        # Project overview and quick start
`-- LICENSE                          # MIT License (Hamza Gharbi, 2023)
```

The separation between `docker-compose.yml` and `docker-compose-airflow.yaml` is intentional. The infrastructure stack (Kafka, Kafka UI, Docker proxy) can be started independently of the Airflow stack, which is useful for local development and debugging of individual components. Both stacks define services on the `airflow-kafka` network, so they can communicate with each other when both are running.

---

## 7. Infrastructure Layer — Docker Compose

### docker-compose.yml — Infrastructure Stack

This file defines four services:

**kafka** — The Kafka broker running in KRaft combined mode. The `soldevelo/kafka:latest` image is used in place of the more commonly referenced `bitnami/kafka` because it is a free alternative that does not require a commercial license for production use. The broker is configured with three listener addresses and exposes port 9094 externally. Key environment variables include `KAFKA_PROCESS_ROLES=broker,controller`, `KAFKA_NODE_ID=1`, and `KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER`.

**kafka-ui** — The Kafka UI web interface from `provectuslabs/kafka-ui`. It is configured to connect to the `kafka` service on port 9092 and is accessible at `http://localhost:8000`. This provides a visual interface for inspecting topics, viewing message content, and monitoring consumer group offsets without needing CLI tools.

**spark-app** — This service exists primarily to build the custom Spark Docker image. It uses `build: .` with `dockerfile: spark/Dockerfile` and tags the resulting image as `rappel-conso/spark:latest`. The service itself does not need to run continuously — it is used to ensure that the image is built and available for the Airflow DockerOperator to reference. Environment variables for PostgreSQL and Kafka connectivity are injected so they are available inside the container at runtime.

**docker-proxy** — An `alpine/socat` container that acts as a TCP-to-socket proxy. It listens on port 2375 and forwards to `/var/run/docker.sock`. This allows the Airflow DockerOperator, running inside its own container, to communicate with the host's Docker daemon via a standard TCP connection (`tcp://docker-proxy:2375`) rather than requiring the Docker socket to be mounted directly into the Airflow container. The socat container mounts `/var/run/docker.sock` with read-only access, keeping the security footprint minimal.

**Network:** All four services are connected to a bridge network named `airflow-kafka`.

### docker-compose-airflow.yaml — Airflow Stack

This file defines five services:

**postgres** — A PostgreSQL 13 container that serves as both the Airflow metadata database and the pipeline output database. It is configured with the credentials from the `.env` file and publishes port 5432 to the host. A named volume `postgres-db-volume` provides persistent storage so that database contents survive container restarts. A healthcheck is configured using `pg_isready` to ensure downstream services wait for the database to be fully ready before starting.

**airflow-webserver** — The Airflow UI process, serving the web interface on port 8080. It depends on the `postgres` service being healthy and on the `airflow-init` service having completed successfully. The executor is set to `LocalExecutor`, which means tasks run as subprocesses within the scheduler or webserver process rather than being distributed to separate worker containers.

**airflow-scheduler** — The Airflow scheduler process, which reads DAG definitions from the mounted `dags` directory and submits task runs according to their schedules. It depends on the same readiness conditions as the webserver.

**airflow-init** — A one-shot initialization container that runs on first startup to perform database migrations (`airflow db init`), create the admin user, and set file ownership on the mounted directories. It exits after completing these tasks. The admin username and password are sourced from `_AIRFLOW_WWW_USER_USERNAME` and `_AIRFLOW_WWW_USER_PASSWORD` environment variables.

**airflow-cli** — A CLI profile container that is only started when explicitly invoked with `--profile debug`. This provides a convenient way to run `airflow` CLI commands inside the container context without starting the full stack.

**Volume mounts in the Airflow services:**
- `./airflow_resources/dags` → `/opt/airflow/dags` — DAG definitions
- `./logs` → `/opt/airflow/logs` — Task execution logs
- `./config` → `/opt/airflow/config` — Airflow configuration files
- `./scripts` → `/opt/airflow/dags/scripts` — Table creation script accessible from DAG
- `./src` → `/opt/airflow/dags/src` — Producer and transformation source accessible from DAG
- `./data/last_processed.json` → `/opt/airflow/data/last_processed.json` — State file

---

## 8. Configuration and Environment Management

The project uses environment-variable-driven configuration throughout. No connection string, credential, hostname, port number, or file path is hardcoded in any Python file. All values come from environment variables, with `src/constants.py` serving as the single place where those environment variables are read and given Python-accessible names.

The `.env.example` file documents every variable the project requires:

```
AIRFLOW_UID=50000
_AIRFLOW_WWW_USER_USERNAME=airflow
_AIRFLOW_WWW_USER_PASSWORD=airflow
APP_POSTGRES_HOST=postgres
APP_POSTGRES_PORT=5432
APP_POSTGRES_DB=airflow
APP_POSTGRES_USER=airflow
APP_POSTGRES_PASSWORD=airflow
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
KAFKA_BOOTSTRAP_SERVERS_LOCAL=localhost:9094
KAFKA_TOPIC=rappel_conso
LAST_PROCESSED_PATH=/opt/airflow/data/last_processed.json
INITIAL_LAST_PROCESSED=2000-01-01
SPARK_IMAGE=rappel-conso/spark:latest
```

A note on the dual Kafka bootstrap server variables: `KAFKA_BOOTSTRAP_SERVERS` is the address used when the producer runs inside Docker (container-to-container communication via internal port 9092). `KAFKA_BOOTSTRAP_SERVERS_LOCAL` is the address used when the producer runs directly on the host machine (external port 9094). The producer in `kafka_stream_data.py` tries the internal address first and falls back to the local address if the connection is refused, making the code usable in both execution contexts.

The `AIRFLOW_UID` variable is specifically important on Linux hosts. Airflow runs its processes under a user with this UID, and the mounted directories (`dags`, `logs`, `config`) need to be owned by the same UID to be readable and writable from inside the container. On Windows and Mac hosts, Docker handles this transparently; on Linux, mismatched UIDs result in permission errors.

---

## 9. Component 1 — Database Schema Creation

**File:** `scripts/create_table.py`
**Invoked by:** Airflow task `create_target_table` (PythonOperator)

This script has a single responsibility: ensure that the `rappel_conso_table` table exists in PostgreSQL before any other pipeline task attempts to write to it.

### Implementation details

The script reads PostgreSQL connection parameters from four environment variables (`APP_POSTGRES_HOST`, `APP_POSTGRES_PORT`, `APP_POSTGRES_DB`, `APP_POSTGRES_USER`, `APP_POSTGRES_PASSWORD`) and establishes a connection using psycopg2.

The `build_create_table_sql()` function constructs a `CREATE TABLE IF NOT EXISTS` statement. Every column is declared as `TEXT` type, including the primary key `reference_fiche`. The `TEXT` type choice is deliberate: it accommodates variable-length strings of any size, avoids truncation errors from unexpected long values, and avoids type-coercion failures on numeric-looking identifiers that might have leading zeros or non-numeric characters.

The `IF NOT EXISTS` clause is what makes this task idempotent. Idempotency in this context means the task can be run any number of times — on the first run it creates the table, on all subsequent runs it detects the table already exists and takes no action. Without idempotency, re-running the DAG after a successful first run would raise a `DuplicateTable` error and fail the entire pipeline.

The function closes the database connection and cursor in a `finally` block, ensuring that connection resources are released even if the SQL execution raises an exception.

### Why this runs as a DAG task rather than a migration script

Making schema creation a DAG task rather than a one-time setup script removes the need for a manual setup step that operators could forget to run. Every DAG run is self-healing: if the table was accidentally dropped between runs, the next run will recreate it before attempting to write. This is a practical pattern in production data pipelines where infrastructure state can diverge from expectations.

### Connection handling pattern

The function opens a new database connection, executes the DDL statement, commits the transaction, and closes the connection inside a `try/finally` block. The `finally` block ensures that `cursor.close()` and `conn.close()` are called even if the SQL execution raises an exception. Leaving database connections open is a common source of connection pool exhaustion in long-running applications; explicit connection management in a short-lived script like this avoids that class of problem entirely.

The connection uses `autocommit=False` (psycopg2's default), which means the DDL statement runs inside a transaction. PostgreSQL DDL is transactional, so if the table creation fails partway through (which is unlikely for a simple CREATE TABLE but theoretically possible), the transaction is rolled back cleanly rather than leaving the table in a partially created state.

---

## 10. Component 2 — Centralized Constants

**File:** `src/constants.py`

This file is the single source of truth for every configuration value used across the pipeline. Rather than having each file read its own environment variables independently — which creates duplication and makes configuration changes require edits in multiple files — all environment reading happens here, and every other file imports the named constants it needs.

### API configuration constants

`URL_API` holds the base URL for the RappelConso dataset endpoint. This is read from an environment variable rather than hardcoded, making it easy to point the pipeline at a staging or test API.

`MAX_LIMIT = 100` sets the number of records requested per API call. This is the maximum the API accepts per request.

`MAX_OFFSET = 10000` is a critical constant. The RappelConso API does not allow retrieving more than 10,000 records for a single date window. If a given publication date has more than 10,000 records (unlikely but architecturally possible), the producer would stop at the cap. More practically, this constant controls when the date-rollover logic activates: when the accumulated offset for a date window reaches `MAX_OFFSET`, the producer advances to the next date rather than continuing to increment the offset.

`DEFAULT_LAST_PROCESSED = "2000-01-01"` is the fallback start date for the first run, ensuring the full historical dataset is fetched.

`PATH_LAST_PROCESSED` reads the path to the state file from `LAST_PROCESSED_PATH`, defaulting to `/opt/airflow/data/last_processed.json` if the variable is not set.

### Kafka configuration constants

`KAFKA_TOPIC` is the name of the Kafka topic, read from the `KAFKA_TOPIC` environment variable.

`KAFKA_BOOTSTRAP_SERVERS` and `KAFKA_BOOTSTRAP_SERVERS_LOCAL` are the internal and external Kafka addresses respectively, as described in the configuration section.

### PostgreSQL configuration constants

`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` are read from their respective environment variables.

`POSTGRES_URL` is the JDBC connection URL string constructed from these components: `jdbc:postgresql://{host}:{port}/{db}`. This format is required by Spark's DataFrame writer when writing via JDBC.

### Column definition lists

`NEW_COLUMNS` — a list of 5 column names that are created by the transformation process and do not exist in the raw API response. These include the merged risk column, the merged health recommendation column, the merged additional info column, and the two parsed commercialization date columns.

`COLUMNS_TO_NORMALIZE` — a list of 12 column names from the raw API response that undergo accent normalization via unidecode. These are all free-text fields whose content is user-entered and may contain accents.

`COLUMNS_TO_KEEP` — a list of 8 column names from the raw API response that are passed through unchanged to the stored schema. These are typically links (URLs), raw date strings, and identifier fields where normalization would be destructive.

`DB_FIELDS` — the complete ordered list of all 25 column names that appear in the `rappel_conso_table` schema. This list is used both by `create_table.py` (to build the CREATE TABLE statement) and by `spark_streaming.py` (to define the schema for JSON parsing).

---

## 11. Component 3 — Data Transformations

**File:** `src/kafka_client/transformations.py`

This module contains all row-level data transformation logic. It is kept separate from the producer logic so that transformations can be understood, tested, and modified independently of the API ingestion mechanics.

### normalize_one(text)

This function takes a single string value and returns its ASCII-transliterated equivalent using `unidecode.unidecode()`. If the input is `None` or not a string, the function returns the input unchanged to avoid type errors downstream.

Practical examples:
- `"Réseau de distribution"` → `"Reseau de distribution"`
- `"Bœuf haché"` → `"Boeuf hache"`
- `"Caractéristiques"` → `"Caracteristiques"`

The rationale for accent normalization is storage consistency. If the same product brand is stored sometimes as `"Société"` and sometimes as `"Societe"` (due to inconsistent source data or encoding variations), queries that filter by brand name will miss records. Normalizing to ASCII ensures that all text fields use a consistent character set.

### merge_two_columns(col_a, col_b, row, normalize)

This function takes two column names and a row dictionary, reads both values from the row, optionally normalizes each with `normalize_one`, and joins them with a newline separator if both are non-empty. If only one value is present, it returns that value alone. If neither is present, it returns an empty string.

This function is called three times in `transform_row()`:
- To merge the two raw risk columns into `risques_encourus_par_le_consommateur`
- To merge the two raw health-recommendation columns into `conduites_a_tenir_par_le_consommateur`
- To merge the two raw additional-info columns into `informations_complementaires`

The merge is necessary because the RappelConso API represents certain multi-part fields as two separate columns rather than one. Storing them as separate columns in the database would complicate downstream queries, since any query for risk information would need to union two columns.

### separate_commercialisation_dates(row)

This is the most complex transformation function. The raw API response contains a single free-text column for the commercialization period, which looks like prose rather than a structured date field. Example values (translated from French) include:
- "Sold from 01/03/2023 until 15/06/2023"
- "From 01/01/2022"
- "Until 30/04/2023"
- (empty)

The function applies the regex pattern `(\d{2}/\d{2}/\d{4})` to extract all date-formatted substrings. It then checks whether the original text contains the French keyword "depuis le" (meaning "from") or "jusqu" (an abbreviation appearing in "jusqu'au" meaning "until") to determine which extracted date is the start date and which is the end date.

Return value is a tuple `(start_date, end_date)` where either value may be an empty string if not determinable from the text. These two values become the `date_debut_fin_de_commercialisation_start` and `date_debut_fin_de_commercialisation_end` columns respectively.

### normalize_columns(api_row)

This function processes a complete raw API row dictionary and applies normalization to the columns listed in `COLUMNS_TO_NORMALIZE`, leaving all other columns untouched. It returns a new dictionary with the same structure as the input but with normalized values in the designated columns.

### transform_row(api_row)

This is the main entry point for the transformation pipeline. It calls all other transformation functions in sequence:

1. `normalize_columns(api_row)` — normalizes accent-bearing text fields
2. `merge_two_columns(...)` × 3 — merges the three pairs of related columns
3. `separate_commercialisation_dates(...)` — parses the commercialization date prose field
4. Constructs and returns a new dictionary with only the final `DB_FIELDS` columns, in the correct order

The output of `transform_row()` is a clean Python dictionary ready to be serialized to JSON and published to Kafka.

---

## 12. Component 4 — Kafka Producer

**File:** `src/kafka_client/kafka_stream_data.py`

This module implements the complete API-to-Kafka ingestion pipeline. It is invoked by the Airflow `kafka_data_stream` task via its `stream()` entry point function.

### get_latest_timestamp()

Reads `last_processed.json` from the path defined in `constants.PATH_LAST_PROCESSED`. If the file exists and contains a `last_processed` key, its value is returned as the starting date for the API query. If the file is missing, empty, or contains malformed JSON, the function returns `constants.DEFAULT_LAST_PROCESSED` ("2000-01-01"), which triggers a full historical fetch.

The state file is mounted from the host machine (`./data/last_processed.json`) into the Airflow container, so its contents persist across container restarts. This is the key mechanism that makes incremental ingestion work: the state survives even if the entire Docker stack is torn down and restarted.

### get_all_data(timestamp)

This is the API pagination engine. It takes a starting timestamp and fetches all records with a publication date greater than or equal to that timestamp.

The pagination strategy works as follows:

- Set offset to 0, current_date to the provided timestamp
- Fetch a batch of `MAX_LIMIT` (100) records at offset
- If the batch is empty, increment the date by one day and reset the offset (date-rollover)
- If the batch has records, yield them and increment the offset by `MAX_LIMIT`
- If the offset reaches `MAX_OFFSET` (10,000) for the current date, advance to the next date and reset the offset
- Continue until reaching the current date with no more records

The date-rollover logic is specifically designed to handle the API's 10,000-record-per-date cap. If a particular date has more than 10,000 records (theoretically), the producer would skip the excess rather than fail, and the left anti-join in the Spark layer would prevent duplicates from a later re-fetch.

Each API call includes a timeout parameter and a retry mechanism: if the request times out, the producer waits and retries up to a configurable number of times before raising an error.

### deduplicate_data(data)

Takes a list of API records and returns only the records whose `reference_fiche` has not been seen in the current batch. It maintains a set of seen keys and filters as it iterates. This handles duplicate records that the API may return for the same publication date within a single query session.

This is distinct from the cross-run deduplication performed by the Spark anti-join. The producer deduplication addresses within-batch duplicates; the Spark deduplication addresses cross-run duplicates.

### update_last_processed_file(data)

After a successful fetch and publish, this function updates the state file with the maximum publication date seen in the current batch, minus one day.

The one-day subtraction is a safety buffer. Publication dates in the API are populated at the time a recall notice is filed, and there can be a lag between when a record is created and when it appears in the API response. By rolling back one day, the next run will re-query records from that date, ensuring that any late-appearing records for a given date are caught in the subsequent run. The downstream Spark anti-join ensures that already-stored records are not re-inserted despite the overlapping query window.

### create_kafka_producer()

Creates and returns a `KafkaProducer` instance configured with:
- `bootstrap_servers`: tries `KAFKA_BOOTSTRAP_SERVERS` (internal), falls back to `KAFKA_BOOTSTRAP_SERVERS_LOCAL` (external) on `NoBrokersAvailable` exception
- `value_serializer`: `lambda v: json.dumps(v).encode('utf-8')` — serializes Python dictionaries to UTF-8 encoded JSON bytes

The fallback from internal to external Kafka address means the producer works correctly whether it runs inside Docker (where `kafka:9092` is reachable) or directly on the host machine (where only `localhost:9094` is reachable).

### stream()

The main entry point. It orchestrates the full ingestion sequence:

1. Call `query_data()` to fetch, deduplicate, and transform all new API records
2. Call `create_kafka_producer()` to get a configured producer
3. Iterate over all transformed records and call `producer.send(KAFKA_TOPIC, value=record)` for each
4. Call `producer.flush()` to ensure all messages are sent before returning
5. Call `producer.close()` to release connection resources

Each record is logged at the DEBUG level as it is sent, providing visibility into individual message publishing during development.

---

## 13. Component 5 — Spark Streaming Consumer

**File:** `src/spark_pgsql/spark_streaming.py`

This module implements the Spark Structured Streaming job that consumes messages from Kafka and writes deduplicated records to PostgreSQL. It runs inside the `rappel-conso/spark:latest` Docker container, which is invoked by the Airflow DockerOperator.

### create_spark_session()

Creates and returns a `SparkSession` configured with:
- `appName`: "PostgreSQL Connection with PySpark"
- `spark.jars.packages`: a comma-separated list of the PostgreSQL JDBC driver and the Kafka connector for Spark 2.12 (the Scala version matching Spark 3.5.x)

The packages string is built dynamically from constants defined in the file. Maven downloads these packages from the central repository on first execution; they are cached in the Spark container's `/root/.ivy2` directory for subsequent runs (though in this containerized setup, each run starts from a fresh container, so Maven download happens every time unless a persistent volume is added).

### create_initial_dataframe(spark_session)

Creates a streaming DataFrame by subscribing to the Kafka topic. Key configuration options:

- `format("kafka")` — instructs Spark to use the Kafka connector
- `option("kafka.bootstrap.servers", ...)` — reads from `KAFKA_BOOTSTRAP_SERVERS` environment variable
- `option("subscribe", KAFKA_TOPIC)` — subscribes to the `rappel_conso` topic
- `option("startingOffsets", "earliest")` — reads all accumulated messages from the beginning of the topic's retention window

The resulting DataFrame has Kafka's schema: columns for `key`, `value`, `topic`, `partition`, `offset`, `timestamp`, and `timestampType`. The actual record data is in the `value` column as binary bytes.

### create_final_dataframe(df)

Transforms the raw Kafka DataFrame into a structured DataFrame with the 25 recall record columns.

First, a `StructType` schema is built programmatically from `DB_FIELDS` — every field is declared as `StringType()`. This is consistent with the all-text database schema.

Then, `from_json(col("value").cast("string"), schema)` is applied to parse the binary Kafka value into a structured nested column. Finally, the 25 individual data columns are selected from the parsed result using `col("data.*")`.

The result is a streaming DataFrame with exactly 25 string columns, one for each database field. Any message that does not match the expected JSON structure will have `null` values in its columns, which will then fail the `reference_fiche` primary key constraint on write — effectively discarding malformed records.

### start_streaming(df_parsed, spark)

This is the most architecturally significant function. It implements the deduplication logic and the write-to-PostgreSQL pipeline.

The function defines an inner function `foreach_batch_function(df, epoch_id)` that is called by Spark for each micro-batch:

1. Read the current contents of `rappel_conso_table` from PostgreSQL into a static DataFrame (`df_existing`) using Spark's JDBC reader
2. Perform a left anti-join: `df.join(df_existing, on="reference_fiche", how="left_anti")`
3. Write only the records that did not match (i.e., records not in the database) to PostgreSQL using append mode

The left anti-join is the idempotency mechanism for the Spark layer. It runs a distributed join between the incoming batch of Kafka records and the full existing database table. Only records whose `reference_fiche` does not exist in the database are passed through to the write step. This guarantees that no record is inserted more than once, regardless of how many times the same Kafka message is consumed.

The `writeStream` configuration includes:
- `foreachBatch(foreach_batch_function)` — custom per-batch processing logic
- `checkpointLocation("/tmp/spark-checkpoints/rappel_conso")` — required for Spark Structured Streaming to maintain offset tracking
- `trigger(once=True)` — process all available messages and terminate

### write_to_postgres()

The main entry point for the Spark job. It calls the four functions above in sequence and calls `awaitTermination()` on the streaming query to wait for the one-shot trigger to complete before the script exits.

### Spark Dockerfile

The `spark/Dockerfile` extends `spark:3.5.7-java17-python3`. It:
- Sets the working directory to `/opt/spark`
- Copies `src/spark_pgsql/spark_streaming.py` to the working directory as `spark_streaming.py`
- Copies `src/constants.py` to `src/constants.py` within the container
- Copies `src/__init__.py` to `src/__init__.py` to make `src` a Python package
- Sets all required environment variables for PostgreSQL and Kafka connectivity

The `spark-submit` command in the Airflow DockerOperator is:

```
./bin/spark-submit --master local[*] --packages [postgresql driver],[kafka connector] ./spark_streaming.py
```

`--master local[*]` runs Spark in local mode using all available CPUs. This is appropriate for a containerized single-node deployment.

---

## 14. Component 6 — Airflow DAG

**File:** `airflow_resources/dags/dag_kafka_spark.py`

### DAG definition

The DAG is identified by `dag_id="kafka_spark_dag"`. Its default arguments set:
- `owner`: "airflow"
- `start_date`: `datetime.now() - timedelta(days=1)` — ensures the DAG is immediately eligible to run after deployment without requiring a specific past date
- `retries`: 1 — each task retries once on failure
- `retry_delay`: `timedelta(seconds=5)` — brief delay between retry attempts

The DAG-level parameters are:
- `schedule_interval`: `timedelta(days=1)` — runs daily
- `catchup`: `False` — disables backfill of any missed historical runs

The `catchup=False` setting is important. If it were set to `True`, starting Airflow after several days of downtime would trigger multiple DAG runs for each missed day, potentially overloading the pipeline. With `catchup=False`, only the most recent missed run is triggered.

### Task 1 — create_target_table (PythonOperator)

```python
create_target_table = PythonOperator(
    task_id="create_target_table",
    python_callable=create_table,
)
```

Calls `scripts.create_table.create_table()` directly as a Python callable. This runs in the Airflow process, using the psycopg2 driver already installed in the Airflow container image.

### Task 2 — kafka_data_stream (PythonOperator)

```python
kafka_data_stream = PythonOperator(
    task_id="kafka_data_stream",
    python_callable=stream,
)
```

Calls `src.kafka_client.kafka_stream_data.stream()` directly. The `src` directory is volume-mounted into `/opt/airflow/dags/src`, which is on the Python path, so the import resolves correctly.

### Task 3 — pyspark_consumer (DockerOperator)

```python
pyspark_consumer = DockerOperator(
    task_id="pyspark_consumer",
    image=SPARK_IMAGE,
    command="./bin/spark-submit --master local[*] --packages ... ./spark_streaming.py",
    docker_url="tcp://docker-proxy:2375",
    network_mode="airflow-kafka",
    environment={
        "APP_POSTGRES_HOST": APP_POSTGRES_HOST,
        "APP_POSTGRES_PORT": APP_POSTGRES_PORT,
        ...
    },
    auto_remove=True,
)
```

Key DockerOperator parameters:
- `image`: References `rappel-conso/spark:latest`, which must be pre-built on the host before the DAG runs
- `docker_url`: `tcp://docker-proxy:2375` — routes Docker API calls through the socat proxy
- `network_mode`: `airflow-kafka` — attaches the spawned Spark container to the same network as Kafka and PostgreSQL, enabling name resolution for `kafka:9092` and `postgres:5432`
- `auto_remove`: `True` — the Spark container is automatically deleted after it finishes, keeping the Docker environment clean
- `environment`: All PostgreSQL and Kafka connection parameters are passed explicitly as environment variables

### Task dependency

```python
create_target_table >> kafka_data_stream >> pyspark_consumer
```

This single line of Python establishes the complete dependency graph. The `>>` operator is Airflow's bitshift notation for "set downstream". The three tasks run strictly in sequence; no task starts until its predecessor has completed successfully.

### Airflow XCom and why it is not used here

Airflow's XCom (cross-communication) mechanism allows tasks to pass small data values to downstream tasks. For example, `kafka_data_stream` could theoretically push the count of published records as an XCom value, which `pyspark_consumer` could then read to decide whether to run.

This project deliberately avoids XCom. The simplicity of the dependency (run A, then B, then C) does not benefit from inter-task communication. The Spark job's behavior is identical regardless of how many records were published — it always reads from "earliest" and deduplicates before writing. Introducing XCom would add complexity without adding correctness or resilience.

### LocalExecutor vs other Airflow executors

The `LocalExecutor` runs tasks as subprocesses on the same machine as the Airflow scheduler. This is the right choice for a local single-machine deployment. The main alternative executors are the `CeleryExecutor` (distributes tasks to remote worker nodes via a message queue, requiring Redis or RabbitMQ as a broker) and the `KubernetesExecutor` (spawns a Kubernetes pod for each task). Both alternatives are operationally more complex and unnecessary for the scale of this project. The `SequentialExecutor` (runs one task at a time) would also work but limits parallelism even when tasks could theoretically run concurrently.

---

## 15. Incremental Processing and State Management

### The problem with full-history fetches

A naive pipeline would fetch all records from the RappelConso API on every run. This is problematic for several reasons: it wastes API bandwidth, it increases the time each run takes as the historical dataset grows, and it creates increasing load on the deduplication layer as the database grows larger.

### The solution: date-based incremental state

The pipeline solves this with a simple but effective state management mechanism. A JSON file (`data/last_processed.json`) stores the date of the most recently processed record. On each run, the producer reads this date and queries only records published after it.

The file format is minimal:
```json
{"last_processed": "2024-03-15"}
```

On the very first run, the file contains `{}` (empty JSON object), which causes `get_latest_timestamp()` to return the default date `2000-01-01`, triggering a full historical fetch.

### State update logic and the safety buffer

After a successful ingestion run, `update_last_processed_file()` writes the maximum publication date found in the current batch, minus one day.

The one-day safety buffer is a deliberate design choice. The RappelConso API populates publication dates from user-entered data, and there can be a lag between when an event is recorded in the system and when it becomes queryable through the API. By rolling back the last-processed date by one day, the next run's query window overlaps slightly with the previous run's window. Any records that were missed (due to API indexing delays) during the previous run will be captured in the next run's query.

The Spark anti-join ensures that the overlapping window does not cause duplicate database writes: even if a record is fetched twice across two consecutive runs, the anti-join will filter it out on the second run because its `reference_fiche` already exists in `rappel_conso_table`.

### Resetting state

To replay historical data from a different date, the file contents can be set to `{}` (for a full reset) or to a specific date:
```bash
echo '{"last_processed": "2023-01-01"}' > data/last_processed.json
```

Because the Spark anti-join prevents duplicate inserts, resetting the state file and re-running the pipeline is always safe. Records that were already stored will be filtered out by the anti-join; only genuinely new records from the replayed date range will be inserted. This means the pipeline is fully replayable without risk of data corruption, which is a property that significantly simplifies operational recovery from errors or partial failures.

### File mounting and container boundaries

The `last_processed.json` file is volume-mounted at the file level (not at the directory level) from the host into the Airflow container. The Airflow container reads and writes it as a local file using standard Python file I/O, which works transparently because Docker volume mounts appear as ordinary filesystem paths inside the container. The Spark container does not access this file — by the time Spark runs, the state has already been read and updated by the producer task.

---

## 16. Deduplication Strategy — Two-Layer Design

Deduplication happens at two independent layers, both keyed on `reference_fiche`.

### Layer 1 — Producer: within-batch deduplication

The `deduplicate_data(data)` function in the producer processes a list of API records and removes any record whose `reference_fiche` has already been seen in the same list. It builds a set of seen keys and returns only the first occurrence of each.

This layer handles API-level duplicates: situations where the same recall notice appears multiple times in the API response for a given date window. This can happen due to API pagination edge cases or updates to existing records that cause them to appear under multiple date stamps.

### Layer 2 — Spark: cross-run deduplication

The `foreach_batch_function` in the Spark job reads the current contents of `rappel_conso_table` and performs a left anti-join against the incoming Kafka batch on `reference_fiche`. Only records not present in the database are written.

A left anti-join returns all rows from the left DataFrame (incoming Kafka batch) that have no match in the right DataFrame (existing database rows). This is more efficient than alternatives like `INSERT ... ON CONFLICT DO NOTHING`, because the filtering happens in Spark's distributed memory before any database write is attempted, reducing the number of JDBC write calls.

### Why two layers are necessary

The two layers address different failure modes:

- The producer layer prevents Kafka from accumulating duplicate messages within a single batch. Even if the Spark layer could handle duplicates, having duplicate messages in Kafka wastes storage and increases Spark processing time.

- The Spark layer provides cross-run idempotency. If the pipeline is re-run (due to a failure, a manual trigger, or the one-day safety buffer overlap), the Spark layer ensures the database remains consistent without requiring any additional logic in the producer.

Together, the two layers provide end-to-end exactly-once semantics for the stored data: regardless of how many times a given record enters the pipeline, it appears exactly once in `rappel_conso_table`.

---

## 17. Data Quality and Normalization

### Text encoding and accent removal

French text contains accented characters (é, è, ê, à, â, ô, ù, û, î, ï, ë, ü, ç, œ, æ, and others) that can cause issues in downstream SQL queries, full-text search, and export to systems with limited Unicode support.

The `unidecode` library performs transliteration — mapping each accented character to its closest ASCII equivalent. This is a lossy transformation: information about the original accent is discarded. The trade-off is accepted because the primary use case is storage and querying, not reconstruction of the original text.

The 12 columns subjected to normalization are all free-text fields entered by recall filers: brand names, product categories, distribution descriptions, recall motives, and similar human-authored text. The 8 columns passed through unchanged are reference identifiers and URLs, where normalization would be destructive.

### Column merging rationale

The raw API response exposes certain semantically unified concepts as multiple columns. For example, consumer risk information appears in two fields that represent different aspects of the same risk (the nature of the risk and the severity). Storing these as two separate columns complicates queries: any query asking "what are the risks for this product" must union two columns. Merging them at ingestion time, joined with a newline separator, keeps the stored schema clean and downstream queries simple.

The newline separator preserves both values distinctly rather than concatenating them into an unreadable string. The receiving application can split on newline to recover the individual components if needed.

### Date parsing

The commercialization period field in the raw API is a free-text prose field written by the recall filer. Dates are embedded in this text in a French-language sentence. The regex `(\d{2}/\d{2}/\d{4})` reliably extracts `DD/MM/YYYY` formatted dates from arbitrary surrounding text. The French keywords "depuis le" and "jusqu" determine which extracted date is the start date and which is the end date.

This approach handles the most common formats but will produce empty strings for unusual formats (such as narrative-only descriptions with no date, or dates in non-standard formats). Empty strings are stored rather than nulls, consistent with the all-text schema.

---

## 18. End-to-End Data Flow Walkthrough

This section traces a single recall record from its origin in the French government database through every stage of the pipeline until it rests in `rappel_conso_table`.

### Stage 1 — Airflow scheduler fires the DAG

At the scheduled time (daily), the Airflow scheduler creates a DAG run for `kafka_spark_dag`. The first task, `create_target_table`, is submitted to the LocalExecutor.

### Stage 2 — Table schema ensured

`create_table()` connects to PostgreSQL, runs `CREATE TABLE IF NOT EXISTS rappel_conso_table (reference_fiche TEXT PRIMARY KEY, ...)`, and exits. On the first run, the table is created. On subsequent runs, the statement is a no-op. Task status: success.

### Stage 3 — Producer reads state and queries API

`stream()` calls `get_latest_timestamp()`, which reads `last_processed.json` and returns, say, `"2024-03-14"`. The producer begins querying the API for records with `date_de_publication >= 2024-03-14`.

### Stage 4 — API pagination

`get_all_data("2024-03-14")` issues GET requests to the RappelConso endpoint with offset 0, 100, 200, etc. Each response returns up to 100 records. When a date window returns an empty response, the producer advances to the next date. This continues until the API returns no records for the current date (indicating we've caught up to the present).

### Stage 5 — Within-batch deduplication

The collected batch is passed to `deduplicate_data()`. Any record whose `reference_fiche` appeared earlier in the same batch is discarded.

### Stage 6 — Transformation

Each unique record is passed to `transform_row()`. Suppose the record contains:
- `nom_de_la_marque_du_produit`: `"Société Générale Alimentaire"`
- `risques_col_a`: `"Risque d'étouffement"`
- `risques_col_b`: `"Risque allergène"`
- `commercialisation_dates`: `"Vendu depuis le 01/03/2023 jusqu'au 15/06/2023"`

After transformation:
- `nom_de_la_marque_du_produit`: `"Societe Generale Alimentaire"` (accent removal)
- `risques_encourus_par_le_consommateur`: `"Risque d'etouffement\nRisque allergene"` (merged, normalized)
- `date_debut_fin_de_commercialisation_start`: `"01/03/2023"` (parsed)
- `date_debut_fin_de_commercialisation_end`: `"15/06/2023"` (parsed)

### Stage 7 — Publishing to Kafka

The transformed record dictionary is JSON-serialized and sent to the `rappel_conso` Kafka topic via `producer.send()`. The message key is None; the value is the UTF-8 encoded JSON string.

### Stage 8 — State file updated

After all records are published, `update_last_processed_file()` writes the maximum date minus one day back to `last_processed.json`.

### Stage 9 — Airflow starts the Spark task

Once `kafka_data_stream` completes successfully, Airflow submits the `pyspark_consumer` task to the DockerOperator.

### Stage 10 — Spark container starts

Airflow calls the Docker API (via `docker-proxy`) to start a new container from `rappel-conso/spark:latest`, attaches it to the `airflow-kafka` network, and passes all environment variables.

### Stage 11 — Spark reads from Kafka

`create_initial_dataframe()` creates a streaming DataFrame subscribed to `rappel_conso` from offset "earliest". With `trigger(once=True)`, Spark reads all currently available messages.

### Stage 12 — Schema parsing

`create_final_dataframe()` applies `from_json` with the 25-field StringType schema, turning each binary Kafka message into a structured row.

### Stage 13 — Left anti-join deduplication

`foreach_batch_function()` reads `rappel_conso_table` from PostgreSQL into `df_existing`. The anti-join `df.join(df_existing, on="reference_fiche", how="left_anti")` filters out any incoming record whose `reference_fiche` already exists in the database.

For a first run, `df_existing` is empty so all records pass through. For subsequent runs, only records from the one-day overlap period that are genuinely new pass through.

### Stage 14 — Write to PostgreSQL

The filtered DataFrame is written to `rappel_conso_table` in append mode via JDBC. The record with `reference_fiche` from our example is now permanently stored.

### Stage 15 — Spark terminates, DAG run completes

With `trigger(once=True)`, Spark exits after processing the available batch. The Spark container stops and is removed (`auto_remove=True`). Airflow marks the `pyspark_consumer` task as successful and the DAG run as complete.

---

## 19. Setup and Running the Project

### Prerequisites

- Docker Desktop (Windows/Mac) or Docker Engine + Docker Compose (Linux)
- Minimum 8 GB RAM allocated to Docker
- Internet connectivity to pull images and reach the RappelConso API
- Git for cloning the repository

### Step-by-step instructions

**Step 1 — Clone the repository**
```bash
git clone https://github.com/8harath/Big-Data-Analytics.git
cd Big-Data-Analytics
```

**Step 2 — Create the environment file**

On Windows PowerShell:
```powershell
Copy-Item .env.example .env
```
On Linux/Mac:
```bash
cp .env.example .env
```
Edit `.env` if you need to change credentials or port assignments.

**Step 3 — Build the Spark image**

The DockerOperator requires the Spark image to exist on the host before the DAG runs:
```bash
docker build -f spark/Dockerfile -t rappel-conso/spark:latest .
```

**Step 4 — Start the infrastructure stack**
```bash
docker compose -f docker-compose.yml up -d
```
Wait for all containers to report healthy:
```bash
docker compose -f docker-compose.yml ps
```

**Step 5 — Start the Airflow stack**
```bash
docker compose -f docker-compose-airflow.yaml up -d
```
Monitor initialization:
```bash
docker compose -f docker-compose-airflow.yaml logs -f airflow-init
```
Wait until `airflow-init` exits with code 0.

**Step 6 — Access web interfaces**
- Airflow UI: http://localhost:8080 (credentials: airflow / airflow)
- Kafka UI: http://localhost:8000

**Step 7 — Enable and trigger the DAG**

In the Airflow UI:
1. Find `kafka_spark_dag` in the DAG list
2. Toggle the enable switch (the pause button on the left)
3. Click the play button to trigger a manual run

Or via CLI:
```bash
docker compose -f docker-compose-airflow.yaml run --rm airflow-cli airflow dags trigger kafka_spark_dag
```

**Step 8 — Monitor the pipeline**

Watch task execution in the Airflow Grid View. Click individual tasks to see their logs.

Open Kafka UI at http://localhost:8000 to see messages accumulating in the `rappel_conso` topic after `kafka_data_stream` completes.

**Step 9 — Query results**
```bash
docker compose -f docker-compose-airflow.yaml exec postgres \
  psql -U airflow -d airflow \
  -c "SELECT COUNT(*) FROM rappel_conso_table;"
```
```bash
docker compose -f docker-compose-airflow.yaml exec postgres \
  psql -U airflow -d airflow \
  -c "SELECT reference_fiche, date_de_publication, categorie_de_produit FROM rappel_conso_table LIMIT 10;"
```

**Step 10 — Shut down**
```bash
docker compose -f docker-compose-airflow.yaml down
docker compose -f docker-compose.yml down
```
To also delete all stored data (volumes):
```bash
docker compose -f docker-compose-airflow.yaml down -v
docker compose -f docker-compose.yml down -v
```

---

## 20. Monitoring and Observability

### Airflow Web UI (port 8080)

The Airflow UI is the primary operational dashboard. Key views:

**DAG list view** — shows all DAGs, their schedules, last run status, and enable/disable toggle.

**Grid view (formerly Tree view)** — shows a matrix of task runs across time, where each cell is colored green (success), red (failure), yellow (running), or gray (not started). This view makes it easy to identify patterns of failure across multiple runs.

**Graph view** — visualizes the DAG's task dependency graph, showing the three tasks and their `>>` connections. Useful for understanding the pipeline structure at a glance.

**Task logs** — clicking any task run cell opens the full task log, which includes all Python print/logging output, exception tracebacks, and the Spark container's stdout output (forwarded by the DockerOperator).

**Task instance details** — shows the exact start time, end time, duration, hostname, and return code for each task execution.

### Kafka UI (port 8000)

**Topics view** — lists all topics in the Kafka cluster, showing the message count, replication factor, and partition count. After `kafka_data_stream` runs, the `rappel_conso` topic should show a message count equal to the number of records ingested.

**Messages view** — allows browsing and searching individual messages in the topic. Messages are displayed as JSON, making it easy to verify that the transformation logic produced the expected output.

**Consumer groups view** — shows any active consumer groups, their topic subscriptions, and their current offset positions. After the Spark job completes, its consumer group should show the offset position equal to the total message count, confirming all messages were consumed.

**Cluster overview** — shows broker health, controller status, and cluster metadata.

### Container logs

```bash
docker compose -f docker-compose.yml logs kafka
docker compose -f docker-compose-airflow.yaml logs airflow-scheduler
docker compose -f docker-compose-airflow.yaml logs airflow-webserver
```

### What there is no monitoring for (current gap)

There is no Prometheus/Grafana stack, no alerting on task failures, no data quality metrics (like record counts per run or schema validation failure rates), and no Spark UI (which would normally be accessible on port 4040 but is not exposed in this containerized setup). These are acknowledged limitations, not oversights in the documentation.

---

## 21. Known Limitations and Honest Constraints

**Single-node Spark.** The Spark job runs in `local[*]` mode inside a single Docker container. There is no Spark cluster — no driver/executor separation, no YARN or Kubernetes resource manager. This limits parallelism to the number of CPU cores available in the container and makes the Spark deployment unsuitable for truly large datasets. For the scale of RappelConso data (tens of thousands of records per day), local mode is entirely sufficient.

**Shared PostgreSQL instance.** Airflow's metadata and the pipeline's output data share the same PostgreSQL container, the same database, and the same user. In production, separating these concerns is standard practice to prevent Airflow's internal metadata writes from interfering with application data and to simplify backup and recovery policies.

**No Spark cluster persistence for packages.** Because the Spark container is ephemeral (started fresh by each DockerOperator invocation), the Maven packages (`org.postgresql` and `org.apache.spark:spark-sql-kafka`) are downloaded anew on every run. This adds startup time and requires outbound internet access from the Spark container. A production setup would pre-download the JARs and include them in the Spark image.

**Minimal Kafka retention configuration.** The Kafka topic's retention policy uses default settings. For production use, explicit retention time and size limits should be configured to prevent unbounded disk growth.

**No test suite.** There are no unit tests for the transformation functions, no integration tests for the API client, and no contract tests for the Kafka message schema. This is the most significant gap for anyone considering extending this project.

**No schema evolution handling.** If the RappelConso API adds, removes, or renames columns, the pipeline will fail silently (missing columns will be null) or loudly (unexpected columns will be dropped). A schema registry or explicit schema validation step at ingestion would address this.

**Local execution only.** The pipeline is designed for local development and demonstration. Deploying it to a cloud environment would require changes to the Docker socket proxy (or switching to a managed container service), the PostgreSQL connection (managed database), and possibly the Airflow executor (CeleryExecutor or KubernetesExecutor for distributed task execution).

---

## 22. Design Decisions and Architectural Trade-offs

### Why Kafka instead of writing directly from Python to PostgreSQL

Introducing Kafka adds complexity and an additional service to deploy. The benefit is decoupling: the Python producer and the Spark consumer are independent processes that communicate through a durable message queue. If the Spark job fails, the messages remain in Kafka and can be reprocessed without re-fetching from the API. If the producer runs faster than the consumer can process, Kafka buffers the excess. This decoupling is a core property of stream-based architectures that this project demonstrates.

### Why Spark instead of writing directly from Python to PostgreSQL

Spark's role in this project is specifically to demonstrate Structured Streaming capabilities and distributed join-based deduplication. A pure Python approach using psycopg2 could achieve the same functional result with less complexity. The deliberate choice of Spark is pedagogically motivated: it anchors the project in the Big Data ecosystem and demonstrates schema parsing, streaming DataFrames, and distributed anti-joins. For the data volumes involved, Spark is technically overpowered but architecturally illustrative.

### Why trigger(once=True) instead of continuous streaming

Continuous streaming would mean running the Spark job as a perpetually active process, which doesn't fit naturally into Airflow's task execution model. Airflow tasks are expected to start, run to completion, and exit. `trigger(once=True)` makes Spark behave like a batch job from Airflow's perspective while retaining all the Structured Streaming machinery internally. It is the idiomatic pattern for Spark jobs managed by Airflow.

### Why left anti-join instead of INSERT ON CONFLICT

`INSERT ... ON CONFLICT DO NOTHING` is a PostgreSQL-native approach to idempotent inserts. The left anti-join approach uses Spark's distributed processing to filter records before any write happens, reducing the number of JDBC round trips. For small datasets, the difference is negligible. For larger datasets, distributing the deduplication logic in Spark rather than the database server scales better. The anti-join approach also keeps the database agnostic — the same logic would work with any JDBC-compatible database.

### Why socat proxy instead of mounting /var/run/docker.sock

Mounting the Docker socket directly into a container grants that container essentially root access to the host — it can start, stop, and modify any container on the host system. The socat proxy approach limits the exposure: the Airflow container can only reach the Docker daemon through the TCP proxy, and the proxy container itself only has the Docker socket mounted read-write (a necessary minimum). While not a complete security solution, it follows the principle of least privilege more closely than the direct socket mount.

### Why all-text schema

Storing all 25 columns as TEXT avoids type-coercion failures at write time. The RappelConso dataset has data quality inconsistencies: numeric-looking fields sometimes contain text descriptions, date fields sometimes contain narrative strings, and reference identifiers sometimes contain non-numeric characters. Using TEXT universally prevents the pipeline from failing due to unexpected values in any column. Type conversion can be applied in SQL views or downstream analytics queries where the consuming application can handle and report conversion failures gracefully.

---

## 23. Troubleshooting Guide

### Airflow UI unreachable at localhost:8080

Cause: Airflow webserver not yet started or still initializing.
Fix: Run `docker compose -f docker-compose-airflow.yaml logs airflow-init` and wait for it to show completion. Then `docker compose -f docker-compose-airflow.yaml logs airflow-webserver` to check for startup errors.

### DAG does not appear in the Airflow UI

Cause: The DAG file is not being found by Airflow.
Checks:
- Verify `./airflow_resources/dags` is mounted to `/opt/airflow/dags` in the compose file
- Ensure there are no Python syntax errors in `dag_kafka_spark.py` (run `python airflow_resources/dags/dag_kafka_spark.py` locally to check)
- Check `docker compose -f docker-compose-airflow.yaml logs airflow-scheduler` for import errors

### kafka_data_stream task fails with "NoBrokersAvailable"

Cause: Kafka is not reachable from the Airflow container.
Checks:
- Verify the infrastructure stack is running: `docker compose -f docker-compose.yml ps`
- Verify both stacks are on the same Docker network: both should reference `airflow-kafka`
- Kafka may still be starting up — wait 30-60 seconds and retry

### pyspark_consumer task fails with "Cannot connect to Docker daemon"

Cause: The docker-proxy service is not running or not reachable.
Checks:
- `docker ps | grep socat` should show the docker-proxy container
- Verify the DockerOperator's `docker_url` is set to `tcp://docker-proxy:2375`
- Ensure both the airflow container and docker-proxy container are on `airflow-kafka`

### pyspark_consumer task fails with "ClassNotFoundException"

Cause: Maven could not download the Spark packages, or the package version does not match the Spark version.
Checks:
- Ensure the Spark container has outbound internet access
- Verify the package versions in the `spark-submit --packages` flag match `spark:3.5.7-java17-python3`
- Check the task logs for the specific class that was not found

### No rows inserted into rappel_conso_table

Cause: One of several possible issues.
Checks:
- Open Kafka UI and verify the `rappel_conso` topic has messages
- If the topic is empty, the producer task failed silently — check `kafka_data_stream` task logs
- If the topic has messages but the table is empty, check `pyspark_consumer` logs for JDBC write errors
- Verify `last_processed.json` is not set to a future date (which would cause the producer to find no new records)

### Pipeline appears to re-process data but inserts nothing

Cause: All fetched records already exist in the database (expected behavior for the one-day overlap).
Confirmation: Run `SELECT COUNT(*) FROM rappel_conso_table` before and after the run. If the count is the same, the anti-join filtered all records — this means no new records were published since the last run.

### Out of memory errors during Spark job

Cause: Spark's local mode is using all available CPUs and running out of heap space.
Fix: Increase Docker's memory limit in Docker Desktop settings to at least 8 GB. If memory is constrained, set `--master local[2]` in the spark-submit command to limit parallelism to 2 cores.

---

## 24. Reproducibility Fixes Applied to This Repository

The repository was forked from an earlier version that had several problems preventing it from running end-to-end. These are the six main fixes:

**Fix 1 — DAG mount path.** The original compose file mounted `./dags` (a non-existent directory) rather than `./airflow_resources/dags`. Fixed by correcting the volume mount path.

**Fix 2 — Missing Spark image build.** The DockerOperator referenced `rappel-conso/spark:latest` but the image was never automatically built. Fixed by adding a `spark-app` service to `docker-compose.yml` with the correct build context and image tag.

**Fix 3 — Inconsistent PostgreSQL credentials.** The Python connection code and the Docker Compose environment variables used different database names, users, and passwords. Fixed by centralizing all credentials in `.env` and reading them consistently via environment variables in `constants.py`.

**Fix 4 — Hardcoded last_processed path.** The state file path was hardcoded as a relative path that resolved differently inside and outside Docker. Fixed by making the path configurable via `LAST_PROCESSED_PATH` and providing the containerized path as the default.

**Fix 5 — Manual table creation requirement.** The original instructions required running a setup script manually before the first DAG run. Fixed by making `create_table.py` the first task in the DAG, so schema creation is always automatic and idempotent.

**Fix 6 — Missing DockerOperator provider.** The Airflow image did not include `apache-airflow-providers-docker`, which is required for `DockerOperator`. Fixed by adding the package to `requirements-airflow.txt` and installing it in the custom Airflow Dockerfile.

---

## 25. Future Improvements

The following improvements would move this pipeline from a local demonstration to a production-ready system:

**Automated test suite.** Unit tests for every function in `transformations.py` (covering edge cases like null inputs, text with only one accent, dates in unusual positions), integration tests for the API client (using mock responses), and end-to-end smoke tests using a local Kafka instance. A Pytest-based test suite with fixtures for common test data would be the natural starting point.

**Schema validation at ingestion.** Validate incoming API responses against a known schema before publishing to Kafka. Tools like Pydantic or Marshmallow could enforce field types and required fields, and failed validation could route records to a dead-letter queue for manual inspection rather than silently dropping them.

**Persistent Spark package cache.** Pre-download the Maven JARs and include them in the Spark Docker image (`COPY jars/postgresql.jar /opt/spark/jars/`) rather than downloading at runtime. This eliminates network dependency during Spark startup and significantly reduces job startup time.

**Separate Airflow and application databases.** Use one PostgreSQL instance for Airflow metadata and a separate instance (or schema) for `rappel_conso_table`. This follows operational best practice for clarity, backup policy separation, and access control.

**Spark checkpoints on a persistent volume.** Mount `/tmp/spark-checkpoints` to a Docker named volume so that Spark's offset tracking survives container restarts. Currently, the ephemeral container loses checkpoints on every invocation, but `trigger(once=True)` mitigates this because the job always reads from "earliest" and relies on the anti-join for deduplication rather than offset-based exactly-once delivery.

**Downstream analytics layer.** Add a Jupyter notebook or Metabase dashboard that reads from `rappel_conso_table` and produces visualizations: recall counts by category over time, top recalled brands, geographic distribution of recalls, most common recall motives. This would give the pipeline a visible consumer and demonstrate end-to-end value.

**Schema evolution handling.** Add a schema registry (Confluent Schema Registry or AWS Glue Schema Registry) to version and validate the JSON schema of Kafka messages. The Spark consumer could then deserialize messages using the registered schema rather than inferring from field names, making it robust against future API changes.

**Alerting and monitoring.** Integrate Airflow's email alerting for task failures (`email_on_failure=True` with SMTP configuration) and add Prometheus metrics via the `StatsD` exporter to expose Airflow and Kafka metrics to a Grafana dashboard.

**CI/CD pipeline.** Add a GitHub Actions workflow that runs the test suite on every pull request, builds and validates the Docker images, and publishes them to a container registry on merge to main.

---

## 26. Conclusion

This project demonstrates a complete, correct, and reproducible implementation of a modern data engineering pipeline. From a real government REST API to a queryable PostgreSQL table, every stage of the pipeline is covered: incremental state management, paginated API ingestion with rollover logic, two-layer deduplication, text normalization and semantic column restructuring, event-driven transport through Kafka, distributed processing with Spark Structured Streaming, and daily orchestration with Airflow — all running locally in Docker Compose with no external cloud dependencies.

The design reflects the real concerns of production data engineering: not just "does it work once" but "does it work correctly on every subsequent run, in the presence of API inconsistencies, container restarts, and overlapping data windows." The two-layer deduplication strategy, the one-day safety buffer, the idempotent schema creation, and the self-contained Docker network all address these concerns explicitly.

Apache Spark is the central component — the engine that takes a raw event stream from Kafka, applies a structured schema, performs a distributed join against existing data, and writes clean records to the database. The surrounding ecosystem (Kafka, Airflow, PostgreSQL, Docker) is not decoration but a practical demonstration of how Spark fits into a real pipeline architecture, bounded by a message queue on one side and a relational database on the other, coordinated by an orchestration layer that enforces execution order and provides operational visibility.

The project is explicitly scoped to local development. It trades production concerns like high availability, cluster-level Spark, and cloud infrastructure for clarity, reproducibility, and pedagogical completeness. Every design decision is documented here with its rationale, and the known limitations are stated honestly. The combination makes this project both a functional data engineering system and a transparent record of the choices that shaped it.

---

---

## 27. Data Quality Layer — Pydantic Validation and Dead-Letter Queue

### The problem this solves

Before this layer was added, the pipeline had a silent failure mode. If the RappelConso API returned a record with a null or missing `reference_fiche`, that record would be published to Kafka, consumed by Spark, and written to PostgreSQL — where the primary key constraint would raise an exception, rolling back the entire JDBC batch. Every subsequent record in that batch would be lost. Alternatively, if the API changed the format of `date_de_publication` from `YYYY-MM-DD` to something else, `update_last_processed_file()` would crash with an unhandled `ValueError` from `strptime`, failing the entire `kafka_data_stream` task without updating the state file, causing the next day's run to re-fetch the same data.

The data quality layer catches both classes of failure before a single invalid record reaches Kafka, and routes invalid records to a dedicated dead-letter topic where they can be inspected, corrected, and replayed without affecting the main pipeline.

### Architecture of the validation layer

```
transform_row(raw_record)
        |
        v
validate_record(transformed)
        |
    ----+----
    |       |
  VALID   INVALID
    |       |
    v       v
KAFKA_TOPIC  KAFKA_DLQ_TOPIC
rappel_conso  rappel_conso_dlq
    |
    v
Spark consumer
    |
    v
PostgreSQL
```

Valid records flow through the existing pipeline unchanged. Invalid records are wrapped in a structured DLQ envelope and published to `rappel_conso_dlq` instead of being silently dropped or crashing the pipeline.

### File: src/kafka_client/schema.py

This new file defines the `RappelConsoRecord` Pydantic model. It uses Pydantic v1 syntax (`pydantic>=1.10.0,<2.0.0`) for compatibility with Apache Airflow 2.7.3, which depends on Pydantic v1 and enforces that constraint in its own package metadata.

**The model defines all 25 DB_FIELDS as typed fields:**

- `reference_fiche: str` — the only truly required field, with no default. Pydantic will raise a `ValidationError` if this field is missing from the record dictionary.
- All other 24 fields are `Optional[str] = None`. They accept a string, `None`, or absence from the dictionary (which defaults to `None`).

**Three validators enforce format contracts:**

`reference_fiche_non_empty` — checks that the primary key is not an empty string or whitespace-only string after stripping. An empty `reference_fiche` passes Python's type check (`""` is a `str`) but would insert an empty primary key into PostgreSQL, corrupting the uniqueness invariant.

`publication_date_format` — checks that `date_de_publication`, when present, matches the regex `^\d{4}-\d{2}-\d{2}$`. This is the exact format expected by `datetime.strptime(..., "%Y-%m-%d")` in `update_last_processed_file()`. A mismatch here would otherwise cause the state file update to fail after records have already been published to Kafka, leaving the pipeline in an inconsistent state where Kafka has messages but the state file was not advanced.

`commercialisation_date_format` — checks that the two parsed commercialization date fields, when present, match `^\d{2}/\d{2}/\d{4}$` (the DD/MM/YYYY output of `separate_commercialisation_dates()`). A mismatch indicates the regex in the transformation layer produced unexpected output.

**The `Config` class sets `extra = "ignore"`**, meaning that if the API response adds new fields in the future that `normalize_columns()` does not filter out, those extra fields are silently ignored rather than raising a validation error. This is the appropriate default: new API fields should be detected as a new API schema version (and handled by updating the model), but they should not break the existing pipeline for all other records.

### validate_record() function in kafka_stream_data.py

```python
def validate_record(record: dict) -> Tuple[bool, list]:
    try:
        RappelConsoRecord(**record)
        return True, []
    except ValidationError as exc:
        return False, exc.errors()
```

`exc.errors()` returns a list of dictionaries, one per validation failure. Each dict contains:
- `loc`: tuple of field names indicating where the error occurred
- `msg`: human-readable error message
- `type`: Pydantic error type string (e.g., `"value_error"`, `"type_error.none.not_allowed"`)

This structured error output is what gets stored in the DLQ message, making it possible to query the DLQ topic in Kafka UI and immediately understand which field failed and why.

### Dead-letter queue message structure

Every invalid record published to `rappel_conso_dlq` has this envelope structure:

```json
{
  "original_record": {
    "reference_fiche": "",
    "date_de_publication": "2024-03-15",
    "...": "..."
  },
  "validation_errors": [
    {
      "loc": ["reference_fiche"],
      "msg": "reference_fiche is the primary key and must be a non-empty string",
      "type": "value_error"
    }
  ],
  "failed_at": "2024-03-16T08:32:11.445Z",
  "source_topic": "rappel_conso"
}
```

`original_record` is the full transformed record so that engineers can see exactly what was ingested from the API. `validation_errors` is the Pydantic error list. `failed_at` is a UTC ISO-8601 timestamp for correlation with Airflow logs. `source_topic` records which topic the record was intended for, which is useful if multiple pipelines share the same DLQ topic in future.

### The DLQ topic: rappel_conso_dlq

Kafka auto-creates topics when a producer first sends to them (auto-create is enabled by default in the `soldevelo/kafka` image). The `rappel_conso_dlq` topic is therefore created automatically on the first pipeline run that encounters a validation failure. No manual Kafka administration is required.

The DLQ topic name is configurable via the `KAFKA_DLQ_TOPIC` environment variable (defaulting to `rappel_conso_dlq`), which is now defined in `.env.example`, `constants.py`, and the `docker-compose.yml` `spark-app` environment block.

### Logging behaviour

For every record routed to the DLQ, a `logging.warning()` call is emitted with the `reference_fiche` (or `<unknown>` if that field itself is missing), the target DLQ topic, and the full error list. This means invalid records are visible in the Airflow task logs without requiring the operator to separately inspect the Kafka DLQ topic.

At the end of every `stream()` call, a `logging.info()` summary line reports the total valid and invalid counts and their respective topics:

```
Stream complete — valid: 847 -> rappel_conso | invalid: 2 -> rappel_conso_dlq
```

This gives operators an at-a-glance signal of the data quality of each ingestion run.

### Pydantic version constraint

`pydantic>=1.10.0,<2.0.0` is now explicit in both `requirements.txt` and `airflow_resources/requirements-airflow.txt`. Pydantic v2 introduced breaking changes to the validator API (`@validator` became `@field_validator`, `class Config` became `model_config`, and error format changed). Since Airflow 2.7.3 has a hard `<2.0.0` upper bound on Pydantic in its own dependency resolution, using v1 syntax avoids installation conflicts. The schema is written entirely in v1-compatible syntax so it will install and run correctly inside the Airflow container.

---

## 28. Previously Undocumented Implementation Details

### The role of __init__.py files

The repository contains `__init__.py` files in four directories: `src/`, `src/kafka_client/`, `scripts/`, and `airflow_resources/`. These files, even when empty, serve a critical function: they declare the directory as a Python package, enabling relative and absolute imports.

Without `src/__init__.py`, the import `from src.constants import KAFKA_TOPIC` in `kafka_stream_data.py` would raise a `ModuleNotFoundError`. Without `src/kafka_client/__init__.py`, the relative import `from .transformations import transform_row` inside `kafka_stream_data.py` would fail. Without `scripts/__init__.py`, the Airflow DAG's `from scripts.create_table import create_table` would fail at import time, preventing the DAG from loading.

The Airflow compose file volume-mounts `./scripts` into `/opt/airflow/dags/scripts` and `./src` into `/opt/airflow/dags/src`, placing both packages on the Python path that Airflow uses to resolve DAG imports. The `__init__.py` files make this resolution work.

### The config/ and logs/ directories

Both `config/` and `logs/` are empty directories in the repository (tracked only via a `.gitkeep` file in some projects, or simply present as empty directories). Their presence is load-bearing:

`logs/` is volume-mounted into the Airflow containers at `/opt/airflow/logs`. Airflow writes task execution logs — every line of stdout and stderr from each task run — into this directory, organized by DAG ID, run ID, and task ID. Without this directory, the volume mount would fail silently on some Docker versions, and Airflow log collection would break, making debugging impossible.

`config/` is volume-mounted into the Airflow containers at `/opt/airflow/config`. Airflow looks here for a custom `airflow.cfg` file that overrides defaults. The directory is currently empty (using built-in Airflow defaults), but the mount is declared so that operators can drop a custom config file without modifying the compose file.

### Kafka KRaft environment variables explained

The `soldevelo/kafka` image uses the Bitnami Kafka environment variable naming convention (`KAFKA_CFG_*`). The six KRaft-specific variables and their exact purposes:

| Variable | Value | Purpose |
|---|---|---|
| `KAFKA_CFG_NODE_ID` | `0` | Unique integer identifier for this broker/controller node within the cluster. In a multi-node cluster, each node has a distinct ID. |
| `KAFKA_CFG_PROCESS_ROLES` | `controller,broker` | Combined mode: this single node acts as both a KRaft controller (manages cluster metadata) and a broker (handles produce/consume). Requires no separate controller nodes. |
| `KAFKA_CFG_LISTENERS` | `PLAINTEXT://:9092,CONTROLLER://:9093,EXTERNAL://:9094` | The three listener sockets the broker opens: internal (9092), controller consensus (9093), and external/host (9094). |
| `KAFKA_CFG_ADVERTISED_LISTENERS` | `PLAINTEXT://kafka:9092,EXTERNAL://localhost:9094` | The addresses that clients are told to connect to. Containers use `kafka:9092` (DNS resolves within Docker); host-machine clients use `localhost:9094` (mapped by Docker port publishing). The `CONTROLLER` listener is intentionally absent — it is internal-only and never advertised to clients. |
| `KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP` | `CONTROLLER:PLAINTEXT,EXTERNAL:PLAINTEXT,PLAINTEXT:PLAINTEXT` | Maps each listener name to its security protocol. All three use `PLAINTEXT` (no TLS, no authentication), appropriate for a local development environment. |
| `KAFKA_CFG_CONTROLLER_QUORUM_VOTERS` | `0@kafka:9093` | Defines the KRaft quorum: voter ID `0` at address `kafka:9093`. In a single-node cluster this is just the node itself. In a multi-node cluster this list would include all controller-role nodes. |
| `KAFKA_CFG_CONTROLLER_LISTENER_NAMES` | `CONTROLLER` | Tells Kafka which listener name to use for inter-controller Raft communication. Must match one of the names in `KAFKA_CFG_LISTENERS`. |

### JDBC write properties in Spark

The `POSTGRES_PROPERTIES` dictionary in `constants.py`:

```python
POSTGRES_PROPERTIES = {
    "user": POSTGRES_USER,
    "password": POSTGRES_PASSWORD,
    "driver": "org.postgresql.Driver",
}
```

This dictionary is passed as the `properties` argument to both Spark's `spark.read.jdbc()` (when reading the existing table for the anti-join) and `DataFrame.write.jdbc()` (when writing new rows). The three keys have specific meanings in the Spark JDBC connector:

`user` and `password` — the PostgreSQL credentials. Spark passes these as connection properties to the JDBC driver. They are read from environment variables that are injected into the Spark container by the Airflow DockerOperator.

`driver` — fully qualified class name of the JDBC driver to load. Spark uses this to locate the driver JAR downloaded via `spark.jars.packages`. Without this explicit class name, Spark would attempt to auto-detect the driver from the JDBC URL prefix, which can fail if multiple JDBC drivers are on the classpath.

The `POSTGRES_URL` is the JDBC connection string in the format `jdbc:postgresql://{host}:{port}/{db}`. Spark uses this URL together with `POSTGRES_PROPERTIES` to establish the connection. Inside the Spark container, `APP_POSTGRES_HOST` resolves to `postgres` (the Docker service name), which is reachable because the Spark container is attached to the `airflow-kafka` network.

### Error handling edge cases in the producer

**API timeout.** `requests.get(url, timeout=30)` raises `requests.exceptions.Timeout` if the API does not respond within 30 seconds. This exception is not caught inside `get_all_data()` and propagates up to the Airflow task, which marks it as failed and retries once (per the DAG's `retries=1` setting). The state file is not updated on a failed run, so the next retry re-fetches from the same date window.

**API HTTP errors.** `response.raise_for_status()` converts 4xx and 5xx HTTP responses into `requests.exceptions.HTTPError`. Same propagation and retry behaviour as timeout.

**Malformed API JSON.** If the API returns a 200 response with non-JSON body, `response.json()` raises `json.JSONDecodeError`. This also propagates to Airflow for retry.

**Corrupt last_processed.json.** If the file exists but contains invalid JSON (e.g., it was partially written during a prior crash), `json.load()` raises `json.JSONDecodeError`. This is now caught explicitly: a warning is logged, and the function falls back to `DEFAULT_LAST_PROCESSED`. The pipeline re-fetches the full history on the next run; the Spark anti-join prevents duplicates.

**Kafka flush failure.** `producer.flush()` blocks until all buffered messages are delivered or the configured delivery timeout is reached. If Kafka becomes unavailable between `producer.send()` calls and `producer.flush()`, some messages may not be delivered. The state file was already updated before the send loop, so the next run will not re-fetch those records. This is a known gap: in a production system, the state file update would happen after confirmed delivery, not before.

---

*Documentation authored for the data-engineering-project repository. All configuration values, version numbers, file paths, and behavioral descriptions are derived from the actual source code as it exists in the repository.*
