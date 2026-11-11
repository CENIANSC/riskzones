"""Regresión de compatibilidad de firma sin importar Streamlit."""
import ast
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_interface_supports_all_app_parameters():
    tree = ast.parse((ROOT/'src'/'cvrp_ui.py').read_text(encoding='utf-8'))
    fn = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name=='bloque_cvrp')
    arguments = {x.arg for x in fn.args.kwonlyargs}
    assert {'zonas','empalmes','to_m','to_geo','epsg',
            'risk_bytes','config_k','forma_empalmes'} <= arguments

def test_app_rejects_old_interface():
    app = (ROOT/'app.py').read_text(encoding='utf-8')
    assert 'VERSION_INTERFAZ_CVRP' in app
    assert 'inspect.signature' in app
    assert 'except TypeError' in app
    assert "1.3.3" in app
    ui = (ROOT/'src'/'cvrp_ui.py').read_text(encoding='utf-8')
    assert "VERSION_INTERFAZ_CVRP = '1.3.3'" in ui
