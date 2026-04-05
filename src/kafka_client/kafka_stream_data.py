from src.constants import (
    URL_API,
    PATH_LAST_PROCESSED,
    DEFAULT_LAST_PROCESSED,
    MAX_LIMIT,
    MAX_OFFSET,
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_BOOTSTRAP_SERVERS_LOCAL,
    KAFKA_TOPIC,
    KAFKA_DLQ_TOPIC,
)

from .transformations import transform_row
from .schema import RappelConsoRecord

import kafka.errors
import json
import datetime
import requests
from kafka import KafkaProducer
from pydantic import ValidationError
from typing import List, Tuple
import logging
from pathlib import Path

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO, force=True)


def get_latest_timestamp():
    """
    Gets the latest timestamp from the last_processed.json file.
    Returns DEFAULT_LAST_PROCESSED if the file is missing or malformed.
    """
    path_last_processed = Path(PATH_LAST_PROCESSED)
    if not path_last_processed.exists():
        return DEFAULT_LAST_PROCESSED

    with path_last_processed.open("r", encoding="utf-8") as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            logging.warning(
                "last_processed.json contains invalid JSON — falling back to "
                f"DEFAULT_LAST_PROCESSED ({DEFAULT_LAST_PROCESSED})."
            )
            return DEFAULT_LAST_PROCESSED

    return data.get("last_processed", DEFAULT_LAST_PROCESSED)


def update_last_processed_file(data: List[dict]):
    """
    Updates the last_processed.json file with the latest timestamp.
    Sets the new last_processed day to the latest timestamp minus one day
    so that records published on the boundary date are re-queried on the
    next run and de-duplicated by the Spark anti-join.
    """
    publication_dates_as_timestamps = [
        datetime.datetime.strptime(row["date_de_publication"], "%Y-%m-%d")
        for row in data
    ]
    last_processed = max(publication_dates_as_timestamps) - datetime.timedelta(days=1)
    last_processed_as_string = last_processed.strftime("%Y-%m-%d")
    path_last_processed = Path(PATH_LAST_PROCESSED)
    path_last_processed.parent.mkdir(parents=True, exist_ok=True)
    with path_last_processed.open("w", encoding="utf-8") as file:
        json.dump({"last_processed": last_processed_as_string}, file)


def get_all_data(last_processed_timestamp: datetime.datetime) -> List[dict]:
    n_results = 0
    full_data = []
    while True:
        # The publication date must be greater than the last processed timestamp and the offset (n_results)
        # corresponds to the number of results already processed.
        url = URL_API.format(last_processed_timestamp, n_results)
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        current_results = data["results"]
        full_data.extend(current_results)
        n_results += len(current_results)
        if len(current_results) < MAX_LIMIT:
            break
        # The sum of offset + limit must stay below 10 000 (API cap).
        # When the cap is about to be hit, roll forward the date window and
        # reset the offset so we continue from where the API left off.
        if n_results + MAX_LIMIT >= MAX_OFFSET:
            last_timestamp = current_results[-1]["date_de_publication"]
            timestamp_as_date = datetime.datetime.strptime(last_timestamp, "%Y-%m-%d")
            timestamp_as_date = timestamp_as_date - datetime.timedelta(days=1)
            last_processed_timestamp = timestamp_as_date.strftime("%Y-%m-%d")
            n_results = 0

    logging.info(f"Got {len(full_data)} results from the API")
    return full_data


def deduplicate_data(data: List[dict]) -> List[dict]:
    """Remove within-batch duplicates keyed on reference_fiche."""
    return list({v["reference_fiche"]: v for v in data}.values())


def query_data() -> List[dict]:
    """Fetch, deduplicate, and update state. Returns raw API rows."""
    last_processed = get_latest_timestamp()
    full_data = get_all_data(last_processed)
    full_data = deduplicate_data(full_data)
    if full_data:
        update_last_processed_file(full_data)
    return full_data


def process_data(row: dict) -> dict:
    """Apply all column transformations to a single raw API row."""
    return transform_row(row)


def validate_record(record: dict) -> Tuple[bool, list]:
    """
    Validate a transformed record against the RappelConsoRecord Pydantic schema.

    Returns
    -------
    (True, [])           — record is valid; safe to publish to main topic.
    (False, [errors])    — record is invalid; should be routed to DLQ.
                           errors is the list of Pydantic ValidationError
                           detail dicts (field, message, type).
    """
    try:
        RappelConsoRecord(**record)
        return True, []
    except ValidationError as exc:
        return False, exc.errors()


def create_kafka_producer() -> KafkaProducer:
    """
    Create and return a KafkaProducer.

    Tries the internal bootstrap address first (container-to-container).
    Falls back to the external localhost address when running outside Docker.
    """
    try:
        producer = KafkaProducer(bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS])
    except kafka.errors.NoBrokersAvailable:
        logging.info(
            "Internal Kafka address unreachable — assuming local execution, "
            f"falling back to {KAFKA_BOOTSTRAP_SERVERS_LOCAL}."
        )
        producer = KafkaProducer(bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS_LOCAL])
    return producer


def stream():
    """
    Full ingestion pipeline:

    1. Fetch new records from the RappelConso API (incremental).
    2. Deduplicate within the batch.
    3. Transform each record.
    4. Validate each transformed record with Pydantic:
       - Valid   -> publish to KAFKA_TOPIC       (rappel_conso)
       - Invalid -> publish to KAFKA_DLQ_TOPIC   (rappel_conso_dlq)
                    with original record + validation errors + timestamp.
    5. Flush and close the producer.
    """
    producer = create_kafka_producer()
    results = query_data()

    valid_count = 0
    invalid_count = 0

    for raw_record in results:
        transformed = process_data(raw_record)
        is_valid, errors = validate_record(transformed)

        if is_valid:
            producer.send(KAFKA_TOPIC, json.dumps(transformed).encode("utf-8"))
            valid_count += 1
        else:
            dlq_message = {
                "original_record": transformed,
                "validation_errors": errors,
                "failed_at": datetime.datetime.utcnow().isoformat(),
                "source_topic": KAFKA_TOPIC,
            }
            producer.send(KAFKA_DLQ_TOPIC, json.dumps(dlq_message).encode("utf-8"))
            invalid_count += 1
            logging.warning(
                f"Record {transformed.get('reference_fiche', '<unknown>')} failed "
                f"validation and was routed to DLQ ({KAFKA_DLQ_TOPIC}). "
                f"Errors: {errors}"
            )

    producer.flush()
    producer.close()

    logging.info(
        f"Stream complete — valid: {valid_count} -> {KAFKA_TOPIC} | "
        f"invalid: {invalid_count} -> {KAFKA_DLQ_TOPIC}"
    )


if __name__ == "__main__":
    stream()
