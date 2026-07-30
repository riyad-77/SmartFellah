from contextlib import asynccontextmanager
import os
import shutil
from enum import Enum
import requests # NOUVEAU: pour appeler Ollama
from fastapi import FastAPI, HTTPException, File, UploadFile, APIRouter, Depends
import pandas as pd
from pydantic import BaseModel, field_validator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

# --- CONFIGURATION ---
DATABASE_URL = "postgresql://admin:secretpassword@host.docker.internal:5432/bifolia_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# NOUVEAU: Configuration Ollama
# Si Ollama tourne sur ton PC Windows et l'API dans Docker, on utilise host.docker.internal
OLLAMA_URL = "http://host.docker.internal:11434/api/generate"
OLLAMA_MODEL = "llama3.2" 

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- FONCTION D'APPEL A OLLAMA ---
def demander_a_ollama(prompt: str, fallback_text: str) -> str:
    """Envoie un prompt à Ollama et retourne le texte généré. En cas d'erreur, retourne le fallback."""
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }
        # Timeout augmenté à 40 secondes au cas où Ollama prend du temps à charger
        response = requests.post(OLLAMA_URL, json=payload, timeout=60)
        response.raise_for_status()
        
        # On récupère le texte et on nettoie les guillemets ou espaces inutiles au début/fin
        text_result = response.json().get("response", "").strip(' \n"\'')
        
        return text_result if text_result else fallback_text
    except Exception as e:
        print(f"⚠️ Erreur Ollama: {e}")
        return fallback_text

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

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
        return v.strip().lower()

class AssolementCommuneInput(BaseModel):
    nom_commune: str

    @field_validator('nom_commune')
    @classmethod
    def clean_text(cls, v: str) -> str:
        return v.strip().lower()

class MaladieInput(BaseModel):
    nom_commune: str
    nom_culture: str

    @field_validator('nom_commune', 'nom_culture')
    @classmethod
    def clean_text(cls, v: str) -> str:
        return v.strip().lower()


# --- 2. ENDPOINTS MÉTIER ---

@app.post("/recommend-crops-by-commune")
def recommend_crops_by_commune(data: AssolementCommuneInput):
    # (Le code de cette route reste inchangé)
    try:
        with engine.connect() as conn:
            commune_query = text("""
                SELECT 
                    cm.nom_commune, 
                    cm.region,
                    p.id as parcelle_id,
                    AVG(dm.temp_min) as temp_min_moy,
                    AVG(dm.temp_max) as temp_max_moy
                FROM communes_maroc cm
                LEFT JOIN parcelles p ON p.commune_id = cm.id OR LOWER(p.commune) = LOWER(cm.nom_commune)
                LEFT JOIN donnees_meteo dm ON dm.parcelle_id = p.id
                WHERE LOWER(cm.nom_commune) = LOWER(:commune)
                GROUP BY cm.nom_commune, cm.region, p.id;
            """)
            res_commune = conn.execute(commune_query, {"commune": data.nom_commune}).fetchone()

            if not res_commune or res_commune.temp_min_moy is None:
                fallback_meteo = text("SELECT AVG(temp_min) as temp_min_moy, AVG(temp_max) as temp_max_moy FROM donnees_meteo;")
                meteo_res = conn.execute(fallback_meteo).fetchone()
                region_query = text("SELECT region, nom_commune FROM communes_maroc WHERE LOWER(nom_commune) = LOWER(:commune)")
                reg_res = conn.execute(region_query, {"commune": data.nom_commune}).fetchone()

                if not reg_res:
                    raise HTTPException(status_code=404, detail=f"Commune '{data.nom_commune}' introuvable.")

                nom_commune_trouvee = reg_res.nom_commune
                region_vraie = reg_res.region
                t_min_locale = float(meteo_res.temp_min_moy) if meteo_res and meteo_res.temp_min_moy else 12.0
                t_max_locale = float(meteo_res.temp_max_moy) if meteo_res and meteo_res.temp_max_moy else 28.0
            else:
                nom_commune_trouvee = res_commune.nom_commune
                region_vraie = res_commune.region if res_commune.region else "Non spécifiée"
                t_min_locale = float(res_commune.temp_min_moy)
                t_max_locale = float(res_commune.temp_max_moy)

            sol_local = "sableux"

            cultures_query = text("""
                SELECT c.nom_culture, rto.temp_min AS culture_temp_min, rto.temp_max AS culture_temp_max, res.libelle AS exigence_sol
                FROM cultures c
                JOIN ref_temp_optimale rto ON c.temp_optimale_id = rto.id
                LEFT JOIN ref_exigences_sol res ON c.exigence_sol_id = res.id
                WHERE rto.temp_min <= :t_max AND rto.temp_max >= :t_min
            """)
            cultures_compatibles = conn.execute(cultures_query, {"t_min": t_min_locale, "t_max": t_max_locale}).fetchall()

            if not cultures_compatibles:
                return {
                    "commune": nom_commune_trouvee.capitalize(),
                    "region": region_vraie,
                    "message": f"Aucune culture ne correspond strictement aux seuils climatiques de {nom_commune_trouvee}.",
                }

            recommandations = []
            for row in cultures_compatibles:
                score = 60
                exigence_sol = row.exigence_sol if row.exigence_sol else "Non spécifié"
                compatibilite_sol = "Standard"
                if sol_local.lower() in exigence_sol.lower():
                    score += 40
                    compatibilite_sol = "Optimale (Sol parfaitement adapté)"
                else:
                    score += 20
                    compatibilite_sol = "Moyenne (Nécessite amendement)"

                recommandations.append({
                    "culture": row.nom_culture.capitalize(),
                    "score_global_pourcent": score,
                    "compatibilite_sol": compatibilite_sol,
                    "limites_thermiques_reference": f"Min: {row.culture_temp_min}°C | Max: {row.culture_temp_max}°C",
                    "exigences_sol_detail": exigence_sol,
                })

            recommandations = sorted(recommandations, key=lambda x: x["score_global_pourcent"], reverse=True)

            return {
                "commune": nom_commune_trouvee.capitalize(),
                "region": region_vraie,
                "meteo_reelle_constatee": f"Min: {round(t_min_locale, 1)}°C | Max: {round(t_max_locale, 1)}°C",
                "recommandations_officielles": recommandations,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/daily-advice")
def get_daily_advice(data: DailyAdviceInput):
    try:
        with engine.connect() as conn:
            meteo_query = text("SELECT dm.temp_moyenne, dm.humidite_moyenne, dm.precipitations_mm, dm.date_mesure, dm.parcelle_id FROM donnees_meteo dm ORDER BY dm.date_mesure DESC LIMIT 1;")
            meteo_res = conn.execute(meteo_query).fetchone()

            if not meteo_res or meteo_res.temp_moyenne is None:
                raise HTTPException(status_code=404, detail="Aucune donnée météo disponible.")

            temp_moy, humidite, pluie_jour = float(meteo_res.temp_moyenne), float(meteo_res.humidite_moyenne), float(meteo_res.precipitations_mm)
            reference_meteo = str(meteo_res.date_mesure)
            parcelle_id = meteo_res.parcelle_id

            irrigation_deja_faite_mm = 0.0
            if parcelle_id:
                op_query = text("SELECT SUM(quantite) as total FROM operations_agricoles WHERE parcelle_id = :p_id AND LOWER(type_operation) LIKE '%irrigation%' AND date_operation >= CURRENT_DATE;")
                op_res = conn.execute(op_query, {"p_id": parcelle_id}).fetchone()
                if op_res and op_res.total: irrigation_deja_faite_mm = float(op_res.total)

            culture_query = text("SELECT c.id, c.nom_culture, res.libelle as sol, rbh.libelle as eau FROM cultures c LEFT JOIN ref_exigences_sol res ON c.exigence_sol_id = res.id LEFT JOIN ref_besoins_hydriques rbh ON c.besoin_hydrique_id = rbh.id WHERE LOWER(c.nom_culture) = LOWER(:culture);")
            cult_res = conn.execute(culture_query, {"culture": data.nom_culture}).fetchone()

            if not cult_res:
                raise HTTPException(status_code=404, detail=f"Culture '{data.nom_culture}' introuvable.")

            recos_query = text("SELECT description, status, categorie FROM recommandation WHERE culture_id = :c_id;")
            recos_res = conn.execute(recos_query, {"c_id": cult_res.id}).fetchall()

            conseils_pertinents = [{"categorie": r.categorie, "status": r.status, "conseil": r.description} 
                                   for r in recos_res
                                   if r.description and "inconnu" not in r.description.lower()
            ]

        et0_base = max(2.0, (temp_moy * 0.15) * (1.0 - (humidite / 200.0)))
        kc = {"semis": 0.4, "croissance": 0.8, "floraison": 1.15, "maturité": 0.6}.get(data.stade_culture.lower(), 0.7)
        besoin_net = max(0.0, round((et0_base * kc) - pluie_jour - irrigation_deja_faite_mm, 1))

        # --- REFORMULATION DIRECTE SANS INTRODUCTIONS ---
        for conseil in conseils_pertinents:
            prompt_conseil = f"""agit comme un expert agricole marocain, chaque chose generee par vous doit etre basee sur les donnees de PostgreSQL et PostGIS et le donnees en input dans FASTAPI. 
            Reformule ce conseil agricole de manière très simple et actionnable : '{conseil['conseil']}'. 
            Fais une seule phrase directe. 
            RÈGLE ABSOLUE : Tu as l'interdiction stricte de commencer ta phrase par une salutation, une accroche ou d'interpeller l'agriculteur (ne dis JAMAIS 'Salut fellah', 'Fellah, écoute bien', etc.). 
            Commence directement par le verbe ou le sujet. Utilise l'infinitif en début de phrase (ex: Irriguer, Fertiliser). Ne dis pas que tu es une IA. Ne mentionne JAMAIS tes sources, ni l'IA, ni FastAPI, ni PostgreSQL, ni la base de données. Donne juste le conseil.
            """
            conseil['conseil'] = demander_a_ollama(prompt_conseil, fallback_text=conseil['conseil'])

        return {
            "commune": data.nom_commune.capitalize(),
            "culture": data.nom_culture.capitalize(),
            "stade_culture": data.stade_culture,
            "meteo_du_jour": {
                "reference_date": reference_meteo,
                "temperature_moyenne": round(temp_moy, 1),
                "pluie_mm": round(pluie_jour, 1),
                "humidite_moyenne": round(humidite, 1),
            },
            "suivi_operations_jour": {"irrigation_deja_effectuee_mm": round(irrigation_deja_faite_mm, 1)},
            "module_irrigation": {"eau_a_apporter_mm": besoin_net, "volume_conseille_litres_par_m2": besoin_net * 10},
            "recommandations_officielles": conseils_pertinents,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/predict-maladies")
def predict_maladies(data: MaladieInput):
    try:
        with engine.connect() as conn:
            meteo_query = text("SELECT temp_moyenne, temp_min, temp_max, humidite_moyenne, precipitations_mm, date_mesure FROM donnees_meteo ORDER BY date_mesure DESC LIMIT 1;")
            meteo_res = conn.execute(meteo_query).fetchone()

            if not meteo_res or meteo_res.temp_moyenne is None:
                raise HTTPException(status_code=404, detail="Aucune donnée météo disponible.")

            t_moy = float(meteo_res.temp_moyenne)
            humidite = float(meteo_res.humidite_moyenne) if meteo_res.humidite_moyenne is not None else 50.0
            pluie = float(meteo_res.precipitations_mm) if meteo_res.precipitations_mm is not None else 0.0

            culture_query = text("SELECT id, nom_culture FROM cultures WHERE LOWER(nom_culture) = LOWER(:culture);")
            cult_res = conn.execute(culture_query, {"culture": data.nom_culture}).fetchone()

            if not cult_res:
                raise HTTPException(status_code=404, detail=f"Culture '{data.nom_culture}' introuvable.")
            
            maladies_query = text("""
                SELECT m.nom_maladie, m.temp_min_declenchement, m.temp_max_declenchement, m.humidite_min_declenchement, m.precipitations_min_declenchement, t.nom_traitement, t.type_traitement, t.description as description_traitement
                FROM cultures c
                JOIN culture_maladie_details cmd ON cmd.culture_id = c.id
                JOIN maladies m ON m.id = cmd.maladie_id
                LEFT JOIN traitements t ON t.id = cmd.traitement_specifique_id
                WHERE c.id = :c_id;
            """)
            maladies_potentielles = conn.execute(maladies_query, {"c_id": cult_res.id}).fetchall()

            alertes_dict = {}
            for m in maladies_potentielles:
                risque_detecte = True
                if (m.nom_maladie and "inconnu" in m.nom_maladie.lower()) or (m.nom_traitement and "incongru" in m.nom_traitement.lower()):
                    continue
                risque_detecte = True
                if m.temp_min_declenchement is not None and t_moy < float(m.temp_min_declenchement): risque_detecte = False
                if m.temp_max_declenchement is not None and t_moy > float(m.temp_max_declenchement): risque_detecte = False
                if m.humidite_min_declenchement is not None and humidite < float(m.humidite_min_declenchement): risque_detecte = False
                if m.precipitations_min_declenchement is not None and pluie < float(m.precipitations_min_declenchement) and humidite < 80.0: risque_detecte = False

                if risque_detecte:
                    nom_maladie = m.nom_maladie
                    traitement_obj = {
                        "nom": m.nom_traitement or "Traitement préventif global",
                        "type": m.type_traitement or "Préventif",
                        "details_bruts": m.description_traitement or "Surveiller la parcelle."
                    }
                    if nom_maladie not in alertes_dict:
                        alertes_dict[nom_maladie] = {"maladie": nom_maladie, "niveau_de_risque": "Élevé", "prescriptions_traitements": [traitement_obj]}
                    elif traitement_obj not in alertes_dict[nom_maladie]["prescriptions_traitements"]:
                        alertes_dict[nom_maladie]["prescriptions_traitements"].append(traitement_obj)

            alertes_maladies = list(alertes_dict.values())

        # --- NOUVEAU PROMPT PRÉVENTIF SANS BLABLA ---
        for alerte in alertes_maladies:
            for traitement in alerte["prescriptions_traitements"]:
                prompt_traitement = f"""agit comme un expert agricole marocain, chaque chose generee par vous doit etre basee sur les donnees de PostgreSQL et PostGIS et le donnees en input dans FASTAPI.
                La météo actuelle favorise l'apparition de '{alerte['maladie']}' sur la culture de {data.nom_culture}, mais la plante n'est pas encore malade.
                Le traitement recommandé est : '{traitement['nom']}' (Détails : {traitement.pop('details_bruts')}).
                Explique très simplement en 2 phrases maximum l'action PRÉVENTIVE à réaliser.
                RÈGLE ABSOLUE : Commence ta phrase directement par le conseil. Utilise l'infinitif en début de phrase (ex: Irriguer, Fertiliser). Tu as l'interdiction stricte de mettre une formule d'introduction ou d'interpeller le lecteur (JAMAIS de "Salut", "Fellah", "Écoute bien", etc.). Pas de guillemets. Ne mentionne JAMAIS tes sources, ni l'IA, ni FastAPI, ni PostgreSQL, ni la base de données. Donne juste le conseil.
                """
                
                traitement["details"] = demander_a_ollama(prompt_traitement, fallback_text="Surveillez la parcelle et appliquez ce traitement préventif dès maintenant pour protéger vos plantes.").replace('\n', ' ')

        return {
            "commune": data.nom_commune.capitalize(),
            "culture": data.nom_culture.capitalize(),
            "conditions_meteo_analysees": {"temperature_moyenne": t_moy, "humidite_moyenne": humidite, "precipitations_mm": pluie},
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
    culture_query = text("SELECT id, nom_culture FROM cultures WHERE LOWER(nom_culture) = LOWER(:nom);")
    culture = db.execute(culture_query, {"nom": nom_culture}).fetchone()
    
    if not culture:
        raise HTTPException(status_code=404, detail=f"Culture '{nom_culture}' introuvable.")
    
    try:
        delete_query = text("DELETE FROM cultures WHERE id = :cid;")
        db.execute(delete_query, {"cid": culture.id})
        db.commit()
        
        culture_lower = nom_culture.lower()
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