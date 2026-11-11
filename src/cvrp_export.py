"""Exportación de experimentos CVRP A/B y comparación λ=0/λ>0."""
from __future__ import annotations
from io import BytesIO
import json
import zipfile
from datetime import datetime, timezone
from importlib.metadata import version, PackageNotFoundError
import platform

import pandas as pd
from shapely.geometry import LineString, mapping
from shapely.ops import transform


def _versions() -> dict:
    ver={'python':platform.python_version()}
    for pkg in ('streamlit','pandas','numpy','shapely','scikit-learn',
                'networkx','pyproj','folium','scipy','openpyxl'):
        try:
            ver[pkg]=version(pkg)
        except PackageNotFoundError:
            ver[pkg]='no instalado en entorno de exportación'
    return ver


def zip_cvrp(sols:dict, matrices_por_metodo:dict,clientes,to_geo,params:dict,
             hash_clientes:str,hash_riesgos:str,hash_vialidades:str|None=None,
             *, metadata:dict|None=None,circulos:list[dict]|None=None)->bytes:
    metadata=metadata or {}
    zbuf=BytesIO()
    with zipfile.ZipFile(zbuf,'w',zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        resumen=[];detail=[];features=[]
        for label,sol in sols.items():
            m=matrices_por_metodo[label]
            info=metadata.get(label,{})
            resumen.append({'etiqueta':label,'tecnica':info.get('tecnica',sol.algoritmo),
                'escenario':info.get('escenario'), 'lambda':info.get('lambda_optimizada'),
                'distancia_km':round(sol.distancia_m/1000,5),
                'exposicion_km':round(sol.exposicion_m/1000,5),
                'costo_objetivo_km_equivalentes':round(sol.costo_m/1000,5),
                'cruces_geom':info.get('cruces_geometricos'),
                'interacciones_penalizadas':info.get('interacciones_penalizadas'),
                'vehiculos_utilizados':sum(bool(r) for r in sol.rutas),
                'segundos_solucion':round(sol.segundos,5),'modelo':m.modo})
            for v,route in enumerate(sol.rutas,1):
                seq=[0]+route+[0]
                detail.append({'etiqueta':label,'tecnica':info.get('tecnica',sol.algoritmo),
                    'escenario':info.get('escenario'),'vehiculo':v,
                    'carga':round(sol.cargas[v-1],5),
                    'secuencia':' | '.join(['DEPOSITO']+
                       [str(clientes.iloc[i-1].cliente) for i in route]+['DEPOSITO'])})
                coords=[]
                for a,b in zip(seq,seq[1:]):
                    pts=m.geometrias.get((a,b),[])
                    if pts:
                        coords.extend(pts if not coords else pts[1:])
                if len(coords)>=2:
                    geom=transform(to_geo.transform,LineString(coords))
                    features.append({'type':'Feature','properties':{
                        'etiqueta':label,'tecnica':info.get('tecnica',sol.algoritmo),
                        'escenario':info.get('escenario'),
                        'vehiculo':v,'carga':round(sol.cargas[v-1],3)},
                        'geometry':mapping(geom)})
        def csvfile(p, rows):
            z.writestr(p,pd.DataFrame(rows).to_csv(index=False).encode('utf-8-sig'))
        csvfile('comparacion_heuristicas.csv',resumen)
        csvfile('secuencias_por_vehiculo.csv',detail)
        csvfile('clientes.csv',clientes.to_dict('records'))
        # Matrices origen-destino para auditar cada función objetivo y los arcos
        # seleccionados, sin duplicarlas por técnica (las tres usan la misma matriz
        # dentro del mismo escenario de riesgo).
        matrices_unicas={}
        for label,m in matrices_por_metodo.items():
            scenario=metadata.get(label,{}).get('escenario') or label
            if scenario not in matrices_unicas:
                matrices_unicas[scenario]=m
        for scenario,mat in matrices_unicas.items():
            rows=[]
            for i in range(len(mat.costo)):
                for j in range(len(mat.costo)):
                    if i==j:
                        continue
                    rows.append({'origen':'DEPOSITO' if i==0 else str(clientes.iloc[i-1].cliente),
                        'destino':'DEPOSITO' if j==0 else str(clientes.iloc[j-1].cliente),
                        'distancia_m':round(float(mat.distancia[i,j]),4),
                        'exposicion_m':round(float(mat.exposicion[i,j]),4),
                        'costo_objetivo_m':round(float(mat.costo[i,j]),4),
                        'cruces_geom':int(mat.cruces[i,j]) if mat.cruces is not None else None,
                        'interacciones_elegibles':int(mat.arcos_penalizados[i,j]) if mat.arcos_penalizados is not None else None})
            slug='sin_penalizacion' if scenario=='Sin penalización' else 'con_penalizacion'
            csvfile('matriz_OD_'+slug+'.csv',rows)
        z.writestr('rutas_escenarios.geojson',json.dumps({'type':'FeatureCollection',
            'features':features},ensure_ascii=False).encode('utf-8'))
        circ_features=[]
        for c in (circulos or []):
            circ_features.append({'type':'Feature','properties':{
               k:v for k,v in c.items() if k!='geometry'},
               'geometry':mapping(transform(to_geo.transform,c['geometry']))})
        z.writestr('circulos_empalmes_o_zonas.geojson',json.dumps({
            'type':'FeatureCollection','features':circ_features},ensure_ascii=False).encode('utf-8'))
        z.writestr('manifiesto_cvrp.json',json.dumps({
            'fecha_utc':datetime.now(timezone.utc).isoformat(),
            'version_app':'1.3.0','versiones_entorno':_versions(),
            'modo_experimento':params.get('mode'),
            'formulaciones':{
              'A':'c_ij = Haversine_ij * (1 + lambda * SUM secantes_elegibles_ijk); exencion por cliente dentro del circulo',
              'B':'Costo de tramos viales = longitud_tramo + lambda * longitud_del_tramo_dentro_de_union_de_circulos; Dijkstra y luego CVRP heuristico'},
            'modelos':{name:mat.modo for name,mat in matrices_por_metodo.items()},
            'avisos':{name:mat.avisos for name,mat in matrices_por_metodo.items()},
            'metodos':list(sols),'detalles_escenario':metadata,
            'parametros':params,'sha256_clientes':hash_clientes,
            'sha256_riesgos':hash_riesgos,'sha256_vialidades':hash_vialidades,
            'sistema_geojson':'EPSG:4326, lon/lat',
            'limitaciones':['No se garantiza óptimo global',
              'Sin datos originales no se reproducen los resultados del artículo',
              'Los datos de demostración son simulados',
              'Modo B requiere una red de calles topológicamente conectada',
              'Cruces del artículo: interacciones arco-círculo, no por tramo de calle',
              'El modelo A usa Haversine como distancia geodésica y no como longitud vial'],
        },ensure_ascii=False,indent=2,default=str).encode('utf-8'))
        z.writestr('LEEME.txt',('Archivo de resultados de Riesgos Urbanos CVRP v1.3. '
         'Los trazos del modo A NO son calles. El modo B representa rutas calculadas en una red '
         'QGIS que debe estar topológicamente conectada y tener sentidos de circulación correctos. '
         'La longitud de exposición no equivale a probabilidad de incidente. '
         'Los costos de los modelos A y B NO son directamente comparables como si fueran '
         'la misma formulación.').encode('utf-8'))
    return zbuf.getvalue()
