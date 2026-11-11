# Riesgos Urbanos + CVRP · Streamlit (versión 1.2)

Aplicación de análisis espacial multirriesgo (**K-Means, geometrías y empalmes**) que incorpora un **módulo de ruteo capacitado (CVRP)** con tres heurísticas para comparar distancia recorrida y longitud expuesta a zonas de conflicto.

> **Límites científicos:** los riesgos son geometrías exploratorias derivadas de K-Means, **no probabilidades de siniestros ni indicadores estadísticamente validados de peligro**. Los algoritmos CVRP son **heurísticos y no certifican optimalidad**. Los datos de ejemplo son **inventados**. Para rutas transitables por calles se requiere una **red vial GeoJSON real, topológicamente conectada, exportada desde QGIS**; el mapa base de OpenStreetMap por sí solo no suministra un grafo para calcular caminos.

## Ejecutar o desplegar

Recomendado: **Python 3.11 o 3.12**.

```bash
pip install -r requirements.txt
streamlit run app.py
```

- En GitHub, sube el **contenido de esta carpeta** al repositorio, no el ZIP como único archivo. `app.py` y `requirements.txt` deben estar en la raíz.
- En Streamlit Community Cloud (`https://share.streamlit.io/`), conecta el repositorio y selecciona `app.py`.
- Este proyecto no necesita clave API para el **mapa base** de OpenStreetMap. Las teselas requieren Internet y están sujetas a la [política de uso OSM](https://operations.osmfoundation.org/policies/tiles/).

## Entradas de la aplicación

### 1. Riesgos urbanos (Excel, una sola pestaña)

`data/riesgos_ejemplo_irapuato.xlsx` contiene **100 accidentes + 50 eventos de inseguridad ficticios**, con tres columnas:

| latitud | longitud | tipo_riesgo |
|---:|---:|---|
| 20.692563 | -101.330562 | Accidentes |
| 20.682141 | -101.360585 | Inseguridad |

La app identifica las etiquetas, acepta tipos adicionales y crea agrupamientos/empalmes. La primera hoja se procesa; todas las coordenadas están en **EPSG:4326**.

### 2. Clientes (CSV o Excel, primera hoja)

`data/clientes_ejemplo_irapuato.csv` incluye **25 clientes ficticios**:

| cliente | latitud | longitud | demanda |
|---|---:|---:|---:|
| C01 | 20.691... | -101.35... | 1... |

`cliente` único; `demanda` estrictamente positiva, en las **mismas unidades que la capacidad vehicular** (por ejemplo, cajas). La ubicación del depósito se configura en la interfaz. Cada cliente se visita **exactamente una vez** y todos los vehículos regresan al depósito. La flota tiene capacidad homogénea; se pueden dejar vehículos sin usar. Límite prototipo de **70 clientes** por ejecución.

### 3. Red vial (opcional, GeoJSON exportado desde QGIS)

Este archivo habilita rutas sobre calles **sin API de terceros**. Debe contener `LineString` o `MultiLineString` en EPSG:4326, con **intersecciones conectadas mediante vértices comunes** (los cruces meramente visuales no están conectados). Cada segmento que pueda ser recorrido en ambos sentidos se considera bidireccional; `oneway=yes`, `1` o `true` marca el tramo como unidireccional en el sentido de la digitalización. No se modelan giros prohibidos, velocidades, pendientes, tráfico ni horarios de circulación.

**Preparación en QGIS:**

1. Descarga o importa la red de calles que cubra **depósito, clientes y posibles desvíos** de Irapuato; por ejemplo, desde datos OSM mediante QuickOSM.
2. Recorta el área, corrige geometrías, **noda/splitea las intersecciones** y asegúrate de que los componentes de la red estén conectados; conserva el atributo `oneway` cuando sea fiable.
3. Exporta `GeoJSON`, CRS `EPSG:4326`, con una selección de calles aptas para el vehículo. Se admite un máximo preventivo de ~**12 000 vértices** y **22 MB** de GeoJSON para Streamlit Community Cloud.
4. Sube ese archivo en la sección CVRP y aumenta la tolerancia de conexión únicamente cuando sea justificable. El programa comprueba alcanzabilidad entre todos los puntos.

**Sin red GeoJSON**, la opción geométrica calcula distancias euclidianas en la proyección UTM y dibuja líneas rectas **no transitables**. No se debe usar para afirmar evitación real de zonas por carretera.

## Función objetivo

La app compara una referencia optimizada **solo por distancia** (`λ=0`) contra métodos que minimizan:

\[
Z = D + \lambda E
\]

- `D`: metros recorridos en la red vial suministrada (o distancia geométrica, si no hay red).
- `E`: metros del recorrido dentro de las zonas seleccionadas: **solo empalmes** o **todas las zonas**. La unión espacial evita contar varias veces la longitud dentro de zonas superpuestas.
- `λ`: coeficiente adimensional >=0 que expresa la importancia relativa de evitar exposición.
- `Z`: costo generalizado en metros equivalentes; **no representa kilómetros físicos**.

En modo vial, cada camino entre dos destinos es el **camino mínimo ponderado** en una red dirigida, con costo por segmento `longitud + λ × longitud_en_zona`. Se calculan matrices de distancia física y exposición **del camino elegido**, luego se resuelve el CVRP de asignación y secuenciación. Por ello **no basta mirar el mapa OSM**; se requiere GeoJSON de calles si se quiere un desvío real.

## Tres opciones de solución (sin depender de OR-Tools)

| Alternativa | Implementación | Uso |
|---|---|---|
| **Búsqueda local** | Empaque factible, inserción de menor costo, `2-opt`, reubicaciones/intercambios | Referencia rápida |
| **Búsqueda tabú** | Arranca con búsqueda local; explora vecinos, lista tabú con aspiración y reintensificación | Escape de mínimos locales |
| **ACO** | Feromonas, construcción estocástica restringida por capacidad, evaporación, refuerzo de mejores recorridos y mejora local | Diversificación |

La asignación inicial de clientes a vehículos usa un empaque con retroceso acotado para respetar capacidad; si no encuentra uno factible, informa el problema en vez de devolver rutas inválidas. Cada técnica devuelve distancia física, exposición, costo penalizado, cantidad de vehículos utilizados, cargas y tiempo de cómputo. La **semilla aleatoria** es configurable.

**Nota:** esto es un prototipo académico, no implementaciones canónicas validadas de ACO/Tabú contra todas las instancias CVRPLIB. La mejora de calidad debe comprobarse con experimentos multisemilla, diversidad de instancias y comparaciones contra OR-Tools/soluciones conocidas.

## Ejemplo paso a paso

1. Publica la app y abre el conjunto ficticio de riesgos incluido.
2. Ajusta K por cada tipo si lo consideras necesario; visualiza empalmes en el mapa.
3. Desplázate a **CVRP** y carga `clientes_ejemplo_irapuato.csv` o utiliza el ejemplo incluido.
4. Indica número de vehículos y capacidad. El ejemplo usa **5 vehículos de 25 unidades**.
5. Selecciona **Solo empalmes** o **Todas las zonas** y cambia `λ` (por ejemplo, 0 / 5 / 15).
6. Elige **las tres heurísticas** y haz clic en *Resolver y comparar rutas CVRP*.
7. Examina tabla, mapa y rutas por vehículo, y descarga el ZIP de resultados para QGIS.
8. Cuando tengas un GeoJSON **real y conectado** de las calles, selecciona *Red vial GeoJSON* y repite el análisis para comparar rutas transitables.

## Exportaciones CVRP

- `comparativo_algoritmos.csv`: distancia, exposición, costo, vehículos usados, duración.
- `rutas_clientes.csv`: secuencia de clientes por ruta.
- `clientes.csv`: entradas analizadas.
- `rutas.geojson`: rutas por vehículo y por algoritmo, EPSG:4326.
- `manifiesto_cvrp.json`: parámetros, fecha UTC, SHA-256 de clientes/riesgos/red vial y semilla.

El ZIP de **análisis de riesgos** sigue disponible por separado (zonas circulares, empalmes, centroides, CSV y manifestación).

## Pruebas

```bash
python -m unittest discover -s tests -v
```

Incluyen validación de riesgo, varios tipos de eventos, GeoJSON de calles, conectividad, capacidad, cobertura de todos los clientes, tres algoritmos y prueba de desvío por riesgo.

## ¿Por qué no incluimos una cuarta opción cuántica?

La computación cuántica se investiga para CVRP mediante **QUBO, QAOA, quantum annealing** y algoritmos híbridos. Actualmente no garantiza soluciones mejores o más rápidas para instancias urbanas grandes frente a métodos clásicos. Incluir un botón cuántico en esta aplicación sin procesador cuántico ni un benchmark válido sería engañoso. Una futura versión experimental podría incorporar instancias pequeñas y comparar calidad/tiempo de optimización **incluyendo transferencia y preparación de datos**, con recursos y acceso autorizados a hardware cuántico.

Lecturas recomendadas:
- Google OR-Tools CVRP: https://developers.google.com/optimization/routing/cvrp
- OR-Tools opciones heurísticas: https://developers.google.com/optimization/routing/routing_options
- *Applying analog quantum computing to solve optimisation problems: case studies on Max-Cut and CVRP* (2025): https://doi.org/10.1080/23302674.2025.2463530
- Revisión de optimización cuántica logística (2025): https://www.mdpi.com/2624-6511/8/6/206

## Límites y ética

No publicar nombres, domicilios ni detalles identificables de víctimas; el servidor procesa los archivos durante la sesión. K-Means no sustituye análisis de siniestralidad con tasas de exposición al flujo vehicular ni valida estadísticamente puntos críticos. En red vial, la fidelidad de los recorridos depende de la calidad de topología y atributos de la capa (incluidos sentidos). La red descargada de OSM puede incluir errores o no tener toda la información operativa. Antes de emplear rutas en campo, verificar legalidad, seguridad, accesibilidad y restricciones en terreno. **Nunca desplegar itinerarios calculados aquí sin validación previa.**

No se incluye licencia de software: determina la licencia y créditos antes de publicarlo.
