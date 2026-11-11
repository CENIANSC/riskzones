"""Pruebas ejecutables con: python -m unittest discover -s tests -v"""
from __future__ import annotations

import io
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import Point

from src.analysis import (
    ajustar_por_riesgo, filtrar_area, k_sugerido, leer_excel, leer_limite_geojson,
    proyeccion, superposiciones, features_geojson,
)
from src.exportacion import crear_paquete

ROOT = Path(__file__).resolve().parents[1]


class TestRiesgosUrbanos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / 'data' / 'riesgos_ejemplo_irapuato.xlsx').read_bytes()
        cls.df, cls.info = leer_excel(cls.raw)

    def test_excel_tres_columnas_una_hoja(self):
        self.assertEqual(len(self.df), 150)
        self.assertEqual(self.df.tipo_riesgo.value_counts().to_dict(),
                         {'Accidentes': 100, 'Inseguridad': 50})
        self.assertEqual(self.info['registros_invalidos'], 0)
        self.assertEqual(list(self.df.columns),
                         ['latitud','longitud','tipo_riesgo','fila_excel'])

    def test_utm_usa_metros(self):
        projected, epsg, _, to_geo = proyeccion(self.df)
        self.assertEqual(epsg, 32614)
        lo, la = to_geo.transform(projected.x_m.iloc[0], projected.y_m.iloc[0])
        self.assertAlmostEqual(lo, self.df.longitud.iloc[0], places=6)
        self.assertAlmostEqual(la, self.df.latitud.iloc[0], places=6)

    def test_k_silueta_siempre_entre_1_y_num_coordenadas_unicas(self):
        p, *_ = proyeccion(self.df)
        k, scores = k_sugerido(p[p.tipo_riesgo == 'Accidentes'][['x_m','y_m']].to_numpy())
        self.assertGreaterEqual(k, 1)
        self.assertLess(k, 100)
        self.assertTrue(all(-1.001 <= s <= 1.001 for s in scores.values()))

    def test_cluster_geometria_y_exportacion(self):
        projected, epsg, _, to_geo = proyeccion(self.df)
        cps, zonas, hulls = ajustar_por_riesgo(projected, {'Accidentes': 6, 'Inseguridad': 4})
        self.assertEqual(len(cps), 150)
        self.assertEqual(len(zonas), 10)
        self.assertEqual(len(hulls), 10)
        self.assertEqual(sum(z['n_incidentes'] for z in zonas), 150)
        self.assertTrue(all(z['geometry'].area > 0 for z in zonas))
        self.assertTrue(all(z['radio_m'] >= 80 for z in zonas))
        for z in zonas:
            self.assertTrue(z['geometry'].covers(Point(z['centro_x_m'], z['centro_y_m'])))
        geo = features_geojson(zonas, to_geo)
        self.assertEqual(len(geo['features']), 10)
        self.assertEqual(geo['type'], 'FeatureCollection')

    def test_filtro_circular(self):
        sel, discarded = filtrar_area(self.df, 'Radio urbano', centro_lat=20.6838673,
                                      centro_lon=-101.3526233, radio_km=4.0)
        self.assertGreater(len(sel), 0)
        self.assertEqual(discarded + len(sel), 150)

    def test_geojson_limite(self):
        polygon = {'type':'Polygon','coordinates': [[[-101.40,20.60],[-101.30,20.60],
                              [-101.30,20.75],[-101.40,20.75],[-101.40,20.60]]]}
        boundary = leer_limite_geojson(json.dumps(polygon).encode())
        sel, discard = filtrar_area(self.df, 'Límite municipal (GeoJSON)', limite_geojson=boundary)
        self.assertEqual(discard + len(sel), 150)

    def test_empalmes_sin_doble_conteo_tres_riesgos(self):
        circles = [
            {'tipo_riesgo':'A','geometry':Point(0,0).buffer(100)},
            {'tipo_riesgo':'B','geometry':Point(50,0).buffer(100)},
            {'tipo_riesgo':'C','geometry':Point(25,25).buffer(100)},
        ]
        inter = superposiciones(circles, 1)
        self.assertTrue(any(e['n_tipos'] == 3 for e in inter))
        for i, a in enumerate(inter):
            for b in inter[i+1:]:
                self.assertLess(a['geometry'].intersection(b['geometry']).area, 0.0001)

    def test_varios_riesgos_tercero_sin_cambiar_codigo(self):
        p, *_ = proyeccion(self.df)
        s = p.iloc[:8].copy()
        s['tipo_riesgo']='Inundaciones'
        all_ = pd.concat([p,s], ignore_index=True)
        _, zon, _ = ajustar_por_riesgo(all_, {'Accidentes':3,'Inseguridad':2,'Inundaciones':1})
        self.assertEqual(len(zon), 6)

    def test_zip_qgis_y_manifestacion(self):
        projected, epsg, _, to_geo = proyeccion(self.df)
        cps, z, hulls = ajustar_por_riesgo(projected, {'Accidentes':4,'Inseguridad':3})
        overlays = superposiciones(z, 10)
        pkg = crear_paquete(df_original=self.df, clasificados=cps,
                            zonas=z, envolventes=hulls, empalmes=overlays,
                            to_geo=to_geo, epsg=epsg, contenido_entrada=self.raw,
                            config={'modo_area':'Sin filtro'}, calidad=self.info)
        import zipfile
        with zipfile.ZipFile(io.BytesIO(pkg)) as zip_:
            names=set(zip_.namelist())
            self.assertIn('zonas_circulares.geojson', names)
            self.assertIn('empalmes_multirriesgo.geojson', names)
            meta=json.loads(zip_.read('manifiesto_metodologico.json'))
            self.assertEqual(meta['filas_clasificadas'],150)
            self.assertEqual(meta['sistema_calculos'],'EPSG:32614')


if __name__ == '__main__':
    unittest.main()
