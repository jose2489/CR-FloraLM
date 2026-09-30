"""
style.py — Cartographic style constants for distribution maps.

All visual decisions live here: colors, transparencies, figure geometry.
Nothing in this file imports geopandas, rasterio, or matplotlib — it is
safe to import without GIS dependencies.
"""
import colorsys
import matplotlib.colors as mcolors

# ---------------------------------------------------------------------------
# Figure geometry (lat/lon degrees, valid for EPSG:4326 rendering).
# In Phase 3 these will be replaced by CRTM05 metric bounds when the
# renderer switches to WORKING_CRS = EPSG:5367.
# ---------------------------------------------------------------------------
XLIM = (-86.1, -82.4)   # Costa Rica longitude bounds
YLIM = (7.9, 11.3)      # Costa Rica latitude bounds
FIG_WIDTH = 9            # inches
DPI = 140

# ---------------------------------------------------------------------------
# Background and structural chrome colors
# ---------------------------------------------------------------------------
BG_COLOR         = "#111827"  # figure/axes background (dark slate)
EDGE_COLOR_DIM   = "#4c566a"  # border of unmatched regions
EDGE_COLOR_PANEL = "#374151"  # legend panel borders

# ---------------------------------------------------------------------------
# Per-region fill color palette — one stable hex per Nombre value.
# Grouped semantically: cordilleras=blues, llanuras=greens, valles=oranges,
# peninsulas=purples, filas=pinks, others=mixed.
# ---------------------------------------------------------------------------
REGION_COLORS: dict[str, str] = {
    # Cordilleras
    "Cordillera de Guanacaste":              "#4fc3f7",  # sky blue
    "Cordillera de Tilarán":                "#29b6f6",  # bright blue
    "Cordillera Central":                   "#03a9f4",  # medium blue
    "Cordillera de Talamanca":              "#0288d1",  # deep blue
    # Llanuras
    "Llanuras de Guanacaste":              "#81c784",  # light green
    "Llanuras de Tortuguero / Santa Clara": "#4caf50",  # green
    "Llanuras de San Carlos":              "#26a69a",  # teal-green
    "LLanura de los Guatusos":             "#00897b",  # teal
    "Llanuras del Diquís":                "#80cbc4",  # pale teal
    # Valles
    "Valle Central Oriental":              "#ffb74d",  # amber-orange
    "Valle Central Occidental":            "#ffa726",  # orange
    "Valle del General":                   "#ff8a65",  # salmon-orange
    "Valle del Coto Brus":                "#ff7043",  # deep orange
    # Penínsulas
    "Península de Nicoya":                "#ce93d8",  # lilac
    "Península de Osa - Golfito":         "#ab47bc",  # purple
    # Filas Costeñas
    "Fila Costeña Norte":                "#f06292",  # pink
    "Fila Costeña Sur":                  "#ec407a",  # deep pink
    # Others
    "Tárcoles - Térraba":               "#dce775",  # yellow-green
    "Baja Talamanca":                     "#ffee58",  # yellow
    "Puriscal - Los Santos":             "#a5d6a7",  # pale green
    "Turrubares":                         "#80deea",  # cyan
    "Coto Colorado":                      "#b0bec5",  # blue-gray
    "Punta Burica":                       "#f48fb1",  # light pink
    "Filas Chonta y Nara":               "#c5e1a5",  # pale lime
}

FALLBACK_REGION_COLOR = "#78909c"  # shown for any Nombre not in the palette


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

def mute_color(hex_color: str, saturation: float = 0.3, lightness: float = 0.4) -> str:
    """Return a desaturated/darkened version of a hex color (HSV space)."""
    r, g, b = mcolors.to_rgb(hex_color)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s * saturation, v * lightness)
    return mcolors.to_hex((r2, g2, b2))
