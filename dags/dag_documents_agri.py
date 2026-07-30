from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime

with DAG(
    'bifolia_document_ingestion',
    description='Pipeline NLP pour extraire et ingérer les fiches techniques PDF',
    schedule_interval=None, 
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['bifolia', 'nlp', 'documents'],
) as dag:

    # On utilise le bon chemin : /opt/airflow/project au lieu de /opt/airflow/dags
    
    task_extract = BashOperator(
        task_id='extract_pdf_to_json',
        bash_command='cd /opt/airflow/project && python extract_agri_to_json.py',
    )

    task_consolidate = BashOperator(
        task_id='consolidate_json',
        bash_command='cd /opt/airflow/project && python Consolidation.py',
    )

    task_ingest = BashOperator(
        task_id='ingest_to_postgis',
        bash_command='cd /opt/airflow/project && python ingestion_smartfellah.py',
    )

    task_extract >> task_consolidate >> task_ingest