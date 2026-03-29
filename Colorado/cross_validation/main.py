"""
Colorado — Agente de Validación Cruzada KYB
Punto de entrada: servidor API y CLI.
"""
from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

# ── Windows: forzar ProactorEventLoop para que Playwright pueda lanzar
#    subprocesos (asyncio.create_subprocess_exec).  Sin esto, uvicorn
#    con --reload usa SelectorEventLoop que NO soporta subprocesos. ──
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Forzar UTF-8 en stdout/stderr para soportar emojis en Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from fastapi import FastAPI
from contextlib import asynccontextmanager

from .core.database import get_pool, close_pool
from .core.config import API_HOST, API_PORT
from .api.router import router
from .services.engine import validar_empresa, validar_todas
from .services.data_loader import listar_empresas
from .services.report_generator import generar_reporte_texto, generar_resumen_global_texto


# ═══════════════════════════════════════════════════════════════════
#  Utilidades de salida
# ═══════════════════════════════════════════════════════════════════

def _output(texto: str, archivo: str | None = None) -> None:
    """Imprime a pantalla o escribe a archivo UTF-8."""
    if archivo:
        path = Path(archivo)
        path.write_text(texto, encoding="utf-8")
        print(f"Reporte guardado en: {path.resolve()}")
    else:
        print(texto)


def _parse_output_flag(args: list[str]) -> tuple[list[str], str | None]:
    """Extrae -o/--output de los argumentos. Devuelve (args_limpio, archivo)."""
    archivo = None
    clean: list[str] = []
    skip = False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a in ("-o", "--output") and i + 1 < len(args):
            archivo = args[i + 1]
            skip = True
        else:
            clean.append(a)
    return clean, archivo


# ═══════════════════════════════════════════════════════════════════
#  FastAPI Application
# ═══════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa y cierra la conexión a la BD."""
    await get_pool()
    yield
    await close_pool()


app = FastAPI(
    title="Colorado — Validación Cruzada KYB",
    description="Agente de validación cruzada de documentos corporativos mexicanos",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════

async def _cli_listar():
    """Lista todas las empresas."""
    await get_pool()
    try:
        empresas = await listar_empresas()
        print(f"\n{'RFC':<14} {'Razón Social':<35} {'Docs':>5}  Tipos")
        print("─" * 80)
        for emp in empresas:
            tipos = ", ".join(emp["doc_types"]) if emp["doc_types"] else "—"
            print(f"{emp['rfc']:<14} {emp['razon_social']:<35} {emp['total_docs']:>5}  {tipos}")
        print(f"\nTotal: {len(empresas)} empresas\n")
    finally:
        await close_pool()


async def _cli_validar(
    empresa_id: str,
    archivo: str | None = None,
    *,
    portales: bool = False,
    modulos_portales: set[str] | None = None,
    headless: bool = True,
):
    """Valida una empresa específica."""
    await get_pool()
    try:
        reporte = await validar_empresa(
            empresa_id,
            portales=portales,
            modulos_portales=modulos_portales,
            headless=headless,
        )
        _output(generar_reporte_texto(reporte), archivo)
    finally:
        await close_pool()


async def _cli_validar_todas(
    archivo: str | None = None,
    *,
    portales: bool = False,
    modulos_portales: set[str] | None = None,
    headless: bool = True,
):
    """Valida todas las empresas."""
    await get_pool()
    try:
        resumen = await validar_todas(
            portales=portales,
            modulos_portales=modulos_portales,
            headless=headless,
        )
        _output(generar_resumen_global_texto(resumen), archivo)
    finally:
        await close_pool()


async def _cli_validar_rfc(
    rfc: str,
    archivo: str | None = None,
    *,
    portales: bool = False,
    modulos_portales: set[str] | None = None,
    headless: bool = True,
):
    """Valida una empresa por RFC."""
    await get_pool()
    try:
        empresas = await listar_empresas()
        matches = [e for e in empresas if e["rfc"].upper() == rfc.upper()]
        if not matches:
            print(f"Error: No se encontró empresa con RFC '{rfc}'")
            return
        reporte = await validar_empresa(
            matches[0]["id"],
            portales=portales,
            modulos_portales=modulos_portales,
            headless=headless,
        )
        _output(generar_reporte_texto(reporte), archivo)
    finally:
        await close_pool()


async def _cli_validar_portales(
    rfcs: list[str] | None = None,
    modulos: set[str] | None = None,
    formato: str = "xlsx",
    headless: bool = True,
):
    """Valida documentos contra portales gubernamentales."""
    from .services.portal_validator.engine import ejecutar_validacion_portales

    await get_pool()
    try:
        resultados = await ejecutar_validacion_portales(
            modulos=modulos,
            rfcs=rfcs,
            formato_reporte=formato,
            headless=headless,
        )
        print(f"\nValidación completada: {len(resultados)} consultas realizadas")
    finally:
        await close_pool()


def _print_usage():
    print("""
Colorado — Agente de Validación Cruzada KYB v1.0.0

Uso:
  python -m cross_validation listar                    Lista empresas en la BD
  python -m cross_validation validar <empresa_id>      Valida una empresa por UUID
  python -m cross_validation validar-rfc <rfc>         Valida una empresa por RFC
  python -m cross_validation validar-todas             Valida todas las empresas
  python -m cross_validation validar-portales          Valida contra portales gubernamentales (legacy)
  python -m cross_validation server                    Inicia el servidor API

Opciones generales:
  -o, --output ARCHIVO   Guarda el reporte en un archivo UTF-8
  --host HOST            Host del servidor API (default: 0.0.0.0)
  --port PORT            Puerto del servidor API (default: 8001)

Opciones de portales (aplica a validar, validar-rfc, validar-todas):
  --portales             Incluir bloque 10: validación contra portales gubernamentales
  --modulos ine,fiel,rfc Módulos de portales a ejecutar (separados por coma)
  --visible              Mostrar el navegador (default: headless)

Opciones de validar-portales (comando legacy):
  --rfc RFC1,RFC2        RFCs específicos (separados por coma). Sin este flag → todas
  --modulos ine,fiel,rfc Módulos a ejecutar (separados por coma). Sin flag → todos
  --formato xlsx|csv     Formato del reporte (default: xlsx)
  --visible              Mostrar el navegador (default: headless)

Ejemplos:
  python -m cross_validation validar-rfc SCX190531824 -o reporte.txt
  python -m cross_validation validar-rfc SCX190531824 --portales --visible -o reporte.txt
  python -m cross_validation validar-todas -o resumen.txt
  python -m cross_validation validar-todas --portales -o resumen.txt
  python -m cross_validation validar-portales --rfc SCX190531824 --modulos ine,rfc
""")


def _parse_portal_flags(args: list[str]) -> tuple[list[str], bool, set[str] | None, bool]:
    """
    Extrae --portales, --modulos y --visible de los argumentos.
    Devuelve (args_limpio, portales, modulos_portales, headless).
    """
    portales = False
    modulos_portales: set[str] | None = None
    headless = True
    clean: list[str] = []
    skip = False

    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a == "--portales":
            portales = True
        elif a == "--visible":
            headless = False
        elif a == "--modulos" and i + 1 < len(args):
            modulos_portales = {m.strip() for m in args[i + 1].split(",") if m.strip()}
            skip = True
        else:
            clean.append(a)

    return clean, portales, modulos_portales, headless


def cli():
    """Punto de entrada CLI."""
    raw_args = sys.argv[1:]

    if not raw_args or raw_args[0] in ("-h", "--help"):
        _print_usage()
        return

    args, archivo = _parse_output_flag(raw_args)
    command = args[0].lower()

    if command == "listar":
        asyncio.run(_cli_listar())

    elif command == "validar":
        if len(args) < 2:
            print("Error: Especifica el empresa_id")
            _print_usage()
            return
        rest, portales, modulos_p, headless = _parse_portal_flags(args[2:])
        asyncio.run(_cli_validar(
            args[1], archivo,
            portales=portales,
            modulos_portales=modulos_p,
            headless=headless,
        ))

    elif command == "validar-rfc":
        if len(args) < 2:
            print("Error: Especifica el RFC")
            _print_usage()
            return
        rest, portales, modulos_p, headless = _parse_portal_flags(args[2:])
        asyncio.run(_cli_validar_rfc(
            args[1], archivo,
            portales=portales,
            modulos_portales=modulos_p,
            headless=headless,
        ))

    elif command == "validar-todas":
        rest, portales, modulos_p, headless = _parse_portal_flags(args[1:])
        asyncio.run(_cli_validar_todas(
            archivo,
            portales=portales,
            modulos_portales=modulos_p,
            headless=headless,
        ))

    elif command == "validar-portales":
        # Parsear flags específicos
        rfcs_arg = None
        modulos_arg = None
        formato_arg = "xlsx"
        headless_arg = True
        i = 1
        while i < len(args):
            if args[i] == "--rfc" and i + 1 < len(args):
                rfcs_arg = [r.strip() for r in args[i + 1].split(",") if r.strip()]
                i += 2
            elif args[i] == "--modulos" and i + 1 < len(args):
                modulos_arg = {m.strip() for m in args[i + 1].split(",") if m.strip()}
                i += 2
            elif args[i] == "--formato" and i + 1 < len(args):
                formato_arg = args[i + 1].strip().lower()
                i += 2
            elif args[i] == "--visible":
                headless_arg = False
                i += 1
            else:
                i += 1
        asyncio.run(_cli_validar_portales(
            rfcs=rfcs_arg,
            modulos=modulos_arg,
            formato=formato_arg,
            headless=headless_arg,
        ))

    elif command == "server":
        import uvicorn
        host = API_HOST
        port = API_PORT
        # Parse optional args
        for i, a in enumerate(args[1:], 1):
            if a == "--host" and i + 1 < len(args):
                host = args[i + 1]
            elif a == "--port" and i + 1 < len(args):
                port = int(args[i + 1])
        uvicorn.run(app, host=host, port=port)

    else:
        print(f"Comando desconocido: '{command}'")
        _print_usage()


if __name__ == "__main__":
    cli()
