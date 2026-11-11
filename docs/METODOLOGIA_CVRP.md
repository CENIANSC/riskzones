# Metodología computacional: CVRP multipenalización y extensión vial

## Modelo de referencia (Modo A)

Fuente metodológica: manuscrito facilitado *A Novel Heuristic Approach for Simplifying Urban Risk Zones in Distribution Route Planning* (Aguirre-Ibarra et al.). El módulo representa el problema **capacitado estático** con restricciones de asignación, conservación de flujo y capacidad, no un DVRP con reoptimización temporal.

Se utiliza un Excel con incidentes georreferenciados por tipo de riesgo. Primero se aplican K-Means individuales; después se obtienen hulls poligonales de los clústeres y sus intersecciones entre categorías de riesgo distintas. Cada polígono de intersección se transforma en un círculo circunscrito con el centroide del empalme y el radio máximo desde el centroide a sus vértices. Una variante exploratoria puede calcular empalmes directamente de círculos de clúster, pero no es la opción por defecto.

Los nodos del CVRP son clientes y un depósito. Distancia Haversine entre coordenadas WGS84. Secante geométrica evaluada en la proyección UTM en metros, con las zonas circulares generadas. Sea `delta_ijk=1` si el segmento `ij` corta el interior de la zona `k`, y `gamma_i^k=1` si el cliente `i` está dentro del círculo. El costo de arco es:

```text
c_ij = d_ij * (1 + lambda * sum_k [delta_ijk * (1-max(gamma_i^k,gamma_j^k))])
```

Esta regla conserva la factibilidad de clientes situados en la zona. Un arco puede cortar físicamente un círculo y estar exento de penalización por alguno de sus extremos; por eso se registran cruces y penalizaciones por separado. Cuando lambda=0 hay interacciones geométricas pero **no** penalizaciones aplicadas. La exposición métrica reportada es longitud de línea recta dentro de la unión de círculos; no entra en el costo de este modo.

## Extensión vial (Modo B)

La red vial se recibe en GeoJSON WGS84; cada segmento debe tener vértices de intersección conectados. Se proyecta a UTM y se construye un grafo de aristas dirigidas, respetando propiedad `oneway` simple cuando existe. Dijkstra obtiene caminos mínimos para cada par de nodos bajo:

```text
w_e = longitud_e + lambda * longitud_e_dentro_de_union_de_circulos
```

Esto permite desvíos por calles cuando existe alternativa. La matriz de cada λ contiene la distancia física del camino escogido, su exposición geométrica y costo generalizado. Las restricciones de capacidad y cobertura del CVRP se resuelven sobre esa matriz. Es un cambio deliberado del criterio multiplicativo del artículo. En ambos modos los círculos solo están motivados por coocurrencia geométrica, no son una predicción probabilística.

La red no se descarga de Internet, el usuario debe cargarla, y no se asumen conexiones inexistentes ni se permiten accesos mayores al umbral de snap. Si el grafo está desconectado o los sentidos impiden un origen-destino, se detiene la ejecución.

## Algoritmos

1. Empaquetado con retroceso limitado de demandas en hasta `K` vehículos de capacidad `Q`.
2. Inserción de menor costo y mejora 2-opt intra-ruta.
3. **Búsqueda local:** reubicación, intercambio y 2-opt, acepta mejoras.
4. **Búsqueda tabú:** candidatos factibles, memoria por movimientos, aspiración, conservación de mejor solución, intensificación local.
5. **ACO simplificado:** construcción probabilística con feromonas y atractivo inverso del costo, descarte de hormigas inviables, evaporación, refuerzo, 2-opt y búsqueda local.
6. Validación de cobertura exactamente una vez y de las cargas; salida con rutas por vehículo.

Cada método se ejecuta con λ=0 y con λ seleccionado, siempre con la misma semilla y los mismos datos de entrada, dentro de cada modo. La comparación 3 × 2 es válida **como estudio exploratorio**; para publicaciones se deben repetir semillas y normalizar presupuesto de cómputo.

## Diseño de un estudio publicable

Usar los datos históricos auténticos y publicar un protocolo de limpieza/geocodificación, filtros de rango espacial, fuentes de incidentes, K y radio mínimo, fecha de consulta, red vial real validada, regla de penalización, parámetros del solucionador y versiones del software. Comparar varias semillas y estrategias, reportar mediana y dispersión de distancia física, exposición, cruces, costo objetivo, tiempo de matrices, tiempo de heurísticas y proporción de instancias factibles. No afirmar que el modo A implementa rutas viales transitables, ni que el modo B conserva idéntica función objetivo del manuscrito. Contrastar con OR-Tools o CVRPLIB donde corresponda. No mezclar datos sintéticos con reales en una tabla de resultados sin indicarlo explícitamente.

## Interpretación del artículo

El artículo reporta un ensayo de 97 clientes y seis círculos de conflicto. Sus resultados λ=0/1/3 (112.81, 128.45 y 129.41 km de costo reportado) **no se reproducen** con los clientes, incidentes o red de ejemplo. Para una réplica estricta hacen falta las mismas entradas originales y las condiciones detalladas de resolución. Este repositorio aporta la implementación metodológica y la extensión vial, con pruebas unitarias específicas.
