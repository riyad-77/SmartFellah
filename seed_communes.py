import pandas as pd
from sqlalchemy import create_engine

# 1. Configuration de la connexion à ta base PostgreSQL (port 5432)
# Adapte le nom d'utilisateur, mot de passe et nom de base si nécessaire
DB_USER = "admin"
DB_PASSWORD = "secretpassword"
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "bifolia_db"

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)

# 2. Dataset de référence complet des communes et de leurs coordonnées géographiques
data_communes = [
    # Région Rabat-Salé-Kénitra
    {"nom_commune": "Kénitra", "cercle": "Kénitra", "province": "Kénitra", "region": "Rabat-Salé-Kénitra", "latitude": 34.2610, "longitude": -6.5802},
    {"nom_commune": "Sidi Allal Tazi", "cercle": "Lalla Mimouna", "province": "Kénitra", "region": "Rabat-Salé-Kénitra", "latitude": 34.4333, "longitude": -6.3667},
    {"nom_commune": "Souk El Arbaa", "cercle": "Bahht", "province": "Sidi Kacem", "region": "Rabat-Salé-Kénitra", "latitude": 34.2500, "longitude": -6.5800},
    {"nom_commune": "Sidi Kacem", "cercle": "Sidi Kacem", "province": "Sidi Kacem", "region": "Rabat-Salé-Kénitra", "latitude": 34.2233, "longitude": -5.7078},
    {"nom_commune": "Khémisset", "cercle": "Khémisset", "province": "Khémisset", "region": "Rabat-Salé-Kénitra", "latitude": 33.8242, "longitude": -6.0664},
    {"nom_commune": "Tiflet", "cercle": "Tiflet", "province": "Khémisset", "region": "Rabat-Salé-Kénitra", "latitude": 33.8900, "longitude": -6.3000},
    {"nom_commune": "Salé", "cercle": "Salé", "province": "Salé", "region": "Rabat-Salé-Kénitra", "latitude": 34.0333, "longitude": -6.8333},
    {"nom_commune": "Rabat", "cercle": "Rabat", "province": "Rabat", "region": "Rabat-Salé-Kénitra", "latitude": 34.0209, "longitude": -6.8416},

    # Région Souss-Massa
    {"nom_commune": "Taroudant", "cercle": "Taroudant", "province": "Taroudant", "region": "Souss-Massa", "latitude": 30.4200, "longitude": -9.5800},
    {"nom_commune": "Belfaa", "cercle": "Chtouka", "province": "Chtouka-Aït Baha", "region": "Souss-Massa", "latitude": 30.1200, "longitude": -9.5600},
    {"nom_commune": "Agadir", "cercle": "Agadir Ida-Outanane", "province": "Agadir Ida-Outanane", "region": "Souss-Massa", "latitude": 30.4278, "longitude": -9.5981},
    {"nom_commune": "Biougra", "cercle": "Chtouka", "province": "Chtouka-Aït Baha", "region": "Souss-Massa", "latitude": 30.2144, "longitude": -9.3708},
    {"nom_commune": "Tiznit", "cercle": "Tiznit", "province": "Tiznit", "region": "Souss-Massa", "latitude": 29.6974, "longitude": -9.7316},

    # Région Fès-Meknès
    {"nom_commune": "Ain Chgag", "cercle": "Sefrou", "province": "Sefrou", "region": "Fès-Meknès", "latitude": 33.8900, "longitude": -5.5500},
    {"nom_commune": "Fès", "cercle": "Fès", "province": "Fès", "region": "Fès-Meknès", "latitude": 34.0333, "longitude": -5.0000},
    {"nom_commune": "Meknès", "cercle": "Meknès", "province": "Meknès", "region": "Fès-Meknès", "latitude": 33.8935, "longitude": -5.5473},
    {"nom_commune": "Sefrou", "cercle": "Sefrou", "province": "Sefrou", "region": "Fès-Meknès", "latitude": 33.8333, "longitude": -4.8333},
    {"nom_commune": "El Hajeb", "cercle": "El Hajeb", "province": "El Hajeb", "region": "Fès-Meknès", "latitude": 33.6931, "longitude": -5.3711},

    # Région Casablanca-Settat
    {"nom_commune": "Sidi Bennour", "cercle": "Sidi Bennour", "province": "Sidi Bennour", "region": "Casablanca-Settat", "latitude": 32.9200, "longitude": -8.5000},
    {"nom_commune": "Benslimane", "cercle": "Benslimane", "province": "Benslimane", "region": "Casablanca-Settat", "latitude": 33.6100, "longitude": -7.1500},
    {"nom_commune": "Settat", "cercle": "Settat", "province": "Settat", "region": "Casablanca-Settat", "latitude": 33.0010, "longitude": -7.6166},
    {"nom_commune": "Berrechid", "cercle": "Berrechid", "province": "Berrechid", "region": "Casablanca-Settat", "latitude": 33.2656, "longitude": -7.5878},
    {"nom_commune": "El Jadida", "cercle": "El Jadida", "province": "El Jadida", "region": "Casablanca-Settat", "latitude": 33.2316, "longitude": -8.5007},

    # Région Béni Mellal-Khénifra
    {"nom_commune": "Fquih Ben Salah", "cercle": "Fquih Ben Salah", "province": "Fquih Ben Salah", "region": "Béni Mellal-Khénifra", "latitude": 32.3300, "longitude": -6.3500},
    {"nom_commune": "Béni Mellal", "cercle": "Béni Mellal", "province": "Béni Mellal", "region": "Béni Mellal-Khénifra", "latitude": 32.3394, "longitude": -6.3603},
    {"nom_commune": "Khénifra", "cercle": "Khénifra", "province": "Khénifra", "region": "Béni Mellal-Khénifra", "latitude": 32.9367, "longitude": -5.6681},
    {"nom_commune": "Azilal", "cercle": "Azilal", "province": "Azilal", "region": "Béni Mellal-Khénifra", "latitude": 31.9689, "longitude": -6.5694},

    # Région Drâa-Tafilalet
    {"nom_commune": "Errachidia", "cercle": "Errachidia", "province": "Errachidia", "region": "Drâa-Tafilalet", "latitude": 31.9300, "longitude": -4.4200},
    {"nom_commune": "Midelt", "cercle": "Midelt", "province": "Midelt", "region": "Drâa-Tafilalet", "latitude": 32.6800, "longitude": -4.7300},
    {"nom_commune": "Ouarzazate", "cercle": "Ouarzazate", "province": "Ouarzazate", "region": "Drâa-Tafilalet", "latitude": 30.9189, "longitude": -6.9361},
    {"nom_commune": "Zagora", "cercle": "Zagora", "province": "Zagora", "region": "Drâa-Tafilalet", "latitude": 30.3308, "longitude": -5.8381},

    # Région Marrakech-Safi
    {"nom_commune": "Ait Ourir", "cercle": "Al Haouz", "province": "Al Haouz", "region": "Marrakech-Safi", "latitude": 31.6300, "longitude": -8.0000},
    {"nom_commune": "Marrakech", "cercle": "Marrakech", "province": "Marrakech", "region": "Marrakech-Safi", "latitude": 31.6295, "longitude": -7.9811},
    {"nom_commune": "Safi", "cercle": "Safi", "province": "Safi", "region": "Marrakech-Safi", "latitude": 32.2994, "longitude": -9.2372},
    {"nom_commune": "Chichaoua", "cercle": "Chichaoua", "province": "Chichaoua", "region": "Marrakech-Safi", "latitude": 31.5447, "longitude": -8.7597},
    {"nom_commune": "Kelâat Sraghna", "cercle": "Kelâat Sraghna", "province": "Kelâat Sraghna", "region": "Marrakech-Safi", "latitude": 32.0497, "longitude": -7.4083},

    # Région Tanger-Tétouan-Al Hoceïma
    {"nom_commune": "Larache", "cercle": "Larache", "province": "Larache", "region": "Tanger-Tétouan-Al Hoceïma", "latitude": 35.1500, "longitude": -6.1100},
    {"nom_commune": "Tanger", "cercle": "Tanger-Assilah", "province": "Tanger-Assilah", "region": "Tanger-Tétouan-Al Hoceïma", "latitude": 35.7595, "longitude": -5.8340},
    {"nom_commune": "Tétouan", "cercle": "Tétouan", "province": "Tétouan", "region": "Tanger-Tétouan-Al Hoceïma", "latitude": 35.5784, "longitude": -5.3684},
    {"nom_commune": "Al Hoceïma", "cercle": "Al Hoceïma", "province": "Al Hoceïma", "region": "Tanger-Tétouan-Al Hoceïma", "latitude": 35.2472, "longitude": -3.9322},
    {"nom_commune": "Chefchaouen", "cercle": "Chefchaouen", "province": "Chefchaouen", "region": "Tanger-Tétouan-Al Hoceïma", "latitude": 35.1688, "longitude": -5.2636},

    # Région Oriental
    {"nom_commune": "Berkane", "cercle": "Berkane", "province": "Berkane", "region": "Oriental", "latitude": 34.9200, "longitude": -2.3200},
    {"nom_commune": "Oujda", "cercle": "Oujda-Angad", "province": "Oujda-Angad", "region": "Oriental", "latitude": 34.6814, "longitude": -1.9086},
    {"nom_commune": "Nador", "cercle": "Nador", "province": "Nador", "region": "Oriental", "latitude": 35.1681, "longitude": -2.9335},
    {"nom_commune": "Taourirt", "cercle": "Taourirt", "province": "Taourirt", "region": "Oriental", "latitude": 34.4103, "longitude": -2.8906},
]

# 3. Conversion en DataFrame Pandas
df = pd.DataFrame(data_communes)

print(f"Chargement de {len(df)} communes dans la base de données PostgreSQL...")

# 4. Insertion dans la table 'communes_maroc' (remplace la table si elle existe déjà)
df.to_sql('communes_maroc', engine, if_exists='replace', index=False)

print("Succès ! La table 'communes_maroc' a été remplie avec succès.")