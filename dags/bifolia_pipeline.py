from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'data_engineer',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    'bifolia_daily_ingestion',
    default_args=default_args,
    description='Pipeline ETL quotidien pour la météo et les satellites GEE',
    schedule_interval='0 0 * * *', 
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['bifolia', 'meteo', 'satellite'],
) as dag:

    task_meteo = BashOperator(
        task_id='ingest_meteo_data',
        bash_command='cd /opt/airflow/dags && python ingest_meteo.py',
    )

    task_gee = BashOperator(
        task_id='ingest_gee_data',
        bash_command='cd /opt/airflow/dags && python ingest_gee.py',
    )

    task_meteo >> task_gee