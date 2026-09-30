import os
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

# 1. REPRODUCIBILIDAD ACADEMICA
SEED = 42
np.random.seed(SEED)

# 2. RUTAS BASE DEL PROYECTO
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data_raw")
OUTPUT_BASE_DIR = os.path.join(BASE_DIR, "outputs")

# Rutas de capas espaciales
DEM_PATH               = os.path.join(DATA_DIR, "topography", "altitud_cr.tif")
REGIONES_BOTANICAS_SHP = os.path.join(DATA_DIR, "regiones_botanicas",
                                      "Jose_regiones_botanicas_con_vertiente.shp")
PROTECTED_AREAS_V2_SHP = os.path.join(DATA_DIR, "vectors", "areas_protegidas_v2.shp")
CARTOGRAFIA_DIR        = os.path.join(DATA_DIR, "Cartografia")

# Crear directorios base si no existen
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_BASE_DIR, exist_ok=True)

# 3. VARIABLES DE ENTORNO Y APIs
#GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "Solicitar Key de GROQ en: https://console.groq.com/keys")
#Ponerla en un archivo .env
load_dotenv()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# 4. GESTOR DE DIRECTORIOS DE EJECUCION
def crear_directorio_ejecucion(especie_nombre):
    """
    Crea y retorna la ruta de una carpeta unica para la ejecucion actual,
    basada en la especie y la fecha/hora exacta.
    """
    # Formatear el nombre de la especie (espacios por guiones bajos)
    especie_formateada = especie_nombre.replace(" ", "_")
    
    # Generar marca de tiempo (Ej: 20260307_101530)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Construir ruta final: outputs/Especie_nombre/run_YYYYMMDD_HHMMSS/
    ruta_ejecucion = os.path.join(OUTPUT_BASE_DIR, especie_formateada, f"run_{timestamp}")
    
    # Crear la carpeta
    os.makedirs(ruta_ejecucion, exist_ok=True)
    
    return ruta_ejecucion

# Configuracion global de modelos permitidos o por defecto
DEFAULT_LLM = "llama-3.3-70b-versatile"
DEFAULT_COUNTRY = "Costa Rica"