"""Visualización Folium sobre OpenStreetMap sin token, con capas controlables."""
from __future__ import annotations
import folium
from shapely.ops import transform
from shapely.geometry import mapping

COLORS=['#1565C0','#EF6C00','#2E7D32','#6A1B9A','#C62828','#00838F','#5D4037','#283593']


def mapa_cvrp(sol, matrices, clientes, to_geo, zonas=None, empalmes=None,
              mostrar_zonas=True,mostrar_empalmes=True,circulos=None):
    lon0,lat0=to_geo.transform(*matrices.coords[0])
    m=folium.Map(location=[lat0,lon0],zoom_start=12,tiles='OpenStreetMap',control_scale=True)
    grp_z=folium.FeatureGroup(name='Zonas K-Means individuales',show=False).add_to(m)
    grp_e=folium.FeatureGroup(name='Empalmes irregulares',show=bool(mostrar_empalmes)).add_to(m)
    grp_c=folium.FeatureGroup(name='Círculos usados para penalización',show=True).add_to(m)
    grp_r=folium.FeatureGroup(name='Rutas de la solución seleccionada',show=True).add_to(m)
    grp_p=folium.FeatureGroup(name='Depósito y clientes',show=True).add_to(m)

    if mostrar_zonas and zonas:
        for z in zonas:
            geom=transform(to_geo.transform,z['geometry'])
            folium.GeoJson(mapping(geom),
                style_function=lambda f:{'color':'#D77C40','fillColor':'#E6A65E','weight':1,
                                         'fillOpacity':.12},
                tooltip=f"{z.get('tipo_riesgo','Riesgo')}: {z.get('n_incidentes','?')} incidentes").add_to(grp_z)
    if mostrar_empalmes and empalmes:
        for e in empalmes:
            geom=transform(to_geo.transform,e['geometry'])
            folium.GeoJson(mapping(geom),
                style_function=lambda f:{'color':'#B50070','fillColor':'#D50080','weight':2,
                                         'fillOpacity':.28},
                tooltip=str(e.get('riesgos','Empalme'))).add_to(grp_e)
    if circulos:
        for c in circulos:
            geo=transform(to_geo.transform,c['geometry'])
            folium.GeoJson(mapping(geo),
                style_function=lambda f:{'color':'#AF2B26','fillColor':'#EF5350',
                                         'weight':4,'fillOpacity':.07,'dashArray':'8, 5'},
                tooltip=f"Zona {c.get('id_zona','?')} · radio {c.get('radio_m',0):.1f} m").add_to(grp_c)
    for v,route in enumerate(sol.rutas,1):
        if not route:
            continue
        path=[]
        for a,b in zip([0]+route,[*route,0]):
            pts=matrices.geometrias.get((a,b))
            if pts:
                path.extend(pts if not path else pts[1:])
        latlon=[]
        for x,y in path:
            lon,lat=to_geo.transform(x,y)
            latlon.append([lat,lon])
        if len(latlon)>=2:
            folium.PolyLine(latlon,color=COLORS[(v-1)%len(COLORS)],weight=4,
                tooltip=f'Vehículo {v} · {len(route)} clientes · carga {sol.cargas[v-1]:g}',
                opacity=.91).add_to(grp_r)
    folium.Marker([lat0,lon0],tooltip='Depósito',popup='Depósito',
                  icon=folium.Icon(color='black',icon='home',prefix='fa')).add_to(grp_p)
    for _,r in clientes.iterrows():
        folium.CircleMarker(location=[float(r.latitud),float(r.longitud)],radius=4,
            color='#263238',weight=1,fill=True,fill_opacity=.95,fill_color='#FFFFFF',
            popup=f"{r.cliente}: demanda {r.demanda:g}",tooltip=str(r.cliente)).add_to(grp_p)
    folium.LayerControl(collapsed=False).add_to(m)
    return m
