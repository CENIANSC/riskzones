import json
import unittest
from io import BytesIO
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point

from src.cvrp import (leer_clientes, crear_nodos, matriz_geometrica,matriz_vial,
                      resolver, CVRPError, unir_zonas_riesgo, evaluar)

class TestCVRP(unittest.TestCase):
    def setUp(self):
        self.client=pd.DataFrame({
            'cliente':['A','B','C','D','E','F'],
            'latitud':[20.680,20.681,20.682,20.683,20.6805,20.6812],
            'longitud':[-101.350,-101.351,-101.352,-101.353,-101.354,-101.355],
            'demanda':[2,3,4,3,2,1]
        })
        self.to_m=Transformer.from_crs(4326,32614,always_xy=True)
        self.coords=crear_nodos(self.client,20.679,-101.349,self.to_m)
        self.m=matriz_geometrica(self.coords)
    def test_lectura(self):
        dat=self.client.to_csv(index=False).encode()
        self.assertEqual(len(leer_clientes(dat,'clientes.csv')),6)
        with self.assertRaises(CVRPError):
            leer_clientes(b'lat,lon\n2,4','c.csv')
    def test_metodos_y_capacidad(self):
        for name in ['Búsqueda local','Búsqueda tabú','Colonia de hormigas (ACO)']:
            with self.subTest(name=name):
                sol=resolver(self.m,self.client,3,6,name,42,iterations=22)
                self.assertEqual(sum(map(len,sol.rutas)),6)
                self.assertTrue(all(c<=6 for c in sol.cargas))
                self.assertGreater(sol.distancia_m,0)
    def test_imposible(self):
        with self.assertRaises(CVRPError):
            resolver(self.m,self.client,2,5,'Búsqueda local')
    def test_risk_reduces_exposure_in_some_network(self):
        center=Point(self.coords[2]).buffer(130)
        m=matriz_geometrica(self.coords,center,penalizacion=3)
        self.assertTrue(np.all(m.costo>=m.distancia))
        self.assertTrue(np.any(m.exposicion>0))
        self.assertTrue(np.allclose(m.costo,m.distancia+3*m.exposicion))
    def test_oneway_and_real_road(self):
        # Artificial 4-way rectangle, segments with proper shared vertices in GeoJSON.
        coords=[(-101.350,20.680),(-101.349,20.680),(-101.349,20.681),(-101.350,20.681)]
        feat=[]
        for i in range(4):
            feat.append({'type':'Feature','properties':{},'geometry':{'type':'LineString','coordinates':[coords[i],coords[(i+1)%4]]}})
        data=json.dumps({'type':'FeatureCollection','features':feat}).encode()
        nodes=np.array([self.to_m.transform(*coords[i]) for i in (0,1,2)])
        mm=matriz_vial(nodes,data,self.to_m,max_snap_m=10)
        self.assertEqual(mm.modo,'Red vial GeoJSON')
        self.assertGreater(mm.distancia[0,2],100)
        self.assertGreater(len(mm.geometrias[0,2]),3)
    def test_risk_penalty_selects_detour_on_road_graph(self):
        to_geo=Transformer.from_crs(32614,4326,always_xy=True)
        x0,y0=self.to_m.transform(-101.35,20.68)
        a=(x0,y0);b=(x0+1000,y0);c=(x0,y0+600);d=(x0+1000,y0+600)
        parts=[[a,b],[a,c],[c,d],[d,b]]
        geo={'type':'FeatureCollection','features':[
            {'type':'Feature','properties':{},'geometry':{'type':'LineString',
            'coordinates':[list(to_geo.transform(*p)) for p in segment]}}
            for segment in parts]}
        coords=np.array([a,b],float)
        riesgo=Point(x0+500,y0).buffer(100)
        directo=matriz_vial(coords,json.dumps(geo).encode(),self.to_m,riesgo,penalizacion=0,max_snap_m=20)
        desvio=matriz_vial(coords,json.dumps(geo).encode(),self.to_m,riesgo,penalizacion=20,max_snap_m=20)
        self.assertLess(directo.distancia[0,1],desvio.distancia[0,1])
        self.assertGreater(directo.exposicion[0,1],180)
        self.assertLess(desvio.exposicion[0,1],1)

    def test_ghost_street_problem(self):
        segments=[{'type':'Feature','geometry':{'type':'LineString','coordinates':[[-101.35,20.68],[-101.349,20.68]]},'properties':{}},
                  {'type':'Feature','geometry':{'type':'LineString','coordinates':[[-101.348,20.681],[-101.348,20.682]]},'properties':{}}]
        data=json.dumps({'type':'FeatureCollection','features':segments}).encode()
        nodes=np.array([self.to_m.transform(-101.35,20.68), self.to_m.transform(-101.348,20.681)])
        with self.assertRaises(CVRPError):
            matriz_vial(nodes,data,self.to_m,max_snap_m=10)

if __name__=='__main__':
    unittest.main()
