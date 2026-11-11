"""Exportación de resultados CVRP, matriz y trazabilidad."""
from __future__ import annotations
from io import BytesIO
import json
import zipfile
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from shapely.geometry import LineString, mapping
from shapely.ops import transform
from src.cvrp import tabla_rutas


def zip_cvrp(sols:dict, matrices_por_metodo:dict,clientes,to_geo,params:dict,hash_clientes:str,
             hash_riesgos:str,hash_vialidades:str|None=None)->bytes:
    zbuf=BytesIO()
    with zipfile.ZipFile(zbuf,'w',zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        resumen=[]
        detail=[]
        features=[]
        for name,sol in sols.items():
            matrices=matrices_por_metodo[name]
            resumen.append({'algoritmo':name,'distancia_km':round(sol.distancia_m/1000,4),
                'exposicion_km':round(sol.exposicion_m/1000,4),'costo_generalizado_km':round(sol.costo_m/1000,4),
                'vehiculos_utilizados':sum(bool(x) for x in sol.rutas),'segundos':round(sol.segundos,4)})
            for v,route in enumerate(sol.rutas,1):
                seq=[0]+route+[0]
                detail.append({'algoritmo':name,'vehiculo':v,'carga':sol.cargas[v-1],
                               'secuencia':' | '.join(['DEPOSITO']+[str(clientes.iloc[i-1].cliente) for i in route]+['DEPOSITO'])})
                coords=[]
                for a,b in zip(seq,seq[1:]):
                    pts=matrices.geometrias.get((a,b),[])
                    coords.extend(pts if not coords else pts[1:])
                if len(coords)>=2:
                    geom=transform(to_geo.transform,LineString(coords))
                    features.append({'type':'Feature','properties':{'algoritmo':name,'vehiculo':v,
                                        'carga':round(sol.cargas[v-1],3)},'geometry':mapping(geom)})
        def csvfile(p, rows):
            z.writestr(p,pd.DataFrame(rows).to_csv(index=False).encode('utf-8-sig'))
        csvfile('comparativo_algoritmos.csv',resumen)
        csvfile('rutas_clientes.csv',detail)
        csvfile('clientes.csv',clientes.to_dict('records'))
        z.writestr('rutas.geojson',json.dumps({'type':'FeatureCollection','features':features},ensure_ascii=False).encode())
        z.writestr('manifiesto_cvrp.json',json.dumps({
            'fecha_utc':datetime.now(timezone.utc).isoformat(),
            'modelo':'CVRP; distancia + lambda * longitud expuesta a polígonos',
            'modelo_vial':{n:m.modo for n,m in matrices_por_metodo.items()},
            'avisos':{n:m.avisos for n,m in matrices_por_metodo.items()},
            'metodos':list(sols), 'semilla':params.get('seed'), 'parametros':params,
            'sha256_clientes':hash_clientes, 'sha256_riesgos':hash_riesgos,
            'sha256_vialidades':hash_vialidades,
            'unidades':'m; coste en metros equivalentes',
            'reproducibilidad':'Heurísticas sin garantía de optimalidad global; datos de ejemplo simulados si se usan ejemplos.'},
            ensure_ascii=False,indent=2,default=str).encode())
        z.writestr('LEEME.txt',('GeoJSON en EPSG:4326. Descarga QGIS para inspección. '
         'Si se utilizó geometría recta, la línea NO es una ruta transitable; '
         'si se utilizó red GeoJSON se usaron caminos mínimos ponderados por riesgo. '
         'Los resultados son heurísticos y no prueban óptimo global.').encode('utf-8'))
    return zbuf.getvalue()
