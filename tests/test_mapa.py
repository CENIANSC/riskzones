"""Regresión: el mapa utiliza calles OSM y no solicita clave de CARTO."""
from pathlib import Path
import unittest
from src.analysis import leer_excel, proyeccion, ajustar_por_riesgo, superposiciones
from src.visualizacion import mapa
from src.cvrp_experimentos import crear_circulos_empalmes

ROOT = Path(__file__).resolve().parents[1]

class TestMapaBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        df, _ = leer_excel((ROOT / 'data' / 'riesgos_ejemplo_irapuato.xlsx').read_bytes())
        projected, _, _, to_geo = proyeccion(df)
        puntos, zonas, envolventes = ajustar_por_riesgo(projected, {'Accidentes': 4, 'Inseguridad': 3})
        cls.params = dict(puntos=puntos, zonas=zonas, envolventes=envolventes,
                          empalmes=superposiciones(zonas), to_geo=to_geo)

    def test_osm_carga_caminos_sin_carto(self):
        m, _ = mapa(**self.params)
        html = m.get_root().render()
        self.assertIn('tile.openstreetmap.org', html)
        self.assertIn('OpenStreetMap', html)
        self.assertNotIn('basemaps.cartocdn.com', html)
        self.assertNotIn('CartoDB positron', html)
        self.assertIn('Empalmes (2+ riesgos)', html)

    def test_circulos_finales_en_mapa_principal(self):
        params = dict(self.params)
        params['empalmes'] = params['empalmes'] or []
        # Capa debe dibujarse en el mapa principal si hay empalmes.
        m, _ = mapa(**params)
        html = m.get_root().render()
        if crear_circulos_empalmes(params['empalmes']):
            self.assertIn('C\\u00cdRCULOS DE CONFLICTO', html)
            self.assertIn('Centros y radios de conflicto', html)
            self.assertIn('dashArray', html)

if __name__ == '__main__':
    unittest.main()
