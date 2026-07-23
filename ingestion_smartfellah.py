import json
import os
import psycopg2
import re
from process_ollama import extraire_seuils_maladie  

# --- CONFIGURATION BASE DE DONNÉES ---
DB_CONFIG = {
    "dbname": "bifolia_db", 
    "user": "admin", 
    "password": "secretpassword", 
    "host": "localhost"
}

def vider_base_de_donnees(cur):
    """Vide toutes les tables de référence et de liaison pour repartir à zéro."""
    print("🧹 Nettoyage de la base de données en cours...")
    cur.execute("""
        TRUNCATE TABLE recommandation, culture_maladie_details, cultures, maladies, traitements, 
                       ref_exigences_sol, ref_besoins_hydriques, ref_temp_optimale 
        RESTART IDENTITY CASCADE;
    """)
    print("✅ Base de données vidée avec succès.\n")

def normaliser_texte(texte):
    """Nettoyage de base pour les textes et troncage de sécurité à 490 caractères."""
    if not texte:
        return "inconnu"
    texte = str(texte).strip()
    if texte.lower() not in ['nan', 'none', 'null', '']:
        return texte[:490]
    return "inconnu"

def get_id(cur, table, col_nom, valeur):
    """Récupère ou insère une valeur dans une table de référence et retourne son ID."""
    query = f"""
        INSERT INTO {table} ({col_nom}) VALUES (%s) 
        ON CONFLICT ({col_nom}) DO UPDATE SET {col_nom} = EXCLUDED.{col_nom} 
        RETURNING id;
    """
    cur.execute(query, (valeur,))
    return cur.fetchone()[0]

def safe_float(valeur, valeur_par_defaut):
    """Tente de convertir une valeur simple en float."""
    if valeur is None:
        return valeur_par_defaut
    try:
        return float(valeur)
    except (ValueError, TypeError):
        return valeur_par_defaut

def extraire_temperature_reelle(texte):
    """
    NOUVEAU : Extrait les valeurs numériques d'un texte complexe (ex: '-16°C à -24°C (dormants)').
    Filtre les valeurs aberrantes (ex: '700 heures') pour ne garder que les températures plausibles.
    """
    if not texte:
        return None, None
        
    # Cherche tous les nombres (négatifs et décimaux inclus)
    nombres = re.findall(r'-?\d+\.?\d*', str(texte))
    
    if nombres:
        # On convertit en float et on filtre (une température agricole dépasse rarement -50 et +60)
        # Cela permet d'éliminer automatiquement le "700" de "700 heures de froid"
        valeurs_temp = [float(n) for n in nombres if -50 <= float(n) <= 60]
        
        if valeurs_temp:
            return min(valeurs_temp), max(valeurs_temp)
            
    return None, None

def pipeline_ingestion(source_dir):
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        vider_base_de_donnees(cur)

        fichiers = [f for f in os.listdir(source_dir) if f.endswith(".json")]
        print(f"🚀 Début de l'ingestion de {len(fichiers)} cultures depuis '{source_dir}'...")

        for file in fichiers:
            with open(os.path.join(source_dir, file), 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            nom_culture = normaliser_texte(data.get("culture"))
            if nom_culture == "inconnu": 
                continue
                
            print(f"-> Traitement de : {nom_culture.capitalize()}")
            
            # --- 1. GESTION DES RÉFÉRENCES ---
            sol_id = get_id(cur, "ref_exigences_sol", "libelle", normaliser_texte(data.get("exigences_sol")))
            eau_id = get_id(cur, "ref_besoins_hydriques", "libelle", normaliser_texte(data.get("besoins_hydriques")))
            
            # --- CORRECTION DE L'EXTRACTION TEXTUELLE (REGEX) ---
            temp_dict = data.get("temp_optimale", {})
            
            # On extrait les plages possibles depuis le texte
            min_vals = extraire_temperature_reelle(temp_dict.get("temp_min"))
            max_vals = extraire_temperature_reelle(temp_dict.get("temp_max"))
            
            # On consolide pour avoir la vraie limite basse et haute
            t_min_opt = min_vals[0] if min_vals[0] is not None else None
            t_max_opt = max_vals[1] if max_vals[1] is not None else (max_vals[0] if max_vals[0] is not None else None)
            
            cur.execute("""
                SELECT id FROM ref_temp_optimale 
                WHERE temp_min IS NOT DISTINCT FROM %s AND temp_max IS NOT DISTINCT FROM %s
            """, (t_min_opt, t_max_opt))
            row_temp = cur.fetchone()
            
            if row_temp:
                temp_opt_id = row_temp[0]
            else:
                cur.execute("""
                    INSERT INTO ref_temp_optimale (temp_min, temp_max) 
                    VALUES (%s, %s) RETURNING id;
                """, (t_min_opt, t_max_opt))
                temp_opt_id = cur.fetchone()[0]
            
            # --- 2. INSERTION DE LA CULTURE ---
            cur.execute("""
                INSERT INTO cultures (nom_culture, exigence_sol_id, besoin_hydrique_id, temp_optimale_id) 
                VALUES (%s, %s, %s, %s) 
                ON CONFLICT (nom_culture) DO NOTHING 
                RETURNING id;
            """, (nom_culture.lower(), sol_id, eau_id, temp_opt_id))
            
            row = cur.fetchone()
            if row:
                culture_id = row[0]
            else:
                cur.execute("SELECT id FROM cultures WHERE nom_culture = %s", (nom_culture.lower(),))
                culture_id = cur.fetchone()[0]
            
            # --- 3. INSERTION DES MALADIES ---
            for m_det in data.get('maladies_details', []):
                nom_maladie = normaliser_texte(m_det.get('nom_maladie'))
                if nom_maladie == "inconnu" or not nom_maladie: 
                    continue
                
                causes_liste = m_det.get('causes', [])
                seuils = extraire_seuils_maladie(causes_liste)
                
                t_min = safe_float(seuils.get('temp_min'), -50.0)
                t_max = safe_float(seuils.get('temp_max'), 60.0)
                h_min = safe_float(seuils.get('humidite_min'), 0.0)
                
                cur.execute("""
                    INSERT INTO maladies (nom_maladie, temp_min_declenchement, temp_max_declenchement, humidite_min_declenchement)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (nom_maladie) DO UPDATE 
                    SET temp_min_declenchement = EXCLUDED.temp_min_declenchement,
                        temp_max_declenchement = EXCLUDED.temp_max_declenchement,
                        humidite_min_declenchement = EXCLUDED.humidite_min_declenchement
                    RETURNING id;
                """, (nom_maladie.lower(), t_min, t_max, h_min))
                maladie_id = cur.fetchone()[0]
                
                traitements = m_det.get('traitements_specifiques', [])
                if not traitements:
                    traitements = ["aucun"]
                    
                for t in traitements:
                    nom_traitement = normaliser_texte(t)
                    traitement_id = get_id(cur, "traitements", "nom_traitement", nom_traitement.lower())
                    
                    cur.execute("""
                        INSERT INTO culture_maladie_details (culture_id, maladie_id, traitement_specifique_id) 
                        VALUES (%s, %s, %s)
                    """, (culture_id, maladie_id, traitement_id))

            # --- 4. INSERTION DES RECOMMANDATIONS ---
            for rec in data.get("recommandations", []):
                description = rec.get("description", "").strip()
                if description and description != "inconnu":
                    status = normaliser_texte(rec.get("status", "à faire"))
                    categorie = normaliser_texte(rec.get("categorie", "optionnel"))
                    
                    cur.execute("""
                        INSERT INTO recommandation (description, status, categorie, culture_id)
                        VALUES (%s, %s, %s, %s)
                    """, (description, status, categorie, culture_id))

        conn.commit()
        print("\n🎉 Pipeline terminé avec succès ! La base de données Bifolia est prête et formatée.")
        
    except Exception as e:
        print(f"\n❌ Erreur fatale lors de l'ingestion : {e}")
        if conn: conn.rollback()
    finally:
        if 'cur' in locals() and cur: cur.close()
        if conn: conn.close()

if __name__ == "__main__":
    # Assure-toi que c'est bien le dossier avec tes JSON propres
    pipeline_ingestion("FT_Clean")