import json
import os
import sys
import psycopg2
import re
import unicodedata

try:
    from deep_translator import GoogleTranslator
except ImportError:
    print("❌ Erreur : pip install deep-translator")
    sys.exit(1)

traducteur = GoogleTranslator(source='auto', target='fr')

DB_CONFIG = {
    "dbname": "bifolia_db",
    "user": "admin",
    "password": "secretpassword",
    "host": "localhost",
}

def traduire_texte(texte):
    if not texte or not isinstance(texte, str): return texte
    try:
        return traducteur.translate(texte).title() if len(texte) > 2 else texte
    except Exception: return texte

def normaliser_culture(nom_brut):
    if not nom_brut: return "inconnu"
    nom = str(nom_brut).lower().strip()
    nom = unicodedata.normalize('NFKD', nom).encode('ASCII', 'ignore').decode('utf-8')
    nom = nom.replace("'", " ").replace("’", " ") 
    nom = re.sub(r'[\-_]', ' ', nom)
    nom = re.sub(r'[\(\)\.]', '', nom)
    nom = re.sub(r'^(le |la |les |l )', '', nom)
    nom = re.sub(r'\s+', ' ', nom).strip()

    intrus = ["poisson", "poissonnier", "inconnue", "culture inconnue", "culture x", "helm", "hormone", "edesse", "hlemm", "a graminees", "achlamydes", "almellya", "arabie", "arabricotier", "arbecette", "arbre a feuilles persistantes", "cerealiculture", "culture marocaine", "ensilage", "legumineuses alimentaires", "orage", "pente cerise", "pompe de terre", "riz du figue", "shaghaat el luzz", "viticulture", "viticulture marocaine", "ziza", "poulet", "rouille brune du ble", "arabin mais traduis en francais", "culture du semis direct", "cereales inconnue"]
    if nom in intrus: return None

    mapping = {
        "abricot": "abricotier", "abricot prunus armeniaca": "abricotier", "arbre de prunus armeniaca": "abricotier", "abricotier prunus armeniaca": "abricotier", "abricotier prunus armeniaca": "abricotier",
        "شجرة اللوز": "amandier", "amandier": "amandier", "amygdalus communis": "amandier", "louz": "amandier",
        "cognassier cydonia vulgaris": "cognassier", "cognassier cydonia vulgaris et neflier du japon": "cognassier", "cognassier cydonia vulgaris et neflier du japon eriobotrya japonica": "cognassier",
        "avocatier persea americana": "avocatier",
        "noyer commun juglans regia": "noyer commun", "noyer": "noyer commun",
        "figue": "figuier", "ficus carica": "figuier", 
        "framboise": "framboisier",
        "pomier": "pommier", "pomme malus domestica": "pommier", "pomme": "pommier",
        "grenade": "grenadier", 
        "palm tree": "palmier dattier", "nkhil temr": "palmier dattier", "nkhil el temmar": "palmier dattier", "nakhil temmar": "palmier dattier", "nkhil tamr": "palmier dattier", "palmier": "palmier dattier",
        "prunus armeniaca": "prunier",
        "rosa damascena": "rose",
        "peche": "pecher", "pecher prunus persica": "pecher", "prunus persica": "pecher",
        "raisin de table": "vigne", "sultanine": "vigne",
        "capparis": "caprier", 
        "mentha verte": "menthe verte", "mentha viridis ou mentha spicata var viridis": "menthe verte", "mentha spicata var viridis": "menthe verte", "mentha viridis": "menthe verte", "mentha verte mentha viridis ou mentha spicat": "menthe verte","mentha verte mentha viridis ou mentha spicata var viridis": "menthe verte",
        "saffron": "safran", "safraniere": "safran", "crocus sativus l": "safran",
        "organe" : "oregano",
        "stevia rebaudiana": "stevia",
        "absinthe artemisia absinthium": "absinthe", "artemisia absinthium": "absinthe", "herbe sainte": "absinthe", "absinthe artemisia absinthium": "absinthe",
        "cereales d automne": "cereale", "cereales": "cereale", "cereales de printemps": "cereale", "cereales inconnue": "cereale", "graminees": "cereale", "graminee": "cereale",
        "culture de ble": "ble", "ble dur": "ble", "ble tendre": "ble", "ble dur et ble tendre": "ble",
        "riz vert": "riz", 
        "arabe": "arabica", "arabique": "arabica", "araabiyat": "arabica", "culture arabe": "arabica",
        "arachidonne": "arachide", "arachis hypogaea": "arachide", "arachid": "arachide",
        "vicia sativa": "vesce", "vicia villosa": "vesce",
        "agrume": "agrumes", "citron": "agrumes", 
        "bananier": "banane",
        "culture de mais": "mais", "zea mays": "mais", "mais ensilage": "mais", "culture de mais ensilage en goutte a goutte d": "mais", "culture de mais ensilage en goutte a goutte dans les sables de larache": "mais",
        "culture de soja": "soja",
        "betterave a sucre monogermes": "betterave a sucre", "betterave a sucre monogerme": "betterave a sucre", 
        "piment rouge niora": "piment rouge", "niora": "piment rouge",
        "fragaria vulgaris": "fraisier", "fraisier fragaria vulgaris": "fraisier", "frasier fragaria vulgaris": "fraisier",
        "rapeseed": "colza",
        "epinard et estragon": "epinard",
        "patate douce et le navet en maroc": "patate douce",
        "tomate de primeurs": "tomate", "tomate sous serre": "tomate"
    }
    
    if any("\u0600" <= c <= "\u06FF" for c in nom): nom = traduire_texte(nom).lower().strip()
    return mapping.get(nom, nom)

def preparer_base_de_donnees(cur):
    print("🧹 Création des tables manquantes et nettoyage de la base de données...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS culture_communes_recommandees (
            id SERIAL PRIMARY KEY,
            culture_id INTEGER REFERENCES cultures(id) ON DELETE CASCADE,
            nom_commune VARCHAR(255),
            UNIQUE (culture_id, nom_commune)
        );
    """)
    cur.execute("""
        TRUNCATE TABLE recommandation, culture_communes_recommandees, culture_maladie_details, cultures, maladies, traitements,
                       ref_exigences_sol, ref_besoins_hydriques, ref_temp_optimale
        RESTART IDENTITY CASCADE;
    """)
    print("✅ Base de données prête.\n")

def normaliser_texte(texte, limit=490):
    if not texte: return "inconnu"
    texte = str(texte).strip()
    return texte[:limit] if texte.lower() not in ['nan', 'none', 'null', ''] else "inconnu"

def get_id(cur, table, col_nom, valeur):
    query = f"""
        INSERT INTO {table} ({col_nom}) VALUES (%s)
        ON CONFLICT ({col_nom}) DO UPDATE SET {col_nom} = EXCLUDED.{col_nom}
        RETURNING id;
    """
    cur.execute(query, (valeur,))
    return cur.fetchone()[0]

def safe_float(valeur, defaut):
    if valeur is None: return defaut
    try: return float(valeur)
    except: return defaut

def pipeline_ingestion(clean_dir):
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        preparer_base_de_donnees(cur)

        fichiers_clean = [f for f in os.listdir(clean_dir) if f.endswith(".json")]
        print(f"🚀 Début de l'ingestion de {len(fichiers_clean)} cultures depuis '{clean_dir}'...")

        for file in fichiers_clean:
            with open(os.path.join(clean_dir, file), 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            nom_brut = normaliser_texte(data.get("culture"))
            nom_culture = normaliser_culture(nom_brut)
            if not nom_culture or nom_culture == "inconnu": continue
                
            print(f"-> Traitement de : {nom_culture.capitalize()}")
                
            sol_id = get_id(cur, "ref_exigences_sol", "libelle", normaliser_texte(data.get("exigences_sol")))
            eau_id = get_id(cur, "ref_besoins_hydriques", "libelle", normaliser_texte(data.get("besoins_hydriques")))
            
            bioclim = data.get("bioclimatologie_optimale") or {}
            t_min = safe_float(bioclim.get("temp_min"), None)
            t_max = safe_float(bioclim.get("temp_max"), None)
            
            cur.execute("SELECT id FROM ref_temp_optimale WHERE temp_min IS NOT DISTINCT FROM %s AND temp_max IS NOT DISTINCT FROM %s", (t_min, t_max))
            row_temp = cur.fetchone()
            if row_temp:
                temp_opt_id = row_temp[0]
            else:
                cur.execute("INSERT INTO ref_temp_optimale (temp_min, temp_max) VALUES (%s, %s) RETURNING id;", (t_min, t_max))
                temp_opt_id = cur.fetchone()[0]
            
            # INSERT CULTURE
            # --- EXTRACTION ---
            indices = data.get("indices_satellitaires_requis") or {}
            
            # On remplace les valeurs par défaut par None (qui devient NULL en SQL)
            ndvi_min = safe_float(indices.get("ndvi_optimal_min"), None)
            ndvi_max = safe_float(indices.get("ndvi_optimal_max"), None)
            ndwi_min = safe_float(indices.get("ndwi_optimal_min"), None)
            ndwi_max = safe_float(indices.get("ndwi_optimal_max"), None)
            evi_min = safe_float(indices.get("evi_optimal_min"), None)
            evi_max = safe_float(indices.get("evi_optimal_max"), None)

            # --- INSERTION ---
            cur.execute("""
                INSERT INTO cultures (
                    nom_culture, exigence_sol_id, besoin_hydrique_id, temp_optimale_id, 
                    ndvi_optimal_min, ndvi_optimal_max, 
                    ndwi_optimal_min, ndwi_optimal_max, 
                    evi_optimal_min, evi_optimal_max
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) 
                ON CONFLICT (nom_culture) 
                DO UPDATE SET 
                    ndvi_optimal_min = EXCLUDED.ndvi_optimal_min,
                    ndvi_optimal_max = EXCLUDED.ndvi_optimal_max,
                    ndwi_optimal_min = EXCLUDED.ndwi_optimal_min,
                    ndwi_optimal_max = EXCLUDED.ndwi_optimal_max,
                    evi_optimal_min = EXCLUDED.evi_optimal_min,
                    evi_optimal_max = EXCLUDED.evi_optimal_max
                RETURNING id;
            """, (nom_culture.lower()[:100], sol_id, eau_id, temp_opt_id, 
                  ndvi_min, ndvi_max, ndwi_min, ndwi_max, evi_min, evi_max))
            
            row = cur.fetchone()
            culture_id = row[0] if row else cur.execute("SELECT id FROM cultures WHERE nom_culture = %s", (nom_culture.lower()[:100],)) or cur.fetchone()[0]
            
            # INSERT ZONES
            zones = data.get("zones_recommandees") or []
            for zone in zones:
                zone_propre = traduire_texte(zone).strip()
                if len(zone_propre) > 1 and not any(c in zone_propre for c in ["∏", "ô", "é°"]):
                    cur.execute("""
                        INSERT INTO culture_communes_recommandees (culture_id, nom_commune)
                        VALUES (%s, %s) ON CONFLICT (culture_id, nom_commune) DO NOTHING;
                    """, (culture_id, zone_propre.title()[:255]))

            # INSERT MALADIES
            for m_det in (data.get('maladies_details') or []):
                if not isinstance(m_det, dict): continue
                nom_maladie = normaliser_texte(m_det.get('nom_maladie'))
                if nom_maladie == "inconnu" or not nom_maladie: continue
                
                cur.execute("INSERT INTO maladies (nom_maladie, temp_min_declenchement, temp_max_declenchement, humidite_min_declenchement) VALUES (%s, -50.0, 60.0, 0.0) ON CONFLICT (nom_maladie) DO NOTHING RETURNING id;", (nom_maladie.lower(),))
                row_mal = cur.fetchone()
                maladie_id = row_mal[0] if row_mal else cur.execute("SELECT id FROM maladies WHERE nom_maladie = %s", (nom_maladie.lower(),)) or cur.fetchone()[0]
                
                for t in (m_det.get('traitements_specifiques') or ["aucun"]):
                    traitement_id = get_id(cur, "traitements", "nom_traitement", normaliser_texte(t))
                    cur.execute("INSERT INTO culture_maladie_details (culture_id, maladie_id, traitement_specifique_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING;", (culture_id, maladie_id, traitement_id))

            # INSERT RECOMMANDATIONS
            for rec in (data.get("recommandations") or []):
                if not isinstance(rec, dict): continue
                desc = normaliser_texte(rec.get("description", ""))
                if desc and desc != "inconnu":
                    cur.execute("INSERT INTO recommandation (description, status, categorie, culture_id) VALUES (%s, %s, %s, %s)", (desc, normaliser_texte(rec.get("status", "à faire"), limit=50), normaliser_texte(rec.get("categorie", "optionnel"), limit=50), culture_id))

        conn.commit()
        print("✅ Pipeline terminé ! La base Bifolia est prête (Cultures + Zones + Maladies).")
        
    except Exception as e:
        print(f"\n❌ Erreur fatale : {e}")
        if conn: conn.rollback()
        sys.exit(1)
    finally:
        if 'cur' in locals() and cur: cur.close()
        if conn: conn.close()

if __name__ == "__main__":
    pipeline_ingestion(r"C:\Users\hp\SmartFellah\FT_Clean")