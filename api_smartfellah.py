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

ml_model = None
ml_features = None
disease_model = None
disease_features = None

# --- CONFIGURATION ---
DB_URL = "postgresql://admin:secretpassword@host.docker.internal:5432/bifolia_db"
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global ml_model, ml_features, disease_model, disease_features
    print("🚀 Démarrage de l'API SmartFellah...")
    try:
        # 1. Chargement du modèle Irrigation (Régression)
        ml_model = joblib.load("models/ndwi_forecaster.pkl")
        ml_features = joblib.load("models/features_list.pkl")
        print("✅ Modèle Irrigation (Random Forest) chargé !")
        
        # 2. Chargement du modèle Maladies (Classification)
        disease_model = joblib.load("models/disease_classifier.pkl")
        disease_features = joblib.load("models/disease_features.pkl")
        print("✅ Modèle Maladies (Classification RF) chargé !")
        
    except Exception as e:
        print(f"⚠️ Impossible de charger les modèles ML : {e}")
    yield
    print("🛑 Arrêt de l'API.")

app = FastAPI(title="SmartFellah Prediction API", lifespan=lifespan)

app = FastAPI(title="SmartFellah Prediction API", lifespan=lifespan)
router = APIRouter()

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

    # 🛡️ NOUVEAU : Nettoyage avant la validation de l'Enum
    @field_validator('stade_culture', mode='before')
    @classmethod
    def clean_stade(cls, v):
        if isinstance(v, str):
            return v.strip().lower() # Force " Floraison " à devenir "floraison"
        return v

class AssolementCommuneInput(BaseModel):
    nom_commune: str

    # On a retiré type_sol_parcelle du validateur
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
    """
    Vérifie le nom dans la base. S'il y a une faute de frappe, 
    trouve la correspondance la plus proche (ex: "framboisir" -> "Framboisier").
    """
    if type_recherche == 'commune':
        query = text("SELECT DISTINCT nom_commune FROM communes_maroc WHERE nom_commune IS NOT NULL")
    else:
        query = text("SELECT DISTINCT nom_culture FROM cultures WHERE nom_culture IS NOT NULL")
        
    resultats = conn.execute(query).fetchall()
    noms_db = [row[0] for row in resultats]
    
    # Création d'un dictionnaire pour lier la version minuscule au Vrai Nom de la DB
    noms_dict = {nom.lower(): nom for nom in noms_db}
    nom_saisi_lower = nom_saisi.lower()
    
    # 1. Correspondance exacte
    if nom_saisi_lower in noms_dict:
        return noms_dict[nom_saisi_lower]
        
    # 2. Correspondance approximative (Fuzzy Matching à 65% de ressemblance)
    correspondances = difflib.get_close_matches(nom_saisi_lower, noms_dict.keys(), n=1, cutoff=0.65)
    
    if correspondances:
        mot_trouve = correspondances[0]
        print(f"🛠️ Correction Auto : '{nom_saisi}' corrigé en '{noms_dict[mot_trouve]}'")
        return noms_dict[mot_trouve]
        
    # Si on ne trouve rien du tout
    return None


# --- 2. ENDPOINTS MÉTIER ---

@app.post("/recommend-crops-by-commune")
def recommend_crops_by_commune(data: AssolementCommuneInput):
    try:
        with engine.connect() as conn:
            commune_corrigee = valider_et_corriger_nom(data.nom_commune, 'commune', conn)
            if not commune_corrigee:
                raise HTTPException(status_code=404, detail=f"Commune '{data.nom_commune}' introuvable, même avec correction.")
            # 1. Extraction Météo de la Commune
            commune_query = text("""
                SELECT 
                    cm.nom_commune, cm.region, p.id as parcelle_id,
                    AVG(dm.temp_min) as temp_min_moy,
                    AVG(dm.temp_max) as temp_max_moy
                FROM communes_maroc cm
                LEFT JOIN parcelles p ON p.commune_id = cm.id OR LOWER(p.commune) = LOWER(cm.nom_commune)
                LEFT JOIN donnees_meteo dm ON dm.parcelle_id = p.id
                WHERE LOWER(cm.nom_commune) = LOWER(:commune)
                GROUP BY cm.nom_commune, cm.region, p.id;
            """)
            res_commune = conn.execute(commune_query, {"commune": commune_corrigee}).fetchone()

            # Gestion du Fallback si la commune n'a pas de capteurs
            is_fallback = False
            if not res_commune or res_commune.temp_min_moy is None:
                fallback_meteo = text("SELECT AVG(temp_min) as temp_min_moy, AVG(temp_max) as temp_max_moy FROM donnees_meteo;")
                meteo_res = conn.execute(fallback_meteo).fetchone()
                region_query = text("SELECT region, nom_commune FROM communes_maroc WHERE LOWER(nom_commune) = LOWER(:commune)")
                reg_res = conn.execute(region_query, {"commune": commune_corrigee}).fetchone()

                if not reg_res:
                    raise HTTPException(status_code=404, detail=f"Commune '{commune_corrigee}' introuvable.")

                nom_commune_trouvee = reg_res.nom_commune
                region_vraie = reg_res.region
                t_min_locale = float(meteo_res.temp_min_moy) if meteo_res and meteo_res.temp_min_moy else 12.0
                t_max_locale = float(meteo_res.temp_max_moy) if meteo_res and meteo_res.temp_max_moy else 28.0
                is_fallback = True
            else:
                nom_commune_trouvee = res_commune.nom_commune
                region_vraie = res_commune.region if res_commune.region else "Non spécifiée"
                t_min_locale = float(res_commune.temp_min_moy)
                t_max_locale = float(res_commune.temp_max_moy)

            # 2. NOUVELLE LOGIQUE SQL : Strict sur le climat (avec tolérance de 2°C)
            # La plante doit supporter un froid au moins égal au froid local (à 2°C près)
            # et une chaleur au moins égale à la chaleur locale.
            cultures_query = text("""
                SELECT c.nom_culture, rto.temp_min AS culture_temp_min, rto.temp_max AS culture_temp_max, res.libelle AS exigence_sol
                FROM cultures c
                JOIN ref_temp_optimale rto ON c.temp_optimale_id = rto.id
                LEFT JOIN ref_exigences_sol res ON c.exigence_sol_id = res.id
                WHERE rto.temp_min <= (:t_min + 2) 
                  AND rto.temp_max >= (:t_max - 2)
            """)
            cultures_compatibles = conn.execute(cultures_query, {"t_min": t_min_locale, "t_max": t_max_locale}).fetchall()

            if not cultures_compatibles:
                return {
                    "commune": nom_commune_trouvee.capitalize(),
                    "region": region_vraie,
                    "message": f"Aucune culture ne correspond strictement aux seuils climatiques stricts de {nom_commune_trouvee}.",
                }

            # 3. NOUVEAU CALCUL DU SCORE
            # Pour l'instant on enlève le "sableux" hardcodé, on le considérera "Inconnu" à moins qu'on ait l'info
            sol_local = "inconnu" 
            
            recommandations = []
            for row in cultures_compatibles:
                score = 100
                
                # Pénalité thermique : Si la plante est "limite" par rapport au climat, on baisse le score
                ecart_min = (t_min_locale - float(row.culture_temp_min))
                ecart_max = (float(row.culture_temp_max) - t_max_locale)
                
                # Si l'écart est très faible (la plante est proche de ses limites mortelles)
                if ecart_min < 2: score -= 15
                if ecart_max < 2: score -= 15

                exigence_sol = row.exigence_sol if row.exigence_sol else "Non spécifié"
                # Calcul de la compatibilité du sol
                if sol_local == "inconnu":
                    compatibilite_sol = "À vérifier sur le terrain"
                elif sol_local in exigence_sol.lower():
                    compatibilite_sol = "Optimale (Sol parfaitement adapté)"
                else:
                    compatibilite_sol = "Moyenne (Nécessite amendement)"
                    score -= 10 # On pénalise un peu si le sol ne correspond pas

                recommandations.append({
                    "culture": row.nom_culture.capitalize(),
                    "score_global_pourcent": max(0, score), # Empêche les scores négatifs
                    "compatibilite_sol": compatibilite_sol,
                    "limites_thermiques_reference": f"Min: {row.culture_temp_min}°C | Max: {row.culture_temp_max}°C",
                    "exigences_sol_detail": exigence_sol,
                })

            # On ne garde que les cultures qui ont un score > 70% et on les trie
            recommandations = [r for r in recommandations if r["score_global_pourcent"] >= 70]
            recommandations = sorted(recommandations, key=lambda x: x["score_global_pourcent"], reverse=True)

            avertissement = "Données basées sur la moyenne nationale car aucun capteur n'est actif dans cette commune." if is_fallback else "Basé sur les relevés des capteurs de la commune."

            return {
                "commune": nom_commune_trouvee.capitalize(),
                "region": region_vraie,
                "fiabilite_donnees": avertissement,
                "meteo_reelle_constatee": f"Min: {round(t_min_locale, 1)}°C | Max: {round(t_max_locale, 1)}°C",
                "recommandations_officielles": recommandations,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def traiter_et_trier_conseils(conseils, stade_actuel):
    """Nettoie les doublons sémantiques et filtre les conseils hors contexte."""
    priorite = {
        "urgence": 1,
        "urgent": 2,
        "normal": 3,
        "non urgent": 4
    }
    
    # 1. Tri par catégorie d'abord
    conseils.sort(key=lambda x: priorite.get(x['categorie'].lower(), 99))
    
    unique_conseils = []
    
    # 2. Définition des mots-clés à bannir selon le stade
    mots_exclus = []
    # Si on est en floraison ou maturité, on ne parle plus de planter ou de jeunes pousses
    if stade_actuel in ["floraison", "maturité"]:
        mots_exclus = ["plantation", "planter", "jeunes plants", "distance", "semis"]
        
    for c in conseils:
        texte_actuel = c['conseil'].lower()
        
        # Filtre 1 : Cohérence métier (On saute les conseils hors sujet)
        if any(mot in texte_actuel for mot in mots_exclus):
            continue
            
        # Filtre 2 : Similarité sémantique (Fuzzy matching)
        est_doublon = False
        for u in unique_conseils:
            texte_existant = u['conseil'].lower()
            # Calcule le ratio de ressemblance entre 0.0 et 1.0
            ratio = difflib.SequenceMatcher(None, texte_actuel, texte_existant).ratio()
            
            # Si le texte ressemble à 65% ou plus à un conseil déjà validé, c'est un doublon
            if ratio > 0.65: 
                est_doublon = True
                break
                
        if not est_doublon:
            unique_conseils.append(c)
            
    return unique_conseils
            
    # 3. Tri par catégorie de priorité
    unique_conseils.sort(key=lambda x: priorite.get(x['categorie'].lower(), 99))
    
    return unique_conseils


@app.post("/daily-advice")
def get_daily_advice(data: DailyAdviceInput):
    try:
        with engine.connect() as conn:
            commune_corrigee = valider_et_corriger_nom(data.nom_commune, 'commune', conn)
            culture_corrigee = valider_et_corriger_nom(data.nom_culture, 'culture', conn)
            
            if not commune_corrigee:
                raise HTTPException(status_code=404, detail=f"Commune '{data.nom_commune}' introuvable, même avec correction.")
            if not culture_corrigee:
                raise HTTPException(status_code=404, detail=f"Culture '{data.nom_culture}' introuvable, même avec correction.")
            # =======================================================

            # 1. Trouver la parcelle liée à la commune
            parcelle_query = text("SELECT id FROM parcelles WHERE LOWER(commune) = LOWER(:commune) LIMIT 1;")
            p_res = conn.execute(parcelle_query, {"commune": commune_corrigee}).fetchone()
            
            if not p_res:
                # Fallback : on prend la première parcelle dispo si la commune n'a pas de capteurs
                p_res = conn.execute(text("SELECT id FROM parcelles LIMIT 1;")).fetchone()
                
            parcelle_id = p_res.id

            # 2. Extraire les recommandations officielles de la culture
            culture_query = text("SELECT id FROM cultures WHERE LOWER(nom_culture) = LOWER(:culture);")
            cult_res = conn.execute(culture_query, {"culture": culture_corrigee}).fetchone()
            
            conseils_pertinents = []
            if cult_res:
                recos_query = text("SELECT description, status, categorie FROM recommandation WHERE culture_id = :c_id;")
                recos_res = conn.execute(recos_query, {"c_id": cult_res.id}).fetchall()
                
                # Liste brute
                conseils_bruts = [{"categorie": r.categorie, "status": r.status, "conseil": r.description} 
                                  for r in recos_res if r.description and "inconnu" not in r.description.lower()]
                
                # NETTOYAGE ET TRI ICI
                conseils_pertinents = traiter_et_trier_conseils(conseils_bruts, data.stade_culture.value)

            # 3. Extraction de l'historique (les 8 derniers jours pour calculer les Lags)
            history_query = text("""
                SELECT 
                    m.date_mesure, m.temp_moyenne, m.temp_max, m.temp_min, m.humidite_moyenne, m.precipitations_mm,
                    COALESCE(s.ndvi, 0.5) as ndvi, COALESCE(s.ndwi, 0.0) as ndwi,
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
                LIMIT 8
            """)
            
            df_hist = pd.read_sql(history_query, conn, params={"p_id": parcelle_id})
            
            if len(df_hist) < 8:
                raise HTTPException(status_code=404, detail="Pas assez d'historique météo .")

            # On remet dans l'ordre chronologique
            df_hist = df_hist.sort_values('date_mesure').reset_index(drop=True)
            
            # --- 4. PRÉPARATION ML EXACTEMENT COMME À L'ENTRAÎNEMENT ---
            df_hist['apport_eau_total'] = df_hist['precipitations_mm'] + df_hist['irrigation_mm']
            
            # Calcul des Lags (On ne le fait que sur ce petit dataset en mémoire)
            for lag in [1, 3, 7]:
                df_hist[f'temp_moy_lag_{lag}'] = df_hist['temp_moyenne'].shift(lag)
                df_hist[f'eau_total_cumul_{lag}j'] = df_hist['apport_eau_total'].rolling(lag).sum()
                df_hist[f'ndwi_lag_{lag}'] = df_hist['ndwi'].shift(lag)

            # On prend la TOUTE DERNIÈRE ligne (Aujourd'hui) qui contient tous les historiques remplis
            jour_actuel = df_hist.iloc[-1:]
            
            # Extraction des variables pures pour l'API
            temp_moy = float(jour_actuel['temp_moyenne'].iloc[0])
            pluie_jour = float(jour_actuel['precipitations_mm'].iloc[0])
            humidite = float(jour_actuel['humidite_moyenne'].iloc[0])
            irrigation_deja_faite = float(jour_actuel['irrigation_mm'].iloc[0])
            reference_meteo = str(jour_actuel['date_mesure'].iloc[0])

            # --- 5. INFÉRENCE(PREDICTION) ---
            if ml_model is not None and ml_features is not None:
                X_pred = jour_actuel[ml_features]
                ndwi_demain_pred = ml_model.predict(X_pred)[0]
            else:
                ndwi_demain_pred = 0.0 # Fallback si le modèle a planté au démarrage

            # 6. Interprétation du modèle : Ajustement selon le Stade de Culture (Kc)
            besoin_net = 0.0
            if ndwi_demain_pred < 0.1:
                # 6.1 Calcul du besoin de base selon la gravité du stress
                gravite = abs(min(0, ndwi_demain_pred - 0.1)) 
                besoin_net_base = 15.0 + (gravite * 50.0)
                
                # 6.2 Application du coefficient cultural (Kc) lié au stade
                coef_stade = 1.0
                stade = data.stade_culture.value
                
                if stade == "semis":
                    coef_stade = 0.6  # Moins d'eau au démarrage
                elif stade == "croissance":
                    coef_stade = 1.0  # Consommation standard
                elif stade == "floraison":
                    coef_stade = 1.3  # Pic critique, besoin maximal
                elif stade == "maturité":
                    coef_stade = 0.8  # Réduction avant récolte
                    
                besoin_net = round(besoin_net_base * coef_stade, 1)

            # 7. Ajout d'une recommandation dynamique basée sur le stade
            message_stade = f"Votre {data.nom_culture} est en phase de {data.stade_culture.value}. "
            if data.stade_culture.value == "floraison":
                message_stade += "Attention, c'est la période la plus critique. Maintenez une irrigation stricte pour éviter la chute des fleurs."
            elif data.stade_culture.value == "semis":
                message_stade += "Maintenez le sol humide mais sans excès pour ne pas noyer les jeunes racines."
            
            conseil_stade = {
                "categorie": "urgence",
                "status": "actif",
                "conseil": message_stade
            }
            
            # On insère ce conseil hyper-personnalisé tout en haut de la liste
            conseils_pertinents.insert(0, conseil_stade)

        return {
            "commune": commune_corrigee,
            "culture": culture_corrigee,
            "meteo_du_jour": {
                "reference_date": reference_meteo,
                "temperature_moyenne": round(temp_moy, 1),
                "pluie_mm": round(pluie_jour, 1),
                "humidite_moyenne": round(humidite, 1),
            },
            "suivi_operations_jour": {"irrigation_deja_effectuee_mm": round(irrigation_deja_faite, 1)},
            "prediction": {
                "ndwi_prevu_demain": round(float(ndwi_demain_pred), 3),
                "statut": "Stress Hydrique Détecté" if ndwi_demain_pred < 0.0 else "Sol Correctement Hydraté"
            },
            "module_irrigation": {
                "eau_a_apporter_mm": besoin_net, 
                "volume_conseille_litres_par_m2": besoin_net * 10
            },
            "recommandations_officielles": conseils_pertinents,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/predict-maladies")
def predict_maladies(data: MaladieInput):
    try:
        with engine.connect() as conn:
            # =======================================================
            # 🛡️ 1. CORRECTION ORTHOGRAPHIQUE AUTOMATIQUE
            # =======================================================
            commune_corrigee = valider_et_corriger_nom(data.nom_commune, 'commune', conn)
            culture_corrigee = valider_et_corriger_nom(data.nom_culture, 'culture', conn)
            
            if not commune_corrigee:
                raise HTTPException(status_code=404, detail=f"Commune '{data.nom_commune}' introuvable, même avec correction.")
            if not culture_corrigee:
                raise HTTPException(status_code=404, detail=f"Culture '{data.nom_culture}' introuvable, même avec correction.")

            # =======================================================
            # 2. Trouver la parcelle liée à la commune (On utilise la commune_corrigee !)
            # =======================================================
            parcelle_query = text("SELECT id FROM parcelles WHERE LOWER(commune) = LOWER(:commune) LIMIT 1;")
            p_res = conn.execute(parcelle_query, {"commune": commune_corrigee}).fetchone()
            
            if not p_res:
                p_res = conn.execute(text("SELECT id FROM parcelles LIMIT 1;")).fetchone()
            parcelle_id = p_res.id

            # 2. Extraire la culture
            culture_query = text("SELECT id, nom_culture FROM cultures WHERE LOWER(nom_culture) = LOWER(:culture);")
            cult_res = conn.execute(culture_query, {"culture": culture_corrigee}).fetchone()

            if not cult_res:
                raise HTTPException(status_code=404, detail=f"Culture '{data.nom_culture}' introuvable.")

            # 3. Extraction de l'historique Météo (les 3 derniers jours)
            history_query = text("""
                SELECT date_mesure, temp_moyenne, temp_max, temp_min, humidite_moyenne, precipitations_mm
                FROM donnees_meteo
                WHERE parcelle_id = :p_id
                ORDER BY date_mesure DESC
                LIMIT 3
            """)
            df_hist = pd.read_sql(history_query, conn, params={"p_id": parcelle_id})

            if df_hist.empty:
                raise HTTPException(status_code=404, detail="Aucune donnée météo disponible.")

            jour_actuel = df_hist.iloc[0] # Le jour le plus récent
            
            # =========================================================
            # VOICI LES VARIABLES QUI MANQUAIENT POUR LE JSON FINAL !
            # =========================================================
            t_moy = float(jour_actuel['temp_moyenne'])
            humidite = float(jour_actuel['humidite_moyenne'])
            pluie = float(jour_actuel['precipitations_mm'])
            # =========================================================

            
            # =======================================================
            # 4. EXTRACTION DES VRAIES PRÉVISIONS (REMPLIES PAR AIRFLOW)
            # =======================================================
            previsions_query = text("""
                SELECT pm.temp_moyenne, pm.temp_min, pm.temp_max, pm.humidite_moyenne, pm.precipitations_mm
                FROM previsions_meteo pm
                JOIN communes_maroc cm ON pm.commune_id = cm.id
                WHERE LOWER(cm.nom_commune) = LOWER(:commune)
                  AND pm.date_prevision > CURRENT_DATE
                ORDER BY pm.date_prevision ASC
                LIMIT 3;
            """)
            prev_res = conn.execute(previsions_query, {"commune": commune_corrigee}).fetchall()

            if len(prev_res) < 3:
                raise HTTPException(status_code=404, detail=f"Les prévisions météo d'Airflow pour '{commune_corrigee}' sont incomplètes ou manquantes.")

            # Calcul des agrégations sur le futur (J+1 à J+3) avec les vraies données
            temp_moy_3j_futur = sum(float(r.temp_moyenne) for r in prev_res) / 3
            hum_moy_3j_futur = sum(float(r.humidite_moyenne) for r in prev_res) / 3
            pluie_cumul_3j_futur = sum(float(r.precipitations_mm) for r in prev_res)

            # Extraction des données précises du 3ème jour (Horizon J+3)
            jour3 = prev_res[2]
            prev_temp_j3 = float(jour3.temp_moyenne)
            prev_temp_max_j3 = float(jour3.temp_max)
            prev_temp_min_j3 = float(jour3.temp_min)
            prev_hum_j3 = float(jour3.humidite_moyenne)
            prev_pluie_j3 = float(jour3.precipitations_mm)

            # 5. Prédiction de l'Intelligence Artificielle (SUR LA VRAIE MÉTÉO FUTURE)
            risque_maladie = 0
            proba_maladie = 0.0
            if disease_model is not None and disease_features is not None:
                X_pred = pd.DataFrame([{
                    'temp_moyenne': prev_temp_j3,
                    'temp_max': prev_temp_max_j3,
                    'temp_min': prev_temp_min_j3,
                    'humidite_moyenne': prev_hum_j3,
                    'precipitations_mm': prev_pluie_j3,
                    'hum_moy_3j': hum_moy_3j_futur,
                    'temp_moy_3j': temp_moy_3j_futur,
                    'pluie_cumul_3j': pluie_cumul_3j_futur
                }])[disease_features]
                
                risque_maladie = int(disease_model.predict(X_pred)[0])
                proba_maladie = float(disease_model.predict_proba(X_pred)[0][1])

            

            # 6. Si l'IA détecte un risque, on va chercher les traitements dans la base
            alertes_maladies = []
            if risque_maladie == 1:
                maladies_query = text("""
                    SELECT m.nom_maladie, t.nom_traitement, t.type_traitement, t.description as description_traitement
                    FROM cultures c
                    JOIN culture_maladie_details cmd ON cmd.culture_id = c.id
                    JOIN maladies m ON m.id = cmd.maladie_id
                    LEFT JOIN traitements t ON t.id = cmd.traitement_specifique_id
                    WHERE c.id = :c_id;
                """)
                maladies_potentielles = conn.execute(maladies_query, {"c_id": cult_res.id}).fetchall()

                alertes_dict = {}
                for m in maladies_potentielles:
                    if m.nom_maladie and "inconnu" in m.nom_maladie.lower():
                        continue
                    
                    nom_maladie = m.nom_maladie
                    traitement_obj = {
                        "nom": m.nom_traitement or "Traitement préventif à définir"
                    }

                    if m.type_traitement:
                        traitement_obj["type"] = m.type_traitement
                    if m.description_traitement:
                        traitement_obj["details"] = m.description_traitement
                    
                    if nom_maladie not in alertes_dict:
                        alertes_dict[nom_maladie] = {
                            "maladie": nom_maladie, 
                            "prescriptions_traitements": [traitement_obj]
                        }
                    elif traitement_obj not in alertes_dict[nom_maladie]["prescriptions_traitements"]:
                        alertes_dict[nom_maladie]["prescriptions_traitements"].append(traitement_obj)

                alertes_maladies = list(alertes_dict.values())

        return {
            "commune": commune_corrigee,
            "culture": culture_corrigee,
            "conditions_meteo_analysees": {
                "temperature_moyenne": round(t_moy, 1), 
                "humidite_moyenne": round(humidite, 1), 
                "precipitations_mm": round(pluie, 1)
            },
            "diagnostic": {
                "statut": "Risque Fongique Détecté" if risque_maladie == 1 else "Plante Saine",
                "code_risque": risque_maladie,
                "certitude_pourcent": round(proba_maladie * 100, 1) # Ajout de cette ligne
            },
            "risques_et_traitements": alertes_maladies,
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
    # =======================================================

    # Utilise culture_corrigee pour la requête
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