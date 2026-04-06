"""
KYB Document Review — Demo UI (Streamlit)

Panel ejecutivo para demostrar el pipeline completo de servicios:
  Archivo(s) + RFC  →  Orquestrador  →  Dakota (extracción, interno)
                                      →  Colorado (validación cruzada)
                                      →  Arizona v2.3 (PLD/FT completo: completitud
                                           + screening + MER + dictamen)
                                      →  Nevada (dictamen jurídico DJ-1)

Ejecutar:
    streamlit run DemoUI/app.py
"""

from __future__ import annotations

import os
import time
from datetime import datetime

import httpx
import streamlit as st

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════

COLORADO_URL = os.environ.get("COLORADO_URL", "http://localhost:8011")
ARIZONA_URL = os.environ.get("ARIZONA_URL", "http://localhost:8012")
NEVADA_URL = os.environ.get("NEVADA_URL", "http://localhost:8013")
ORQUESTRATOR_URL = os.environ.get("ORQUESTRATOR_URL", "http://localhost:8002")

COLORADO_PREFIX = "/api/v1/validacion"
PLD_PREFIX = "/api/v1/pld"
NEVADA_PREFIX = "/api/v1/legal"
PIPELINE_PREFIX = "/api/v1/pipeline"

TIMEOUT = 600.0  # 10 minutos — expedientes completos con 5 pasos

# Tipos de documento y sus labels amigables
DOC_TYPES: dict[str, str] = {
    "csf": "📋 Constancia de Situación Fiscal",
    "acta_constitutiva": "📜 Acta Constitutiva",
    "ine": "🪪 INE Frente",
    "ine_reverso": "🪪 INE Reverso",
    "poder_notarial": "⚖️ Poder Notarial",
    "domicilio": "🏠 Comprobante de Domicilio",
    "fiel": "🔐 FIEL",
    "estado_cuenta": "🏦 Estado de Cuenta",
    "reforma_estatutos": "📝 Reforma de Estatutos",
}

DOC_TYPES_REQUIRED = ["csf", "acta_constitutiva", "ine", "poder_notarial", "domicilio"]
DOC_TYPES_OPTIONAL = ["fiel", "estado_cuenta", "reforma_estatutos", "ine_reverso"]

DICTAMEN_EMOJI = {
    "APROBADO": "✅",
    "APROBADO_CON_OBSERVACIONES": "⚠️",
    "RECHAZADO": "❌",
}

DICTAMEN_LEGAL_EMOJI = {
    "FAVORABLE": "✅",
    "FAVORABLE_CON_CONDICIONES": "⚠️",
    "NO_FAVORABLE": "❌",
}

NIVEL_RIESGO_COLOR = {
    "BAJO": ("#d4edda", "#155724", "#28a745"),
    "MEDIO": ("#fff3cd", "#856404", "#ffc107"),
    "ALTO": ("#f8d7da", "#721c24", "#dc3545"),
    "MUY ALTO": ("#f8d7da", "#721c24", "#dc3545"),
}


# ══════════════════════════════════════════════════════════════════════════════
#  FUNCIONES HTTP
# ══════════════════════════════════════════════════════════════════════════════

def check_services() -> dict[str, bool]:
    """Verifica qué servicios están activos consultando al Orquestrador."""
    try:
        r = httpx.get(f"{ORQUESTRATOR_URL}{PIPELINE_PREFIX}/health", timeout=10)
        if r.status_code == 200:
            data = r.json()
            result = {
                "Orquestrator": True,
                "Dakota": data.get("dakota", {}).get("reachable", False),
                "Colorado": data.get("colorado", {}).get("reachable", False),
                "Arizona": data.get("arizona_pld", {}).get("reachable", False),
            }
            # Nevada no está en el health del Orquestrator, verificar directo
            try:
                rn = httpx.get(f"{NEVADA_URL}{NEVADA_PREFIX}/health", timeout=5)
                result["Nevada"] = rn.status_code == 200
            except Exception:
                result["Nevada"] = False
            return result
    except Exception:
        pass
    # Fallback: verificar uno a uno
    status: dict[str, bool] = {}
    for name, url, path in [
        ("Colorado", COLORADO_URL, f"{COLORADO_PREFIX}/health"),
        ("Arizona", ARIZONA_URL, f"{PLD_PREFIX}/health"),
        ("Nevada", NEVADA_URL, f"{NEVADA_PREFIX}/health"),
        ("Orquestrator", ORQUESTRATOR_URL, f"{PIPELINE_PREFIX}/health"),
    ]:
        try:
            r = httpx.get(f"{url}{path}", timeout=5)
            status[name] = r.status_code == 200
        except Exception:
            status[name] = False
    return status


def send_to_pipeline(
    file_bytes: bytes,
    file_name: str,
    doc_type: str,
    rfc: str,
    content_type: str = "application/pdf",
) -> dict | None:
    """Envía un documento al Orquestrador para pipeline completo."""
    url = f"{ORQUESTRATOR_URL}{PIPELINE_PREFIX}/process"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(
                url,
                files={"file": (file_name, file_bytes, content_type)},
                data={"doc_type": doc_type, "rfc": rfc},
            )
        if r.status_code == 200:
            return r.json()
        return {"_error": f"HTTP {r.status_code}", "_body": r.text[:500]}
    except httpx.ConnectError:
        return {"_error": "Orquestrador no disponible (puerto 8002)"}
    except httpx.TimeoutException:
        return {"_error": f"Timeout ({TIMEOUT}s)"}
    except Exception as e:
        return {"_error": str(e)}


def send_expediente_to_pipeline(
    rfc: str,
    archivos: list[tuple[str, bytes, str, str]],
) -> dict | None:
    """Envía un expediente completo al Orquestrador.

    Args:
        rfc: RFC de la empresa.
        archivos: Lista de (doc_type, file_bytes, file_name, content_type).
    """
    url = f"{ORQUESTRATOR_URL}{PIPELINE_PREFIX}/expediente"
    files_list = []
    data_list: list[tuple[str, str]] = [("rfc", rfc)]
    for doc_type, file_bytes, file_name, content_type in archivos:
        files_list.append(("files", (file_name, file_bytes, content_type)))
        data_list.append(("doc_types", doc_type))
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(url, files=files_list, data=data_list)
        if r.status_code == 200:
            return r.json()
        return {"_error": f"HTTP {r.status_code}", "_body": r.text[:500]}
    except httpx.ConnectError:
        return {"_error": "Orquestrador no disponible (puerto 8002)"}
    except httpx.TimeoutException:
        return {"_error": f"Timeout ({TIMEOUT}s)"}
    except Exception as e:
        return {"_error": str(e)}


def run_colorado(empresa_id: str) -> dict | None:
    """Ejecuta validación cruzada en Colorado."""
    url = f"{COLORADO_URL}{COLORADO_PREFIX}/empresa/{empresa_id}"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(url)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def get_colorado_report(empresa_id: str) -> str | None:
    """Obtiene el reporte en texto plano de Colorado."""
    url = f"{COLORADO_URL}{COLORADO_PREFIX}/empresa/{empresa_id}/reporte"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(url)
        if r.status_code == 200:
            return r.text
        return None
    except Exception:
        return None


def run_arizona_pld(empresa_id: str) -> dict | None:
    """Ejecuta análisis PLD Etapa 1 (completitud + screening) en Arizona."""
    url = f"{ARIZONA_URL}{PLD_PREFIX}/etapa1/{empresa_id}"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(url)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def run_arizona_pld_reporte(empresa_id: str) -> str | None:
    """Ejecuta análisis PLD Etapa 1 y devuelve reporte de texto."""
    url = f"{ARIZONA_URL}{PLD_PREFIX}/etapa1/{empresa_id}/reporte"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(url)
        if r.status_code == 200:
            return r.text
        return None
    except Exception:
        return None


def run_arizona_reporte_consolidado(empresa_id: str) -> str | None:
    """Ejecuta reporte consolidado PLD (Etapa 1 + 2 + estructura)."""
    url = f"{ARIZONA_URL}{PLD_PREFIX}/reporte/{empresa_id}"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(url)
        if r.status_code == 200:
            return r.text
        return None
    except Exception:
        return None


def run_arizona_completo(empresa_id: str) -> str | None:
    """Ejecuta pipeline PLD completo en Arizona (Etapas 1-5 + dictamen). Devuelve reporte.txt."""
    url = f"{ARIZONA_URL}{PLD_PREFIX}/completo/{empresa_id}"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(url)
        if r.status_code == 200:
            return r.text
        return None
    except Exception:
        return None


def get_arizona_dictamen(empresa_id: str) -> dict | None:
    """Obtiene el dictamen PLD/FT guardado (JSON) desde Arizona."""
    url = f"{ARIZONA_URL}{PLD_PREFIX}/dictamen/{empresa_id}"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.get(url)
        if r.status_code == 200:
            data = r.json()
            # El endpoint devuelve la fila de BD; el contenido real está en dictamen_json
            dj = data.get("dictamen_json") if isinstance(data, dict) else None
            if isinstance(dj, str):
                import json as _json
                return _json.loads(dj)
            if isinstance(dj, dict):
                return dj
            return data
        return None
    except Exception:
        return None


def get_arizona_dictamen_txt(empresa_id: str) -> str | None:
    """Obtiene el dictamen PLD/FT en texto plano desde Arizona."""
    url = f"{ARIZONA_URL}{PLD_PREFIX}/dictamen/{empresa_id}/txt"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.get(url)
        if r.status_code == 200:
            return r.text
        return None
    except Exception:
        return None


def run_nevada_dictamen(empresa_id: str) -> dict | None:
    """Genera el dictamen jurídico DJ-1 con Nevada."""
    url = f"{NEVADA_URL}{NEVADA_PREFIX}/dictamen/{empresa_id}"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(url)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def get_nevada_dictamen(empresa_id: str) -> dict | None:
    """Obtiene el dictamen jurídico guardado (JSON) desde Nevada."""
    url = f"{NEVADA_URL}{NEVADA_PREFIX}/dictamen/{empresa_id}"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.get(url)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def get_empresas() -> list[dict]:
    """Lista empresas disponibles en la BD."""
    url = f"{COLORADO_URL}{COLORADO_PREFIX}/empresas"
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(url)
        if r.status_code == 200:
            return r.json()
        return []
    except Exception:
        return []


def get_pipeline_status(rfc: str) -> dict | None:
    """Consulta el estado del pipeline por RFC al Orquestrador."""
    url = f"{ORQUESTRATOR_URL}{PIPELINE_PREFIX}/status/{rfc}"
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(url)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  INTERFAZ STREAMLIT
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    st.set_page_config(
        page_title="KYB Document Review",
        page_icon="🏢",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── CSS personalizado ─────────────────────────────────────────────────
    st.markdown("""
    <style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1B3A5C;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .metric-card {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1.2rem;
        text-align: center;
        border-left: 4px solid #1B3A5C;
    }
    .dictamen-box {
        padding: 1.5rem;
        border-radius: 12px;
        text-align: center;
        font-size: 1.4rem;
        font-weight: 700;
        margin: 1rem 0;
    }
    .dictamen-aprobado { background: #d4edda; color: #155724; border: 2px solid #28a745; }
    .dictamen-observaciones { background: #fff3cd; color: #856404; border: 2px solid #ffc107; }
    .dictamen-rechazado { background: #f8d7da; color: #721c24; border: 2px solid #dc3545; }
    .risk-box {
        padding: 1rem 1.5rem;
        border-radius: 10px;
        text-align: center;
        font-weight: 600;
        margin: 0.5rem 0;
    }
    .step-header {
        font-size: 1.1rem;
        font-weight: 600;
        color: #1B3A5C;
        border-bottom: 2px solid #e0e0e0;
        padding-bottom: 0.4rem;
        margin-top: 1.5rem;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Header ────────────────────────────────────────────────────────────
    st.markdown('<div class="main-header">🏢 KYB Document Review</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">'
                '(Extracción → Validación → PLD/AML → Dictamen PLD/FT → Dictamen Jurídico) — todo vía Orquestrador'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Sidebar: Status de servicios ──────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ Estado del Sistema")
        if st.button("🔄 Verificar servicios", use_container_width=True):
            st.session_state["services"] = check_services()

        services = st.session_state.get("services", {})
        if services:
            for svc, ok in services.items():
                if ok:
                    st.success(f"✅ {svc}")
                else:
                    st.error(f"❌ {svc}")
            all_ok = all(services.values())
            if all_ok:
                st.info("🟢 Todos los servicios operativos")
            else:
                st.warning("🟡 Algunos servicios no disponibles")
        else:
            st.info("Haz clic en 'Verificar servicios' para comprobar la conexión.")

        st.divider()

        st.markdown("**Servicios del pipeline:**")
        st.markdown("""
        | Servicio | Puerto |
        |----------|--------|
        | Dakota | 8010 |
        | Colorado | 8011 |
        | Arizona | 8012 |
        | Nevada | 8013 |
        | Orquestrador | 8002 |
        """)

        st.divider()
        st.caption("Versión: 3.0.0 · Abril 2026")

    # ── Pestañas principales ──────────────────────────────────────────────
    tab_expediente, tab_individual, tab_agentes, tab_consulta, tab_pipeline, tab_historial = st.tabs([
        "📁 Expediente Completo",
        "📄 Documento Individual",
        "🧩 Agentes Individuales",
        "🔍 Consultar por RFC",
        "📊 Estado Pipeline",
        "📜 Historial",
    ])

    # ══════════════════════════════════════════════════════════════════════
    #  TAB 1: EXPEDIENTE COMPLETO
    # ══════════════════════════════════════════════════════════════════════
    with tab_expediente:
        st.subheader("Subir expediente completo")
        st.markdown(
            "Sube todos los documentos de la empresa. El sistema **extrae**, **valida**, "
            "ejecuta **análisis PLD/AML** y genera el **dictamen PLD/FT** automáticamente."
        )

        col_rfc, _ = st.columns([1, 2])
        with col_rfc:
            rfc_exp = st.text_input(
                "RFC de la empresa",
                placeholder="Ej: ABC230223IA7",
                key="rfc_expediente",
                help="12-13 caracteres. Se convierte a mayúsculas automáticamente.",
            ).strip().upper()

        st.markdown("**Documentos requeridos:**")
        uploaded_required: dict[str, st.runtime.uploaded_file_manager.UploadedFile | None] = {}
        cols = st.columns(len(DOC_TYPES_REQUIRED))
        for i, dtype in enumerate(DOC_TYPES_REQUIRED):
            with cols[i]:
                label = DOC_TYPES[dtype]
                uploaded_required[dtype] = st.file_uploader(
                    label,
                    type=["pdf", "png", "jpg", "jpeg", "tiff"],
                    key=f"exp_{dtype}",
                )

        st.markdown("**Documentos opcionales:**")
        uploaded_optional: dict[str, st.runtime.uploaded_file_manager.UploadedFile | None] = {}
        cols_opt = st.columns(len(DOC_TYPES_OPTIONAL))
        for i, dtype in enumerate(DOC_TYPES_OPTIONAL):
            with cols_opt[i]:
                label = DOC_TYPES[dtype]
                uploaded_optional[dtype] = st.file_uploader(
                    label,
                    type=["pdf", "png", "jpg", "jpeg", "tiff", "cer"],
                    key=f"exp_{dtype}",
                )

        # Conteo
        n_required = sum(1 for f in uploaded_required.values() if f is not None)
        n_optional = sum(1 for f in uploaded_optional.values() if f is not None)
        n_total = n_required + n_optional

        if n_total > 0:
            st.info(f"📎 {n_required}/{len(DOC_TYPES_REQUIRED)} requeridos · {n_optional} opcionales subidos")

        # Botón de procesamiento
        can_process = bool(rfc_exp) and n_required >= 3
        if st.button(
            "▶️  Procesar Expediente Completo (3 pasos)",
            disabled=not can_process,
            type="primary",
            use_container_width=True,
            key="btn_expediente",
        ):
            _run_expediente(rfc_exp, uploaded_required, uploaded_optional)

    # ══════════════════════════════════════════════════════════════════════
    #  TAB 2: DOCUMENTO INDIVIDUAL
    # ══════════════════════════════════════════════════════════════════════
    with tab_individual:
        st.subheader("Procesar un documento individual")
        st.markdown(
            "Sube un solo archivo, extrae los datos y (si hay datos previos) "
            "ejecuta la validación cruzada + análisis PLD + dictamen."
        )

        col1, col2 = st.columns(2)
        with col1:
            rfc_ind = st.text_input(
                "RFC de la empresa",
                placeholder="Ej: ABC230223IA7",
                key="rfc_individual",
            ).strip().upper()
        with col2:
            doc_type_sel = st.selectbox(
                "Tipo de documento",
                options=list(DOC_TYPES.keys()),
                format_func=lambda x: DOC_TYPES[x],
                key="doc_type_individual",
            )

        uploaded_single = st.file_uploader(
            "Selecciona el archivo",
            type=["pdf", "png", "jpg", "jpeg", "tiff", "cer"],
            key="file_individual",
        )

        if st.button(
            "▶️  Procesar Documento",
            disabled=not (rfc_ind and uploaded_single),
            type="primary",
            use_container_width=True,
            key="btn_individual",
        ):
            _run_individual(rfc_ind, doc_type_sel, uploaded_single)

    # ══════════════════════════════════════════════════════════════════════
    #  TAB 3: CONSULTAR POR RFC
    # ══════════════════════════════════════════════════════════════════════
    with tab_consulta:
        st.subheader("Consultar empresa existente")
        st.markdown(
            "Si ya procesaste documentos antes, consulta el estado y ejecuta "
            "pasos individuales sin re-subir archivos."
        )

        empresas = get_empresas()

        if empresas:
            opciones = {
                e.get("id", e.get("empresa_id", "")): f"{e.get('razon_social', 'Sin nombre')} — {e.get('rfc', '?')}"
                for e in empresas
            }
            empresa_sel = st.selectbox(
                "Selecciona una empresa",
                options=list(opciones.keys()),
                format_func=lambda x: opciones[x],
                key="empresa_consulta",
            )

            st.markdown("**Ejecutar pasos individuales:**")
            col_a, col_b, col_c, col_d, col_e = st.columns(5)
            with col_a:
                if st.button("🔍 Validación cruzada", use_container_width=True, key="btn_validar"):
                    _run_validation_only(empresa_sel)
            with col_b:
                if st.button("🛡️ Pipeline PLD/FT", use_container_width=True, key="btn_pld"):
                    _run_pld_only(empresa_sel)
            with col_c:
                if st.button("📋 Dictamen PLD", use_container_width=True, key="btn_dictamen"):
                    _run_compliance_only(empresa_sel)
            with col_d:
                if st.button("⚖️ Dictamen Jurídico", use_container_width=True, key="btn_legal"):
                    _run_nevada_generate(empresa_sel)
            with col_e:
                if st.button("📄 Todo (Pipeline completo)", use_container_width=True, key="btn_reporte"):
                    _run_all_reports(empresa_sel)

        else:
            st.warning("No hay empresas en la base de datos. Sube documentos primero.")

    # ══════════════════════════════════════════════════════════════════════
    #  TAB 4: ESTADO PIPELINE
    # ══════════════════════════════════════════════════════════════════════
    with tab_pipeline:
        st.subheader("Consultar estado del pipeline por RFC")
        st.markdown(
            "Consulta el progreso end-to-end registrado por el Orquestrador "
            "en la tabla `pipeline_resultados`."
        )

        rfc_status = st.text_input(
            "RFC de la empresa",
            placeholder="Ej: ABC230223IA7",
            key="rfc_pipeline_status",
        ).strip().upper()

        if st.button("🔎 Consultar", disabled=not rfc_status, key="btn_pipeline_status"):
            _show_pipeline_status(rfc_status)

    # ══════════════════════════════════════════════════════════════════════
    #  TAB 3: AGENTES INDIVIDUALES
    # ══════════════════════════════════════════════════════════════════════
    with tab_agentes:
        st.subheader("Ejecutar agentes de forma individual")
        st.markdown(
            "Invoca cada agente del pipeline por separado: extrae documentos, "
            "valida, ejecuta análisis PLD o genera un dictamen — sin depender del flujo completo."
        )

        agent_choice = st.radio(
            "Selecciona el agente a ejecutar:",
            ["� Colorado — Validación",
             "🛡️ Arizona — Pipeline PLD/FT Completo", "⚖️ Nevada — Dictamen Jurídico"],
            horizontal=True,
            key="agent_radio",
        )

        st.divider()

        # ────────────────────────────────────────────────────────────
        # COLORADO — Validación cruzada
        # ────────────────────────────────────────────────────────────
        if "Colorado" in agent_choice:
            st.markdown("### 🔍 Colorado — Validación Cruzada")
            st.caption(
                "Ejecuta validación cruzada (puerto 8011): comparación entre documentos, "
                "consulta a portales SAT y detección de inconsistencias."
            )

            empresas = get_empresas()
            if empresas:
                opciones_col = {
                    e.get("id", e.get("empresa_id", "")): f"{e.get('razon_social', 'Sin nombre')} — {e.get('rfc', '?')}"
                    for e in empresas
                }
                empresa_col = st.selectbox(
                    "Selecciona una empresa",
                    options=list(opciones_col.keys()),
                    format_func=lambda x: opciones_col[x],
                    key="empresa_agent_colorado",
                )

                if st.button(
                    "▶️  Ejecutar validación cruzada",
                    type="primary",
                    use_container_width=True,
                    key="btn_agent_colorado",
                ):
                    _run_validation_only(empresa_col)
            else:
                st.warning("No hay empresas en la base de datos. Sube documentos primero en la pestaña Expediente Completo.")

        # ────────────────────────────────────────────────────────────
        # ARIZONA — Pipeline PLD/FT Completo
        # ────────────────────────────────────────────────────────────
        elif "Arizona" in agent_choice:
            st.markdown("### 🛡️ Arizona — Pipeline PLD/FT Completo (v2.3)")
            st.caption(
                "Ejecuta el pipeline PLD/FT completo (puerto 8012): completitud DCG Art.115, "
                "screening contra listas negras, estructura accionaria, beneficiarios controladores, "
                "MER v7.0, dictamen PLD/FT con representantes legales, perfil transaccional y vigencias."
            )

            empresas = get_empresas()
            if empresas:
                opciones_pld = {
                    e.get("id", e.get("empresa_id", "")): f"{e.get('razon_social', 'Sin nombre')} — {e.get('rfc', '?')}"
                    for e in empresas
                }
                empresa_pld = st.selectbox(
                    "Selecciona una empresa",
                    options=list(opciones_pld.keys()),
                    format_func=lambda x: opciones_pld[x],
                    key="empresa_agent_pld",
                )

                col_run, col_dict = st.columns(2)
                with col_run:
                    if st.button(
                        "▶️  Ejecutar pipeline PLD/FT completo",
                        type="primary",
                        use_container_width=True,
                        key="btn_agent_pld",
                    ):
                        _run_pld_only(empresa_pld)
                with col_dict:
                    if st.button(
                        "📋 Consultar dictamen existente",
                        use_container_width=True,
                        key="btn_agent_dictamen_existing",
                    ):
                        _run_compliance_only(empresa_pld)
            else:
                st.warning("No hay empresas en la base de datos. Sube documentos primero en la pestaña Expediente Completo.")

        # ────────────────────────────────────────────────────────────
        # NEVADA — Dictamen Jurídico
        # ────────────────────────────────────────────────────────────
        else:
            st.markdown("### ⚖️ Nevada — Dictamen Jurídico DJ-1")
            st.caption(
                "Genera el Dictamen Jurídico (DJ-1) para Banco PagaTodo (puerto 8013): "
                "análisis de escritura constitutiva, poder notarial, tenencia accionaria, "
                "facultades del apoderado, régimen de administración, integración con "
                "Colorado (validación cruzada) y Arizona (PLD/FT)."
            )

            empresas = get_empresas()
            if empresas:
                opciones_nev = {
                    e.get("id", e.get("empresa_id", "")): f"{e.get('razon_social', 'Sin nombre')} — {e.get('rfc', '?')}"
                    for e in empresas
                }
                empresa_nev = st.selectbox(
                    "Selecciona una empresa",
                    options=list(opciones_nev.keys()),
                    format_func=lambda x: opciones_nev[x],
                    key="empresa_agent_nevada",
                )

                col_gen, col_get = st.columns(2)
                with col_gen:
                    if st.button(
                        "▶️  Generar dictamen jurídico",
                        type="primary",
                        use_container_width=True,
                        key="btn_agent_nevada_gen",
                    ):
                        _run_nevada_generate(empresa_nev)
                with col_get:
                    if st.button(
                        "📋 Consultar dictamen existente",
                        use_container_width=True,
                        key="btn_agent_nevada_get",
                    ):
                        _run_nevada_consultar(empresa_nev)
            else:
                st.warning("No hay empresas en la base de datos. Sube documentos primero en la pestaña Expediente Completo.")
    with tab_historial:
        st.subheader("Historial de validaciones")
        _show_historial()


# ══════════════════════════════════════════════════════════════════════════════
#  LÓGICA DE PROCESAMIENTO
# ══════════════════════════════════════════════════════════════════════════════

def _run_expediente(rfc: str, required: dict, optional: dict) -> None:
    """Procesa un expediente completo vía Orquestrador (OCR → Colorado → Arizona → Nevada)."""
    all_docs = {**required, **optional}
    docs_to_process = {k: v for k, v in all_docs.items() if v is not None}

    # Recoger archivos para enviar al Orquestrador
    archivos: list[tuple[str, bytes, str, str]] = []
    for dtype, uploaded in docs_to_process.items():
        archivos.append((dtype, uploaded.read(), uploaded.name, uploaded.type or "application/pdf"))

    # ── PASO 1: Orquestrador — Pipeline completo ──────────────────────
    progress = st.progress(0, text="Enviando expediente al Orquestrador...")
    st.markdown(
        '<div class="step-header">📤 Paso 1 — Pipeline completo (Orquestrador)</div>',
        unsafe_allow_html=True,
    )

    with st.spinner(f"Procesando {len(archivos)} documentos (OCR + validación + PLD + dictamen)..."):
        t0 = time.time()
        result = send_expediente_to_pipeline(rfc, archivos)
        elapsed_pipeline = time.time() - t0

    if not result or "_error" in result:
        progress.progress(1.0, text="❌ Error en el pipeline")
        error_msg = result.get("_error", "Error desconocido") if result else "Sin respuesta del Orquestrador"
        st.error(f"❌ {error_msg}")
        if result and "_body" in result:
            with st.expander("Detalle del error"):
                st.code(result["_body"])
        return

    empresa_id = result.get("empresa_id")
    st.success(f"✅ Pipeline completado en {elapsed_pipeline:.1f}s")
    progress.progress(0.3, text="Extracción completada...")

    # ── Resumen de extracción ─────────────────────────────────────────
    docs = result.get("documentos", [])
    if docs:
        st.markdown("**Resumen de extracción:**")
        rows = []
        for d in docs:
            status = "✅ OK" if d.get("status") == "ok" else f"❌ {d.get('error', 'Error')}"
            rows.append({
                "tipo": d.get("tipo_documento", ""),
                "archivo": d.get("archivo", ""),
                "status": status,
                "tiempo": f"{d.get('tiempo_ms', 0) / 1000:.1f}s",
            })
        st.dataframe(
            rows,
            column_config={
                "tipo": st.column_config.TextColumn("Tipo"),
                "archivo": st.column_config.TextColumn("Archivo"),
                "status": st.column_config.TextColumn("Estado"),
                "tiempo": st.column_config.TextColumn("Tiempo"),
            },
            hide_index=True,
            use_container_width=True,
        )

    if not empresa_id:
        progress.progress(1.0, text="⚠️ No se obtuvo empresa_id — pipeline incompleto")
        st.warning("No se obtuvo empresa_id del Orquestrador.")
        return

    # ── PASO 2: Resultado Colorado (ya ejecutado por Orquestrador) ────
    progress.progress(0.5, text="Obteniendo reporte Colorado...")
    st.markdown(
        '<div class="step-header">🔍 Paso 2 — Validación cruzada (Colorado)</div>',
        unsafe_allow_html=True,
    )

    val_cruzada = result.get("validacion_cruzada")
    if result.get("pipeline_detenido"):
        st.error(f"⛔ Pipeline detenido: {result.get('motivo_detencion', 'Colorado RECHAZÓ')}")

    if val_cruzada:
        reporte_colorado = get_colorado_report(empresa_id)
        _render_validacion(val_cruzada, reporte_colorado, elapsed_pipeline)
    else:
        st.warning("⚠️ Colorado no retornó resultado.")

    if result.get("pipeline_detenido"):
        progress.progress(1.0, text="⛔ Pipeline detenido por Colorado")
        return

    # ── PASO 3: Arizona PLD Completo ──────────────────────────────────
    progress.progress(0.7, text="Ejecutando pipeline PLD/FT completo (Arizona)...")
    st.markdown(
        '<div class="step-header">🛡️ Paso 3 — Pipeline PLD/FT Completo (Arizona v2.3)</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Arizona ejecutando pipeline PLD/FT completo (5 etapas + dictamen)..."):
        t0 = time.time()
        reporte_pld = run_arizona_completo(empresa_id)
        elapsed_pld = time.time() - t0

    dictamen_json = None
    dictamen_txt = None
    if reporte_pld:
        dictamen_json = get_arizona_dictamen(empresa_id)
        dictamen_txt = get_arizona_dictamen_txt(empresa_id)
        _render_arizona_resultado(reporte_pld, dictamen_json, dictamen_txt, elapsed_pld)
    else:
        st.warning("⚠️ Arizona PLD no retornó resultado.")

    # ── PASO 4: Nevada — Dictamen Jurídico (ya ejecutado) ─────────────
    progress.progress(0.9, text="Obteniendo dictamen jurídico (Nevada)...")
    st.markdown(
        '<div class="step-header">⚖️ Paso 4 — Dictamen Jurídico DJ-1 (Nevada)</div>',
        unsafe_allow_html=True,
    )

    legal_result = get_nevada_dictamen(empresa_id)
    if legal_result:
        _render_nevada_resultado(legal_result, elapsed_pipeline)
    else:
        st.warning("⚠️ Nevada no generó dictamen. Verifica que el servicio esté corriendo.")

    progress.progress(1.0, text="✅ Pipeline completo — 4 pasos finalizados")

    # ── Resumen final ─────────────────────────────────────────────────
    validacion = val_cruzada
    st.markdown("---")
    st.markdown("### 🏁 Resumen del Pipeline")
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        v_dict = validacion.get("dictamen", "—") if validacion else "—"
        emoji = DICTAMEN_EMOJI.get(v_dict, "❓")
        st.metric("Colorado", f"{emoji} {v_dict.replace('_', ' ')}")
    with col2:
        if dictamen_json:
            riesgo = dictamen_json.get("grado_riesgo_inicial", "—")
            st.metric("Riesgo MER", riesgo.upper() if isinstance(riesgo, str) else "—")
        else:
            st.metric("Riesgo MER", "—")
    with col3:
        if dictamen_json:
            n_rep = len(dictamen_json.get("representantes_legales", []))
            n_acc = len(dictamen_json.get("estructura_accionaria", []))
            st.metric("Personas", f"{n_acc} acc. · {n_rep} rep.")
        else:
            st.metric("Personas", "—")
    with col4:
        if reporte_pld:
            st.metric("Arizona", "✅ Completo")
        else:
            st.metric("Arizona", "—")
    with col5:
        if legal_result:
            legal_dict = legal_result.get("dictamen", "—")
            legal_emoji = DICTAMEN_LEGAL_EMOJI.get(legal_dict, "❓")
            st.metric("Nevada DJ-1", f"{legal_emoji} {legal_dict.replace('_', ' ')}")
        else:
            st.metric("Nevada DJ-1", "—")


def _run_individual(rfc: str, doc_type: str, uploaded: st.runtime.uploaded_file_manager.UploadedFile) -> None:
    """Procesa un solo documento vía Orquestrador (OCR + pipeline completo)."""
    with st.spinner(f"Enviando {uploaded.name} al Orquestrador (pipeline completo)..."):
        t0 = time.time()
        result = send_to_pipeline(
            file_bytes=uploaded.read(),
            file_name=uploaded.name,
            doc_type=doc_type,
            rfc=rfc,
            content_type=uploaded.type or "application/pdf",
        )
        elapsed = time.time() - t0

    if result and "_error" not in result:
        st.success(f"✅ Pipeline completado en {elapsed:.1f}s")

        # Mostrar resumen de extracción
        extraccion = result.get("extraccion")
        if extraccion:
            with st.expander("📋 Datos extraídos (JSON)", expanded=False):
                st.json(extraccion)

        empresa_id = result.get("empresa_id") or (result.get("persistencia") or {}).get("empresa_id")

        # Mostrar resumen de validación cruzada
        val = result.get("validacion_cruzada")
        if val and not val.get("error"):
            dictamen = val.get("dictamen", "—")
            emoji = DICTAMEN_EMOJI.get(dictamen, "❓")
            st.info(f"🔍 Colorado: {emoji} {dictamen.replace('_', ' ')} — "
                    f"{val.get('total_hallazgos', 0)} hallazgos, {val.get('criticos', 0)} críticos")

        if result.get("pipeline_detenido"):
            st.warning(f"⛔ {result.get('motivo_detencion', 'Pipeline detenido')}")

        # Tiempos
        tiempos = result.get("tiempos", {})
        if tiempos:
            parts = []
            if tiempos.get("dakota_ocr_ms"):
                parts.append(f"OCR: {tiempos['dakota_ocr_ms']/1000:.1f}s")
            if tiempos.get("validacion_cruzada_ms"):
                parts.append(f"Colorado: {tiempos['validacion_cruzada_ms']/1000:.1f}s")
            if tiempos.get("total_ms"):
                parts.append(f"Total: {tiempos['total_ms']/1000:.1f}s")
            if parts:
                st.caption(" · ".join(parts))

        if empresa_id:
            st.markdown("**Ejecutar pasos adicionales:**")
            col_a, col_b, col_c, col_d = st.columns(4)
            with col_a:
                if st.button("🔍 Validación cruzada", key="btn_cross_val_ind"):
                    _run_validation_only(empresa_id)
            with col_b:
                if st.button("🛡️ Pipeline PLD/FT", key="btn_pld_ind"):
                    _run_pld_only(empresa_id)
            with col_c:
                if st.button("📋 Dictamen PLD", key="btn_compliance_ind"):
                    _run_compliance_only(empresa_id)
            with col_d:
                if st.button("⚖️ Dictamen Jurídico", key="btn_legal_ind"):
                    _run_nevada_generate(empresa_id)
    else:
        error_msg = result.get("_error", "Error desconocido") if result else "Sin respuesta del Orquestrador"
        st.error(f"❌ {error_msg}")
        if result and "_body" in result:
            with st.expander("Detalle del error"):
                st.code(result["_body"])


def _run_validation_only(empresa_id: str) -> None:
    """Ejecuta solo validación cruzada + reporte."""
    with st.spinner("Ejecutando validación cruzada con Colorado..."):
        t0 = time.time()
        validacion = run_colorado(empresa_id)
        reporte_txt = get_colorado_report(empresa_id)
        elapsed = time.time() - t0

    if validacion:
        _render_validacion(validacion, reporte_txt, elapsed)
    else:
        st.error("❌ Colorado no retornó resultado.")


def _run_pld_only(empresa_id: str) -> None:
    """Ejecuta pipeline PLD completo de Arizona y muestra resultados."""
    with st.spinner("Ejecutando pipeline PLD/FT completo con Arizona v2.3..."):
        t0 = time.time()
        reporte_txt = run_arizona_completo(empresa_id)
        elapsed = time.time() - t0

    if reporte_txt:
        dictamen_json = get_arizona_dictamen(empresa_id)
        dictamen_txt = get_arizona_dictamen_txt(empresa_id)
        _render_arizona_resultado(reporte_txt, dictamen_json, dictamen_txt, elapsed)
    else:
        st.error("❌ Arizona PLD no retornó resultado.")


def _run_compliance_only(empresa_id: str) -> None:
    """Consulta el dictamen PLD/FT ya generado para una empresa."""
    with st.spinner("Consultando dictamen PLD/FT..."):
        t0 = time.time()
        dictamen_json = get_arizona_dictamen(empresa_id)
        dictamen_txt = get_arizona_dictamen_txt(empresa_id)
        elapsed = time.time() - t0

    if dictamen_json or dictamen_txt:
        _render_arizona_resultado(None, dictamen_json, dictamen_txt, elapsed)
    else:
        st.error("❌ No hay dictamen guardado. Ejecuta primero el pipeline PLD completo.")


def _run_all_reports(empresa_id: str) -> None:
    """Ejecuta los 4 pasos de análisis y muestra todo."""
    _run_validation_only(empresa_id)
    _run_pld_only(empresa_id)
    _run_compliance_only(empresa_id)
    _run_nevada_generate(empresa_id)


    _run_pld_only(empresa_id)
    _run_compliance_only(empresa_id)
    _run_nevada_generate(empresa_id)


def _run_nevada_generate(empresa_id: str) -> None:
    """Genera dictamen jurídico DJ-1 con Nevada."""
    with st.spinner("Nevada generando dictamen jurídico DJ-1 (reglas + LLM)..."):
        t0 = time.time()
        result = run_nevada_dictamen(empresa_id)
        elapsed = time.time() - t0

    if result:
        _render_nevada_resultado(result, elapsed)
    else:
        st.error("❌ Nevada no retornó resultado. Verifica que el servicio esté corriendo (puerto 8013).")


def _run_nevada_consultar(empresa_id: str) -> None:
    """Consulta dictamen jurídico existente desde Nevada."""
    with st.spinner("Consultando dictamen jurídico..."):
        t0 = time.time()
        result = get_nevada_dictamen(empresa_id)
        elapsed = time.time() - t0

    if result:
        _render_nevada_resultado(result, elapsed)
    else:
        st.error("❌ No hay dictamen jurídico guardado. Genera uno primero.")


def _render_nevada_resultado(result: dict, elapsed: float) -> None:
    """Renderiza resultado del dictamen jurídico DJ-1 de Nevada."""
    st.caption(f"Tiempo de ejecución: {elapsed:.1f}s")

    dictamen_resultado = result.get("dictamen", "—")
    emoji = DICTAMEN_LEGAL_EMOJI.get(dictamen_resultado, "❓")
    dictamen_display = dictamen_resultado.replace("_", " ")

    css_class = {
        "FAVORABLE": "dictamen-aprobado",
        "FAVORABLE_CON_CONDICIONES": "dictamen-observaciones",
        "NO_FAVORABLE": "dictamen-rechazado",
    }.get(dictamen_resultado, "")

    st.markdown(
        f'<div class="dictamen-box {css_class}">{emoji} Dictamen Jurídico DJ-1: {dictamen_display}</div>',
        unsafe_allow_html=True,
    )

    dj = result.get("dictamen_json", {})

    # ── Métricas de confiabilidad ─────────────────────────────────
    confiabilidad = dj.get("confiabilidad", {})
    reglas_data = result.get("reglas", {})

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        score = confiabilidad.get("score_global", 0)
        nivel = confiabilidad.get("nivel", "—")
        st.metric("Confiabilidad", f"{score}% ({nivel})")
    with col2:
        cumplidas = confiabilidad.get("reglas_cumplidas", 0)
        totales = confiabilidad.get("reglas_totales", 0)
        st.metric("Reglas", f"{cumplidas}/{totales}")
    with col3:
        score_ocr = confiabilidad.get("score_ocr")
        campos = confiabilidad.get("campos_ocr_evaluados", 0)
        st.metric("OCR", f"{score_ocr:.0f}% ({campos} campos)" if score_ocr else "—")
    with col4:
        usa_llm = confiabilidad.get("usa_llm", False)
        st.metric("Fuente", "LLM + Reglas" if usa_llm else "Solo Reglas")

    # ── Datos de constitución ─────────────────────────────────────
    const = dj.get("constitucion", {})
    ult = dj.get("ultimos_estatutos", {})
    with st.expander("📜 Datos de Constitución y Estatutos", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Constitución:**")
            st.markdown(f"- Escritura N°: **{const.get('escritura_numero', '—')}**")
            st.markdown(f"- Fecha: **{const.get('escritura_fecha', '—')}**")
            st.markdown(f"- Notario: **{const.get('nombre_notario', '—')}** (N° {const.get('numero_notario', '—')})")
            st.markdown(f"- Residencia: **{const.get('residencia_notario', '—')}**")
            st.markdown(f"- Folio Mercantil: **{const.get('folio_mercantil', '—')}**")
        with c2:
            st.markdown("**Últimos Estatutos:**")
            st.markdown(f"- Escritura N°: **{ult.get('escritura_numero', '—')}**")
            st.markdown(f"- Fecha: **{ult.get('escritura_fecha', '—')}**")
            st.markdown(f"- Notario: **{ult.get('nombre_notario', '—')}** (N° {ult.get('numero_notario', '—')})")
            st.markdown(f"- Residencia: **{ult.get('residencia_notario', '—')}**")
            st.markdown(f"- Folio Mercantil: **{ult.get('folio_mercantil', '—')}**")

    # ── Actividad / Giro ──────────────────────────────────────────
    act = dj.get("actividad", {})
    with st.expander("🏭 Actividad / Giro", expanded=False):
        st.markdown(f"- Actividad: **{act.get('actividad_giro', '—')}**")
        st.markdown(f"- ¿Sufrió modificaciones?: **{'Sí' if act.get('sufrio_modificaciones') else 'No'}**")
        obs_act = act.get("observaciones")
        if obs_act:
            st.markdown(f"- Observaciones: {obs_act}")

    # ── Tenencia accionaria ───────────────────────────────────────
    tenencia = dj.get("tenencia", {})
    accionistas = tenencia.get("accionistas", [])
    hay_ext = tenencia.get("hay_extranjeros", False)
    with st.expander(f"📊 Tenencia Accionaria ({len(accionistas)} accionistas)", expanded=False):
        if accionistas:
            rows = []
            for a in accionistas:
                rows.append({
                    "Nombre": a.get("nombre", ""),
                    "%": f"{a.get('porcentaje', 0):.1f}%",
                    "Extranjero": "Sí" if a.get("es_extranjero") else "No",
                    "Tipo": a.get("tipo_persona", "física"),
                })
            st.dataframe(rows, hide_index=True, use_container_width=True)
        if hay_ext:
            st.warning("⚠️ Hay accionistas extranjeros")
        else:
            st.success("✅ Sin accionistas extranjeros")

    # ── Apoderado(s) ──────────────────────────────────────────────
    apoderados = dj.get("apoderados", [])
    with st.expander(f"⚖️ Apoderado / Representante Legal ({len(apoderados)})", expanded=True):
        for ap in apoderados:
            st.markdown(f"### {ap.get('nombre', '—')}")
            fac = ap.get("facultades", {})
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(f"- Administración: **{'✅ Sí' if fac.get('administracion') else '❌ No'}**")
                st.markdown(f"- Dominio: **{'✅ Sí' if fac.get('dominio') else '❌ No'}**")
                st.markdown(f"- Delegación: **{'✅ Sí' if fac.get('delegacion_sustitucion') else '❌ No'}**")
            with c2:
                st.markdown(f"- Títulos de crédito: **{'✅ Sí' if fac.get('titulos_credito') else '❌ No'}**")
                st.markdown(f"- Apertura cuentas: **{'✅ Sí' if fac.get('apertura_cuentas') else '❌ No'}**")
                especiales = fac.get("especiales")
                st.markdown(f"- Especiales: **{especiales or '—'}**")
            with c3:
                st.markdown(f"- Régimen firmas: **{ap.get('regimen_firmas', '—')}**")
                st.markdown(f"- Nacionalidad: **{ap.get('nacionalidad', '—')}**")
                st.markdown(f"- Puede firmar: **{'✅ Sí' if ap.get('puede_firmar_contrato') else '❌ No'}**")
            limitaciones = ap.get("limitaciones")
            if limitaciones:
                st.info(f"📝 Limitaciones: {limitaciones}")

    # ── Régimen de administración ─────────────────────────────────
    admin = dj.get("administracion", {})
    with st.expander("🏛️ Régimen de Administración", expanded=False):
        tipo = admin.get("tipo", "—")
        st.markdown(f"- Tipo: **{tipo or '—'}**")
        miembros = admin.get("miembros", [])
        if miembros:
            for m in miembros:
                st.markdown(f"  - {m.get('nombre', '—')} — {m.get('cargo', '—')}")

    # ── Observaciones ─────────────────────────────────────────────
    obs = dj.get("observaciones", {})
    obs_list = obs.get("observaciones", []) if isinstance(obs, dict) else []
    if obs_list:
        with st.expander(f"📝 Observaciones ({len(obs_list)})", expanded=True):
            for i, o in enumerate(obs_list, 1):
                if o:
                    st.markdown(f"{i}. {o}")

    # ── Fundamento legal ──────────────────────────────────────────
    fundamento = result.get("fundamento_legal") or dj.get("fundamento_legal")
    if fundamento:
        with st.expander("📖 Fundamento Legal", expanded=False):
            st.markdown(fundamento)

    # ── Reglas evaluadas ──────────────────────────────────────────
    reglas_list = reglas_data.get("reglas", [])
    if reglas_list:
        with st.expander(f"📋 Reglas Evaluadas ({len(reglas_list)})", expanded=False):
            for r in reglas_list:
                cumple = r.get("cumple", False)
                icon = "✅" if cumple else "❌"
                st.markdown(
                    f"{icon} **{r.get('codigo', '')}** — {r.get('nombre', '')}: "
                    f"{r.get('detalle', '')}"
                )

    # ── Dictamen texto completo ───────────────────────────────────
    dictamen_texto = result.get("dictamen_texto")
    if not dictamen_texto:
        # Intentar del JSON anidado
        dictamen_texto = result.get("dictamen_json", {}).get("dictamen_texto") if isinstance(result.get("dictamen_json"), dict) else None

    if dictamen_texto:
        with st.expander("📄 Dictamen Jurídico DJ-1 (texto completo)", expanded=False):
            st.code(dictamen_texto, language=None)
        st.download_button(
            "📥 Descargar Dictamen Jurídico DJ-1",
            data=dictamen_texto.encode("utf-8"),
            file_name=f"dictamen_juridico_{result.get('rfc', 'empresa')}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            mime="text/plain",
            use_container_width=True,
        )

    # ── JSON completo ─────────────────────────────────────────────
    with st.expander("📊 Dictamen completo (JSON)", expanded=False):
        st.json(dj)


def _show_pipeline_status(rfc: str) -> None:
    """Consulta y muestra el estado del pipeline por RFC."""
    with st.spinner("Consultando Orquestrador..."):
        data = get_pipeline_status(rfc)

    if not data:
        st.warning(f"No se encontró pipeline para RFC: {rfc}")
        return

    pipeline = data.get("pipeline", {})
    empresa = data.get("empresa", {})

    if empresa:
        st.markdown(f"**Empresa:** {empresa.get('razon_social', '—')} — RFC: {empresa.get('rfc', '—')}")

    if pipeline:
        st.markdown("**Estado del pipeline:**")
        cols = st.columns(5)
        steps = [
            ("Pipeline", pipeline.get("pipeline_status", "—")),
            ("Dakota", pipeline.get("dakota_status", "PENDIENTE")),
            ("Colorado", pipeline.get("colorado_status", "PENDIENTE")),
            ("Arizona", pipeline.get("arizona_status", "PENDIENTE")),
            ("Compliance", pipeline.get("nevada_status", "PENDIENTE")),
        ]
        for i, (label, status) in enumerate(steps):
            with cols[i]:
                if status == "COMPLETADO":
                    st.success(f"✅ {label}")
                elif status == "ERROR":
                    st.error(f"❌ {label}")
                elif status == "EN_PROCESO":
                    st.warning(f"⏳ {label}")
                else:
                    st.info(f"⬜ {label}")

        with st.expander("📊 Detalle completo", expanded=False):
            st.json(pipeline)

        tiempos = pipeline.get("tiempos_ms")
        if tiempos and isinstance(tiempos, dict):
            st.markdown("**Tiempos de ejecución:**")
            for k, v in tiempos.items():
                if isinstance(v, (int, float)):
                    st.caption(f"  {k}: {v/1000:.1f}s")


# ══════════════════════════════════════════════════════════════════════════════
#  RENDERIZADO DE RESULTADOS
# ══════════════════════════════════════════════════════════════════════════════

def _render_validacion(validacion: dict, reporte_txt: str | None, elapsed: float) -> None:
    """Renderiza resultado de validación cruzada de Colorado."""
    st.caption(f"Tiempo de análisis: {elapsed:.1f}s")

    dictamen = validacion.get("dictamen", "DESCONOCIDO")
    emoji = DICTAMEN_EMOJI.get(dictamen, "❓")
    dictamen_display = dictamen.replace("_", " ")

    css_class = {
        "APROBADO": "dictamen-aprobado",
        "APROBADO_CON_OBSERVACIONES": "dictamen-observaciones",
        "RECHAZADO": "dictamen-rechazado",
    }.get(dictamen, "")

    st.markdown(
        f'<div class="dictamen-box {css_class}">{emoji} Validación Cruzada: {dictamen_display}</div>',
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Hallazgos", validacion.get("total_hallazgos", len(validacion.get("hallazgos", []))))
    with col2:
        st.metric("Críticos", validacion.get("criticos", 0))
    with col3:
        st.metric("Portales SAT", "✅" if validacion.get("portales_ejecutados") else "—")

    if reporte_txt:
        with st.expander("📄 Reporte Colorado (texto)", expanded=False):
            st.code(reporte_txt, language=None)
        st.download_button(
            "📥 Descargar reporte Colorado",
            data=reporte_txt.encode("utf-8"),
            file_name=f"reporte_colorado_{validacion.get('rfc', 'empresa')}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
            mime="text/plain",
            use_container_width=True,
        )


def _render_pld(pld_result: dict, elapsed: float) -> None:
    """Renderiza resultado de análisis PLD/AML de Arizona."""
    st.caption(f"Tiempo de análisis: {elapsed:.1f}s")

    resultado = pld_result.get("resultado", "—")
    pct = pld_result.get("porcentaje_completitud", 0)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Resultado", resultado)
    with col2:
        st.metric("Completitud", f"{pct:.0f}%")
    with col3:
        st.metric("Items presentes", f"{pld_result.get('items_presentes', 0)}/{pld_result.get('total_items', 0)}")
    with col4:
        st.metric("Personas identificadas", len(pld_result.get("personas_identificadas", [])))

    if pld_result.get("tiene_poder_bancario") is not None:
        if pld_result["tiene_poder_bancario"]:
            st.success("✅ Poder bancario detectado")
        else:
            st.warning("⚠️ Sin poder bancario")

    faltantes = pld_result.get("items_faltantes_detalle", pld_result.get("items_faltantes", []))
    if faltantes and isinstance(faltantes, list) and len(faltantes) > 0:
        with st.expander(f"📋 Items faltantes ({len(faltantes)})", expanded=False):
            for item in faltantes:
                if isinstance(item, dict):
                    st.markdown(f"- **{item.get('nombre', item.get('campo', '?'))}** — {item.get('fuente', '')}")
                else:
                    st.markdown(f"- {item}")

    screening = pld_result.get("screening", pld_result.get("resultados_screening", {}))
    if screening:
        with st.expander("🔎 Resultados de screening (listas negras)", expanded=False):
            if isinstance(screening, dict):
                for persona, resultado_scr in screening.items():
                    if isinstance(resultado_scr, dict):
                        coincidencias = resultado_scr.get("coincidencias", 0)
                        if coincidencias > 0:
                            st.error(f"🔴 {persona}: {coincidencias} coincidencias")
                        else:
                            st.success(f"✅ {persona}: sin coincidencias")
                    else:
                        st.markdown(f"- {persona}: {resultado_scr}")
            else:
                st.json(screening)

    with st.expander("📊 Resultado PLD completo (JSON)", expanded=False):
        st.json(pld_result)


def _render_arizona_resultado(
    reporte_txt: str | None,
    dictamen_json: dict | None,
    dictamen_txt: str | None,
    elapsed: float,
) -> None:
    """Renderiza resultado completo de Arizona v2.3 (reporte + dictamen)."""
    st.caption(f"Tiempo de ejecución: {elapsed:.1f}s")

    # ── Encabezado con grado de riesgo ────────────────────────────────
    if dictamen_json:
        riesgo = dictamen_json.get("grado_riesgo_inicial", "—")
        pm = dictamen_json.get("persona_moral", {})
        rfc = pm.get("rfc", "—")

        bg, fg, border = NIVEL_RIESGO_COLOR.get(
            riesgo.upper() if isinstance(riesgo, str) else "",
            ("#e2e3e5", "#383d41", "#6c757d"),
        )
        st.markdown(
            f'<div class="risk-box" style="background:{bg}; color:{fg}; border:2px solid {border};">'
            f'🛡️ Dictamen PLD/FT — Grado de riesgo: <strong>{riesgo.upper()}</strong> '
            f'— RFC: <strong>{rfc}</strong>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── Métricas de resumen ───────────────────────────────────
        meta = dictamen_json.get("metadata", {})
        conclusiones = dictamen_json.get("conclusiones", {})
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Accionistas", len(dictamen_json.get("estructura_accionaria", [])))
        with col2:
            st.metric("Propietarios reales", len(dictamen_json.get("propietarios_reales", [])))
        with col3:
            st.metric("Representantes", len(dictamen_json.get("representantes_legales", [])))
        with col4:
            st.metric("Personas screened", meta.get("total_personas_screened", "—"))
        with col5:
            tiempo_ms = meta.get("tiempo_pipeline_ms", 0)
            st.metric("Tiempo pipeline", f"{tiempo_ms / 1000:.0f}s" if tiempo_ms else "—")

        # ── Datos de la persona moral ─────────────────────────────
        with st.expander("🏢 Datos de la Persona Moral", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Razón social:** {pm.get('razon_social', '—')}")
                st.markdown(f"**RFC:** {pm.get('rfc', '—')}")
                st.markdown(f"**Fecha constitución:** {pm.get('fecha_constitucion', '—')}")
                st.markdown(f"**Actividad económica:** {pm.get('actividad_economica', '—')}")
            with c2:
                st.markdown(f"**Domicilio:** {dictamen_json.get('domicilio', '—')}")
                st.markdown(f"**Uso de cuenta:** {dictamen_json.get('uso_cuenta', '—')}")
                folio = pm.get("folio_mercantil", "")
                if folio:
                    st.markdown(f"**Folio mercantil:** {folio}")
                clausula = pm.get("clausula_extranjeros", "")
                if clausula:
                    st.markdown(f"**Cláusula extranjeros:** {clausula}")
                notariales = pm.get("datos_notariales_acta", {})
                if notariales:
                    notario = notariales.get("notario", "")
                    esc = notariales.get("escritura", "")
                    if notario:
                        st.markdown(f"**Notario acta:** {notario}")
                    if esc:
                        st.markdown(f"**Escritura N°:** {esc}")

        # ── Estructura accionaria ─────────────────────────────────
        accionistas = dictamen_json.get("estructura_accionaria", [])
        if accionistas:
            with st.expander(f"📊 Estructura Accionaria ({len(accionistas)} accionistas)", expanded=False):
                rows = []
                for a in accionistas:
                    rows.append({
                        "#": a.get("numero", ""),
                        "Nombre": a.get("nombre_razon_social", ""),
                        "%": a.get("porcentaje_accionario", ""),
                        "RFC/CURP": a.get("rfc_curp", "N/D"),
                        "Tipo": a.get("tipo_persona", ""),
                        "Listas": a.get("coincidencia_listas", "NO"),
                    })
                st.dataframe(rows, hide_index=True, use_container_width=True)

        # ── Propietarios reales ───────────────────────────────────
        propietarios = dictamen_json.get("propietarios_reales", [])
        if propietarios:
            with st.expander(f"👤 Propietarios Reales / Beneficiarios Controladores ({len(propietarios)})", expanded=False):
                rows = []
                for p in propietarios:
                    rows.append({
                        "#": p.get("numero", ""),
                        "Nombre": p.get("nombre", ""),
                        "Tipo control": p.get("tipo_control", ""),
                        "RFC/CURP": p.get("rfc_curp", "N/D"),
                        "Listas": p.get("coincidencia_listas", "NO"),
                    })
                st.dataframe(rows, hide_index=True, use_container_width=True)

        # ── Representantes legales ────────────────────────────────
        representantes = dictamen_json.get("representantes_legales", [])
        detalle_poder = dictamen_json.get("detalle_poder_notarial", {})
        with st.expander(f"⚖️ Representantes Legales ({len(representantes)})", expanded=False):
            if representantes:
                for r in representantes:
                    st.markdown(f"**{r.get('nombre', '—')}** — CURP: `{r.get('rfc_curp', 'N/D')}` — Listas: {r.get('coincidencia_listas', 'NO')}")
            else:
                st.info("No se identificaron representantes legales.")
            if detalle_poder:
                st.markdown("---")
                st.markdown("**Poder notarial:**")
                tipo_p = detalle_poder.get("tipo_poder", "")
                if tipo_p:
                    st.markdown(f"- **Tipo:** {tipo_p}")
                notario_p = detalle_poder.get("notario", "")
                if notario_p:
                    st.markdown(f"- **Notario:** {notario_p}")
                esc_p = detalle_poder.get("escritura", "")
                if esc_p:
                    st.markdown(f"- **Escritura:** {esc_p}")
                fecha_p = detalle_poder.get("fecha", "")
                if fecha_p:
                    st.markdown(f"- **Fecha:** {fecha_p}")
                fac_p = detalle_poder.get("facultades", "")
                if fac_p:
                    st.markdown(f"- **Facultades:** {fac_p[:500]}{'…' if len(str(fac_p)) > 500 else ''}")

        # ── Perfil transaccional ──────────────────────────────────
        perfil = dictamen_json.get("perfil_transaccional", {})
        if perfil:
            with st.expander("🏦 Perfil Transaccional (Estado de Cuenta)", expanded=False):
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown(f"**Banco:** {perfil.get('banco', '—')}")
                    st.markdown(f"**Cuenta:** {perfil.get('cuenta', '—')}")
                    st.markdown(f"**CLABE:** {perfil.get('clabe', '—')}")
                with c2:
                    st.markdown(f"**Período:** {perfil.get('periodo', '—')}")
                    st.markdown(f"**Saldo inicial:** {perfil.get('saldo_inicial', '—')}")
                    st.markdown(f"**Saldo final:** {perfil.get('saldo_final', '—')}")
                with c3:
                    st.markdown(f"**Depósitos:** {perfil.get('total_depositos', '—')}")
                    st.markdown(f"**Retiros:** {perfil.get('total_retiros', '—')}")

        # ── Vigencia de documentos ────────────────────────────────
        vigencias = dictamen_json.get("vigencia_documentos", [])
        if vigencias:
            with st.expander(f"📅 Vigencia de Documentos ({len(vigencias)})", expanded=False):
                for v in vigencias:
                    doc = v.get("documento", "")
                    estado = v.get("estado", "")
                    detalle = v.get("detalle", "")
                    if "Vigente" in estado:
                        st.success(f"✅ **{doc}** — {estado} {detalle}")
                    elif "No vigente" in estado:
                        st.warning(f"⚠️ **{doc}** — {estado} {detalle}")
                    else:
                        st.info(f"❓ **{doc}** — {estado} {detalle}")

        # ── Conclusiones ──────────────────────────────────────────
        if conclusiones:
            with st.expander("📋 Conclusiones PLD/FT", expanded=False):
                st.markdown(f"- **Señales de alerta:** {'SÍ' if conclusiones.get('senales_alerta') else 'NO'}")
                st.markdown(f"- **Grado riesgo:** {conclusiones.get('grado_riesgo_confirmado', '—')}")
                edd = conclusiones.get("debida_diligencia_reforzada")
                st.markdown(f"- **DDR:** {'SÍ' if edd else 'NO'}")
                obs = conclusiones.get("observaciones", "")
                if obs:
                    st.markdown(f"- **Observaciones:** {obs[:1000]}")

    # ── Descargas: reporte.txt y dictamen_pld.txt ─────────────────
    st.markdown("---")
    st.markdown("**📥 Descargar documentos:**")
    dl_cols = st.columns(2)
    with dl_cols[0]:
        if reporte_txt:
            st.download_button(
                "📥 Reporte PLD (reporte.txt)",
                data=reporte_txt.encode("utf-8"),
                file_name=f"reporte_pld_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                mime="text/plain",
                use_container_width=True,
            )
    with dl_cols[1]:
        if dictamen_txt:
            st.download_button(
                "📥 Dictamen PLD/FT (dictamen_pld.txt)",
                data=dictamen_txt.encode("utf-8"),
                file_name=f"dictamen_pld_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                mime="text/plain",
                use_container_width=True,
            )

    # ── Expandibles con texto completo ────────────────────────────
    if reporte_txt:
        with st.expander("📄 Reporte PLD completo (texto)", expanded=False):
            st.code(reporte_txt, language=None)

    if dictamen_txt:
        with st.expander("📄 Dictamen PLD/FT completo (texto)", expanded=False):
            st.code(dictamen_txt, language=None)

    if dictamen_json:
        with st.expander("📊 Dictamen completo (JSON)", expanded=False):
            st.json(dictamen_json)


def _show_historial() -> None:
    """Muestra el historial de validaciones."""
    url = f"{COLORADO_URL}{COLORADO_PREFIX}/historial"
    try:
        with httpx.Client(timeout=15) as client:
            r = client.get(url, params={"limit": 20})
        if r.status_code != 200:
            st.warning("No se pudo obtener el historial.")
            return
        data = r.json()
    except Exception:
        st.warning("Colorado no está disponible para consultar historial.")
        return

    if not data:
        st.info("No hay validaciones registradas aún.")
        return

    rows = []
    for v in data:
        dictamen = v.get("dictamen", "")
        emoji = DICTAMEN_EMOJI.get(dictamen, "")
        rows.append({
            "Fecha": v.get("created_at", "")[:16],
            "RFC": v.get("rfc", ""),
            "Dictamen": f"{emoji} {dictamen.replace('_', ' ')}",
            "Hallazgos": v.get("total_hallazgos", 0),
            "Críticos": v.get("total_criticos", 0),
            "Portales": "✅" if v.get("portales_ejecutados") else "—",
        })

    st.dataframe(rows, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
