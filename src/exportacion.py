"""Exportaciones compatibles con QGIS y trazabilidad científica."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
import zipfile
import sys

import numpy as np
import pandas as pd
import pyproj
import shapely
import sklearn

from .analysis import APP_VERSION, features_geojson, tabla_geometria


INSTRUCCIONES_QGIS = """IMPORTAR EN QGIS
================
1. Descomprime este ZIP.
2. QGIS > Capa > Añadir capa > Añadir capa vectorial: carga los archivos
   'zonas_circulares.geojson', 'envolventes_convexas.geojson',
   'empalmes_multirriesgo.geojson' y 'puntos.geojson'.
3. Todas las geometrías se exportan en WGS84 (EPSG:4326).
4. Simboliza zonas por 'tipo_riesgo', incidentes por 'tipo_riesgo' y
   empalmes por 'n_tipos'.
5. Abre 'resumen_zonas.csv' para consultar centroides y radios en metros.
6. Para medir áreas o distancias usa un CRS proyectado adecuado; los campos
   'area_m2' y 'radio_m' se calcularon en el CRS UTM registrado en el manifiesto.

IMPORTANTE
---------
Los polígonos representan agrupamientos geométricos de eventos. No demuestran
probabilidades, causalidad, severidad de incidentes ni riesgo individual. No
son rutas optimizadas y los datos de ejemplo son completamente simulados.
Si se usó filtro circular, NO representa los límites oficiales del municipio.
No interpretes un empalme de zonas como prueba de correlación estadística.
"""


def _json_blob(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def _csv_blob(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def crear_paquete(*, df_original: pd.DataFrame,
                  clasificados: pd.DataFrame,
                  zonas: list[dict],
                  envolventes: list[dict],
                  empalmes: list[dict],
                  to_geo,
                  epsg: int,
                  contenido_entrada: bytes,
                  config: dict,
                  calidad: dict) -> bytes:
    """Genera ZIP íntegramente en memoria, sin guardar cargas del usuario."""
    puntos = clasificados[["latitud", "longitud", "tipo_riesgo", "fila_excel", "cluster", "id_zona"]].copy()
    points_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "tipo_riesgo": str(row.tipo_riesgo), "fila_excel": int(row.fila_excel),
                    "cluster": int(row.cluster), "id_zona": str(row.id_zona),
                },
                "geometry": {
                    "type": "Point", "coordinates": [float(row.longitud), float(row.latitud)],
                },
            }
            for row in puntos.itertuples(index=False)
        ],
    }
    zdf = tabla_geometria(zonas, to_geo)
    edf = tabla_geometria(empalmes, to_geo)
    manifiesto = {
        "aplicacion": "Riesgos Urbanos - Agrupamiento Multirriesgo",
        "version_aplicacion": APP_VERSION,
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "sha256_archivo_entrada": hashlib.sha256(contenido_entrada).hexdigest(),
        "sistema_entrada": "EPSG:4326 / WGS84",
        "sistema_calculos": f"EPSG:{epsg}",
        "proyeccion": "UTM local inferida de la mediana de coordenadas",
        "semilla_aleatoria": 42,
        "parametros": config,
        "control_calidad": calidad,
        "filas_validas_originales": int(len(df_original)),
        "filas_clasificadas": int(len(clasificados)),
        "zonas_circulares": len(zonas),
        "empalmes_multirriesgo": len(empalmes),
        "librerias": {"python": sys.version.split()[0], "scikit_learn": sklearn.__version__,
                      "shapely": shapely.__version__, "pyproj": pyproj.__version__,
                      "pandas": pd.__version__, "numpy": np.__version__},
        "interpretacion": "Concentraciones geométricas exploratorias, no probabilidad de accidente ni delito.",
    }
    files = {
        "puntos.csv": _csv_blob(puntos),
        "puntos.geojson": _json_blob(points_geojson),
        "resumen_zonas.csv": _csv_blob(zdf),
        "resumen_empalmes.csv": _csv_blob(edf),
        "zonas_circulares.geojson": _json_blob(features_geojson(zonas, to_geo)),
        "envolventes_convexas.geojson": _json_blob(features_geojson(envolventes, to_geo)),
        "empalmes_multirriesgo.geojson": _json_blob(features_geojson(empalmes, to_geo)),
        "manifiesto_metodologico.json": _json_blob(manifiesto),
        "LEEME_QGIS.txt": INSTRUCCIONES_QGIS.encode("utf-8"),
    }
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=8) as z:
        for name, b in files.items():
            z.writestr(name, b)
    return buffer.getvalue()
