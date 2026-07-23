import json
import os
import shutil
import unicodedata
import re
from collections import defaultdict

# --- NOUVEAU : Importation du traducteur ---
try:
    from deep_translator import GoogleTranslator
except ImportError:
    print("❌ Erreur : Veuillez installer la librairie avec la commande : pip install deep-translator")
    exit()

# Initialisation du traducteur (détection automatique vers le français)
traducteur = GoogleTranslator(source='auto', target='fr')

def traduire_texte(texte):
    """ Traduit un texte en français. Retourne le texte original en cas d'échec. """
    if not texte or not isinstance(texte, str):
        return texte
    try:
        # Petite sécurité pour ne pas traduire les textes trop courts (ex: "oui", "non")
        if len(texte) > 3:
            return traducteur.translate(texte)
        return texte
    except Exception:
        return texte

def traduire_liste(liste):
    """ Traduit une liste de chaînes de caractères. """
    if not liste or not isinstance(liste, list):
        return liste
    return [traduire_texte(el) for el in liste if isinstance(el, str)]

def normaliser_culture(nom_brut):
    """ Standardise les noms et filtre les aberrations. """
    if not nom_brut:
        return "inconnu"
        
    nom = str(nom_brut).lower().strip()
    nom = unicodedata.normalize('NFKD', nom).encode('ASCII', 'ignore').decode('utf-8')
    nom = re.sub(r'[\-_]', ' ', nom)
    nom = re.sub(r'[\(\)\.]', '', nom)
    nom = re.sub(r'^(le |la |les |l\')', '', nom)
    nom = re.sub(r'\s+', ' ', nom).strip()

    # FILTRAGE STRICT DES INTRUS
    intrus = [
        "poisson", "poissonnier", "inconnue", "culture inconnue", "culture x", 
        "helm", "hormone", "edesse", "hlemm", "a graminees", "achlamydes", 
        "almellya", "arabie", "arabricotier", "arbecette", "arbre a feuilles persistantes", 
        "cerealiculture", "culture marocaine", "ensilage", "legumineuses alimentaires", 
        "orage", "pente cerise", "pompe de terre", "riz du figue", 
        "shaghaat el luzz", "viticulture", "viticulture marocaine", "ziza"
    ]
    if nom in intrus:
        return None

    # MAPPING DES DOUBLONS & TRADUCTIONS DES TITRES
    # 8. MAPPING (Pour fusionner les doublons, traduire l'anglais et le latin)
    mapping = {
        # Fruits & Arbres
        "abricot": "abricotier", "abricot prunus armeniaca": "abricotier", "arbre de prunus armeniaca": "abricotier",
        "amandier": "amandier", "amygdalus communis": "amandier", "louz": "amandier",
        "cognassier cydonia vulgaris": "cognassier",
        "avocatier persea americana": "avocatier",
        "noyer commun juglans regia": "noyer commun", "noyer": "noyer commun",
        "figue": "figuier", "ficus carica": "figuier", # Corrigé en figuier
        "framboise": "framboisier",
        "pomier": "pommier", "pomme malus domestica": "pommier", "pomme": "pommier",
        "grenade": "grenadier", 
        "palm tree": "palmier dattier", "nkhil temr": "palmier dattier", "nkhil el temmar": "palmier dattier",
        "prunus armeniaca": "prunier",
        "rosa damascena": "rose",
        "peche": "pecher", "pecher prunus persica": "pecher", # Fusion du fruit et de l'arbre
        "raisin de table": "vigne", # Regroupement sous la plante mère
        "capparis": "caprier", # Traduction du latin
        
        # Herbes & Épices
        "mentha verte": "menthe verte", "mentha viridis ou mentha spicata var viridis": "menthe verte", "mentha spicata var viridis": "menthe verte", "mentha viridis": "menthe verte",
        "saffron": "safran", "safraniere": "safran",
        "organe" : "oregano",
        "stevia rebaudiana": "stevia", # Simplification
        
        # Céréales
        "cereales d automne": "cereale", "cereales": "cereale", "cereales de printemps": "cereale",
        "culture de ble": "ble", "ble dur": "ble", "ble tendre": "ble", "ble dur et ble tendre": "ble",
        "riz vert": "riz", # Fusion du riz
        
        # Café & Légumineuses
        "arabe": "arabica", "arabique": "arabica", "araabiyat": "arabica", "culture arabe": "arabica",
        "arachidonne": "arachide", "arachis hypogaea": "arachide", "arachid": "arachide",
        
        # Légumes & Autres
        "agrume": "agrumes", "citron": "agrumes", # On englobe le citron dans agrumes
        "bananier": "banane",
        "culture de mais": "mais", "zea mays": "mais", "mais ensilage": "mais",
        "culture de soja": "soja",
        "betterave a sucre monogermes": "betterave a sucre", "betterave a sucre monogerme": "betterave a sucre", # Fusion des betteraves
        "piment rouge niora": "piment rouge",
        "fragaria vulgaris": "fraisier",
        "rapeseed": "colza" # Traduction de l'anglais
    }
    return mapping.get(nom, nom)

def fusionner_par_culture(input_dir, output_dir):
    if os.path.exists(output_dir):
        print(f"🧹 Nettoyage du dossier '{output_dir}'...")
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    data_fusionnee = defaultdict(lambda: {
        "culture": "",
        "exigences_sol": "",
        "besoins_hydriques": "",
        "temp_optimale": {"temp_min": None, "temp_max": None},
        "maladies_details": {},
        "recommandations": [] 
    })

    fichiers = [f for f in os.listdir(input_dir) if f.endswith(".json")]
    print(f"🚀 Début de la consolidation et traduction de {len(fichiers)} fichiers... (Cela peut prendre un peu de temps)")

    for file in fichiers:
        with open(os.path.join(input_dir, file), 'r', encoding='utf-8') as f:
            try:
                contenu = json.load(f)
            except json.JSONDecodeError:
                print(f"⚠️ Erreur de lecture : {file}")
                continue
                
            items = [contenu] if isinstance(contenu, dict) else contenu
            
            for item in items:
                nom_brut = item.get("culture", "inconnu")
                nom_culture = normaliser_culture(nom_brut)
                
                if not nom_culture or nom_culture == "inconnu":
                    continue
                
                data_fusionnee[nom_culture]["culture"] = nom_culture.capitalize()
                
                # --- TRADUCTION DES TEXTES LONGS ---
                if not data_fusionnee[nom_culture]["exigences_sol"] and item.get("exigences_sol"):
                    data_fusionnee[nom_culture]["exigences_sol"] = traduire_texte(item.get("exigences_sol"))
                    
                if not data_fusionnee[nom_culture]["besoins_hydriques"] and item.get("besoins_hydriques"):
                    data_fusionnee[nom_culture]["besoins_hydriques"] = traduire_texte(item.get("besoins_hydriques"))
                
                temp_opt = item.get("temp_optimale", {})
                if isinstance(temp_opt, dict):
                    if not data_fusionnee[nom_culture]["temp_optimale"]["temp_min"] and temp_opt.get("temp_min"):
                        data_fusionnee[nom_culture]["temp_optimale"]["temp_min"] = temp_opt.get("temp_min")
                    if not data_fusionnee[nom_culture]["temp_optimale"]["temp_max"] and temp_opt.get("temp_max"):
                        data_fusionnee[nom_culture]["temp_optimale"]["temp_max"] = temp_opt.get("temp_max")
                
                # --- TRADUCTION DES MALADIES ---
                maladies = item.get("maladies_details", [])
                if isinstance(maladies, list):
                    for m in maladies:
                        if m and isinstance(m, dict):
                            m_nom = m.get("nom_maladie")
                            if m_nom:
                                cle_maladie = normaliser_culture(m_nom) # On utilise la même logique pour nettoyer la clé
                                if not cle_maladie: 
                                    cle_maladie = m_nom.lower().strip()
                                
                                if cle_maladie not in data_fusionnee[nom_culture]["maladies_details"]:
                                    # Traduction du contenu de la maladie
                                    m_traduite = {
                                        "nom_maladie": traduire_texte(m_nom),
                                        "causes": traduire_liste(m.get("causes", [])),
                                        "traitements_specifiques": traduire_liste(m.get("traitements_specifiques", []))
                                    }
                                    data_fusionnee[nom_culture]["maladies_details"][cle_maladie] = m_traduite

                # --- TRADUCTION DES RECOMMANDATIONS ---
                recommandations = item.get("recommandations", [])
                if isinstance(recommandations, list):
                    for rec in recommandations:
                        if rec and isinstance(rec, dict):
                            desc = rec.get("description")
                            if desc:
                                desc_traduite = traduire_texte(desc.strip())
                                desc_nettoyee = desc_traduite.lower().strip()
                                
                                deja_existante = any(
                                    r.get("description", "").lower().strip() == desc_nettoyee 
                                    for r in data_fusionnee[nom_culture]["recommandations"]
                                )
                                
                                if not deja_existante:
                                    data_fusionnee[nom_culture]["recommandations"].append({
                                        "description": desc_traduite,
                                        "status": traduire_texte(rec.get("status", "à faire")),
                                        "categorie": traduire_texte(rec.get("categorie", "optionnel"))
                                    })

    compteur = 0
    for culture, data in data_fusionnee.items():
        if culture == "inconnu": 
            continue 
            
        data["maladies_details"] = list(data["maladies_details"].values())
        nom_fichier = f"{culture}.json".replace(" ", "_")
        
        with open(os.path.join(output_dir, nom_fichier), 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        compteur += 1

    print(f"✅ Consolidation et traduction terminées : {compteur} cultures propres générées dans '{output_dir}'.")

if __name__ == "__main__":
    fusionner_par_culture("FT_Json_Data", "FT_Clean")