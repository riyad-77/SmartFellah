import os
import json
import pymupdf
import psycopg2
import re
import unicodedata
import requests

# --- CONFIGURATION ---
BASE_DIR = r"C:\Users\hp\SmartFellah" 
PDF_DIR = os.path.join(BASE_DIR, "FT_Vegetal")
MAX_DIR = os.path.join(BASE_DIR, "FT_Max")

DB_CONFIG = {
    "dbname": "bifolia_db",
    "user": "admin",
    "password": "secretpassword",
    "host": "localhost",
}

OLLAMA_URL = 'http://localhost:11434/api/chat'
MODEL_NAME = 'llama3.2'

# --- NORMALISATION ---
def normaliser_culture(nom_brut):
    if not nom_brut:
        return "inconnu"
        
    nom = str(nom_brut).lower().strip()
    nom = unicodedata.normalize('NFKD', nom).encode('ASCII', 'ignore').decode('utf-8')
    nom = re.sub(r'[\-_]', ' ', nom)
    nom = re.sub(r'[\(\)\.]', '', nom)
    nom = re.sub(r'^(le |la |les |l\')', '', nom)
    nom = re.sub(r'\s+', ' ', nom).strip()

    intrus = [
        "poisson", "poissonnier", "inconnue", "culture inconnue", "culture x", 
        "helm", "hormone", "edesse", "hlemm", "a graminees", "achlamydes", 
        "almellya", "arabie", "arabricotier", "arbecette", "arbre a feuilles persistantes", 
        "cerealiculture", "culture marocaine", "ensilage", "legumineuses alimentaires", 
        "orage", "pente cerise", "pompe de terre", "riz du figue", 
        "shaghaat el luzz", "viticulture", "viticulture marocaine", "ziza",
        "poulet", "rouille brune du ble", "arabin mais traduis en francais", 
        "culture du semis direct", "cereales inconnue"
    ]
    if nom in intrus: 
        return None

    mapping = {
        "abricot": "abricotier", "abricot prunus armeniaca": "abricotier", "arbre de prunus armeniaca": "abricotier", "abricotier prunus armeniaca": "abricotier", "abricotier_prunus_armeniaca": "abricotier",
        "شجرة اللوز": "amandier", "amandier": "amandier", "amygdalus communis": "amandier", "louz": "amandier",
        "cognassier cydonia vulgaris": "cognassier", "cognassier cydonia vulgaris et neflier du japon": "cognassier", "cognassier_cydonia_vulgaris_et_neflier_du_japon_eriobotrya_japonica": "cognassier",
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
        "absinthe artemisia absinthium": "absinthe", "artemisia absinthium": "absinthe", "herbe sainte": "absinthe", "absinthe_artemisia_absinthium":"absinthe",
        "cereales d automne": "cereale", "cereales": "cereale", "cereales de printemps": "cereale", "cereales inconnue": "cereale",
        "culture de ble": "ble", "ble dur": "ble", "ble tendre": "ble", "ble dur et ble tendre": "ble",
        "riz vert": "riz", 
        "arabe": "arabica", "arabique": "arabica", "araabiyat": "arabica", "culture arabe": "arabica",
        "arachidonne": "arachide", "arachis hypogaea": "arachide", "arachid": "arachide",
        "vicia sativa": "vesce", "vicia villosa": "vesce",
        "agrume": "agrumes", "citron": "agrumes", 
        "bananier": "banane",
        "culture de mais": "mais", "zea mays": "mais", "mais ensilage": "mais", "culture de mais ensilage en goutte a goutte d": "mais", "culture_de_mais_ensilage_en_goutte_a_goutte_dans_les_sables_de_larache": "mais",
        "culture de soja": "soja",
        "betterave a sucre monogermes": "betterave a sucre", "betterave a sucre monogerme": "betterave a sucre", 
        "piment rouge niora": "piment rouge", "niora": "piment rouge",
        "fragaria vulgaris": "fraisier", "fraisier fragaria vulgaris": "fraisier", "frasier fragaria vulgaris": "fraisier",
        "rapeseed": "colza",
        "epinard et estragon": "epinard",
        "patate douce et le navet en maroc": "patate douce",
        "tomate de primeurs": "tomate", "tomate sous serre": "tomate"
    }
    return mapping.get(nom, nom)

def safe_float(valeur):
    if valeur is None: return None
    try: return float(valeur)
    except: return None

# --- EXTRACTION CIBLÉE (Via l'API HTTP d'Ollama) ---
def extraire_seulement_max(pdf_path):
    doc = pymupdf.open(pdf_path)
    full_text = "\n".join([page.get_text("text") for page in doc])
    doc.close() 

    if len(full_text.strip()) < 50:
        return None

    prompt = f"""
    Tu es un expert agronome au Maroc. Ton seul but est d'extraire le nom de la culture et ses indices satellitaires maximaux depuis ce texte.
    
    Structure JSON obligatoire EXACTE (ne renvoie rien d'autre) :
    {{
        "culture": "nom de la culture",
        "ndvi_optimal_max": "valeur numerique",
        "ndwi_optimal_max": "valeur numerique",
        "evi_optimal_max": "valeur numerique"
    }}

    Texte :
    {full_text[:5000]}
    """
    
    payload = {
        "model": MODEL_NAME,
        "format": "json",
        "stream": False,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    
    try:
        response = requests.post(OLLAMA_URL, json=payload)
        response.raise_for_status()
        return json.loads(response.json()['message']['content'])
    except Exception as e:
        print(f"Erreur API HTTP Ollama: {e}")
        return None

# --- PROCESSUS PRINCIPAL ---
if __name__ == "__main__":
    os.makedirs(MAX_DIR, exist_ok=True)
    fichiers_bruts = [f for f in os.listdir(PDF_DIR) if f.endswith(".pdf")]
    
    # 1. FILTRAGE ET DÉDUPLICATION
    # On trie par taille de nom : "52.pdf" sera analysé avant "52-unlocked.pdf"
    fichiers_bruts.sort(key=len)
    
    fichiers_a_traiter = []
    bases_traitees = set()
    
    for fichier in fichiers_bruts:
        # On supprime les " (1)", " (2)", "-unlocked" avec regex pour trouver la vraie racine
        base_name = re.sub(r'(\s*\(\d+\))?(-unlocked)?\.pdf$', '', fichier, flags=re.IGNORECASE).strip()
        
        if base_name not in bases_traitees:
            bases_traitees.add(base_name)
            fichiers_a_traiter.append(fichier)
        else:
            print(f"⏭️ Doublon ignoré : {fichier}")

    if not fichiers_a_traiter:
        print("✅ Aucun PDF valide à traiter après filtrage.")
        exit(0)

    print(f"\n🚀 Début de l'extraction des MAX pour {len(fichiers_a_traiter)} fichiers uniques...\n")

    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        for file in fichiers_a_traiter:
            print(f"Traitement : {file}...")
            pdf_path = os.path.join(PDF_DIR, file)
            json_path = os.path.join(MAX_DIR, file.replace(".pdf", "_max.json"))

            # 1. Extraction via IA
            try:
                data = extraire_seulement_max(pdf_path)
                if not data:
                    continue
                
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                    
            except Exception as e:
                print(f"  ⚠️ Erreur JSON sur {file}: {e}")
                continue

            # 2. Normalisation du nom
            nom_brut = data.get("culture", "inconnu")
            nom_culture = normaliser_culture(nom_brut)

            if not nom_culture or nom_culture == "inconnu":
                print(f"  ⏩ Culture ignorée/inconnue : {nom_brut}")
                continue

            # 3. Récupération et formatage des valeurs
            ndvi_max = safe_float(data.get("ndvi_optimal_max"))
            ndwi_max = safe_float(data.get("ndwi_optimal_max"))
            evi_max = safe_float(data.get("evi_optimal_max"))

            # 4. Mise à jour (PATCH) dans PostgreSQL
            try:
                cur.execute("""
                    UPDATE cultures 
                    SET ndvi_optimal_max = COALESCE(%s, ndvi_optimal_max),
                        ndwi_optimal_max = COALESCE(%s, ndwi_optimal_max),
                        evi_optimal_max = COALESCE(%s, evi_optimal_max)
                    WHERE LOWER(nom_culture) = %s;
                """, (ndvi_max, ndwi_max, evi_max, nom_culture[:100]))
                
                if cur.rowcount > 0:
                    print(f"  ✅ Succès DB : {nom_culture.capitalize()} mise à jour.")
                else:
                    print(f"  ⚠️ Attention : {nom_culture.capitalize()} introuvable dans la table 'cultures'.")
            except Exception as e:
                print(f"  ❌ Erreur DB sur {nom_culture}: {e}")
                conn.rollback()
                continue
            
            conn.commit()

        print("\n🎉 Patch des indices MAX terminé avec succès.")
        
    except Exception as e:
        print(f"Erreur globale : {e}")
    finally:
        if 'cur' in locals() and cur: cur.close()
        if conn: conn.close()