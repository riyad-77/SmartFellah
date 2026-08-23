from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import requests
import pandas as pd
from sqlalchemy import create_engine, text

# --- CONFIGURATION ---
API_KEY = "356ec6dc80c0140dd14d9009cf7ce143"
# ⚠️ Ajuste le host si Airflow n'arrive pas à joindre la DB (ex: 'postgres' ou 'host.docker.internal')
DB_URL = "postgresql://admin:secretpassword@host.docker.internal:5432/bifolia_db"

def fetch_and_store_forecasts():
    engine = create_engine(DB_URL)
    
    # 1. Obtenir TOUTES les communes avec leurs coordonnées GPS
    with engine.connect() as conn:
        communes = conn.execute(text("""
            SELECT id, latitude, longitude, nom_commune 
            FROM communes_maroc 
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        """)).fetchall()
        
    all_forecasts = []
    
    # 2. Boucler sur chaque commune pour interroger OpenWeather
    for commune in communes:
        commune_id, lat, lon, nom = commune[0], commune[1], commune[2], commune[3]
        
        # Endpoint 5 day / 3 hour forecast
        url = f"http://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={API_KEY}&units=metric"
        response = requests.get(url)
        
        if response.status_code != 200:
            print(f"⚠️ Erreur API pour {nom} (ID: {commune_id})")
            continue
            
        data = response.json()
        
        # 3. Agréger les blocs de 3h en journées entières
        daily_data = {}
        for item in data.get('list', []):
            date_str = item['dt_txt'].split(' ')[0] # Extrait "YYYY-MM-DD"
            
            temp = item['main']['temp']
            t_min = item['main']['temp_min']
            t_max = item['main']['temp_max']
            hum = item['main']['humidity']
            # La pluie peut être absente du JSON s'il ne pleut pas
            rain = item.get('rain', {}).get('3h', 0.0) 
            
            if date_str not in daily_data:
                daily_data[date_str] = {'temps': [], 't_mins': [], 't_maxs': [], 'hums': [], 'rain_total': 0.0}
                
            daily_data[date_str]['temps'].append(temp)
            daily_data[date_str]['t_mins'].append(t_min)
            daily_data[date_str]['t_maxs'].append(t_max)
            daily_data[date_str]['hums'].append(hum)
            daily_data[date_str]['rain_total'] += rain

        # 4. Garder uniquement les 3 prochains jours (J+1, J+2, J+3)
        today_str = datetime.now().strftime('%Y-%m-%d')
        # On filtre les dates futures et on prend les 3 premières
        sorted_dates = sorted([d for d in daily_data.keys() if d > today_str])[:3]
        
        for d in sorted_dates:
            info = daily_data[d]
            all_forecasts.append({
                'commune_id': commune_id,
                'date_prevision': d,
                'temp_moyenne': round(sum(info['temps'])/len(info['temps']), 2),
                'temp_min': min(info['t_mins']),
                'temp_max': max(info['t_maxs']),
                'humidite_moyenne': round(sum(info['hums'])/len(info['hums']), 2),
                'precipitations_mm': round(info['rain_total'], 2)
            })
            
    if not all_forecasts:
        print("🛑 Aucune prévision calculée.")
        return

    # 5. Injection (UPSERT) dans PostgreSQL
    df_forecast = pd.DataFrame(all_forecasts)
    
    with engine.begin() as conn:
        for _, row in df_forecast.iterrows():
            upsert_stmt = text("""
                INSERT INTO previsions_meteo 
                (commune_id, date_prevision, temp_moyenne, temp_min, temp_max, humidite_moyenne, precipitations_mm)
                VALUES (:commune_id, :date_prevision, :temp_moyenne, :temp_min, :temp_max, :humidite_moyenne, :precipitations_mm)
                ON CONFLICT (commune_id, date_prevision) 
                DO UPDATE SET 
                    temp_moyenne = EXCLUDED.temp_moyenne,
                    temp_min = EXCLUDED.temp_min,
                    temp_max = EXCLUDED.temp_max,
                    humidite_moyenne = EXCLUDED.humidite_moyenne,
                    precipitations_mm = EXCLUDED.precipitations_mm,
                    date_mise_a_jour = CURRENT_TIMESTAMP;
            """)
            conn.execute(upsert_stmt, row.to_dict())

    print(f"✅ {len(all_forecasts)} prévisions météorologiques insérées ou mises à jour avec succès !")


# --- DÉFINITION DU DAG ---
with DAG(
    'ingest_openweather_forecasts', 
    start_date=datetime(2026, 8, 20), 
    schedule_interval='0 2 * * *', # S'exécute à 02:00 du matin tous les jours
    catchup=False,
    tags=['météo', 'prévisions', 'api']
) as dag:

    task_fetch = PythonOperator(
        task_id='fetch_and_store_forecasts',
        python_callable=fetch_and_store_forecasts
    )