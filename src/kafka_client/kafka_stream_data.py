from src.constants import (
    URL_API,
    PATH_LAST_PROCESSED,
    DEFAULT_LAST_PROCESSED,
    MAX_LIMIT,
    MAX_OFFSET,
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_BOOTSTRAP_SERVERS_LOCAL,
    KAFKA_TOPIC,
)

from .transformations import transform_row

import kafka.errors
import json
import datetime
import requests
from kafka import KafkaProducer
from typing import List
import logging
from pathlib import Path

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO, force=True)


def get_latest_timestamp():
    """
    Gets the latest timestamp from the last_processed.json file
    """
    path_last_processed = Path(PATH_LAST_PROCESSED)
    if not path_last_processed.exists():
        return DEFAULT_LAST_PROCESSED

    with path_last_processed.open("r", encoding="utf-8") as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            return DEFAULT_LAST_PROCESSED

    return data.get("last_processed", DEFAULT_LAST_PROCESSED)


def update_last_processed_file(data: List[dict]):
    """
    Updates the last_processed.json file with the latest timestamp. Since the comparison is strict
    on the field date_de_publication, we set the new last_processed day to the latest timestamp minus one day.
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
        # The sum of offset + limit API parameter must be lower than 10000.
        if n_results + MAX_LIMIT >= MAX_OFFSET:
            # If it is the case, change the last_processed_timestamp parameter to the date_de_publication
            # of the last retrieved result, minus one day. In case of duplicates, they will be filtered
            # in the deduplicate_data function. We also reset n_results (or the offset parameter) to 0.
            last_timestamp = current_results[-1]["date_de_publication"]
            timestamp_as_date = datetime.datetime.strptime(last_timestamp, "%Y-%m-%d")
            timestamp_as_date = timestamp_as_date - datetime.timedelta(days=1)
            last_processed_timestamp = timestamp_as_date.strftime("%Y-%m-%d")
            n_results = 0

    logging.info(f"Got {len(full_data)} results from the API")

    return full_data


def deduplicate_data(data: List[dict]) -> List[dict]:
    return list({v["reference_fiche"]: v for v in data}.values())


def query_data() -> List[dict]:
    """
    Queries the data from the API
    """
    last_processed = get_latest_timestamp()
    full_data = get_all_data(last_processed)
    full_data = deduplicate_data(full_data)
    if full_data:
        update_last_processed_file(full_data)
    return full_data


def process_data(row):
    """
    Processes the data from the API
    """
    return transform_row(row)


def create_kafka_producer():
    """
    Creates the Kafka producer object
    """
    try:
        producer = KafkaProducer(bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS])
    except kafka.errors.NoBrokersAvailable:
        logging.info(
            "We assume that we are running locally, so we use localhost instead of kafka and the external "
            "port 9094"
        )
        producer = KafkaProducer(bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS_LOCAL])

    return producer


def stream():
    """
    Writes the API data to Kafka topic rappel_conso
    """
    producer = create_kafka_producer()
    results = query_data()
    kafka_data_full = map(process_data, results)
    for kafka_data in kafka_data_full:
        producer.send(KAFKA_TOPIC, json.dumps(kafka_data).encode("utf-8"))
    producer.flush()
    producer.close()


if __name__ == "__main__":
    stream()
