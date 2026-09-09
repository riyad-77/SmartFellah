import json
import os
import sys
import unicodedata
import re
from collections import defaultdict

try:
    from deep_translator import GoogleTranslator
except ImportError:
    print("❌ Erreur : Veuillez installer la librairie avec la commande : pip install deep-translator")
    exit()

traducteur = GoogleTranslator(source='auto', target='fr')

def traduire_texte(texte):
    if not texte or not isinstance(texte, str):
        return texte
    try:
        if len(texte) > 3:
            return traducteur.translate(texte)
        return texte
    except Exception:
        return texte

def traduire_liste(liste):
    if not liste or not isinstance(liste, list):
        return liste
    return [traduire_texte(el) for el in liste if isinstance(el, str)]

def normaliser_culture(nom_brut):
    if not nom_brut: return "inconnu"
        
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
    if nom in intrus: return None

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


def fusionner_par_culture(input_dir, output_dir):
    if not os.path.exists(input_dir):
        os.makedirs(input_dir, exist_ok=True)
        
    fichiers_nouveaux = [f for f in os.listdir(input_dir) if f.endswith(".json")]
    
    if len(fichiers_nouveaux) == 0:
        print("✅ Aucun fichier JSON à consolider. Arrêt de l'étape.")
        sys.exit(0)

    os.makedirs(output_dir, exist_ok=True)

    data_fusionnee = defaultdict(lambda: {
        "culture": "",
        "zones_recommandees": [],
        "exigences_sol": "",
        "besoins_hydriques": "",
        "bioclimatologie_optimale": {"temp_min": None, "temp_max": None, "hum_min": None, "hum_max": None},
        "indices_satellitaires_requis": {
            "ndvi_optimal_min": None, "ndvi_optimal_max": None,
            "ndwi_optimal_min": None, "ndwi_optimal_max": None,
            "evi_optimal_min": None,  "evi_optimal_max": None
        },
        "maladies_details": {},
        "recommandations": [] 
    })

    fichiers_existants = [f for f in os.listdir(output_dir) if f.endswith(".json")]
    for file in fichiers_existants:
        with open(os.path.join(output_dir, file), 'r', encoding='utf-8') as f:
            try:
                existant = json.load(f)
                nom_culture = normaliser_culture(existant.get("culture", ""))
                if nom_culture and nom_culture != "inconnu":
                    data_fusionnee[nom_culture]["culture"] = existant.get("culture", nom_culture.capitalize())
                    data_fusionnee[nom_culture]["zones_recommandees"] = existant.get("zones_recommandees", [])
                    data_fusionnee[nom_culture]["exigences_sol"] = existant.get("exigences_sol", "")
                    data_fusionnee[nom_culture]["besoins_hydriques"] = existant.get("besoins_hydriques", "")
                    
                    anciennes_temps = existant.get("temp_optimale", {})
                    bioclim = existant.get("bioclimatologie_optimale", {
                        "temp_min": anciennes_temps.get("temp_min"), 
                        "temp_max": anciennes_temps.get("temp_max"), 
                        "hum_min": None, "hum_max": None
                    })
                    data_fusionnee[nom_culture]["bioclimatologie_optimale"] = bioclim
                    data_fusionnee[nom_culture]["indices_satellitaires_requis"] = existant.get("indices_satellitaires_requis", {"ndvi_optimal_min": None, "ndwi_optimal_min": None, "evi_optimal_min": None})
                    
                    for m in existant.get("maladies_details", []):
                        cle_mal = normaliser_culture(m.get("nom_maladie", ""))
                        if cle_mal:
                            data_fusionnee[nom_culture]["maladies_details"][cle_mal] = m
                            
                    data_fusionnee[nom_culture]["recommandations"] = existant.get("recommandations", [])
            except json.JSONDecodeError:
                pass

    print(f"🚀 Début de la consolidation de {len(fichiers_nouveaux)} nouveaux fichiers avec l'historique...")
    
    for file in fichiers_nouveaux:
        with open(os.path.join(input_dir, file), 'r', encoding='utf-8') as f:
            try:
                contenu = json.load(f)
            except json.JSONDecodeError:
                continue
                
            items = [contenu] if isinstance(contenu, dict) else contenu
            
            for item in items:
                nom_brut = item.get("culture", "inconnu")
                nom_culture = normaliser_culture(nom_brut)
                
                if not nom_culture or nom_culture == "inconnu":
                    continue
                
                data_fusionnee[nom_culture]["culture"] = nom_culture.capitalize()
                
                # FUSION DES ZONES GEOGRAPHIQUES
                nouvelles_zones = item.get("zones_recommandees", [])
                if isinstance(nouvelles_zones, list):
                    anciennes_zones = data_fusionnee[nom_culture]["zones_recommandees"]
                    for z in nouvelles_zones:
                        z_clean = traduire_texte(str(z).strip()).title()
                        if z_clean and z_clean not in anciennes_zones:
                            anciennes_zones.append(z_clean)
                    data_fusionnee[nom_culture]["zones_recommandees"] = anciennes_zones
                
                if not data_fusionnee[nom_culture]["exigences_sol"] and item.get("exigences_sol"):
                    data_fusionnee[nom_culture]["exigences_sol"] = traduire_texte(item.get("exigences_sol"))
                    
                if not data_fusionnee[nom_culture]["besoins_hydriques"] and item.get("besoins_hydriques"):
                    data_fusionnee[nom_culture]["besoins_hydriques"] = traduire_texte(item.get("besoins_hydriques"))
                
                bioclim_new = item.get("bioclimatologie_optimale", {})
                if isinstance(bioclim_new, dict):
                    if not data_fusionnee[nom_culture]["bioclimatologie_optimale"]["temp_min"] and bioclim_new.get("temp_min"):
                        data_fusionnee[nom_culture]["bioclimatologie_optimale"]["temp_min"] = bioclim_new.get("temp_min")
                    if not data_fusionnee[nom_culture]["bioclimatologie_optimale"]["temp_max"] and bioclim_new.get("temp_max"):
                        data_fusionnee[nom_culture]["bioclimatologie_optimale"]["temp_max"] = bioclim_new.get("temp_max")
                    if not data_fusionnee[nom_culture]["bioclimatologie_optimale"]["hum_min"] and bioclim_new.get("hum_min"):
                        data_fusionnee[nom_culture]["bioclimatologie_optimale"]["hum_min"] = bioclim_new.get("hum_min")
                    if not data_fusionnee[nom_culture]["bioclimatologie_optimale"]["hum_max"] and bioclim_new.get("hum_max"):
                        data_fusionnee[nom_culture]["bioclimatologie_optimale"]["hum_max"] = bioclim_new.get("hum_max")
                
                indices_new = item.get("indices_satellitaires_requis", {})
                if isinstance(indices_new, dict):
                    if not data_fusionnee[nom_culture]["indices_satellitaires_requis"]["ndvi_optimal_min"] and indices_new.get("ndvi_optimal_min"):
                        data_fusionnee[nom_culture]["indices_satellitaires_requis"]["ndvi_optimal_min"] = indices_new.get("ndvi_optimal_min")
                    if not data_fusionnee[nom_culture]["indices_satellitaires_requis"]["ndvi_optimal_max"] and indices_new.get("ndvi_optimal_max"):
                        data_fusionnee[nom_culture]["indices_satellitaires_requis"]["ndvi_optimal_max"] = indices_new.get("ndvi_optimal_max")
                        
                    if not data_fusionnee[nom_culture]["indices_satellitaires_requis"]["ndwi_optimal_min"] and indices_new.get("ndwi_optimal_min"):
                        data_fusionnee[nom_culture]["indices_satellitaires_requis"]["ndwi_optimal_min"] = indices_new.get("ndwi_optimal_min")
                    if not data_fusionnee[nom_culture]["indices_satellitaires_requis"]["ndwi_optimal_max"] and indices_new.get("ndwi_optimal_max"):
                        data_fusionnee[nom_culture]["indices_satellitaires_requis"]["ndwi_optimal_max"] = indices_new.get("ndwi_optimal_max")
                        
                    if not data_fusionnee[nom_culture]["indices_satellitaires_requis"]["evi_optimal_min"] and indices_new.get("evi_optimal_min"):
                        data_fusionnee[nom_culture]["indices_satellitaires_requis"]["evi_optimal_min"] = indices_new.get("evi_optimal_min")
                    if not data_fusionnee[nom_culture]["indices_satellitaires_requis"]["evi_optimal_max"] and indices_new.get("evi_optimal_max"):
                        data_fusionnee[nom_culture]["indices_satellitaires_requis"]["evi_optimal_max"] = indices_new.get("evi_optimal_max")
                        
                maladies = item.get("maladies_details", [])
                if isinstance(maladies, list):
                    for m in maladies:
                        if m and isinstance(m, dict):
                            m_nom = m.get("nom_maladie")
                            if m_nom:
                                cle_maladie = normaliser_culture(m_nom) 
                                if not cle_maladie: 
                                    cle_maladie = m_nom.lower().strip()
                                
                                if cle_maladie not in data_fusionnee[nom_culture]["maladies_details"]:
                                    m_traduite = {
                                        "nom_maladie": traduire_texte(m_nom),
                                        "causes": traduire_liste(m.get("causes", [])),
                                        "traitements_specifiques": traduire_liste(m.get("traitements_specifiques", []))
                                    }
                                    data_fusionnee[nom_culture]["maladies_details"][cle_maladie] = m_traduite

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
    fusionner_par_culture(r"C:\Users\hp\SmartFellah\FT_Json_Data", r"C:\Users\hp\SmartFellah\FT_Clean")