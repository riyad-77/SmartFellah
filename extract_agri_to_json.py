import os
import pymupdf
from ollama import Client
import json
import shutil

ollama_client = Client(host='http://localhost:11434')

BASE_DIR = r"C:\Users\hp\SmartFellah"
PDF_DIR = os.path.join(BASE_DIR, "FT_Vegetal")
JSON_DIR = os.path.join(BASE_DIR, "FT_Json_Data")
MODEL_NAME = 'llama3.2'

def setup_directories():
    """Prépare le dossier de destination en le nettoyant s'il existe."""
    if os.path.exists(JSON_DIR):
        print(f"🧹 Dossier '{JSON_DIR}' existant trouvé. Nettoyage...")
        shutil.rmtree(JSON_DIR)
    os.makedirs(JSON_DIR, exist_ok=True)
    print(f"📁 Dossier '{JSON_DIR}' prêt.")

def extract_to_json_robust(pdf_path):
    """Extrait le texte d'un PDF et le structure en JSON via Ollama."""
    doc = pymupdf.open(pdf_path)
    full_text = "\n".join([page.get_text("text") for page in doc])
    doc.close() 
    
    if len(full_text.strip()) < 50:
        raise ValueError("Document vide ou illisible (probablement un scan sans OCR)")

    # Prompt mis à jour pour inclure "zones_recommandees"
    prompt = f"""
    Tu es un expert agronome au Maroc. Extrais les données du document technique fourni en format JSON.

    RÈGLES DE SORTIE :
    1. Retourne UNIQUEMENT un objet JSON valide.
    2. Si une information est absente du texte, utilise null ou une estimation scientifique prudente.
    3. Si la culture est en arabe, traduis-la en français.
    4. NE JAMAIS deviner la culture. Si la culture n'est pas explicite, écris "Inconnue".
    5. NE JAMAIS utiliser "Blé" par défaut.
    6. Pour hum_min et hum_max, extrait le taux d'humidité en pourcentage (sinon 20 et 80 par défaut).
    7. Pour les indices satellitaires (ndvi, ndwi, evi), si absent, mets 0.4 (ndvi), 0.0 (ndwi), et 0.3 (evi).
    8. Pour zones_recommandees, identifie les villes, communes ou régions agricoles du Maroc explicitement mentionnées (si aucune, retourne []).

    Structure JSON obligatoire EXACTE :
    {{
        "culture": "string",
        "zones_recommandees": ["liste des communes recommandees"],
        "exigences_sol": "description",
        "besoins_hydriques": "description",
        "bioclimatologie_optimale": {{
            "temp_min": "valeur numerique", 
            "temp_max": "valeur numerique",
            "hum_min": "valeur numerique",
            "hum_max": "valeur numerique"
        }},
        "indices_satellitaires_requis": {{
            "ndvi_optimal_min": "valeur numerique",
            "ndvi_optimal_max": "valeur numerique",
            "ndwi_optimal_min": "valeur numerique",
            "ndwi_optimal_max": "valeur numerique",
            "evi_optimal_min": "valeur numerique",
            "evi_optimal_max": "valeur numerique"
        }},
        "maladies_details": [
            {{
                "nom_maladie": "nom de la maladie",
                "causes": ["liste des causes"],
                "traitements_specifiques": ["liste des remèdes"]
            }}
        ],
        "recommandations": [
            {{
                "description": "description détaillée",
                "status": "en cours",
                "categorie": "urgent" 
            }}
        ]
    }}

    Texte à analyser :
    {full_text[:6000]}
    """
    
    response = ollama_client.chat(
        model=MODEL_NAME, 
        messages=[{'role': 'user', 'content': prompt}],
        format='json'
    )
    
    content = response['message']['content']
    return json.loads(content)

if __name__ == "__main__":
    import sys
    
    if not os.path.exists(PDF_DIR):
        os.makedirs(PDF_DIR, exist_ok=True)
        
    fichiers = sorted([f for f in os.listdir(PDF_DIR) if f.endswith(".pdf")])
    
    if len(fichiers) == 0:
        print("✅ Aucun nouveau PDF à traiter. Le pipeline s'arrête ici.")
        sys.exit(0)

    print(f"🚀 Début du traitement de {len(fichiers)} fichiers...\n")
    setup_directories()

    for file in fichiers:
        json_path = os.path.join(JSON_DIR, file.replace(".pdf", ".json"))
        pdf_path = os.path.join(PDF_DIR, file)
        
        print(f"Traitement : {file}...")
        try:
            data = extract_to_json_robust(pdf_path)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print(f"  ✅ Succès : {file.replace('.pdf', '.json')}")
            
        except json.JSONDecodeError:
            print(f"  ❌ Erreur de formatage JSON généré par l'IA pour {file}")
        except Exception as e:
            print(f"  ⚠️ Erreur sur {file} : {e}")

    print("\n🎉 Étape 1 : Extraction vers JSON terminée avec succès.")