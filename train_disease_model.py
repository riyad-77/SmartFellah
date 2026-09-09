import pandas as pd
import numpy as np
import os
import warnings
import joblib
from sqlalchemy import create_engine, text

from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score, f1_score, roc_auc_score, average_precision_score



# 1. Approche discriminante
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier

# 2. Méthodes d'agrégation
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier

# 3. Approche générative
from sklearn.naive_bayes import GaussianNB

warnings.filterwarnings("ignore")

# --- CONFIGURATION ---
DB_URL = "postgresql://admin:secretpassword@localhost:5432/bifolia_db"
engine = create_engine(DB_URL)
MODEL_DIR = "models"
os.makedirs(MODEL_DIR, exist_ok=True)

def load_and_generate_disease_data():
    """Génère un dataset basé sur les conditions universelles de prolifération fongique."""
    print("📥 Extraction et ingénierie des données météo...")
    
    with engine.connect() as conn:
        df_meteo = pd.read_sql(text("""
            SELECT date_mesure, parcelle_id, temp_moyenne, temp_max, temp_min, humidite_moyenne, precipitations_mm 
            FROM donnees_meteo 
            ORDER BY parcelle_id, date_mesure
        """), conn)
        
    df_meteo['date_mesure'] = pd.to_datetime(df_meteo['date_mesure'])
    df_meteo['hum_moy_3j'] = df_meteo.groupby('parcelle_id')['humidite_moyenne'].transform(lambda x: x.rolling(3, min_periods=1).mean())
    df_meteo['temp_moy_3j'] = df_meteo.groupby('parcelle_id')['temp_moyenne'].transform(lambda x: x.rolling(3, min_periods=1).mean())
    df_meteo['pluie_cumul_3j'] = df_meteo.groupby('parcelle_id')['precipitations_mm'].transform(lambda x: x.rolling(3, min_periods=1).sum())

    # --- RÈGLE AGRONOMIQUE UNIVERSELLE (Risque Fongique Global) ---
    # Les champignons se développent si : 
    # 1. Humidité élevée (> 75%) ET Température douce (entre 15°C et 30°C)
    # OU 2. Fortes pluies récentes (> 5mm cumulés) ET Température > 12°C
    
    condition_fongique = (
        (df_meteo['hum_moy_3j'] >= 75.0) & 
        (df_meteo['temp_moy_3j'] >= 15.0) & 
        (df_meteo['temp_moy_3j'] <= 30.0)
    )
    
    condition_pluie = (
        (df_meteo['pluie_cumul_3j'] >= 5.0) & 
        (df_meteo['temp_moy_3j'] >= 12.0)
    )
    
    df_meteo['risque_maladie'] = np.where(condition_fongique | condition_pluie, 1, 0)
    
    # Bruit statistique minime (5%) pour forcer le modèle ML à généraliser 
    # au lieu d'apprendre cette règle exacte par cœur
    np.random.seed(42)
    bruit = np.random.choice([0, 1], size=len(df_meteo), p=[0.95, 0.05])
    df_meteo['risque_maladie'] = np.abs(df_meteo['risque_maladie'] - bruit)

    print("\n📊 Distribution des classes générées (Risque Fongique Global) :")
    print(df_meteo['risque_maladie'].value_counts(normalize=True).map('{:.2%}'.format))

    return df_meteo.dropna().copy()

def run_model_benchmark(df):
    """Teste plusieurs modèles et conserve le meilleur selon l'AUC-PR."""
    print("\n⚔️ --- DÉBUT DU TOURNNOI DE CLASSIFICATION ---")
    print("🏆 Le critère de victoire est l'AUC-PR (Average Precision), idéal pour les données déséquilibrées.\n")
    
    features = [
        'temp_moyenne', 'temp_max', 'temp_min', 'humidite_moyenne', 'precipitations_mm',
        'hum_moy_3j', 'temp_moy_3j', 'pluie_cumul_3j'
    ]
    X = df[features]
    y = df['risque_maladie']

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    modeles = {
        "Régression Logistique": LogisticRegression(class_weight='balanced', random_state=42),
        "Arbre de Décision": DecisionTreeClassifier(class_weight='balanced', random_state=42),
        "Forêt Aléatoire": RandomForestClassifier(n_estimators=100, class_weight='balanced', random_state=42),
        "SVM (Noyau RBF)": SVC(probability=True, class_weight='balanced', random_state=42),
        "KNN": KNeighborsClassifier(n_neighbors=5),
        "Naïve Bayes": GaussianNB(),
        "Réseau de Neurones": MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=500, random_state=42),
        "XGBoost": XGBClassifier(scale_pos_weight=20, random_state=42, eval_metric='logloss'),
        "LightGBM": LGBMClassifier(class_weight='balanced', random_state=42, verbose=-1)
    }

    meilleur_score = 0
    meilleur_modele = None
    nom_gagnant = ""

    for nom, modele in modeles.items():
        # Entraînement
        modele.fit(X_train, y_train)
        
        # Prédiction des classes (0 ou 1)
        y_pred = modele.predict(X_test)
        
        # Prédiction des probabilités pour l'AUC-ROC et l'AUC-PR
        # (On prend la probabilité de la classe 1)
        y_prob = modele.predict_proba(X_test)[:, 1]
        
        # Calcul des 3 métriques
        score_f1 = f1_score(y_test, y_pred, average='macro')
        auc_roc = roc_auc_score(y_test, y_prob)
        auc_pr = average_precision_score(y_test, y_prob)
        
        print(f"🔹 {nom:<22} -> AUC-PR: {auc_pr:.4f} | AUC-ROC: {auc_roc:.4f} | F1(Macro): {score_f1:.4f}")
        
        # Élection du champion basée sur l'AUC-PR (la plus robuste face au déséquilibre)
        if auc_pr > meilleur_score:
            meilleur_score = auc_pr
            meilleur_modele = modele
            nom_gagnant = nom

    print(f"\n🏆 LE CHAMPION EST : {nom_gagnant} avec un AUC-PR de {meilleur_score:.4f} !")
    
    # Affichage du rapport détaillé du gagnant
    print(f"\n📊 Rapport détaillé du gagnant ({nom_gagnant}) :")
    y_pred_best = meilleur_modele.predict(X_test)
    print(classification_report(y_test, y_pred_best, target_names=["Sain (0)", "Risque (1)"]))

    return meilleur_modele, features, nom_gagnant

def save_disease_model(model, features, nom_gagnant):
    model_path = os.path.join(MODEL_DIR, "disease_classifier.pkl")
    features_path = os.path.join(MODEL_DIR, "disease_features.pkl")
    
    joblib.dump(model, model_path)
    joblib.dump(features, features_path)
    print(f"✅ Le modèle '{nom_gagnant}' a été sauvegardé dans '{MODEL_DIR}/' !")

if __name__ == "__main__":
    df_donnees = load_and_generate_disease_data()
    print(f"Total d'enregistrements prêts pour l'entraînement : {len(df_donnees)}")
    
    modele, liste_features, nom_gagnant = run_model_benchmark(df_donnees)
    save_disease_model(modele, liste_features, nom_gagnant)