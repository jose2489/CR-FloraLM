import os
import rasterio
import geopandas as gpd
from shapely.geometry import Point

def extraer_altitud(df, ruta_altitud):
    """Extrae el valor del píxel de altitud para cada coordenada del DataFrame."""
    print("[INFO] Extrayendo variables de Altitud...")
    valores_altitud = []
    
    # === BLINDAJE DINÁMICO DE COLUMNAS ===
    # Busca cómo se llama la columna de longitud
    if 'decimalLongitude' in df.columns:
        lon_col = 'decimalLongitude'
    elif 'lon' in df.columns:
        lon_col = 'lon'
    elif 'longitude' in df.columns:
        lon_col = 'longitude'
    else:
        raise KeyError("[ERROR] No se encontró la columna de longitud en el DataFrame.")

    # Busca cómo se llama la columna de latitud
    if 'decimalLatitude' in df.columns:
        lat_col = 'decimalLatitude'
    elif 'lat' in df.columns:
        lat_col = 'lat'
    elif 'latitude' in df.columns:
        lat_col = 'latitude'
    else:
        raise KeyError("[ERROR] No se encontró la columna de latitud en el DataFrame.")
    # =======================================
    
    with rasterio.open(ruta_altitud) as src_alt:
        nodata = src_alt.nodata  # typically -32768 for Int16 DEMs
        for idx, row in df.iterrows():
            lon, lat = row[lon_col], row[lat_col]
            try:
                for val in src_alt.sample([(lon, lat)]):
                    pixel = val[0]
                    # Reject nodata values (e.g. -32768) and implausible negatives
                    if nodata is not None and pixel == nodata:
                        valores_altitud.append(None)
                    elif pixel < -500:  # safety net for any nodata variant
                        valores_altitud.append(None)
                    else:
                        valores_altitud.append(pixel)
            except Exception:
                valores_altitud.append(None)
                
    df['Altitud'] = valores_altitud
    return df

def generar_contexto_conservacion(df, dicc_rutas_vectores):
    """Cruza las presencias con múltiples Shapefiles y redacta el resumen ecológico."""
    print("[INFO] Realizando cruce espacial con capas vectoriales múltiples...")
    
    # 1. Manejo dinámico de coordenadas y creación de GeoDataFrame
    lon_col = 'decimalLongitude' if 'decimalLongitude' in df.columns else 'lon'
    lat_col = 'decimalLatitude' if 'decimalLatitude' in df.columns else 'lat'
    
    geometria = [Point(xy) for xy in zip(df[lon_col], df[lat_col])]
    gdf_puntos = gpd.GeoDataFrame(df, geometry=geometria, crs="EPSG:4326")
    
    # Trabajamos solo con presencias reales (clase == 1) si la columna existe
    if 'clase' in df.columns:
        gdf_puntos = gdf_puntos[gdf_puntos['clase'] == 1]
        
    total_presencias = len(gdf_puntos)
    if total_presencias == 0:
        return "No hay presencias válidas para calcular métricas espaciales."

    # 2. Iniciar el texto del súper-contexto para el LLM
    texto_contexto = "ANÁLISIS DE CONSERVACIÓN, POLÍTICA Y TOPOGRAFÍA (Nicho Realizado):\n"
    
    # 3. Cálculos de Altitud
    if 'Altitud' in df.columns:
        # Filtramos de nuevo por clase 1 solo para asegurar la estadística correcta
        df_presencias = df[df['clase']==1] if 'clase' in df.columns else df
        alt_min = round(df_presencias['Altitud'].min(), 1)
        alt_max = round(df_presencias['Altitud'].max(), 1)
        alt_mean = round(df_presencias['Altitud'].mean(), 1)
        texto_contexto += f"- Rango de Altitud: de {alt_min} a {alt_max} m.s.n.m. (Media: {alt_mean} m).\n"
    else:
        texto_contexto += "- Datos de altitud no disponibles.\n"

    # 4. Magia Pura: Iterar sobre cada shapefile proporcionado
    for nombre_capa, ruta_shp in dicc_rutas_vectores.items():
        try:
            if not os.path.exists(ruta_shp):
                texto_contexto += f"- {nombre_capa}: Archivo shapefile no encontrado.\n"
                continue
                
            gdf_shp = gpd.read_file(ruta_shp)
            
            # Buscador inteligente de la columna del nombre
            columna_nombre = None
            posibles_nombres = ['nombre_asp', 'nombre_ac', 'nombre', 'NOMBRE', 'descripcio']
            for nom in posibles_nombres:
                if nom in gdf_shp.columns:
                    columna_nombre = nom
                    break
            
            # Si tiene nombres muy raros, usamos la primera columna por defecto
            if not columna_nombre:
                columna_nombre = gdf_shp.columns[0]

            # Cruce espacial matemático
            gdf_cruce = gpd.sjoin(gdf_puntos, gdf_shp, how="left", predicate="intersects")
            
            # Estadísticas
            puntos_adentro = gdf_cruce[gdf_cruce[columna_nombre].notna()]
            porcentaje = round((len(puntos_adentro) / total_presencias) * 100, 2)
            
            if porcentaje > 0:
                top_sitios = puntos_adentro[columna_nombre].value_counts().head(3)
                texto_sitios = ", ".join([f"{n} ({c} reg)" for n, c in top_sitios.items()])
                texto_contexto += f"- {nombre_capa}: El {porcentaje}% de los registros caen aquí. Principales: {texto_sitios}.\n"
            else:
                texto_contexto += f"- {nombre_capa}: No hay presencia significativa (0%).\n"
                
        except Exception as e:
            print(f"[ERROR] Falló el procesamiento de la capa {nombre_capa}: {e}")
            texto_contexto += f"- {nombre_capa}: Error al procesar capa espacial.\n"

    return texto_contexto