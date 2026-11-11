"""Interfaz CVRP integrada en la misma aplicación de análisis de riesgos."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

from src.cvrp import (CVRPError,leer_clientes,validar_capacidad,crear_nodos,
     unir_zonas_riesgo,matriz_geometrica,matriz_vial,resolver,hash_archivo)
from src.cvrp_export import zip_cvrp
from src.cvrp_viz import mapa_cvrp

TECHS=['Búsqueda local','Búsqueda tabú','Colonia de hormigas (ACO)']
DEMO=Path(__file__).resolve().parent.parent/'data'/'clientes_ejemplo_irapuato.csv'


def bloque_cvrp(*,zonas,empalmes,to_m,to_geo,epsg,risk_bytes:bytes,config_k:dict):
    st.header('CVRP · Minimización de distancia y exposición al riesgo')
    st.markdown('**Elige hasta tres heurísticas** para el problema de ruteo capacitado. '
        'El objetivo es minimizar distancia + λ × metros de recorrido dentro de las zonas seleccionadas, '
        'respetando las demandas y capacidades vehiculares. **No se garantiza óptimo global.**')
    with st.expander('📚 Cómo interpretar los métodos',expanded=False):
        st.markdown('''
- **Búsqueda local:** construcción por inserción barata, 2-opt y movimientos de clientes entre vehículos; rápida y reproducible.
- **Búsqueda tabú:** parte de una solución factible, explora movimientos 1-a-1 y evita repetir movimientos recientes durante algunas iteraciones.
- **Colonia de hormigas (ACO):** construye rutas probabilísticamente con feromonas y costo de los arcos; refuerza las soluciones de menor costo y mejora localmente. Una hormiga que no satisface todas las demandas se descarta.

El resultado más corto no tiene por qué ser el de menor exposición. La **solución de referencia** siempre minimiza distancia sin penalización para mostrar el compromiso entre objetivos. La distancia de referencia y la distancia penalizada se calculan sobre el mismo tipo de red.
''')
    with st.expander('📄 Formato de clientes y ejemplo simulado'):
        st.dataframe(pd.DataFrame({'cliente':['C01','C02'],'latitud':[20.6820,20.6910],
                                   'longitud':[-101.3532,-101.3621],'demanda':[2,3]}),hide_index=True)
        st.download_button('Descargar clientes de demostración (25 puntos)', DEMO.read_bytes(),
          file_name='clientes_ejemplo_irapuato.csv',mime='text/csv')
        st.caption('El archivo de riesgos es distinto del de clientes: riesgos en Excel (latitud, longitud, tipo_riesgo); clientes en CSV o Excel (cliente, latitud, longitud, demanda).')
    file=st.file_uploader('Archivo de clientes (.csv o .xlsx)',type=['csv','xlsx'],key='cvrp_clients')
    if file:
        client_bytes=file.getvalue();client_name=file.name
    else:
        client_bytes=DEMO.read_bytes();client_name='clientes_ejemplo_irapuato.csv'
        st.caption('Se utiliza el escenario de clientes simulado que acompaña al repositorio.')
    try:
        clientes=leer_clientes(client_bytes,client_name)
    except CVRPError as exc:
        st.error(str(exc));return

    cc1,cc2,cc3,cc4=st.columns(4)
    with cc1:
        lat0=st.number_input('Depósito · latitud',value=20.6838673,format='%.7f',key='dep_lat')
    with cc2:
        lon0=st.number_input('Depósito · longitud',value=-101.3526233,format='%.7f',key='dep_lon')
    with cc3:
        vehiculos=st.number_input('Vehículos',min_value=1,max_value=35,value=5,step=1,key='fleet')
    with cc4:
        cap=st.number_input('Capacidad por vehículo (unidades)',min_value=.1,max_value=1e7,value=25.,step=1.,key='cap')
    try:
        validar_capacidad(clientes,int(vehiculos),float(cap))
    except CVRPError as exc:
        st.error(str(exc));return
    st.caption(f"Clientes: **{len(clientes)}** · Demanda total: **{clientes.demanda.sum():g}** · Capacidad total: **{vehiculos*cap:g}**")

    col1,col2=st.columns(2)
    with col1:
        risk_scope=st.selectbox('Áreas para evaluar exposición',
            ['Solo empalmes multirriesgo','Todas las zonas de riesgo','Sin penalización'],key='risk_scope')
        lam=st.slider('Penalización λ por metro expuesto',0.0,20.0,5.0,.5,key='lam',
            help='Coste generalizado = metros recorridos + λ × metros de tramos dentro de los polígonos. No es una probabilidad de incidente.')
        techs=st.multiselect('Algoritmos a comparar',TECHS,default=TECHS,key='selected_techs')
    with col2:
        mode=st.radio('Distancias y trazado de rutas',
            ['Distancia geométrica (demostración)','Red vial GeoJSON (QGIS)'],key='roadmode',
            help='Distancia geométrica traza segmentos rectos; para rutas sobre calles, sube una red vial correctamente conectada.')
        roadfile=None
        max_snap=250.
        if mode.startswith('Red vial'):
            roadfile=st.file_uploader('Red vial LineString/MultiLineString en EPSG:4326',
                  type=['geojson','json'],key='roads_upload')
            max_snap=st.number_input('Distancia máxima para conectar clientes a nodos de vialidad (m)',
                                       min_value=10.,max_value=1000.,value=250.,step=10.)
            st.caption('Preparación en QGIS: recortar calles de Irapuato, segmentar y **conectar intersecciones**; exportar GeoJSON WGS84. Los sentidos únicos se toman de la propiedad `oneway` si existe.')
        else:
            st.warning('En modo geométrico, el mapa de calles es solo fondo: los trazos rectos **no son rutas circulables** ni evitan físicamente la zona mediante desvíos de calles.')
    par1,par2=st.columns(2)
    with par1:
        iterations=st.slider('Intensidad de búsqueda (iteraciones)',30,400,140,10,key='iterations')
    with par2:
        seed=st.number_input('Semilla aleatoria',min_value=0,max_value=999999,value=42,step=1,key='seed')
    if not techs:
        st.warning('Selecciona al menos una técnica.');return
    if mode.startswith('Red vial') and not roadfile:
        st.info('Para resolver rutas por calles, carga una red vial GeoJSON exportada de QGIS.');return

    roadbytes=roadfile.getvalue() if roadfile else None
    if risk_scope=='Solo empalmes multirriesgo' and not empalmes and lam>0:
        st.warning('No hay empalmes: con este alcance la penalización será cero. Cambia a «Todas las zonas de riesgo» para evaluar exposición.')
    geometries_hash=hashlib.sha256(b''.join(z['geometry'].wkb for z in zonas)+
                                  b''.join(e['geometry'].wkb for e in empalmes)).hexdigest()
    keyvals={'geometry_sha':geometries_hash,'risk_sha':hash_archivo(risk_bytes),'clientes_sha':hash_archivo(client_bytes),
       'roads_sha':hash_archivo(roadbytes) if roadbytes else None,
       'k':config_k,'n_zonas':len(zonas),'n_empalmes':len(empalmes),'epsg':epsg,
       'deposito':[lat0,lon0],'fleet':vehiculos,'cap':cap,'scope':risk_scope,
       'lam':lam,'techs':techs,'mode':mode,'snap':max_snap,'iter':iterations,'seed':seed}
    sig=hashlib.sha256(json.dumps(keyvals,sort_keys=True,default=str).encode()).hexdigest()
    if st.button('🚚 Resolver y comparar rutas CVRP',type='primary',key='solve_cvrp'):
        try:
            with st.spinner('Calculando matrices y soluciones heurísticas...'):
                riesgo=unir_zonas_riesgo(zonas,empalmes,risk_scope)
                xy=crear_nodos(clientes,float(lat0),float(lon0),to_m)
                if roadbytes:
                    model=matriz_vial(xy,roadbytes,to_m,riesgo,float(lam),float(max_snap))
                    base=matriz_vial(xy,roadbytes,to_m,riesgo,0.,float(max_snap))
                else:
                    model=matriz_geometrica(xy,riesgo,float(lam))
                    base=matriz_geometrica(xy,riesgo,0.)
                ref=resolver(base,clientes,int(vehiculos),float(cap),'Búsqueda local',int(seed),int(iterations))
                solutions={'Referencia sin penalización':ref}
                matrices={'Referencia sin penalización':base}
                for tech in techs:
                    solutions[tech]=resolver(model,clientes,int(vehiculos),float(cap),tech,int(seed),int(iterations))
                    matrices[tech]=model
                zipbytes=zip_cvrp(solutions,matrices,clientes,to_geo,keyvals,
                       hash_archivo(client_bytes),hash_archivo(risk_bytes),
                       hash_archivo(roadbytes) if roadbytes else None)
                st.session_state['cvrp_results']={'fingerprint':sig,'solutions':solutions,
                    'matrices':matrices,'clientes':clientes,'zip':zipbytes,
                    'model':model,'base':base}
        except (CVRPError,ValueError,RuntimeError) as exc:
            st.error(f'No se pudo resolver el CVRP: {exc}')
            st.session_state.pop('cvrp_results',None)
            return
    res=st.session_state.get('cvrp_results')
    if not res or res['fingerprint']!=sig:
        st.caption('Ajusta parámetros y presiona «Resolver y comparar rutas CVRP».')
        return
    st.subheader('Comparación de resultados')
    rows=[]
    baseline=res['solutions']['Referencia sin penalización']
    for name,sol in res['solutions'].items():
        rows.append({'Técnica':name,'Distancia (km)':round(sol.distancia_m/1000,3),
                     'Exposición (km)':round(sol.exposicion_m/1000,3),
                     'Costo generalizado (km eq.)':round((sol.distancia_m+lam*sol.exposicion_m)/1000,3),
                     'Variación distancia vs. ref. (%)':round((sol.distancia_m/baseline.distancia_m-1)*100,2) if baseline.distancia_m else 0.,
                     'Variación exposición vs. ref. (%)':round((sol.exposicion_m/baseline.exposicion_m-1)*100,2) if baseline.exposicion_m else None,
                     'Vehículos usados':sum(bool(x) for x in sol.rutas),'Tiempo solución (s)':round(sol.segundos,2)})
    st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
    st.caption('La exposición se mide por longitud recorrida dentro de las zonas geométricas, NO por frecuencia o probabilidad real de incidentes. El costo generalizado permite comparar soluciones con λ común.')
    selected=st.selectbox('Visualizar solución',list(res['solutions']),key='chosen_cvrp')
    sol=res['solutions'][selected]
    st.caption('Ruta por calles' if roadbytes else 'Ruta geométrica de demostración: segmentos rectos sobre mapa de calles.')
    m=mapa_cvrp(sol,res['matrices'][selected],clientes,to_geo,zonas=zonas,empalmes=empalmes)
    components.html(m.get_root().render(),height=630,scrolling=False)
    from src.cvrp import tabla_rutas
    st.dataframe(tabla_rutas(sol,clientes),hide_index=True,use_container_width=True)
    st.download_button('⬇️ Descargar rutas GeoJSON, comparativo, clientes y manifiesto (ZIP)',
            data=res['zip'],file_name='resultados_cvrp_riesgo.zip',mime='application/zip',key='download_cvrp')
    st.info('Interpretación: si λ=0 el modelo prioriza distancia. Con λ>0 prioriza distancia generalizada; la exposición puede caer a costa de mayor recorrido. Las tres técnicas son heurísticas, no certifican distancia mínima global.')
