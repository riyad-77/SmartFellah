from sqlalchemy import create_engine, text
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:secretpassword@localhost:5432/bifolia_db")
engine = create_engine(DATABASE_URL)

def predict_disease_risk(field_id, culture):
    culture_nom = culture.lower().strip() 
    
    with engine.connect() as conn:
        # 1. On récupère la météo du jour
        query_meteo = text("""
            SELECT temp_moyenne, precipitations_mm, humidite_moyenne, ndvi
            FROM donnees_meteo m
            LEFT JOIN indices_satellites s ON m.parcelle_id = s.parcelle_id AND m.date_mesure = s.date_capture
            WHERE m.parcelle_id = :field_id
            ORDER BY m.date_mesure DESC LIMIT 1
        """)
        meteo = conn.execute(query_meteo, {"field_id": field_id}).fetchone()

        if not meteo:
            return {"risks": {"erreur": "Données météo introuvables"}, "water": "UNKNOWN", "yield": "UNKNOWN", "recos": []}

        temp_moy = float(meteo.temp_moyenne)
        humidite = float(meteo.humidite_moyenne) if meteo.humidite_moyenne else 50.0
        precip = float(meteo.precipitations_mm)

        # 2. LA REQUÊTE SYSTÈME EXPERT : On croise la météo avec les seuils des maladies !
        query_expert = text("""
            SELECT m.nom_maladie, t.nom_traitement
            FROM maladies m
            JOIN culture_maladie_details cmd ON m.id = cmd.maladie_id
            JOIN cultures c ON c.id = cmd.culture_id
            JOIN traitements t ON cmd.traitement_specifique_id = t.id
            WHERE TRIM(LOWER(c.nom_culture)) = :culture
              AND :temp_actuelle BETWEEN m.temp_min_declenchement AND m.temp_max_declenchement
              AND :humidite_actuelle >= m.humidite_min_declenchement
        """)
        
        alertes = conn.execute(query_expert, {
            "culture": culture_nom, 
            "temp_actuelle": temp_moy, 
            "humidite_actuelle": humidite
        }).fetchall()

    # 3. Formatage de la réponse
    risks_calcules = {}
    recos = []
    
    for alerte in alertes:
        nom_mal = alerte.nom_maladie.capitalize()
        traitement = alerte.nom_traitement
        
        if nom_mal not in risks_calcules:
            risks_calcules[nom_mal] = 0.85 
            recos.append(f"Alerte {nom_mal} : Appliquer {traitement}.")
        else:
            recos.append(f"Alternative pour {nom_mal} : {traitement}.")

    if not alertes:
        recos.append("Météo favorable, aucun risque de maladie majeur détecté.")

    return {
        "risks": risks_calcules if risks_calcules else {"Toutes maladies": 0.10},
        "water": "HIGH" if precip == 0 and temp_moy > 28 else "NORMAL",
        "yield": "GOOD",
        "recos": recos
    }

# --- TEST ---
if __name__ == "__main__":
    print(predict_disease_risk(12, "tomate"))