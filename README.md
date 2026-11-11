# Riesgos Urbanos — análisis geoespacial multirriesgo con Streamlit

Aplicación Python/Streamlit para agrupar **cualquier número de tipos de riesgo** registrados en **un único archivo Excel, primera hoja**, con las columnas `latitud`, `longitud` y `tipo_riesgo`. El programa crea círculos de cobertura, envolventes convexas, intersecciones de zonas de tipos diferentes, mapa interactivo y exportaciones listas para QGIS.

> **Naturaleza de los resultados.** Es una herramienta de exploración geoespacial. K-Means y los polígonos derivados de sus centroides **no demuestran riesgo causal, probabilidad de accidente/delito, ni puntos críticos estadísticamente significativos**. Tampoco constituye un solucionador de rutas CVRP. Los puntos del ejemplo son inventados para pruebas.

## 1. Archivo Excel de entrada

Incluye `data/riesgos_ejemplo_irapuato.xlsx` con **una sola hoja** denominada `Riesgos` y 150 filas simuladas:

| A: latitud | B: longitud | C: tipo_riesgo |
|---|---|---|
| 20.692563 | -101.330562 | Accidentes |
| 20.682141 | -101.360585 | Inseguridad |

- **100** registros de Accidentes y **50** de Inseguridad.
- Las coordenadas corresponden al entorno urbano de Irapuato, **no se garantiza** que cada punto pertenezca al municipio oficial sin usar su polígono territorial.
- Puedes agregar filas con `Bloqueos`, `Inundaciones`, `Robos`, etc., sin modificar el código.
- La app lee **la primera hoja**, incluso si el Excel tiene otras, y conserva cada registro repetido como posible evento separado.
- Entrada estándar en **EPSG:4326**: latitud en A, longitud en B. No se aceptan coordenadas UTM en la entrada.
- Por rendimiento se limitan las cargas a 30 000 registros y 20 clases por ejecución; los límites pueden modificarse en `src/analysis.py` si cuentas con infraestructura apropiada.

## 2. Ejecutar en Windows

Recomendado: Python **3.11**.

1. Descomprime la carpeta del proyecto.
2. Abre una terminal dentro de la carpeta (donde está `app.py`).
3. Ejecuta:

```bat
py -3 -m pip install -r requirements.txt
py -3 -m streamlit run app.py
```

También se incluye `ejecutar_windows.bat` para instalar las dependencias y abrir Streamlit desde Windows.

## 3. Subir a GitHub y publicar en Streamlit Community Cloud

1. Crea un repositorio nuevo en <https://github.com/new> (por ejemplo `riesgos-urbanos`).
2. **Descomprime** el archivo ZIP descargado e incorpora los archivos del proyecto a la **raíz del repositorio**, de modo que `app.py`, `requirements.txt` y `data/` aparezcan en la raíz. No subas solamente el ZIP.
3. Abre <https://share.streamlit.io/> e inicia sesión con GitHub.
4. Selecciona **Create app**, tu repositorio, rama `main` y archivo principal `app.py`.
5. En configuración avanzada, selecciona **Python 3.11** si la plataforma permite elegirlo.
6. Despliega la aplicación. En la primera apertura aparecerá el conjunto de prueba incluido.
7. Descarga el Excel de ejemplo, modifica/agrega incidentes y súbelo a la aplicación.

El repositorio incluye `requirements.txt` y `.streamlit/config.toml` para que Streamlit instale las dependencias y configure la interfaz.

**Privacidad:** Si publicas la app, otras personas podrán acceder a ella. La aplicación no guarda archivos de entrada en una base de datos y crea las exportaciones en memoria, pero los archivos se procesan temporalmente en el servidor. No utilices datos de víctimas, domicilios particulares o registros sensibles sin anonimizar, justificar el tratamiento y controlar el acceso.

## 4. Flujo del algoritmo

```text
Excel: latitud | longitud | tipo_riesgo (A:B:C)
    ↓
Validación de datos y clasificación por nombre de riesgo
    ↓
Filtro espacial opcional: sin filtro / círculo urbano / polígono GeoJSON
    ↓
Proyección WGS84 → UTM local (distancias en metros)
    ↓
Por cada tipo: K sugerido (silueta) o elegido por el usuario
    ↓
K-Means (semilla 42) → centros, puntos asignados, cantidad de incidentes
    ↓
Zonas circulares [radio = max(distancia máxima al centro, radio mínimo)]
+ Envolventes convexas con buffer
    ↓
Zonas individuales (incluso sin empalme)
    ↓
Unión de círculos por riesgo + partición por tipos de riesgo coincidentes
    ↓
Mapa, tablas, GeoJSON, CSV y manifiesto JSON SHA-256 para QGIS
```

### Elección de K

La app calcula el índice de silueta para K entre 2 y una cantidad moderada de grupos en cada categoría, cuando el número de coordenadas lo permite. La sugerencia es **puramente geométrica**. El operador puede ajustar manualmente K por riesgo y repetir análisis de sensibilidad. Con menos de cuatro coordenadas distintas se sugiere K=1. El radio mínimo (80 m por defecto) impide que los grupos unitarios produzcan círculos de radio cero, pero es un **parámetro modelado** y debe justificarse con datos reales cuando se publique.

### Intersecciones de varios riesgos

Las zonas individuales **se conservan siempre** salvo que el usuario active un umbral mínimo de incidentes que las descarte de las intersecciones. Las zonas de un mismo riesgo se unen antes de comparar diferentes categorías. Una partición incremental evita contar dos veces una misma superficie. Así se distinguen regiones con `Accidentes + Inseguridad` y aquellas con `Accidentes + Inseguridad + Inundaciones`. El empalme **no implica correlación estadística ni causalidad**.

### Filtros territoriales

- **Sin filtro**: utiliza todos los registros válidos; predeterminado.
- **Radio urbano**: círculo ajustable alrededor de coordenadas elegidas. **No sustituye el polígono municipal**.
- **Límite municipal (GeoJSON)**: permite cargar un polígono territorial oficial desde QGIS, en EPSG:4326, para conservar solamente los puntos dentro del municipio.

## 5. Archivos ZIP exportados

| Archivo | Descripción |
|---|---|
| `puntos.geojson` | Puntos individuales en WGS84 (para mapa QGIS) |
| `puntos.csv` | Tabla con tipo de riesgo, clúster, identificador de zona y fila original |
| `zonas_circulares.geojson` | Regiones geométricas por riesgo |
| `envolventes_convexas.geojson` | Envolventes opcionales con buffer |
| `empalmes_multirriesgo.geojson` | Regiones compartidas por 2 o más tipos distintos |
| `resumen_zonas.csv` | Incidentes, radio, superficies y centroides |
| `resumen_empalmes.csv` | Riesgos presentes y superficie de cada coincidencia |
| `manifiesto_metodologico.json` | SHA-256 del Excel, parámetros, fecha UTC, CRS y versiones de biblioteca |
| `LEEME_QGIS.txt` | Pasos de importación a QGIS |

**QGIS:** `Capa > Añadir capa > Añadir capa vectorial` para cada GeoJSON. Para medir geometrías, trabaja en CRS proyectado. El GeoJSON se exporta en EPSG:4326; los campos `radio_m` y `area_m2` provienen del análisis UTM.

## 6. Pruebas automatizadas

```bash
python -m unittest discover -s tests -v
```

Revisan estructura del Excel, geoproyección, sugerencia de K, agrupamientos, filtros, empalmes sin doble conteo, incorporación de un tercer riesgo y exportación ZIP/QGIS.

## 7. Uso académico y límites

Para sustentar una publicación sobre riesgos viales, son necesarios datos documentados, validación de geocodificación, fecha/hora, denominadores de exposición al tránsito, análisis de sensibilidad espacial, comparación con KDE/Gi* y análisis de subregistro cuando corresponda. El paquete **no** entrega esas inferencias automáticamente.

El código es un prototipo propio rediseñado a partir del cuaderno del usuario. No se incluye licencia de redistribución: el titular debe decidir deliberadamente la licencia del repositorio antes de hacerlo público.

Más detalle: [docs/METODOLOGIA.md](docs/METODOLOGIA.md).
