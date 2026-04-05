import os
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.docker.operators.docker import DockerOperator
from datetime import datetime, timedelta

from scripts.create_table import create_table
from src.kafka_client.kafka_stream_data import stream


start_date = datetime.today() - timedelta(days=1)
spark_image = os.getenv("SPARK_IMAGE", "rappel-conso/spark:latest")
spark_submit_command = os.getenv(
    "SPARK_SUBMIT_COMMAND",
    "./bin/spark-submit --master local[*] --packages "
    "org.postgresql:postgresql:42.5.4,org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0 "
    "./spark_streaming.py",
)
spark_environment = {
    "SPARK_LOCAL_HOSTNAME": os.getenv("SPARK_LOCAL_HOSTNAME", "localhost"),
    "APP_POSTGRES_HOST": os.getenv("APP_POSTGRES_HOST", "postgres"),
    "APP_POSTGRES_PORT": os.getenv("APP_POSTGRES_PORT", "5432"),
    "APP_POSTGRES_DB": os.getenv("APP_POSTGRES_DB", "airflow"),
    "APP_POSTGRES_USER": os.getenv("APP_POSTGRES_USER", "airflow"),
    "APP_POSTGRES_PASSWORD": os.getenv("APP_POSTGRES_PASSWORD", "airflow"),
    "KAFKA_BOOTSTRAP_SERVERS": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    "KAFKA_TOPIC": os.getenv("KAFKA_TOPIC", "rappel_conso"),
}


default_args = {
    "owner": "airflow",
    "start_date": start_date,
    "retries": 1,  # number of retries before failing the task
    "retry_delay": timedelta(seconds=5),
}


with DAG(
    dag_id="kafka_spark_dag",
    default_args=default_args,
    schedule_interval=timedelta(days=1),
    catchup=False,
) as dag:

    create_table_task = PythonOperator(
        task_id="create_target_table",
        python_callable=create_table,
        dag=dag,
    )

    kafka_stream_task = PythonOperator(
        task_id="kafka_data_stream",
        python_callable=stream,
        dag=dag,
    )

    spark_stream_task = DockerOperator(
        task_id="pyspark_consumer",
        image=spark_image,
        api_version="auto",
        auto_remove=True,
        command=spark_submit_command,
        docker_url="tcp://docker-proxy:2375",
        environment=spark_environment,
        mount_tmp_dir=False,
        network_mode="airflow-kafka",
        dag=dag,
    )


    create_table_task >> kafka_stream_task >> spark_stream_task
