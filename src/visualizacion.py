"""Mapas Folium con calles de OpenStreetMap y capas de riesgo.

No utiliza CARTO: desde septiembre de 2026 sus mosaicos exigen API key.
"""
from __future__ import annotations

import folium
from folium.plugins import Fullscreen, MiniMap
from pyproj import Transformer
from shapely.ops import transform
from src.cvrp_experimentos import crear_circulos_empalmes

VERSION_VISUALIZACION = '1.3.4'

COLORS = ["#2563EB", "#DC2626", "#059669", "#A855F7", "#EA580C", "#0891B2",
          "#C026D3", "#B45309", "#64748B", "#65A30D", "#C2410C", "#0F766E"]


def mapa(*, puntos, zonas, envolventes, empalmes, to_geo: Transformer,
         mostrar_puntos=True, mostrar_hulls=False, mostrar_empalmes=True,
         mostrar_circulos_conflicto=True, mostrar_centros_conflicto=True,
         limite_original=None, max_puntos=3000):
    tipos = sorted(puntos.tipo_riesgo.unique())
    paleta = {t: COLORS[i % len(COLORS)] for i, t in enumerate(tipos)}
    # OpenStreetMap estándar muestra vialidades y no requiere clave API.
    # Se mantiene la atribución obligatoria. CARTO Positron ya no funciona sin key.
    mp = folium.Map(
        location=[float(puntos.latitud.mean()), float(puntos.longitud.mean())],
        zoom_start=13, tiles=None, control_scale=True, prefer_canvas=True,
    )
    folium.TileLayer(
        tiles="OpenStreetMap", name="Calles y vialidades (OpenStreetMap)",
        overlay=False, control=True, show=True,
    ).add_to(mp)
    if limite_original is not None:
        folium.GeoJson(limite_original.__geo_interface__, name="Límite de estudio (aportado)",
                       style_function=lambda _: {"color": "#374151", "weight": 2,
                                                  "fillOpacity": 0}).add_to(mp)
    # Zonas circulares: una capa por categoría.
    for tipo in tipos:
        sub = folium.FeatureGroup(name=f"Zonas · {tipo}", show=True)
        for z in zonas:
            if z["tipo_riesgo"] != tipo:
                continue
            g = transform(to_geo.transform, z["geometry"])
            folium.GeoJson(
                g.__geo_interface__,
                style_function=lambda _, color=paleta[tipo]: {"color": color,
                    "fillColor": color, "weight": 2, "fillOpacity": 0.16},
                tooltip=(f"{tipo} · zona {z['cluster']} · {z['n_incidentes']} registros · "
                         f"radio {z['radio_m']:.0f} m"),
            ).add_to(sub)
        sub.add_to(mp)
    if mostrar_hulls:
        hgroup = folium.FeatureGroup(name="Envolventes convexas", show=False)
        for z in envolventes:
            g = transform(to_geo.transform, z["geometry"])
            folium.GeoJson(g.__geo_interface__,
                           style_function=lambda _, c=paleta[z["tipo_riesgo"]]: {
                               "color": c, "fillOpacity": 0, "dashArray": "4, 6", "weight": 2
                           }, tooltip=f"Hull: {z['tipo_riesgo']} / {z['cluster']}").add_to(hgroup)
        hgroup.add_to(mp)
    if mostrar_empalmes and empalmes:
        eg = folium.FeatureGroup(name="Empalmes (2+ riesgos)", show=True)
        for e in empalmes:
            g = transform(to_geo.transform, e["geometry"])
            folium.GeoJson(g.__geo_interface__,
                           style_function=lambda _, n=e["n_tipos"]: {
                               "color": "#7C2D12", "weight": 2,
                               "fillColor": "#F59E0B" if n == 2 else "#D946EF",
                               "fillOpacity": 0.48,
                           }, tooltip=(f"{e['riesgos']} · {e['n_tipos']} riesgos · "
                                       f"área {e['area_m2']:.0f} m²")).add_to(eg)
        eg.add_to(mp)
    # Zonas circulares definitivas: se obtienen de los EMPALMES, no de K-Means.
    # Se dibujan como capas propias, con estilo contrastante y centros visibles.
    circulos_conflicto = crear_circulos_empalmes(empalmes or [])
    if mostrar_circulos_conflicto and circulos_conflicto:
        cg = folium.FeatureGroup(name=f"CÍRCULOS DE CONFLICTO · {len(circulos_conflicto)} (penalización CVRP)", show=True)
        for c in circulos_conflicto:
            g = transform(to_geo.transform, c["geometry"])
            texto = (f"Círculo {c['id_zona']} | {c['riesgos']} | "
                     f"radio {c['radio_m']:.1f} m | "
                     f"empalme original {c['area_empalme_m2']:.0f} m²")
            folium.GeoJson(g.__geo_interface__,
                style_function=lambda _, color="#0D47A1": {
                    "color": color, "fillColor": "#64B5F6", "weight": 4,
                    "opacity": 1, "fillOpacity": 0.09, "dashArray": "8, 5"
                }, tooltip=texto).add_to(cg)
        cg.add_to(mp)
        if mostrar_centros_conflicto:
            centros = folium.FeatureGroup(name="Centros y radios de conflicto", show=True)
            for c in circulos_conflicto:
                lon, lat = to_geo.transform(c["centro_x_m"], c["centro_y_m"])
                folium.CircleMarker(
                    location=[lat, lon], radius=6, color="#08306B",
                    weight=2, fill=True, fill_color="#FFFFFF", fill_opacity=1,
                    tooltip=f"Centro {c['id_zona']} · radio {c['radio_m']:.1f} m",
                    popup=f"Círculo {c['id_zona']} · {c['riesgos']} · {c['radio_m']:.1f} m"
                ).add_to(centros)
            centros.add_to(mp)
    if mostrar_puntos:
        pg = folium.FeatureGroup(name="Incidentes individuales", show=True)
        muestreo = puntos if len(puntos) <= max_puntos else puntos.sample(max_puntos, random_state=42)
        for row in muestreo.itertuples(index=False):
            folium.CircleMarker(
                location=[float(row.latitud), float(row.longitud)], radius=3,
                color=paleta[str(row.tipo_riesgo)], fill=True, fill_opacity=0.85,
                weight=1, tooltip=f"{row.tipo_riesgo} · fila Excel {row.fila_excel}",
            ).add_to(pg)
        pg.add_to(mp)
    folium.LayerControl(collapsed=False).add_to(mp)
    Fullscreen(position="topright").add_to(mp)
    return mp, paleta
