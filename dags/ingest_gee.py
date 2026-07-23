import ee
import pandas as pd
import time
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy import text

# ==========================================
# 1. INITIALISATION & CONNEXION
# ==========================================
try:
    ee.Initialize(project='bifolia-engine-415208')
except Exception as e:
    print(f"Erreur d'initialisation GEE : {e}")

DB_URL = "postgresql://admin:secretpassword@host.docker.internal:5432/bifolia_db"
engine = create_engine(DB_URL)

# ==========================================
# 2. DÉFINITION DES FONCTIONS
# ==========================================
def mask_s2_clouds(image):
    """ Masque les nuages sur Sentinel-2 et conserve la date. """
    qa = image.select('QA60')
    cloudBitMask = 1 << 10
    cirrusBitMask = 1 << 11
    mask = qa.bitwiseAnd(cloudBitMask).eq(0).And(qa.bitwiseAnd(cirrusBitMask).eq(0))
    return image.updateMask(mask).divide(10000).copyProperties(image, ['system:time_start'])

def fetch_gee_indices(lat, lon, start_date, end_date):
    """ Extrait les séries temporelles NDVI et NDWI via Google Earth Engine. """
    point = ee.Geometry.Point([lon, lat])
    
    collection = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
                  .filterBounds(point)
                  .filterDate(start_date, end_date)
                  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
                  .map(mask_s2_clouds))
    
    def calculate_indices(image):
        ndvi = image.normalizedDifference(['B8', 'B4']).rename('ndvi')
        ndwi = image.normalizedDifference(['B3', 'B8']).rename('ndwi')
        date = image.date().format('YYYY-MM-dd')
        return image.addBands([ndvi, ndwi]).set({'date': date})
    
    indices_collection = collection.map(calculate_indices)
    
    def extract_point_data(image):
        mean_dict = image.select(['ndvi', 'ndwi']).reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=point,
            scale=10,
            maxPixels=1e9
        )
        return ee.Feature(None, {
            'date': image.get('date'),
            'ndvi': mean_dict.get('ndvi'),
            'ndwi': mean_dict.get('ndwi')
        })
    
    features = ee.FeatureCollection(indices_collection.map(extract_point_data)).getInfo()
    
    data = []
    for f in features['features']:
        props = f['properties']
        if props.get('ndvi') is not None and props.get('ndwi') is not None:
            data.append({
                'date_capture': props['date'],
                'ndvi': props['ndvi'],
                'ndwi': props['ndwi']
            })
            
    return pd.DataFrame(data)

def save_sat_to_database(df, parcelle_id):
    """ Sauvegarde idempotente avec fusion des captures du même jour """
    if df.empty:
        return
    
    # 1. LE FIX : On fait la moyenne des indices si le satellite est passé 2 fois le même jour
    df = df.groupby('date_capture', as_index=False)[['ndvi', 'ndwi']].mean()
    
    # 2. Préparation pour la base de données
    df['parcelle_id'] = parcelle_id
    min_date = df['date_capture'].min()
    max_date = df['date_capture'].max()
    
    # 3. Nettoyage des anciennes données sur la période
    with engine.begin() as conn:
        query = text(f"""
            DELETE FROM indices_satellites 
            WHERE parcelle_id = {parcelle_id} 
            AND date_capture >= '{min_date}' 
            AND date_capture <= '{max_date}'
        """)
        conn.execute(query)
            
    # 4. Insertion propre et sans aucun doublon
    df.to_sql('indices_satellites', engine, if_exists='append', index=False)

# ==========================================
# 3. EXÉCUTION DU PIPELINE PRINCIPAL (L'Orchestration)
# ==========================================
if __name__ == "__main__":
    
    print("Chargement du référentiel des parcelles (zones agricoles)...")
    try:
        # CORRECTION : On lit la table 'parcelles'
        df_parcelles = pd.read_sql("SELECT * FROM parcelles", engine)
    except Exception as e:
        print(f"Erreur de lecture de la base (Vérifie ton mot de passe !) : {e}")
        exit()

    # --- LA GESTION DYNAMIQUE DES DATES ---
    DATE_DEBUT = "2024-01-01"
    DATE_FIN = datetime.today().strftime('%Y-%m-%d') # Récupère la date d'aujourd'hui automatiquement !
    
    print(f"Période d'extraction : du {DATE_DEBUT} au {DATE_FIN}")
    print(f"Début de l'ingestion satellite pour {len(df_parcelles)} parcelles.\n")

    # CORRECTION : On boucle sur df_parcelles
    for index, row in df_parcelles.iterrows():
        parcelle_id = row['id']
        nom_parcelle = row['nom_parcelle']
        lat = row['latitude']
        lon = row['longitude']
        
        print(f"--- Traitement [{index + 1}/{len(df_parcelles)}] : {nom_parcelle} ---")
        
        try:
            df_sat = fetch_gee_indices(lat, lon, DATE_DEBUT, DATE_FIN)
            
            if not df_sat.empty:
                save_sat_to_database(df_sat, parcelle_id)
                print(f" -> {len(df_sat)} captures synchronisées avec succès !")
            else:
                print(" -> Aucune image claire trouvée sur cette période.")
                
        except Exception as e:
            print(f" -> Erreur lors du traitement : {e}")
        
        # Pause obligatoire pour Google Earth Engine
        time.sleep(2)

    print("\nIngestion GEE terminée avec succès ! Prêt pour Airflow.")