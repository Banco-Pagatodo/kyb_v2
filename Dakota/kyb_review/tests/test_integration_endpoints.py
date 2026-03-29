"""
Tests de integración para todos los endpoints de validación de documentos.

Estos tests realizan llamadas reales al pipeline completo (Azure DI + OpenAI).
Se omiten automáticamente si no hay credenciales de Azure configuradas.

Ejecutar sólo estos tests:
    pytest tests/test_integration_endpoints.py -v -m integration

Ejecutar un endpoint específico:
    pytest tests/test_integration_endpoints.py -v -k "csf"

Ejecutar cross-validation (documentos incorrectos):
    pytest tests/test_integration_endpoints.py -v -k "wrong"
"""

import os
import pytest
import httpx
from pathlib import Path
from fastapi.testclient import TestClient
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.parent
TEST_FILES_DIR = BASE_DIR / "Test_Files"

# Cargar variables desde api/service/.env si existen
_env_file = BASE_DIR / "api" / "service" / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)

# Credenciales requeridas para tests de integración
# La API usa DI_KEY y AZURE_OPENAI_API_KEY
_AZURE_DI_KEY = os.getenv("DI_KEY", "")
_AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
_HAS_AZURE = bool(_AZURE_DI_KEY and _AZURE_OPENAI_KEY)

pytestmark = pytest.mark.integration

skip_no_azure = pytest.mark.skipif(
    not _HAS_AZURE,
    reason="Credenciales Azure no configuradas (DI_KEY / AZURE_OPENAI_API_KEY)"
)

# ---------------------------------------------------------------------------
# Catálogo de archivos de prueba
# ---------------------------------------------------------------------------

CSF_FILES = sorted((TEST_FILES_DIR / "Constancia_Situacion_Fiscal").glob("*.pdf"))
ACTA_FILES = sorted((TEST_FILES_DIR / "Acta_Constitutiva").glob("*.pdf"))
COMPROBANTE_FILES = sorted((TEST_FILES_DIR / "Comprobante_Domicilio").glob("*.pdf"))
INE_FILES = sorted((TEST_FILES_DIR / "INE").glob("*.pdf"))
INE_BACK_FILES = sorted((TEST_FILES_DIR / "INE_back").glob("*.pdf"))
PODER_FILES = sorted((TEST_FILES_DIR / "Poder_Notarial").glob("*.pdf"))
REFORMA_FILES = sorted((TEST_FILES_DIR / "Reforma_Estatutos").glob("*.pdf"))
ESTADO_FILES = sorted((TEST_FILES_DIR / "Estado_Cuenta").glob("*.pdf"))
FIEL_FILES = sorted((TEST_FILES_DIR / "Fiel").glob("*.pdf"))

# Archivos representativos para cross-validation (sólo uno de cada tipo)
# para evitar una explosión de combinaciones en ci.
_CROSS_CSF = CSF_FILES[0] if CSF_FILES else None
_CROSS_ACTA = ACTA_FILES[0] if ACTA_FILES else None
_CROSS_PODER = PODER_FILES[0] if PODER_FILES else None
_CROSS_INE = INE_FILES[0] if INE_FILES else None
_CROSS_DOMICILIO = COMPROBANTE_FILES[0] if COMPROBANTE_FILES else None

# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def client():
    """TestClient con la app FastAPI completa (en proceso)."""
    from api.main import app  # importación diferida para no fallar si no hay .env
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = "/kyb/api/v1.0.0/docs"
HEALTH_URL = "/kyb/api/v1.0.0/health"


def _post_file(client: TestClient, endpoint: str, filepath: Path) -> httpx.Response:
    """Envía un PDF al endpoint indicado."""
    with open(filepath, "rb") as f:
        return client.post(
            f"{BASE_URL}/{endpoint}",
            files={"file": (filepath.name, f, "application/pdf")},
        )


def _assert_response_schema(data: dict) -> None:
    """Verifica que la respuesta contenga los bloques esperados."""
    assert "document_identification" in data, f"Falta 'document_identification' en: {list(data.keys())}"
    assert "kyb_compliance" in data, f"Falta 'kyb_compliance' en: {list(data.keys())}"
    assert "resumen" in data, f"Falta 'resumen' en: {list(data.keys())}"

    ident = data["document_identification"]
    assert "is_correct" in ident, f"Falta 'is_correct' en document_identification: {ident}"
    assert "expected_type" in ident
    assert "reasoning" in ident
    assert "should_reject" in ident

    kyb = data["kyb_compliance"]
    assert "status" in kyb
    assert "compliance_score" in kyb
    assert "errores" in kyb

    resumen = data["resumen"]
    assert "verdict" in resumen
    assert resumen["verdict"] in ("APROBADO", "REVISION_REQUERIDA", "RECHAZADO",
                                   "APPROVED", "REVIEW_REQUIRED", "REJECTED")


def _assert_correct_type(data: dict, endpoint: str) -> None:
    """El documento debería ser reconocido como el tipo correcto."""
    ident = data["document_identification"]
    assert ident["is_correct"] is True, (
        f"[{endpoint}] Se esperaba is_correct=True.\n"
        f"  reasoning: {ident.get('reasoning')}\n"
        f"  compliance_score: {data['kyb_compliance'].get('compliance_score')}"
    )
    assert ident["should_reject"] is False


def _assert_wrong_type(data: dict, endpoint: str, file_desc: str) -> None:
    """El documento debería ser rechazado por ser del tipo incorrecto."""
    ident = data["document_identification"]
    assert ident["is_correct"] is False, (
        f"[{endpoint}] '{file_desc}' debería detectarse como tipo incorrecto.\n"
        f"  reasoning: {ident.get('reasoning')}"
    )
    assert ident["should_reject"] is True
    assert "correcto" in ident["reasoning"].lower() or "corresponde" in ident["reasoning"].lower(), (
        f"Mensaje de reasoning no es claro: {ident['reasoning']}"
    )
    kyb = data["kyb_compliance"]
    assert kyb["compliance_score"] == 0.0, (
        f"compliance_score debe ser 0 para documento incorrecto, obtenido: {kyb['compliance_score']}"
    )
    assert len(kyb["errores"]) > 0, "Debe haber al menos un error cuando el tipo es incorrecto"


# ---------------------------------------------------------------------------
# Verificar que los archivos existen
# ---------------------------------------------------------------------------

def test_test_files_exist():
    """Verifica que todos los directorios de Test_Files tienen archivos."""
    assert len(CSF_FILES) > 0, "No hay PDFs en Constancia_Situacion_Fiscal/"
    assert len(ACTA_FILES) > 0, "No hay PDFs en Acta_Constitutiva/"
    assert len(COMPROBANTE_FILES) > 0, "No hay PDFs en Comprobante_Domicilio/"
    assert len(INE_FILES) > 0, "No hay PDFs en INE/"
    assert len(INE_BACK_FILES) > 0, "No hay PDFs en INE_back/"
    assert len(PODER_FILES) > 0, "No hay PDFs en Poder_Notarial/"
    assert len(REFORMA_FILES) > 0, "No hay PDFs en Reforma_Estatutos/"
    assert len(ESTADO_FILES) > 0, "No hay PDFs en Estado_Cuenta/"
    assert len(FIEL_FILES) > 0, "No hay PDFs en Fiel/"


# ===========================================================================
# CSF
# ===========================================================================

class TestCSFEndpoint:
    """Tests para /docs/csf"""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", CSF_FILES, ids=[f.name for f in CSF_FILES])
    def test_csf_correct_files(self, client, pdf_path):
        """Todos los archivos CSF deben ser aceptados como tipo correcto."""
        resp = _post_file(client, "csf", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
        data = resp.json()
        _assert_response_schema(data)
        _assert_correct_type(data, "csf")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", [_CROSS_ACTA, _CROSS_PODER], ids=["acta", "poder"])
    def test_csf_wrong_document_type(self, client, pdf_path):
        """Subir Acta o Poder al endpoint CSF debe rechazarse."""
        if pdf_path is None:
            pytest.skip("Archivo no disponible")
        resp = _post_file(client, "csf", pdf_path)
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_schema(data)
        _assert_wrong_type(data, "csf", pdf_path.name)

    def test_csf_empty_file(self, client):
        """Un archivo vacío debe devolver 400 o un error controlado."""
        resp = client.post(
            f"{BASE_URL}/csf",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code in (400, 415, 422, 500), f"Inesperado: {resp.status_code}"

    def test_csf_invalid_mime(self, client):
        """Un archivo .exe no debe superar los guardrails."""
        resp = client.post(
            f"{BASE_URL}/csf",
            files={"file": ("malware.exe", b"MZ\x90\x00" * 10, "application/octet-stream")},
        )
        assert resp.status_code in (400, 415, 422), f"Guardrail debería rechazar: {resp.status_code}"

    def test_csf_response_schema(self, client):
        """Verificar que la respuesta tiene todos los campos requeridos (con archivo real si hay Azure)."""
        if not _HAS_AZURE or not CSF_FILES:
            pytest.skip("Requiere Azure + archivos")
        resp = _post_file(client, "csf", CSF_FILES[0])
        assert resp.status_code == 200
        _assert_response_schema(resp.json())


# ===========================================================================
# Acta Constitutiva
# ===========================================================================

class TestActaConstitutiva:
    """Tests para /docs/acta_constitutiva"""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", ACTA_FILES, ids=[f.name for f in ACTA_FILES])
    def test_acta_correct_files(self, client, pdf_path):
        """Todos los archivos de Acta deben ser aceptados."""
        resp = _post_file(client, "acta_constitutiva", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
        data = resp.json()
        _assert_response_schema(data)
        _assert_correct_type(data, "acta_constitutiva")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", [_CROSS_CSF, _CROSS_INE], ids=["csf", "ine"])
    def test_acta_wrong_document_type(self, client, pdf_path):
        """CSF o INE en endpoint de Acta debe rechazarse."""
        if pdf_path is None:
            pytest.skip("Archivo no disponible")
        resp = _post_file(client, "acta_constitutiva", pdf_path)
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_schema(data)
        _assert_wrong_type(data, "acta_constitutiva", pdf_path.name)

    def test_acta_empty_file(self, client):
        """Archivo vacío debe ser rechazado."""
        resp = client.post(
            f"{BASE_URL}/acta_constitutiva",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code in (400, 415, 422, 500)


# ===========================================================================
# Poder Notarial
# ===========================================================================

class TestPoderNotarial:
    """Tests para /docs/poder_notarial"""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", PODER_FILES, ids=[f.name for f in PODER_FILES])
    def test_poder_correct_files(self, client, pdf_path):
        """Todos los archivos de Poder deben ser aceptados."""
        resp = _post_file(client, "poder_notarial", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
        data = resp.json()
        _assert_response_schema(data)
        _assert_correct_type(data, "poder_notarial")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", [_CROSS_CSF, _CROSS_DOMICILIO], ids=["csf", "domicilio"])
    def test_poder_wrong_document_type(self, client, pdf_path):
        """CSF o Comprobante en endpoint de Poder debe rechazarse."""
        if pdf_path is None:
            pytest.skip("Archivo no disponible")
        resp = _post_file(client, "poder_notarial", pdf_path)
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_schema(data)
        _assert_wrong_type(data, "poder_notarial", pdf_path.name)

    def test_poder_empty_file(self, client):
        resp = client.post(
            f"{BASE_URL}/poder_notarial",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code in (400, 415, 422, 500)


# ===========================================================================
# Comprobante de Domicilio
# ===========================================================================

class TestComprobanteDomicilio:
    """Tests para /docs/domicilio"""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", COMPROBANTE_FILES, ids=[f.name for f in COMPROBANTE_FILES])
    def test_domicilio_correct_files(self, client, pdf_path):
        """Todos los comprobantes de domicilio deben aceptarse."""
        resp = _post_file(client, "domicilio", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
        data = resp.json()
        _assert_response_schema(data)
        _assert_correct_type(data, "domicilio")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", [_CROSS_ACTA], ids=["acta"])
    def test_domicilio_wrong_document_type(self, client, pdf_path):
        """Acta en endpoint de Domicilio debe rechazarse.
        Nota: CSF se acepta como comprobante de domicilio (contiene domicilio fiscal).
        """
        if pdf_path is None:
            pytest.skip("Archivo no disponible")
        resp = _post_file(client, "domicilio", pdf_path)
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_schema(data)
        _assert_wrong_type(data, "domicilio", pdf_path.name)

    def test_domicilio_empty_file(self, client):
        resp = client.post(
            f"{BASE_URL}/domicilio",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code in (400, 415, 422, 500)


# ===========================================================================
# INE (anverso)
# ===========================================================================

class TestINEEndpoint:
    """Tests para /docs/ine"""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", INE_FILES, ids=[f.name for f in INE_FILES])
    def test_ine_correct_files(self, client, pdf_path):
        """Todas las INE de anverso deben aceptarse."""
        resp = _post_file(client, "ine", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
        data = resp.json()
        _assert_response_schema(data)
        _assert_correct_type(data, "ine")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", [_CROSS_CSF, _CROSS_ACTA], ids=["csf", "acta"])
    def test_ine_wrong_document_type(self, client, pdf_path):
        """CSF o Acta en endpoint de INE debe rechazarse."""
        if pdf_path is None:
            pytest.skip("Archivo no disponible")
        resp = _post_file(client, "ine", pdf_path)
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_schema(data)
        _assert_wrong_type(data, "ine", pdf_path.name)

    def test_ine_empty_file(self, client):
        resp = client.post(
            f"{BASE_URL}/ine",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code in (400, 415, 422, 500)


# ===========================================================================
# INE (reverso)
# ===========================================================================

class TestINEReverso:
    """Tests para /docs/ine_reverso"""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", INE_BACK_FILES, ids=[f.name for f in INE_BACK_FILES])
    def test_ine_reverso_correct_files(self, client, pdf_path):
        """Todos los reversos de INE deben aceptarse."""
        resp = _post_file(client, "ine_reverso", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
        data = resp.json()
        _assert_response_schema(data)
        _assert_correct_type(data, "ine_reverso")

    @skip_no_azure
    def test_ine_reverso_wrong_type_csf(self, client):
        """CSF en endpoint de INE reverso debe rechazarse."""
        if _CROSS_CSF is None:
            pytest.skip("Archivo no disponible")
        resp = _post_file(client, "ine_reverso", _CROSS_CSF)
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_schema(data)
        _assert_wrong_type(data, "ine_reverso", _CROSS_CSF.name)

    def test_ine_reverso_empty_file(self, client):
        resp = client.post(
            f"{BASE_URL}/ine_reverso",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code in (400, 415, 422, 500)


# ===========================================================================
# Estado de Cuenta
# ===========================================================================

class TestEstadoCuenta:
    """Tests para /docs/estado_cuenta"""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", ESTADO_FILES, ids=[f.name for f in ESTADO_FILES])
    def test_estado_cuenta_correct_files(self, client, pdf_path):
        """Todos los estados de cuenta deben aceptarse."""
        resp = _post_file(client, "estado_cuenta", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
        data = resp.json()
        _assert_response_schema(data)
        _assert_correct_type(data, "estado_cuenta")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", [_CROSS_CSF, _CROSS_ACTA], ids=["csf", "acta"])
    def test_estado_cuenta_wrong_document_type(self, client, pdf_path):
        """CSF o Acta en endpoint de Estado de Cuenta debe rechazarse."""
        if pdf_path is None:
            pytest.skip("Archivo no disponible")
        resp = _post_file(client, "estado_cuenta", pdf_path)
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_schema(data)
        _assert_wrong_type(data, "estado_cuenta", pdf_path.name)

    def test_estado_cuenta_empty_file(self, client):
        resp = client.post(
            f"{BASE_URL}/estado_cuenta",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code in (400, 415, 422, 500)


# ===========================================================================
# FIEL
# ===========================================================================

class TestFIELEndpoint:
    """Tests para /docs/fiel"""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", FIEL_FILES, ids=[f.name for f in FIEL_FILES])
    def test_fiel_correct_files(self, client, pdf_path):
        """Todos los acuses de FIEL deben aceptarse."""
        resp = _post_file(client, "fiel", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
        data = resp.json()
        _assert_response_schema(data)
        _assert_correct_type(data, "fiel")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", [_CROSS_CSF, _CROSS_INE], ids=["csf", "ine"])
    def test_fiel_wrong_document_type(self, client, pdf_path):
        """CSF o INE en endpoint de FIEL debe rechazarse."""
        if pdf_path is None:
            pytest.skip("Archivo no disponible")
        resp = _post_file(client, "fiel", pdf_path)
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_schema(data)
        _assert_wrong_type(data, "fiel", pdf_path.name)

    def test_fiel_empty_file(self, client):
        resp = client.post(
            f"{BASE_URL}/fiel",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code in (400, 415, 422, 500)


# ===========================================================================
# Reforma de Estatutos
# ===========================================================================

class TestReformaEstatutos:
    """Tests para /docs/reforma_estatutos"""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", REFORMA_FILES, ids=[f.name for f in REFORMA_FILES])
    def test_reforma_correct_files(self, client, pdf_path):
        """Todos los archivos de Reforma deben aceptarse."""
        resp = _post_file(client, "reforma_estatutos", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
        data = resp.json()
        _assert_response_schema(data)
        _assert_correct_type(data, "reforma_estatutos")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", [_CROSS_CSF, _CROSS_INE], ids=["csf", "ine"])
    def test_reforma_wrong_document_type(self, client, pdf_path):
        """CSF o INE en endpoint de Reforma debe rechazarse."""
        if pdf_path is None:
            pytest.skip("Archivo no disponible")
        resp = _post_file(client, "reforma_estatutos", pdf_path)
        assert resp.status_code == 200
        data = resp.json()
        _assert_response_schema(data)
        _assert_wrong_type(data, "reforma_estatutos", pdf_path.name)

    def test_reforma_empty_file(self, client):
        resp = client.post(
            f"{BASE_URL}/reforma_estatutos",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code in (400, 415, 422, 500)


# ===========================================================================
# Cross-validation matrix
# ===========================================================================

# Tabla completa: (archivo_origen, endpoint_destino) — combinaciones de tipo incorrecto
_CROSS_MATRIX = [
    # CSF subido a cada endpoint incorrecto
    pytest.param(_CROSS_CSF, "acta_constitutiva", id="csf→acta"),
    pytest.param(_CROSS_CSF, "poder_notarial",    id="csf→poder"),
    # CSF se acepta como domicilio (alternativa válida), no incluir en cross-validation
    pytest.param(_CROSS_CSF, "ine",                id="csf→ine"),
    pytest.param(_CROSS_CSF, "reforma_estatutos",  id="csf→reforma"),
    pytest.param(_CROSS_CSF, "estado_cuenta",      id="csf→estado_cuenta"),
    pytest.param(_CROSS_CSF, "fiel",               id="csf→fiel"),
    # Acta subida a cada endpoint incorrecto
    pytest.param(_CROSS_ACTA, "csf",               id="acta→csf"),
    pytest.param(_CROSS_ACTA, "domicilio",          id="acta→domicilio"),
    pytest.param(_CROSS_ACTA, "ine",                id="acta→ine"),
    # INE subida a endpoints incompatibles
    pytest.param(_CROSS_INE, "csf",                id="ine→csf"),
    pytest.param(_CROSS_INE, "acta_constitutiva",  id="ine→acta"),
    pytest.param(_CROSS_INE, "poder_notarial",     id="ine→poder"),
    # Comprobante subido a endpoints incompatibles
    pytest.param(_CROSS_DOMICILIO, "csf",          id="domicilio→csf"),
    pytest.param(_CROSS_DOMICILIO, "ine",          id="domicilio→ine"),
    # Poder subido a endpoints incompatibles
    pytest.param(_CROSS_PODER, "csf",              id="poder→csf"),
    pytest.param(_CROSS_PODER, "ine",              id="poder→ine"),
]


@skip_no_azure
@pytest.mark.parametrize("pdf_path,endpoint", _CROSS_MATRIX)
def test_cross_validation_matrix(client, pdf_path, endpoint):
    """
    Matriz de cross-validation: cada tipo de documento en un endpoint incorrecto.
    El sistema DEBE rechazar el documento con is_correct=False y compliance_score=0.
    """
    if pdf_path is None:
        pytest.skip("Archivo no disponible")

    resp = _post_file(client, endpoint, pdf_path)
    assert resp.status_code == 200, (
        f"[{pdf_path.name} → {endpoint}] HTTP {resp.status_code}: {resp.text[:300]}"
    )
    data = resp.json()
    _assert_response_schema(data)
    _assert_wrong_type(data, endpoint, pdf_path.name)


# ===========================================================================
# Health / estructura básica (sin Azure)
# ===========================================================================

class TestAPIHealth:
    """Tests de disponibilidad de la API que no requieren Azure."""

    def test_health_endpoint(self, client):
        """El endpoint de health debe responder 200."""
        resp = client.get(HEALTH_URL)
        assert resp.status_code == 200

    def test_metrics_endpoint(self, client):
        """El endpoint de métricas debe responder 200."""
        resp = client.get(f"{BASE_URL}/metrics")
        assert resp.status_code == 200

    def test_invalid_endpoint_returns_404(self, client):
        """Un endpoint inexistente debe devolver 404."""
        resp = client.post(f"{BASE_URL}/nonexistent_doc_type",
                           files={"file": ("f.pdf", b"%PDF-1", "application/pdf")})
        assert resp.status_code == 404

    @pytest.mark.parametrize("endpoint", [
        "csf", "acta_constitutiva", "poder_notarial", "domicilio",
        "ine", "ine_reverso", "estado_cuenta", "fiel", "reforma_estatutos"
    ])
    def test_all_endpoints_accept_pdf_mime(self, client, endpoint):
        """
        Todos los endpoints deben responder (no 404/405) a un PDF aunque sea corrupto.
        El guardrail puede rechazarlo con 400 pero no debe haber 404/405.
        """
        resp = client.post(
            f"{BASE_URL}/{endpoint}",
            files={"file": ("test.pdf", b"%PDF-1.4 corrupt", "application/pdf")},
        )
        assert resp.status_code != 404, f"Endpoint /{endpoint} no existe (404)"
        assert resp.status_code != 405, f"Endpoint /{endpoint} no acepta POST (405)"
