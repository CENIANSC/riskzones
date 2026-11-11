# Metodología de ruteo capacitado sensible a zonas de conflicto

## 1. Problema de investigación

El CVRP determina un conjunto de circuitos que comienzan y terminan en un depósito, visitan cada cliente una sola vez y respetan la capacidad vehicular. La aplicación contrasta una estrategia de minimización de distancia con una estrategia de minimización de **costo generalizado** que incorpora la longitud transitada por áreas de riesgo espacial.

Las regiones de riesgo son polígonos exploratorios derivados de K-Means y de sus empalmes geométricos. No son tasas de riesgo ni frecuencias de accidentes/robos esperadas. Son **supuestos geométricos de modelado**, verificables pero no equivalentes a peligrosidad estadísticamente validada.

## 2. Notación y objetivo

- `V={0,...,n}`: depósito `0` y clientes `1..n`.
- `K`: número máximo de vehículos homogéneos.
- `q_i`: demanda del cliente `i`.
- `Q`: capacidad de cada vehículo.
- `d_ij(λ)`: longitud física del trayecto entre `i` y `j` seleccionado por la matriz OD.
- `e_ij(λ)`: longitud de ese mismo trayecto dentro de las zonas seleccionadas.
- `c_ij(λ)=d_ij(λ)+λ e_ij(λ)`: costo generalizado, expresado en metros equivalentes.
- `x_ij^k∈{0,1}`: uso del arco de conexión entre nodos `i` y `j` por vehículo `k`.

Objetivo: minimizar `sum_k sum_i sum_j c_ij(λ) * x_ij^k` sujeto a cobertura de todos los clientes, conservación de flujo por vehículo, regreso al depósito, eliminación de subtours y `sum_i q_i * y_i^k <= Q`. Los operadores implementados representan rutas como listas de clientes y verifican cobertura y capacidad explícitamente antes de devolver la solución.

Una penalización `λ=0` equivale a minimizar distancia; con `λ>0` se intercambia recorrido adicional por menos exposición. La función no contiene probabilidades de accidente, costos monetarios ni tiempo de tránsito porque los datos actuales no permiten estimarlos.

## 3. Dos modos de cálculo de distancia

### (A) Geometría recta — prototipo exclusivamente ilustrativo

Convierte los puntos WGS84 a UTM y calcula distancias euclidianas y longitud del segmento recto dentro de la unión de zonas. El mapa muestra el segmento, NO una calle ni un recorrido físicamente posible. Este modo **no debe utilizarse** para afirmar que una distribución evita vialidades conflictivas.

### (B) Red vial importada de QGIS — prototipo de navegación en grafo

Importa un GeoJSON de líneas de calle WGS84, lo proyecta a UTM y genera un grafo dirigido de vértices y segmentos. Cada conexión tiene `coste = longitud + λ * longitud_intersectada` con la unión de zonas de exposición; los segmentos bidireccionales se duplican en ambos sentidos, salvo propiedad `oneway` reconocida. Para cada depósito/cliente se busca el vértice de calle más próximo y se comprueba una distancia máxima de conexión. Después, Dijkstra calcula un camino mínimo generalizado entre cada par de destinos y guarda simultáneamente su longitud física y exposición.

La matriz entre pares depende de λ: el camino de costo mínimo puede cambiar con la penalización. **Esto es precisamente lo que permite el desvío dentro de la red vial**, a diferencia de un segmento recto. Si el grafo presenta componentes desconectados, sentidos incompatibles o puntos demasiado alejados, el sistema falla explícitamente en vez de inventar un camino.

Advertencias: no se modelan giros prohibidos, semáforos, tráfico, velocidades, horarios, cierres ni circulación de vehículos pesados. Las intersecciones deben estar nodadas en QGIS. El tipo de capa y la calidad de topología afectan validez del resultado. El costo de conectar puntos al grafo se añade como aproximación recta; pueden existir accesos reales más largos.

## 4. Heurísticas implementadas

### Solución inicial

1. Verificar que la demanda máxima no exceda `Q`, y que la demanda total no exceda `KQ`.
2. Asignar demandas a vehículos mediante un algoritmo de empaquetado con retroceso limitado; no siempre existen soluciones factibles aun con capacidad global suficiente.
3. Ordenar clientes de cada vehículo mediante inserción de menor costo.
4. Aplicar inversiones `2-opt` y movimientos factibles de reubicación/intercambio de clientes entre vehículos.

### Búsqueda local

Acepta únicamente una mejora estricta del costo generalizado tras generar un conjunto de vecinos factibles. Se detiene cuando el muestreo no encuentra una mejora o se alcanza el presupuesto de pasadas. Es un método heurístico muy rápido, pero puede detenerse en un mínimo local.

### Búsqueda tabú

Parte de la solución local. En cada iteración considera reubicaciones e intercambios entre vehículos; permite movimientos temporalmente no mejorantes y restringe movimientos recientes mediante una memoria tabú. Una aspiración autoriza movimientos tabú cuando mejoran la mejor solución histórica. Se conserva la mejor solución encontrada y se aplica una intensificación local final.

### Ant Colony Optimization (ACO)

Simula colonias de hormigas que construyen rutas secuencialmente. La probabilidad de elegir el siguiente cliente combina feromona de arco y atractivo inverso de costo; cada hormiga respeta demandas y capacidad residual. Si una construcción deja clientes sin servir, se descarta. Tras la construcción se aplica `2-opt`; las mejores soluciones aportan feromona a sus arcos, mientras la evaporación evita persistencia absoluta. Al final se aplica búsqueda local a la mejor solución ACO. Para evitar una regresión trivial, se conserva como mínimo la solución inicial si las hormigas no mejoran el costo.

Ninguna de estas alternativas produce certificados de optimalidad. Las implementaciones son **simplificadas**, controlables por semilla, comparables en la interfaz pero con distinta cantidad y estructura de operaciones; no se presentan como benchmarks estándar equivalentes en presupuesto de cómputo.

## 5. Diseño de experimentos para publicación científica

Sugerencia:

1. Crear escenarios `λ∈{0,1,3,5,10}` y dos alcances de zona: empalmes y todas las zonas.
2. Usar datos reales verificados y una red vial consistente con sentido de circulación.
3. Comparar los tres métodos durante varias semillas (`n>=20`), mismo equipo, mismo conjunto de instancias; registrar media, desviación, mejor costo y tiempo.
4. Reportar **distancia física**, **longitud expuesta**, **costo generalizado**, cargas, clientes atendidos, tiempo de cómputo y porcentaje de cobertura; jamás resumir todo como «distancia».
5. Realizar análisis de sensibilidad por número de clústeres, buffer/radio geométrico y λ.
6. Evaluar validez externa: diferentes ciudades, días, cambios de tráfico, cierre de calles e incertidumbre de geocodificación.
7. Incorporar una comparación con **OR-Tools Guided Local Search** sobre el mismo grafo y parámetros para tener una línea de base reconocida y validar con CVRPLIB cuando sea posible.
8. Documentar versiones, hashes de fuentes, filtros de riesgo, grafo vial, semillas y límites de tiempo.

## 6. Posible línea cuántica

Una extensión cuántica podría representar pequeñas instancias del CVRP como QUBO y ensayar QAOA o recocido cuántico; otra es resolver clásicamente la partición de clientes y ensayar subproblemas TSP con un procesador cuántico o simulador. Esto requiere acceso a hardware/simulador cuántico, traducción del problema, control de factibilidad, evaluación de latencia extremo a extremo y comparación contra la mejor solución clásica disponible.

La literatura vigente reconoce dificultades de escala, costo de embedding, ruido y factibilidad. Esta versión no incorpora ejecución cuántica ni debe describirse como «cuánticamente optimizada».

Fuentes de apoyo:
- https://developers.google.com/optimization/routing/cvrp
- https://developers.google.com/optimization/routing/routing_options
- https://doi.org/10.1080/23302674.2025.2463530
- https://www.mdpi.com/2624-6511/8/6/206
