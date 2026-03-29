"""
Tests para la extracción y validación de estructura accionaria.

Estos tests verifican que:
1. La extracción regex captura correctamente diferentes formatos de accionistas
2. NO se asume distribución igualitaria cuando faltan datos
3. Los indicadores de confiabilidad funcionan correctamente
4. Las validaciones detectan errores en sumas de porcentajes/acciones
"""

import pytest
import sys
import os

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.service.openai import (
    _extract_socios_fundadores_fallback,
    _validate_estructura_accionaria
)


class TestExtractSociosFundadoresFallback:
    """Tests para la función _extract_socios_fundadores_fallback"""
    
    def test_extrae_socios_con_acciones_explicitas(self):
        """Debe extraer correctamente socios con acciones explícitas"""
        texto = """
        CAPITAL SOCIAL Y ACCIONES
        
        El capital social es de $100,000.00 dividido en 100 acciones.
        
        ARTURO PONS AGUIRRE SUSCRIBE 45 ACCIONES
        ESTEBAN SANTIAGO VARELA VEGA SUSCRIBE 35 ACCIONES
        ALEJANDRO PÉREZ ONTIVEROS SUSCRIBE 15 ACCIONES
        RICARDO ELIAS FERNÁNDEZ SUSCRIBE 5 ACCIONES
        """
        
        socios = _extract_socios_fundadores_fallback(texto, total_acciones=100)
        
        assert len(socios) == 4
        
        # Verificar que los porcentajes son correctos (no igualitarios)
        nombres_acciones = {s["nombre"]: s["acciones"] for s in socios}
        assert nombres_acciones.get("ARTURO PONS AGUIRRE") == 45
        assert nombres_acciones.get("ESTEBAN SANTIAGO VARELA VEGA") == 35
        assert nombres_acciones.get("ALEJANDRO PÉREZ ONTIVEROS") == 15
        assert nombres_acciones.get("RICARDO ELIAS FERNÁNDEZ") == 5
        
        # Verificar porcentajes calculados
        porcentajes = {s["nombre"]: s["porcentaje"] for s in socios}
        assert porcentajes.get("ARTURO PONS AGUIRRE") == 45.0
        assert porcentajes.get("ESTEBAN SANTIAGO VARELA VEGA") == 35.0
        assert porcentajes.get("ALEJANDRO PÉREZ ONTIVEROS") == 15.0
        assert porcentajes.get("RICARDO ELIAS FERNÁNDEZ") == 5.0
    
    def test_no_asume_distribucion_igualitaria(self):
        """NO debe asumir distribución igualitaria para socios sin datos"""
        texto = """
        COMPARECEN LOS SEÑORES JUAN PÉREZ GARCÍA Y MARÍA LÓPEZ HERNÁNDEZ,
        quienes constituyen la sociedad con un capital de $1,000,000.00
        """
        
        socios = _extract_socios_fundadores_fallback(texto, total_acciones=1000)
        
        # Solo debe extraer nombres, sin acciones ni porcentajes inventados
        for socio in socios:
            # Los socios sin datos explícitos deben tener _requiere_verificacion=True
            if socio.get("_confiabilidad", 0) < 0.5:
                assert socio.get("_requiere_verificacion") == True
                # NO deben tener porcentajes inventados de 50%
                assert socio.get("porcentaje") is None or socio.get("acciones") is not None
    
    def test_extrae_porcentajes_explicitos(self):
        """Debe extraer porcentajes cuando están explícitos en el texto"""
        texto = """
        DISTRIBUCIÓN DEL CAPITAL:
        
        CARLOS MARTÍNEZ RUIZ, representativas del 60% del capital social.
        SOFÍA GONZÁLEZ LUNA, representativas del 40% del capital social.
        """
        
        socios = _extract_socios_fundadores_fallback(texto)
        
        assert len(socios) >= 2
        # Verificar que al menos encontró los nombres y porcentajes
        nombres = [s["nombre"] for s in socios]
        porcentajes = [s["porcentaje"] for s in socios if s.get("porcentaje")]
        
        # Debe encontrar ambos nombres (pueden tener variaciones)
        assert any("CARLOS" in n and "MARTÍNEZ" in n for n in nombres)
        assert any("SOFÍA" in n or "SOFIA" in n for n in nombres)
        # Los porcentajes deben ser 60 y 40
        assert 60.0 in porcentajes
        assert 40.0 in porcentajes
    
    def test_patron_aporta_acciones(self):
        """Debe extraer usando patrón 'APORTA X ACCIONES'"""
        texto = """
        FERNANDO SÁNCHEZ TORRES APORTA 300 ACCIONES SERIE A.
        GUADALUPE RAMÍREZ VEGA APORTA 200 ACCIONES SERIE A.
        """
        
        socios = _extract_socios_fundadores_fallback(texto, total_acciones=500)
        
        assert len(socios) >= 2
        # Verificar que se encontraron las acciones correctas
        acciones = [s["acciones"] for s in socios if s.get("acciones")]
        nombres = [s["nombre"] for s in socios]
        
        assert 300 in acciones
        assert 200 in acciones
        assert any("FERNANDO" in n for n in nombres)
        assert any("GUADALUPE" in n for n in nombres)
    
    def test_detecta_persona_moral(self):
        """Debe detectar correctamente personas morales"""
        texto = """
        INVERSIONES ABC S.A. DE C.V. SUSCRIBE 600 ACCIONES.
        JUAN PÉREZ GARCÍA SUSCRIBE 400 ACCIONES.
        """
        
        socios = _extract_socios_fundadores_fallback(texto, total_acciones=1000)
        
        # Nota: La detección de tipo moral se hace en _validate_estructura_accionaria
        # Aquí solo verificamos que se extraigan correctamente
        acciones = [s["acciones"] for s in socios if s.get("acciones")]
        assert len(socios) >= 1
        # Al menos debe capturar las acciones
        assert 600 in acciones or 400 in acciones
    
    def test_confiabilidad_alta_con_datos_completos(self):
        """Socios con datos completos deben tener alta confiabilidad"""
        texto = """
        ROBERTO DÍAZ CAMPOS SUSCRIBE 50 ACCIONES representativas del 50%.
        LAURA MENDOZA RÍOS SUSCRIBE 50 ACCIONES representativas del 50%.
        """
        
        socios = _extract_socios_fundadores_fallback(texto, total_acciones=100)
        
        # Debe encontrar socios con alta confiabilidad
        assert len(socios) >= 2
        # Al menos algunos deben tener alta confiabilidad
        confiabilidades = [s.get("_confiabilidad", 0) for s in socios]
        assert max(confiabilidades) >= 0.9
    
    def test_confiabilidad_baja_sin_datos_numericos(self):
        """Socios sin datos numéricos deben tener baja confiabilidad"""
        texto = """
        LOS SEÑORES PEDRO ROJAS VARGAS Y ANA CASTRO MORA comparecen ante el notario
        """
        
        socios = _extract_socios_fundadores_fallback(texto)
        
        for socio in socios:
            if socio.get("acciones") is None and socio.get("porcentaje") is None:
                assert socio.get("_confiabilidad", 1) < 0.5
                assert socio.get("_requiere_verificacion") == True


class TestValidateEstructuraAccionaria:
    """Tests para la función _validate_estructura_accionaria"""
    
    def test_valida_estructura_correcta(self):
        """Estructura con 100% de porcentajes debe ser válida"""
        data = {
            "total_acciones": 100,
            "estructura_accionaria": [
                {"nombre": "ARTURO PONS AGUIRRE", "acciones": 60, "porcentaje": 60.0},
                {"nombre": "ESTEBAN VARELA VEGA", "acciones": 40, "porcentaje": 40.0}
            ]
        }
        
        result = _validate_estructura_accionaria(data)
        
        assert result["_porcentajes_validos"] == True
        assert result["_suma_porcentajes"] == 100.0
        assert result["_estructura_confiabilidad"] == 1.0
        assert result["_estructura_accionaria_status"] == "Verificada"
    
    def test_detecta_porcentajes_incorrectos(self):
        """Debe detectar cuando porcentajes no suman 100%"""
        data = {
            "estructura_accionaria": [
                {"nombre": "ARTURO PONS AGUIRRE", "porcentaje": 45.0},
                {"nombre": "ESTEBAN VARELA VEGA", "porcentaje": 35.0},
                {"nombre": "PATRICIA LUNA GARCIA", "porcentaje": 15.0}
                # Falta 5% - solo suman 95%
            ]
        }
    
        result = _validate_estructura_accionaria(data)
        
        assert result["_porcentajes_validos"] == False
        assert result["_suma_porcentajes"] == 95.0
        assert "_alertas_accionarias" in result
        assert any("95.0%" in alerta for alerta in result["_alertas_accionarias"])
    
    def test_detecta_persona_moral_mayor_25(self):
        """Debe alertar sobre personas morales con >25%"""
        data = {
            "estructura_accionaria": [
                {"nombre": "HOLDING XYZ S.A. DE C.V.", "tipo": "moral", "porcentaje": 70.0},
                {"nombre": "JUAN PÉREZ", "tipo": "fisica", "porcentaje": 30.0}
            ]
        }
        
        result = _validate_estructura_accionaria(data)
        
        assert "_alertas_accionarias" in result
        assert any("perforación" in alerta.lower() for alerta in result["_alertas_accionarias"])
    
    def test_marca_accionistas_sin_datos(self):
        """Debe marcar accionistas sin datos numéricos para verificación"""
        data = {
            "estructura_accionaria": [
                {"nombre": "ARTURO PONS AGUIRRE", "acciones": 500, "porcentaje": 50.0},
                {"nombre": "ESTEBAN VARELA VEGA", "acciones": None, "porcentaje": None}  # Sin datos
            ]
        }
        
        result = _validate_estructura_accionaria(data)
        
        assert "_alertas_accionarias" in result
        assert any("MANUAL" in alerta.upper() for alerta in result["_alertas_accionarias"])
        assert result["_estructura_confiabilidad"] < 1.0
    
    def test_calcula_porcentaje_desde_acciones(self):
        """Debe calcular porcentaje cuando hay acciones pero no porcentaje"""
        data = {
            "total_acciones": 1000,
            "estructura_accionaria": [
                {"nombre": "ARTURO PONS AGUIRRE", "acciones": 600},  # Sin porcentaje
                {"nombre": "ESTEBAN VARELA VEGA", "acciones": 400}   # Sin porcentaje
            ]
        }
        
        result = _validate_estructura_accionaria(data)
        
        estructura = result["estructura_accionaria"]
        socio_a = next(s for s in estructura if s["nombre"] == "ARTURO PONS AGUIRRE")
        socio_b = next(s for s in estructura if s["nombre"] == "ESTEBAN VARELA VEGA")
        
        assert socio_a["porcentaje"] == 60.0
        assert socio_b["porcentaje"] == 40.0
    
    def test_detecta_discrepancia_acciones(self):
        """Debe detectar cuando suma de acciones no coincide con total"""
        data = {
            "total_acciones": 1000,
            "estructura_accionaria": [
                {"nombre": "ARTURO PONS AGUIRRE", "acciones": 600, "porcentaje": 60.0},
                {"nombre": "ESTEBAN VARELA VEGA", "acciones": 300, "porcentaje": 30.0}
                # Solo suman 900 acciones, faltan 100
            ]
        }
        
        result = _validate_estructura_accionaria(data)
        
        assert result["_acciones_validas"] == False
        assert result["_suma_acciones"] == 900
        assert "_alertas_accionarias" in result
    
    def test_usa_fallback_cuando_estructura_vacia(self):
        """Debe usar fallback regex cuando no hay estructura"""
        data = {
            "total_acciones": 100,
            "estructura_accionaria": []
        }
        text_ocr = """
        MIGUEL ÁNGEL TORRES SUSCRIBE 70 ACCIONES
        PATRICIA LUNA GARCÍA SUSCRIBE 30 ACCIONES
        """
        
        result = _validate_estructura_accionaria(data, text_ocr)
        
        assert result.get("_estructura_extraida_por_fallback") == True
        assert len(result["estructura_accionaria"]) == 2
    
    def test_autodetecta_tipo_persona(self):
        """Debe auto-detectar tipo de persona basado en nombre"""
        data = {
            "estructura_accionaria": [
                {"nombre": "GRUPO INDUSTRIAL S.A. DE C.V.", "porcentaje": 60.0},
                {"nombre": "PROMOTORA BANCOMEXT S.C.", "porcentaje": 20.0},
                {"nombre": "JUAN CARLOS RAMÍREZ", "porcentaje": 20.0}
            ]
        }
        
        result = _validate_estructura_accionaria(data)
        
        estructura = result["estructura_accionaria"]
        grupo = next(s for s in estructura if "GRUPO INDUSTRIAL" in s["nombre"])
        promotora = next(s for s in estructura if "PROMOTORA" in s["nombre"])
        juan = next(s for s in estructura if "JUAN CARLOS" in s["nombre"])
        
        assert grupo["tipo"] == "moral"
        assert promotora["tipo"] == "moral"
        assert juan["tipo"] == "fisica"


class TestCasosRealesProblematicos:
    """Tests basados en casos reales que causaron errores"""
    
    def test_capital_x_distribucion_desigual(self):
        """Reproduce el error de Capital X donde se infirió 25% igualitario"""
        texto = """
        ACTA CONSTITUTIVA DE SOLUCIONES CAPITAL X S.A. DE C.V.
        
        CAPITAL SOCIAL: $100,000.00 (CIEN MIL PESOS 00/100 M.N.)
        DIVIDIDO EN 100 (CIEN) ACCIONES
        
        ESTRUCTURA DE SUSCRIPCIÓN:
        - ARTURO PONS AGUIRRE SUSCRIBE 45 ACCIONES
        - ESTEBAN SANTIAGO VARELA VEGA SUSCRIBE 35 ACCIONES
        - ALEJANDRO PÉREZ ONTIVEROS SUSCRIBE 15 ACCIONES
        - RICARDO ELIAS FERNÁNDEZ SUSCRIBE 5 ACCIONES
        """
        
        data = {"estructura_accionaria": [], "total_acciones": 100}
        result = _validate_estructura_accionaria(data, texto)
        
        estructura = result["estructura_accionaria"]
        
        # Verificar que NO se asignó 25% igualitario
        for socio in estructura:
            assert socio["porcentaje"] != 25.0, \
                f"ERROR: {socio['nombre']} tiene 25% cuando debería tener valor real"
        
        # Verificar distribución correcta
        porcentajes = {s["nombre"]: s["porcentaje"] for s in estructura}
        assert porcentajes.get("ARTURO PONS AGUIRRE") == 45.0
        assert porcentajes.get("ESTEBAN SANTIAGO VARELA VEGA") == 35.0
        assert porcentajes.get("ALEJANDRO PÉREZ ONTIVEROS") == 15.0
        assert porcentajes.get("RICARDO ELIAS FERNÁNDEZ") == 5.0
    
    def test_almirante_capital_sin_distribucion_explicita(self):
        """Caso donde no hay distribución explícita - NO debe inventar"""
        texto = """
        ACTA CONSTITUTIVA DE ALMIRANTE CAPITAL S.A. DE C.V.
        
        COMPARECEN LOS SEÑORES JUAN PÉREZ Y MARÍA LÓPEZ,
        quienes declaran constituir una sociedad mercantil con
        un capital social de $1,000,000.00 dividido en 1,000 acciones.
        """
        
        data = {"estructura_accionaria": [], "total_acciones": 1000}
        result = _validate_estructura_accionaria(data, texto)
        
        estructura = result["estructura_accionaria"]
        
        # La salida simplificada solo incluye nombre/tipo/porcentaje,
        # así que verificamos a nivel de resultado global.
        # Socios sin distribución explícita → baja confiabilidad
        for socio in estructura:
            # NO debe tener 50% inventado (distribución igualitaria)
            assert socio.get("porcentaje") is None or socio["porcentaje"] != 50.0
        
        # La estructura debe indicar baja confiabilidad
        assert result["_estructura_confiabilidad"] < 0.5
        assert result["_estructura_accionaria_status"] in [
            "Requiere_Verificacion", "No_Confiable", "Estructura_Implicita"
        ]
    
    def test_extraccion_tabla_ocr_capital_x(self):
        """Test específico para extracción de tabla OCR linearizada"""
        from api.service.openai import _extract_tabla_accionistas_estructurada
        
        # Formato OCR típico de tabla de accionistas
        texto = """ACCIONISTAS
ACCIONES
VALOR
ARTURO PONS AGUIRRE
45
$45,000.00
ESTEBAN SANTIAGO VARELA
VEGA
35
$35,000.00
ALEJANDRO PEREZ ONTIVEROS
15
$15,000.00
RICARDO ELIAS FERNANDEZ
5
$5,000.00
TOTAL
100
$100,000.00"""
        
        socios = _extract_tabla_accionistas_estructurada(texto)
        
        # Debe extraer exactamente 4 accionistas
        assert len(socios) == 4, f"Esperado 4 socios, encontrados {len(socios)}"
        
        # Verificar acciones correctas
        acciones_por_nombre = {s["nombre"].upper(): s["acciones"] for s in socios}
        
        assert acciones_por_nombre.get("ARTURO PONS AGUIRRE") == 45
        assert acciones_por_nombre.get("ESTEBAN SANTIAGO VARELA VEGA") == 35
        assert acciones_por_nombre.get("ALEJANDRO PEREZ ONTIVEROS") == 15
        assert acciones_por_nombre.get("RICARDO ELIAS FERNANDEZ") == 5
        
        # Verificar que la suma es 100
        suma = sum(s["acciones"] for s in socios)
        assert suma == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
