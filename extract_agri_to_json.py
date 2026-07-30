import os
import fitz
from ollama import Client
import json
import shutil


ollama_client = Client(host='http://host.docker.internal:11434')



BASE_DIR = "/opt/airflow/data"
PDF_DIR = os.path.join(BASE_DIR, "FT_Vegetal")
JSON_DIR = os.path.join(BASE_DIR, "FT_Json_Data")
MODEL_NAME = 'llama3.2'

# --- INITIALISATION DES DOSSIERS ---
def setup_directories():
    """Prépare le dossier de destination en le nettoyant s'il existe."""
    if os.path.exists(JSON_DIR):
        print(f"🧹 Dossier '{JSON_DIR}' existant trouvé. Nettoyage...")
        shutil.rmtree(JSON_DIR)
    os.makedirs(JSON_DIR, exist_ok=True)
    print(f"📁 Dossier '{JSON_DIR}' prêt.")

# --- FONCTION D'EXTRACTION ---
def extract_to_json_robust(pdf_path):
    """Extrait le texte d'un PDF et le structure en JSON via Ollama."""
    # 1. Lecture du PDF
    doc = fitz.open(pdf_path)
    full_text = "\n".join([page.get_text("text") for page in doc])
    doc.close() # Bonne pratique : libérer la mémoire du fichier
    
    if len(full_text.strip()) < 50:
        raise ValueError("Document vide ou illisible (probablement un scan sans OCR)")

    # 2. Préparation du Prompt
    prompt = f"""
    Tu es un expert agronome au Maroc. Extrais les données du document technique fourni en format JSON.

    RÈGLES DE SORTIE :
    1. Retourne UNIQUEMENT un objet JSON valide.
    2. Si une information est absente, utilise null.
    3. Si la culture est en arabe, traduis-la en français.
    4. NE JAMAIS deviner. Si la culture n'est pas explicite, écris "Inconnue".
    5. NE JAMAIS utiliser "Blé" par défaut.

    Structure JSON obligatoire EXACTE :
    {{
        "culture": "string",
        "exigences_sol": "description",
        "besoins_hydriques": "description",
        "temp_optimale": {{"temp_min": "valeur", "temp_max": "valeur"}},
        "maladies_details": [
            {{
                "nom_maladie": "nom de la maladie",
                "causes": ["liste des causes"],
                "traitements_specifiques": ["liste des remèdes"]
            }}
        ],
        "recommandations": [
        {{
            "description": "description détaillée du conseil ou de la tâche agricole à réaliser",
            "status": "en cours",
            "categorie": "urgent" 
        }}
    ]
    }}

    Texte à analyser :
    {full_text[:6000]}
    """
    
    # 3. Appel à l'IA avec forçage du format JSON
    response = ollama_client.chat( # <-- MODIFIÉ : Utilise ollama_client
        model=MODEL_NAME, 
        messages=[{'role': 'user', 'content': prompt}],
        format='json'
    )
    
    # Plus besoin de chercher les { et } manuellement !
    content = response['message']['content']
    return json.loads(content)

# --- BOUCLE PRINCIPALE ---
if __name__ == "__main__":
    import sys
    
    # S'assurer que le dossier source existe pour éviter le crash
    if not os.path.exists(PDF_DIR):
        os.makedirs(PDF_DIR, exist_ok=True)
        
    fichiers = sorted([f for f in os.listdir(PDF_DIR) if f.endswith(".pdf")])
    
    # Si le dossier est vide, on arrête le script avec succès (code 0)
    if len(fichiers) == 0:
        print("✅ Aucun nouveau PDF à traiter. Le pipeline s'arrête ici.")
        sys.exit(0) # Fera passer la case Airflow au VERT

    print(f"🚀 Début du traitement de {len(fichiers)} fichiers...\n")
    setup_directories() # On nettoie FT_Json_Data QUE si on a de nouveaux PDF

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