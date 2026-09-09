import os
import json
import psycopg2

# --- CONFIGURATION ---
BASE_DIR = r"C:\Users\hp\SmartFellah" # Ajustez si besoin
FT_CLEAN_DIR = os.path.join(BASE_DIR, "FT_Clean")

DB_CONFIG = {
    "dbname": "bifolia_db",
    "user": "admin",
    "password": "secretpassword",
    "host": "localhost",
}

def safe_float(valeur):
    if valeur is None: return None
    try: return float(valeur)
    except: return None

# --- PROCESSUS DE PATCH ---
if __name__ == "__main__":
    if not os.path.exists(FT_CLEAN_DIR):
        print(f"❌ Le dossier {FT_CLEAN_DIR} n'existe pas.")
        exit(1)

    fichiers_json = [f for f in os.listdir(FT_CLEAN_DIR) if f.endswith(".json")]
    
    if not fichiers_json:
        print("✅ Aucun fichier JSON trouvé dans FT_Clean.")
        exit(0)

    print(f"🚀 Début de l'injection des données manquantes depuis {len(fichiers_json)} fichiers (FT_Clean)...")

    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        for file in fichiers_json:
            json_path = os.path.join(FT_CLEAN_DIR, file)
            
            with open(json_path, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    print(f"  ⚠️ Fichier JSON corrompu ignoré : {file}")
                    continue

            nom_culture = data.get("culture")
            if not nom_culture or nom_culture.lower() == "inconnu":
                continue
                
            nom_culture_clean = nom_culture.lower()[:100]
            print(f"Mise à jour : {nom_culture_clean.capitalize()}...")

            try:
                # ---------------------------------------------------------
                # 1. MISE À JOUR DES INDICES SATELLITAIRES (MIN) DANS "cultures"
                # ---------------------------------------------------------
                indices = data.get("indices_satellitaires_requis") or {}
                ndvi_min = safe_float(indices.get("ndvi_optimal_min"))
                ndwi_min = safe_float(indices.get("ndwi_optimal_min"))
                evi_min = safe_float(indices.get("evi_optimal_min"))

                # On fait l'UPDATE et on récupère le temp_optimale_id pour l'étape suivante
                cur.execute("""
                    UPDATE cultures 
                    SET ndvi_optimal_min = COALESCE(%s, ndvi_optimal_min),
                        ndwi_optimal_min = COALESCE(%s, ndwi_optimal_min),
                        evi_optimal_min = COALESCE(%s, evi_optimal_min)
                    WHERE LOWER(nom_culture) = %s
                    RETURNING temp_optimale_id;
                """, (ndvi_min, ndwi_min, evi_min, nom_culture_clean))
                
                row = cur.fetchone()
                if not row:
                    print(f"  ⚠️ Culture '{nom_culture_clean}' non trouvée en base. Ignorée.")
                    continue
                
                temp_opt_id = row[0]

                # ---------------------------------------------------------
                # 2. MISE À JOUR DE L'HUMIDITÉ DANS "ref_temp_optimale"
                # ---------------------------------------------------------
                if temp_opt_id:
                    bioclim = data.get("bioclimatologie_optimale") or {}
                    hum_min = safe_float(bioclim.get("hum_min"))
                    hum_max = safe_float(bioclim.get("hum_max"))

                    cur.execute("""
                        UPDATE ref_temp_optimale 
                        SET hum_min = COALESCE(%s, hum_min),
                            hum_max = COALESCE(%s, hum_max)
                        WHERE id = %s;
                    """, (hum_min, hum_max, temp_opt_id))

                # ---------------------------------------------------------
                # 3. MISE À JOUR DES CAUSES DANS "maladies"
                # ---------------------------------------------------------
                maladies_details = data.get('maladies_details') or []
                for m_det in maladies_details:
                    if not isinstance(m_det, dict): continue
                    
                    nom_maladie = m_det.get('nom_maladie')
                    if not nom_maladie or "inconnu" in str(nom_maladie).lower(): continue
                    
                    # Nettoyage de la liste des causes pour l'insérer en texte
                    causes_liste = m_det.get('causes') or []
                    if causes_liste:
                        causes_texte = ", ".join([str(c).strip() for c in causes_liste if c])[:1000]
                        
                        cur.execute("""
                            UPDATE maladies 
                            SET causes = COALESCE(%s, causes)
                            WHERE LOWER(nom_maladie) = %s;
                        """, (causes_texte, str(nom_maladie).lower().strip()))
                
                conn.commit()
                print(f"  ✅ {nom_culture_clean.capitalize()} complétée avec succès.")

            except Exception as e:
                print(f"  ❌ Erreur DB sur {nom_culture_clean}: {e}")
                conn.rollback()
                continue

        print("\n🎉 Injection des données manquantes terminée avec succès !")
        
    except Exception as e:
        print(f"Erreur globale : {e}")
    finally:
        if 'cur' in locals() and cur: cur.close()
        if conn: conn.close()