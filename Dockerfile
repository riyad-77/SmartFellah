FROM python:3.10-slim

WORKDIR /app

# Installation des dépendances système nécessaires pour psycopg2
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copie et installation des requirements/dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie de tout le code source dans le conteneur
COPY . .

# Exposition du port de l'API
EXPOSE 8001

# Commande de lancement de l'API avec Uvicorn
CMD ["uvicorn", "api_smartfellah.py:app", "--host", "0.0.0.0", "--port", "8001"]