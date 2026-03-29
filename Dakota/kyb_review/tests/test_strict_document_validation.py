"""
Tests ESTRICTOS de validación de documentos.

Cada endpoint se prueba contra TODOS los archivos de su carpeta correcta
(positivos) y contra TODOS los archivos de TODAS las carpetas incorrectas
(negativos).  Si la API acepta un documento incorrecto o rechaza uno correcto,
el test FALLA con el response completo para depuración.

Ejecutar:
    pytest tests/test_strict_document_validation.py -v -m integration
    pytest tests/test_strict_document_validation.py -v -k "acta"
    pytest tests/test_strict_document_validation.py -v -k "negative"
"""

import json
import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.parent
TEST_FILES_DIR = BASE_DIR / "Test_Files"

_env_file = BASE_DIR / "api" / "service" / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)

_HAS_AZURE = bool(os.getenv("DI_KEY", "")) and bool(os.getenv("AZURE_OPENAI_API_KEY", ""))

pytestmark = pytest.mark.integration

skip_no_azure = pytest.mark.skipif(
    not _HAS_AZURE,
    reason="Credenciales Azure no configuradas (DI_KEY / AZURE_OPENAI_API_KEY)",
)

# ---------------------------------------------------------------------------
# Catálogo de carpetas → endpoint
# ---------------------------------------------------------------------------

FOLDER_ENDPOINT_MAP = {
    "Acta_Constitutiva":          "acta_constitutiva",
    "Constancia_Situacion_Fiscal": "csf",
    "Comprobante_Domicilio":       "domicilio",
    "Estado_Cuenta":               "estado_cuenta",
    "Fiel":                        "fiel",
    "INE":                         "ine",
    "INE_back":                    "ine_reverso",
    "Poder_Notarial":              "poder_notarial",
    "Reforma_Estatutos":           "reforma_estatutos",
}

ALL_FOLDERS = list(FOLDER_ENDPOINT_MAP.keys())

def _files_in(folder: str) -> list[Path]:
    return sorted((TEST_FILES_DIR / folder).glob("*.pdf"))

# Pre-cargar listados para parametrize
_FILE_LISTS: dict[str, list[Path]] = {f: _files_in(f) for f in ALL_FOLDERS}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_URL = "/kyb/api/v1.0.0/docs"

@pytest.fixture(scope="session")
def client():
    from api.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _post(client: TestClient, endpoint: str, filepath: Path):
    with open(filepath, "rb") as f:
        return client.post(
            f"{BASE_URL}/{endpoint}",
            files={"file": (filepath.name, f, "application/pdf")},
        )

# ---------------------------------------------------------------------------
# Helpers de aserción
# ---------------------------------------------------------------------------

def _dump(data: dict) -> str:
    """Pretty-print truncado a 2000 chars para mensajes de error."""
    txt = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    return txt[:2000] + ("..." if len(txt) > 2000 else "")


def assert_accepted(data: dict, filename: str, endpoint: str):
    """El documento DEBE ser aceptado como tipo correcto."""
    ident = data.get("document_identification", {})
    resumen = data.get("resumen", {})

    assert ident.get("is_correct") is True, (
        f"FAIL POSITIVO | {filename} → /{endpoint}\n"
        f"  is_correct={ident.get('is_correct')}  should_reject={ident.get('should_reject')}\n"
        f"  reasoning: {ident.get('reasoning')}\n"
        f"  RESPONSE:\n{_dump(data)}"
    )
    assert ident.get("should_reject") is False, (
        f"FAIL POSITIVO | {filename} → /{endpoint}\n"
        f"  should_reject=True pero debería ser False\n"
        f"  reasoning: {ident.get('reasoning')}\n"
        f"  RESPONSE:\n{_dump(data)}"
    )
    # El veredicto final debe ser APROBADO o REVISION_REQUERIDA (nunca RECHAZADO)
    assert resumen.get("verdict") in ("APROBADO", "REVISION_REQUERIDA"), (
        f"FAIL POSITIVO | {filename} → /{endpoint}\n"
        f"  verdict={resumen.get('verdict')} (esperado APROBADO o REVISION_REQUERIDA)\n"
        f"  RESPONSE:\n{_dump(data)}"
    )


def assert_rejected(data: dict, filename: str, source_folder: str, endpoint: str):
    """El documento DEBE ser rechazado por tipo incorrecto."""
    ident = data.get("document_identification", {})
    kyb = data.get("kyb_compliance", {})

    assert ident.get("is_correct") is False, (
        f"BUG | {filename} (de {source_folder}) ACEPTADO en /{endpoint}\n"
        f"  is_correct=True — debería ser False!\n"
        f"  reasoning: {ident.get('reasoning')}\n"
        f"  RESPONSE:\n{_dump(data)}"
    )
    assert ident.get("should_reject") is True, (
        f"BUG | {filename} (de {source_folder}) no marcado para rechazo en /{endpoint}\n"
        f"  should_reject=False — debería ser True!\n"
        f"  reasoning: {ident.get('reasoning')}\n"
        f"  RESPONSE:\n{_dump(data)}"
    )
    assert kyb.get("compliance_score") == 0.0, (
        f"BUG | {filename} (de {source_folder}) en /{endpoint} tiene compliance_score "
        f"= {kyb.get('compliance_score')} — debería ser 0.0\n"
        f"  RESPONSE:\n{_dump(data)}"
    )
    assert len(kyb.get("errores", [])) > 0, (
        f"BUG | {filename} (de {source_folder}) rechazado sin errores en /{endpoint}\n"
        f"  errores está vacío pero debería informar el problema\n"
        f"  RESPONSE:\n{_dump(data)}"
    )


# =====================================================================
# 0. Verificar que existen archivos de prueba
# =====================================================================

def test_all_test_folders_have_files():
    """Cada carpeta de Test_Files debe contener al menos un PDF."""
    for folder in ALL_FOLDERS:
        files = _FILE_LISTS[folder]
        assert len(files) > 0, f"No hay PDFs en Test_Files/{folder}/"


# =====================================================================
#  MACRO para generar clases de test por endpoint
# =====================================================================
# En lugar de copiar+pegar la misma estructura 9 veces, la generamos
# dinámicamente.  Cada endpoint recibe:
#   - tests positivos: TODOS los archivos de su carpeta correcta
#   - tests negativos: primer archivo de CADA carpeta incorrecta
# =====================================================================


def _make_positive_params(folder: str):
    """Parametrize IDs para los archivos correctos."""
    files = _FILE_LISTS.get(folder, [])
    return [pytest.param(f, id=f.name) for f in files]


def _make_negative_params(correct_folder: str):
    """Parametrize IDs para un archivo de cada carpeta INCORRECTA."""
    params = []
    for folder in ALL_FOLDERS:
        if folder == correct_folder:
            continue
        files = _FILE_LISTS.get(folder, [])
        if not files:
            continue
        # Primer archivo de cada carpeta incorrecta
        params.append(pytest.param(files[0], folder, id=f"{folder}/{files[0].name}"))
    return params


def _make_negative_all_files_params(correct_folder: str):
    """Parametrize IDs para TODOS los archivos de TODAS las carpetas incorrectas."""
    params = []
    for folder in ALL_FOLDERS:
        if folder == correct_folder:
            continue
        files = _FILE_LISTS.get(folder, [])
        for f in files:
            params.append(pytest.param(f, folder, id=f"{folder}/{f.name}"))
    return params


# =====================================================================
# 1. ACTA CONSTITUTIVA
# =====================================================================

class TestActaConstitutivaStrict:
    """Endpoint /docs/acta_constitutiva — tests estrictos."""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", _make_positive_params("Acta_Constitutiva"))
    def test_positive_accepts_all_acta_files(self, client, pdf_path):
        resp = _post(client, "acta_constitutiva", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_accepted(resp.json(), pdf_path.name, "acta_constitutiva")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path,source_folder", _make_negative_all_files_params("Acta_Constitutiva"))
    def test_negative_rejects_all_non_acta_files(self, client, pdf_path, source_folder):
        resp = _post(client, "acta_constitutiva", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_rejected(resp.json(), pdf_path.name, source_folder, "acta_constitutiva")


# =====================================================================
# 2. CONSTANCIA DE SITUACIÓN FISCAL
# =====================================================================

class TestCSFStrict:
    """Endpoint /docs/csf — tests estrictos."""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", _make_positive_params("Constancia_Situacion_Fiscal"))
    def test_positive_accepts_all_csf_files(self, client, pdf_path):
        resp = _post(client, "csf", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_accepted(resp.json(), pdf_path.name, "csf")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path,source_folder", _make_negative_all_files_params("Constancia_Situacion_Fiscal"))
    def test_negative_rejects_all_non_csf_files(self, client, pdf_path, source_folder):
        resp = _post(client, "csf", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_rejected(resp.json(), pdf_path.name, source_folder, "csf")


# =====================================================================
# 3. COMPROBANTE DE DOMICILIO
# =====================================================================

class TestComprobanteDomicilioStrict:
    """Endpoint /docs/domicilio — tests estrictos."""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", _make_positive_params("Comprobante_Domicilio"))
    def test_positive_accepts_all_domicilio_files(self, client, pdf_path):
        resp = _post(client, "domicilio", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_accepted(resp.json(), pdf_path.name, "domicilio")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path,source_folder", _make_negative_all_files_params("Comprobante_Domicilio"))
    def test_negative_rejects_all_non_domicilio_files(self, client, pdf_path, source_folder):
        resp = _post(client, "domicilio", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_rejected(resp.json(), pdf_path.name, source_folder, "domicilio")


# =====================================================================
# 4. ESTADO DE CUENTA
# =====================================================================

class TestEstadoCuentaStrict:
    """Endpoint /docs/estado_cuenta — tests estrictos."""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", _make_positive_params("Estado_Cuenta"))
    def test_positive_accepts_all_estado_files(self, client, pdf_path):
        resp = _post(client, "estado_cuenta", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_accepted(resp.json(), pdf_path.name, "estado_cuenta")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path,source_folder", _make_negative_all_files_params("Estado_Cuenta"))
    def test_negative_rejects_all_non_estado_files(self, client, pdf_path, source_folder):
        resp = _post(client, "estado_cuenta", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_rejected(resp.json(), pdf_path.name, source_folder, "estado_cuenta")


# =====================================================================
# 5. FIEL
# =====================================================================

class TestFIELStrict:
    """Endpoint /docs/fiel — tests estrictos."""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", _make_positive_params("Fiel"))
    def test_positive_accepts_all_fiel_files(self, client, pdf_path):
        resp = _post(client, "fiel", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_accepted(resp.json(), pdf_path.name, "fiel")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path,source_folder", _make_negative_all_files_params("Fiel"))
    def test_negative_rejects_all_non_fiel_files(self, client, pdf_path, source_folder):
        resp = _post(client, "fiel", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_rejected(resp.json(), pdf_path.name, source_folder, "fiel")


# =====================================================================
# 6. INE (anverso)
# =====================================================================

class TestINEStrict:
    """Endpoint /docs/ine — tests estrictos."""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", _make_positive_params("INE"))
    def test_positive_accepts_all_ine_files(self, client, pdf_path):
        resp = _post(client, "ine", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_accepted(resp.json(), pdf_path.name, "ine")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path,source_folder", _make_negative_all_files_params("INE"))
    def test_negative_rejects_all_non_ine_files(self, client, pdf_path, source_folder):
        resp = _post(client, "ine", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_rejected(resp.json(), pdf_path.name, source_folder, "ine")


# =====================================================================
# 7. INE REVERSO
# =====================================================================

class TestINEReversoStrict:
    """Endpoint /docs/ine_reverso — tests estrictos."""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", _make_positive_params("INE_back"))
    def test_positive_accepts_all_ine_reverso_files(self, client, pdf_path):
        resp = _post(client, "ine_reverso", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_accepted(resp.json(), pdf_path.name, "ine_reverso")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path,source_folder", _make_negative_all_files_params("INE_back"))
    def test_negative_rejects_all_non_ine_reverso_files(self, client, pdf_path, source_folder):
        resp = _post(client, "ine_reverso", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_rejected(resp.json(), pdf_path.name, source_folder, "ine_reverso")


# =====================================================================
# 8. PODER NOTARIAL
# =====================================================================

class TestPoderNotarialStrict:
    """Endpoint /docs/poder_notarial — tests estrictos."""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", _make_positive_params("Poder_Notarial"))
    def test_positive_accepts_all_poder_files(self, client, pdf_path):
        resp = _post(client, "poder_notarial", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_accepted(resp.json(), pdf_path.name, "poder_notarial")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path,source_folder", _make_negative_all_files_params("Poder_Notarial"))
    def test_negative_rejects_all_non_poder_files(self, client, pdf_path, source_folder):
        resp = _post(client, "poder_notarial", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_rejected(resp.json(), pdf_path.name, source_folder, "poder_notarial")


# =====================================================================
# 9. REFORMA DE ESTATUTOS
# =====================================================================

class TestReformaEstatutosStrict:
    """Endpoint /docs/reforma_estatutos — tests estrictos."""

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path", _make_positive_params("Reforma_Estatutos"))
    def test_positive_accepts_all_reforma_files(self, client, pdf_path):
        resp = _post(client, "reforma_estatutos", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_accepted(resp.json(), pdf_path.name, "reforma_estatutos")

    @skip_no_azure
    @pytest.mark.parametrize("pdf_path,source_folder", _make_negative_all_files_params("Reforma_Estatutos"))
    def test_negative_rejects_all_non_reforma_files(self, client, pdf_path, source_folder):
        resp = _post(client, "reforma_estatutos", pdf_path)
        assert resp.status_code == 200, f"HTTP {resp.status_code} para {pdf_path.name}: {resp.text[:500]}"
        assert_rejected(resp.json(), pdf_path.name, source_folder, "reforma_estatutos")
