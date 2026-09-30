"""
geodata.py — Cached shapefile loaders for distribution map layers.

Single source of truth for:
  - PATHS dict (all shapefile locations)
  - WORKING_CRS (currently EPSG:4326; migrates to EPSG:5367 in Phase 3)
  - _repair() pipeline (invalid geom fix, known attribute fixes)

All public loaders return GeoDataFrames in WORKING_CRS.
"""
import sys
import os
import struct
from pathlib import Path

import geopandas as gpd
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import config as _cfg

# ---------------------------------------------------------------------------
# CRS — will change to "EPSG:5367" (CRTM05) in Phase 3 when the renderer
# is rebuilt to use metric coordinates. EPSG:4326 kept here so Phase 1 is
# a zero-behaviour-change extraction.
# ---------------------------------------------------------------------------
WORKING_CRS = "EPSG:4326"

# ---------------------------------------------------------------------------
# All shapefile paths in one place — change paths here, nowhere else.
# ---------------------------------------------------------------------------
PATHS: dict[str, Path] = {
    "regiones_botanicas": Path(_cfg.REGIONES_BOTANICAS_SHP),
    "protected_areas":    Path(_cfg.PROTECTED_AREAS_V2_SHP),
    "dem":                Path(_cfg.DEM_PATH),
    "provincias":         Path(_cfg.CARTOGRAFIA_DIR) / "IGN_5_limite_Provincial.shp",
    "cantones":           Path(_cfg.CARTOGRAFIA_DIR) / "IGN_5_limite_cantonal.shp",
    "distritos":          Path(_cfg.CARTOGRAFIA_DIR) / "IGN_5_limite_distrital.shp",
    "holdridge":          Path(_cfg.CARTOGRAFIA_DIR) / "Zonas_de_vida_Holdridge.shp",
}

# ---------------------------------------------------------------------------
# Known data-quality fixes applied during load (keeps fix logic out of
# the renderer and avoids ad-hoc patches scattered in calling code).
# ---------------------------------------------------------------------------
_ATTRIBUTE_FIXES: dict[str, dict] = {
    "Vertiente": {
        # Botanical regions shapefile sometimes has "NULLCaribe" / "NULLPacifico"
        "starts_with": "NULL",
        "replacement": lambda v: v[4:],   # strip the leading "NULL"
    }
}


def _repair(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Standard repair pipeline applied to every loaded shapefile."""
    gdf = gdf.copy()
    # Fix invalid geometries (common in SINAC shapefiles)
    gdf["geometry"] = gdf.geometry.buffer(0)
    gdf = gdf[~gdf.is_empty].reset_index(drop=True)
    # Fix known bad attribute values
    for col, fix in _ATTRIBUTE_FIXES.items():
        if col not in gdf.columns:
            continue
        prefix = fix["starts_with"]
        mask = gdf[col].str.startswith(prefix, na=False)
        if mask.any():
            n = mask.sum()
            print(f"  [WARN] Fixing {n} malformed '{col}' value(s) in shapefile")
            gdf.loc[mask, col] = gdf.loc[mask, col].apply(fix["replacement"])
    return gdf


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------

def load_regiones_botanicas() -> gpd.GeoDataFrame:
    """Load botanical regions, repair, reproject to WORKING_CRS, add vert_norm."""
    gdf = gpd.read_file(PATHS["regiones_botanicas"])
    gdf = _repair(gdf)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(WORKING_CRS)
    gdf["vert_norm"] = gdf["Vertiente"].apply(
        lambda v: "carib" if "carib" in str(v).lower() else "pacifico"
    )
    return gdf


def load_protected_areas() -> gpd.GeoDataFrame:
    """Load SINAC protected areas, repair, reproject to WORKING_CRS."""
    gdf = gpd.read_file(PATHS["protected_areas"])
    gdf = _repair(gdf)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(WORKING_CRS)
    return gdf


def _fix_dbf_truncated_utf8(dbf_path: Path) -> None:
    """
    In-place patch: DBF field names with accented characters (e.g. CANTÓN, CÓDIGO)
    sometimes have their last byte truncated when the UTF-8 sequence overflows
    the 10-byte slot. This causes pyogrio to raise UnicodeDecodeError when reading
    field names. We strip the incomplete trailing byte so pyogrio can open the file.

    The patch is idempotent — if the name is already valid UTF-8, it is left alone.
    Only field names are patched; no data bytes are changed.
    """
    with open(dbf_path, "rb") as f:
        raw = bytearray(f.read())

    if len(raw) < 64:
        return

    try:
        header_size = struct.unpack_from("<H", raw, 8)[0]
    except struct.error:
        return

    modified = False
    pos = 32
    while pos + 32 <= len(raw) and raw[pos] != 0x0D and pos < header_size:
        field_bytes = raw[pos : pos + 11]
        raw_name = bytes(field_bytes).split(b"\x00")[0]
        try:
            raw_name.decode("utf-8")
        except UnicodeDecodeError:
            # Find the last valid UTF-8 prefix and null-pad the rest
            for end in range(len(raw_name), 0, -1):
                try:
                    raw_name[:end].decode("utf-8")
                    clean = raw_name[:end]
                    break
                except UnicodeDecodeError:
                    continue
            else:
                clean = raw_name.decode("ascii", errors="ignore").encode("ascii")

            new_field = clean + b"\x00" * (11 - len(clean))
            raw[pos : pos + 11] = new_field[:11]
            modified = True
        pos += 32

    if modified:
        with open(dbf_path, "wb") as f:
            f.write(bytes(raw))


def _safe_read_shapefile(path: Path, **kwargs) -> gpd.GeoDataFrame:
    """Read shapefile, patching DBF truncated UTF-8 field names if needed."""
    dbf_path = path.with_suffix(".dbf")
    if dbf_path.exists():
        _fix_dbf_truncated_utf8(dbf_path)
    return gpd.read_file(path, **kwargs)


def load_cantones() -> gpd.GeoDataFrame:
    """Load IGN canton boundaries. Key attribute: CANTÓN (canton name)."""
    gdf = _safe_read_shapefile(PATHS["cantones"])
    gdf = _repair(gdf)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(WORKING_CRS)
    return gdf


def load_distritos() -> gpd.GeoDataFrame:
    """Load IGN district boundaries. Key attributes: DISTRITO, CANTÓN, PROVINCIA."""
    gdf = _safe_read_shapefile(PATHS["distritos"])
    gdf = _repair(gdf)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(WORKING_CRS)
    return gdf


def load_provincias() -> gpd.GeoDataFrame:
    """Load IGN province boundaries. Key attribute: PROVINCIA."""
    gdf = _safe_read_shapefile(PATHS["provincias"])
    gdf = _repair(gdf)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(WORKING_CRS)
    return gdf


def load_holdridge_zones() -> gpd.GeoDataFrame:
    """
    Load Holdridge life zone polygons.
    Key attribute: nombre (e.g. 'BOSQUE MUY HUMEDO TROPICAL').
    Also useful: zone (code), piso (altitudinal belt).
    """
    gdf = _safe_read_shapefile(PATHS["holdridge"])
    gdf = _repair(gdf)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(WORKING_CRS)
    return gdf


def filter_pa_to_regions(
    pa_gdf: gpd.GeoDataFrame, region_gdf: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Clip protected areas to the union of the highlighted botanical regions.
    Geometries are truncated at region boundaries so no PA outline extends
    into non-highlighted areas.
    """
    if region_gdf.empty:
        return pa_gdf.iloc[0:0]
    try:
        pa_valid = pa_gdf.copy()
        pa_valid["geometry"] = pa_valid.geometry.buffer(0)
        region_valid = region_gdf.copy()
        region_valid["geometry"] = region_valid.geometry.buffer(0)
        region_union = unary_union(region_valid.geometry)
        clipped = gpd.clip(pa_valid, region_union)
        clipped = clipped[~clipped.is_empty].reset_index(drop=True)
        return clipped
    except Exception as e:
        print(f"  [WARN] Protected-area clip failed: {e}")
        return pa_gdf.iloc[0:0]
