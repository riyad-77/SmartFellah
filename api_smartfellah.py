from contextlib import asynccontextmanager
import os
import shutil
from enum import Enum
from fastapi import FastAPI, HTTPException, File, UploadFile, APIRouter, Depends
import pandas as pd
from pydantic import BaseModel, field_validator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
import joblib
import difflib
import re
import unicodedata  # AJOUT : Pour la gestion des accents
from functools import lru_cache

ml_model = None
ml_features = None
disease_model = None
disease_features = None

# --- CONFIGURATION ---
DB_URL = "postgresql://admin:secretpassword@localhost:5432/bifolia_db"
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Variable globale pour stocker le modèle NLP
nlp_classifier = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global ml_model, ml_features
    # nlp_classifier a été supprimé
    
    print("🚀 Démarrage de l'API SmartFellah (Mode Lexical Rapide)...")
    try:
        # On ne charge QUE le modèle d'irrigation (Random Forest)
        ml_model = joblib.load("models/ndwi_forecaster.pkl")
        ml_features = joblib.load("models/features_list.pkl")
        print("✅ Modèle Irrigation chargé !")
        
    except Exception as e:
        print(f"⚠️ Erreur de chargement : {e}")
    yield
    print("🛑 Arrêt de l'API.")

app = FastAPI(title="SmartFellah Prediction API", lifespan=lifespan)
router = APIRouter()

# --- FONCTIONS DE NETTOYAGE MOJIBAKE ---
def nettoyer_mojibake(texte: str) -> str:
    if not texte or not isinstance(texte, str):
        return texte
    corrections = {
        "├®": "é", "├¿": "è", "├¬": "ê", "├á": "à", "├º": "ç", 
        "├â": "Â", "┬½": "«", "┬╗": "»", "ÔÇÖ": "'", "╦Ü": "°",
        "├»": "ï"
    }
    for faux, vrai in corrections.items():
        texte = texte.replace(faux, vrai)
    return texte

def sans_accents(texte: str) -> str:
    if not texte or not isinstance(texte, str):
        return texte
    texte = unicodedata.normalize('NFD', texte).encode('ascii', 'ignore').decode('utf-8')
    return texte.lower().strip()


# --- 1. DÉFINITIONS DES CLASSES PYDANTIC ---
class StadeCultureEnum(str, Enum):
    semis = "semis"
    croissance = "croissance"
    floraison = "floraison"
    maturite = "maturité"

class DailyAdviceInput(BaseModel):
    nom_commune: str
    nom_culture: str
    stade_culture: StadeCultureEnum = StadeCultureEnum.croissance

    @field_validator('nom_commune', 'nom_culture')
    @classmethod
    def clean_text(cls, v: str) -> str:
        return re.sub(r'\s+', ' ', v.strip().lower())

    @field_validator('stade_culture', mode='before')
    @classmethod
    def clean_stade(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

class AssolementCommuneInput(BaseModel):
    nom_commune: str

    @field_validator('nom_commune')
    @classmethod
    def clean_text(cls, v: str) -> str:
        return re.sub(r'\s+', ' ', v.strip().lower())

class MaladieInput(BaseModel):
    nom_commune: str
    nom_culture: str

    @field_validator('nom_commune', 'nom_culture')
    @classmethod
    def clean_text(cls, v: str) -> str:
        return re.sub(r'\s+', ' ', v.strip().lower())


def valider_et_corriger_nom(nom_saisi: str, type_recherche: str, conn) -> str:
    if type_recherche == 'commune':
        query = text("SELECT DISTINCT nom_commune FROM communes_maroc WHERE nom_commune IS NOT NULL")
    else:
        query = text("SELECT DISTINCT nom_culture FROM cultures WHERE nom_culture IS NOT NULL")
        
    resultats = conn.execute(query).fetchall()
    noms_dict = {}
    for row in resultats:
        nom_brut_db = row[0]
        nom_propre = nettoyer_mojibake(nom_brut_db)
        cle_recherche = sans_accents(nom_propre)
        noms_dict[cle_recherche] = nom_brut_db
        
    nom_saisi_norm = sans_accents(nom_saisi)
    if nom_saisi_norm in noms_dict:
        return noms_dict[nom_saisi_norm]
        
    correspondances = difflib.get_close_matches(nom_saisi_norm, noms_dict.keys(), n=1, cutoff=0.65)
    if correspondances:
        return noms_dict[correspondances[0]]
    return None


def analyser_compatibilite_nlp(sol_local: str, exigence_texte: str) -> tuple[str, bool]:
    """
    Analyse NLP sémantique : retourne un message de statut et un booléen (True si compatible, False si conflit).
    """
    if not sol_local or sol_local.lower().startswith("inconnu") or not exigence_texte:
        return "À vérifier sur le terrain", True
        
    sol_loc = sans_accents(sol_local).lower()
    exigence = sans_accents(exigence_texte).lower()
    
    familles_sols = {
        "sable": ["sable", "sableux", "sablonneux", "r'mel", "rmel", "drainant", "arenosols", "podzols"],
        "argile": ["argile", "argileux", "argilo", "lourd", "vertisols", "acrisols", "luvisols", "lixisols"],
        "limon": ["limon", "limoneux", "limono", "alluvial", "fluvisols"],
        "calcaire": ["calcaire", "calcaires", "calcium", "calcisols"],
        "humus": ["humus", "humifere", "terreau", "organique", "fertile", "riche", "chernozems", "histosols", "phaeozems"],
        "salin": ["sel", "salin", "salinite", "solonchaks", "solonetz"],
        "gypse": ["gypse", "gypsisols"]
    }
    
    caracteristiques_locales = [famille for famille, mots in familles_sols.items() if any(mot in sol_loc for mot in mots)]
            
    if not caracteristiques_locales:
        return "À vérifier sur le terrain", True
        
    match = False
    conflit = False
    negations = ["eviter", "non", "pas", "jamais", "sensible", "redoute", "inadapte", "deconseille"]
    mots_exigence = re.findall(r'\b\w+\b', exigence)
    
    for carac in caracteristiques_locales:
        mots_famille = familles_sols[carac]
        if any(mot in exigence for mot in mots_famille):
            for mot_famille in mots_famille:
                if mot_famille in mots_exigence:
                    index = mots_exigence.index(mot_famille)
                    contexte = " ".join(mots_exigence[max(0, index-4):index])
                    if any(neg in contexte for neg in negations):
                        conflit = True
                    else:
                        match = True

    if conflit:
        return "Déconseillée (Sol incompatible selon l'analyse sémantique)", False
    elif match:
        return "Optimale (Forte correspondance textuelle)", True
    else:
        return "Moyenne (Aucune correspondance précise trouvée, validation requise)", True

def analyser_causes_meteo_nlp(causes_texte: str, meteo: dict) -> bool:
    """
    Analyse NLP sémantique : Vérifie si les causes textuelles de la maladie
    correspondent aux conditions météorologiques actuelles.
    """
    if not causes_texte or causes_texte.lower() in ["none", "null", ""]:
        # Si la maladie n'a pas de cause définie en BDD, on la laisse passer par sécurité
        return True 
        
    cause = sans_accents(str(causes_texte)).lower()
    match = False
    
    # 1. Pluie & Excès d'eau
    if any(mot in cause for mot in ["pluie", "pluies", "humidite", "humide", "eau", "inondation"]):
        if meteo.get("precipitations_mm", 0) > 0.5 or meteo.get("humidite_moyenne", 0) > 70:
            match = True
            
    # 2. Sécheresse & Manque d'eau
    if any(mot in cause for mot in ["manque d'eau", "secheresse", "sec", "aridite"]):
        if meteo.get("precipitations_mm", 0) <= 0.1 and meteo.get("humidite_moyenne", 100) < 50:
            match = True
            
    # 3. Chaleur & Températures excessives
    if any(mot in cause for mot in ["chaleur", "temperature excessive", "extreme", "chaud", "insolation", "soleil"]):
        if meteo.get("temp_max", 0) > 30 or meteo.get("temp_moyenne", 0) > 25:
            match = True
            
    # 4. Froid & Gel (-4°C, froid, etc.)
    if any(mot in cause for mot in ["froid", "gel", "gelee", "basses", "temperature inferieure", "-", "frais"]):
        if meteo.get("temp_min", 20) < 10:
            match = True
            
    # 5. Facteurs externes non-climatiques (Vent, Parasites, Nutrition, Salinité)
    # On force à True car ces facteurs ne sont pas mesurables via la simple météo
    facteurs_externes = ["vent", "vents", "parasite", "parasites", "nutrition", "fertilisation", "salinite", "salin"]
    if any(mot in cause for mot in facteurs_externes):
        match = True
        
    return match





# On crée une fonction qui fait SEULEMENT le NLP, et on la met en cache !
@lru_cache(maxsize=1000)
def analyser_texte_maladie_nlp(causes_texte: str):
    if not causes_texte or nlp_classifier is None:
        return []
        
    # On force l'IA à valider une relation de cause à effet stricte
    labels_candidats = [
        "provoqué par un excès d'humidité",
        "provoqué par des fortes pluies",
        "provoqué par de fortes chaleurs",
        "provoqué par le froid",
        "provoqué par la sécheresse ou le manque d'eau"
    ]
    
    resultat = nlp_classifier(
        causes_texte,
        candidate_labels=labels_candidats,
        multi_label=True
    )
    
    labels_valides = []
    # On augmente légèrement le seuil de confiance à 65% pour filtrer le bruit
    for i, label in enumerate(resultat['labels']):
        if resultat['scores'][i] > 0.65: 
            # On re-traduit la phrase en concept simple pour notre dictionnaire météo
            if "humidité" in label: labels_valides.append("humidité")
            elif "pluies" in label: labels_valides.append("pluie")
            elif "chaleurs" in label: labels_valides.append("chaleur")
            elif "froid" in label: labels_valides.append("froid")
            elif "sécheresse" in label: labels_valides.append("sécheresse")
            
    return labels_valides


DICTIONNAIRE_REGEX = {
    "humidite_haute": r"(humidit|hygrom|champignon|fongique|mousse|eau stagnante|mouill|pourriture)",
    "humidite_basse": r"(s[eé]cheresse|sec|arid|manque d'eau|manque d'irrigation|déficit hydrique|soif)",
    "chaleur": r"(chaleur|chaud|canicule|temp[eé]rature[s]? [eé]lev[eé]e|insolation|soleil)",
    "froid": r"(froid|gel|givre|basse temp[eé]rature|fra[iî]cheur|neige|hiver)",
    "pluie": r"(pluie|averse|précipitation|inondation|grêle)",
    "vent": r"(vent|bourrasque|temp[eê]te|ouragan)"
}

def evaluer_causes_rapide(causes_texte: str, meteo_jour: dict, ref_optimale: dict) -> list:
    """
    Évalue les causes textuelles en se basant sur les seuils stricts de la table ref_temp_optimale.
    """
    if not causes_texte or not ref_optimale:
        return []
        
    texte_cible = causes_texte.lower()
    facteurs_declencheurs = []
    
    # CORRECTION : Utilisation de .get() car ref_optimale est un dictionnaire
    hum_max_culture = float(ref_optimale.get("hum_max") or 75.0)
    hum_min_culture = float(ref_optimale.get("hum_min") or 40.0)
    temp_max_culture = float(ref_optimale.get("temp_max") or 35.0)
    temp_min_culture = float(ref_optimale.get("temp_min") or 5.0)

    # 1. Analyse de l'humidité excessive
    if re.search(DICTIONNAIRE_REGEX["humidite_haute"], texte_cible):
        if meteo_jour["humidite_moyenne"] > hum_max_culture:
            facteurs_declencheurs.append(f"Humidité critique pour cette culture ({meteo_jour['humidite_moyenne']}% > seuil max {hum_max_culture}%)")
            
    # 2. Analyse du déficit hydrique (sécheresse)
    if re.search(DICTIONNAIRE_REGEX["humidite_basse"], texte_cible):
        if meteo_jour["humidite_moyenne"] < hum_min_culture and meteo_jour["precipitations_mm"] == 0:
            facteurs_declencheurs.append(f"Déficit hydrique ({meteo_jour['humidite_moyenne']}% < seuil min {hum_min_culture}%)")
            
    # 3. Analyse de la chaleur
    if re.search(DICTIONNAIRE_REGEX["chaleur"], texte_cible):
        if meteo_jour["temp_max"] > temp_max_culture:
            facteurs_declencheurs.append(f"Chaleur excessive ({meteo_jour['temp_max']}°C > seuil max {temp_max_culture}°C)")
            
    # 4. Analyse du froid
    if re.search(DICTIONNAIRE_REGEX["froid"], texte_cible):
        if meteo_jour["temp_min"] < temp_min_culture:
            facteurs_declencheurs.append(f"Froid critique ({meteo_jour['temp_min']}°C < seuil min {temp_min_culture}°C)")
            
    # 5. Phénomènes ponctuels (non liés à ref_temp_optimale mais aux capteurs)
    if re.search(DICTIONNAIRE_REGEX["pluie"], texte_cible):
        if meteo_jour["precipitations_mm"] > 0.5:
            facteurs_declencheurs.append(f"Précipitations actives ({meteo_jour['precipitations_mm']} mm)")
            
    if re.search(DICTIONNAIRE_REGEX["vent"], texte_cible):
        if meteo_jour.get("vitesse_vent_kmh", 0) > 20:
            facteurs_declencheurs.append(f"Vents forts détectés ({meteo_jour.get('vitesse_vent_kmh')} km/h)")

    return facteurs_declencheurs

# --- 2. ENDPOINTS MÉTIER ---

@app.post("/recommend-crops-by-commune")
def recommend_crops_by_commune(data: AssolementCommuneInput):
    try:
        with engine.connect() as conn:
            commune_corrigee = valider_et_corriger_nom(data.nom_commune, 'commune', conn)
            if not commune_corrigee:
                raise HTTPException(status_code=404, detail=f"Commune '{data.nom_commune}' introuvable.")
            
            check_col = text("SELECT column_name FROM information_schema.columns WHERE table_name='communes_maroc' AND column_name='type_de_sol'")
            has_sol_col = conn.execute(check_col).fetchone()
            sol_select = "cm.type_de_sol" if has_sol_col else "NULL as type_de_sol"

            # 1. Requête principale avec l'EVI ajouté
            commune_query = text(f"""
                SELECT 
                    cm.nom_commune, cm.region, {sol_select},
                    cm.temp_min_climat, cm.temp_max_climat,
                    cm.humidite_min_climat, cm.humidite_max_climat,
                    AVG(s.ndvi) as ndvi_moyen,
                    AVG(s.ndwi) as ndwi_moyen,
                    AVG(s.evi) as evi_moyen
                FROM communes_maroc cm
                LEFT JOIN parcelles p ON p.commune_id = cm.id OR LOWER(p.commune) = LOWER(cm.nom_commune)
                LEFT JOIN indices_satellites s ON s.parcelle_id = p.id
                WHERE LOWER(cm.nom_commune) = LOWER(:commune)
                GROUP BY cm.id;
            """)
            res_commune = conn.execute(commune_query, {"commune": commune_corrigee}).fetchone()

            sol_local = str(res_commune.type_de_sol) if res_commune and res_commune.type_de_sol else "inconnu"
            nom_commune_trouvee = res_commune.nom_commune if res_commune else commune_corrigee
            
            # NETTOYAGE STRICT AVANT LA RECHERCHE SQL
            commune_propre = nettoyer_mojibake(nom_commune_trouvee)
            region_propre = nettoyer_mojibake(res_commune.region if res_commune and res_commune.region else "Non spécifiée")
            region_courte = region_propre.split('-')[0].strip() if region_propre else ""

            # 2. Utilisation exclusive des données de la base
            if res_commune and res_commune.temp_min_climat is not None:
                t_min_locale = float(res_commune.temp_min_climat)
                t_max_locale = float(res_commune.temp_max_climat)
                avertissement = "Basé sur les extrêmes climatiques de la commune (historique + prévisions)."
            else:
                fallback_national = text("SELECT MIN(temp_min_climat) as tmin, MAX(temp_max_climat) as tmax FROM communes_maroc;")
                meteo_nat = conn.execute(fallback_national).fetchone()
                
                if not meteo_nat or meteo_nat.tmin is None:
                    raise HTTPException(status_code=500, detail="Base de données météo entièrement vide, impossible de recommander.")
                
                t_min_locale = float(meteo_nat.tmin)
                t_max_locale = float(meteo_nat.tmax)
                avertissement = "Basé sur les extrêmes climatiques nationaux (aucune donnée locale trouvée)."
                
            ndvi_moy = float(res_commune.ndvi_moyen) if res_commune and res_commune.ndvi_moyen else None
            ndwi_moy = float(res_commune.ndwi_moyen) if res_commune and res_commune.ndwi_moyen else None
            evi_moy = float(res_commune.evi_moyen) if res_commune and res_commune.evi_moyen else None

            # 3. Filtrage : Tolérance climatique OU Bypass via Terroir Historique
            cultures_query = text("""
                SELECT 
                    c.nom_culture, 
                    rto.temp_min AS culture_temp_min, 
                    rto.temp_max AS culture_temp_max, 
                    res.libelle AS exigence_sol,
                    CASE 
                        WHEN MAX(ccr.id) IS NOT NULL THEN TRUE 
                        ELSE FALSE 
                    END as est_terroir_historique
                FROM cultures c
                JOIN ref_temp_optimale rto ON c.temp_optimale_id = rto.id
                LEFT JOIN ref_exigences_sol res ON c.exigence_sol_id = res.id
                LEFT JOIN culture_communes_recommandees ccr 
                    ON c.id = ccr.culture_id 
                    AND (
                        LOWER(ccr.nom_commune) LIKE '%' || LOWER(:commune_cible) || '%' 
                        OR LOWER(ccr.nom_commune) LIKE '%' || LOWER(:region_cible) || '%'
                    )
                GROUP BY c.id, c.nom_culture, rto.temp_min, rto.temp_max, res.libelle
                HAVING (rto.temp_min <= :t_min AND rto.temp_max >= :t_max)
                    OR MAX(ccr.id) IS NOT NULL
            """)
            
            cultures_compatibles = conn.execute(cultures_query, {
                "t_min": t_min_locale, 
                "t_max": t_max_locale,
                "commune_cible": commune_propre,
                "region_cible": region_courte
            }).fetchall()

            if not cultures_compatibles:
                return {
                    "commune": commune_propre.capitalize(),
                    "region": region_propre,
                    "type_de_sol_calcule": sol_local.capitalize(),
                    "message": f"Aucune culture ne tolère les extrêmes stricts de {commune_propre} (Min: {t_min_locale}°C, Max: {t_max_locale}°C) et aucune n'y est officiellement recommandée.",
                }

            # 4. Filtrage Pédologique Strict (NLP)
            recommandations = []
            for row in cultures_compatibles:
                exigence_sol = nettoyer_mojibake(row.exigence_sol if row.exigence_sol else "Non spécifié")
                compatibilite_sol, est_compatible = analyser_compatibilite_nlp(sol_local, exigence_sol)
                
                if not est_compatible:
                    continue

                # On ne garde que les clés essentielles
                recommandations.append({
                    "culture": row.nom_culture.capitalize(),
                    "terroir_historique_recommande": row.est_terroir_historique,
                    "exigences_sol_detail": exigence_sol
                })
                
            # 5. Tri Final : Le Terroir Officiel d'abord
            recommandations = sorted(recommandations, key=lambda x: x["terroir_historique_recommande"], reverse=True)

            return {
                "commune": commune_propre.capitalize(),
                "region": region_propre,
                "source_recommandation": "Ces cultures sont spécifiquement recommandées pour cette région selon les études et fiches techniques officielles du Ministère de l'Agriculture du Maroc.",
                "cultures_compatibles": recommandations
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def traiter_et_trier_conseils(conseils, stade_actuel):
    priorite = {
        "urgence": 1,
        "urgent": 2,
        "normal": 3,
        "non urgent": 4
    }
    
    conseils.sort(key=lambda x: priorite.get(x['categorie'].lower(), 99))
    unique_conseils = []
    
    mots_exclus = []
    if stade_actuel in ["floraison", "maturité"]:
        mots_exclus = ["plantation", "planter", "jeunes plants", "distance", "semis"]
        
    for c in conseils:
        texte_actuel = c['conseil'].lower()
        if any(mot in texte_actuel for mot in mots_exclus):
            continue
            
        est_doublon = False
        for u in unique_conseils:
            texte_existant = u['conseil'].lower()
            ratio = difflib.SequenceMatcher(None, texte_actuel, texte_existant).ratio()
            if ratio > 0.65: 
                est_doublon = True
                break
                
        if not est_doublon:
            unique_conseils.append(c)
            
    unique_conseils.sort(key=lambda x: priorite.get(x['categorie'].lower(), 99))
    return unique_conseils


@app.post("/daily-advice")
def get_daily_advice(data: DailyAdviceInput):
    try:
        with engine.connect() as conn:
            commune_corrigee = valider_et_corriger_nom(data.nom_commune, 'commune', conn)
            culture_corrigee = valider_et_corriger_nom(data.nom_culture, 'culture', conn)
            
            if not commune_corrigee or not culture_corrigee:
                raise HTTPException(status_code=404, detail="Commune ou Culture introuvable.")

            # 1. Identification Parcelle et Récupération Propre des Seuils
            parcelle_query = text("SELECT id FROM parcelles WHERE LOWER(commune) = LOWER(:commune) LIMIT 1;")
            p_res = conn.execute(parcelle_query, {"commune": commune_corrigee}).fetchone()
            parcelle_id = p_res.id if p_res else conn.execute(text("SELECT id FROM parcelles LIMIT 1;")).fetchone().id

            cult_query = text("""
                SELECT c.id, c.nom_culture, rto.temp_min, rto.temp_max,
                       c.ndvi_optimal_min, c.ndvi_optimal_max,
                       c.ndwi_optimal_min, c.ndwi_optimal_max,
                       c.evi_optimal_min, c.evi_optimal_max
                FROM cultures c
                LEFT JOIN ref_temp_optimale rto ON c.temp_optimale_id = rto.id
                WHERE LOWER(c.nom_culture) = LOWER(:culture);
            """)
            cult_res = conn.execute(cult_query, {"culture": culture_corrigee}).fetchone()
            
            # --- EXTRACTION DIRECTE ET SÉCURISÉE (La BDD est déjà propre) ---
            c_map = dict(cult_res._mapping) if cult_res else {}
            
            opt_tmin = float(c_map.get("temp_min")) if c_map.get("temp_min") is not None else None
            opt_tmax = float(c_map.get("temp_max")) if c_map.get("temp_max") is not None else None
            
            opt_ndvi_min = float(c_map.get("ndvi_optimal_min")) if c_map.get("ndvi_optimal_min") is not None else None
            opt_ndvi_max = float(c_map.get("ndvi_optimal_max")) if c_map.get("ndvi_optimal_max") is not None else None
            
            opt_ndwi_min = float(c_map.get("ndwi_optimal_min")) if c_map.get("ndwi_optimal_min") is not None else None
            opt_ndwi_max = float(c_map.get("ndwi_optimal_max")) if c_map.get("ndwi_optimal_max") is not None else None
            
            opt_evi_min = float(c_map.get("evi_optimal_min")) if c_map.get("evi_optimal_min") is not None else None
            opt_evi_max = float(c_map.get("evi_optimal_max")) if c_map.get("evi_optimal_max") is not None else None
            
            # --- TRAITEMENT DES RECOMMANDATIONS SAISONNIÈRES ---
            conseils_pertinents = []
            if cult_res:
                recos_query = text("SELECT description, status, categorie FROM recommandation WHERE culture_id = :c_id;")
                recos_res = conn.execute(recos_query, {"c_id": c_map.get("id")}).fetchall()
                
                # FILTRE ANTI-DÉCHETS : On exclut les erreurs de l'IA
                conseils_bruts = []
                for r in recos_res:
                    if r.description:
                        texte = nettoyer_mojibake(r.description)
                        if "error 500" not in texte.lower() and "server error" not in texte.lower():
                            conseils_bruts.append({"categorie": r.categorie, "status": r.status, "conseil": texte})
                            
                conseils_pertinents = traiter_et_trier_conseils(conseils_bruts, data.stade_culture.value)

            # 2. Historique PANDAS
            history_query = text("""
                SELECT 
                    m.date_mesure, m.temp_moyenne, m.temp_max, m.temp_min, m.humidite_moyenne, m.precipitations_mm,
                    COALESCE(s.ndvi, 0.5) as ndvi, 
                    COALESCE(s.ndwi, 0.0) as ndwi,
                    COALESCE(s.evi, 0.3) as evi,
                    COALESCE(op.total_irrigation, 0) as irrigation_mm
                FROM donnees_meteo m
                LEFT JOIN indices_satellites s ON m.parcelle_id = s.parcelle_id AND DATE(m.date_mesure) = DATE(s.date_capture)
                LEFT JOIN (
                    SELECT parcelle_id, date_operation, SUM(quantite) as total_irrigation
                    FROM operations_agricoles
                    WHERE LOWER(type_operation) LIKE '%irrigation%'
                    GROUP BY parcelle_id, date_operation
                ) op ON m.parcelle_id = op.parcelle_id AND DATE(m.date_mesure) = DATE(op.date_operation)
                WHERE m.parcelle_id = :p_id
                ORDER BY m.date_mesure DESC
                LIMIT 1
            """)
            df_hist = pd.read_sql(history_query, conn, params={"p_id": parcelle_id})
            
            if df_hist.empty:
                raise HTTPException(status_code=404, detail="Aucune donnée météo/satellitaire disponible pour aujourd'hui.")

            jour_actuel = df_hist.iloc[0]
            
            temp_moy = float(jour_actuel['temp_moyenne'])
            temp_max = float(jour_actuel['temp_max'])
            temp_min = float(jour_actuel['temp_min'])
            ndvi_actuel = float(jour_actuel['ndvi'])
            evi_actuel = float(jour_actuel['evi'])
            ndwi_actuel = float(jour_actuel['ndwi'])
            irrigation_deja_faite = float(jour_actuel['irrigation_mm'])
            pluie_du_jour = float(jour_actuel['precipitations_mm'])

            # 3. Analyse Bioclimatique avec Recommandations Agronomiques Expertes
            analyse_bioclimatique = {}
            
            # Classification de la culture pour adapter les conseils d'excès végétatif
            cultures_arboriculture = [
                "abricotier", "agrumes", "amandier", "arganier", "avocatier", "banane",
                "cerisier", "cognassier", "figuier", "grenadier", "noyer", "olivier",
                "palmier", "pecher", "pistachier", "pommier", "prunier", "vigne",
                "caroubier", "caprier", "framboisier", "myrtille", "rose"
            ]
            est_arbre_ou_vigne = any(mot in culture_corrigee.lower() for mot in cultures_arboriculture)
            
            # --- Diagnostic NDVI (Vigueur foliaire & Azote) ---
            if opt_ndvi_min is not None and ndvi_actuel < opt_ndvi_min:
                statut_ndvi = "Déficit de Vigueur"
                action_ndvi = f"NDVI ({ndvi_actuel}) sous le minimum ({opt_ndvi_min}). Carence probable : appliquez une fertilisation azotée (N) d'urgence et lancez un diagnostic maladie."
            elif opt_ndvi_max is not None and ndvi_actuel > opt_ndvi_max:
                statut_ndvi = "Excès de Vigueur"
                if est_arbre_ou_vigne:
                    action_ndvi = f"NDVI ({ndvi_actuel}) au-dessus du maximum ({opt_ndvi_max}). Excès végétatif : stoppez l'azote, favorisez le Phosphore/Potassium (P-K) et pratiquez une taille en vert pour l'ensoleillement des fruits."
                else:
                    action_ndvi = f"NDVI ({ndvi_actuel}) au-dessus du maximum ({opt_ndvi_max}). Excès végétatif : stoppez net les apports en azote pour éviter la verse (effondrement) ou l'étouffement, et favorisez le Potassium."
            elif opt_ndvi_min is None and opt_ndvi_max is None:
                statut_ndvi = "Non Évalué"
                action_ndvi = "Aucune norme satellitaire NDVI officielle enregistrée."
            else:
                statut_ndvi = "Vigueur Optimale"
                action_ndvi = "Développement foliaire parfait. Maintenez votre programme de fertilisation de base."
                
            analyse_bioclimatique["sante_vegetale_ndvi"] = {
                "actuelle": ndvi_actuel, "optimale_min": opt_ndvi_min, "optimale_max": opt_ndvi_max,
                "statut": statut_ndvi, "action_requise": action_ndvi
            }

            # --- Diagnostic EVI (Biomasse & Structure) ---
            if opt_evi_min is not None and evi_actuel < opt_evi_min:
                statut_evi = "Biomasse Faible"
                action_evi = f"EVI ({evi_actuel}) sous le seuil de {opt_evi_min}. Canopée clairsemée : vérifiez un éventuel blocage racinaire (compaction du sol) et aérez par binage."
            elif opt_evi_max is not None and evi_actuel > opt_evi_max:
                statut_evi = "Biomasse Excessive"
                if est_arbre_ou_vigne:
                    action_evi = f"EVI ({evi_actuel}) dépasse le seuil de {opt_evi_max}. Canopée trop dense : risque majeur de champignons par humidité stagnante. Éclaircissez les branches d'urgence."
                else:
                    action_evi = f"EVI ({evi_actuel}) dépasse le seuil de {opt_evi_max}. Densité excessive : risque de maladies fongiques (mildiou/oïdium). Espacez les irrigations pour freiner la croissance végétative."
            elif opt_evi_min is None and opt_evi_max is None:
                statut_evi = "Non Évalué"
                action_evi = "Aucune norme EVI officielle enregistrée."
            else:
                statut_evi = "Biomasse Conforme"
                action_evi = "Structure de la canopée satisfaisante, permettant une bonne pénétration de la lumière et de l'air."
                
            analyse_bioclimatique["biomasse_evi"] = {
                "actuelle": evi_actuel, "optimale_min": opt_evi_min, "optimale_max": opt_evi_max,
                "statut": statut_evi, "action_requise": action_evi
            }

            # 4. Bilan Hydrique Combiné
            radiation_solaire_moyenne = 15.0
            et0_quotidien = 0.0023 * radiation_solaire_moyenne * ((temp_max - temp_min)**0.5) * (temp_moy + 17.8)
            kc_stade = {"semis": 0.4, "croissance": 0.8, "floraison": 1.2, "maturité": 0.6}.get(data.stade_culture.value, 1.0)
            
            etc_brut = et0_quotidien * kc_stade
            besoin_quotidien_etc = max(0.0, round(etc_brut - pluie_du_jour, 1))
            besoin_brut_total = besoin_quotidien_etc
            
            if opt_ndwi_min is not None and ndwi_actuel < opt_ndwi_min:
                statut_hydrique = "Stress Hydrique Détecté"
                gravite = abs(opt_ndwi_min - ndwi_actuel)
                besoin_brut_total = round(besoin_quotidien_etc + (gravite * 50.0), 1)
                
                besoin_net_restant = max(0.0, round(besoin_brut_total - irrigation_deja_faite, 1))
                if besoin_net_restant > 0:
                    actions_hydriques = f"Déficit actuel. Apport de {besoin_net_restant} mm conseillé ({besoin_quotidien_etc} mm d'entretien + correction) pour remonter le NDWI."
                else:
                    actions_hydriques = "L'irrigation effectuée (ou la pluie) couvre le besoin météo et le déficit."
                    
            elif opt_ndwi_max is not None and ndwi_actuel > opt_ndwi_max:
                statut_hydrique = "Asphyxie Racinaire Risquée"
                besoin_brut_total = 0.0
                besoin_net_restant = 0.0
                actions_hydriques = f"Alerte : NDWI actuel ({round(ndwi_actuel, 3)}) dépasse la limite tolérée. Suspendez l'irrigation, sol engorgé."
            
            else:
                statut_hydrique = "Humidité Conforme / Mode Entretien"
                besoin_net_restant = max(0.0, round(besoin_brut_total - irrigation_deja_faite, 1))
                if besoin_net_restant > 0:
                    actions_hydriques = f"Humidité stable. Apportez {besoin_net_restant} mm pour compenser la consommation quotidienne (pluie naturelle déduite)."
                else:
                    actions_hydriques = f"Consommation journalière couverte (Pluie du jour : {pluie_du_jour} mm). Aucune irrigation requise."

            if opt_ndwi_min is not None and opt_ndwi_max is not None:
                ndwi_exige_str = f"Entre {opt_ndwi_min} et {opt_ndwi_max}"
            elif opt_ndwi_min is not None:
                ndwi_exige_str = f"Minimum {opt_ndwi_min}"
            elif opt_ndwi_max is not None:
                ndwi_exige_str = f"Maximum {opt_ndwi_max}"
            else:
                ndwi_exige_str = "Norme non spécifiée (Calcul basé sur ET0 pure)"

            recommandations_finales = [{"conseil": c["conseil"]} for c in conseils_pertinents[:5]]

            return {
                "commune": nettoyer_mojibake(commune_corrigee).capitalize(),
                "culture": nettoyer_mojibake(culture_corrigee).capitalize(),
                "stade_actuel": data.stade_culture.value,
                "analyse_satellitaire_reglementaire": analyse_bioclimatique,
                "bilan_hydrique": {
                    "ndwi_actuel": round(ndwi_actuel, 3),
                    "ndwi_optimale_min": opt_ndwi_min,
                    "ndwi_optimale_max": opt_ndwi_max,
                    "ndwi_optimal_exige": ndwi_exige_str,
                    "statut": statut_hydrique,
                    "besoin_total_calcule_mm": besoin_brut_total,
                    "irrigation_deja_effectuee_mm": irrigation_deja_faite,
                    "irrigation_restante_a_faire_mm": besoin_net_restant,
                    "volume_conseille_litres_par_m2": besoin_net_restant,
                    "actions_operationnelles": actions_hydriques
                },
                "recommandations_saisonnieres": recommandations_finales
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



def evaluer_conditions_maladie(causes_texte: str, meteo: dict, satellite: dict, optimal: dict) -> bool:
    """
    Évalue si les conditions actuelles/prévues déclenchent une maladie en croisant :
    1. Les conditions météo d'OpenWeather et les indices satellites (GEE).
    2. Les bornes physiologiques optimales de la culture (temp_min/max, hum_min/max, ndvi).
    3. L'analyse NLP des causes textuelles de la maladie.
    """
    if not causes_texte or causes_texte.lower() in ["none", "null", ""]:
        return True # Sécurité : si l'IA n'a pas trouvé de causes, on alerte par précaution.
        
    cause = sans_accents(str(causes_texte)).lower()
    
    # 1. Vulnérabilité Satellitaire (NDVI de GEE inférieur au seuil optimal)
    ndvi_opt_min = optimal.get('ndvi_optimal_min')
    if ndvi_opt_min is not None and satellite.get('ndvi', 0.5) < float(ndvi_opt_min):
        if any(mot in cause for mot in ["faiblesse", "carence", "vulnerable", "faible", "croissance"]):
            return True

    # 2. Excès d'eau (Humidité OpenWeather > hum_max optimale OU fortes pluies)
    hum_opt_max = optimal.get('hum_max') or 80.0
    if meteo.get("precipitations_mm", 0) > 0.5 or meteo.get("humidite_moyenne", 0) > float(hum_opt_max):
        if any(mot in cause for mot in ["pluie", "pluies", "humidite", "humide", "eau", "inondation", "stagnation"]):
            return True

    # 3. Stress Hydrique / Sécheresse (Humidité OpenWeather < hum_min optimale)
    hum_opt_min = optimal.get('hum_min') or 40.0
    if meteo.get("precipitations_mm", 0) <= 0.1 and meteo.get("humidite_moyenne", 100) < float(hum_opt_min):
        if any(mot in cause for mot in ["manque d'eau", "secheresse", "sec", "aridite"]):
            return True

    # 4. Stress Thermique / Chaleur (Température OpenWeather > temp_max_optimale)
    temp_opt_max = optimal.get('temp_max') or 30.0
    if meteo.get("temp_max", 0) > float(temp_opt_max) or meteo.get("temp_moyenne", 0) > float(temp_opt_max):
        if any(mot in cause for mot in ["chaleur", "temperature excessive", "extreme", "chaud", "insolation", "soleil", "brulure"]):
            return True

    # 5. Stress Thermique / Froid (Température OpenWeather < temp_min_optimale)
    temp_opt_min = optimal.get('temp_min') or 10.0
    if meteo.get("temp_min", 20) < float(temp_opt_min):
        if any(mot in cause for mot in ["froid", "gel", "gelee", "basses", "temperature inferieure", "hivernale"]):
            return True
            
    # 6. Stress Mécanique (Vents forts > 40 km/h)
    if meteo.get("vitesse_vent_kmh", 0) > 40.0:
        if any(mot in cause for mot in ["vent", "vents", "rafale", "rafales", "tempete", "dessechant", "ouragan", "casse"]):
            return True
            
    # 7. Facteurs externes non-climatiques (On a retiré "vent" d'ici)
    facteurs_externes = ["parasite", "parasites", "nutrition", "salinite", "salin", "fertilisation"]
    if any(mot in cause for mot in facteurs_externes):
        return True
        
    return False

@app.post("/predict-maladies")
def predict_maladies(data: MaladieInput):
    try:
        with engine.connect() as conn:
            commune_corrigee = valider_et_corriger_nom(data.nom_commune, 'commune', conn)
            culture_corrigee = valider_et_corriger_nom(data.nom_culture, 'culture', conn)
            
            if not commune_corrigee or not culture_corrigee:
                raise HTTPException(status_code=404, detail="Commune ou Culture introuvable.")

            parcelle_query = text("SELECT id FROM parcelles WHERE LOWER(commune) = LOWER(:commune) LIMIT 1;")
            p_res = conn.execute(parcelle_query, {"commune": commune_corrigee}).fetchone()
            parcelle_id = p_res.id if p_res else conn.execute(text("SELECT id FROM parcelles LIMIT 1;")).fetchone().id

            # --- 1. EXTRACTION DES SEUILS OPTIMAUX ---
            culture_query = text("""
                SELECT c.id, c.nom_culture, rto.temp_min, rto.temp_max, rto.hum_min, rto.hum_max,
                       c.ndvi_optimal_min, c.ndvi_optimal_max, c.ndwi_optimal_min, c.ndwi_optimal_max,
                       c.evi_optimal_min, c.evi_optimal_max
                FROM cultures c
                LEFT JOIN ref_temp_optimale rto ON c.temp_optimale_id = rto.id
                WHERE LOWER(c.nom_culture) = LOWER(:culture);
            """)
            cult_res = conn.execute(culture_query, {"culture": culture_corrigee}).fetchone()
            if not cult_res:
                raise HTTPException(status_code=404, detail=f"Culture '{data.nom_culture}' introuvable.")
                
            optimal_thresholds = dict(cult_res._mapping)

            # --- 2. EXTRACTION INDICES SATELLITAIRES (Pour évaluer la vulnérabilité actuelle) ---
            sat_query = text("SELECT ndvi, ndwi, evi FROM indices_satellites WHERE parcelle_id = :p_id ORDER BY date_capture DESC LIMIT 1")
            sat_res = conn.execute(sat_query, {"p_id": parcelle_id}).fetchone()
            indices_sat = {
                "ndvi": float(sat_res.ndvi) if sat_res and sat_res.ndvi else 0.5,
                "ndwi": float(sat_res.ndwi) if sat_res and sat_res.ndwi else 0.0,
                "evi": float(sat_res.evi) if sat_res and sat_res.evi else 0.3
            }

            # --- 3. EXTRACTION OPENWEATHER (Les 5 jours à venir) ---
            previsions_query = text("""
                SELECT pm.date_prevision, pm.temp_moyenne, pm.temp_min, pm.temp_max, pm.humidite_moyenne, pm.precipitations_mm, pm.vitesse_vent_kmh
                FROM previsions_meteo pm
                JOIN communes_maroc cm ON pm.commune_id = cm.id
                WHERE LOWER(cm.nom_commune) = LOWER(:commune) AND pm.date_prevision >= CURRENT_DATE
                ORDER BY pm.date_prevision ASC
                LIMIT 5; 
            """)
            prev_res = conn.execute(previsions_query, {"commune": commune_corrigee}).fetchall()
            
            if not prev_res:
                raise HTTPException(status_code=404, detail="Aucune prévision météo OpenWeather disponible.")

            # --- 4. RÉCUPÉRATION DES MALADIES DE LA CULTURE ---
            maladies_query = text("""
                SELECT m.nom_maladie, m.causes, 
                       t.nom_traitement, t.type_traitement, t.description as description_traitement
                FROM cultures c
                JOIN culture_maladie_details cmd ON cmd.culture_id = c.id
                JOIN maladies m ON m.id = cmd.maladie_id
                LEFT JOIN traitements t ON t.id = cmd.traitement_specifique_id
                WHERE c.id = :c_id;
            """)
            maladies_potentielles = conn.execute(maladies_query, {"c_id": cult_res.id}).fetchall()

            # --- 5. MOTEUR D'INFERENCE (100% PHYSIOLOGIE + NLP Lexical) ---
            jour_critique = None
            conditions_critiques = None
            alertes_dict = {}

            # On scanne chaque jour de la semaine
            for i, jour in enumerate(prev_res):
                meteo_jour = {
                    "temp_moyenne": float(jour.temp_moyenne),
                    "temp_max": float(jour.temp_max),
                    "temp_min": float(jour.temp_min),
                    "humidite_moyenne": float(jour.humidite_moyenne),
                    "precipitations_mm": float(jour.precipitations_mm),
                    "vitesse_vent_kmh": float(jour.vitesse_vent_kmh) if hasattr(jour, 'vitesse_vent_kmh') and jour.vitesse_vent_kmh else 0.0
                }

                # On teste la météo de ce jour contre TOUTES les maladies
                for m in maladies_potentielles:
                    if m.nom_maladie and "inconnu" in m.nom_maladie.lower():
                        continue
                        
                    causes_db = str(m.causes) if hasattr(m, 'causes') and m.causes else ""
                    
                    # 🧠 LE MOTEUR DYNAMIQUE PREND LE RELAIS ICI (avec optimal_thresholds)
                    causes_declencheuses = evaluer_causes_rapide(causes_db, meteo_jour, optimal_thresholds)
                    
                    if causes_declencheuses:
                        
                        # On mémorise le PREMIER jour critique trouvé
                        if not jour_critique:
                            jour_critique = f"J+{i} ({jour.date_prevision})"
                            conditions_critiques = meteo_jour
                            code_risque = 1

                        nom_maladie = m.nom_maladie
                        traitement_obj = {
                            "nom": nettoyer_mojibake(m.nom_traitement) or "Traitement préventif à définir"
                        }
                        if m.type_traitement: traitement_obj["type"] = nettoyer_mojibake(m.type_traitement)
                        if m.description_traitement: traitement_obj["details"] = nettoyer_mojibake(m.description_traitement)
                        
                        if nom_maladie not in alertes_dict:
                            alertes_dict[nom_maladie] = {
                                "maladie": nom_maladie, 
                                "facteurs_declencheurs_meteo": causes_declencheuses,
                                "causes_de_la_maladie": nettoyer_mojibake(causes_db), # <-- Modification ici
                                "prescriptions_traitements": [traitement_obj]
                            }
                        elif traitement_obj not in alertes_dict[nom_maladie]["prescriptions_traitements"]:
                            alertes_dict[nom_maladie]["prescriptions_traitements"].append(traitement_obj)

            # --- 6. RÉPONSE FINALE ---
            if not jour_critique:
                # Tout va bien
                conditions_critiques = {
                    "temp_moyenne": float(prev_res[0].temp_moyenne),
                    "temp_max": float(prev_res[0].temp_max),
                    "temp_min": float(prev_res[0].temp_min),
                    "humidite_moyenne": float(prev_res[0].humidite_moyenne),
                    "precipitations_mm": float(prev_res[0].precipitations_mm)
                }
                statut_final = "Prévisions saines sur les 5 prochains jours."
                code_risque = 0
            else:
                statut_final = f"Alerte : Conditions propices aux maladies détectées pour {jour_critique}"
                code_risque = 1

            return {
                "commune": nettoyer_mojibake(commune_corrigee).capitalize(),
                "culture": nettoyer_mojibake(culture_corrigee).capitalize(),
                "conditions_critiques_lag": conditions_critiques,
                "diagnostic_proactif": {
                    "statut": statut_final,
                    "jour_critique_estime": jour_critique or "Aucun"
                    # <-- code_risque et certitude_pourcent supprimés
                },
                "risques_et_traitements": list(alertes_dict.values()),
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- 3. UPLOAD ET SUPPRESSION (FICHIERS & DB) ---

PDF_DIR = "/app/FT_Vegetal"
FT_VEGETAL_DIR = r"C:\Users\USER\Desktop\smartfellah\FT_Vegetal"
FT_JSON_DATA_DIR = r"C:\Users\USER\Desktop\smartfellah\FT_Json_Data"
FT_CLEAN_DIR = r"C:\Users\USER\Desktop\smartfellah\FT_Clean"

@app.post("/upload-agri-document/", tags=["Ingestion"])
async def upload_document(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés.")
    
    os.makedirs(PDF_DIR, exist_ok=True)
    file_path = os.path.join(PDF_DIR, file.filename)
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la sauvegarde: {str(e)}")
        
    return {"status": "success", "message": f"Le fichier '{file.filename}' a été uploadé avec succès."}


@app.delete("/cultures/{nom_culture}")
def delete_culture_and_files(nom_culture: str, db: Session = Depends(get_db)):
    culture_corrigee = valider_et_corriger_nom(nom_culture, 'culture', db)
    
    if not culture_corrigee:
        raise HTTPException(status_code=404, detail=f"Culture '{nom_culture}' introuvable, même avec correction.")

    culture_query = text("SELECT id, nom_culture FROM cultures WHERE LOWER(nom_culture) = LOWER(:nom);")
    culture = db.execute(culture_query, {"nom": culture_corrigee}).fetchone()
    
    if not culture:
        raise HTTPException(status_code=404, detail=f"Culture '{nom_culture}' introuvable.")
    
    try:
        delete_query = text("DELETE FROM cultures WHERE id = :cid;")
        db.execute(delete_query, {"cid": culture.id})
        db.commit()
        
        culture_lower = culture_corrigee.lower()
        fichiers_supprimes = []
        
        paths = [
            (FT_VEGETAL_DIR, f"{culture_lower}.pdf", "FT_Vegetal"),
            (FT_JSON_DATA_DIR, f"{culture_lower}.json", "FT_Json_Data"),
            (FT_CLEAN_DIR, f"{culture_lower}.json", "FT_Clean")
        ]
        
        for dir_path, filename, folder_name in paths:
            file_path = os.path.join(dir_path, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                fichiers_supprimes.append(f"{folder_name}/{filename}")

        return {"status": "success", "message": f"La culture '{nom_culture}' a été supprimée.", "fichiers_physiques_supprimes": fichiers_supprimes}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erreur lors de la suppression : {str(e)}")