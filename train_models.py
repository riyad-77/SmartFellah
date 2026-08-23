import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, mean_absolute_error
import joblib
import os
from sqlalchemy import create_engine, text
import warnings
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from xgboost import XGBRegressor
from lightgbm import LGBMRegressor
from statsmodels.tsa.statespace.sarimax import SARIMAX
import pmdarima as pm
from statsmodels.stats.diagnostic import acorr_ljungbox

warnings.filterwarnings("ignore")
# --- 1. CONFIGURATION ---
DB_URL = "postgresql://admin:secretpassword@localhost:5432/bifolia_db"
engine = create_engine(DB_URL)
MODEL_DIR = "models"
os.makedirs(MODEL_DIR, exist_ok=True)

def load_data():
    """Extrait et fusionne la météo, les satellites ET les opérations d'irrigation."""
    print("📥 Extraction des données depuis PostgreSQL...")
    
    # On enveloppe la requête dans text()
    query = text("""
        SELECT 
            m.date_mesure, m.parcelle_id, 
            m.temp_moyenne, m.temp_max, m.temp_min, 
            m.precipitations_mm, m.humidite_moyenne,
            s.ndvi, s.ndwi,
            COALESCE(op.total_irrigation, 0) as irrigation_mm
        FROM donnees_meteo m
        LEFT JOIN indices_satellites s 
            ON m.parcelle_id = s.parcelle_id 
            AND DATE(m.date_mesure) = DATE(s.date_capture)
        LEFT JOIN (
            -- On agrège toutes les irrigations du même jour pour une parcelle
            SELECT parcelle_id, date_operation, SUM(quantite) as total_irrigation
            FROM operations_agricoles
            WHERE LOWER(type_operation) LIKE '%irrigation%'
            GROUP BY parcelle_id, date_operation
        ) op ON m.parcelle_id = op.parcelle_id AND DATE(m.date_mesure) = DATE(op.date_operation)
        ORDER BY m.parcelle_id, m.date_mesure
    """)
    
    # On utilise une connexion explicite avec "with engine.connect()"
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
        
    df['date_mesure'] = pd.to_datetime(df['date_mesure'])
    return df

def feature_engineering(df):
    """Création des variables explicatives (Lags, Moyennes glissantes)."""
    print("⚙️ Feature Engineering (Séries Temporelles)...")
    
    # Remplir les trous des satellites (qui ne passent que tous les 5 jours)
    df['ndvi'] = df.groupby('parcelle_id')['ndvi'].transform(lambda x: x.interpolate(method='linear', limit_direction='both'))
    df['ndwi'] = df.groupby('parcelle_id')['ndwi'].transform(lambda x: x.interpolate(method='linear', limit_direction='both'))
    
    # S'il reste des NaN au tout début, on les remplit avec la moyenne
    df['ndvi'] = df['ndvi'].fillna(df['ndvi'].mean())
    df['ndwi'] = df['ndwi'].fillna(df['ndwi'].mean())

    # Traitement de l'irrigation et de l'apport en eau
    df['irrigation_mm'] = df['irrigation_mm'].fillna(0)
    df['apport_eau_total'] = df['precipitations_mm'] + df['irrigation_mm']

    # Création des Lags (historique) - UNE SEULE BOUCLE PROPRE
    for lag in [1, 3, 7]:
        df[f'temp_moy_lag_{lag}'] = df.groupby('parcelle_id')['temp_moyenne'].shift(lag)
        # Le modèle regardera l'apport d'eau total cumulé (Pluie + Irrigation) sur les derniers jours
        df[f'eau_total_cumul_{lag}j'] = df.groupby('parcelle_id')['apport_eau_total'].transform(lambda x: x.rolling(lag).sum())
        df[f'ndwi_lag_{lag}'] = df.groupby('parcelle_id')['ndwi'].shift(lag)

    # La cible (Target Y) : On veut prédire le NDWI de demain (t+1)
    df['target_ndwi_t1'] = df.groupby('parcelle_id')['ndwi'].shift(-1)

    # Nettoyage des NaN générés par les shifts
    df_clean = df.dropna().copy()
    return df_clean

def train_and_evaluate_models(df):
    print("🧠 Préparation des données pour le grand tournoi (avec optimisation AIC/BIC)...")
    
    # Nos variables exogènes (X)
    exog_features = [
        'temp_moyenne', 'temp_max', 'temp_min', 'humidite_moyenne',
        'apport_eau_total', 
        'temp_moy_lag_1', 'temp_moy_lag_3', 'temp_moy_lag_7',
        'eau_total_cumul_1j', 'eau_total_cumul_3j', 'eau_total_cumul_7j',
        'ndvi' # La vigueur de la plante
    ]
    
    X = df[exog_features]
    y = df['target_ndwi_t1']

    # Split chronologique
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    meilleur_score_rmse = float('inf')
    nom_gagnant = ""
    meilleur_modele = None

    print("\n⚔️ --- DÉBUT DU BENCHMARK ---")
    
    # ---------------------------------------------------------
    # 1. ÉCONOMÉTRIE : Auto-ARIMAX (Optimisation AIC & Résidus)
    # ---------------------------------------------------------
    print("🔹 Auto-ARIMAX (Recherche du meilleur modèle via AIC)...")
    try:
        # L'algorithme cherche tout seul la stationnarité (d) et les meilleurs p, q
        auto_arimax = pm.auto_arima(
            y_train, 
            exogenous=X_train,
            start_p=0, start_q=0, max_p=3, max_q=3,
            test='adf',       # Test de Dickey-Fuller pour trouver 'd'
            seasonal=False,   # Mettre True et m=365 si tu as des années entières de données
            trace=True,       # Affiche la recherche dans le terminal
            error_action='ignore',  
            suppress_warnings=True, 
            stepwise=True,
            information_criterion='aic'
        )
        
        print(f"\n✅ Meilleur modèle trouvé : {auto_arimax.summary().tables[0].data[1][1]}")
        print(f"   -> AIC : {auto_arimax.aic():.2f}")
        
        # Diagnostic des Résidus (Bruit Blanc ?)
        residus = auto_arimax.resid()
        # Test de Ljung-Box sur les résidus (H0: les résidus sont indépendants / bruit blanc)
        lb_test = acorr_ljungbox(residus, lags=[10], return_df=True)
        p_value = lb_test['lb_pvalue'].iloc[0]
        if p_value > 0.05:
            print("   -> Test Ljung-Box : OK (Les résidus ressemblent à un bruit blanc)")
        else:
            print("   -> Test Ljung-Box : Attention (Il reste de l'autocorrélation dans les erreurs)")

        # Prédiction
        arimax_preds = auto_arimax.predict(n_periods=len(y_test), exogenous=X_test)
        arimax_rmse = np.sqrt(mean_squared_error(y_test, arimax_preds))
        print(f"   -> RMSE Test : {arimax_rmse:.4f}\n")
        
        meilleur_score_rmse = arimax_rmse
        meilleur_modele = auto_arimax
        nom_gagnant = "Auto-ARIMAX"
        
    except Exception as e:
        print(f"   -> Échec de l'Auto-ARIMAX : {e}\n")


    # ---------------------------------------------------------
    # 2. MACHINE LEARNING / BOOSTING
    # ---------------------------------------------------------
    # (En vrai, pour être totalement rigoureux, il faudrait aussi faire un GridSearchCV ici pour optimiser leurs hyperparamètres)
    
    # Attention, on remet les variables endogènes retardées (lags) dans le ML car il n'a pas de composante AR intégrée
    features_ml = exog_features + ['ndwi_lag_1', 'ndwi_lag_3', 'ndwi_lag_7']
    X_train_ml, X_test_ml = df[features_ml].loc[X_train.index], df[features_ml].loc[X_test.index]

    modeles_ml = {
        "Random Forest": RandomForestRegressor(n_estimators=100, random_state=42),
        "XGBoost": XGBRegressor(n_estimators=100, random_state=42, objective='reg:squarederror'),
        "LightGBM": LGBMRegressor(n_estimators=100, random_state=42, verbose=-1)
    }

    for nom, modele in modeles_ml.items():
        modele.fit(X_train_ml, y_train)
        predictions = modele.predict(X_test_ml)
        rmse = np.sqrt(mean_squared_error(y_test, predictions))
        
        print(f"🔹 {nom:<20} -> RMSE Test: {rmse:.4f}")
        
        if rmse < meilleur_score_rmse:
            meilleur_score_rmse = rmse
            meilleur_modele = modele
            nom_gagnant = nom

    print(f"\n🏆 LE CHAMPION EST : {nom_gagnant} avec un RMSE de {meilleur_score_rmse:.4f} !")
    return meilleur_modele, features_ml, nom_gagnant
   

def save_model(model, features, nom_modele):
    """Sauvegarde le modèle gagnant et la liste des features."""
    model_path = os.path.join(MODEL_DIR, "ndwi_forecaster.pkl")
    features_path = os.path.join(MODEL_DIR, "features_list.pkl")
    
    joblib.dump(model, model_path)
    joblib.dump(features, features_path)
    print(f"✅ Le modèle champion '{nom_modele}' a été sauvegardé avec succès, prêt pour la production !")

if __name__ == "__main__":
    df_raw = load_data()
    
    if df_raw.empty:
        print("❌ Aucune donnée trouvée dans la base.")
    else:
        df_ml = feature_engineering(df_raw)
        meilleur_modele, features_list, nom_gagnant = train_and_evaluate_models(df_ml)
        save_model(meilleur_modele, features_list, nom_gagnant)