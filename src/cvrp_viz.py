"""Mapa de resultados CVRP con capas de áreas de riesgo y rutas."""
from __future__ import annotations
import folium
from shapely.ops import transform
from shapely.geometry import mapping

COLORS=['#1565C0','#EF6C00','#2E7D32','#6A1B9A','#C62828','#00838F','#5D4037','#283593']


def mapa_cvrp(sol,matrices,clientes,to_geo,zonas=None,empalmes=None,
              mostrar_zonas=True,mostrar_empalmes=True):
    lon0,lat0=to_geo.transform(*matrices.coords[0])
    m=folium.Map(location=[lat0,lon0],zoom_start=12,tiles='OpenStreetMap',control_scale=True)
    if mostrar_zonas and zonas:
        for z in zonas:
            geom=transform(to_geo.transform,z['geometry'])
            folium.GeoJson(mapping(geom),name='Zonas de riesgo',
                           style_function=lambda f:{'color':'#D77C40','fillColor':'#E6A65E','weight':1,
                                                    'fillOpacity':.13},
                           tooltip=f"{z.get('tipo_riesgo','Riesgo')}: {z.get('n_incidentes','?')} incidentes").add_to(m)
    if mostrar_empalmes and empalmes:
        for e in empalmes:
            geom=transform(to_geo.transform,e['geometry'])
            folium.GeoJson(mapping(geom),name='Empalmes multirriesgo',
                           style_function=lambda f:{'color':'#B50070','fillColor':'#D50080','weight':2,
                                                    'fillOpacity':.30},tooltip=str(e.get('riesgos','Empalme'))).add_to(m)
    for v,route in enumerate(sol.rutas,1):
        if not route:
            continue
        road=[]
        seq=[0]+route+[0]
        for a,b in zip(seq,seq[1:]):
            pts=matrices.geometrias.get((a,b))
            if not pts:
                continue
            road.extend(pts if not road else pts[1:])
        geopath=[]
        for x,y in road:
            lon,lat=to_geo.transform(x,y)
            geopath.append([lat,lon])
        if len(geopath)>=2:
            folium.PolyLine(geopath, color=COLORS[(v-1)%len(COLORS)],weight=4,
                            tooltip=f'Ruta {v} · {len(route)} clientes · {sol.cargas[v-1]:g} unidades',
                            opacity=.9).add_to(m)
    folium.Marker([lat0,lon0],tooltip='Depósito',popup='Depósito',
                  icon=folium.Icon(color='black',icon='home',prefix='fa')).add_to(m)
    for i,r in clientes.iterrows():
        folium.CircleMarker(location=[float(r.latitud),float(r.longitud)],radius=5,
             color='#263238',weight=1,fill=True,fill_opacity=.95,fill_color='#FFFFFF',
             popup=f"{r.cliente}: demanda {r.demanda:g}",tooltip=str(r.cliente)).add_to(m)
    return m
