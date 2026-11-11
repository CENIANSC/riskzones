from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_textos_de_encabezado():
    s=(ROOT/'app.py').read_text()
    for text in ('Riesgos urbanos|K-Means y CVRP', 'Daniel A. Aguirre Ibarra',
                 'Doctorado en Logística y Dirección de la Cadena de Suministro', 'UPAEP'):
        assert text in s
    assert 'Paquete integrado 1.3.5 ·' not in s
    assert 'st.caption(f"Versión {APP_VERSION}' not in s

def test_configuracion_fija_y_construccion_de_empalmes():
    s=(ROOT/'app.py').read_text()
    assert 'modo = "Radio urbano"' in s
    assert 'base_empalmes = envolventes' in s
    assert 'forma_empalmes = "Envolventes convexas"' in s
    assert '"Círculos K-Means (exploratorio)"' not in s
    assert '"Sin filtro", "Radio urbano"' not in s
    assert 'st.caption("Los archivos que subes se procesan en memoria' not in s

def test_cvrp_solo_empalmes():
    s=(ROOT/'src'/'cvrp_ui.py').read_text()
    assert 'Círculos individuales K-Means (EXTENSIÓN, no artículo)' not in s
    assert "alcance='Círculos derivados de empalmes multirriesgo'" in s
