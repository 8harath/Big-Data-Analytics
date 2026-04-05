import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

# API params
PATH_LAST_PROCESSED = Path(
    os.getenv("LAST_PROCESSED_PATH", DEFAULT_DATA_DIR / "last_processed.json")
)
DEFAULT_LAST_PROCESSED = os.getenv("INITIAL_LAST_PROCESSED", "2000-01-01")
MAX_LIMIT = int(os.getenv("RAPPELCONSO_API_LIMIT", "100"))
MAX_OFFSET = int(os.getenv("RAPPELCONSO_API_MAX_OFFSET", "10000"))

# We have three parameters in the URL:
# 1. MAX_LIMIT: the maximum number of records to be returned by the API
# 2. date_de_publication: the date from which we want to get the data
# 3. offset: the index of the first result
URL_API = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/rappelconso0/records?limit={}&where=date_de_publication%20%3E%20'{}'&order_by=date_de_publication%20ASC&offset={}"
URL_API = URL_API.format(MAX_LIMIT, "{}", "{}")

# Kafka params
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "rappel_conso")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_BOOTSTRAP_SERVERS_LOCAL = os.getenv(
    "KAFKA_BOOTSTRAP_SERVERS_LOCAL", "localhost:9094"
)

# PostgreSQL params
POSTGRES_HOST = os.getenv("APP_POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("APP_POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("APP_POSTGRES_DB", "postgres")
POSTGRES_USER = os.getenv("APP_POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("APP_POSTGRES_PASSWORD")

POSTGRES_URL = f"jdbc:postgresql://{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
POSTGRES_PROPERTIES = {
    "user": POSTGRES_USER,
    "password": POSTGRES_PASSWORD,
    "driver": "org.postgresql.Driver",
}

NEW_COLUMNS = [
    "risques_pour_le_consommateur",
    "recommandations_sante",
    "date_debut_commercialisation",
    "date_fin_commercialisation",
    "informations_complementaires",
]

COLUMNS_TO_NORMALIZE = [
    "categorie_de_produit",
    "sous_categorie_de_produit",
    "nom_de_la_marque_du_produit",
    "noms_des_modeles_ou_references",
    "identification_des_produits",
    "conditionnements",
    "temperature_de_conservation",
    "zone_geographique_de_vente",
    "distributeurs",
    "motif_du_rappel",
    "numero_de_contact",
    "modalites_de_compensation",
]

COLUMNS_TO_KEEP = [
    "reference_fiche",
    "liens_vers_les_images",
    "lien_vers_la_liste_des_produits",
    "lien_vers_la_liste_des_distributeurs",
    "lien_vers_affichette_pdf",
    "lien_vers_la_fiche_rappel",
    "date_de_publication",
    "date_de_fin_de_la_procedure_de_rappel",
]
DB_FIELDS = COLUMNS_TO_KEEP + COLUMNS_TO_NORMALIZE + NEW_COLUMNS
