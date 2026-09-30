"""Paths to the geospatial base layers used by the map pipeline.

These layers are third-party and are not redistributed with this repository; see
README, "Data not included". Point DATA_DIR at a directory holding them, or override
the individual paths.

Language-model and vector-store settings live in mpcr_rag/config.py, not here.
"""
import os

from dotenv import load_dotenv

# --- project paths ----------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("CRFLORALM_DATA_DIR", os.path.join(BASE_DIR, "data_raw"))

# --- geospatial layers ------------------------------------------------------
# Digital elevation model: SRTM, public domain.
DEM_PATH = os.path.join(DATA_DIR, "topography", "altitud_cr.tif")

# Botanical regions: our digitization of the phytogeographic map of Costa Rica drawn
# by M. V. Castro for the Manual de Plantas de Costa Rica. Available on request.
REGIONES_BOTANICAS_SHP = os.path.join(DATA_DIR, "regiones_botanicas",
                                      "Jose_regiones_botanicas_con_vertiente.shp")

# Protected areas and base cartography: SNIT / SINAC.
PROTECTED_AREAS_V2_SHP = os.path.join(DATA_DIR, "vectors", "areas_protegidas_v2.shp")
CARTOGRAFIA_DIR = os.path.join(DATA_DIR, "Cartografia")

# --- credentials ------------------------------------------------------------
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
