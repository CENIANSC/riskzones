"""Pruebas offline para exportar OSMnx respetando sentidos y geometrías."""
import json
import unittest
from unittest.mock import patch
import networkx as nx
from shapely.geometry import LineString
from src.red_vial_osm import exportar_grafo_osmnx, descargar_red_osm
from src.cvrp import construir_grafo_vial, CVRPError
from pyproj import Transformer

class TestOSM(unittest.TestCase):
    def setUp(self):
        self.G=nx.MultiDiGraph()
        self.G.add_node(1,x=-101.35,y=20.68)
        self.G.add_node(2,x=-101.349,y=20.68)
        self.G.add_node(3,x=-101.349,y=20.681)
        self.G.add_edge(1,2,key=0,geometry=LineString([(-101.349,20.68),(-101.3495,20.6801),(-101.35,20.68)]),name='Eje 1')
        self.G.add_edge(2,1,key=0,geometry=LineString([(-101.35,20.68),(-101.3495,20.6801),(-101.349,20.68)]))
        self.G.add_edge(2,3,key=0)
        self.t=Transformer.from_crs('EPSG:4326','EPSG:32614',always_xy=True)

    def test_directed_segments_and_shape(self):
        blob,meta=exportar_grafo_osmnx(self.G,centro=(20.68,-101.35),radio_m=2000,fecha_utc='2026-11-11T00:00:00Z')
        data=json.loads(blob)
        self.assertEqual(meta['arcos_dirigidos'],3)
        self.assertEqual(data['type'],'FeatureCollection')
        self.assertTrue(all(f['properties']['oneway']=='yes' for f in data['features']))
        arc=data['features'][0]['geometry']['coordinates']
        self.assertEqual(arc[0],[-101.35,20.68]); self.assertEqual(arc[-1],[-101.349,20.68])
        graph=construir_grafo_vial(blob,self.t)
        a=(round(self.t.transform(-101.35,20.68)[0],1),round(self.t.transform(-101.35,20.68)[1],1))
        b=(round(self.t.transform(-101.349,20.68)[0],1),round(self.t.transform(-101.349,20.68)[1],1))
        self.assertTrue(nx.has_path(graph,a,b));self.assertTrue(nx.has_path(graph,b,a))

    def test_one_way(self):
        H=nx.MultiDiGraph()
        for n in [1,2]:H.add_node(n,**self.G.nodes[n])
        H.add_edge(1,2,key=0)
        blob,_=exportar_grafo_osmnx(H,centro=(20.68,-101.35),radio_m=1500)
        graph=construir_grafo_vial(blob,self.t)
        self.assertEqual(graph.number_of_edges(),1)

    def test_input(self):
        with self.assertRaises(CVRPError):descargar_red_osm(20.68,-101.35,10000)

if __name__=='__main__':unittest.main()
