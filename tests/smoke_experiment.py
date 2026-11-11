"""Prueba manual no ejecutada automáticamente: caso realista de 25 y 150 clientes simulados."""
from pathlib import Path
from time import perf_counter
import pandas as pd
from src.analysis import leer_excel,proyeccion,k_sugerido,ajustar_por_riesgo,superposiciones
from src.cvrp import crear_nodos,leer_clientes,resolver
from src.cvrp_experimentos import crear_circulos_empalmes,matriz_articulo,matriz_vial_experimental,cantidad_cruces

BASE=Path(__file__).parents[1]
p=BASE/'data/riesgos_ejemplo_irapuato.xlsx'
d,_=leer_excel(p.read_bytes())
d,epsg,to_m,to_geo=proyeccion(d)
ks={k:k_sugerido(g[['x_m','y_m']].to_numpy())[0] for k,g in d.groupby('tipo_riesgo')}
print('K',ks,flush=True)
_,zones,hulls=ajustar_por_riesgo(d,ks)
over=superposiciones(hulls,100)
cs=crear_circulos_empalmes(over)
print('zonas',len(zones),'empalmes',len(over),'circulos',len(cs),flush=True)
for mode in ('A','B'):
  clfile=BASE/'data/clientes_ejemplo_irapuato.csv'
  cli=leer_clientes(clfile.read_bytes(),clfile.name)
  coords=crear_nodos(cli,20.6838673,-101.3526233,to_m)
  t=perf_counter()
  if mode=='A':
    models=[matriz_articulo(coords,to_geo,cs,l) for l in (0,3)]
  else:
    roads=(BASE/'data/red_vial_ARTIFICIAL_pruebas.geojson').read_bytes()
    models=[matriz_vial_experimental(coords,roads,to_m,cs,l,250) for l in (0,3)]
  print(mode,'matrices',round(perf_counter()-t,2),'s',flush=True)
  for idx,mat in enumerate(models):
    for method in ('Búsqueda local','Búsqueda tabú','Colonia de hormigas (ACO)'):
      sol=resolver(mat,cli,5,25,method,42,40)
      print(mode,idx,method,'dist',round(sol.distancia_m/1000,2),'exposure',round(sol.exposicion_m/1000,2),'cruces',cantidad_cruces(sol.rutas,mat),'time',round(sol.segundos,2),flush=True)
# 150 clients compatible in A, one local run no large cloud assumptions
f=BASE/'data/clientes_150_simulados_irapuato.xlsx'
cli=leer_clientes(f.read_bytes(),f.name)
coords=crear_nodos(cli,20.6838673,-101.3526233,to_m)
t=perf_counter();model=matriz_articulo(coords,to_geo,cs,1)
print('150: matriz',round(perf_counter()-t,2),'s',flush=True)
sol=resolver(model,cli,5,80,'Búsqueda local',42,40)
print('150: sol',sol.distancia_m/1000,'s',sol.segundos,flush=True)
