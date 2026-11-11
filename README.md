# Riesgos Urbanos + CVRP: dos modalidades experimentales (v1.3)

Aplicación **Streamlit** para identificar agrupamientos espaciales y zonas de conflicto a partir de **un único Excel** de incidentes, y comparar tres heurísticas de ruteo capacitado (**Búsqueda local**, **Búsqueda tabú**, **Colonia de hormigas — ACO**) en **dos escenarios de costo**, `λ=0` y `λ>0`. El usuario puede seleccionar **uno de dos modos científicos**, que **no tienen la misma función objetivo**.

**Advertencia:** es un prototipo de investigación. Los incidentes, clientes y calles del repositorio son **simulados**. K-Means no estima la probabilidad real de accidente o delincuencia. Las heurísticas no demuestran optimalidad global. La fidelidad al artículo es **metodológica**, no una reproducción numérica certificada de su experimento original.

## Instalación y publicación

Recomendado: Python 3.11–3.12.

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

En GitHub, sube los **archivos descomprimidos** de este proyecto, con `app.py` y `requirements.txt` en la raíz. Después usa [Streamlit Community Cloud](https://share.streamlit.io/) y selecciona `app.py` como archivo principal. El mapa base es **OpenStreetMap**, sin configurar una clave API; necesitas conexión a Internet para descargar sus teselas.

```text
app.py
requirements.txt
src/
  analysis.py             # limpieza, UTM, K-Means y empalmes
  cvrp.py                 # CVRP, soluciones iniciales, tres heurísticas, grafo vial
  cvrp_experimentos.py    # NUEVO: modelo A multiplicativo; modelo B de calle
  cvrp_ui.py              # NUEVO: selector A/B y 3 × 2 escenarios
  cvrp_export.py          # comparativos, rutas, círculos, manifiesto
  cvrp_viz.py             # mapa OSM de rutas y círculos
  visualizacion.py        # mapa de accidentes, riesgos y empalmes
  exportacion.py          # exportación de análisis espacial

data/
  riesgos_ejemplo_irapuato.xlsx            # 100 + 50 eventos ficticios
  clientes_ejemplo_irapuato.csv            # 25 clientes ficticios
  clientes_150_simulados_irapuato.xlsx     # 150 clientes ficticios
  red_vial_ARTIFICIAL_pruebas.geojson      # grafo de calles SINTÉTICO: no real

tests/
  test_analysis.py
  test_cvrp.py
  test_dos_modos.py
  test_mapa.py
  smoke_experiment.py                     # comprobación integrada opcional

docs/METODOLOGIA_CVRP.md
```

## Archivos de entrada

**Incidentes**: `.xlsx`, primera hoja; columnas `latitud`, `longitud`, `tipo_riesgo`. Puedes usar más de dos categorías sin modificar el código.

**Clientes**: `.csv` o `.xlsx`, primera hoja; columnas `cliente`, `latitud`, `longitud`, `demanda`. ID único, coordenadas WGS84 y demanda positiva. La capacidad y la demanda deben estar en la misma unidad. **Máximo de esta versión: 150 clientes**; 150 clientes con red grande y 6 experimentos pueden exigir más recursos que el plan gratuito de Streamlit.

**Calles del modo B**: `.geojson` con `LineString` o `MultiLineString`, WGS84 (EPSG:4326), caminos conectados mediante **vértices coincidentes**. Respeta sentidos `oneway` (`yes`, `true`, `1`, `-1`). No se conectan cruces de líneas que no tengan vértices comunes. Debes preparar el grafo en QGIS.

Se incluye una **red vial ortogonal artificial**, únicamente para comprobar que el programa calcula caminos y desvíos. **No representa las vialidades reales de Irapuato, no debe utilizarse para distribución real.**

## Transformación de riesgos (previa a ambos modelos)

1. Leer el Excel y controlar coordenadas y etiquetas; aplicar el área de estudio solicitada.
2. Convertir WGS84 a UTM (metros).
3. Aplicar K-Means por **tipo de riesgo** (K configurable, silueta sugerida).
4. Construir regiones irregulares de los clústeres mediante **envolventes convexas**; también se calculan los círculos de cada clúster para visualización.
5. **Por defecto, calcular los empalmes entre envolventes convexas de tipos distintos**, sin doble conteo: esto sigue mejor la secuencia del artículo (agrupamiento → regiones irregulares → empalmes → círculos), a diferencia del método anterior que intersectaba directamente los círculos iniciales. Puede elegirse la alternativa circular en el panel lateral para sensibilidad metodológica.
6. Para cada componente del empalme, obtener su **centroide** y el **radio máximo a los vértices** del polígono. El círculo que lo circunscribe es la **zona operativa de penalización** del artículo.

Si **no hay empalmes**, el modelo A no tiene zonas para penalizar y se avisa de ello; no se fabrican regiones ficticias.

## Modo A — reproducción metodológica del artículo

Mismo enfoque conceptual de *A Novel Heuristic Approach for Simplifying Urban Risk Zones in Distribution Route Planning*:

- Clientes y depósito unidos por **arcos rectos**; la distancia `d_ij` es **Haversine** (metros).
- Para cada zona circular `k`, se evalúa si el **interior** del arco intersecta el círculo: `δ_ijk=1` si hay secante; una tangencia exacta no cuenta como segmento interior.
- `γ_i^k=1` si el extremo `i` está dentro de `k`; lo mismo para `j`.
- Penalización multiplicativa por arco y número de zonas secantes elegibles:

\[
 c_{ij}(\lambda)=d_{ij}\left(1+\lambda\sum_k\delta_{ij}^{k}(1-\max(\gamma_i^k,\gamma_j^k))\right).
\]

Los arcos con algún extremo dentro de un círculo **no reciben penalización por ese círculo**, para no impedir el servicio de clientes en la zona. Se conservan métricas separadas de **cruces brutos** y **penalizaciones efectivas**. **La longitud expuesta es informativa, no integra el costo del modo A.**

**No se usan calles reales**. Por ello una ruta recta que parece evitar una zona no demuestra un desvío vial factible. El modelo A no promete reproducir numéricamente los 112.81/128.45/129.41 km publicados: faltan los **97 clientes, las seis zonas originales y el solver** exactos, más configuración experimental.

## Modo B — extensión por red vial QGIS

- GeoJSON vial topológicamente conectado; los arcos del grafo se miden en UTM.
- Si `R` es la **unión** de los círculos seleccionados, el costo de un tramo vial `e` es

\[
 w_e(\lambda)=d_e+\lambda\,\operatorname{length}(e\cap R).
\]

- Con Dijkstra se calcula una matriz origen-destino de caminos mínimos **bajo ese peso**, almacenando tanto la **longitud física del camino seleccionado** como la **longitud dentro de las zonas**. A mayor λ, puede elegirse una ruta vial más larga con menor exposición.
- Se añaden conexiones aproximadas de clientes al vértice vial más cercano (distancia máxima configurable); el programa verifica conectividad de cada par y declara errores cuando corresponde.
- **Esta formulación es una extensión aditiva por tramo**, NO la formulación multiplicativa por arco del artículo. Esto se identifica en pantalla, archivos y manifiestos.

Para preparar QGIS: obtener vialidades en el área de estudio, incluir posibles desvíos, limpiar topología, partir líneas en intersecciones, comprobar sentidos y exportar GeoJSON WGS84. La red no considera restricciones de giro, velocidad, congestión, giros de vehículos pesados, semáforos ni seguridad en tiempo real.

## Las tres heurísticas y los seis escenarios

La solución inicial consiste en empaquetado factible de demandas, inserción de costo mínimo y 2-opt. Búsqueda local ejecuta movimientos de reubicación e intercambio. Búsqueda tabú admite movimientos temporalmente no mejorantes y utiliza memoria y criterio de aspiración. ACO usa feromonas y construcción probabilística factible, seguida de mejoras locales.

**Ya no hay una referencia oculta calculada únicamente con búsqueda local.** Al seleccionar las tres técnicas, la aplicación calcula:

| Método | λ=0 | λ configurable |
|---|---|---|
| Búsqueda local | Sí | Sí |
| Búsqueda tabú | Sí | Sí |
| Colonia de hormigas (ACO) | Sí | Sí |

La tabla muestra: distancia física, exposición, costo efectivamente optimizado por cada método, cruces, interacciones penalizadas, cambio de distancia respecto a la **menor distancia obtenida** de los tres métodos con λ=0, vehículos usados y tiempo. El mapa y el detalle por vehículo muestran **solo el escenario/método elegido** en el selector, identificado por nombre y λ.

Un cambio de objetivo (λ=0 vs λ>0) afecta cuál es el costo mínimo buscado: no compares costos penalizados entre modos A/B como si fueran la misma magnitud. Los tres métodos tienen presupuestos de exploración diferentes: los tiempos medidos en un equipo son una descripción, no prueba de superioridad general.

## Salidas y reproducibilidad

La descarga ZIP contiene:

- `comparacion_heuristicas.csv`: 3 × 2 filas (si se seleccionan tres métodos).
- `secuencias_por_vehiculo.csv`: clientes atendidos, vehículo, carga.
- `clientes.csv`.
- `matriz_OD_sin_penalizacion.csv` y `matriz_OD_con_penalizacion.csv`: costos auditables por pareja de depósito/cliente, distancia, exposición y secantes, **una vez por escenario**, no por heurística.
- `rutas_escenarios.geojson`: geometrías del recorrido seleccionado por cada escenario (en A, líneas rectas; en B, calles proporcionadas).
- `circulos_empalmes_o_zonas.geojson`: zonas de penalización efectivamente empleadas, EPSG:4326.
- `manifiesto_cvrp.json`: modalidad, técnicas, λ, parámetros, fecha UTC, versiones Python/dependencias, método de empalmes y SHA-256 de fuentes.

Se mantiene la descarga independiente de riesgos y empalmes GeoJSON para QGIS.

## Pruebas

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
# Prueba integrada con datos simulados, que incluye 25 y 150 clientes:
PYTHONPATH=. python tests/smoke_experiment.py
```

Cobertura de pruebas: lectura y capacidad, K-Means y superposiciones, multiplicador secante, exención por clientes en zona, prueba de tangencia, varios círculos, 3 heurísticas × 2 condiciones, cambio de camino en red vial, exportación de ZIP y aceptación de 150 clientes.

La interfaz **no se ha verificado en un despliegue real de Streamlit Community Cloud** dentro de este entorno. Revisa las limitaciones de recursos del servidor y usa la red artificial solo para comprobar el flujo, nunca para publicar resultados empíricos.

## Referencia científica y límites

El modo A implementa una **interpretación de la regla de penalización multiplicativa** y la secuencia de transformación geométrica descritas en el manuscrito proporcionado por el usuario. La tesis y un artículo reproducible deben usar registros reales, reporte del filtro espacial, parámetros de K, pruebas de sensibilidad, varias semillas, red y configuración del solver, y considerar errores de geocodificación. Para el modo B, el cambio de función objetivo y el uso de la red vial son **extensiones nuevas** que requieren experimentación independiente.

No incorpora QAOA ni computación cuántica. No se ha comprobado ventaja cuántica para estos casos. Antes de publicar código o datos de terceros, revisa derechos/licencias y privacidad. El proyecto no incorpora una licencia de código abierto porque no se ha autorizado ninguna.
