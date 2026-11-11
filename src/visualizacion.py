"""Mapas Folium con controles de capas (requiere conectividad a teselas OSM)."""
from __future__ import annotations

import folium
from folium.plugins import Fullscreen, MiniMap
from pyproj import Transformer
from shapely.ops import transform

COLORS = ["#2563EB", "#DC2626", "#059669", "#A855F7", "#EA580C", "#0891B2",
          "#C026D3", "#B45309", "#64748B", "#65A30D", "#C2410C", "#0F766E"]


def mapa(*, puntos, zonas, envolventes, empalmes, to_geo: Transformer,
         mostrar_puntos=True, mostrar_hulls=False, mostrar_empalmes=True,
         limite_original=None, max_puntos=3000):
    tipos = sorted(puntos.tipo_riesgo.unique())
    paleta = {t: COLORS[i % len(COLORS)] for i, t in enumerate(tipos)}
    mp = folium.Map(
        location=[float(puntos.latitud.mean()), float(puntos.longitud.mean())],
        zoom_start=12, tiles="CartoDB positron", control_scale=True, prefer_canvas=True,
    )
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
