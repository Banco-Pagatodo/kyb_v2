"""
Etapa 2 — Screening contra Listas Negras (PLD/AML).

Implementa:
1. Búsqueda en 3 tablas: CatPLD69BPerson, CatPLDLockedPerson, TraPLDBlackListEntry
2. Sistema de scoring para diferenciar coincidencias verdaderas de homónimos
3. Normalización de nombres para búsqueda fuzzy
4. Integración con reporte PLD

Tablas de listas negras:
- CatPLD69BPerson: Lista 69-B del SAT (EFOS/EDOS - simuladores de operaciones)
- CatPLDLockedPerson: Personas bloqueadas por UIF (Unidad de Inteligencia Financiera)
- TraPLDBlackListEntry: Lista negra consolidada (OFAC, PEP, SAT69, etc.)

Sistema de Scoring para Homónimos:
- En México los nombres repetidos son MUY comunes
- Un match de nombre NO implica que sea la misma persona
- Requerimos datos adicionales (RFC, CURP, fecha nacimiento) para confirmar
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher
from enum import Enum
from typing import Any

import pyodbc
from dotenv import load_dotenv

from ..core.normalize import normalizar_nombre, normalizar_razon_social, normalizar_rfc

logger = logging.getLogger("arizona.blacklist_screening")

# Cargar variables de entorno
load_dotenv()


# ═══════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════

BLACKLIST_DB_CONFIG = {
    "host": os.getenv("BLACKLIST_DB_HOST", "172.26.3.5"),
    "port": os.getenv("BLACKLIST_DB_PORT", "1433"),
    "database": os.getenv("BLACKLIST_DB_NAME", "Siglonet_PagaTodo"),
    "user": os.getenv("BLACKLIST_DB_USER", "usrSiglo"),
    "password": os.getenv("BLACKLIST_DB_PASS", ""),
    "driver": os.getenv("BLACKLIST_DB_DRIVER", "ODBC Driver 17 for SQL Server"),
}

# Umbrales de scoring
UMBRAL_MATCH_CONFIRMADO = 90  # RFC/CURP coincide = match confirmado
UMBRAL_MATCH_PROBABLE = 70   # Alta probabilidad (requiere revisión manual)
UMBRAL_MATCH_POSIBLE = 50    # Posible homónimo (requiere verificación adicional)
UMBRAL_DESCARTAR = 30        # Por debajo se descarta como homónimo

# Apellidos muy comunes en México (penalizar coincidencias)
APELLIDOS_COMUNES_MX = {
    "GARCIA", "HERNANDEZ", "MARTINEZ", "LOPEZ", "GONZALEZ",
    "RODRIGUEZ", "PEREZ", "SANCHEZ", "RAMIREZ", "TORRES",
    "FLORES", "RIVERA", "GOMEZ", "DIAZ", "REYES",
    "MORALES", "JIMENEZ", "RUIZ", "ALVAREZ", "MENDOZA",
    "AGUILAR", "ORTIZ", "CASTILLO", "CRUZ", "ROMERO",
    "VARGAS", "RAMOS", "HERRERA", "CHAVEZ", "MEDINA",
    "GUTIERREZ", "ESPINOZA", "VEGA", "MORENO", "CASTRO",
    "FERNANDEZ", "SALAZAR", "DELGADO", "SANTIAGO", "CONTRERAS",
}

# Nombres muy comunes en México
NOMBRES_COMUNES_MX = {
    "JUAN", "JOSE", "CARLOS", "LUIS", "MIGUEL",
    "ANTONIO", "FRANCISCO", "PEDRO", "MANUEL", "JESUS",
    "MARIA", "GUADALUPE", "ANA", "ROSA", "ELENA",
    "PATRICIA", "ELIZABETH", "CARMEN", "LAURA", "MARTHA",
    "DANIEL", "ALEJANDRO", "FERNANDO", "RICARDO", "ARTURO",
    "DAVID", "EDUARDO", "RAFAEL", "JORGE", "ROBERTO",
}


# ═══════════════════════════════════════════════════════════════════
#  ENUMERACIONES
# ═══════════════════════════════════════════════════════════════════

class TipoLista(str, Enum):
    """Tipo de lista negra."""
    LISTA_69B = "LISTA_69B"           # SAT EFOS/EDOS
    BLOQUEADOS_UIF = "BLOQUEADOS_UIF" # UIF - personas bloqueadas
    LISTA_NEGRA = "LISTA_NEGRA"       # Consolidada (OFAC, PEP, etc)


class NivelCoincidencia(str, Enum):
    """Nivel de coincidencia del match."""
    CONFIRMADO = "CONFIRMADO"       # RFC/CURP coincide - es la misma persona
    PROBABLE = "PROBABLE"           # Alta probabilidad - requiere revisión
    POSIBLE = "POSIBLE"             # Posible homónimo - verificar datos adicionales
    HOMONIMO = "HOMONIMO"           # Mismo nombre pero diferente persona
    SIN_COINCIDENCIA = "SIN_COINCIDENCIA"


class SituacionContribuyente(str, Enum):
    """Situación del contribuyente en lista 69-B."""
    DEFINITIVO = "DEFINITIVO"
    PRESUNTO = "PRESUNTO"
    DESVIRTUADO = "DESVIRTUADO"
    SENTENCIA_FAVORABLE = "SENTENCIA_FAVORABLE"


# ═══════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PersonaBuscada:
    """Persona a buscar en listas negras."""
    nombre: str
    rfc: str = ""
    curp: str = ""
    fecha_nacimiento: date | None = None
    tipo_persona: str = "fisica"  # fisica | moral
    rol: str = ""  # apoderado, accionista, etc.
    fuente: str = ""  # documento donde se identificó


@dataclass
class CoincidenciaLista:
    """Coincidencia encontrada en una lista negra."""
    # Datos de la lista
    tipo_lista: TipoLista
    nombre_en_lista: str
    rfc_en_lista: str = ""
    curp_en_lista: str = ""
    fecha_nacimiento_lista: date | None = None
    
    # Tabla SQL origen — nombre real de la tabla consultada
    tabla_origen: str = ""  # CatPLD69BPerson, CatPLDLockedPerson, TraPLDBlackListEntry
    
    # Scoring
    score: int = 0
    nivel_coincidencia: NivelCoincidencia = NivelCoincidencia.SIN_COINCIDENCIA
    
    # Detalles del match
    match_nombre: float = 0.0  # 0.0 - 1.0
    match_rfc: bool = False
    match_curp: bool = False
    
    # Datos adicionales de la lista
    fuente: str = ""  # SAT69, OFAC, UIF, etc.
    categoria: str = ""
    subcategoria: str = ""
    situacion: str = ""  # Para 69-B: presunto, definitivo, desvirtuado
    fecha_publicacion: str = ""
    informacion_adicional: str = ""
    activo: bool = True
    
    # Justificación del scoring
    explicacion_score: list[str] = field(default_factory=list)


@dataclass
class ResultadoScreening:
    """Resultado del screening de una persona."""
    persona: PersonaBuscada
    coincidencias: list[CoincidenciaLista] = field(default_factory=list)
    
    # Resumen
    tiene_coincidencias: bool = False
    coincidencia_mas_alta: CoincidenciaLista | None = None
    score_maximo: int = 0
    nivel_riesgo: NivelCoincidencia = NivelCoincidencia.SIN_COINCIDENCIA
    
    # Flags
    requiere_revision_manual: bool = False
    requiere_escalamiento: bool = False
    
    # Trazabilidad
    listas_consultadas: list[str] = field(default_factory=list)
    listas_exitosas: list[str] = field(default_factory=list)
    listas_fallidas: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    screening_incompleto: bool = False


@dataclass
class ResumenScreening:
    """Resumen del screening de todas las personas."""
    total_personas: int = 0
    personas_con_coincidencias: int = 0
    coincidencias_confirmadas: int = 0
    coincidencias_probables: int = 0
    coincidencias_posibles: int = 0
    homonimos_descartados: int = 0
    
    resultados: list[ResultadoScreening] = field(default_factory=list)
    
    # Flags globales
    tiene_coincidencias_criticas: bool = False
    requiere_escalamiento: bool = False
    screening_incompleto: bool = False  # True si alguna lista falló
    
    # Errores
    errores_conexion: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
#  FUNCIONES DE NORMALIZACIÓN  →  importadas de core.normalize
# ═══════════════════════════════════════════════════════════════════


def extraer_componentes_nombre(nombre_completo: str) -> dict[str, str]:
    """
    Extrae componentes de un nombre completo mexicano.
    Formato típico: NOMBRE(S) APELLIDO_PATERNO APELLIDO_MATERNO
    
    Returns:
        dict con: nombres, apellido_paterno, apellido_materno
    """
    partes = normalizar_nombre(nombre_completo).split()
    
    if len(partes) == 0:
        return {"nombres": "", "apellido_paterno": "", "apellido_materno": ""}
    
    if len(partes) == 1:
        return {"nombres": partes[0], "apellido_paterno": "", "apellido_materno": ""}
    
    if len(partes) == 2:
        return {"nombres": partes[0], "apellido_paterno": partes[1], "apellido_materno": ""}
    
    if len(partes) == 3:
        return {
            "nombres": partes[0],
            "apellido_paterno": partes[1],
            "apellido_materno": partes[2],
        }
    
    # 4+ partes: asumir últimas 2 son apellidos
    return {
        "nombres": " ".join(partes[:-2]),
        "apellido_paterno": partes[-2],
        "apellido_materno": partes[-1],
    }


# ═══════════════════════════════════════════════════════════════════
#  FUNCIONES DE SCORING
# ═══════════════════════════════════════════════════════════════════

def calcular_similitud_texto(texto1: str, texto2: str) -> float:
    """
    Calcula similitud entre dos textos (0.0 - 1.0).
    Usa SequenceMatcher para comparación fuzzy.
    """
    if not texto1 or not texto2:
        return 0.0
    
    t1 = normalizar_nombre(texto1)
    t2 = normalizar_nombre(texto2)
    
    if t1 == t2:
        return 1.0
    
    return SequenceMatcher(None, t1, t2).ratio()


def calcular_score_coincidencia(
    persona: PersonaBuscada,
    nombre_lista: str,
    rfc_lista: str = "",
    curp_lista: str = "",
    apellido_paterno_lista: str = "",
    apellido_materno_lista: str = "",
    fecha_nac_lista: date | None = None,
) -> tuple[int, list[str]]:
    """
    Calcula el score de coincidencia entre una persona y un registro de lista.
    
    Sistema de puntuación:
    - RFC exacto: +50 puntos (casi confirma identidad)
    - CURP exacto: +50 puntos (confirma identidad)
    - Nombre completo exacto: +30 puntos
    - Similitud nombre >90%: +25 puntos
    - Similitud nombre 80-90%: +20 puntos
    - Similitud nombre 70-80%: +15 puntos
    - Apellidos coinciden: +15 puntos c/u
    - Fecha nacimiento coincide: +20 puntos
    
    Penalizaciones:
    - Apellidos muy comunes: -5 puntos c/u
    - Solo primer nombre común: -10 puntos
    - Persona moral vs física: -20 puntos
    
    Returns:
        (score, explicaciones)
    """
    score = 0
    explicaciones = []
    
    nombre_persona = normalizar_nombre(persona.nombre)
    nombre_lista_norm = normalizar_nombre(nombre_lista)
    
    # ─── RFC ───
    if persona.rfc and rfc_lista:
        rfc_p = normalizar_rfc(persona.rfc)
        rfc_l = normalizar_rfc(rfc_lista)
        if rfc_p == rfc_l:
            score += 50
            explicaciones.append(f"RFC coincide exactamente: {rfc_p} (+50)")
        elif rfc_p[:10] == rfc_l[:10]:  # Primeros 10 caracteres (sin homoclave)
            score += 35
            explicaciones.append(f"RFC coincide sin homoclave: {rfc_p[:10]} (+35)")
    
    # ─── CURP ───
    if persona.curp and curp_lista:
        curp_p = normalizar_rfc(persona.curp)
        curp_l = normalizar_rfc(curp_lista)
        if curp_p == curp_l:
            score += 50
            explicaciones.append(f"CURP coincide exactamente: {curp_p} (+50)")
    
    # ─── NOMBRE COMPLETO ───
    similitud = calcular_similitud_texto(nombre_persona, nombre_lista_norm)
    
    if similitud == 1.0:
        score += 30
        explicaciones.append(f"Nombre exacto: '{nombre_persona}' (+30)")
    elif similitud >= 0.90:
        score += 25
        explicaciones.append(f"Similitud nombre {similitud*100:.0f}%: '{nombre_persona}' vs '{nombre_lista_norm}' (+25)")
    elif similitud >= 0.80:
        score += 20
        explicaciones.append(f"Similitud nombre {similitud*100:.0f}%: '{nombre_persona}' vs '{nombre_lista_norm}' (+20)")
    elif similitud >= 0.70:
        score += 15
        explicaciones.append(f"Similitud nombre {similitud*100:.0f}%: '{nombre_persona}' vs '{nombre_lista_norm}' (+15)")
    elif similitud >= 0.60:
        score += 10
        explicaciones.append(f"Similitud nombre {similitud*100:.0f}%: '{nombre_persona}' vs '{nombre_lista_norm}' (+10)")
    
    # ─── APELLIDOS ───
    comp_persona = extraer_componentes_nombre(persona.nombre)
    
    if apellido_paterno_lista:
        ap_lista = normalizar_nombre(apellido_paterno_lista)
        if comp_persona["apellido_paterno"] == ap_lista:
            score += 15
            explicaciones.append(f"Apellido paterno coincide: {ap_lista} (+15)")
            if ap_lista in APELLIDOS_COMUNES_MX:
                score -= 5
                explicaciones.append(f"Apellido paterno muy común: {ap_lista} (-5)")
    
    if apellido_materno_lista:
        am_lista = normalizar_nombre(apellido_materno_lista)
        if comp_persona["apellido_materno"] == am_lista:
            score += 15
            explicaciones.append(f"Apellido materno coincide: {am_lista} (+15)")
            if am_lista in APELLIDOS_COMUNES_MX:
                score -= 5
                explicaciones.append(f"Apellido materno muy común: {am_lista} (-5)")
    
    # ─── FECHA DE NACIMIENTO ───
    if persona.fecha_nacimiento and fecha_nac_lista:
        if persona.fecha_nacimiento == fecha_nac_lista:
            score += 20
            explicaciones.append(f"Fecha de nacimiento coincide: {fecha_nac_lista} (+20)")
    
    # ─── PENALIZACIONES ───
    # Solo primer nombre y es común
    partes_nombre = comp_persona["nombres"].split()
    if len(partes_nombre) == 1 and partes_nombre[0] in NOMBRES_COMUNES_MX:
        # No penalizar si hay otros matches fuertes
        if score < 50:
            score -= 10
            explicaciones.append(f"Solo primer nombre común sin otros datos: {partes_nombre[0]} (-10)")
    
    # Persona moral tratada como física o viceversa
    if persona.tipo_persona == "moral" and not any(
        s in nombre_lista_norm for s in ["SA", "CV", "SC", "AC", "SAS"]
    ):
        score -= 10
        explicaciones.append("Persona moral comparada con aparente física (-10)")
    
    return max(0, score), explicaciones


def determinar_nivel_coincidencia(score: int) -> NivelCoincidencia:
    """Determina el nivel de coincidencia basado en el score."""
    if score >= UMBRAL_MATCH_CONFIRMADO:
        return NivelCoincidencia.CONFIRMADO
    elif score >= UMBRAL_MATCH_PROBABLE:
        return NivelCoincidencia.PROBABLE
    elif score >= UMBRAL_MATCH_POSIBLE:
        return NivelCoincidencia.POSIBLE
    elif score >= UMBRAL_DESCARTAR:
        return NivelCoincidencia.HOMONIMO
    else:
        return NivelCoincidencia.SIN_COINCIDENCIA


# ═══════════════════════════════════════════════════════════════════
#  CLASE PRINCIPAL DE SCREENING
# ═══════════════════════════════════════════════════════════════════

class BlacklistScreeningService:
    """
    Servicio de screening contra listas negras PLD/AML.
    
    Consulta las siguientes tablas:
    - CatPLD69BPerson: Lista 69-B del SAT (EFOS/EDOS)
    - CatPLDLockedPerson: Personas bloqueadas por UIF
    - TraPLDBlackListEntry: Lista negra consolidada
    """
    
    def __init__(self, config: dict[str, str] | None = None):
        """
        Inicializa el servicio con configuración de conexión.
        
        Args:
            config: Diccionario con host, port, database, user, password, driver.
                   Si es None, usa variables de entorno.
        """
        self.config = config or BLACKLIST_DB_CONFIG
        self._conexion: pyodbc.Connection | None = None
    
    def _conectar(self) -> pyodbc.Connection:
        """Establece conexión a la base de datos."""
        if self._conexion is not None:
            try:
                # Verificar si la conexión sigue activa
                self._conexion.execute("SELECT 1")
                return self._conexion
            except Exception:
                self._conexion = None
        
        conn_str = (
            f"DRIVER={{{self.config['driver']}}};"
            f"SERVER={self.config['host']},{self.config['port']};"
            f"DATABASE={self.config['database']};"
            f"UID={self.config['user']};"
            f"PWD={self.config['password']};"
            "TrustServerCertificate=yes;"
            "Connection Timeout=5;"
        )
        
        logger.info(f"Conectando a SQL Server: {self.config['host']}:{self.config['port']}")
        self._conexion = pyodbc.connect(conn_str)
        return self._conexion
    
    def cerrar(self):
        """Cierra la conexión a la base de datos."""
        if self._conexion is not None:
            self._conexion.close()
            self._conexion = None
    
    def _buscar_lista_69b(
        self,
        persona: PersonaBuscada,
    ) -> list[CoincidenciaLista]:
        """
        Busca en la Lista 69-B del SAT (EFOS/EDOS).
        """
        coincidencias = []
        
        try:
            conn = self._conectar()
            cursor = conn.cursor()
            
            # Normalizar para búsqueda
            if persona.tipo_persona == "moral":
                nombre_buscar = normalizar_razon_social(persona.nombre)
            else:
                nombre_buscar = normalizar_nombre(persona.nombre)
            
            # Construir términos de búsqueda
            terminos = nombre_buscar.split()
            if not terminos:
                return []
            
            # Buscar con LIKE por cada término principal
            # Para personas morales: buscar nombre completo primero
            if persona.tipo_persona == "moral":
                query = """
                    SELECT TOP 20
                        PersonName69B, RFC, TaxpayerSituation,
                        SATNumDateGloPresumptionOffice, PublicationOfTheAllegedSATPage,
                        DefinitiveGlobalTradeDateNum, FinalSATPagePublication
                    FROM [dbo].[CatPLD69BPerson]
                    WHERE PersonName69B LIKE ?
                    ORDER BY PersonName69B
                """
                cursor.execute(query, (f"%{nombre_buscar}%",))
            else:
                # Personas físicas: buscar con múltiples términos
                # Usar patrón con % entre términos
                patron = "%"
                for t in terminos:
                    patron += t + "%"
                
                query = """
                    SELECT TOP 20
                        PersonName69B, RFC, TaxpayerSituation,
                        SATNumDateGloPresumptionOffice, PublicationOfTheAllegedSATPage,
                        DefinitiveGlobalTradeDateNum, FinalSATPagePublication
                    FROM [dbo].[CatPLD69BPerson]
                    WHERE PersonName69B LIKE ?
                    ORDER BY PersonName69B
                """
                cursor.execute(query, (patron,))
            
            rows = cursor.fetchall()
            
            # Buscar también por RFC si está disponible
            if persona.rfc:
                rfc_norm = normalizar_rfc(persona.rfc)
                cursor.execute("""
                    SELECT TOP 10
                        PersonName69B, RFC, TaxpayerSituation,
                        SATNumDateGloPresumptionOffice, PublicationOfTheAllegedSATPage,
                        DefinitiveGlobalTradeDateNum, FinalSATPagePublication
                    FROM [dbo].[CatPLD69BPerson]
                    WHERE RFC LIKE ?
                """, (f"%{rfc_norm}%",))
                rows.extend(cursor.fetchall())
            
            # Procesar resultados
            vistos = set()
            for row in rows:
                nombre_lista = row[0] or ""
                rfc_lista = row[1] or ""
                
                # Evitar duplicados
                key = (nombre_lista, rfc_lista)
                if key in vistos:
                    continue
                vistos.add(key)
                
                # Calcular score
                score, explicaciones = calcular_score_coincidencia(
                    persona=persona,
                    nombre_lista=nombre_lista,
                    rfc_lista=rfc_lista,
                )
                
                # Solo incluir si supera umbral mínimo
                if score >= UMBRAL_DESCARTAR:
                    situacion = row[2] or ""
                    fecha_presunto = row[4] or ""
                    fecha_definitivo = row[6] or ""
                    
                    coinc = CoincidenciaLista(
                        tipo_lista=TipoLista.LISTA_69B,
                        nombre_en_lista=nombre_lista,
                        rfc_en_lista=rfc_lista,
                        tabla_origen="CatPLD69BPerson",
                        score=score,
                        nivel_coincidencia=determinar_nivel_coincidencia(score),
                        match_nombre=calcular_similitud_texto(persona.nombre, nombre_lista),
                        match_rfc=(normalizar_rfc(persona.rfc) == normalizar_rfc(rfc_lista)) if persona.rfc else False,
                        fuente="SAT Lista 69-B (Art. 69-B CFF)",
                        categoria="EFOS/EDOS",
                        situacion=situacion,
                        fecha_publicacion=fecha_presunto or fecha_definitivo,
                        informacion_adicional=f"Situación: {situacion}",
                        activo=(situacion.upper() not in ["DESVIRTUADO", "SENTENCIA FAVORABLE"]),
                        explicacion_score=explicaciones,
                    )
                    coincidencias.append(coinc)
            
        except Exception as e:
            error_msg = f"Error buscando en Lista 69-B: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
        
        return coincidencias
    
    def _buscar_bloqueados_uif(
        self,
        persona: PersonaBuscada,
    ) -> list[CoincidenciaLista]:
        """
        Busca en la lista de personas bloqueadas por UIF.
        """
        coincidencias = []
        
        try:
            conn = self._conectar()
            cursor = conn.cursor()
            
            nombre_buscar = normalizar_nombre(persona.nombre)
            terminos = nombre_buscar.split()
            
            if not terminos:
                return []
            
            # Buscar en LockedPersonName, FullName, apellidos
            if persona.tipo_persona == "moral":
                query = """
                    SELECT TOP 20
                        LockedPersonID, LockedPersonName, FullName, IsLegalPerson,
                        BirthDate, RFC, NotificationNumber, NotificationDate,
                        PaternalSurname, MaternalSurname, AdditionalInformation, IsActive
                    FROM [dbo].[CatPLDLockedPerson]
                    WHERE FullName LIKE ? OR LockedPersonName LIKE ?
                    ORDER BY FullName
                """
                cursor.execute(query, (f"%{nombre_buscar}%", f"%{nombre_buscar}%"))
            else:
                # Para personas físicas, buscar con términos del nombre
                comp = extraer_componentes_nombre(persona.nombre)
                
                conditions = []
                params = []
                
                if comp["apellido_paterno"]:
                    conditions.append("PaternalSurname LIKE ?")
                    params.append(f"%{comp['apellido_paterno']}%")
                
                if comp["apellido_materno"]:
                    conditions.append("MaternalSurname LIKE ?")
                    params.append(f"%{comp['apellido_materno']}%")
                
                if comp["nombres"]:
                    primer_nombre = comp["nombres"].split()[0]
                    conditions.append("(LockedPersonName LIKE ? OR FullName LIKE ?)")
                    params.extend([f"%{primer_nombre}%", f"%{primer_nombre}%"])
                
                if not conditions:
                    return []
                
                query = f"""
                    SELECT TOP 20
                        LockedPersonID, LockedPersonName, FullName, IsLegalPerson,
                        BirthDate, RFC, NotificationNumber, NotificationDate,
                        PaternalSurname, MaternalSurname, AdditionalInformation, IsActive
                    FROM [dbo].[CatPLDLockedPerson]
                    WHERE {' AND '.join(conditions)}
                    ORDER BY FullName
                """
                cursor.execute(query, params)
            
            rows = cursor.fetchall()
            
            # Buscar también por RFC
            if persona.rfc:
                rfc_norm = normalizar_rfc(persona.rfc)
                cursor.execute("""
                    SELECT TOP 10
                        LockedPersonID, LockedPersonName, FullName, IsLegalPerson,
                        BirthDate, RFC, NotificationNumber, NotificationDate,
                        PaternalSurname, MaternalSurname, AdditionalInformation, IsActive
                    FROM [dbo].[CatPLDLockedPerson]
                    WHERE RFC LIKE ?
                """, (f"%{rfc_norm}%",))
                rows.extend(cursor.fetchall())
            
            # Procesar resultados — dedup por (nombre_normalizado)
            mejores: dict[str, dict] = {}
            for row in rows:
                id_lista = row[0]
                nombre_lista = row[2] or row[1] or ""  # FullName o LockedPersonName
                rfc_lista = row[5] or ""
                fecha_nac = row[4] if row[4] and str(row[4]) != "1900-01-01" else None
                ap_paterno = row[8] or ""
                ap_materno = row[9] or ""
                info_adicional = row[10] or ""
                activo = row[11]
                
                # Calcular score
                score, explicaciones = calcular_score_coincidencia(
                    persona=persona,
                    nombre_lista=nombre_lista,
                    rfc_lista=rfc_lista,
                    apellido_paterno_lista=ap_paterno,
                    apellido_materno_lista=ap_materno,
                    fecha_nac_lista=fecha_nac,
                )
                
                if score < UMBRAL_DESCARTAR:
                    continue
                
                # Dedup key: nombre normalizado (misma persona con múltiples registros)
                dedup_key = normalizar_nombre(nombre_lista)
                
                if dedup_key not in mejores or score > mejores[dedup_key]["score"]:
                    mejores[dedup_key] = {
                        "nombre_lista": nombre_lista,
                        "rfc_lista": rfc_lista,
                        "fecha_nac": fecha_nac,
                        "info_adicional": info_adicional,
                        "activo": activo,
                        "score": score,
                        "explicaciones": explicaciones,
                    }
            
            for entry in mejores.values():
                coinc = CoincidenciaLista(
                    tipo_lista=TipoLista.BLOQUEADOS_UIF,
                    nombre_en_lista=entry["nombre_lista"],
                    rfc_en_lista=entry["rfc_lista"],
                    fecha_nacimiento_lista=entry["fecha_nac"],
                    tabla_origen="CatPLDLockedPerson",
                    score=entry["score"],
                    nivel_coincidencia=determinar_nivel_coincidencia(entry["score"]),
                    match_nombre=calcular_similitud_texto(persona.nombre, entry["nombre_lista"]),
                    match_rfc=(normalizar_rfc(persona.rfc) == normalizar_rfc(entry["rfc_lista"])) if persona.rfc and entry["rfc_lista"] else False,
                    fuente="UIF - Personas Bloqueadas",
                    categoria="Bloqueados SHCP/UIF",
                    situacion="BLOQUEADO" if entry["activo"] else "DESBLOQUEADO",
                    informacion_adicional=entry["info_adicional"][:500] if entry["info_adicional"] else "",
                    activo=entry["activo"] if entry["activo"] is not None else True,
                    explicacion_score=entry["explicaciones"],
                )
                coincidencias.append(coinc)
            
        except Exception as e:
            error_msg = f"Error buscando en Bloqueados UIF: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
        
        return coincidencias
    
    def _buscar_lista_negra(
        self,
        persona: PersonaBuscada,
    ) -> list[CoincidenciaLista]:
        """
        Busca en la lista negra consolidada (OFAC, PEP, SAT69, etc.).
        """
        coincidencias = []
        
        try:
            conn = self._conectar()
            cursor = conn.cursor()
            
            nombre_buscar = normalizar_nombre(persona.nombre)
            
            if persona.tipo_persona == "moral":
                # Personas morales: buscar en FirstName (que contiene razón social)
                # TOP 200 para capturar todas las variantes antes del dedup
                query = """
                    SELECT TOP 200
                        BlackListEntryID, FirstName, LastName, SecondLastName,
                        Source, Category, SubCategory, Remarks,
                        TaxId, CURP, BirthDate, Country, IsActive
                    FROM [dbo].[TraPLDBlackListEntry]
                    WHERE FirstName LIKE ? OR LastName LIKE ? OR SecondLastName LIKE ?
                    ORDER BY FirstName
                """
                cursor.execute(query, (
                    f"%{nombre_buscar}%",
                    f"%{nombre_buscar}%",
                    f"%{nombre_buscar}%",
                ))
            else:
                # Personas físicas: buscar por componentes de nombre
                comp = extraer_componentes_nombre(persona.nombre)
                
                conditions = []
                params = []
                
                if comp["nombres"]:
                    primer_nombre = comp["nombres"].split()[0]
                    conditions.append("FirstName LIKE ?")
                    params.append(f"%{primer_nombre}%")
                
                if comp["apellido_paterno"]:
                    conditions.append("LastName LIKE ?")
                    params.append(f"%{comp['apellido_paterno']}%")
                
                if comp["apellido_materno"]:
                    conditions.append("SecondLastName LIKE ?")
                    params.append(f"%{comp['apellido_materno']}%")
                
                if not conditions:
                    return []
                
                # TOP 200 para capturar todas las variantes antes del dedup
                query = f"""
                    SELECT TOP 200
                        BlackListEntryID, FirstName, LastName, SecondLastName,
                        Source, Category, SubCategory, Remarks,
                        TaxId, CURP, BirthDate, Country, IsActive
                    FROM [dbo].[TraPLDBlackListEntry]
                    WHERE {' AND '.join(conditions)}
                    ORDER BY FirstName, LastName
                """
                cursor.execute(query, params)
            
            rows = cursor.fetchall()
            
            # Buscar por RFC/TaxId
            if persona.rfc:
                rfc_norm = normalizar_rfc(persona.rfc)
                cursor.execute("""
                    SELECT TOP 10
                        BlackListEntryID, FirstName, LastName, SecondLastName,
                        Source, Category, SubCategory, Remarks,
                        TaxId, CURP, BirthDate, Country, IsActive
                    FROM [dbo].[TraPLDBlackListEntry]
                    WHERE TaxId LIKE ?
                """, (f"%{rfc_norm}%",))
                rows.extend(cursor.fetchall())
            
            # Procesar resultados — deduplicar por (nombre_normalizado, fuente)
            # La misma persona puede tener muchas filas con diferentes IDs;
            # quedarnos solo con la de mayor score por combinación única.
            mejores: dict[tuple[str, str], dict] = {}  # key → {row, score, coinc}
            for row in rows:
                id_lista = row[0]
                first_name = row[1] or ""
                last_name = row[2] or ""
                second_last_name = row[3] or ""
                source = row[4] or ""
                category = row[5] or ""
                subcategory = row[6] or ""
                remarks = row[7] or ""
                tax_id = row[8] or ""
                curp = row[9] or ""
                birth_date_str = row[10] or ""
                country = row[11] or ""
                activo = row[12]
                
                # Construir nombre completo
                nombre_completo = " ".join(filter(None, [first_name, last_name, second_last_name]))
                
                # Clave de dedup: nombre normalizado + fuente
                dedup_key = (normalizar_nombre(nombre_completo), normalizar_nombre(source))
                
                # Parsear fecha de nacimiento
                fecha_nac = None
                if birth_date_str and birth_date_str not in ["", "NULL"]:
                    try:
                        if "-" in birth_date_str:
                            fecha_nac = datetime.strptime(birth_date_str[:10], "%Y-%m-%d").date()
                    except Exception:
                        pass
                
                # Calcular score
                score, explicaciones = calcular_score_coincidencia(
                    persona=persona,
                    nombre_lista=nombre_completo,
                    rfc_lista=tax_id,
                    curp_lista=curp,
                    apellido_paterno_lista=last_name,
                    apellido_materno_lista=second_last_name,
                    fecha_nac_lista=fecha_nac,
                )
                
                if score >= UMBRAL_DESCARTAR:
                    # Solo guardar si es mejor que una entrada previa con la misma key
                    if dedup_key not in mejores or score > mejores[dedup_key]["score"]:
                        coinc = CoincidenciaLista(
                            tipo_lista=TipoLista.LISTA_NEGRA,
                            nombre_en_lista=nombre_completo,
                            rfc_en_lista=tax_id,
                            curp_en_lista=curp,
                            fecha_nacimiento_lista=fecha_nac,
                            tabla_origen="TraPLDBlackListEntry",
                            score=score,
                            nivel_coincidencia=determinar_nivel_coincidencia(score),
                            match_nombre=calcular_similitud_texto(persona.nombre, nombre_completo),
                            match_rfc=(normalizar_rfc(persona.rfc) == normalizar_rfc(tax_id)) if persona.rfc and tax_id else False,
                            match_curp=(normalizar_rfc(persona.curp) == normalizar_rfc(curp)) if persona.curp and curp else False,
                            fuente=source,
                            categoria=category,
                            subcategoria=subcategory,
                            informacion_adicional=remarks[:500] if remarks else f"País: {country}" if country else "",
                            activo=activo if activo is not None else True,
                            explicacion_score=explicaciones,
                        )
                        mejores[dedup_key] = {"score": score, "coinc": coinc}
            
            coincidencias = [v["coinc"] for v in mejores.values()]
            
        except Exception as e:
            error_msg = f"Error buscando en Lista Negra: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
        
        return coincidencias
    
    def screening_persona(
        self,
        persona: PersonaBuscada,
    ) -> ResultadoScreening:
        """
        Realiza screening completo de una persona contra todas las listas.
        
        Args:
            persona: PersonaBuscada con datos de la persona a verificar
            
        Returns:
            ResultadoScreening con todas las coincidencias encontradas
        """
        resultado = ResultadoScreening(
            persona=persona,
            listas_consultadas=[
                "CatPLD69BPerson (Lista 69-B SAT)",
                "CatPLDLockedPerson (Bloqueados UIF)",
                "TraPLDBlackListEntry (Lista Negra Consolidada)",
            ],
        )
        
        logger.info(f"Iniciando screening: {persona.nombre} ({persona.tipo_persona})")
        
        todas_coincidencias = []
        
        # ── Lista 69-B SAT ──
        try:
            coinc_69b = self._buscar_lista_69b(persona)
            todas_coincidencias.extend(coinc_69b)
            resultado.listas_exitosas.append("CatPLD69BPerson (Lista 69-B SAT)")
        except Exception as e:
            error_msg = f"ERROR CONEXIÓN Lista 69-B SAT: {e}"
            logger.error(error_msg)
            resultado.errores.append(error_msg)
            resultado.listas_fallidas.append("CatPLD69BPerson (Lista 69-B SAT)")
            resultado.screening_incompleto = True
        
        # ── Bloqueados UIF ──
        try:
            coinc_uif = self._buscar_bloqueados_uif(persona)
            todas_coincidencias.extend(coinc_uif)
            resultado.listas_exitosas.append("CatPLDLockedPerson (Bloqueados UIF)")
        except Exception as e:
            error_msg = f"ERROR CONEXIÓN Bloqueados UIF: {e}"
            logger.error(error_msg)
            resultado.errores.append(error_msg)
            resultado.listas_fallidas.append("CatPLDLockedPerson (Bloqueados UIF)")
            resultado.screening_incompleto = True
        
        # ── Lista Negra Consolidada ──
        try:
            coinc_negra = self._buscar_lista_negra(persona)
            todas_coincidencias.extend(coinc_negra)
            resultado.listas_exitosas.append("TraPLDBlackListEntry (Lista Negra Consolidada)")
        except Exception as e:
            error_msg = f"ERROR CONEXIÓN Lista Negra Consolidada: {e}"
            logger.error(error_msg)
            resultado.errores.append(error_msg)
            resultado.listas_fallidas.append("TraPLDBlackListEntry (Lista Negra Consolidada)")
            resultado.screening_incompleto = True
        
        # Ordenar por score descendente
        todas_coincidencias.sort(key=lambda c: c.score, reverse=True)
        
        resultado.coincidencias = todas_coincidencias
        resultado.tiene_coincidencias = len(todas_coincidencias) > 0
        
        if todas_coincidencias:
            resultado.coincidencia_mas_alta = todas_coincidencias[0]
            resultado.score_maximo = todas_coincidencias[0].score
            resultado.nivel_riesgo = todas_coincidencias[0].nivel_coincidencia
            
            # Determinar si requiere acciones
            if resultado.nivel_riesgo == NivelCoincidencia.CONFIRMADO:
                resultado.requiere_escalamiento = True
                resultado.requiere_revision_manual = True
            elif resultado.nivel_riesgo == NivelCoincidencia.PROBABLE:
                resultado.requiere_revision_manual = True
            elif resultado.nivel_riesgo == NivelCoincidencia.POSIBLE:
                resultado.requiere_revision_manual = True
        
        logger.info(
            f"Screening completado: {persona.nombre} - "
            f"{len(todas_coincidencias)} coincidencia(s), "
            f"score máximo: {resultado.score_maximo}, "
            f"listas OK: {len(resultado.listas_exitosas)}, "
            f"listas FALLIDAS: {len(resultado.listas_fallidas)}"
        )
        
        return resultado
    
    def screening_lote(
        self,
        personas: list[PersonaBuscada],
    ) -> ResumenScreening:
        """
        Realiza screening de múltiples personas.
        
        Args:
            personas: Lista de PersonaBuscada
            
        Returns:
            ResumenScreening con resultados de todas las personas
        """
        resumen = ResumenScreening(total_personas=len(personas))
        
        logger.info(f"Iniciando screening en lote: {len(personas)} persona(s)")
        
        for persona in personas:
            resultado = self.screening_persona(persona)
            resumen.resultados.append(resultado)
            
            if resultado.tiene_coincidencias:
                resumen.personas_con_coincidencias += 1
                
                nivel = resultado.nivel_riesgo
                if nivel == NivelCoincidencia.CONFIRMADO:
                    resumen.coincidencias_confirmadas += 1
                    resumen.tiene_coincidencias_criticas = True
                    resumen.requiere_escalamiento = True
                elif nivel == NivelCoincidencia.PROBABLE:
                    resumen.coincidencias_probables += 1
                elif nivel == NivelCoincidencia.POSIBLE:
                    resumen.coincidencias_posibles += 1
                elif nivel == NivelCoincidencia.HOMONIMO:
                    resumen.homonimos_descartados += 1
            
            if resultado.errores:
                resumen.errores_conexion.extend(resultado.errores)
            
            if resultado.screening_incompleto:
                resumen.screening_incompleto = True
        
        logger.info(
            f"Screening en lote completado: "
            f"{resumen.personas_con_coincidencias}/{resumen.total_personas} con coincidencias, "
            f"{resumen.coincidencias_confirmadas} confirmada(s), "
            f"screening_incompleto={resumen.screening_incompleto}"
        )
        
        return resumen


# ═══════════════════════════════════════════════════════════════════
#  FUNCIONES DE ALTO NIVEL
# ═══════════════════════════════════════════════════════════════════

def convertir_persona_identificada_a_buscada(
    persona: dict[str, Any],
) -> PersonaBuscada:
    """
    Convierte un dict de PersonaIdentificada a PersonaBuscada.
    """
    return PersonaBuscada(
        nombre=persona.get("nombre", ""),
        rfc=persona.get("rfc", ""),
        curp=persona.get("curp", ""),
        tipo_persona=persona.get("tipo_persona", "fisica"),
        rol=persona.get("rol", ""),
        fuente=persona.get("fuente", ""),
    )


def ejecutar_screening_completo(
    personas_identificadas: list[dict[str, Any]],
    config: dict[str, str] | None = None,
) -> ResumenScreening:
    """
    Ejecuta screening completo para una lista de personas identificadas.
    
    Args:
        personas_identificadas: Lista de dicts con datos de PersonaIdentificada
        config: Configuración opcional de conexión a BD
        
    Returns:
        ResumenScreening con todos los resultados
    """
    # Convertir a PersonaBuscada
    personas = [
        convertir_persona_identificada_a_buscada(p)
        for p in personas_identificadas
        if p.get("requiere_screening", True)
    ]
    
    # Ejecutar screening
    service = BlacklistScreeningService(config)
    try:
        resumen = service.screening_lote(personas)
    finally:
        service.cerrar()
    
    return resumen


# ═══════════════════════════════════════════════════════════════════
#  MAIN PARA PRUEBAS
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    # Prueba con datos de ejemplo
    personas_test = [
        PersonaBuscada(
            nombre="ARTURO PONS AGUIRRE",
            tipo_persona="fisica",
            rol="accionista",
        ),
        PersonaBuscada(
            nombre="SOLUCIONES CAPITAL X S.A. DE C.V.",
            rfc="SCX190531824",
            tipo_persona="moral",
            rol="empresa",
        ),
        PersonaBuscada(
            nombre="JUAN CARLOS LOPEZ GARCIA",
            tipo_persona="fisica",
            rol="representante_legal",
        ),
    ]
    
    print("=" * 70)
    print("PRUEBA DE SCREENING CONTRA LISTAS NEGRAS")
    print("=" * 70)
    
    service = BlacklistScreeningService()
    
    for persona in personas_test:
        print(f"\n>>> Buscando: {persona.nombre} ({persona.tipo_persona})")
        resultado = service.screening_persona(persona)
        
        if resultado.tiene_coincidencias:
            print(f"  ⚠️  {len(resultado.coincidencias)} coincidencia(s) encontrada(s)")
            print(f"  Score máximo: {resultado.score_maximo}")
            print(f"  Nivel: {resultado.nivel_riesgo.value}")
            
            for i, coinc in enumerate(resultado.coincidencias[:3], 1):
                print(f"\n  [{i}] {coinc.nombre_en_lista}")
                print(f"      Lista: {coinc.tipo_lista.value}")
                print(f"      Score: {coinc.score} ({coinc.nivel_coincidencia.value})")
                print(f"      Fuente: {coinc.fuente}")
                if coinc.situacion:
                    print(f"      Situación: {coinc.situacion}")
                print("      Explicación:")
                for exp in coinc.explicacion_score[:5]:
                    print(f"        - {exp}")
        else:
            print("  ✅ Sin coincidencias en listas negras")
        
        if resultado.errores:
            print(f"  ❌ Errores: {resultado.errores}")
    
    service.cerrar()
    print("\n" + "=" * 70)
    print("FIN DE PRUEBA")


# ═══════════════════════════════════════════════════════════════════
#  GENERADOR DE REPORTE TEXTO
# ═══════════════════════════════════════════════════════════════════

def generar_reporte_screening(
    resumen: ResumenScreening,
    rfc: str,
    razon_social: str,
) -> str:
    """
    Genera un reporte de texto formateado del screening.
    
    Args:
        resumen: ResumenScreening con los resultados
        rfc: RFC de la empresa
        razon_social: Razón social de la empresa
    
    Returns:
        Texto formateado del reporte
    """
    lineas = [
        "═" * 70,
        "ETAPA 2 — SCREENING CONTRA LISTAS NEGRAS / PEPs",
        "═" * 70,
        "",
        f"Empresa : {razon_social}",
        f"RFC     : {rfc}",
        "",
        "─" * 50,
        "RESUMEN",
        "─" * 50,
        f"  Total personas analizadas  : {resumen.total_personas}",
        f"  Con coincidencias          : {resumen.personas_con_coincidencias}",
        f"  Coincidencias confirmadas  : {resumen.coincidencias_confirmadas}",
        f"  Coincidencias probables    : {resumen.coincidencias_probables}",
        f"  Coincidencias posibles     : {resumen.coincidencias_posibles}",
        f"  Homónimos descartados      : {resumen.homonimos_descartados}",
        "",
    ]
    
    # Resultado global
    if resumen.screening_incompleto:
        lineas.append("🚨 RESULTADO: SCREENING INCOMPLETO — Errores de conexión")
    elif resumen.tiene_coincidencias_criticas:
        lineas.append("⚠️ RESULTADO: COINCIDENCIAS CRÍTICAS DETECTADAS")
        lineas.append("   → Requiere escalamiento a Comité PLD")
    elif resumen.personas_con_coincidencias > 0:
        lineas.append("⚠️ RESULTADO: COINCIDENCIAS ENCONTRADAS")
        lineas.append("   → Requiere revisión manual")
    else:
        lineas.append("✅ RESULTADO: SIN COINCIDENCIAS")
        lineas.append("   → Puede continuar al siguiente paso")
    
    lineas.append("")
    
    # Detalle por persona
    lineas.append("─" * 50)
    lineas.append("DETALLE POR PERSONA")
    lineas.append("─" * 50)
    
    for i, resultado in enumerate(resumen.resultados, 1):
        persona = resultado.persona
        lineas.append(f"\n  [{i}] {persona.nombre}")
        lineas.append(f"      Tipo: {persona.tipo_persona} | Rol: {persona.rol}")
        if persona.rfc:
            lineas.append(f"      RFC: {persona.rfc}")
        if persona.curp:
            lineas.append(f"      CURP: {persona.curp}")
        
        lineas.append(f"      Listas consultadas: {', '.join(resultado.listas_consultadas) or 'Ninguna'}")
        
        if resultado.listas_exitosas:
            lineas.append(f"      ✅ Exitosas: {', '.join(resultado.listas_exitosas)}")
        if resultado.listas_fallidas:
            lineas.append(f"      🚨 Fallidas: {', '.join(resultado.listas_fallidas)}")
        
        if resultado.tiene_coincidencias:
            lineas.append(f"      ⚠️ Nivel de riesgo: {resultado.nivel_riesgo.value}")
            lineas.append(f"      Score máximo: {resultado.score_maximo}")
            
            for j, c in enumerate(resultado.coincidencias, 1):
                lineas.append(f"\n        Coincidencia #{j}:")
                lineas.append(f"          Tabla SQL:        {c.tabla_origen}")
                lineas.append(f"          Tipo lista:       {c.tipo_lista.value}")
                lineas.append(f"          Fuente:           {c.fuente}")
                lineas.append(f"          Nombre en lista:  {c.nombre_en_lista}")
                if c.rfc_en_lista:
                    lineas.append(f"          RFC en lista:     {c.rfc_en_lista}")
                if c.curp_en_lista:
                    lineas.append(f"          CURP en lista:    {c.curp_en_lista}")
                lineas.append(f"          Score:            {c.score} ({c.nivel_coincidencia.value})")
                lineas.append(f"          Similitud nombre: {c.match_nombre*100:.1f}%")
                lineas.append(f"          Match RFC:        {'SÍ' if c.match_rfc else 'No'}")
                lineas.append(f"          Match CURP:       {'SÍ' if c.match_curp else 'No'}")
                if c.categoria:
                    lineas.append(f"          Categoría:        {c.categoria}")
                if c.situacion:
                    lineas.append(f"          Situación:        {c.situacion}")
                if c.informacion_adicional:
                    lineas.append(f"          Info adicional:   {c.informacion_adicional[:200]}")
                if c.explicacion_score:
                    lineas.append(f"          Scoring:")
                    for exp in c.explicacion_score:
                        lineas.append(f"            • {exp}")
        else:
            lineas.append("      ✅ Sin coincidencias")
        
        if resultado.errores:
            lineas.append(f"      ❌ Errores: {', '.join(resultado.errores)}")
    
    # Errores globales
    if resumen.errores_conexion:
        lineas.append("\n")
        lineas.append("─" * 50)
        lineas.append("ERRORES DE CONEXIÓN")
        lineas.append("─" * 50)
        for err in set(resumen.errores_conexion):
            lineas.append(f"  • {err}")
    
    lineas.append("")
    lineas.append("═" * 70)
    lineas.append("FIN DEL REPORTE ETAPA 2")
    lineas.append("═" * 70)
    
    return "\n".join(lineas)
