FROM bitnami/spark:3.5.0


WORKDIR /opt/bitnami/spark

RUN pip install --no-cache-dir py4j

COPY ./src/spark_pgsql/spark_streaming.py ./spark_streaming.py
COPY ./src/constants.py ./src/constants.py
COPY ./src/__init__.py ./src/__init__.py

ENV APP_POSTGRES_HOST=postgres
ENV APP_POSTGRES_PORT=5432
ENV APP_POSTGRES_DB=airflow
ENV APP_POSTGRES_USER=airflow
ENV KAFKA_BOOTSTRAP_SERVERS=kafka:9092
ENV KAFKA_TOPIC=rappel_conso

