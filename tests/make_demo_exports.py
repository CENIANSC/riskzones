"""Genera opcionalmente ZIP DEMOSTRATIVOS de A y B usando datos y red artificiales."""
from pathlib import Path
from src.analysis import leer_excel,proyeccion,k_sugerido,ajustar_por_riesgo,superposiciones
from src.cvrp import leer_clientes,crear_nodos,resolver,hash_archivo
from src.cvrp_experimentos import crear_circulos_empalmes,matriz_articulo,matriz_vial_experimental,cantidad_cruces
from src.cvrp_export import zip_cvrp

ROOT=Path(__file__).parents[1]
risk=(ROOT/'data/riesgos_ejemplo_irapuato.xlsx').read_bytes()
raw,_=leer_excel(risk)
projected,epsg,to_m,to_geo=proyeccion(raw)
K={k:k_sugerido(g[['x_m','y_m']].to_numpy())[0] for k,g in projected.groupby('tipo_riesgo')}
_,zones,hulls=ajustar_por_riesgo(projected,K)
over=superposiciones(hulls,100)
circles=crear_circulos_empalmes(over)
file=ROOT/'data/clientes_ejemplo_irapuato.csv'
client_bytes=file.read_bytes()
clients=leer_clientes(client_bytes,file.name)
xy=crear_nodos(clients,20.6838673,-101.3526233,to_m)
techs=['Búsqueda local','Búsqueda tabú','Colonia de hormigas (ACO)']
for mode in ['A','B']:
  roadbytes=(ROOT/'data/red_vial_ARTIFICIAL_pruebas.geojson').read_bytes() if mode=='B' else None
  if mode=='A':
    base=matriz_articulo(xy,to_geo,circles,0.)
    penal=matriz_articulo(xy,to_geo,circles,3.)
  else:
    base=matriz_vial_experimental(xy,roadbytes,to_m,circles,0,250)
    penal=matriz_vial_experimental(xy,roadbytes,to_m,circles,3,250)
  sols={};matrices={}; metadata={}
  for condition,m in [('Sin penalización',base),('Con penalización',penal)]:
    for tech in techs:
      name=f'{tech} | {condition}'
      sol=resolver(m,clients,5,25,tech,42,40)
      sols[name]=sol;matrices[name]=m
      c,p=cantidad_cruces(sol.rutas,m)
      metadata[name]={'escenario':condition,'tecnica':tech,'lambda_optimizada':3 if condition=='Con penalización' else 0,
                      'cruces_geometricos':c,'interacciones_penalizadas':p}
  result=zip_cvrp(sols,matrices,clients,to_geo,
         {'mode':mode,'seed':42,'demo':True,'lambda':3,'model':'SINTETICO'},
         hash_archivo(client_bytes),hash_archivo(risk),hash_archivo(roadbytes) if roadbytes else None,
         metadata=metadata,circulos=circles)
  out=ROOT/'salidas_demo'/f'Demostracion_CVRP_Modo_{mode}_Datos_Simulados.zip'
  out.parent.mkdir(parents=True,exist_ok=True)
  out.write_bytes(result)
  print(mode,len(result),len(sols),out,flush=True)
