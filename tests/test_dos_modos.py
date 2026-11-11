"""Casos de regresión para la penalización multiplicativa y la extensión vial."""
import json
import unittest
import zipfile
from io import BytesIO

import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, Polygon

from src.cvrp import (leer_clientes, crear_nodos, resolver, matriz_geometrica,
                      CVRPError)
from src.cvrp_experimentos import (crear_circulos_empalmes, matriz_articulo,
                                  matriz_vial_experimental,cantidad_cruces)
from src.cvrp_export import zip_cvrp


class TestDosModos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.to_geo=Transformer.from_crs(32614,4326,always_xy=True)
        cls.to_m=Transformer.from_crs(4326,32614,always_xy=True)
        cls.origin=np.array(cls.to_m.transform(-101.35,20.68))

    def pts(self,xy):
        return np.array([self.origin+np.asarray(p,float) for p in xy])

    def circle(self,center,r):
        p=self.origin+np.asarray(center,float)
        return {'id_zona':'E001','riesgos':'Accidentes | Inseguridad',
            'centro_x_m':p[0], 'centro_y_m':p[1], 'radio_m':r,
            'geometry':Point(p).buffer(r,quad_segs=64)}

    def test_circulos_recubren_todos_vertices_del_empalme(self):
        x,y=self.origin
        poly=Polygon([(x+100,y+100),(x+200,y+100),(x+200,y+200),(x+100,y+200)])
        cc=crear_circulos_empalmes([{'id_empalme':'E7','geometry':poly,'riesgos':'A | B'}])
        self.assertEqual(len(cc),1)
        self.assertEqual(cc[0]['id_zona'],'E7')
        for p in poly.exterior.coords:
            self.assertLessEqual(Point(p).distance(Point(cc[0]['centro_x_m'],cc[0]['centro_y_m'])),cc[0]['radio_m']+1e-5)

    def test_multiplicativo_secante_sin_clientes_dentro(self):
        xy=self.pts([(0,0),(1000,0)])
        zone=self.circle((500,0),100)
        m=matriz_articulo(xy,self.to_geo,[zone],3.)
        self.assertEqual(m.cruces[0,1],1)
        self.assertEqual(m.arcos_penalizados[0,1],1)
        self.assertAlmostEqual(m.costo[0,1]/m.distancia[0,1],4.,places=6)
        self.assertGreater(m.exposicion[0,1],190)
        self.assertTrue(np.allclose(m.costo,m.costo.T))
        self.assertEqual(m.modo,'Artículo · Haversine y secantes')

    def test_endpoint_inside_exento_pero_cruce_contabilizado(self):
        xy=self.pts([(500,0),(1000,0)])
        m=matriz_articulo(xy,self.to_geo,[self.circle((500,0),100)],10.)
        self.assertEqual(m.cruces[0,1],1)
        self.assertEqual(m.arcos_penalizados[0,1],0)
        self.assertAlmostEqual(m.costo[0,1],m.distancia[0,1])

    def test_dos_zonas_penalizacion_no_se_satura_por_union(self):
        xy=self.pts([(0,0),(1000,0)])
        m=matriz_articulo(xy,self.to_geo,[self.circle((350,0),100),
                                              self.circle((700,0),100)],2.)
        self.assertEqual(m.arcos_penalizados[0,1],2)
        self.assertAlmostEqual(m.costo[0,1]/m.distancia[0,1],5.,places=5)

    def test_sin_cruce_ni_tangencia_costo_igual(self):
        xy=self.pts([(0,100),(1000,100)])
        m=matriz_articulo(xy,self.to_geo,[self.circle((500,0),100)],3.)
        self.assertEqual(m.arcos_penalizados[0,1],0)
        self.assertAlmostEqual(m.costo[0,1],m.distancia[0,1])

    def test_tres_heuristicas_en_dos_escenarios(self):
        xy=self.pts([(0,0),(150,0),(300,0),(450,0),(600,0),(720,0),(850,0)])
        latlon=[self.to_geo.transform(*x) for x in xy[1:]]
        cli=pd.DataFrame({'cliente':list('ABCDEF'),'latitud':[y for x,y in latlon],
            'longitud':[x for x,y in latlon],'demanda':[1,1,1,1,1,1]})
        circles=[self.circle((400,0),100)]
        zero=matriz_articulo(xy,self.to_geo,circles,0)
        pos=matriz_articulo(xy,self.to_geo,circles,4.)
        for method in ['Búsqueda local','Búsqueda tabú','Colonia de hormigas (ACO)']:
            for m in (zero,pos):
                with self.subTest(method=method,lmbd=float(m.costo.max())):
                    s=resolver(m,cli,2,3.,method,42,iterations=20)
                    self.assertEqual(sum(len(r) for r in s.rutas),6)
                    self.assertTrue(all(v<=3 for v in s.cargas))
                    self.assertTrue(cantidad_cruces(s.rutas,m)[0]>=0)

    def test_modo_vial_red_se_desvia(self):
        a=self.origin;b=a+np.array([1000.,0.]);c=a+np.array([0.,600.]);d=a+np.array([1000.,600.])
        coords=np.array([a,b])
        features=[]
        for p,q in [(a,b),(a,c),(c,d),(d,b)]:
            features.append({'type':'Feature','properties':{},'geometry':{
                'type':'LineString','coordinates':[list(self.to_geo.transform(*p)),
                                                   list(self.to_geo.transform(*q))]}})
        roads=json.dumps({'type':'FeatureCollection','features':features}).encode()
        circ=[self.circle((500,0),100)]
        m0=matriz_vial_experimental(coords,roads,self.to_m,circ,0,max_snap_m=20)
        m1=matriz_vial_experimental(coords,roads,self.to_m,circ,20,max_snap_m=20)
        self.assertGreater(m1.distancia[0,1],m0.distancia[0,1])
        self.assertLess(m1.exposicion[0,1],m0.exposicion[0,1])
        self.assertIn('aditiva',m1.descripcion_objetivo)

    def test_exporta_tablas_circulos_y_metadata(self):
        xy=self.pts([(0,0),(150,0),(300,0)])
        ll=[self.to_geo.transform(*x) for x in xy[1:]]
        cli=pd.DataFrame({'cliente':['a','b'],'latitud':[x[1] for x in ll],
            'longitud':[x[0] for x in ll],'demanda':[1,1]})
        circs=[self.circle((200,0),80)]
        model=matriz_articulo(xy,self.to_geo,circs,1.)
        s=resolver(model,cli,1,2,'Búsqueda local',42,20)
        z=zip_cvrp({'Local | Con penalización':s},{'Local | Con penalización':model},
            cli,self.to_geo,{'mode':'A'},'abc','def',metadata={'Local | Con penalización':{
            'tecnica':'Búsqueda local','escenario':'Con penalización','lambda_optimizada':1}},circulos=circs)
        with zipfile.ZipFile(BytesIO(z)) as f:
            self.assertIn('circulos_empalmes_o_zonas.geojson',f.namelist())
            self.assertIn('comparacion_heuristicas.csv',f.namelist())
            self.assertIn('matriz_OD_con_penalizacion.csv',f.namelist())
            self.assertEqual(json.loads(f.read('manifiesto_cvrp.json'))['modo_experimento'],'A')

    def test_150_clientes_aceptados(self):
        from pathlib import Path
        p=Path(__file__).resolve().parents[1]/'data'/'clientes_150_simulados_irapuato.xlsx'
        d=leer_clientes(p.read_bytes(),p.name)
        self.assertEqual(len(d),150)

if __name__=='__main__':
    unittest.main()
