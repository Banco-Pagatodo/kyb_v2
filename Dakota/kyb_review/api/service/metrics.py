# api/service/metrics.py
"""
Módulo de métricas y logging para el sistema de validación KYB.
Proporciona tracking de scores, tiempos, costos y estadísticas de extracción.

Características:
- Desglose de latencia por servicio (Azure DI, OpenAI)
- Estimación de costos de API
- Alertas por degradación de rendimiento
- Métricas de circuit breaker
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from enum import Enum

from ..config import JSON_DIR

logger = logging.getLogger(__name__)

# Directorio para métricas
METRICS_DIR = Path(JSON_DIR) / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE COSTOS (precios aproximados por unidad)
# ═══════════════════════════════════════════════════════════════════════════════

class APICosts:
    """Costos estimados de APIs (USD)."""
    # Azure Document Intelligence (por página)
    AZURE_DI_READ_PER_PAGE = 0.001       # $1 por 1000 páginas
    AZURE_DI_CUSTOM_PER_PAGE = 0.01      # $10 por 1000 páginas
    AZURE_DI_LAYOUT_PER_PAGE = 0.01      # $10 por 1000 páginas
    
    # Azure OpenAI GPT-4o (por 1000 tokens)
    OPENAI_GPT4O_INPUT_PER_1K = 0.005    # $5 por 1M tokens
    OPENAI_GPT4O_OUTPUT_PER_1K = 0.015   # $15 por 1M tokens
    
    # Azure OpenAI GPT-4o-mini (por 1000 tokens)  
    OPENAI_GPT4O_MINI_INPUT_PER_1K = 0.00015   # $0.15 por 1M tokens
    OPENAI_GPT4O_MINI_OUTPUT_PER_1K = 0.0006   # $0.60 por 1M tokens


# ═══════════════════════════════════════════════════════════════════════════════
# TIPOS DE ALERTAS
# ═══════════════════════════════════════════════════════════════════════════════

class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Representa una alerta del sistema."""
    severity: AlertSeverity
    message: str
    metric_name: str
    value: float
    threshold: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> dict:
        return {**asdict(self), "severity": self.severity.value}


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE UMBRALES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AlertThresholds:
    """Umbrales para generar alertas."""
    # Scores
    min_score_warning: float = 0.70
    min_score_critical: float = 0.50
    
    # Tiempos (segundos)
    max_total_time_warning: float = 30.0
    max_total_time_critical: float = 60.0
    max_di_time_warning: float = 15.0
    max_openai_time_warning: float = 10.0
    
    # Tasas de error
    error_rate_warning: float = 0.10     # 10%
    error_rate_critical: float = 0.25    # 25%
    
    # Costos (USD por día)
    daily_cost_warning: float = 50.0
    daily_cost_critical: float = 100.0


class ValidationMetrics:
    """
    Singleton para tracking de métricas de validación.
    Registra scores, tiempos, costos y estadísticas por tipo de documento.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Inicializa estructuras de datos."""
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_start = datetime.now()
        self.metrics = defaultdict(list)
        self.alerts: List[Alert] = []
        self.thresholds = AlertThresholds()
        self._alert_callbacks: List[Callable[[Alert], None]] = []
        
        # Resumen por tipo de documento
        self.summary = defaultdict(lambda: {
            "total": 0,
            "success": 0,
            "errors": 0,
            "revision_required": 0,
            "scores": [],
            "processing_times": [],
            "di_times": [],
            "openai_times": [],
            "pages_processed": 0,
            "tokens_input": 0,
            "tokens_output": 0,
        })
        
        # Métricas de servicios externos
        self.service_metrics = {
            "azure_di": {
                "calls": 0,
                "errors": 0,
                "total_time": 0.0,
                "pages": 0,
            },
            "azure_openai": {
                "calls": 0,
                "errors": 0,
                "total_time": 0.0,
                "tokens_in": 0,
                "tokens_out": 0,
            }
        }
    
    def register_alert_callback(self, callback: Callable[[Alert], None]) -> None:
        """Registra callback para notificaciones de alertas."""
        self._alert_callbacks.append(callback)
    
    def record_validation(
        self,
        doc_type: str,
        file_name: str,
        score: float,
        campos: Dict[str, Any],
        processing_time: float = 0.0,
        error: Optional[str] = None,
        requires_revision: bool = False,
        di_time: float = 0.0,
        openai_time: float = 0.0,
        pages: int = 1,
        tokens_in: int = 0,
        tokens_out: int = 0
    ) -> None:
        """
        Registra una validación completada.
        
        Args:
            doc_type: Tipo de documento
            file_name: Nombre del archivo procesado
            score: Score global de validación (0.0-1.0)
            campos: Diccionario con validación por campo
            processing_time: Tiempo de procesamiento en segundos
            error: Mensaje de error si hubo fallo
            requires_revision: Si requiere revisión manual
            di_time: Tiempo de Azure Document Intelligence
            openai_time: Tiempo de Azure OpenAI
            pages: Páginas procesadas
            tokens_in: Tokens de entrada usados
            tokens_out: Tokens de salida generados
        """
        timestamp = datetime.now().isoformat()
        
        record = {
            "timestamp": timestamp,
            "file_name": file_name,
            "score": score,
            "campos": {k: v.get("confianza", 0) for k, v in campos.items() if isinstance(v, dict)},
            "processing_time": processing_time,
            "di_time": di_time,
            "openai_time": openai_time,
            "pages": pages,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "error": error,
            "requires_revision": requires_revision,
        }
        
        self.metrics[doc_type].append(record)
        
        # Actualizar resumen
        summary = self.summary[doc_type]
        summary["total"] += 1
        summary["scores"].append(score)
        summary["processing_times"].append(processing_time)
        summary["di_times"].append(di_time)
        summary["openai_times"].append(openai_time)
        summary["pages_processed"] += pages
        summary["tokens_input"] += tokens_in
        summary["tokens_output"] += tokens_out
        
        if error:
            summary["errors"] += 1
        elif requires_revision:
            summary["revision_required"] += 1
        else:
            summary["success"] += 1
        
        # Verificar alertas
        self._check_alerts(doc_type, score, processing_time, di_time, openai_time)
        
        # Log para producción
        level = logging.INFO if score >= 0.7 else logging.WARNING
        logger.log(
            level,
            f"[METRICS] {doc_type}: {file_name} | Score: {score:.0%} | "
            f"Time: {processing_time:.2f}s (DI: {di_time:.2f}s, LLM: {openai_time:.2f}s) | "
            f"Pages: {pages} | Tokens: {tokens_in}/{tokens_out} | Revision: {requires_revision}"
        )
    
    def record_service_call(
        self,
        service: str,  # "azure_di" or "azure_openai"
        success: bool,
        duration: float,
        pages: int = 0,
        tokens_in: int = 0,
        tokens_out: int = 0
    ) -> None:
        """
        Registra una llamada a servicio externo.
        
        Args:
            service: Nombre del servicio
            success: Si fue exitosa
            duration: Duración en segundos
            pages: Páginas procesadas (para DI)
            tokens_in: Tokens de entrada (para OpenAI)
            tokens_out: Tokens de salida (para OpenAI)
        """
        if service not in self.service_metrics:
            return
        
        svc = self.service_metrics[service]
        svc["calls"] += 1
        svc["total_time"] += duration
        
        if not success:
            svc["errors"] += 1
        
        if service == "azure_di":
            svc["pages"] += pages
        elif service == "azure_openai":
            svc["tokens_in"] += tokens_in
            svc["tokens_out"] += tokens_out
    
    def _check_alerts(
        self, 
        doc_type: str, 
        score: float, 
        total_time: float,
        di_time: float,
        openai_time: float
    ) -> None:
        """Verifica condiciones de alerta."""
        th = self.thresholds
        
        # Alerta por score bajo
        if score < th.min_score_critical:
            self._emit_alert(AlertSeverity.CRITICAL, 
                f"Score crítico para {doc_type}", "score", score, th.min_score_critical)
        elif score < th.min_score_warning:
            self._emit_alert(AlertSeverity.WARNING,
                f"Score bajo para {doc_type}", "score", score, th.min_score_warning)
        
        # Alerta por tiempo total
        if total_time > th.max_total_time_critical:
            self._emit_alert(AlertSeverity.CRITICAL,
                f"Tiempo de procesamiento crítico", "total_time", total_time, th.max_total_time_critical)
        elif total_time > th.max_total_time_warning:
            self._emit_alert(AlertSeverity.WARNING,
                f"Tiempo de procesamiento alto", "total_time", total_time, th.max_total_time_warning)
        
        # Alerta por tiempo de DI
        if di_time > th.max_di_time_warning:
            self._emit_alert(AlertSeverity.WARNING,
                f"Azure DI lento", "di_time", di_time, th.max_di_time_warning)
        
        # Alerta por tiempo de OpenAI
        if openai_time > th.max_openai_time_warning:
            self._emit_alert(AlertSeverity.WARNING,
                f"OpenAI lento", "openai_time", openai_time, th.max_openai_time_warning)
        
        # Verificar tasa de error
        self._check_error_rate_alert()
        
        # Verificar costos
        self._check_cost_alert()
    
    def _emit_alert(
        self, 
        severity: AlertSeverity, 
        message: str, 
        metric_name: str, 
        value: float, 
        threshold: float
    ) -> None:
        """Emite una alerta y notifica callbacks."""
        alert = Alert(
            severity=severity,
            message=message,
            metric_name=metric_name,
            value=value,
            threshold=threshold
        )
        
        self.alerts.append(alert)
        
        # Limitar historial de alertas
        if len(self.alerts) > 1000:
            self.alerts = self.alerts[-500:]
        
        # Log la alerta
        log_level = {
            AlertSeverity.INFO: logging.INFO,
            AlertSeverity.WARNING: logging.WARNING,
            AlertSeverity.CRITICAL: logging.ERROR
        }.get(severity, logging.WARNING)
        
        logger.log(log_level, f"[ALERT] {severity.value.upper()}: {message} ({metric_name}={value:.2f}, threshold={threshold:.2f})")
        
        # Notificar callbacks
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")
    
    def _check_error_rate_alert(self) -> None:
        """Verifica tasa de error global."""
        total = sum(s["total"] for s in self.summary.values())
        errors = sum(s["errors"] for s in self.summary.values())
        
        if total < 10:  # Necesita mínimo de muestras
            return
        
        error_rate = errors / total
        th = self.thresholds
        
        if error_rate > th.error_rate_critical:
            self._emit_alert(AlertSeverity.CRITICAL,
                "Tasa de error crítica", "error_rate", error_rate, th.error_rate_critical)
        elif error_rate > th.error_rate_warning:
            self._emit_alert(AlertSeverity.WARNING,
                "Tasa de error elevada", "error_rate", error_rate, th.error_rate_warning)
    
    def _check_cost_alert(self) -> None:
        """Verifica costos estimados del día."""
        estimated_cost = self.get_estimated_cost()
        daily_cost = estimated_cost.get("total_usd", 0)
        
        # Extrapolar a 24 horas
        elapsed = (datetime.now() - self.session_start).total_seconds() / 3600
        if elapsed > 0:
            daily_projection = daily_cost * (24 / elapsed)
        else:
            daily_projection = 0
        
        th = self.thresholds
        
        if daily_projection > th.daily_cost_critical:
            self._emit_alert(AlertSeverity.CRITICAL,
                "Proyección de costos crítica", "daily_cost_projection", daily_projection, th.daily_cost_critical)
        elif daily_projection > th.daily_cost_warning:
            self._emit_alert(AlertSeverity.WARNING,
                "Proyección de costos alta", "daily_cost_projection", daily_projection, th.daily_cost_warning)
    
    def get_estimated_cost(self) -> Dict[str, float]:
        """
        Calcula costos estimados de la sesión.
        
        Returns:
            Diccionario con desglose de costos en USD
        """
        svc = self.service_metrics
        
        # Costos Azure DI
        di_cost = svc["azure_di"]["pages"] * APICosts.AZURE_DI_LAYOUT_PER_PAGE
        
        # Costos OpenAI (asumiendo GPT-4o-mini)
        openai_cost = (
            (svc["azure_openai"]["tokens_in"] / 1000) * APICosts.OPENAI_GPT4O_MINI_INPUT_PER_1K +
            (svc["azure_openai"]["tokens_out"] / 1000) * APICosts.OPENAI_GPT4O_MINI_OUTPUT_PER_1K
        )
        
        return {
            "azure_di_usd": round(di_cost, 4),
            "azure_openai_usd": round(openai_cost, 4),
            "total_usd": round(di_cost + openai_cost, 4),
            "pages_processed": svc["azure_di"]["pages"],
            "tokens_input": svc["azure_openai"]["tokens_in"],
            "tokens_output": svc["azure_openai"]["tokens_out"],
        }
    
    def get_summary(self, doc_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Obtiene resumen de métricas.
        
        Args:
            doc_type: Tipo específico o None para todos
        
        Returns:
            Diccionario con resumen de métricas
        """
        if doc_type:
            summary = self.summary[doc_type]
            return {
                "doc_type": doc_type,
                "total_processed": summary["total"],
                "success_count": summary["success"],
                "error_count": summary["errors"],
                "revision_count": summary["revision_required"],
                "avg_score": sum(summary["scores"]) / len(summary["scores"]) if summary["scores"] else 0,
                "min_score": min(summary["scores"]) if summary["scores"] else 0,
                "max_score": max(summary["scores"]) if summary["scores"] else 0,
                "avg_time": sum(summary["processing_times"]) / len(summary["processing_times"]) if summary["processing_times"] else 0,
                "avg_di_time": sum(summary["di_times"]) / len(summary["di_times"]) if summary["di_times"] else 0,
                "avg_openai_time": sum(summary["openai_times"]) / len(summary["openai_times"]) if summary["openai_times"] else 0,
                "total_pages": summary["pages_processed"],
                "total_tokens_in": summary["tokens_input"],
                "total_tokens_out": summary["tokens_output"],
            }
        
        # Resumen global
        return {
            doc: self.get_summary(doc)
            for doc in self.summary.keys()
        }
    
    def get_service_summary(self) -> Dict[str, Any]:
        """
        Obtiene resumen de métricas de servicios externos.
        
        Returns:
            Diccionario con métricas por servicio
        """
        result = {}
        
        for service, data in self.service_metrics.items():
            calls = data["calls"]
            avg_time = data["total_time"] / calls if calls > 0 else 0
            error_rate = data["errors"] / calls if calls > 0 else 0
            
            result[service] = {
                "total_calls": calls,
                "errors": data["errors"],
                "error_rate": round(error_rate, 4),
                "total_time_seconds": round(data["total_time"], 2),
                "avg_time_seconds": round(avg_time, 3),
            }
            
            if service == "azure_di":
                result[service]["pages_processed"] = data["pages"]
            elif service == "azure_openai":
                result[service]["tokens_in"] = data["tokens_in"]
                result[service]["tokens_out"] = data["tokens_out"]
        
        return result
    
    def get_alerts(
        self, 
        severity: Optional[AlertSeverity] = None,
        since_minutes: int = 60
    ) -> List[dict]:
        """
        Obtiene alertas recientes.
        
        Args:
            severity: Filtrar por severidad
            since_minutes: Alertas de los últimos N minutos
        
        Returns:
            Lista de alertas
        """
        cutoff = datetime.utcnow() - timedelta(minutes=since_minutes)
        cutoff_str = cutoff.isoformat()
        
        result = []
        for alert in self.alerts:
            if alert.timestamp < cutoff_str:
                continue
            if severity and alert.severity != severity:
                continue
            result.append(alert.to_dict())
        
        return result
    
    def get_low_confidence_fields(self, threshold: float = 0.7) -> Dict[str, List[str]]:
        """
        Identifica campos con baja confianza frecuente.
        
        Args:
            threshold: Umbral de confianza
        
        Returns:
            Diccionario con campos problemáticos por tipo de documento
        """
        problematic = {}
        
        for doc_type, records in self.metrics.items():
            field_scores = defaultdict(list)
            
            for record in records:
                for campo, conf in record.get("campos", {}).items():
                    field_scores[campo].append(conf)
            
            low_conf_fields = []
            for campo, scores in field_scores.items():
                valid_scores = [s for s in scores if s is not None]
                if valid_scores and sum(valid_scores) / len(valid_scores) < threshold:
                    avg = sum(valid_scores) / len(valid_scores)
                    low_conf_fields.append(f"{campo} (avg: {avg:.0%})")
            
            if low_conf_fields:
                problematic[doc_type] = low_conf_fields
        
        return problematic
    
    def save_to_file(self) -> str:
        """
        Guarda métricas a archivo JSON.
        
        Returns:
            Ruta del archivo guardado
        """
        output_path = METRICS_DIR / f"metrics_{self.session_id}.json"
        
        data = {
            "session_id": self.session_id,
            "session_start": self.session_start.isoformat(),
            "timestamp": datetime.now().isoformat(),
            "summary": self.get_summary(),
            "service_metrics": self.get_service_summary(),
            "estimated_cost": self.get_estimated_cost(),
            "low_confidence_fields": self.get_low_confidence_fields(),
            "recent_alerts": self.get_alerts(since_minutes=1440),  # Últimas 24h
            "details": dict(self.metrics),
        }
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"[METRICS] Saved to {output_path}")
        return str(output_path)
    
    def print_summary(self) -> None:
        """Imprime resumen de métricas en consola."""
        logger.info("\n" + "═" * 70)
        logger.info("RESUMEN DE METRICAS DE VALIDACION")
        logger.info("═" * 70)
        
        for doc_type in self.summary.keys():
            summary = self.get_summary(doc_type)
            logger.info(f"\n{doc_type.upper()}")
            logger.info(f"   • Total procesados: {summary['total_processed']}")
            logger.info(f"   • Exitosos: {summary['success_count']}")
            logger.info(f"   • Requieren revisión: {summary['revision_count']}")
            logger.error(f"   • Errores: {summary['error_count']}")
            logger.info(f"   • Score promedio: {summary['avg_score']:.0%}")
            logger.info(f"   • Tiempo promedio: {summary['avg_time']:.2f}s")
            logger.info(f"   • Tiempo DI promedio: {summary['avg_di_time']:.2f}s")
            logger.info(f"   • Tiempo OpenAI promedio: {summary['avg_openai_time']:.2f}s")
        
        # Campos problemáticos
        low_conf = self.get_low_confidence_fields()
        if low_conf:
            logger.warning("\n[ADVERTENCIA] CAMPOS CON BAJA CONFIANZA FRECUENTE:")
            for doc_type, fields in low_conf.items():
                logger.info(f"   {doc_type}: {', '.join(fields)}")
        
        # Costos estimados
        costs = self.get_estimated_cost()
        logger.info("\n[COSTOS ESTIMADOS]")
        logger.info(f"   • Azure DI: ${costs['azure_di_usd']:.4f}")
        logger.info(f"   • Azure OpenAI: ${costs['azure_openai_usd']:.4f}")
        logger.info(f"   • Total: ${costs['total_usd']:.4f}")
        
        # Alertas recientes
        critical = self.get_alerts(AlertSeverity.CRITICAL, since_minutes=60)
        warnings = self.get_alerts(AlertSeverity.WARNING, since_minutes=60)
        if critical or warnings:
            logger.info("\n[ALERTAS RECIENTES]")
            if critical:
                logger.info(f"   • CRITICAS: {len(critical)}")
            if warnings:
                logger.warning(f"   • ADVERTENCIAS: {len(warnings)}")
        
        logger.info("\n" + "═" * 70)
    
    def reset(self) -> None:
        """Reinicia métricas para nueva sesión."""
        self._initialize()


# Instancia global
metrics = ValidationMetrics()


def log_validation(
    doc_type: str,
    file_name: str,
    validation_result: Dict[str, Any],
    processing_time: float = 0.0,
    error: Optional[str] = None,
    di_time: float = 0.0,
    openai_time: float = 0.0,
    pages: int = 1,
    tokens_in: int = 0,
    tokens_out: int = 0
) -> None:
    """
    Función helper para registrar validación.
    
    Args:
        doc_type: Tipo de documento
        file_name: Nombre del archivo
        validation_result: Resultado de validate_extraction()
        processing_time: Tiempo de procesamiento
        error: Mensaje de error
        di_time: Tiempo de Azure DI
        openai_time: Tiempo de OpenAI
        pages: Páginas procesadas
        tokens_in: Tokens de entrada
        tokens_out: Tokens de salida
    """
    metrics.record_validation(
        doc_type=doc_type,
        file_name=file_name,
        score=validation_result.get("score_global", 0),
        campos=validation_result.get("campos", {}),
        processing_time=processing_time,
        error=error,
        requires_revision=validation_result.get("requiere_revision", False),
        di_time=di_time,
        openai_time=openai_time,
        pages=pages,
        tokens_in=tokens_in,
        tokens_out=tokens_out
    )


def log_service_call(
    service: str,
    success: bool,
    duration: float,
    **kwargs
) -> None:
    """
    Registra llamada a servicio externo.
    
    Args:
        service: "azure_di" o "azure_openai"
        success: Si fue exitosa
        duration: Duración en segundos
        **kwargs: pages, tokens_in, tokens_out según el servicio
    """
    metrics.record_service_call(
        service=service,
        success=success,
        duration=duration,
        **kwargs
    )


def get_metrics_summary() -> Dict[str, Any]:
    """Obtiene resumen de métricas actual."""
    return metrics.get_summary()


def get_service_metrics() -> Dict[str, Any]:
    """Obtiene métricas de servicios externos."""
    return metrics.get_service_summary()


def get_cost_estimate() -> Dict[str, float]:
    """Obtiene estimación de costos."""
    return metrics.get_estimated_cost()


def get_recent_alerts(severity: Optional[str] = None, minutes: int = 60) -> List[dict]:
    """
    Obtiene alertas recientes.
    
    Args:
        severity: "info", "warning", o "critical"
        minutes: Últimos N minutos
    """
    sev = AlertSeverity(severity) if severity else None
    return metrics.get_alerts(sev, minutes)


def save_metrics() -> str:
    """Guarda métricas a archivo."""
    return metrics.save_to_file()


def print_metrics() -> None:
    """Imprime resumen de métricas."""
    metrics.print_summary()
