"""Motor geoespacial reproducible para analizar categorías de incidentes.

Entrada: Excel (latitud, longitud, tipo_riesgo) en WGS84. Las zonas son
representaciones geométricas *exploratorias*, NO probabilidades ni riesgo real
calibrado. Todas las distancias y superficies se calculan en UTM (metros).
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import math
from typing import Any
import unicodedata

import numpy as np
import pandas as pd
from pyproj import CRS, Transformer
from shapely.geometry import Point, shape, mapping, MultiPoint
from shapely.ops import transform, unary_union
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

SEED = 42
APP_VERSION = "1.1.0"
REQUIRED = ("latitud", "longitud", "tipo_riesgo")


class DatosError(ValueError):
    """Datos de entrada no compatibles con el formato requerido."""


def _normaliza_columna(label: Any) -> str:
    txt = unicodedata.normalize("NFKD", str(label).strip().lower())
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return txt.replace(" ", "_")


def leer_excel(contenido: bytes) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Lee la PRIMERA hoja y valida A/B/C. Mantiene duplicados: son eventos.

    Ignora columnas adicionales, pero exige las tres columnas por nombre.
    La fila de origen permite identificar registros descartados.
    """
    if not contenido:
        raise DatosError("El archivo está vacío.")
    try:
        raw = pd.read_excel(BytesIO(contenido), sheet_name=0, engine="openpyxl")
    except Exception as exc:
        raise DatosError(f"No fue posible leer el Excel: {exc}") from exc
    raw.columns = [_normaliza_columna(c) for c in raw.columns]
    if len(set(raw.columns)) != len(raw.columns):
        raise DatosError("Existen columnas con nombres repetidos después de normalizarlas.")
    if not set(REQUIRED).issubset(raw.columns):
        raise DatosError("La primera hoja requiere las columnas: latitud, longitud y tipo_riesgo.")

    df = raw.loc[:, REQUIRED].copy()
    df["fila_excel"] = np.arange(2, len(df) + 2)
    total = len(df)
    if total == 0:
        raise DatosError("La hoja está vacía; incluye al menos un incidente.")
    if total > 30000:
        raise DatosError("Límite de seguridad: 30 000 filas por archivo.")

    for col in ("latitud", "longitud"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["tipo_riesgo"] = (df["tipo_riesgo"].fillna("").astype(str)
                         .str.strip().str.replace(r"\s+", " ", regex=True))
    # Se conserva la primera grafía; mayúsculas/minúsculas no crean una categoría nueva.
    grafias = {}
    for etiqueta in df["tipo_riesgo"]:
        clave = etiqueta.casefold()
        grafias.setdefault(clave, etiqueta)
    df["tipo_riesgo"] = df["tipo_riesgo"].map(lambda etiqueta: grafias[etiqueta.casefold()])
    # Un registro sin tipo o sin coordenada no se asigna a categoría genérica.
    valid = (df["latitud"].between(-90, 90)
             & df["longitud"].between(-180, 180)
             & np.isfinite(df["latitud"].to_numpy())
             & np.isfinite(df["longitud"].to_numpy())
             & df["tipo_riesgo"].ne(""))
    valid_df = df.loc[valid].reset_index(drop=True)
    if len(valid_df) == 0:
        raise DatosError("No hay coordenadas válidas asociadas a un tipo de riesgo.")
    # En este flujo, cada tipo se controla como categoría independiente.
    if valid_df["tipo_riesgo"].nunique() > 20:
        raise DatosError("Se admiten hasta 20 tipos de riesgo por ejecución.")
    issues = {
        "registros_originales": total,
        "registros_validos": len(valid_df),
        "registros_invalidos": int((~valid).sum()),
        "filas_invalidas": df.loc[~valid, "fila_excel"].astype(int).tolist()[:50],
        "riesgos_detectados": int(valid_df["tipo_riesgo"].nunique()),
        "coordenadas_repetidas": int(valid_df.duplicated(["latitud", "longitud", "tipo_riesgo"]).sum()),
    }
    return valid_df, issues


def utm_epsg(lat: float, lon: float) -> int:
    if not (-80 <= lat <= 84):
        raise DatosError("Se requiere un área compatible con la proyección UTM.")
    zona = max(1, min(60, int(math.floor((lon + 180) / 6) + 1)))
    return (32600 if lat >= 0 else 32700) + zona


def proyeccion(df: pd.DataFrame) -> tuple[pd.DataFrame, int, Transformer, Transformer]:
    """Convierte X=longitud, Y=latitud a UTM de la mediana espacial."""
    ep = utm_epsg(float(df.latitud.median()), float(df.longitud.median()))
    to_m = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_epsg(ep), always_xy=True)
    to_geo = Transformer.from_crs(CRS.from_epsg(ep), CRS.from_epsg(4326), always_xy=True)
    x, y = to_m.transform(df.longitud.to_numpy(), df.latitud.to_numpy())
    out = df.copy()
    out["x_m"] = x
    out["y_m"] = y
    return out, ep, to_m, to_geo


def leer_limite_geojson(contenido: bytes):
    """Lee límite opcional GeoJSON RFC 7946 (lon/lat)."""
    try:
        obj = json.loads(contenido)
        if obj.get("type") == "FeatureCollection":
            formas = [shape(f["geometry"]) for f in obj["features"] if f.get("geometry")]
            poly = unary_union(formas) if formas else None
        elif obj.get("type") == "Feature":
            poly = shape(obj["geometry"])
        else:
            poly = shape(obj)
        if poly is None or poly.is_empty or poly.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError("El límite debe contener polígonos.")
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            raise ValueError("El polígono resultante está vacío.")
        return poly
    except (ValueError, KeyError, TypeError) as exc:
        raise DatosError(f"GeoJSON del límite no válido: {exc}") from exc


def filtrar_area(df: pd.DataFrame, modo: str, *,
                 centro_lat: float | None = None,
                 centro_lon: float | None = None,
                 radio_km: float | None = None,
                 limite_geojson=None) -> tuple[pd.DataFrame, int]:
    """El filtro circular es urbano, NO límite oficial del municipio."""
    if modo == "Sin filtro":
        return df.copy().reset_index(drop=True), 0
    if modo == "Radio urbano":
        if centro_lat is None or centro_lon is None or radio_km is None:
            raise DatosError("Falta centro o radio para aplicar el filtro urbano.")
        epsg = utm_epsg(centro_lat, centro_lon)
        tm = Transformer.from_crs(4326, epsg, always_xy=True)
        x1, y1 = tm.transform(df.longitud.to_numpy(), df.latitud.to_numpy())
        x0, y0 = tm.transform(centro_lon, centro_lat)
        select = np.hypot(x1 - x0, y1 - y0) <= radio_km * 1000
    elif modo == "Límite municipal (GeoJSON)":
        if limite_geojson is None:
            raise DatosError("Para filtrar por municipio carga un GeoJSON poligonal.")
        select = np.array([limite_geojson.covers(Point(lon, lat))
                           for lat, lon in zip(df.latitud, df.longitud)])
    else:
        raise DatosError("Modo de filtro desconocido.")
    included = df.loc[select].copy().reset_index(drop=True)
    if included.empty:
        raise DatosError("El filtro excluyó todos los registros; cambia el área de estudio.")
    return included, int((~select).sum())


def k_sugerido(coords: np.ndarray, *, max_k: int = 12) -> tuple[int, dict[int, float]]:
    """K-Means con semilla fija; usa silhouette cuando hay suficientes puntos.

    K=1 para menos de cuatro coordenadas únicas. La silueta NO valida
    causalidad, riesgo, ni carácter estadístico de un hotspot.
    """
    n_unique = len(np.unique(coords, axis=0))
    n = len(coords)
    if n_unique < 4 or n < 5:
        return 1, {}
    upper = min(max_k, n_unique - 1, max(2, round(math.sqrt(n_unique))))
    scores: dict[int, float] = {}
    for k in range(2, upper + 1):
        labels = KMeans(n_clusters=k, random_state=SEED, n_init=10).fit_predict(coords)
        if len(set(labels)) < 2 or len(set(labels)) >= n:
            continue
        try:
            scores[k] = float(silhouette_score(coords, labels, sample_size=min(n, 2000), random_state=SEED))
        except ValueError:
            continue
    if scores:
        return max(scores, key=lambda k: (scores[k], -k)), scores
    return 1, {}


def ajustar_por_riesgo(df_proy: pd.DataFrame, k_por_riesgo: dict[str, int],
                       radio_minimo_m: float = 80.0,
                       buffer_hull_m: float = 20.0) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    """K-Means separado por riesgo, círculo incluyente y hull opcional.

    Si k=1 cubre todo el conjunto; si k=n_distintos aparecerán clusters
    unitarios y la zona usa exclusivamente el radio mínimo configurado.
    """
    clasificados = []
    zonas: list[dict] = []
    envolventes: list[dict] = []
    for riesgo, grupo in df_proy.groupby("tipo_riesgo", sort=True):
        grupo = grupo.copy()
        xy = grupo[["x_m", "y_m"]].to_numpy(dtype=float)
        n_distintos = len(np.unique(xy, axis=0))
        k = int(k_por_riesgo[riesgo])
        if not 1 <= k <= n_distintos:
            raise DatosError(f"Para {riesgo}, K debe estar entre 1 y {n_distintos}.")
        kmeans = KMeans(n_clusters=k, random_state=SEED, n_init=10)
        grupo["cluster"] = kmeans.fit_predict(xy) + 1
        grupo["id_zona"] = grupo["tipo_riesgo"] + "_" + grupo["cluster"].astype(str)
        clasificados.append(grupo)
        for cid, sg in grupo.groupby("cluster", sort=True):
            cx, cy = kmeans.cluster_centers_[int(cid) - 1]
            xy_local = sg[["x_m", "y_m"]].to_numpy(dtype=float)
            max_m = float(np.linalg.norm(xy_local - [cx, cy], axis=1).max())
            radius = max(float(radio_minimo_m), max_m + 0.001)  # Pequeño margen numérico.
            circle = Point(cx, cy).buffer(radius, quad_segs=32)
            hull = MultiPoint([Point(v) for v in xy_local]).convex_hull.buffer(buffer_hull_m)
            props = {
                "id_zona": f"{riesgo}_{cid}",
                "tipo_riesgo": str(riesgo),
                "cluster": int(cid),
                "n_incidentes": int(len(sg)),
                "centro_x_m": float(cx),
                "centro_y_m": float(cy),
                "dist_max_m": round(max_m, 3),
                "radio_m": round(radius, 3),
                "area_m2": round(float(circle.area), 2),
                "concentracion_geom_eventos_km2": round(len(sg) * 1_000_000 / float(circle.area), 4),
            }
            zonas.append({**props, "geometry": circle})
            envolventes.append({**props, "geometry": hull, "area_m2": round(float(hull.area), 2)})
    return pd.concat(clasificados, ignore_index=True), zonas, envolventes


def _partes_poligonales(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g] if g.area > 1e-8 else []
    if hasattr(g, "geoms"):
        return [poly for sub in g.geoms for poly in _partes_poligonales(sub)]
    return []


def superposiciones(zonas: list[dict], area_minima_m2: float = 100.0) -> list[dict]:
    """Partición sin doble conteo por conjuntos EXACTOS de tipos de riesgo.

    Primero se disuelven todos los círculos del mismo tipo, luego se produce
    overlay incremental. Las zonas resultantes no solapan entre sí y pueden
    corresponder a DOS, TRES o más tipos simultáneos.
    """
    nombres = sorted({str(z["tipo_riesgo"]) for z in zonas})
    if len(nombres) < 2:
        return []
    por_tipo = {t: unary_union([z["geometry"] for z in zonas if z["tipo_riesgo"] == t]) for t in nombres}
    partes: list[tuple[frozenset[str], object]] = []
    for nombre in nombres:
        geom = por_tipo[nombre]
        if not partes:
            partes = [(frozenset([nombre]), p) for p in _partes_poligonales(geom)]
            continue
        anteriores = unary_union([g for _, g in partes])
        nueva: list[tuple[frozenset[str], object]] = []
        for etiquetas, anterior in partes:
            for pieza in _partes_poligonales(anterior.difference(geom)):
                nueva.append((etiquetas, pieza))
            for pieza in _partes_poligonales(anterior.intersection(geom)):
                nueva.append((etiquetas | {nombre}, pieza))
        for pieza in _partes_poligonales(geom.difference(anteriores)):
            nueva.append((frozenset([nombre]), pieza))
        partes = nueva

    agrupar = {}
    for etiquetas, geom in partes:
        if len(etiquetas) < 2:
            continue
        agrupar.setdefault(tuple(sorted(etiquetas)), []).append(geom)
    result = []
    for etiquetas, geometries in sorted(agrupar.items()):
        combinado = unary_union(geometries)
        for g in _partes_poligonales(combinado):
            if g.area < area_minima_m2:
                continue
            rp = g.representative_point()
            result.append({
                "id_empalme": f"E{len(result)+1:03d}",
                "riesgos": " | ".join(etiquetas),
                "n_tipos": len(etiquetas),
                "area_m2": round(float(g.area), 2),
                "centro_x_m": float(rp.x),
                "centro_y_m": float(rp.y),
                "geometry": g,
            })
    return result


def features_geojson(registros: list[dict], to_geo: Transformer) -> dict:
    fs = []
    for row in registros:
        geom = transform(to_geo.transform, row["geometry"])
        props = {k: v for k, v in row.items() if k != "geometry"}
        # Los centroides X/Y se mantienen como métricas de análisis, no como lat/lon.
        fs.append({"type": "Feature", "properties": props, "geometry": mapping(geom)})
    return {"type": "FeatureCollection", "features": fs}


def tabla_geometria(rows: list[dict], to_geo: Transformer) -> pd.DataFrame:
    salida = []
    for row in rows:
        d = {k:v for k,v in row.items() if k != "geometry"}
        latlon = to_geo.transform(row["centro_x_m"], row["centro_y_m"])
        d["centro_longitud"] = round(float(latlon[0]), 7)
        d["centro_latitud"] = round(float(latlon[1]), 7)
        salida.append(d)
    return pd.DataFrame(salida)
