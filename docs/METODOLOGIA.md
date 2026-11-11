# Metodología técnica documentada

## Origen y refactorización

El cuaderno de referencia `K_means (1).ipynb` realizaba dos cargas CSV independientes desde Google Colab, aplicaba K-Means en grados de latitud/longitud, usaba números fijos de clústeres (incluidos 100 y 5), filtraba alrededor de un radio urbano de 4 km y seleccionaba parte de los grupos según un umbral acumulado del 30 %. Se construían polígonos convexos de grupos con tres puntos o más y se calculaban intersecciones para dos riesgos. En la nueva arquitectura, la entrada, el agrupamiento, la construcción de geometrías, los empalmes y la exportación se convierten en módulos separados.

## Entrada, calidad y reproducibilidad

La tabla tiene tres atributos obligatorios: latitud, longitud y tipo_riesgo. Se registra el número de fila original de Excel y los motivos cuantificables de exclusión: coordenadas ausentes o fuera de rango, riesgo vacío y filtro territorial. No se eliminan automáticamente coordenadas duplicadas: una ubicación puede registrar distintos incidentes. Los duplicados pueden alterar la partición por K-Means al aumentar su peso relativo; para aplicaciones donde un archivo registre ubicaciones en lugar de eventos, conviene revisar ese supuesto.

La ejecución registra un hash SHA-256 del archivo, semilla aleatoria, valores K por riesgo, filtros, radios, fecha UTC y versiones de bibliotecas en el manifiesto de salida. Esto permite rastrear un conjunto particular de resultados sin persistir la entrada en el servidor.

## Modelo geométrico

Para cada categoría `r`, sea `X_r = {x_1, ..., x_n}` el conjunto de posiciones proyectadas a un sistema UTM en metros. K-Means divide `X_r` en `K_r` grupos minimizando la suma de distancias cuadradas respecto a sus centroides:

`J_r = sum_{k=1..K_r} sum_{x_i in C_{r,k}} ||x_i - mu_{r,k}||^2`.

El número `K_r` es independiente entre categorías. Se propone automáticamente con un análisis de silueta cuando hay suficientes posiciones; el usuario puede establecer otro valor. Esto es solo un criterio de calidad del agrupamiento, no valida que la concentración revele un nivel anómalo de accidente o delito.

Para cada grupo se define `R_{r,k} = max( r_min, max_{x_i in C_{r,k}} ||x_i - mu_{r,k}|| + eps )`, donde `r_min` es el radio mínimo del usuario y `eps = 0.001 m` evita errores por límite numérico. La zona circular es el buffer euclidiano de su centroide con radio `R_{r,k}`. Se genera también una envolvente convexa con buffer de suavización configurable. El círculo contiene los puntos del clúster por construcción, pero no tiene interpretación probabilística.

## Construcción de empalmes sin doble conteo

Cada categoría puede tener varias zonas que se traslapan. Antes del análisis se aplica unión geométrica (`unary_union`) para obtener una región de cobertura por **tipo** de riesgo, no por clúster. Se crean de manera incremental piezas geométricas con etiquetas que identifican las categorías presentes. Al incorporar una nueva clase se separan (i) regiones previamente cubiertas y no cubiertas por ella, (ii) intersecciones etiquetadas con la nueva clase y (iii) regiones exclusivas nuevas. De esta manera, cada superficie participa en una sola pieza de la partición final. Las piezas con menos de dos tipos se conservan en las zonas originales, pero no forman parte del resultado `empalmes_multirriesgo`.

El campo `n_tipos` significa el número exacto de categorías cuyas uniones geométricas cubren la pieza. Se filtran áreas menores que un umbral en m². El algoritmo contabiliza superficies, **no tasas de incidentes**. La significación de las asociaciones entre categorías debe evaluarse aparte mediante un diseño estadístico.

## Precauciones para investigación científica

1. La delimitación administrativa real de Irapuato **no se incorpora en la muestra**, porque requiere un polígono oficial validado; el usuario puede proporcionar uno desde QGIS.
2. K-Means sobre coordenadas UTM requiere cautela en áreas que cruzan zonas UTM o que no puedan aproximarse localmente mediante distancias euclidianas.
3. Las distancias euclidianas no son distancias de recorrido por red vial. Las zonas no identifican qué arcos pueden o deben evitar los vehículos.
4. La medida de concentración de accidentes debe considerar exposición al tráfico; no equivale a riesgo por vehículo-kilómetro.
5. La herramienta no añade frecuencia, severidad, período temporal, denuncia, calidad de geocodificación ni pesos empíricos que los datos originales no contienen.
6. Para una publicación es necesario registrar la procedencia de los registros, la fecha de extracción, la cobertura espacial/temporal, sesgos, validación y sensibilidad al número de clústeres y al radio mínimo.
7. La importación de `zonas_circulares.geojson` puede constituir la entrada geométrica de un modelo CVRP sensible al riesgo **separado**, pero este repositorio no optimiza rutas ni cuantifica ahorros o exposición.
