import pandas as pd
import openmeteo_requests
import requests_cache
from sqlalchemy import create_engine, text
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import requests

# 1. Connexion DB
DB_URL = "postgresql://admin:secretpassword@host.docker.internal:5432/bifolia_db"
engine = create_engine(DB_URL)

# 2. Setup Session avec Retry intégré
retry_strategy = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session = requests_cache.CachedSession('.cache', expire_after=3600)
session.mount("https://", adapter)

openmeteo = openmeteo_requests.Client(session=session)

print("Chargement des parcelles (zones agricoles)...")
# CORRECTION : On lit la table 'parcelles'
df_parcelles = pd.read_sql("SELECT * FROM parcelles", engine)

# 3. Boucle d'ingestion nationale
for _, parcelle in df_parcelles.iterrows():
    print(f"Extraction météo pour : {parcelle['nom_parcelle']}...")
    
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": parcelle['latitude'],
        "longitude": parcelle['longitude'],
        "start_date": "2024-01-01",
        "end_date": datetime.today().strftime('%Y-%m-%d'),
        "daily": ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean", "precipitation_sum", "relative_humidity_2m_mean"]
    }
    
    try:
        responses = openmeteo.weather_api(url, params=params)
        daily = responses[0].Daily()
        
        # Création des dates de référence
        dates = pd.date_range(
            start=pd.to_datetime(daily.Time(), unit="s", utc=True),
            end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=daily.Interval()),
            inclusive="left"
        ).tz_localize(None) # Conversion en naive pour correspondre à SQL
        
        n_days = len(dates)

        # Construction du DataFrame avec reindex pour garantir la longueur
        data_dict = {
            'parcelle_id': [parcelle['id']] * n_days,
            'date_mesure': dates,
            'temp_max': pd.Series(daily.Variables(0).ValuesAsNumpy()).reindex(range(n_days)),
            'temp_min': pd.Series(daily.Variables(1).ValuesAsNumpy()).reindex(range(n_days)),
            'temp_moyenne': pd.Series(daily.Variables(2).ValuesAsNumpy()).reindex(range(n_days)),
            'precipitations_mm': pd.Series(daily.Variables(3).ValuesAsNumpy()).reindex(range(n_days)),
            'humidite_moyenne': pd.Series(daily.Variables(4).ValuesAsNumpy()).reindex(range(n_days))
        }
        
        df = pd.DataFrame(data_dict).dropna(subset=['temp_max', 'temp_min'])

        # IDEMPOTENCE : Suppression des données existantes pour cette parcelle avant insertion
        with engine.begin() as conn:
            conn.execute(text(f"DELETE FROM donnees_meteo WHERE parcelle_id = {parcelle['id']}"))
        
        # Insertion
        df.to_sql('donnees_meteo', engine, if_exists='append', index=False)
        print(f" -> {len(df)} lignes météo insérées.")
        
    except Exception as e:
        print(f" -> Erreur lors du traitement de {parcelle['nom_parcelle']} : {e}")

print("Ingestion météo terminée avec succès !")