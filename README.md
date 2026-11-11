# Riesgos Urbanos + CVRP v1.3.5 — Red vial real de OpenStreetMap

La versión 1.3.5 mantiene el **Modo A** del artículo (Haversine y penalización multiplicativa sobre círculos construidos a partir de empalmes). En **Modo B** incorpora tres fuentes de vialidad:

1. **Descargar calles REALES de OpenStreetMap (OSMnx).** Selecciona centro (latitud, longitud) y radio de estudio, y presiona el botón de descarga. Requiere acceso de Streamlit Cloud al servicio Overpass. Descarga los arcos transitables por vehículos (`network_type="drive"`) y los exporta como GeoJSON dirigido EPSG:4326. Puedes descargar ese GeoJSON para conservar la misma red en futuras ejecuciones o usarlo en QGIS.
2. **Subir tu propia red vial GeoJSON desde QGIS.** Se mantiene el flujo previo.
3. **Red ARTIFICIAL:** exclusivamente para pruebas.

## Despliegue en GitHub y Streamlit

Sube el **contenido completo** de este ZIP a la raíz del repositorio, reemplazando `app.py`, `src/` y `requirements.txt`. **No combines versiones.** Inicia con `app.py` como archivo principal. La cabecera debe indicar `Paquete integrado 1.3.5`. Se mantiene la versión interna 1.3.4 del módulo del mapa porque la interfaz de visualización no ha cambiado.

`requirements.txt` incorpora `osmnx>=2.1,<3`. Requiere Python 3.11+ (`.python-version` fija 3.11). Streamlit Community Cloud instalará dependencias al desplegar.

## Uso con calles reales

1. Carga tu Excel de riesgos y realiza K-Means + análisis de empalmes.
2. Abre **CVRP experimental**, carga un Excel de clientes con demandas y define depósito, capacidad y vehículos.
3. Selecciona **Modo B — Extensión vial** y **Descargar calles REALES de OpenStreetMap**.
4. Configura el centro y radio de descarga (comienza con 2,500 metros). Descarga la red con el botón.
5. Guarda el archivo `irapuato_osm_drive_2500m.geojson` ofrecido en pantalla para experimentos reproducibles.
6. Ejecuta los escenarios con λ = 0 y λ > 0. Compara distancia, exposición, costos y rutas sobre calles.

**IMPORTANTE:** el área descargada debe cubrir **todos** los clientes y el depósito, incluidos caminos intermedios. Si las visitas quedan fuera del radio o aparecen a más de 250 m del vértice vial más cercano, amplía el área, ajusta el umbral justificadamente o revisa los puntos. Descargas mayores pueden superar 12,000 vértices o 22 MB y serán rechazadas para evitar saturar el servicio gratuito; en ese caso divide el estudio en áreas o usa una instancia reducida.

Los datos de OpenStreetMap **no garantizan cobertura, accesos, sentidos de circulación, restricciones de giro o tráfico actualizado**, y el motor conecta los clientes al vértice de red más próximo mediante un tramo geométrico. No representa restricciones de giro ni demanda por horario. La conexión a Overpass puede fallar o demorarse por cuotas y restricciones del servidor. La red guardada permite reproducir experimentos sin volver a consultar Overpass. Los resultados deben validarse antes de emplearse en distribución real.

## Precisión metodológica

- Modo A: costo multiplicativo por arco secante (artículo), líneas Haversine no transitables.
- Modo B: costo por **distancia vial más λ multiplicado por la longitud vial dentro de la unión de círculos**. OSMnx es solo el origen de los arcos de calle, no un solucionador CVRP.
- Se mantienen tres heurísticas: búsqueda local, tabú y colonia de hormigas (ACO); ninguna garantiza óptimo global.
- La red vial real se descarga **en tiempo de uso**. El proyecto no incluye un extracto OSM de Irapuato precargado, dado que no se ha podido obtener y validar una descarga real en este entorno.

## Validación

Ejecuta `python -m unittest discover -s tests -v`. Las pruebas de la conversión de un grafo de OSMnx a GeoJSON y de univocidad vial se realizan **sin Internet**, con un grafo simulado. Una verificación integral de descarga en Streamlit Cloud y de exactitud de los datos OSM debe hacerse en el despliegue real.
