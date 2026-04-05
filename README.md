# End-to-End Data Engineering Pipeline with Kafka, Spark, Airflow, and PostgreSQL

This repository implements a local end-to-end streaming data pipeline around the French public `RappelConso` product-recall dataset. It ingests recall records from a government API, publishes them to Kafka, processes them with Spark Structured Streaming, stores the final rows in PostgreSQL, and orchestrates the flow with Airflow.

## Quick Summary

1. A Python producer pulls recall data from the `RappelConso` API.
2. The producer normalizes and publishes those records to a Kafka topic.
3. Spark reads the Kafka topic and writes deduplicated rows into PostgreSQL.
4. Airflow coordinates table creation, ingestion, and Spark execution.
5. Docker Compose runs the local infrastructure.

## Main Tool

If you need to present the repository around one Big Data tool for an academic submission, use **Apache Spark** as the primary tool. Kafka, Airflow, PostgreSQL, and Docker are supporting technologies in the surrounding ecosystem.

## Full Documentation

The complete technical guide is available in [PROJECT_GUIDE.md](PROJECT_GUIDE.md).

It covers:

- project purpose
- dataset details
- repository structure
- architecture and data flow
- setup and run instructions
- commands to execute
- troubleshooting and extension ideas

## Architecture

![chatuml-diagram](https://github.com/HamzaG737/data-engineering-project/assets/71135893/ce92b731-038a-4d9c-9722-f97a6ba51153)
