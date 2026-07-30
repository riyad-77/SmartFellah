from ollama import Client
import json

def extraire_seuils_maladie(liste_causes):
    if not liste_causes:
        return {"temp_min": None, "temp_max": None, "humidite_min": None}

    texte_causes = " ".join(liste_causes)
    prompt = f"""
    Analyse ce texte décrivant les causes climatiques d'une maladie agricole.
    Extrais UNIQUEMENT les seuils de déclenchement sous format JSON strict.
    Si une information climatique est absente, mets null.
    
    Format requis EXACT :
    {{
        "temp_min": null,
        "temp_max": null,
        "humidite_min": null
    }}
    
    Texte à analyser : "{texte_causes}"
    """
    try:
        # Assure-toi d'utiliser le modèle que tu as téléchargé (llama3.2 ou qwen2.5)
        response = ollama.chat(model='llama3.2', messages=[{'role': 'user', 'content': prompt}], format='json')
        content = response['message']['content']
        return json.loads(content)
    except Exception as e:
        print(f"Erreur LLM sur les seuils: {e}")
        return {"temp_min": None, "temp_max": None, "humidite_min": None}