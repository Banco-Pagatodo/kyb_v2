"""
engine.py — Orquestador de validación masiva contra portales gubernamentales.

Coordina la ejecución de los 3 módulos de validación:
  1. INE → Lista Nominal
  2. FIEL → Certificados SAT
  3. RFC → Validación RFC SAT

Flujo:
  1. Conectar a PostgreSQL y cargar datos de todas las empresas
  2. Para cada empresa, ejecutar los módulos habilitados
  3. Recopilar ResultadoPortal de cada consulta
  4. Generar reporte Excel/CSV
  5. Imprimir resumen en consola
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Sequence

from ..data_loader import cargar_expediente, listar_empresas
from ..text_utils import get_valor_str
from .base import ResultadoPortal, EstadoValidacion, logger
from .ine_validator import INEValidator
from .fiel_validator import FIELValidator
from .rfc_validator import RFCValidator
from .report import generar_reporte, imprimir_resumen


# ── Módulos disponibles ──
MODULOS_DISPONIBLES = {"ine", "fiel", "rfc"}


async def ejecutar_validacion_portales(
    *,
    modulos: set[str] | None = None,
    rfcs: list[str] | None = None,
    formato_reporte: str = "xlsx",
    directorio_reporte: str | Path | None = None,
    headless: bool = True,
) -> list[ResultadoPortal]:
    """
    Ejecuta la validación masiva contra portales gubernamentales.

    Args:
        modulos: Conjunto de módulos a ejecutar {'ine', 'fiel', 'rfc'}.
                 None = todos.
        rfcs: Lista de RFCs específicos a validar.
              None = todas las empresas en BD.
        formato_reporte: 'xlsx' o 'csv'
        directorio_reporte: Directorio para guardar el reporte
        headless: Si True, navegador sin ventana visible

    Returns:
        Lista de ResultadoPortal con todos los resultados
    """
    mods = (modulos or MODULOS_DISPONIBLES) & MODULOS_DISPONIBLES

    logger.info(
        f"Iniciando validación de portales — "
        f"Módulos: {', '.join(sorted(mods))} | "
        f"RFCs: {rfcs or 'TODAS'}"
    )

    # ── Cargar empresas ──
    empresas = await listar_empresas()

    if rfcs:
        rfcs_upper = {r.upper() for r in rfcs}
        empresas = [e for e in empresas if e["rfc"].upper() in rfcs_upper]

    if not empresas:
        logger.warning("No se encontraron empresas para validar")
        return []

    logger.info(f"Empresas a validar: {len(empresas)}")

    # ── Crear instancias de validadores ──
    validators: dict[str, Any] = {}
    if "ine" in mods:
        validators["ine"] = INEValidator()
    if "fiel" in mods:
        validators["fiel"] = FIELValidator()
    if "rfc" in mods:
        validators["rfc"] = RFCValidator()

    # ── Ejecutar validaciones ──
    todos_resultados: list[ResultadoPortal] = []

    for val_name, validator in validators.items():
        logger.info(f"═══ Módulo: {val_name.upper()} ═══")

        try:
            await validator.iniciar_navegador(headless=headless)

            for emp in empresas:
                rfc = emp["rfc"]
                nombre = emp.get("razon_social", rfc)
                empresa_id = emp["id"]

                try:
                    # Cargar expediente completo
                    expediente = await cargar_expediente(empresa_id)

                    # Preparar datos según el módulo
                    datos = _preparar_datos(val_name, expediente)

                    if datos is None:
                        # No hay datos para este módulo/empresa
                        resultado = ResultadoPortal(
                            modulo=validator.portal_nombre,
                            empresa=nombre,
                            rfc=rfc,
                            identificador="SIN_DATOS",
                            estado=EstadoValidacion.SIN_DATOS,
                            detalle=f"No hay datos de {val_name.upper()} para esta empresa",
                        )
                        todos_resultados.append(resultado)
                        logger.info(
                            f"  ⊘ {nombre} — Sin datos de {val_name.upper()}"
                        )
                        continue

                    # Ejecutar con reintentos
                    resultado = await validator.validar_con_reintentos(
                        datos=datos,
                        empresa=nombre,
                        rfc=rfc,
                    )
                    todos_resultados.append(resultado)

                    estado_icon = (
                        "✅" if resultado.estado and resultado.estado.value in (
                            "ENCONTRADO", "VIGENTE", "VALIDO"
                        ) else "❌"
                    )
                    logger.info(
                        f"  {estado_icon} {nombre} — "
                        f"{resultado.estado.value if resultado.estado else '?'}: "
                        f"{resultado.detalle[:80]}"
                    )

                except Exception as e:
                    logger.error(f"  ❌ Error procesando {nombre}: {e}")
                    todos_resultados.append(ResultadoPortal(
                        modulo=validator.portal_nombre,
                        empresa=nombre,
                        rfc=rfc,
                        identificador="ERROR",
                        estado=EstadoValidacion.ERROR,
                        detalle=f"Error interno: {e}",
                    ))

        finally:
            await validator.cerrar_navegador()

    # ── Generar reporte ──
    if todos_resultados:
        ruta_reporte = generar_reporte(
            todos_resultados,
            formato=formato_reporte,
            directorio=directorio_reporte,
        )
        imprimir_resumen(todos_resultados)
        logger.info(f"Reporte guardado: {ruta_reporte}")
    else:
        logger.warning("Sin resultados para reportar")

    return todos_resultados


def _preparar_datos(
    modulo: str,
    expediente: Any,
) -> dict[str, Any] | None:
    """
    Extrae los datos relevantes del expediente para el módulo indicado.

    Returns:
        dict con los campos necesarios o None si no hay datos.
    """
    docs = expediente.documentos

    if modulo == "ine":
        # Buscar datos de INE (front)
        ine = docs.get("ine") or docs.get("ine_front") or docs.get("INE")
        if not ine:
            return None
        return ine

    elif modulo == "fiel":
        # Buscar datos de FIEL
        fiel = docs.get("fiel") or docs.get("FIEL")
        if not fiel:
            return None
        return fiel

    elif modulo == "rfc":
        # Para RFC solo se requiere el RFC de la empresa (del registro)
        # Pasar datos de CSF si existen para comparar info adicional
        csf = docs.get("constancia_situacion_fiscal") or docs.get("csf") or {}
        return {
            "rfc": expediente.rfc,
            "razon_social": expediente.razon_social,
            **csf,
        }

    return None


async def ejecutar_modulo_individual(
    modulo: str,
    rfc: str,
    *,
    headless: bool = True,
) -> ResultadoPortal | None:
    """
    Ejecuta un solo módulo para un RFC específico.
    Útil para validaciones individuales desde la API.
    """
    if modulo not in MODULOS_DISPONIBLES:
        raise ValueError(f"Módulo no válido: {modulo}. Válidos: {MODULOS_DISPONIBLES}")

    resultados = await ejecutar_validacion_portales(
        modulos={modulo},
        rfcs=[rfc],
        headless=headless,
    )
    return resultados[0] if resultados else None
