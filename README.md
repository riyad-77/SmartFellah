# 🌱 SmartFellah - Backend d'Assistance Agronomique Intelligente

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-PostGIS-336791.svg)
![Google Earth Engine](https://img.shields.io/badge/GEE-Satellite_API-success.svg)

**SmartFellah** est une API backend développée dans le cadre de mon Projet de Fin d'Année (PFA) à l'INSEA. Elle permet l'ingestion de documents agricoles officiels, la recommandation spatiale de cultures, et le suivi agronomique des parcelles (stress hydrique, fertilisation, maladies) en croisant des données climatiques (OpenWeather) et des indices satellitaires (Google Earth Engine).

## 🚀 Fonctionnalités Principales

1. **Ingestion & Structuration de Données (ETL) :**
   - Extraction des informations agronomiques depuis les documents officiels (PDF) du Ministère de l'Agriculture.
   - Structuration en JSON (seuils thermiques, besoins hydriques, maladies, zones recommandées) et intégration automatisée en base de données relationnelle.
2. **Recommandation de Cultures par Terroir :**
   - Filtrage spatial optimisé directement via SQL pour recommander les cultures adaptées à une commune spécifique (basé sur le zonage officiel).
3. **Conseil Quotidien (Daily Advice) :**
   - Calcul et normalisation des indices satellitaires (NDVI, NDWI, EVI) via Google Earth Engine.
   - Moteur de règles déterministe pour générer des conseils :
     - **Irrigation :** Basé sur le NDWI (alerte d'asphyxie racinaire ou recommandation d'apport en eau).
     - **Fertilisation :** Basé sur le NDVI (suivi de la vigueur végétative).
     - **Canopy Management (Taille) :** Basé sur l'EVI (gestion de la biomasse et de la densité foliaire).
4. **Prédiction des Maladies :**
   - Croisement des prévisions météorologiques locales avec les conditions de développement des maladies (seuils de température et d'humidité) pour générer des alertes préventives.

## 🏗️ Architecture du Système

Le système est divisé en deux grandes étapes :
- **Étape 1 : Acquisition et Ingestion** (PDF -> JSON -> Bifolia DB)
- **Étape 2 : Processus et Services API** (Endpoints de recommandation et de diagnostic)

L'intelligence du filtrage spatial est entièrement déléguée à la base de données (PostgreSQL/PostGIS) pour garantir une complexité temporelle minimale et des performances optimales.

## 🛠️ Stack Technique

- **Backend Framework :** FastAPI (Python)
- **Base de données :** PostgreSQL avec extension spatiale PostGIS
- **ORM / Base de données :** SQLAlchemy, intégration de requêtes SQL natives pour l'optimisation
- **API Tiers :** 
  - Google Earth Engine (GEE) - *Extraction indices satellitaires*
  - OpenWeather API - *Données météorologiques*
- **Traitement Asynchrone :** `BackgroundTasks` de FastAPI pour les pipelines d'ingestion longs.

## 🌐 Endpoints Principaux

| Méthode | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/upload-agri-document/` | Lance le pipeline d'extraction (PDF vers DB) en arrière-plan. |
| `POST` | `/recommend-crops-by-commune` | Retourne les cultures recommandées pour une commune donnée. |
| `POST` | `/daily-advice` | Fournit des recommandations (eau, engrais, taille) basées sur GEE et Météo. |
| `POST` | `/predict-maladies` | Prédit les risques de maladies selon les prévisions météo. |
| `DELETE` | `/cultures/{nom_culture}` | Suppression en cascade d'une culture et de ses données associées. |

## ⚙️ Installation et Lancement

1. **Cloner le dépôt :**
   ```bash
   git clone [https://github.com/riyad-77/smartfellah-backend.git](https://github.com/riyad-77/smartfellah-backend.git)
   cd smartfellah-backend
