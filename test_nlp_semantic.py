from transformers import pipeline

print("📥 Chargement du modèle d'Inférence Logique (NLI Multilingue)...")
# Ce modèle (mDeBERTa) est le champion actuel pour comprendre les contradictions en français
classifier = pipeline("zero-shot-classification", model="MoritzLaurer/mDeBERTa-v3-base-mnli-xnli")

def generer_phrase_meteo(meteo):
    phrase = "Le climat actuel est "
    if meteo['temp_moyenne'] > 28: phrase += "très chaud, "
    elif meteo['temp_moyenne'] > 15: phrase += "doux, "
    else: phrase += "froid, "
    
    if meteo['humidite_moyenne'] > 75: phrase += "très humide "
    else: phrase += "sec "
        
    if meteo['precipitations_mm'] > 10: phrase += "avec des précipitations abondantes."
    elif meteo['precipitations_mm'] > 0: phrase += "avec de légères pluies."
    else: phrase += "sans pluie."
    return phrase

# --- TEST ---
donnees_meteo = {
    "temp_moyenne": 18,
    "humidite_moyenne": 85,
    "precipitations_mm": 20
}

texte_meteo = generer_phrase_meteo(donnees_meteo)
print(f"\n🌤️ Météo de l'API : '{texte_meteo}'")

causes_base_de_donnees = {
    "Oïdium": "Temps sec avec des températures élevées et un manque d'eau.",
    "Botrytis": "Taux d'hygrométrie insoutenable, averses régulières et fraîcheur.",
    "Stress Salin": "Irrigation avec une eau chargée en sel et aridité."
}

print("\n🔍 Analyse Logique (Entailment / Contradiction) :")
for maladie, cause_texte in causes_base_de_donnees.items():
    
    # On demande au modèle : "Sachant la météo actuelle, est-ce que cette cause est présente ?"
    resultat = classifier(
        texte_meteo, 
        candidate_labels=[cause_texte], 
        multi_label=True # Évalue chaque cause indépendamment
    )
    
    score = resultat['scores'][0]
    match = "🚨 ALERTE" if score > 0.50 else "✅ Sain"
    
    print(f"- {maladie:<15} | Score: {score:.2f} | {match} (Cause: {cause_texte})")