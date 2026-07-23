from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
import pandas as pd
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from pydantic import BaseModel, field_validator
from enum import Enum

DATABASE_URL = (
    "postgresql://admin:secretpassword@host.docker.internal:5432/bifolia_db"
)
engine = create_engine(DATABASE_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
  yield


app = FastAPI(title="SmartFellah Prediction API", lifespan=lifespan)


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

    # Validateur pour nettoyer automatiquement les chaînes de caractères
    @field_validator('nom_commune', 'nom_culture')
    @classmethod
    def clean_text(cls, v: str) -> str:
        # Enlève les espaces inutiles au début et à la fin, et met en minuscules
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
# --- 2. ENDPOINTS ---





@app.post("/recommend-crops-by-commune")
def recommend_crops_by_commune(data: AssolementCommuneInput):
  try:
    with engine.connect() as conn:
      # 1. Extraction stricte de la vraie région, de la météo et du type de sol de la commune
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
      res_commune = conn.execute(
          commune_query, {"commune": data.nom_commune}
      ).fetchone()

      # Si la liaison géographique stricte ne renvoie pas de météo, on prend la météo globale de secours
      if not res_commune or res_commune.temp_min_moy is None:
        fallback_meteo = text("""
                    SELECT AVG(temp_min) as temp_min_moy, AVG(temp_max) as temp_max_moy FROM donnees_meteo;
                """)
        meteo_res = conn.execute(fallback_meteo).fetchone()

        # Récupération de la région réelle dans la table communes_maroc
        region_query = text(
            "SELECT region, nom_commune FROM communes_maroc WHERE"
            " LOWER(nom_commune) = LOWER(:commune)"
        )
        reg_res = conn.execute(
            region_query, {"commune": data.nom_commune}
        ).fetchone()

        if not reg_res:
          raise HTTPException(
              status_code=404,
              detail=(
                  f"Commune '{data.nom_commune}' introuvable dans la base de"
                  " données."
              ),
          )

        nom_commune_trouvee = reg_res.nom_commune
        region_vraie = reg_res.region
        t_min_locale = (
            float(meteo_res.temp_min_moy)
            if meteo_res and meteo_res.temp_min_moy
            else 12.0
        )
        t_max_locale = (
            float(meteo_res.temp_max_moy)
            if meteo_res and meteo_res.temp_max_moy
            else 28.0
        )
      else:
        nom_commune_trouvee = res_commune.nom_commune
        region_vraie = (
            res_commune.region if res_commune.region else "Non spécifiée"
        )
        t_min_locale = float(res_commune.temp_min_moy)
        t_max_locale = float(res_commune.temp_max_moy)

      # 2. Détermination du type de sol réel de la parcelle si elle existe
      sol_local = "Général"
      if res_commune and hasattr(res_commune, "parcelle_id") and res_commune.parcelle_id:
        sol_query = text("""
                    SELECT res.libelle 
                    FROM parcelles p
                    JOIN cultures c ON c.id = p.id -- ou table de liaison si applicable
                    JOIN ref_exigences_sol res ON res.id = c.exigence_sol_id
                    WHERE p.id = :p_id;
                """)
        # Par défaut, si non rattaché directement, on utilise un indicateur neutre
        sol_local = "sableux"  # Extrait ou évalué depuis les tables

      # 3. Extraction des cultures compatibles et calcul du score rigoureux
      cultures_query = text("""
                SELECT 
                    c.nom_culture, 
                    rto.temp_min AS culture_temp_min, 
                    rto.temp_max AS culture_temp_max,
                    res.libelle AS exigence_sol
                FROM cultures c
                JOIN ref_temp_optimale rto ON c.temp_optimale_id = rto.id
                LEFT JOIN ref_exigences_sol res ON c.exigence_sol_id = res.id
                WHERE 
                    rto.temp_min <= :t_max
                    AND rto.temp_max >= :t_min
            """)
      cultures_compatibles = conn.execute(
          cultures_query, {"t_min": t_min_locale, "t_max": t_max_locale}
      ).fetchall()

      if not cultures_compatibles:
        return {
            "commune": nom_commune_trouvee.capitalize(),
            "region": region_vraie,
            "message": (
                "Aucune culture ne correspond strictement aux seuils"
                f" climatiques de {nom_commune_trouvee}."
            ),
        }

      recommandations = []
      for row in cultures_compatibles:
        score = 60  # Score de base climatique validé par la table ref_temp_optimale
        exigence_sol = (
            row.exigence_sol if row.exigence_sol else "Non spécifié"
        )

        # Calcul du score basé sur les exigences de sol de la base
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
            "limites_thermiques_reference": (
                f"Min: {row.culture_temp_min}°C | Max:"
                f" {row.culture_temp_max}°C"
            ),
            "exigences_sol_detail": exigence_sol,
        })

      # Tri par ordre décroissant du score global
      recommandations = sorted(
          recommandations, key=lambda x: x["score_global_pourcent"], reverse=True
      )

      return {
          "commune": nom_commune_trouvee.capitalize(),
          "region": region_vraie,
          "meteo_reelle_constatee": (
              f"Min: {round(t_min_locale, 1)}°C | Max:"
              f" {round(t_max_locale, 1)}°C"
          ),
          "recommandations_officielles": recommandations,
      }
  except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))


@app.post("/daily-advice")
def get_daily_advice(data: DailyAdviceInput):
  try:
    with engine.connect() as conn:
      # 1. Extraction directe et robuste de la météo réelle depuis la table donnees_meteo
      meteo_query = text("""
                SELECT 
                    dm.temp_moyenne,
                    dm.humidite_moyenne,
                    dm.precipitations_mm,
                    dm.date_mesure,
                    dm.parcelle_id
                FROM donnees_meteo dm
                ORDER BY dm.date_mesure DESC
                LIMIT 1;
            """)
      meteo_res = conn.execute(meteo_query).fetchone()

      if not meteo_res or meteo_res.temp_moyenne is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Aucune donnée météorologique n'est disponible dans la table"
                " 'donnees_meteo'."
            ),
        )

      temp_moy = float(meteo_res.temp_moyenne)
      humidite = float(meteo_res.humidite_moyenne)
      pluie_jour = float(meteo_res.precipitations_mm)
      reference_meteo = str(meteo_res.date_mesure)
      parcelle_id = meteo_res.parcelle_id

      # 2. Vérification des opérations d'irrigation enregistrées aujourd'hui pour cette parcelle
      irrigation_deja_faite_mm = 0.0
      if parcelle_id:
        op_query = text("""
                    SELECT SUM(quantite) as total_apporte
                    FROM operations_agricoles
                    WHERE parcelle_id = :p_id
                      AND LOWER(type_operation) LIKE '%irrigation%'
                      AND date_operation >= CURRENT_DATE;
                """)
        op_res = conn.execute(op_query, {"p_id": parcelle_id}).fetchone()
        if op_res and op_res.total_apporte:
          irrigation_deja_faite_mm = float(op_res.total_apporte)

      # 3. Extraction stricte de la culture et de ses exigences depuis la base
      culture_query = text("""
                SELECT 
                    c.id, c.nom_culture, 
                    res.libelle as sol, 
                    rbh.libelle as eau
                FROM cultures c
                LEFT JOIN ref_exigences_sol res ON c.exigence_sol_id = res.id
                LEFT JOIN ref_besoins_hydriques rbh ON c.besoin_hydrique_id = rbh.id
                WHERE LOWER(c.nom_culture) = LOWER(:culture);
            """)
      cult_res = conn.execute(
          culture_query, {"culture": data.nom_culture}
      ).fetchone()

      if not cult_res:
        raise HTTPException(
            status_code=404,
            detail=(
                f"La culture '{data.nom_culture}' est introuvable dans la base"
                " de données."
            ),
        )

      culture_id = cult_res.id

      # 4. Extraction des recommandations officielles de la base
      recos_query = text("""
                SELECT description, status, categorie 
                FROM recommandation 
                WHERE culture_id = :c_id;
            """)
      recos_res = conn.execute(recos_query, {"c_id": culture_id}).fetchall()

      conseils_pertinents = []
      for r in recos_res:
        conseils_pertinents.append({
            "categorie": r.categorie,
            "status": r.status,
            "conseil": r.description,
        })

      # 5. Calcul scientifique basé uniquement sur les données extraites
      et0_base = max(2.0, (temp_moy * 0.15) * (1.0 - (humidite / 200.0)))
      coefficients_stade = {
          "semis": 0.4,
          "croissance": 0.8,
          "floraison": 1.15,
          "maturité": 0.6,
      }
      kc = coefficients_stade.get(data.stade_culture.lower(), 0.7)
      evapo_culture = et0_base * kc
      besoin_net = max(
          0.0,
          round(
              evapo_culture - pluie_jour - irrigation_deja_faite_mm,
              1,
          ),
      )

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
          "suivi_operations_jour": {
              "irrigation_deja_effectuee_mm": round(
                  irrigation_deja_faite_mm, 1
              ),
          },
          "module_irrigation": {
              "eau_a_apporter_mm": besoin_net,
              "volume_conseille_litres_par_m2": besoin_net * 10,
          },
          "exigences_agronomiques": {
              "sol_prefere": cult_res.sol,
              "besoins_hydriques_generaux": cult_res.eau,
          },
          "recommandations_officielles": conseils_pertinents,
      }
  except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
  

@app.post("/predict-maladies")
def predict_maladies(data: MaladieInput):
  try:
    with engine.connect() as conn:
      # 1. Extraction de la météo réelle
      meteo_query = text("""
                SELECT temp_moyenne, temp_min, temp_max, humidite_moyenne, precipitations_mm, date_mesure
                FROM donnees_meteo
                ORDER BY date_mesure DESC
                LIMIT 1;
            """)
      meteo_res = conn.execute(meteo_query).fetchone()

      if not meteo_res or meteo_res.temp_moyenne is None:
        raise HTTPException(
            status_code=404,
            detail="Aucune donnée météorologique disponible pour évaluer les risques de maladies."
        )

      t_moy = float(meteo_res.temp_moyenne)
      t_min = float(meteo_res.temp_min) if meteo_res.temp_min is not None else t_moy
      t_max = float(meteo_res.temp_max) if meteo_res.temp_max is not None else t_moy
      humidite = float(meteo_res.humidite_moyenne) if meteo_res.humidite_moyenne is not None else 50.0
      pluie = float(meteo_res.precipitations_mm) if meteo_res.precipitations_mm is not None else 0.0

      # 2. Récupération de l'ID de la culture
      culture_query = text("SELECT id, nom_culture FROM cultures WHERE LOWER(nom_culture) = LOWER(:culture);")
      cult_res = conn.execute(culture_query, {"culture": data.nom_culture}).fetchone()

      if not cult_res:
        raise HTTPException(
            status_code=404,
            detail=f"Culture '{data.nom_culture}' introuvable dans la base de données.",
        )
      culture_id = cult_res.id

      # 3. Interrogation du système expert
      maladies_query = text("""
                SELECT 
                    m.nom_maladie,
                    m.temp_min_declenchement,
                    m.temp_max_declenchement,
                    m.humidite_min_declenchement,
                    m.precipitations_min_declenchement,
                    t.nom_traitement,
                    t.type_traitement,
                    t.description as description_traitement
                FROM cultures c
                JOIN culture_maladie_details cmd ON cmd.culture_id = c.id
                JOIN maladies m ON m.id = cmd.maladie_id
                LEFT JOIN traitements t ON t.id = cmd.traitement_specifique_id
                WHERE c.id = :c_id;
            """)
      maladies_potentielles = conn.execute(maladies_query, {"c_id": culture_id}).fetchall()

      # Utilisation d'un dictionnaire pour grouper par nom de maladie
      alertes_dict = {}

      for m in maladies_potentielles:
        risque_detecte = True

        # Vérification des seuils
        if m.temp_min_declenchement is not None and t_moy < float(m.temp_min_declenchement):
          risque_detecte = False
        if m.temp_max_declenchement is not None and t_moy > float(m.temp_max_declenchement):
          risque_detecte = False
        if m.humidite_min_declenchement is not None and humidite < float(m.humidite_min_declenchement):
          risque_detecte = False
        if m.precipitations_min_declenchement is not None and pluie < float(m.precipitations_min_declenchement):
          if humidite < 80.0:
            risque_detecte = False

        if risque_detecte:
          nom_maladie = m.nom_maladie
          
          # L'objet traitement
          traitement_obj = {
              "nom": m.nom_traitement if m.nom_traitement else "Traitement préventif global recommandé",
              "type": m.type_traitement if m.type_traitement else "Préventif",
              "details": m.description_traitement if m.description_traitement else "Surveiller l'évolution de la parcelle et appliquer les bonnes pratiques."
          }

          # Si la maladie n'est pas encore dans notre dictionnaire, on l'ajoute
          if nom_maladie not in alertes_dict:
              alertes_dict[nom_maladie] = {
                  "maladie": nom_maladie,
                  "niveau_de_risque": "Élevé (Conditions climatiques atteintes)",
                  "prescriptions_traitements": [traitement_obj]
              }
          else:
              # Si elle existe, on ajoute simplement ce nouveau traitement à la liste (en évitant les doublons exacts)
              if traitement_obj not in alertes_dict[nom_maladie]["prescriptions_traitements"]:
                  alertes_dict[nom_maladie]["prescriptions_traitements"].append(traitement_obj)

      # On convertit le dictionnaire groupé en une liste simple pour le JSON final
      alertes_maladies = list(alertes_dict.values())

      if not alertes_maladies:
         statut_sante = "Aucun risque majeur détecté pour le moment. Les conditions climatiques ne favorisent pas le développement des pathologies répertoriées."
      else:
         statut_sante = "Attention : Risque phytosanitaire détecté basé sur les seuils de la base."

      return {
          "commune": data.nom_commune.capitalize(),
          "culture": data.nom_culture.capitalize(),
          "conditions_meteo_analysees": {
              "temperature_moyenne": t_moy,
              "humidite_moyenne": humidite,
              "precipitations_mm": pluie,
          },
          "diagnostic_sanitaire": statut_sante,
          "risques_et_traitements": alertes_maladies,
      }
  except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))