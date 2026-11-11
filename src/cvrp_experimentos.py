"""Dos enfoques experimentales para el CVRP sensible al riesgo.

A / REPRODUCCIÓN METODOLÓGICA del artículo:
  - Distancia Haversine entre clientes y depósito (NO distancia vial).
  - Círculos envolventes de polígonos de empalmes multirriesgo.
  - Secantes detectadas sobre segmentos proyectados UTM.
  - c_ij = d_ij * (1 + lambda * sum_k(delta_ijk * (1-max(gamma_ik,gamma_jk))))
  - La exención de arcos con extremos dentro de zonas obedece a la
    formulación explicada en el manuscrito; no elimina el registro de cruces.

B / EXTENSIÓN CON RED VIAL:
  - Las calles proceden de un GeoJSON vial topológicamente conectado.
  - El camino de cada par de clientes se obtiene mediante Dijkstra sobre
    tramos con coste d + lambda * longitud_expuesta.
  - Este enfoque ES DISTINTO del criterio multiplicativo por arco del artículo.

Ninguno certifica optimalidad global ni reproduce resultados publicados sin
las mismas entradas exactas, modelo, solver, semillas y condiciones.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from src.cvrp import Matrices, CVRPError, matriz_vial


@dataclass
class CirculoConflicto:
    id_zona: str
    riesgos: str
    cx: float
    cy: float
    radio_m: float
    geometry: object
    area_empalme_m2: float


def crear_circulos_empalmes(empalmes: list[dict], min_radio_m: float = 1.0) -> list[dict]:
    """Circunscribe cada componente del empalme mediante centroide y radio máximo.

    El radio incluye todos los vértices de la geometría (incluidos interiores).
    No se toma el radio de los círculos K-Means originales.
    """
    if min_radio_m < 0:
        raise CVRPError('El radio mínimo debe ser no negativo.')
    salida = []
    for idx, empalme in enumerate(empalmes, 1):
        pol = empalme['geometry']
        if pol.is_empty or pol.area <= 0:
            continue
        centro = pol.centroid
        # Los componentes proceden del overlay poligonal, no de nodos/vértices sueltos.
        contornos = list(pol.geoms) if pol.geom_type == 'MultiPolygon' else [pol]
        vertices=[]
        for p in contornos:
            vertices.extend(p.exterior.coords)
            for hole in p.interiors:
                vertices.extend(hole.coords)
        if not vertices:
            continue
        radio = max(float(min_radio_m), max(math.hypot(float(x)-centro.x,float(y)-centro.y) for x,y in vertices))
        # La aproximación del polígono circular es solo para mapa/exportaciones;
        # el test secante se evalúa con radio matemático, no con el polígono discretizado.
        circle = Point(centro.x, centro.y).buffer(radio + 1e-6, quad_segs=64)
        salida.append({
            'id_zona': str(empalme.get('id_empalme', f'E{idx:03d}')),
            'riesgos':str(empalme.get('riesgos','')),
            'centro_x_m':float(centro.x),
            'centro_y_m':float(centro.y),
            'radio_m':round(radio,6),
            'area_empalme_m2':float(pol.area),
            'geometry':circle
        })
    return salida


def _hav_m(lon1,lat1,lon2,lat2):
    """Haversine con radio terrestre medio 6371008.8 m."""
    r=6371008.8
    a1,a2=np.deg2rad(lat1),np.deg2rad(lat2)
    da=a2-a1
    dl=np.deg2rad(lon2-lon1)
    a=np.sin(da/2)**2+np.cos(a1)*np.cos(a2)*np.sin(dl/2)**2
    return 2*r*np.arcsin(np.minimum(1.,np.sqrt(np.maximum(0.,a))))


def matriz_articulo(coords: np.ndarray, to_geo: Transformer,
                    circulos: list[dict], penalizacion:float=0.0) -> Matrices:
    """Haversine y penalización multiplicativa con secantes y clientes obligatorios.

    `cruces`: número de CÍRCULOS cuyo interior intersecta geométricamente cada arco.
    `arcos_penalizados`: número de CÍRCULOS cuyo arco debe penalizarse luego de
     aplicar la regla de exención si alguno de los extremos está en el círculo.

    La exposición métrica se reporta como longitud dentro de la UNIÓN de círculos,
    no se suma doble en las superposiciones; NO determina el costo del modo A.
    """
    if penalizacion < 0 or not np.isfinite(penalizacion):
        raise CVRPError('Lambda debe ser finito y no negativo.')
    coords=np.asarray(coords,dtype=float)
    if coords.ndim!=2 or coords.shape[1]!=2:
        raise CVRPError('Se esperan coordenadas proyectadas (N,2).')
    if not np.isfinite(coords).all():
        raise CVRPError('Hay coordenadas proyectadas inválidas.')
    n=len(coords)
    lon,lat=to_geo.transform(coords[:,0],coords[:,1])
    lon=np.asarray(lon,dtype=float);lat=np.asarray(lat,dtype=float)
    dist=np.asarray(_hav_m(lon[:,None],lat[:,None],lon[None,:],lat[None,:]),float)
    np.fill_diagonal(dist,0.)
    expon=np.zeros((n,n),float)
    cuenta=np.zeros((n,n),dtype=int)
    elegible=np.zeros((n,n),dtype=int)
    geometrias={}
    centros=[Point(float(z['centro_x_m']),float(z['centro_y_m'])) for z in circulos]
    radios=[float(z['radio_m']) for z in circulos]
    union=unary_union([z['geometry'] for z in circulos]) if circulos else None
    for i in range(n):
        for j in range(i+1,n):
            pts=[tuple(map(float,coords[i])),tuple(map(float,coords[j]))]
            geometrias[i,j]=pts;geometrias[j,i]=list(reversed(pts))
            seg=LineString(pts)
            if union is not None and not union.is_empty:
                expon[i,j]=expon[j,i]=float(seg.intersection(union).length)
            raw=0;eligible=0
            for centro,rad in zip(centros,radios):
                if rad <= 0 or seg.length <= 1e-12:
                    continue
                # Una tangencia aislada no implica recorrer un tramo interior.
                if centro.distance(seg) >= rad-1e-7:
                    continue
                raw+=1
                # gamma_i, gamma_j = 1 si el cliente está dentro de la zona.
                if centro.distance(Point(pts[0])) <= rad+1e-7 or centro.distance(Point(pts[1])) <= rad+1e-7:
                    continue
                eligible+=1
            cuenta[i,j]=cuenta[j,i]=raw
            elegible[i,j]=elegible[j,i]=eligible
    costo=dist*(1+float(penalizacion)*elegible)
    return Matrices(distancia=dist,exposicion=expon,costo=costo,
       geometrias=geometrias,coords=coords,modo='Artículo · Haversine y secantes',
       avisos=['Distancias geodésicas Haversine entre clientes; los trazos rectos NO son rutas transitables.',
              'Costo multiplicativo por arco, con exención para extremos de arco dentro de la zona.',
              'Los círculos se aproximan a partir de empalmes; no equivalen automáticamente a la geometría o resultados del artículo publicado.'],
       cruces=cuenta,arcos_penalizados=elegible,
       descripcion_objetivo='Artículo: suma_ij d_ij*[1+lambda*sum_k(delta_ijk*(1-max(gamma_i,gamma_j)))]',
       lambda_aplicada=float(penalizacion))


def matriz_vial_experimental(coords:np.ndarray, geob:bytes, to_m:Transformer,
                  circulos:list[dict], penalizacion:float=0.0,max_snap_m:float=250.) -> Matrices:
    """Red vial con recálculo de rutas mínimas según exposición real por tramo.

    El costo de cada segmento vial es su longitud + lambda*longitud dentro de la
    unión de zonas. λ se aplica a tramos de calle, NO como multiplicador por cada
    arco cliente-cliente y NO incorpora exención de extremos del artículo.
    """
    riesgo=unary_union([z['geometry'] for z in circulos]) if circulos else None
    m=matriz_vial(coords,geob,to_m,riesgo,penalizacion,max_snap_m)
    m.modo='QGIS · red vial con exposición por tramo'
    m.descripcion_objetivo='Red: penalización aditiva por tramo, suma longitud + lambda*longitud dentro de unión de círculos'
    m.avisos.append('Extensión metodológica: función aditiva de exposición a calles, NO formulación multiplicativa de arcos del artículo.')
    m.lambda_aplicada=float(penalizacion)
    m.cruces=(m.exposicion>1e-7).astype(int)
    m.arcos_penalizados=(m.exposicion>1e-7).astype(int)
    return m


def cantidad_cruces(rutas:list[list[int]],matrices:Matrices)->tuple[int,int]:
    """Cuenta cruces de zona y penalizaciones por arcos recorridos.

    En el modo del artículo es suma de interacciones arco-círculo (no solo arcos
    distintos). En red vial se cuenta una interacción por par cliente-cliente
    con exposición, sin segmentar múltiples círculos.
    """
    if matrices.cruces is None:
        return 0,0
    total=0;pen=0
    for rt in rutas:
        seq=[0]+rt+[0]
        for a,b in zip(seq,seq[1:]):
            total+=int(matrices.cruces[a,b])
            pen+=int(matrices.arcos_penalizados[a,b]) if matrices.arcos_penalizados is not None else 0
    return total,pen if matrices.lambda_aplicada>0 else 0
