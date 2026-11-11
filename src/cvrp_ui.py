"""Interfaz de comparación de 3 heurísticas × 2 escenarios, en dos modalidades CVRP."""
from __future__ import annotations

from pathlib import Path
from time import perf_counter
import hashlib
import json
import math

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.cvrp import (CVRPError, leer_clientes, validar_capacidad, crear_nodos,
                      resolver, hash_archivo, tabla_rutas)
from src.cvrp_experimentos import (crear_circulos_empalmes, matriz_articulo,
    matriz_vial_experimental, cantidad_cruces)
from src.cvrp_export import zip_cvrp
from src.cvrp_viz import mapa_cvrp

TECNICAS = ['Búsqueda local', 'Búsqueda tabú', 'Colonia de hormigas (ACO)']
ROOT=Path(__file__).resolve().parents[1]
DEMO25=ROOT/'data'/'clientes_ejemplo_irapuato.csv'
DEMO150=ROOT/'data'/'clientes_150_simulados_irapuato.xlsx'
DEMO_ROADS=ROOT/'data'/'red_vial_ARTIFICIAL_pruebas.geojson'
MODO_A='A · Reproducción metodológica (Haversine + secantes)'
MODO_B='B · Extensión vial con QGIS (rutas por calles)'


def _sha_geometria(rows):
    sha=hashlib.sha256()
    for row in rows:
        sha.update(row['geometry'].wkb)
    return sha.hexdigest()


def bloque_cvrp(*, zonas, empalmes, to_m, to_geo, epsg, risk_bytes:bytes, config_k:dict, forma_empalmes:str=""):
    st.header('CVRP experimental · dos modos y tres heurísticas')
    st.markdown('Compara **Búsqueda local, Búsqueda tabú y Colonia de hormigas (ACO)** '
        'con **λ = 0** y **λ mayor que cero** usando los mismos clientes, capacidades y semilla. '
        'Todos los métodos son heurísticos; **no prueban óptimo global**.')

    with st.expander('📘 Diferencia entre los modos A y B',expanded=True):
        st.markdown(r'''
**Modo A · reproducción metodológica:** toma cada empalme de dos o más riesgos, construye
su círculo envolvente, calcula distancias Haversine entre depósito y clientes y comprueba
qué arcos rectos son secantes de los círculos. Para cada arco, el costo es:

$$ c_{ij}=d_{ij}\left[1+\lambda\sum_k\delta_{ij}^{k}(1-\max(\gamma_i^k,\gamma_j^k))\right]. $$

Los extremos situados dentro de la zona no activan penalización en ese arco;
siempre se atiende a los clientes. **No representa la distancia por calles.**

**Modo B · extensión por QGIS:** importa calles conectadas y minimiza caminos
ponderados por tramo: $\sum_e (d_e+\lambda\,\ell_{e\cap R})$.
La penalización es **aditiva por longitud de calle expuesta**, diferente de
la formulación multiplicativa por arco del artículo. La red debe tener
intersecciones conectadas y debe estar en EPSG:4326.

**Interpretación de métricas:** distancia física, exposición, costo de optimización y cruces
son indicadores distintos. En A, *exposición* es informativa y NO se usa para
penalizar; en B, sí determina la penalización. No equiparar ambos costos
ni considerar las rutas rectas como transitables.
''')

    with st.expander('Archivos de ejemplo y formatos',expanded=False):
        st.dataframe(pd.DataFrame({'cliente':['C001','C002'], 'latitud':[20.68,20.691],
           'longitud':[-101.35,-101.36], 'demanda':[2,3]}),hide_index=True)
        c1,c2=st.columns(2)
        with c1:
            st.download_button('Descargar 25 clientes (CSV)',DEMO25.read_bytes(),
                file_name='clientes_25_demo.csv',mime='text/csv',key='demo25')
        with c2:
            st.download_button('Descargar 150 clientes (Excel)',DEMO150.read_bytes(),
                file_name='clientes_150_demo.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key='demo150')
        st.caption('Los registros de ejemplo son completamente simulados; no se encuentran necesariamente sobre calles.')

    file=st.file_uploader('Clientes: CSV o Excel con cliente, latitud, longitud, demanda',
        type=['csv','xlsx'],key='cvrp_clients')
    if file is not None:
        data=file.getvalue(); name=file.name
    else:
        data=DEMO25.read_bytes(); name=DEMO25.name
        st.caption('Se está usando el ejemplo simulado de 25 clientes.')
    try:
        clientes=leer_clientes(data,name)
    except CVRPError as e:
        st.error(str(e));return
    c1,c2,c3,c4=st.columns(4)
    with c1:
        dep_lat=st.number_input('Depósito · latitud',value=20.6838673,format='%.7f',key='exp_dep_lat')
    with c2:
        dep_lon=st.number_input('Depósito · longitud',value=-101.3526233,format='%.7f',key='exp_dep_lon')
    with c3:
        vehiculos=int(st.number_input('Vehículos',min_value=1,max_value=35,value=5,step=1,key='exp_fleet'))
    with c4:
        sugerida=float(max(25, math.ceil(clientes.demanda.sum()/5*1.25)))
        cap=float(st.number_input('Capacidad por vehículo',min_value=1.,max_value=1e7,
                                  value=sugerida,step=1.,key='exp_cap'))
    st.caption(f'Clientes: **{len(clientes)}** · Demanda total: **{clientes.demanda.sum():g}** · '
               f'Capacidad disponible: **{vehiculos*cap:g}**. Puedes cargar hasta 150 clientes.')
    try:
        validar_capacidad(clientes,vehiculos,cap)
    except CVRPError as exc:
        st.warning(f'Ajusta vehículos/capacidad antes de resolver: {exc}');return

    modo=st.radio('Modalidad experimental', [MODO_A,MODO_B], horizontal=False,key='exp_mode')
    circulos=crear_circulos_empalmes(empalmes)
    roadfile=None; roadbytes=None
    alcance='Círculos derivados de empalmes multirriesgo'
    max_snap=250.
    if modo==MODO_B:
        alcance=st.radio('Polígonos de riesgo sobre calles',
          ['Círculos derivados de empalmes multirriesgo',
           'Círculos individuales K-Means (EXTENSIÓN, no artículo)'],
          key='exp_risk_area')
        if alcance.startswith('Círculos individuales'):
            circulos=[{**z,'riesgos':z.get('tipo_riesgo','')} for z in zonas]
        roadfile=st.file_uploader('Sube GeoJSON de vialidades conectado (QGIS · WGS84)',
             type=['geojson','json'],key='exp_roads')
        max_snap=float(st.number_input('Distancia máxima de conexión de clientes (metros)',
             min_value=10.,max_value=1500.,value=250.,step=10.,key='exp_snap'))
        st.caption('La capa debe incluir calles LINESTRING con intersecciones cortadas y conectadas. '
                   'Respeta `oneway` si la propiedad está presente. No se descargan calles automáticamente.')
        st.download_button('Descargar red vial ARTIFICIAL para comprobar el modo B (NO es Irapuato real)',
             DEMO_ROADS.read_bytes(), file_name='red_vial_ARTIFICIAL_pruebas.geojson',
             mime='application/geo+json',key='demo_roads')
        roadbytes=roadfile.getvalue() if roadfile is not None else None
        if roadbytes is None:
            st.info('Para el modo B sube un GeoJSON vial de QGIS. Puedes usar también la red artificial incluida en el repositorio para pruebas.')
    else:
        st.info('Modo A: solo se penalizan **círculos derivados de empalmes**. Los segmentos son rectos y la distancia es Haversine.')

    if not circulos:
        st.warning('No se identificaron empalmes/zonas en el alcance elegido. '
                   'Se obtendrán rutas CVRP con λ=0 efectivamente, aunque modifiques λ.')

    c1,c2=st.columns(2)
    with c1:
        lam=float(st.slider('λ · Intensidad de penalización',min_value=0.0,max_value=20.0,
                         value=1.0,step=0.5,key='exp_lambda'))
        if lam==0:
            st.warning('λ=0 hace idénticos ambos escenarios de costo. Usa λ>0 para comparar.')
        tecnicas=st.multiselect('Métodos para ambas condiciones',TECNICAS,
                                default=TECNICAS,key='exp_techs')
    with c2:
        iterations=int(st.slider('Iteraciones heurísticas',min_value=20,max_value=400,
                                value=100,step=10,key='exp_iters'))
        seed=int(st.number_input('Semilla reproducible',min_value=0,max_value=999999,
                                value=42,step=1,key='exp_seed'))
    if not tecnicas:
        st.warning('Selecciona al menos un método.');return
    if modo==MODO_B and roadbytes is None:
        return
    if len(clientes)>75:
        st.warning('Con más de 75 clientes, sobre todo en modo vial y al comparar 6 escenarios, '
                   'el cálculo puede exigir varios recursos en Streamlit Cloud. Prueba primero con 25 clientes.')

    geometry_hash=_sha_geometria(circulos)
    signature_dict={'geometry':geometry_hash,'risk_sha':hash_archivo(risk_bytes),
       'clients_sha':hash_archivo(data),'road_sha':hash_archivo(roadbytes) if roadbytes else None,
       'mode':modo,'scope':alcance,'forma_empalmes':forma_empalmes,'k':config_k,'epsg':epsg,'depot':[dep_lat,dep_lon],
       'vehicles':vehiculos,'capacity':cap,'lambda':lam,'techniques':tecnicas,
       'iterations':iterations,'seed':seed,'snap_m':max_snap}
    signature=hashlib.sha256(json.dumps(signature_dict,sort_keys=True,default=str).encode()).hexdigest()

    if st.button('🚚 Ejecutar ambos escenarios con los métodos seleccionados',
                 type='primary',key='exp_solve'):
        try:
            with st.spinner('Creando matrices y resolviendo ambos escenarios…'):
                xy=crear_nodos(clientes,float(dep_lat),float(dep_lon),to_m)
                began=perf_counter()
                if modo==MODO_A:
                    base=matriz_articulo(xy,to_geo,circulos,0.)
                    penal=matriz_articulo(xy,to_geo,circulos,lam)
                else:
                    base=matriz_vial_experimental(xy,roadbytes,to_m,circulos,0.,max_snap)
                    penal=matriz_vial_experimental(xy,roadbytes,to_m,circulos,lam,max_snap)
                matrix_seconds=perf_counter()-began
                if modo==MODO_A and lam>0 and penal.arcos_penalizados is not None:
                    if int((penal.arcos_penalizados>0).sum())==0:
                        st.warning('La matriz no contiene arcos penalizables: quizá los clientes/depósito '
                            'están dentro de los círculos y aplica la excepción del artículo. '
                            'Revisa K, los empalmes y el radio de las zonas.')
                solutions={}; matrices={}; meta={}
                # Cada método aparece bajo ambas condiciones; nunca hay una única
                # técnica de referencia oculta. Todos comparten las mismas matrices.
                for condition,mat in [('Sin penalización',base),('Con penalización',penal)]:
                    for technique in tecnicas:
                        key=f'{technique} | {condition}'
                        sol=resolver(mat,clientes,vehiculos,cap,technique,seed,iterations)
                        solutions[key]=sol;matrices[key]=mat
                        cruces,penalizados=cantidad_cruces(sol.rutas,mat)
                        meta[key]={'tecnica':technique,'escenario':condition,
                            'lambda_optimizada':(0. if condition=='Sin penalización' else lam),
                            'cruces_geometricos':cruces,'interacciones_penalizadas':penalizados}
                export_params={**signature_dict, "tiempo_matrices_segundos":round(matrix_seconds,5)}
                zipbytes=zip_cvrp(solutions,matrices,clientes,to_geo,export_params,
                       hash_archivo(data),hash_archivo(risk_bytes),
                       hash_archivo(roadbytes) if roadbytes else None,
                       metadata=meta,circulos=circulos)
                st.session_state['cvrp_results_v13']={'fingerprint':signature,
                   'solutions':solutions,'matrices':matrices,'meta':meta,
                   'clients':clientes,'circulos':circulos,'zip':zipbytes,
                   'matrix_seconds':matrix_seconds}
        except (CVRPError,ValueError,RuntimeError,MemoryError) as exc:
            st.error(f'No se pudo completar el experimento: {exc}')
            st.session_state.pop('cvrp_results_v13',None)
            return
    res=st.session_state.get('cvrp_results_v13')
    if not res or res['fingerprint']!=signature:
        st.caption('Ajusta los parámetros y ejecuta el experimento para mostrar la comparación.')
        return

    st.subheader('Comparación de resultados · λ=0 frente a λ configurada')
    opts=res['solutions']
    baselines=[sol.distancia_m for key,sol in opts.items()
               if res['meta'][key]['escenario']=='Sin penalización']
    best_base=min(baselines) if baselines else None
    rows=[]
    for key,sol in opts.items():
        metadata=res['meta'][key]
        rows.append({'Heurística':metadata['tecnica'], 'Escenario':metadata['escenario'],
            'λ':metadata['lambda_optimizada'],
            'Distancia (km)':round(sol.distancia_m/1000,3),
            'Exposición (km)':round(sol.exposicion_m/1000,3),
            'Costo optimizado (unid. distancia)':round(sol.costo_m/1000,3),
            'Cruces/interacciones':metadata['cruces_geometricos'],
            'Interacciones penalizadas':metadata['interacciones_penalizadas'],
            'Desvío vs menor distancia λ=0 (%)':round(100*(sol.distancia_m/best_base-1),2) if best_base else None,
            'Vehículos usados':sum(bool(r) for r in sol.rutas),
            'Tiempo heurística (s)':round(sol.segundos,2)})
    table=pd.DataFrame(rows)
    st.dataframe(table,hide_index=True,use_container_width=True)
    st.caption(f'Tiempo total de construcción de las dos matrices: **{res["matrix_seconds"]:.2f} s** '
        '(separado del tiempo de cada heurística). Los costos de A y B tienen significados distintos. '
        'El número de cruces en A cuenta interacciones arco-círculo, no intersecciones viales.')

    selected=st.selectbox('Visualizar una de las soluciones calculadas',list(opts),key='exp_selected')
    sol=opts[selected]; mat=res['matrices'][selected];meta=res['meta'][selected]
    st.markdown(f'**Mostrando:** {meta["tecnica"]} · {meta["escenario"]} · '
        f'**λ = {meta["lambda_optimizada"]:g}** · {mat.modo}')
    m=mapa_cvrp(sol,mat,clientes,to_geo,zonas=zonas,empalmes=empalmes,
                circulos=res['circulos'])
    components.html(m.get_root().render(),height=630,scrolling=False)
    st.markdown('**Resultado por vehículo de la solución seleccionada**')
    st.dataframe(tabla_rutas(sol,clientes),hide_index=True,use_container_width=True)
    st.download_button('⬇️ Exportar seis escenarios, rutas, círculos y manifiesto (ZIP)',
        data=res['zip'],file_name='CVRP_dos_modos_experimento.zip',mime='application/zip',
        key='exp_export')
    st.info('Este proyecto implementa dos modelos distintos. Para reproducir los valores '
        'publicados (p. ej. 112.81 km) son indispensables las entradas originales de 97 clientes, '
        'las seis zonas exactas y las condiciones del solucionador del manuscrito. '
        'Los datos de demostración no pueden reproducirlos.')
