"""
Test de las funciones mejoradas de extracción de estructura accionaria.
Verifica:
1. Tabla OCR multi-línea (caso Avanza Sólido - Martha González)
2. Comparecientes sin tabla (caso Almirante Capital)
3. Texto libre con patrones de suscripción
"""
import json
import sys
sys.path.insert(0, ".")

from api.service.openai import (
    _extract_accionistas_multiseccion,
    _extract_tabla_accionistas_estructurada,
    _extract_socios_fundadores_fallback,
)


def test_tabla_multilinea():
    """Caso Avanza Sólido: nombre partido en 2 líneas por OCR."""
    print("=" * 60)
    print("TEST 1: Tabla OCR multi-línea (Avanza Sólido)")
    print("=" * 60)
    
    texto_tabla = """
CAPITAL SOCIAL QUEDA SUSCRITO DE LA SIGUIENTE MANERA

ACCIONISTAS ACCIONES VALOR
OSCAR GERMAN CRUZ
CAMARENA
100
$100,000.00
ERIKA GORDILLO
MORENO
100
$100,000.00
MARTHA GONZALEZ
GARCIA
100
$100,000.00
TOTAL
300
$300,000.00

SEGUNDO: ADMINISTRACION
"""
    socios_tabla = _extract_tabla_accionistas_estructurada(texto_tabla.upper())
    
    print(f"Socios encontrados: {len(socios_tabla)}")
    for s in socios_tabla:
        print(f"  - {s['nombre']}: acciones={s.get('acciones')}, patron={s.get('_patron')}")
    
    assert len(socios_tabla) >= 3, f"ERROR: Esperados 3 socios, encontrados {len(socios_tabla)}"
    
    nombres = [s["nombre"].upper() for s in socios_tabla]
    assert any("MARTHA" in n and "GONZALEZ" in n for n in nombres), \
        f"ERROR: Martha González no encontrada. Nombres: {nombres}"
    
    print("✓ PASÓ: 3 socios encontrados incluyendo Martha González")
    print()


def test_comparecientes_sin_tabla():
    """Caso Almirante Capital: socios solo como comparecientes."""
    print("=" * 60)
    print("TEST 2: Comparecientes sin tabla (Almirante Capital)")
    print("=" * 60)
    
    texto = """
ESCRITURA PUBLICA NUMERO 27,883

Ante mi, el Notario Público, COMPARECEN:

El Señor RODRIGO ALONSO SALUM, mexicano, mayor de edad,
con domicilio en la ciudad de Monterrey, Nuevo León,
quien se identifica con credencial de elector.

El Señor FERNANDO ALONSO VEGA, mexicano, mayor de edad,
con domicilio en la ciudad de San Pedro Garza García,
quien se identifica con pasaporte vigente.

DECLARAN los comparecientes que es su voluntad constituir
una sociedad mercantil conforme a los siguientes:

ESTATUTOS SOCIALES

CLAUSULA PRIMERA: DENOMINACION
La Sociedad se denomina ALMIRANTE CAPITAL, Sociedad Anónima
Promotora de Inversión de Capital Variable.

CLAUSULA CUARTA: CAPITAL SOCIAL
El capital social mínimo fijo de la Sociedad es de $50,000.00
(CINCUENTA MIL PESOS 00/100 MONEDA NACIONAL), representado 
por 50,000 (CINCUENTA MIL) acciones ordinarias nominativas,
Serie A, con valor nominal de $1.00 (UN PESO) cada una.
"""
    socios, tipo = _extract_accionistas_multiseccion(texto)
    
    print(f"Tipo extracción: {tipo}")
    print(f"Socios encontrados: {len(socios)}")
    for s in socios:
        acc = s.get("acciones")
        sec = s.get("_seccion_origen", "?")
        pat = s.get("_patron_usado", "?")
        nota = s.get("_nota", "")
        print(f"  - {s['nombre']}: acciones={acc}, sección={sec}, patrón={pat}")
        if nota:
            print(f"    nota: {nota}")
    
    assert len(socios) >= 2, f"ERROR: Esperados 2 socios, encontrados {len(socios)}"
    assert tipo == "estructura_implicita", f"ERROR: Tipo esperado 'estructura_implicita', obtenido '{tipo}'"
    
    nombres = [s["nombre"].upper() for s in socios]
    assert any("RODRIGO" in n for n in nombres), "ERROR: Rodrigo Alonso no encontrado"
    assert any("FERNANDO" in n for n in nombres), "ERROR: Fernando Alonso no encontrado"
    
    print("✓ PASÓ: 2 comparecientes identificados como estructura implícita")
    print()


def test_texto_libre_suscribe():
    """Socios mencionados en texto libre con patrón de suscripción."""
    print("=" * 60)
    print("TEST 3: Texto libre - 'NOMBRE suscribe N acciones'")
    print("=" * 60)
    
    texto = """
ESCRITURA PUBLICA NUMERO 5,432

Ante mi COMPARECEN los señores JUAN PEREZ GARCIA y MARIA LOPEZ HERNANDEZ.

DECLARAN que constituyen EJEMPLO S.A. DE C.V.

CLAUSULA CUARTA: CAPITAL SOCIAL
El capital social es de $200,000.00 dividido en 200 acciones.

CLAUSULA TRANSITORIA:
El señor JUAN PEREZ GARCIA suscribe 120 acciones ordinarias
Serie A, pagando en su totalidad su valor nominal.

La señora MARIA LOPEZ HERNANDEZ suscribe 80 acciones ordinarias
Serie A, pagando en su totalidad su valor nominal.
"""
    socios, tipo = _extract_accionistas_multiseccion(texto, total_acciones=200)
    
    print(f"Tipo extracción: {tipo}")
    print(f"Socios encontrados: {len(socios)}")
    for s in socios:
        acc = s.get("acciones")
        pct = s.get("porcentaje")
        pat = s.get("_patron_usado", "?")
        print(f"  - {s['nombre']}: acciones={acc}, porcentaje={pct}, patrón={pat}")
    
    assert len(socios) >= 2, f"ERROR: Esperados 2 socios, encontrados {len(socios)}"
    
    socios_con_acciones = [s for s in socios if s.get("acciones") is not None]
    assert len(socios_con_acciones) >= 2, "ERROR: No todos los socios tienen acciones"
    
    print("✓ PASÓ: Socios extraídos de texto libre con acciones")
    print()


def test_fallback_completo():
    """Test del fallback completo con búsqueda multi-sección."""
    print("=" * 60)
    print("TEST 4: Fallback completo con multi-sección")
    print("=" * 60)
    
    texto = """
ESCRITURA PUBLICA NUMERO 12345

ANTE MI EL NOTARIO COMPARECEN:
El Señor CARLOS MARTINEZ RIVAS, mexicano, con domicilio en CDMX.
La Señora ANA GARCIA TORRES, mexicana, con domicilio en CDMX.

DECLARAN que constituyen una sociedad.

CAPITAL SOCIAL: $100,000.00 dividido en 100 acciones Serie A.

El señor CARLOS MARTINEZ RIVAS aporta la cantidad de $60,000.00
correspondiente a 60 acciones ordinarias.

La señora ANA GARCIA TORRES aporta la cantidad de $40,000.00
correspondiente a 40 acciones ordinarias.
"""
    socios = _extract_socios_fundadores_fallback(texto, total_acciones=100)
    
    print(f"Socios encontrados: {len(socios)}")
    for s in socios:
        acc = s.get("acciones")
        pct = s.get("porcentaje")
        pat = s.get("_patron_usado", "?")
        print(f"  - {s['nombre']}: acciones={acc}, porcentaje={pct}, patrón={pat}")
    
    socios_con_datos = [s for s in socios if s.get("acciones") is not None]
    print(f"Socios con datos: {len(socios_con_datos)}/{len(socios)}")
    
    print("✓ PASÓ: Fallback completo ejecutado")
    print()


if __name__ == "__main__":
    test_tabla_multilinea()
    test_comparecientes_sin_tabla()
    test_texto_libre_suscribe()
    test_fallback_completo()
    
    print("=" * 60)
    print("TODOS LOS TESTS PASARON ✓")
    print("=" * 60)
