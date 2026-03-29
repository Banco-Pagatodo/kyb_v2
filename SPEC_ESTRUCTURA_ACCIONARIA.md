# Especificación Técnica: Estructura Accionaria y Propietarios Reales

> Documento de requisitos para Dakota, Colorado y Arizona  
> Generado: 11 de marzo de 2026

---

## 1. Resumen Ejecutivo

La verificación de estructura accionaria en PLD bancario mexicano requiere implementar un pipeline de 5 fases que cruza el **Acta Constitutiva** con todas las **Reformas de Estatutos**, aplica **perforación de cadena** hasta identificar personas físicas, y cumple con **tres marcos regulatorios simultáneos**.

### Arquitectura de responsabilidades

| Agente | Responsabilidad |
|--------|-----------------|
| **Dakota** | Fases 1-2: Extracción documental + campos estructurados |
| **Colorado** | Fases 3-4: Cruce cronológico + verificación de consistencia |
| **Arizona** | Fase 5: Cálculo de propiedad indirecta + identificación de Propietarios Reales + screening |

---

## 2. Marco Regulatorio (Tres Capas)

### 2.1 Capa Bancaria-PLD (DCG Art. 115 LIC)
- **Umbral:** 25% de participación directa o indirecta
- **Concepto:** "Propietario Real" (Disposición 2ª, fracción XVIII)
- **Control:** persona física que adquiere ≥25% de composición accionaria

### 2.2 Capa Fiscal (CFF Art. 32-B Ter–Quinquies)
- **Umbral:** >15% de derechos de voto
- **Concepto:** "Beneficiario Controlador"
- **Vigencia:** desde 1 de enero de 2022

### 2.3 Capa Antilavado (LFPIORPI reforma 2025)
- **Umbral:** 25% (reducido de 50%)
- **Conceptos unificados:** Beneficiario Controlador = Beneficiario Final = Propietario Real
- **Nuevo:** documentar "cadena de titularidad" y "cadena de control"

### Implicación para Arizona
- Aplicar umbral 25% para PLD bancario
- Documentar información para satisfacer también umbral fiscal 15%

---

## 3. Dakota — Extracción Documental

### 3.1 Campos a extraer por Accionista/Socio

```python
class AccionistaCompleto(BaseModel):
    # Identificación
    nombre_completo: str  # PF: nombre(s) + ap. paterno + ap. materno
    denominacion_social: str | None  # PM: razón social completa
    tipo_persona: Literal["fisica", "moral"]
    
    # Identificadores fiscales
    rfc: str  # 12 chars PM, 13 chars PF
    curp: str | None  # 18 chars, solo PF
    
    # Datos personales/corporativos
    nacionalidad: str
    fecha_nacimiento: str | None  # Solo PF, formato YYYY-MM-DD
    fecha_constitucion: str | None  # Solo PM, formato YYYY-MM-DD
    genero: Literal["M", "F"] | None  # Solo PF
    estado_civil: str | None  # Solo PF
    
    # Domicilio completo
    domicilio: DomicilioCompleto
    
    # Participación accionaria
    numero_acciones: int | None
    numero_partes_sociales: int | None  # Para S. de R.L.
    serie: str | None  # Ej: "A", "B"
    clase: str | None  # Ej: "ordinaria", "preferente"
    valor_nominal: float | None
    porcentaje_directo: float
    monto_exhibiciones: float | None
    
    # Metadatos
    fuente: str  # "acta_constitutiva" | "reforma_estatutos"
    fecha_documento: str | None
    confiabilidad: float  # 0.0 - 1.0
    requiere_verificacion: bool


class DomicilioCompleto(BaseModel):
    calle: str
    numero_exterior: str
    numero_interior: str | None
    colonia: str
    alcaldia_municipio: str
    ciudad: str | None
    entidad_federativa: str
    codigo_postal: str
    pais: str = "México"
```

### 3.2 Campos de la Entidad (PM cliente)

```python
class EntidadCompleta(BaseModel):
    denominacion_social: str
    tipo_societario: str  # S.A. de C.V., S. de R.L., etc.
    objeto_social: str
    domicilio_social: DomicilioCompleto
    duracion: str  # "99 años", "indefinida"
    
    # Capital social
    capital_social_total: float
    capital_fijo: float | None
    capital_variable: float | None
    moneda: str = "MXN"
    
    # Datos constitutivos
    fecha_constitucion: str
    numero_escritura: str
    notario: str
    numero_notaria: int
    plaza_notarial: str
    fecha_protocolizacion: str
    
    # Registro
    folio_mercantil: str | None
    fecha_inscripcion_rpc: str | None
    
    # Administración
    tipo_administracion: Literal["administrador_unico", "consejo_administracion"]
    administradores: list[Administrador]
    comisarios: list[Comisario] | None
```

### 3.3 Validación de RFC

```python
import re

# Patrones de validación
RFC_PM_PATTERN = r'^[A-ZÑ&]{3}[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[A-Z0-9]{3}$'
RFC_PF_PATTERN = r'^[A-ZÑ&]{4}[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[A-Z0-9]{3}$'

# RFCs genéricos a reconocer
RFCS_GENERICOS = {
    "EXTF900101NI1": "Persona física extranjera",
    "EXT990101NI1": "Persona moral extranjera",
    "XAXX010101000": "Público en general",
    "XEXX010101000": "Residente extranjero sin RFC",
}

def validar_rfc(rfc: str) -> tuple[bool, str]:
    """Valida formato de RFC y determina tipo de persona."""
    rfc = rfc.upper().strip()
    
    if rfc in RFCS_GENERICOS:
        return True, "generico"
    
    if re.match(RFC_PM_PATTERN, rfc) and len(rfc) == 12:
        return True, "moral"
    
    if re.match(RFC_PF_PATTERN, rfc) and len(rfc) == 13:
        return True, "fisica"
    
    return False, "invalido"
```

### 3.4 Detección de Tipo de Persona

```python
# Sufijos corporativos para detección automática
SUFIJOS_ACCIONES = [
    "S.A.", "S.A. DE C.V.", "S.A.B. DE C.V.", "S.A.P.I. DE C.V.",
    "S. EN C. POR A.", "S.A.S."
]

SUFIJOS_PARTES_SOCIALES = [
    "S. DE R.L.", "S. DE R.L. DE C.V.", "S. EN N.C.", 
    "S. EN C.S.", "S.C."
]

SUFIJOS_CIVILES = ["A.C.", "S.C."]

def detectar_tipo_persona(nombre: str, rfc: str = None) -> str:
    """
    Detecta si es persona física o moral.
    Prioridad: RFC > Sufijo corporativo > Indicador textual
    """
    nombre_upper = nombre.upper()
    
    # 1. Validar por RFC si disponible
    if rfc:
        valido, tipo = validar_rfc(rfc)
        if valido and tipo in ("fisica", "moral"):
            return tipo
    
    # 2. Detectar por sufijo corporativo
    for sufijo in SUFIJOS_ACCIONES + SUFIJOS_PARTES_SOCIALES + SUFIJOS_CIVILES:
        if sufijo in nombre_upper:
            return "moral"
    
    # 3. Detectar por indicadores textuales
    indicadores_moral = ["FIDEICOMISO", "FONDO", "SOCIEDAD"]
    if any(ind in nombre_upper for ind in indicadores_moral):
        return "moral"
    
    # 4. Detectar en contexto del Acta (frases típicas)
    # "en su propio nombre y derecho" → persona física
    # "en representación de..." → persona moral
    
    return "fisica"  # Default
```

### 3.5 Extracción de Reformas de Estatutos

Dakota debe extraer de cada Reforma:

```python
class ReformaEstatutos(BaseModel):
    # Identificación
    tipo_asamblea: Literal["ordinaria", "extraordinaria"]
    fecha_asamblea: str
    
    # Orden del día (detectar modificaciones relevantes)
    modificaciones: list[TipoModificacion]
    # Tipos: capital_social, ingreso_socios, salida_socios, 
    #        transmision_acciones, administracion, fusion, escision
    
    # Nueva distribución accionaria (post-modificación)
    estructura_accionaria_nueva: list[AccionistaCompleto]
    
    # Accionistas entrantes/salientes
    accionistas_entrantes: list[AccionistaCompleto]
    accionistas_salientes: list[str]  # nombres
    
    # Datos notariales
    numero_escritura: str
    notario: str
    numero_notaria: int
    plaza_notarial: str
    fecha_protocolizacion: str
    
    # Inscripción registral
    folio_mercantil: str | None
    fecha_inscripcion_rpc: str | None
    inscrita: bool
```

### 3.6 Alertas y Banderas Rojas (Dakota)

```python
ALERTAS_ESTRUCTURALES = [
    "estructura_multicapa_compleja",  # >2 niveles sin propósito evidente
    "shell_company_detectada",  # PM accionista recién constituida sin operaciones
    "prestanombre_posible",  # PF sin capacidad económica con participación significativa
    "cambios_frecuentes",  # >3 cambios de estructura en 12 meses
    "estructura_circular",  # A posee B, B posee A
    "jurisdiccion_alto_riesgo",  # Accionista en paraíso fiscal
]

ALERTAS_DOCUMENTALES = [
    "tachaduras_enmendaduras",
    "discrepancia_denominacion_csf_acta",
    "sin_inscripcion_rpc",  # Sin folio mercantil
    "acta_antigua_sin_reformas",  # >5 años sin actualización
    "capital_inconsistente_actividad",
    "discrepancia_rfc_tipo_persona",  # RFC 12 chars pero declarado como PF
]

ALERTAS_PLD = [
    "pep_detectado",
    "requiere_perforacion",  # PM con >25%
    "documentacion_incompleta",
    "resistencia_cliente",  # Marcador manual
]
```

---

## 4. Colorado — Cruce Cronológico y Validación

### 4.1 Fase 3: Cruce Cronológico

```python
def determinar_estructura_vigente(
    acta_constitutiva: dict,
    reformas: list[dict],  # Ordenadas cronológicamente
) -> EstructuraVigente:
    """
    Determina la estructura accionaria vigente aplicando
    todas las reformas en orden cronológico.
    
    REGLA: La última Reforma inscrita en RPC prevalece.
    """
    # 1. Empezar con estructura del Acta Constitutiva
    estructura_base = acta_constitutiva["estructura_accionaria"]
    
    # 2. Ordenar reformas por fecha de inscripción (no protocolización)
    reformas_ordenadas = sorted(
        reformas, 
        key=lambda r: r.get("fecha_inscripcion_rpc") or r.get("fecha_asamblea")
    )
    
    # 3. Aplicar cada reforma secuencialmente
    for reforma in reformas_ordenadas:
        if not reforma.get("inscrita"):
            # Reforma no inscrita: solo efectos entre partes
            generar_alerta("reforma_no_inscrita", reforma)
            continue
        
        # Aplicar modificaciones
        if "estructura_accionaria_nueva" in reforma:
            estructura_base = reforma["estructura_accionaria_nueva"]
        else:
            estructura_base = aplicar_modificaciones(
                estructura_base,
                reforma.get("accionistas_entrantes", []),
                reforma.get("accionistas_salientes", []),
            )
    
    return EstructuraVigente(
        accionistas=estructura_base,
        fuente_final=reformas_ordenadas[-1] if reformas_ordenadas else acta_constitutiva,
        fecha_vigencia=reformas_ordenadas[-1].get("fecha_inscripcion_rpc") if reformas_ordenadas else acta_constitutiva.get("fecha_constitucion"),
    )
```

### 4.2 Validaciones de Consistencia

```python
VALIDACIONES_ESTRUCTURA = [
    # V5.1 - Suma de porcentajes debe ser ~100%
    {
        "codigo": "V5.1",
        "descripcion": "Suma de porcentajes accionarios",
        "validar": lambda acc: abs(sum(a["porcentaje"] for a in acc) - 100) < 1.0,
        "severidad": "error",
    },
    
    # V5.2 - Capital fijo solo modificable por Asamblea Extraordinaria
    {
        "codigo": "V5.2",
        "descripcion": "Modificación de capital fijo requiere Asamblea Extraordinaria",
        "validar": lambda reforma: (
            reforma.get("tipo_asamblea") == "extraordinaria" 
            if "capital_fijo" in reforma.get("modificaciones", []) 
            else True
        ),
        "severidad": "warning",
    },
    
    # V5.3 - Reforma inscrita en RPC
    {
        "codigo": "V5.3",
        "descripcion": "Reformas deben estar inscritas en RPC",
        "validar": lambda reforma: reforma.get("inscrita", False),
        "severidad": "info" if reforma.get("modifica_capital_variable") else "warning",
    },
    
    # V5.4 - Consistencia RFC vs tipo declarado
    {
        "codigo": "V5.4",
        "descripcion": "RFC debe coincidir con tipo de persona declarado",
        "validar": lambda acc: validar_rfc(acc["rfc"])[1] == acc["tipo_persona"],
        "severidad": "error",
    },
]
```

### 4.3 Diferencias por Tipo Societario

Colorado debe parametrizar validaciones según tipo:

| Tipo | Acciones/Partes | Transferencia | Libro | Quórum modificación |
|------|-----------------|---------------|-------|---------------------|
| S.A. de C.V. | Acciones | Libre (default) | Registro de Acciones | 50% capital |
| S. de R.L. | Partes sociales | Requiere consentimiento | Especial de Socios | 75% capital |
| S.A.B. | Acciones | LMV | Indeval | LMV |
| S.A.S. | Acciones | Solo PF | Electrónico | Simplificado |

---

## 5. Arizona — Identificación de Propietarios Reales

### 5.1 Cálculo de Propiedad Indirecta (Look-through)

```python
def calcular_propiedad_indirecta(
    estructura: list[Accionista],
    estructuras_intermedias: dict[str, list[Accionista]],  # RFC_PM -> sus accionistas
) -> list[PropietarioReal]:
    """
    Aplica perforación de cadena hasta llegar a personas físicas.
    
    Ejemplo:
    - PM-Cliente es 60% de PM-Holding
    - PM-Holding es 80% de Juan Pérez (PF)
    - Propiedad indirecta de Juan = 60% × 80% = 48%
    """
    propietarios_reales: list[PropietarioReal] = []
    
    def perforar(accionistas: list, factor: float = 1.0, nivel: int = 0):
        for acc in accionistas:
            porcentaje_efectivo = acc["porcentaje"] * factor / 100
            
            if acc["tipo_persona"] == "fisica":
                # Llegamos a persona física
                propietarios_reales.append(PropietarioReal(
                    nombre=acc["nombre"],
                    rfc=acc["rfc"],
                    porcentaje_directo=acc["porcentaje"] if nivel == 0 else 0,
                    porcentaje_indirecto=porcentaje_efectivo * 100,
                    porcentaje_total=(acc["porcentaje"] if nivel == 0 else 0) + porcentaje_efectivo * 100,
                    cadena_titularidad=construir_cadena(acc, nivel),
                    nivel=nivel,
                ))
            else:
                # Es persona moral, continuar perforación
                rfc_pm = acc["rfc"]
                if rfc_pm in estructuras_intermedias:
                    perforar(
                        estructuras_intermedias[rfc_pm],
                        factor * acc["porcentaje"] / 100,
                        nivel + 1
                    )
                else:
                    # PM sin información de accionistas
                    propietarios_reales.append(PropietarioReal(
                        nombre=acc["nombre"],
                        rfc=acc["rfc"],
                        porcentaje_directo=acc["porcentaje"] if nivel == 0 else 0,
                        porcentaje_indirecto=porcentaje_efectivo * 100,
                        tipo="moral_sin_perforar",
                        requiere_documentacion=True,
                    ))
    
    perforar(estructura)
    
    # Consolidar propietarios reales que aparecen múltiples veces
    return consolidar_propietarios(propietarios_reales)
```

### 5.2 Cascada CNBV para Identificación

```python
def identificar_propietarios_reales_cnbv(
    estructura: list[Accionista],
    administradores: list[Administrador],
    umbral_pld: float = 25.0,
    umbral_fiscal: float = 15.0,
) -> ResultadoPropietariosReales:
    """
    Aplica cascada de identificación según lineamientos CNBV (28-julio-2017):
    
    1. PF con ≥25% de propiedad directa o indirecta
    2. Quien ejerce control por otros medios
    3. Administrador Único o Consejo de Administración
    4. PF designada si administrador es PM
    """
    
    # Paso 1: Buscar PF con ≥25% (o ≥15% para fiscal)
    propietarios_25 = [
        p for p in estructura_perforada
        if p["tipo_persona"] == "fisica" and p["porcentaje_total"] >= umbral_pld
    ]
    
    if propietarios_25:
        return ResultadoPropietariosReales(
            propietarios=propietarios_25,
            criterio="PROPIEDAD_25PCT",
            cumple_pld=True,
        )
    
    # Paso 2: Buscar control por otros medios
    # - Capacidad de imponer decisiones en asambleas
    # - Nombrar/remover mayoría del consejo
    # - Derechos de voto >50% del capital
    # - Dirigir administración y estrategia
    controladores = detectar_control_por_otros_medios(estructura, actas_asamblea)
    
    if controladores:
        return ResultadoPropietariosReales(
            propietarios=controladores,
            criterio="CONTROL_OTROS_MEDIOS",
            cumple_pld=True,
        )
    
    # Paso 3: Administrador Único o Consejo
    if administradores:
        admin_pf = [a for a in administradores if a["tipo_persona"] == "fisica"]
        
        if admin_pf:
            return ResultadoPropietariosReales(
                propietarios=admin_pf,
                criterio="ADMINISTRADOR",
                cumple_pld=True,
            )
        
        # Paso 4: Si administrador es PM, identificar PF designada
        admin_pm = [a for a in administradores if a["tipo_persona"] == "moral"]
        for pm in admin_pm:
            pf_designada = obtener_representante_pm(pm["rfc"])
            if pf_designada:
                return ResultadoPropietariosReales(
                    propietarios=[pf_designada],
                    criterio="CONTROLADOR_PM_ADMINISTRADORA",
                    cumple_pld=True,
                )
    
    return ResultadoPropietariosReales(
        propietarios=[],
        criterio="NO_IDENTIFICADO",
        cumple_pld=False,
        requiere_escalamiento=True,
    )
```

### 5.3 Umbrales y Documentación

```python
class ConfiguracionUmbrales:
    # PLD Bancario (DCG Art. 115)
    UMBRAL_PROPIETARIO_REAL = 25.0
    
    # Fiscal (CFF)
    UMBRAL_BENEFICIARIO_CONTROLADOR = 15.0
    
    # LFPIORPI 2025
    UMBRAL_LFPIORPI = 25.0
    
    # Cotizadas (LMV)
    UMBRAL_ACCIONISTA_SIGNIFICATIVO = 10.0


def generar_reporte_propietarios(
    propietarios: list[PropietarioReal],
    config: ConfiguracionUmbrales,
) -> ReportePropietarios:
    """
    Genera reporte cumpliendo con los tres marcos regulatorios.
    """
    return ReportePropietarios(
        # Para DCG (25%)
        propietarios_reales_pld=[
            p for p in propietarios if p.porcentaje_total >= config.UMBRAL_PROPIETARIO_REAL
        ],
        
        # Para CFF (15%) - incluye los anteriores + adicionales
        beneficiarios_controladores_cff=[
            p for p in propietarios if p.porcentaje_total >= config.UMBRAL_BENEFICIARIO_CONTROLADOR
        ],
        
        # Cadenas de titularidad para LFPIORPI
        cadenas_titularidad=[p.cadena_titularidad for p in propietarios],
        
        # Metadata
        fecha_analisis=datetime.now(),
        version_regulatoria="DCG-2019 / CFF-2022 / LFPIORPI-2025",
    )
```

---

## 6. Pipeline Completo

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              PIPELINE KYB                                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  DAKOTA (Extracción)                                                            │
│  ───────────────────                                                            │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐       │
│  │ COLLECT │───▶│CLASSIFY │───▶│PRE-VAL  │───▶│ EXTRACT │───▶│VALIDATE │       │
│  │ docs    │    │ tipo    │    │ sellos  │    │ OCR+AI  │    │ formato │       │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘    └────┬────┘       │
│                                                                    │            │
│  ──────────────────────────────────────────────────────────────────┼────────── │
│                                                                    │            │
│  COLORADO (Validación)                                             │            │
│  ─────────────────────                                             ▼            │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐       │
│  │ CROSS   │───▶│ CHRONO  │───▶│ SIGER   │───▶│ RFC     │───▶│ CALC    │       │
│  │REFERENCE│    │ ORDER   │    │ CHECK   │    │VALIDATE │    │OWNERSHIP│       │
│  └────┬────┘    └─────────┘    └─────────┘    └─────────┘    └────┬────┘       │
│       │         Cruce Acta     Verificar      Formato        Directa+│          │
│       │         + Reformas     inscripción    12/13 chars    Indirecta          │
│       │                                                           │             │
│  ─────┼───────────────────────────────────────────────────────────┼──────────  │
│       │                                                           │             │
│  ARIZONA (PLD)                                                    ▼             │
│  ─────────────                                                                  │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐       │
│  │IDENTIFY │───▶│ SCREEN  │───▶│  FLAG   │───▶│GENERATE │───▶│ PERSIST │       │
│  │  UBO    │    │ LISTS   │    │ ALERTS  │    │ REPORT  │    │   BD    │       │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘       │
│   Cascada        LPB/OFAC      Banderas       JSON para      Tabla             │
│   CNBV           PEP/69-B      rojas          analista       analisis_pld      │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Brechas Actuales vs. Requisitos

### 7.1 Dakota — Estado Actual vs. Requerido

| Funcionalidad | Actual | Requerido | Prioridad |
|---------------|--------|-----------|-----------|
| Extracción estructura_accionaria | ✅ Básica | Completa | Alta |
| Validación RFC 12/13 chars | ❌ | ✅ | Alta |
| RFCs genéricos (EXTF, XAXX) | ❌ | ✅ | Media |
| Campos adicionales (serie, clase, valor_nominal) | ❌ | ✅ | Media |
| Detección tipo societario | ✅ Parcial | Completa | Alta |
| Extracción de Reformas | ✅ Básica | Con cruce cronológico | Alta |
| Alertas estructurales | ❌ | ✅ | Alta |
| Alertas documentales | ❌ | ✅ | Alta |

### 7.2 Colorado — Estado Actual vs. Requerido

| Funcionalidad | Actual | Requerido | Prioridad |
|---------------|--------|-----------|-----------|
| Consolidación accionistas | ✅ | ✅ | — |
| Priorización Reforma > Acta | ✅ | ✅ | — |
| Cruce cronológico múltiples Reformas | ❌ | ✅ | Alta |
| Validación V5.4 (RFC vs tipo) | ❌ | ✅ | Alta |
| Detección reformas no inscritas | ❌ | ✅ | Media |
| Parametrización por tipo societario | ❌ | ✅ | Media |

### 7.3 Arizona — Estado Actual vs. Requerido

| Funcionalidad | Actual | Requerido | Prioridad |
|---------------|--------|-----------|-----------|
| Etapa 1: Completitud | ✅ | ✅ | — |
| Cálculo propiedad indirecta | ❌ | ✅ | Alta |
| Cascada CNBV | ❌ | ✅ | Alta |
| Umbrales 25%/15% | ❌ | ✅ | Alta |
| Screening listas | ❌ | ✅ | Alta |
| Generación JSON screening | ❌ | ✅ | Alta |

---

## 8. Plan de Implementación

### Fase 1 — Dakota (2-3 semanas)
1. Implementar validación RFC con regex
2. Agregar detección de RFCs genéricos
3. Extender schema de AccionistaCompleto
4. Implementar alertas estructurales y documentales
5. Mejorar extracción de Reformas con campos adicionales

### Fase 2 — Colorado (1-2 semanas)
1. Implementar cruce cronológico de múltiples Reformas
2. Agregar validación V5.4 (RFC vs tipo)
3. Detectar reformas no inscritas
4. Parametrizar validaciones por tipo societario

### Fase 3 — Arizona (2-3 semanas)
1. Implementar cálculo de propiedad indirecta
2. Implementar cascada CNBV
3. Agregar umbrales configurables
4. Generar JSON para screening
5. Implementar Etapa 2 (screening contra listas)

---

## 9. Modelo de Datos Final

### Tabla `estructura_accionaria` (propuesta)

```sql
CREATE TABLE estructura_accionaria (
    id UUID PRIMARY KEY,
    empresa_id UUID REFERENCES empresas(id),
    
    -- Accionista
    nombre VARCHAR(255) NOT NULL,
    tipo_persona VARCHAR(10) NOT NULL,  -- 'fisica' | 'moral'
    rfc VARCHAR(13),
    curp VARCHAR(18),
    
    -- Participación
    numero_acciones INTEGER,
    serie VARCHAR(10),
    clase VARCHAR(50),
    valor_nominal DECIMAL(18,2),
    porcentaje_directo DECIMAL(5,2),
    porcentaje_indirecto DECIMAL(5,2),
    porcentaje_total DECIMAL(5,2),
    
    -- Clasificación PLD
    es_propietario_real BOOLEAN DEFAULT FALSE,
    criterio_identificacion VARCHAR(50),
    nivel_cadena INTEGER DEFAULT 0,
    cadena_titularidad JSONB,
    
    -- Metadatos
    fuente VARCHAR(50),
    fecha_documento DATE,
    confiabilidad DECIMAL(3,2),
    requiere_verificacion BOOLEAN DEFAULT FALSE,
    
    -- Auditoría
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_estructura_empresa ON estructura_accionaria(empresa_id);
CREATE INDEX idx_estructura_rfc ON estructura_accionaria(rfc);
CREATE INDEX idx_estructura_propietario ON estructura_accionaria(es_propietario_real);
```

---

## 10. Referencias Regulatorias

- **DCG Art. 115 LIC** — Disposiciones de Carácter General (SHCP/CNBV)
- **CFF Art. 32-B Ter–Quinquies** — Beneficiario Controlador (SAT)
- **LFPIORPI reforma 2025** — Ley Federal PLD
- **LGSM** — Ley General de Sociedades Mercantiles
- **LMV** — Ley del Mercado de Valores
- **GAFI/FATF** — Recomendaciones 10, 24, 25
- **Lineamientos CNBV 28-julio-2017** — Identificación de Propietario Real
