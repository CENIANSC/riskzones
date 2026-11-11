"""CVRP heurístico: construcción + 2-opt, búsqueda tabú y colonia de hormigas.

Entradas geográficas: lat/lon WGS84, geometrías proyectadas UTM (metros).
La alternativa Euclidiana es SOLO referencia geométrica; red de calle real
requiere GeoJSON vial. Nada aquí demuestra un óptimo global.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from time import perf_counter
import hashlib
import json
import math
import random
import unicodedata
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform, unary_union

MAX_CLIENTES = 70
MAX_VIALIDADES_VERTICES = 12000

class CVRPError(ValueError):
    pass


def _normalizar(s: str) -> str:
    t=unicodedata.normalize('NFKD',str(s).strip().lower())
    return ''.join(x for x in t if not unicodedata.combining(x)).replace(' ','_')


def leer_clientes(contenido: bytes, nombre: str = 'clientes.csv') -> pd.DataFrame:
    """Primera hoja xlsx o CSV, ID, latitud, longitud, demanda."""
    try:
        if nombre.lower().endswith('.xlsx'):
            df=pd.read_excel(BytesIO(contenido), sheet_name=0)
        elif nombre.lower().endswith('.csv'):
            df=pd.read_csv(BytesIO(contenido), encoding='utf-8-sig')
        else:
            raise CVRPError('Se requiere archivo .xlsx o .csv de clientes.')
    except CVRPError:
        raise
    except Exception as exc:
        raise CVRPError(f'No se pudo leer el archivo de clientes: {exc}') from exc
    df.columns=[_normalizar(c) for c in df.columns]
    if 'cliente' not in df and 'id' in df:
        df=df.rename(columns={'id':'cliente'})
    missing={'cliente','latitud','longitud','demanda'}-set(df.columns)
    if missing:
        raise CVRPError('Faltan columnas: '+', '.join(sorted(missing)))
    df=df[['cliente','latitud','longitud','demanda']].copy()
    if not 1<=len(df)<=MAX_CLIENTES:
        raise CVRPError(f'Se aceptan entre 1 y {MAX_CLIENTES} clientes por ejecución.')
    df['cliente']=df['cliente'].astype(str).str.strip()
    for k in ['latitud','longitud','demanda']:
        df[k]=pd.to_numeric(df[k],errors='coerce')
    valid=(df['latitud'].between(-90,90) & df['longitud'].between(-180,180)
           & np.isfinite(df['latitud']) & np.isfinite(df['longitud'])
           & np.isfinite(df['demanda']) & (df['demanda']>0)
           & df['cliente'].ne('') & df['cliente'].ne('nan'))
    if not bool(valid.all()):
        raise CVRPError('Hay coordenadas, demandas o identificadores no válidos en clientes (demandas deben ser >0).')
    if df['cliente'].duplicated().any():
        raise CVRPError('Los ID de clientes deben ser únicos.')
    return df.reset_index(drop=True)


def validar_capacidad(clientes: pd.DataFrame, vehiculos: int, capacidad: float):
    if vehiculos < 1 or capacidad<=0:
        raise CVRPError('Se requiere al menos un vehículo y capacidad positiva.')
    if float(clientes.demanda.max()) > capacidad+1e-7:
        raise CVRPError('Al menos un cliente demanda más que la capacidad de un vehículo.')
    if float(clientes.demanda.sum()) > vehiculos*capacidad+1e-7:
        raise CVRPError('La demanda total supera la capacidad total disponible.')


def unir_zonas_riesgo(zonas: list[dict], empalmes: list[dict], alcance: str):
    if alcance=='Sin penalización':
        return None
    if alcance=='Solo empalmes multirriesgo':
        shapes=[e['geometry'] for e in empalmes]
    elif alcance=='Todas las zonas de riesgo':
        shapes=[z['geometry'] for z in zonas]
    else:
        raise CVRPError('Alcance del riesgo no reconocido.')
    return unary_union(shapes) if shapes else None


def _exposicion(line: LineString, riesgo) -> float:
    return float(line.intersection(riesgo).length) if riesgo is not None and not riesgo.is_empty else 0.0


@dataclass
class Matrices:
    # Matrices [depósito, clientes...], coordenadas UTM [x,y]
    distancia: np.ndarray
    exposicion: np.ndarray
    costo: np.ndarray
    geometrias: dict[tuple[int,int], list[tuple[float,float]]]
    coords: np.ndarray
    modo: str
    avisos: list[str]
    red_vertices: int = 0
    red_aristas: int = 0


def crear_nodos(clientes: pd.DataFrame, deposito_lat: float, deposito_lon: float,
                 to_m: Transformer) -> np.ndarray:
    if not (-90<=deposito_lat<=90 and -180<=deposito_lon<=180):
        raise CVRPError('El depósito no tiene coordenadas válidas.')
    lon=np.array([deposito_lon]+clientes.longitud.tolist(),dtype=float)
    lat=np.array([deposito_lat]+clientes.latitud.tolist(),dtype=float)
    xx, yy=to_m.transform(lon,lat)
    return np.column_stack([xx,yy])


def matriz_geometrica(coords: np.ndarray, riesgo=None, penalizacion:float=0.0) -> Matrices:
    """Segmentos rectos, NO distancias ni detours de calles reales."""
    if penalizacion<0:
        raise CVRPError('La penalización no puede ser negativa.')
    n=len(coords)
    dist=np.linalg.norm(coords[:,None,:]-coords[None,:,:],axis=2)
    exp=np.zeros((n,n),dtype=float)
    lineas={}
    for i in range(n):
        for j in range(i+1,n):
            pts=[tuple(map(float,coords[i])),tuple(map(float,coords[j]))]
            lineas[i,j]=pts
            lineas[j,i]=list(reversed(pts))
            exp[i,j]=exp[j,i]=_exposicion(LineString(pts),riesgo)
    return Matrices(dist,exp,dist+penalizacion*exp,lineas,coords,'Geometría recta',
                    ['Las líneas rectas no representan calles ni desvíos reales. No interpretar este modo como ruteo vial.'])


def _extract_roads(geo: dict) -> list[tuple[LineString,dict]]:
    if geo.get('type')=='FeatureCollection':
        features=geo.get('features',[])
    elif geo.get('type')=='Feature':
        features=[geo]
    else:
        features=[{'geometry':geo,'properties':{}}]
    outs=[]
    for f in features:
        if not f.get('geometry'):
            continue
        geom=shape(f['geometry'])
        parts=list(geom.geoms) if geom.geom_type=='MultiLineString' else [geom]
        for p in parts:
            if p.geom_type=='LineString' and len(p.coords)>=2:
                outs.append((p,f.get('properties') or {}))
    return outs


def construir_grafo_vial(contenido:bytes, to_m:Transformer, riesgo=None, penalizacion=0.0) -> nx.DiGraph:
    """Lee segmentos viales WGS84; nodos en vértices, unión por coordenadas a 0.1m.

    Es indispensable exportar la red CON NODOS EN INTERSECCIONES. No se
    infieren cruces geométricos que carezcan de vértice común.
    """
    if len(contenido)>22_000_000:
        raise CVRPError('GeoJSON vial demasiado grande (>22 MB). Recorta el área en QGIS.')
    try:
        parts=_extract_roads(json.loads(contenido.decode('utf-8-sig')))
    except Exception as exc:
        raise CVRPError(f'GeoJSON de vialidades no válido: {exc}') from exc
    if not parts:
        raise CVRPError('El archivo vial no contiene LineString/MultiLineString.')
    g=nx.DiGraph()
    for road,attrs in parts:
        coords=list(road.coords)
        xm,ym=to_m.transform([v[0] for v in coords],[v[1] for v in coords])
        vals=list(zip(xm,ym))
        oneway_value=str(attrs.get('oneway','')).strip().lower()
        oneway=oneway_value in ('true','1','yes','si','sí')
        reverse_only=oneway_value in ('-1','reverse')
        for p,q in zip(vals[:-1],vals[1:]):
            u=(round(float(p[0]),1),round(float(p[1]),1))
            v=(round(float(q[0]),1),round(float(q[1]),1))
            if u==v:
                continue
            seg=LineString([u,v]);d=float(seg.length)
            exposure=_exposicion(seg,riesgo)
            for a,b in ([(v,u)] if reverse_only else ([(u,v)] if oneway else [(u,v),(v,u)])):
                cost=d+penalizacion*exposure
                if not g.has_edge(a,b) or g[a][b]['cost']>cost:
                    g.add_edge(a,b,dist=d,exp=exposure,cost=cost)
            if g.number_of_nodes()>MAX_VIALIDADES_VERTICES:
                raise CVRPError('Red muy grande para Streamlit gratuito (>12 000 vértices). Recorta el área o simplifica la capa.')
    if g.number_of_nodes()<2:
        raise CVRPError('No se generó ninguna arista vial utilizable.')
    return g


def matriz_vial(coords:np.ndarray, geob:bytes, to_m:Transformer,
                riesgo=None,penalizacion:float=0.0,max_snap_m:float=250.) -> Matrices:
    if penalizacion<0:
        raise CVRPError('La penalización no puede ser negativa.')
    g=construir_grafo_vial(geob,to_m,riesgo,penalizacion)
    nodos=list(g.nodes())
    arr=np.array(nodos,dtype=float)
    tree=cKDTree(arr)
    gaps, inds=tree.query(coords)
    if np.max(gaps)>max_snap_m:
        raise CVRPError(f'Uno o más puntos están demasiado lejos de la red (> {max_snap_m:.0f} m). Distancia máxima: {max(gaps):.1f} m. Amplía o corrige la capa.')
    anchors=[nodos[int(i)] for i in inds]
    n=len(coords)
    dist=np.zeros((n,n),dtype=float)
    exp=np.zeros((n,n),dtype=float)
    lineas={}
    # connector from each original point to nearest actual road vertex.
    conn_dist=np.asarray(gaps,dtype=float)
    conn_exp=np.array([_exposicion(LineString([tuple(coords[i]),anchors[i]]),riesgo)
                       if conn_dist[i]>0.001 else 0. for i in range(n)])
    for i, source in enumerate(anchors):
        lengths, routes=nx.single_source_dijkstra(g,source,weight='cost')
        for j,target in enumerate(anchors):
            if i==j:
                continue
            path=routes.get(target)
            if path is None:
                raise CVRPError('La red vial está desconectada o tiene sentidos únicos que impiden algunas visitas. Revisa su topología en QGIS.')
            dd=sum(g[u][v]['dist'] for u,v in zip(path,path[1:]))
            ee=sum(g[u][v]['exp'] for u,v in zip(path,path[1:]))
            dist[i,j]=float(dd+conn_dist[i]+conn_dist[j])
            exp[i,j]=float(ee+conn_exp[i]+conn_exp[j])
            seq=[tuple(map(float,coords[i]))]
            seq.extend([tuple(map(float,x)) for x in path])
            seq.append(tuple(map(float,coords[j])))
            lineas[i,j]=seq
    return Matrices(dist,exp,dist+penalizacion*exp,lineas,coords,'Red vial GeoJSON',
                    ['Distancia de calles según conectividad del GeoJSON, no tráfico real.',
                     'La precisión depende de intersecciones conectadas, sentidos y cercanía de clientes a nodos.'],
                    g.number_of_nodes(),g.number_of_edges())


def _route_cost(rt:list[int],cost:np.ndarray)->float:
    seq=[0]+rt+[0]
    return float(sum(cost[a,b] for a,b in zip(seq,seq[1:])))


def _cost_routes(routes:list[list[int]],cost:np.ndarray)->float:
    return sum(_route_cost(r,cost) for r in routes)


def _loads(routes:list[list[int]], demands:np.ndarray)->list[float]:
    return [sum(float(demands[x]) for x in r) for r in routes]


def _pack(demands:np.ndarray,k:int,cap:float,limit:int=150000)->list[list[int]]:
    """FFD y backtracking acotado; asignación factible previa a ordenar rutas."""
    order=sorted(range(1,len(demands)),key=lambda i:-demands[i])
    bins=[[] for _ in range(k)]
    rem=[cap]*k
    failed=set()
    work=0
    def dfs(t:int)->bool:
        nonlocal work
        work+=1
        if work>limit:
            return False
        if t==len(order):
            return True
        j=order[t]
        unique=set()
        for v in range(k):
            r=round(rem[v],6)
            if r in unique or r+1e-7<demands[j]:
                continue
            unique.add(r)
            rem[v]-=float(demands[j]);bins[v].append(j)
            if dfs(t+1):
                return True
            bins[v].pop();rem[v]+=float(demands[j])
        return False
    if dfs(0):
        return bins
    raise CVRPError('No se encontró una asignación factible bajo el límite de búsqueda: aumenta vehículos/capacidad o revisa las demandas. La capacidad total por sí sola no garantiza factibilidad.')


def _cheapest_order(ids:list[int],cost:np.ndarray)->list[int]:
    route=[]
    for j in sorted(ids, key=lambda x: min(cost[0,x],cost[x,0])):
        best_index=min(range(len(route)+1),
                       key=lambda p: _route_cost(route[:p]+[j]+route[p:],cost))
        route.insert(best_index,j)
    return route


def _2opt(rt:list[int],cost:np.ndarray)->list[int]:
    if len(rt)<3:
        return rt[:]
    out=rt[:]
    for _ in range(4):
        best_delta=0.; best=None
        base=_route_cost(out,cost)
        for i in range(len(out)-1):
            for j in range(i+1,len(out)):
                cand=out[:i]+out[i:j+1][::-1]+out[j+1:]
                delta=_route_cost(cand,cost)-base
                if delta<best_delta-1e-7:
                    best_delta=delta;best=cand
        if best is None:
            break
        out=best
    return out


def _moves(routes:list[list[int]],demands:np.ndarray,cap:float,rng:random.Random,
           budget:int=150):
    """Relocate y swap entre/intra rutas (candidatos factibles)."""
    k=len(routes)
    positions=[(v,p,n) for v,r in enumerate(routes) for p,n in enumerate(r)]
    if not positions:
        return
    loads=_loads(routes,demands)
    for _ in range(budget):
        v,p,node=rng.choice(positions)
        w=rng.randrange(k)
        if rng.random()<.5:
            newpos=rng.randint(0,len(routes[w]))
            if v==w and (newpos==p or newpos==p+1):
                continue
            if v!=w and loads[w]+demands[node]>cap+1e-7:
                continue
            rr=[r[:] for r in routes]
            rr[v].pop(p)
            if v==w and newpos>p:
                newpos-=1
            rr[w].insert(newpos,node)
            yield rr, ('move',node)
        else:
            if not routes[w]:
                continue
            q=rng.randrange(len(routes[w]))
            if v==w and p==q:
                continue
            other=routes[w][q]
            if v!=w and (loads[v]-demands[node]+demands[other]>cap+1e-7 or
                         loads[w]-demands[other]+demands[node]>cap+1e-7):
                continue
            rr=[r[:] for r in routes]
            rr[v][p],rr[w][q]=rr[w][q],rr[v][p]
            yield rr,('swap',*sorted((node,other)))


def _local_search(routes:list[list[int]],demands:np.ndarray,cap:float,cost:np.ndarray,
                  seed:int=42,passes:int=6,budget:int=250)->list[list[int]]:
    rng=random.Random(seed)
    out=[_2opt(r,cost) for r in routes]
    best=_cost_routes(out,cost)
    for _ in range(passes):
        changed=False
        for candidate,_ in _moves(out,demands,cap,rng,budget):
            v=_cost_routes(candidate,cost)
            if v<best-1e-6:
                out=[_2opt(r,cost) for r in candidate]
                best=_cost_routes(out,cost)
                changed=True
                break
        if not changed:
            break
    return out


def _tabu(initial:list[list[int]],demands:np.ndarray,cap:float,cost:np.ndarray,
          seed:int=42,iterations:int=140,candidates:int=110)->list[list[int]]:
    rng=random.Random(seed+7)
    current=[r[:] for r in initial]
    best=[r[:] for r in current]
    bestval=_cost_routes(best,cost)
    tabu={}
    stale=0
    for step in range(iterations):
        candidates_iter=_moves(current,demands,cap,rng,candidates)
        choice=None;val=math.inf;key_chosen=None
        for cand,key in candidates_iter:
            v=_cost_routes(cand,cost)
            if tabu.get(key,-1)>step and v>=bestval-1e-7:
                continue
            if v<val:
                val=v;choice=cand;key_chosen=key
        if choice is None:
            break
        current=choice
        tabu[key_chosen]=step+max(5,int(math.sqrt(len(demands))))
        if val<bestval-1e-6:
            best=[r[:] for r in current];bestval=val;stale=0
        else:
            stale+=1
        if stale>45:
            current=[r[:] for r in best]
            stale=0
    return _local_search(best,demands,cap,cost,seed+23,passes=4,budget=250)


def _aco(demands:np.ndarray,k:int,cap:float,cost:np.ndarray,seed:int=42,
         iterations:int=28,ants:int=15)->list[list[int]]:
    """ACO simplificado (cluster-first route construction) con factibilidad estricta.
    La selección probabilística puede generar particiones inviables: se descartan.
    """
    rng=np.random.default_rng(seed)
    n=len(demands)
    cost=np.asarray(cost,dtype=float)
    positive=cost[cost>1e-5]
    scale=max(float(np.median(positive)) if len(positive) else 1,1.)
    desirability=1/(1+(cost/scale))**2
    tau=np.ones((n,n),dtype=float)
    best=None;bestval=math.inf
    for it in range(iterations):
        deposits=[]
        for _ in range(ants):
            remaining=set(range(1,n))
            rr=[[] for _ in range(k)]
            feasible=True
            for v in range(k):
                rem=cap;prev=0
                while remaining:
                    allowed=[j for j in sorted(remaining) if demands[j]<=rem+1e-7]
                    if not allowed:
                        break
                    # Occasionally stop a route to leave capacity for later routes.
                    if rr[v] and v<k-1 and rng.random()<.13:
                        break
                    weights=np.array([tau[prev,j]**1.15 * desirability[prev,j]**2 for j in allowed])
                    if not np.isfinite(weights.sum()) or weights.sum()<=0:
                        j=int(rng.choice(allowed))
                    else:
                        j=int(rng.choice(allowed,p=weights/weights.sum()))
                    rr[v].append(j);rem-=demands[j];remaining.remove(j);prev=j
                if not remaining:
                    break
            if remaining:
                feasible=False
            if not feasible:
                continue
            rr=[_2opt(r,cost) for r in rr]
            val=_cost_routes(rr,cost)
            deposits.append((rr,val))
            if val<bestval:
                bestval=val;best=[r[:] for r in rr]
        tau*=.82
        tau=np.maximum(tau,.03)
        if deposits:
            top=sorted(deposits,key=lambda t:t[1])[:4]
            for routes,val in top:
                increment=(scale/max(val,scale))*len(demands)
                for route in routes:
                    seq=[0]+route+[0]
                    for i,j in zip(seq,seq[1:]):
                        tau[i,j]+=increment
        if best:
            for rt in best:
                seq=[0]+rt+[0]
                for i,j in zip(seq,seq[1:]):
                    tau[i,j]+=0.2
    return best if best is not None else []


@dataclass
class Solucion:
    algoritmo: str
    rutas: list[list[int]]
    distancia_m: float
    exposicion_m: float
    costo_m: float
    cargas: list[float]
    segundos: float
    seed: int


def evaluar(rutas:list[list[int]], matrices:Matrices,demands:np.ndarray,
            cap:float,vehiculos:int, nombre:str, segundos:float,seed:int)->Solucion:
    nodes=[x for route in rutas for x in route]
    if sorted(nodes)!=list(range(1,len(demands))):
        raise CVRPError('La solución omitió o repitió clientes.')
    if len(rutas)!=vehiculos:
        raise CVRPError('La solución tiene una cantidad incorrecta de vehículos.')
    cargas=_loads(rutas,demands)
    if any(v>cap+1e-7 for v in cargas):
        raise CVRPError('La solución viola la capacidad vehicular.')
    return Solucion(nombre,rutas,_cost_routes(rutas,matrices.distancia),
                    _cost_routes(rutas,matrices.exposicion),_cost_routes(rutas,matrices.costo),
                    cargas,segundos,seed)


def resolver(matrices:Matrices, clientes:pd.DataFrame,vehiculos:int,cap:float,
             tecnica:str,seed:int=42,iterations:int=140)->Solucion:
    validar_capacidad(clientes,vehiculos,cap)
    demands=np.r_[0.,clientes.demanda.to_numpy(float)]
    if len(demands)!=len(matrices.costo):
        raise CVRPError('Las matrices no coinciden con los clientes.')
    started=perf_counter()
    assigned=_pack(demands,vehiculos,cap)
    inicial=[_cheapest_order(b,matrices.costo) for b in assigned]
    inicial=_local_search(inicial,demands,cap,matrices.costo,seed,passes=5,budget=200)
    if tecnica=='Búsqueda local':
        result=inicial
    elif tecnica=='Búsqueda tabú':
        result=_tabu(inicial,demands,cap,matrices.costo,seed,iterations=iterations)
    elif tecnica=='Colonia de hormigas (ACO)':
        ant=_aco(demands,vehiculos,cap,matrices.costo,seed,
                 iterations=max(6,iterations//5),ants=12)
        if ant:
            ant=_local_search(ant,demands,cap,matrices.costo,seed+17,passes=5,budget=230)
        result=ant if ant and _cost_routes(ant,matrices.costo)<_cost_routes(inicial,matrices.costo) else inicial
    else:
        raise CVRPError('Técnica no reconocida.')
    return evaluar(result,matrices,demands,cap,vehiculos,tecnica,perf_counter()-started,seed)


def tabla_rutas(sol:Solucion,clientes:pd.DataFrame)->pd.DataFrame:
    result=[]
    for v,route in enumerate(sol.rutas,1):
        result.append({'vehiculo':v,'clientes':len(route),'carga':round(sol.cargas[v-1],3),
                       'secuencia':'Depósito → '+' → '.join(clientes.iloc[i-1].cliente for i in route)+' → Depósito'})
    return pd.DataFrame(result)


def hash_archivo(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()
