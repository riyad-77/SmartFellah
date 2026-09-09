import pandas as pd
import openmeteo_requests
import requests_cache
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 1. Connexion DB
DB_URL = "postgresql://admin:secretpassword@localhost:5432/bifolia_db"
engine = create_engine(DB_URL)

# 2. Setup Session
retry_strategy = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry_strategy)
session = requests_cache.CachedSession('.cache', expire_after=3600)
session.mount("https://", adapter)
openmeteo = openmeteo_requests.Client(session=session)

print("Chargement des parcelles (zones agricoles)...")
df_parcelles = pd.read_sql("SELECT * FROM parcelles", engine)

# --- GESTION DES DATES POUR CONTOURNER LE DÉCALAGE DE L'API ---
today = datetime.today()
date_today_str = today.strftime('%Y-%m-%d')
date_archive_end_str = (today - timedelta(days=6)).strftime('%Y-%m-%d') # Archive s'arrête à J-6
date_recent_start_str = (today - timedelta(days=5)).strftime('%Y-%m-%d') # Le temps réel prend le relai à J-5

def fetch_open_meteo(url, params, parcelle_id):
    """Fonction utilitaire pour extraire les données d'une API spécifique"""
    responses = openmeteo.weather_api(url, params=params)
    daily = responses[0].Daily()
    
    dates = pd.date_range(
        start=pd.to_datetime(daily.Time(), unit="s", utc=True),
        end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
        freq=pd.Timedelta(seconds=daily.Interval()),
        inclusive="left"
    ).tz_localize(None)
    
    n_days = len(dates)
    data_dict = {
        'parcelle_id': [parcelle_id] * n_days,
        'date_mesure': dates,
        'temp_max': pd.Series(daily.Variables(0).ValuesAsNumpy()).reindex(range(n_days)),
        'temp_min': pd.Series(daily.Variables(1).ValuesAsNumpy()).reindex(range(n_days)),
        'temp_moyenne': pd.Series(daily.Variables(2).ValuesAsNumpy()).reindex(range(n_days)),
        'precipitations_mm': pd.Series(daily.Variables(3).ValuesAsNumpy()).reindex(range(n_days)),
        'humidite_moyenne': pd.Series(daily.Variables(4).ValuesAsNumpy()).reindex(range(n_days))
    }
    return pd.DataFrame(data_dict).dropna(subset=['temp_max', 'temp_min'])

# 3. Boucle d'ingestion
for _, parcelle in df_parcelles.iterrows():
    print(f"Extraction météo pour : {parcelle['nom_parcelle']}...")
    
    try:
        # A. On récupère le passé lointain (Archive API)
        params_archive = {
            "latitude": parcelle['latitude'], "longitude": parcelle['longitude'],
            "start_date": "2024-01-01", "end_date": date_archive_end_str,
            "daily": ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean", "precipitation_sum", "relative_humidity_2m_mean"]
        }
        df_archive = fetch_open_meteo("https://archive-api.open-meteo.com/v1/archive", params_archive, parcelle['id'])

        # B. On récupère les jours récents jusqu'à aujourd'hui (Forecast API)
        params_recent = {
            "latitude": parcelle['latitude'], "longitude": parcelle['longitude'],
            "start_date": date_recent_start_str, "end_date": date_today_str,
            "daily": ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean", "precipitation_sum", "relative_humidity_2m_mean"]
        }
        df_recent = fetch_open_meteo("https://api.open-meteo.com/v1/forecast", params_recent, parcelle['id'])

        # C. FUSION des deux DataFrames
        df_final = pd.concat([df_archive, df_recent], ignore_index=True)

        # IDEMPOTENCE : On vide les données de cette parcelle avant d'insérer le tout
        with engine.begin() as conn:
            conn.execute(text(f"DELETE FROM donnees_meteo WHERE parcelle_id = {parcelle['id']}"))
        
        # Insertion finale
        df_final.to_sql('donnees_meteo', engine, if_exists='append', index=False)
        print(f" -> {len(df_final)} lignes insérées avec succès (de Janvier à Aujourd'hui).")
        
    except Exception as e:
        print(f" -> Erreur lors du traitement de {parcelle['nom_parcelle']} : {e}")

print("Ingestion météo terminée avec succès !")