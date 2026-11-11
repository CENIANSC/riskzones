"""Riesgos Urbanos · aplicación Streamlit para datos georreferenciados.

NO es un modelo predictivo de siniestros/delitos ni un solucionador CVRP.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.analysis import (
    DatosError, ajustar_por_riesgo, filtrar_area, k_sugerido, leer_excel,
    leer_limite_geojson, proyeccion, superposiciones, tabla_geometria,
    APP_VERSION,
)
from src.exportacion import crear_paquete
from src.visualizacion import mapa

st.set_page_config(page_title="Riesgos Urbanos · K-Means", page_icon="🗺️", layout="wide")
st.title("Riesgos urbanos | Análisis espacial multirriesgo")
st.caption(f"Versión {APP_VERSION} · K-Means por tipo de riesgo · exportación QGIS/GeoJSON · enfoque exploratorio")
st.info("Las zonas representan agrupamientos geométricos, NO probabilidades ni niveles comprobados de peligro. "
        "Los puntos del ejemplo son simulados; sustituye el archivo para investigar datos reales.")

PATH_EJEMPLO = Path(__file__).resolve().parent / "data" / "riesgos_ejemplo_irapuato.xlsx"
base_bytes = PATH_EJEMPLO.read_bytes()

with st.expander("📄 Formato del Excel y archivo de ejemplo", expanded=False):
    st.write("Se lee **la primera hoja** y los encabezados deben llamarse exactamente "
             "`latitud`, `longitud`, `tipo_riesgo` (sin importar mayúsculas ni acentos). "
             "Puedes agregar nuevos riesgos escribiendo otro nombre en la columna C.")
    st.dataframe(pd.DataFrame([
        {"latitud": 20.692563, "longitud": -101.330562, "tipo_riesgo": "Accidentes"},
        {"latitud": 20.682141, "longitud": -101.360585, "tipo_riesgo": "Inseguridad"},
        {"latitud": 20.691210, "longitud": -101.365100, "tipo_riesgo": "Inundaciones"},
    ]), hide_index=True, use_container_width=True)
    st.download_button("Descargar ejemplo de Irapuato (150 puntos simulados)",
                       data=base_bytes, file_name="riesgos_ejemplo_irapuato.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

file = st.file_uploader("Carga un Excel con todos los riesgos", type=["xlsx"],
                        help="Una hoja con columnas: latitud, longitud, tipo_riesgo")
contenido = file.getvalue() if file is not None else base_bytes
if file is None:
    st.caption("Modo demostración: se utiliza el Excel incluido en el repositorio (100 accidentes + 50 incidentes de inseguridad simulados).")
else:
    st.success(f"Archivo cargado: {file.name} — SHA-256: {hashlib.sha256(contenido).hexdigest()[:16]}…")

try:
    original, calidad = leer_excel(contenido)
except DatosError as exc:
    st.error(str(exc))
    st.stop()

st.sidebar.header("Configuración geográfica")
modo = st.sidebar.selectbox("Área de estudio", ["Sin filtro", "Radio urbano", "Límite municipal (GeoJSON)"], index=0)
kwargs = {}
limite = None
if modo == "Radio urbano":
    st.sidebar.caption("El círculo NO representa el límite oficial del municipio.")
    kwargs["centro_lat"] = st.sidebar.number_input("Centro · latitud", value=20.6838673, format="%.7f")
    kwargs["centro_lon"] = st.sidebar.number_input("Centro · longitud", value=-101.3526233, format="%.7f")
    kwargs["radio_km"] = st.sidebar.slider("Radio de análisis (km)", 1.0, 40.0, 6.0, step=0.5)
elif modo == "Límite municipal (GeoJSON)":
    lim_file = st.sidebar.file_uploader("Polígono GeoJSON municipal (WGS84)", type=["geojson", "json"])
    if lim_file:
        try:
            limite = leer_limite_geojson(lim_file.getvalue())
        except DatosError as exc:
            st.sidebar.error(str(exc))
            st.stop()
    else:
        st.sidebar.warning("Sube un polígono municipal oficial; no viene incluido para evitar límites inventados.")
        st.stop()
    kwargs["limite_geojson"] = limite

try:
    filtrados, fuera = filtrar_area(original, modo, **kwargs)
    puntos_m, epsg, to_m, to_geo = proyeccion(filtrados)
except DatosError as exc:
    st.error(str(exc))
    st.stop()

n_invalid = calidad["registros_invalidos"]
if n_invalid:
    st.warning(f"Se descartaron {n_invalid} filas por datos inválidos o riesgo vacío. "
               f"Filas de Excel: {calidad['filas_invalidas']}")
if fuera:
    st.warning(f"Se excluyeron {fuera} puntos por el filtro territorial seleccionado.")
if calidad["coordenadas_repetidas"]:
    st.caption(f"Hay {calidad['coordenadas_repetidas']} coordenadas repetidas por tipo; "
               "se conservan porque pueden corresponder a incidentes distintos.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Registros analizados", f"{len(puntos_m):,}")
c2.metric("Tipos de riesgo", puntos_m.tipo_riesgo.nunique())
c3.metric("Filas fuera del área", fuera)
c4.metric("CRS para distancias", f"EPSG:{epsg}")

st.sidebar.divider()
st.sidebar.header("Parámetros del modelo")
radio_min = st.sidebar.slider("Radio mínimo para zonas (m)", 20, 500, 80, 10,
                              help="Asegura un polígono incluso si un clúster tiene un solo punto. "
                                   "NO representa riesgo clínico, policial ni probabilidad.")
buffer_hull = st.sidebar.slider("Buffer de envolvente convexa (m)", 5, 100, 20, 5)
min_puntos = st.sidebar.number_input("Mínimo de incidentes por zona retenida", min_value=1, max_value=100, value=1,
                                     help="Las zonas con menos incidentes se reportan, pero no se utilizan en los empalmes.")
area_minima = st.sidebar.number_input("Área mínima de empalme (m²)", min_value=0, max_value=100000,
                                      value=100, step=100)

config_k = {}
siluetas = {}
with st.sidebar.expander("K-Means por cada tipo de riesgo", expanded=True):
    st.caption("El K inicial se sugiere mediante silueta, cuando es calculable. "
               "Puedes modificarlo manualmente para análisis de sensibilidad.")
    for riesgo, grupo in puntos_m.groupby("tipo_riesgo", sort=True):
        xy = grupo[["x_m", "y_m"]].to_numpy()
        n_unicos = len(pd.DataFrame(xy).drop_duplicates())
        k_auto, scores = k_sugerido(xy)
        siluetas[riesgo] = scores
        max_k = min(25, n_unicos)
        config_k[riesgo] = st.slider(f"{riesgo} · K (n={len(grupo)}, únicos={n_unicos})",
                                    min_value=1, max_value=max_k, value=min(k_auto, max_k),
                                    step=1, key=f"k_{riesgo}")
        if scores:
            st.caption(f"K sugerido: {k_auto}; silueta = {scores[k_auto]:.3f} (criterio geométrico).")
        else:
            st.caption("Pocos puntos distintos; K=1 sugerido.")

try:
    clasificados, zonas_todas, envolventes_todas = ajustar_por_riesgo(
        puntos_m, config_k, radio_minimo_m=float(radio_min), buffer_hull_m=float(buffer_hull))
    selected_ids = {z["id_zona"] for z in zonas_todas if z["n_incidentes"] >= int(min_puntos)}
    zonas = [z for z in zonas_todas if z["id_zona"] in selected_ids]
    envolventes = [e for e in envolventes_todas if e["id_zona"] in selected_ids]
    empalmes = superposiciones(zonas, area_minima_m2=float(area_minima))
except (DatosError, ValueError) as exc:
    st.error(f"No fue posible completar el análisis: {exc}")
    st.stop()

st.subheader("Resultados")
m1, m2, m3 = st.columns(3)
m1.metric("Zonas obtenidas", len(zonas_todas))
m2.metric("Zonas retenidas", len(zonas))
m3.metric("Empalmes de 2+ riesgos", len(empalmes))
if len(zonas) < len(zonas_todas):
    st.warning(f"Se omitieron {len(zonas_todas)-len(zonas)} zonas de los empalmes por el mínimo de incidentes; "
               "los puntos originales se conservan en el mapa y en la exportación.")

st.caption("Los empalmes representan regiones de coincidencia geométrica. "
           "La operación elimina dobles conteos y distingue coincidencias de 2, 3 o más tipos.")
map_tab, data_tab, meth_tab = st.tabs(["🗺️ Mapa interactivo", "📊 Tablas", "🔬 Metodología"]) 
with map_tab:
    vis_puntos = st.checkbox("Mostrar puntos", True)
    vis_hulls = st.checkbox("Incluir envolventes convexas", False)
    vis_overlap = st.checkbox("Destacar coincidencias multirriesgo", True)
    if len(puntos_m) > 3000:
        st.info("Para mantener fluido el mapa se visualiza una muestra reproducible de 3 000 puntos. "
                "La exportación incluye todos los registros.")
    m, _ = mapa(puntos=clasificados, zonas=zonas, envolventes=envolventes,
                empalmes=empalmes, to_geo=to_geo, mostrar_puntos=vis_puntos,
                mostrar_hulls=vis_hulls, mostrar_empalmes=vis_overlap, limite_original=limite)
    components.html(m.get_root().render(), height=630, scrolling=False)
    st.caption("El mapa base requiere conexión a Internet; las coordenadas, tablas y GeoJSON funcionan sin él.")
with data_tab:
    vc = puntos_m.tipo_riesgo.value_counts().rename_axis("tipo_riesgo").reset_index(name="incidentes")
    st.bar_chart(vc, x="tipo_riesgo", y="incidentes", use_container_width=True)
    st.markdown("**Zonas y radios proyectados**")
    tabla_zonas = tabla_geometria(zonas_todas, to_geo)
    tabla_zonas["retenida"] = tabla_zonas["id_zona"].isin(selected_ids)
    st.dataframe(tabla_zonas, hide_index=True, use_container_width=True)
    st.markdown("**Empalmes entre tipos distintos**")
    tabla_empalmes = tabla_geometria(empalmes, to_geo)
    if empalmes:
        st.dataframe(tabla_empalmes, hide_index=True, use_container_width=True)
    else:
        st.info("No se encontraron superficies compartidas que superen el umbral de área configurado.")
with meth_tab:
    st.markdown("""
**Procedimiento reproducible**

1. Leer un Excel con tres columnas: `latitud`, `longitud`, `tipo_riesgo`. Validar y conservar la fila de origen.
2. Filtrar por área de estudio elegida (opcional). Un radio urbano **no equivale** a un municipio.
3. Transformar las coordenadas WGS84 a UTM local para operar con metros.
4. Agrupar **cada riesgo por separado** con K-Means (semilla aleatoria 42). Sugerir `K` con el índice de silueta si hay suficientes puntos y permitir ajuste manual.
5. Calcular para cada grupo un centroide y la máxima distancia de sus incidentes al centroide; el radio circular es el máximo entre esa distancia y el radio mínimo establecido. Generar adicionalmente una envolvente convexa con buffer.
6. Conservar zonas de cada tipo por separado; disolver zonas del mismo tipo y efectuar superposiciones entre **tipos distintos**. Las regiones resultantes son disjuntas y permiten evaluar coincidencias de dos o más categorías sin contarlas dos veces.
7. Exportar CSV, GeoJSON en WGS84 y manifiesto metodológico con SHA-256, filtros, parámetros, software y proyección.

**Limitaciones:** K-Means no demuestra *hotspots* estadísticamente significativos, y la densidad de registros no equivale a tasa de riesgo sin exposición vial, subregistro, temporalidad y validación. Las zonas no representan barreras físicas. La optimización CVRP no está incluida en esta versión.
""")
    st.json({"modo_area": modo, "epsg_calculos": epsg, "K_por_riesgo": config_k,
             "radio_minimo_m": radio_min, "umbral_eventos": int(min_puntos),
             "area_minima_empalme_m2": int(area_minima)})

st.divider()
conf_export = {
    "modo_area": modo,
    "centro_y_radio": {k: v for k, v in kwargs.items() if k != "limite_geojson"},
    "limite_geojson_proporcionado": bool(limite is not None),
    "k_por_riesgo": config_k,
    "siluetas": siluetas,
    "radio_minimo_m": radio_min,
    "buffer_envolvente_m": buffer_hull,
    "min_incidentes_zona": int(min_puntos),
    "area_minima_empalmes_m2": int(area_minima),
    "dataset_ejemplo_simulado": file is None,
}
calidad = {**calidad, "fuera_area": fuera}
paquete = crear_paquete(
    df_original=original, clasificados=clasificados, zonas=zonas, envolventes=envolventes,
    empalmes=empalmes, to_geo=to_geo, epsg=epsg, contenido_entrada=contenido,
    config=conf_export, calidad=calidad,
)
st.download_button("⬇️ Descargar resultados para QGIS y manifiesto (ZIP)",
                   data=paquete, file_name="resultados_riesgos_urbanos_qgis.zip",
                   mime="application/zip", type="primary")
st.caption("Los archivos que subes se procesan en memoria durante la sesión. "
           "No publiques datos sensibles o identificables en una aplicación pública.")
