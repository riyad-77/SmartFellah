from sqlalchemy import create_engine, text
import re
import os

# Connexion dynamique (prend en compte Docker ou le test local)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:secretpassword@localhost:5432/bifolia_db")
engine = create_engine(DATABASE_URL)

def validate_crop(field_id, culture_nom):
    # Nettoyage de l'entrée utilisateur
    culture_nom = culture_nom.lower().strip()
    
    with engine.connect() as conn:
        # 1. Étape A : Trouver la culture et récupérer son temp_optimale_id
        query_culture = text("""
            SELECT id, nom_culture, temp_optimale_id 
            FROM cultures 
            WHERE TRIM(LOWER(nom_culture)) = :culture
        """)
        culture_row = conn.execute(query_culture, {"culture": culture_nom}).fetchone()
        
        if not culture_row:
            return False, "Culture inconnue dans le référentiel."
            
        if culture_row.temp_optimale_id is None:
            return True, "Cette culture n'a pas de paramètres climatiques stricts, validation acceptée par défaut."

        # 2. Étape B : Récupérer la valeur de température minimale requise
        query_temp = text("""
            SELECT valeur 
            FROM ref_temp_optimale 
            WHERE id = :id
        """)
        temp_row = conn.execute(query_temp, {"id": culture_row.temp_optimale_id}).fetchone()
        
        if not temp_row:
             return True, "Paramètres climatiques introuvables, validation acceptée par défaut."
             
        temp_valeur_str = temp_row.valeur
        
        # Extraction intelligente du chiffre après "Min:"
        match_min = re.search(r"Min:\s*([0-9.-]+)", temp_valeur_str)
        
        if match_min:
            temp_min_culture = float(match_min.group(1))
        else:
            return True, "Température minimale inconnue pour cette culture, validation acceptée."

        # 3. Étape C : Récupérer la dernière température minimale de la parcelle
        query_meteo = text("""
            SELECT temp_min 
            FROM donnees_meteo 
            WHERE parcelle_id = :field_id 
            ORDER BY date_mesure DESC 
            LIMIT 1
        """)
        meteo_data = conn.execute(query_meteo, {"field_id": field_id}).fetchone()

        if not meteo_data:
            return False, "Données météo indisponibles pour cette parcelle."

        # 4. Étape D : Moteur de règles (Validation)
        temp_actuelle = float(meteo_data[0])

        if temp_actuelle < temp_min_culture:
            return False, f"Risque de gel ou froid : température actuelle {temp_actuelle}°C < seuil requis {temp_min_culture}°C."
        
        return True, "Culture adaptée aux conditions climatiques actuelles."

# --- ZONE DE TEST ---
if __name__ == "__main__":
    is_valid, message = validate_crop(12, "tomate")
    print(f"Validation : {is_valid} - Message : {message}")