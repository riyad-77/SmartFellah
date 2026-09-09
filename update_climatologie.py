from sqlalchemy import create_engine, text

DB_URL = "postgresql://admin:secretpassword@localhost:5432/bifolia_db"
engine = create_engine(DB_URL)

print("🔄 Calcul de la climatologie locale à partir de la base de données...")

query_mise_a_jour = text("""
    WITH stats_combinees AS (
        -- 1. Récupération des extrêmes depuis les capteurs (Historique)
        SELECT 
            cm.id as commune_id,
            dm.temp_min, dm.temp_max, 
            dm.humidite_moyenne as hum_min, dm.humidite_moyenne as hum_max
        FROM donnees_meteo dm
        JOIN parcelles p ON dm.parcelle_id = p.id
        JOIN communes_maroc cm ON p.commune_id = cm.id OR LOWER(p.commune) = LOWER(cm.nom_commune)
        
        UNION ALL
        
        -- 2. Récupération des extrêmes depuis Airflow (Prévisions)
        SELECT 
            commune_id,
            temp_min, temp_max, 
            humidite_moyenne as hum_min, humidite_moyenne as hum_max
        FROM previsions_meteo
    ),
    agregation_finale AS (
        -- 3. On prend le Min absolu et le Max absolu de TOUT ce qu'on a trouvé
        SELECT 
            commune_id,
            MIN(temp_min) as t_min,
            MAX(temp_max) as t_max,
            MIN(hum_min) as h_min,
            MAX(hum_max) as h_max
        FROM stats_combinees
        GROUP BY commune_id
    )
    -- 4. Injection dans la table commune
    UPDATE communes_maroc cm
    SET 
        temp_min_climat = af.t_min,
        temp_max_climat = af.t_max,
        humidite_min_climat = af.h_min,
        humidite_max_climat = af.h_max
    FROM agregation_finale af
    WHERE cm.id = af.commune_id;
""")

with engine.begin() as conn:
    result = conn.execute(query_mise_a_jour)
    print(f"✅ Succès ! Les extrêmes climatiques de {result.rowcount} communes ont été calculés d'après tes tables.")