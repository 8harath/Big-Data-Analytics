"""
Pydantic schema for a single transformed RappelConso record.

Every record is validated here before being published to Kafka.
Records that fail validation are routed to the dead-letter topic
(rappel_conso_dlq) instead of the main topic (rappel_conso).

Field rules
-----------
- reference_fiche   : required, non-empty — it is the primary key for
                      the entire downstream pipeline. A missing or blank
                      value would silently corrupt the PostgreSQL table.
- date_de_publication: optional, but must match YYYY-MM-DD when present —
                      update_last_processed_file() parses this field with
                      strptime and will raise on an unexpected format.
- date_debut/fin_commercialisation: optional, DD/MM/YYYY when present —
                      produced by separate_commercialisation_dates() regex.
- All other fields  : Optional[str], no format constraint.
"""

import re
from typing import Optional

from pydantic import BaseModel, validator


# ---------------------------------------------------------------------------
# Pydantic v1-compatible model
# Airflow 2.7.3 ships pydantic >=1.10.0,<2.0.0, so we stay on v1 syntax.
# ---------------------------------------------------------------------------

_DATE_YYYYMMDD = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_DDMMYYYY = re.compile(r"^\d{2}/\d{2}/\d{4}$")


class RappelConsoRecord(BaseModel):
    """Represents one fully-transformed recall record ready for Kafka."""

    # --- primary key --------------------------------------------------------
    reference_fiche: str

    # --- kept columns (links + raw dates) -----------------------------------
    liens_vers_les_images: Optional[str] = None
    lien_vers_la_liste_des_produits: Optional[str] = None
    lien_vers_la_liste_des_distributeurs: Optional[str] = None
    lien_vers_affichette_pdf: Optional[str] = None
    lien_vers_la_fiche_rappel: Optional[str] = None
    date_de_publication: Optional[str] = None
    date_de_fin_de_la_procedure_de_rappel: Optional[str] = None

    # --- normalised text columns --------------------------------------------
    categorie_de_produit: Optional[str] = None
    sous_categorie_de_produit: Optional[str] = None
    nom_de_la_marque_du_produit: Optional[str] = None
    noms_des_modeles_ou_references: Optional[str] = None
    identification_des_produits: Optional[str] = None
    conditionnements: Optional[str] = None
    temperature_de_conservation: Optional[str] = None
    zone_geographique_de_vente: Optional[str] = None
    distributeurs: Optional[str] = None
    motif_du_rappel: Optional[str] = None
    numero_de_contact: Optional[str] = None
    modalites_de_compensation: Optional[str] = None

    # --- derived / merged columns -------------------------------------------
    risques_pour_le_consommateur: Optional[str] = None
    recommandations_sante: Optional[str] = None
    date_debut_commercialisation: Optional[str] = None
    date_fin_commercialisation: Optional[str] = None
    informations_complementaires: Optional[str] = None

    # -----------------------------------------------------------------------
    # Validators
    # -----------------------------------------------------------------------

    @validator("reference_fiche")
    @classmethod
    def reference_fiche_non_empty(cls, v: str) -> str:
        """Primary key must never be null or whitespace-only."""
        if not v or not v.strip():
            raise ValueError(
                "reference_fiche is the primary key and must be a non-empty string; "
                "a null or blank value would silently corrupt the database."
            )
        return v.strip()

    @validator("date_de_publication")
    @classmethod
    def publication_date_format(cls, v: Optional[str]) -> Optional[str]:
        """
        update_last_processed_file() parses this field with
        datetime.strptime(row["date_de_publication"], "%Y-%m-%d"),
        so an unexpected format will raise a ValueError there.
        Catch it here first.
        """
        if v is not None and not _DATE_YYYYMMDD.match(v):
            raise ValueError(
                f"date_de_publication must be YYYY-MM-DD format; got '{v}'. "
                "This would break the incremental state update."
            )
        return v

    @validator("date_debut_commercialisation", "date_fin_commercialisation")
    @classmethod
    def commercialisation_date_format(cls, v: Optional[str]) -> Optional[str]:
        """
        separate_commercialisation_dates() produces DD/MM/YYYY strings.
        Anything else indicates the regex produced garbage output.
        """
        if v is not None and not _DATE_DDMMYYYY.match(v):
            raise ValueError(
                f"Commercialisation date must be DD/MM/YYYY format; got '{v}'."
            )
        return v

    class Config:
        # Extra fields from a future API response are silently ignored so
        # that new API columns don't break the pipeline before the schema
        # is updated to include them.
        extra = "ignore"
