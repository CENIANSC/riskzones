
"""El contrato mapa() debe aceptar todos los parámetros usados en app.py."""
import ast
import inspect
from pathlib import Path
from src import visualizacion
ROOT=Path(__file__).resolve().parents[1]

def test_firma_mapa_con_todos_los_argumentos():
    params=set(inspect.signature(visualizacion.mapa).parameters)
    assert {'puntos','zonas','envolventes','empalmes','to_geo',
            'mostrar_puntos','mostrar_hulls','mostrar_empalmes',
            'mostrar_circulos_conflicto','mostrar_centros_conflicto',
            'limite_original'} <= params
    assert visualizacion.VERSION_VISUALIZACION == '1.3.4'

def test_app_utiliza_preflight_y_control_del_error_de_mapa():
    app=(ROOT/'app.py').read_text(encoding='utf-8')
    assert '_REQUIRED_MAP_ARGS' in app
    assert '_visualizacion.mapa(' in app
    assert 'except TypeError:' in app
    assert '_map_version != _MAP_VERSION_EXPECTED' in app

def test_los_argumentos_reales_del_llamado_existen_en_la_funcion():
    tree=ast.parse((ROOT/'app.py').read_text(encoding='utf-8'))
    calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call)
           and isinstance(node.func,ast.Attribute) and node.func.attr=='mapa'
           and isinstance(node.func.value,ast.Name) and node.func.value.id=='_visualizacion']
    assert len(calls)==1
    names={arg.arg for arg in calls[0].keywords}
    assert names <= set(inspect.signature(visualizacion.mapa).parameters)
