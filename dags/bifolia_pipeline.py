from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

# Configuration de base du DAG
default_args = {
    'owner': 'data_engineer',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# Définition du DAG (S'exécute tous les jours à minuit)
with DAG(
    'bifolia_daily_ingestion',
    default_args=default_args,
    description='Pipeline ETL quotidien pour la météo et les satellites GEE',
    schedule_interval='0 0 * * *', # Syntaxe CRON : Tous les jours à minuit
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['bifolia', 'meteo', 'satellite'],
) as dag:

    # Tâche 1 : Lancer l'ingestion Météo
    task_meteo = BashOperator(
        task_id='ingest_meteo_data',
        # On exécute le script Python qui se trouve dans le même dossier
        bash_command='python /opt/airflow/dags/ingest_meteo.py',
    )

    # Tâche 2 : Lancer l'ingestion GEE
    task_gee = BashOperator(
        task_id='ingest_gee_data',
        bash_command='python /opt/airflow/dags/ingest_gee.py',
    )

    # L'ordre d'exécution (Les deux peuvent tourner en parallèle si on veut, 
    # mais ici on les met à la suite pour ne pas surcharger la base)
    task_meteo >> task_gee