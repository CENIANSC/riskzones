"""Descarga una red DE CONDUCCIÓN de OpenStreetMap mediante OSMnx.

Transforma el MultiDiGraph OSMnx en el GeoJSON de arcos dirigidos que consume
el motor vial del CVRP. No convierte vías OSM en líneas de doble sentido:
cada arco dirigido se exporta con `oneway=yes` para conservar la direccionalidad.
No interpreta restricciones de giro ni tráfico en tiempo real.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from typing import Any

from shapely.geometry import LineString, mapping

from src.cvrp import CVRPError

VERSION_RED_OSM = "1.0"
MAX_GEOJSON_BYTES = 22_000_000
MAX_VERTICES_PROYECTADOS = 12_000


def _validar_entrada(lat: float, lon: float, radio_m: float) -> None:
    if not all(math.isfinite(float(x)) for x in (lat, lon, radio_m)):
        raise CVRPError("Las coordenadas y el radio deben ser números finitos.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise CVRPError("Coordenadas inválidas para el centro de descarga.")
    if not (500 <= radio_m <= 5000):
        raise CVRPError("Selecciona un radio entre 500 y 5,000 metros.")


def exportar_grafo_osmnx(grafo, *, centro: tuple[float,float], radio_m: float,
                           fecha_utc: str | None = None) -> tuple[bytes, dict[str, Any]]:
    """Exporta arcos dirigidos de OSMnx a GeoJSON WGS84 (para modo B).

    El punto de inicio/fin de cada polilínea se fuerza a la coordenada
    del nodo correspondiente: mantiene conexiones OSMnx en el grafo de CVRP.
    Los arcos paralelos se preservan en features separadas; el motor CVRP
    elige la arista de menor costo entre extremos repetidos.
    """
    if grafo.number_of_nodes() < 2 or grafo.number_of_edges() < 1:
        raise CVRPError("La consulta OSM no produjo calles utilizables.")
    features=[]
    oriented_vertices=set()
    for u,v,key,data in grafo.edges(keys=True,data=True):
        a=grafo.nodes[u]; b=grafo.nodes[v]
        orig=(float(a['x']),float(a['y']))
        dest=(float(b['x']),float(b['y']))
        geom=data.get('geometry')
        coords=list(geom.coords) if geom is not None else [orig,dest]
        coords=[(float(x),float(y)) for x,y,*_ in coords]
        # OSMnx direction is u -> v; the shape is sometimes reversed.
        if len(coords)>2:
            direct=math.dist(coords[0],orig)+math.dist(coords[-1],dest)
            inverse=math.dist(coords[-1],orig)+math.dist(coords[0],dest)
            if inverse < direct:
                coords.reverse()
        coords[0]=orig; coords[-1]=dest
        if len(coords)<2 or orig==dest:
            continue
        if not all(math.isfinite(t) for pt in coords for t in pt):
            raise CVRPError("La red OSM contiene una coordenada inválida.")
        if any(abs(x)>180 or abs(y)>90 for x,y in coords):
            raise CVRPError("La red OSM no está en EPSG:4326.")
        # Los sentidos quedan explícitos por ARCO: incluso en una calle de
        # doble sentido, OSMnx devuelve ambos arcos como features distintas.
        features.append({'type':'Feature',
                         'properties':{'origen':'OpenStreetMap/OSMnx',
                             'osm_u':str(u),'osm_v':str(v),'osm_key':str(key),
                             'oneway':'yes','name':str(data.get('name','')),
                             'highway':str(data.get('highway',''))},
                         'geometry':mapping(LineString(coords))})
        for pt in coords:
            oriented_vertices.add((round(pt[0],6),round(pt[1],6)))
    if len(oriented_vertices)>MAX_VERTICES_PROYECTADOS:
        raise CVRPError(f'Área demasiado extensa para Streamlit gratuito: {len(oriented_vertices)} vértices aproximados (límite {MAX_VERTICES_PROYECTADOS}). Reduce el radio.')
    if not features:
        raise CVRPError("La red no produjo arcos dirigidos exportables.")
    stamp=fecha_utc or datetime.now(timezone.utc).isoformat()
    metadata={'fuente':'OpenStreetMap (Overpass) mediante OSMnx',
        'version_exportador':VERSION_RED_OSM,
        'fecha_descarga_utc':stamp,'centro_latitud':float(centro[0]),
        'centro_longitud':float(centro[1]),'radio_consulta_m':int(radio_m),
        'tipo_red':'drive','epsg':'EPSG:4326',
        'nodos_osmnx':int(grafo.number_of_nodes()),
        'arcos_dirigidos':len(features),
        'vertices_aproximados':len(oriented_vertices),
        'notas':['Datos OSM de cobertura variable; verificar restricciones locales.',
                 'Sentidos de calles representados por arcos dirigidos.',
                 'No se incorporan restricciones de giro ni velocidad/tráfico en tiempo real.',
                 'Los conectores de clientes a vértices próximos son geométricos.']}
    geo={'type':'FeatureCollection','features':features,'metadata':metadata}
    blob=json.dumps(geo,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(blob)>MAX_GEOJSON_BYTES:
        raise CVRPError('El GeoJSON supera 22 MB; reduce el radio de descarga.')
    return blob,metadata


def descargar_red_osm(lat:float,lon:float,radio_m:float) -> tuple[bytes,dict[str, Any]]:
    """Solicita la red al servidor Overpass cuando el usuario lo activa."""
    _validar_entrada(lat,lon,radio_m)
    try:
        import osmnx as ox
    except ImportError as exc:
        raise CVRPError('OSMnx no está instalado: actualiza requirements.txt y reinicia la app.') from exc
    try:
        ox.settings.use_cache=True
        ox.settings.requests_timeout=120
        g=ox.graph.graph_from_point((float(lat),float(lon)),dist=int(radio_m),
               dist_type='bbox',network_type='drive',simplify=True,
               retain_all=False,truncate_by_edge=True)
    except Exception as exc:
        raise CVRPError('No se pudo descargar la red vial real. Revisa Internet/Overpass, reduce el radio o sube un GeoJSON desde QGIS. '
                        f'Detalle técnico: {type(exc).__name__}: {str(exc)[:280]}') from exc
    return exportar_grafo_osmnx(g,centro=(lat,lon),radio_m=radio_m)
