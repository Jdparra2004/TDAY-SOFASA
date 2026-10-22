"""
model.py
--------
Estructuras de datos base para el reto de cadena de suministro CKD Sofasa.

Un `Container` representa un contenedor CKD que debe recorrer:
    puerto -> (directo a SOFASA) | (Suppla -> traslado -> SOFASA) -> producción

`Params` agrupa todos los parámetros operativos y de costos del reto
(capacidades, estándar de tiempo puerto->planta, costos). Todos son
configurables para poder reemplazar los valores sintéticos por datos
reales (Tracking, Programación N-1 / prog DIEL, TD Ingeniería CKD).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import List, Optional, Sequence, Union

Number = Union[int, float]


class EstadoContenedor(str, Enum):
    PROGRAMADO_EN_HORIZONTE = "PROGRAMADO_EN_HORIZONTE"
    EM_PROYECTADA = "EM_PROYECTADA"
    DIFERIDO_SIN_CUPO = "DIFERIDO_SIN_CUPO"
    EXCLUIDO_EN_PLANTA = "EXCLUIDO_EN_PLANTA"
    FUERA_VENTANA = "FUERA_VENTANA"


@dataclass
class Container:
    """Un contenedor CKD a programar."""

    id: str
    eta: int  # día (índice, 0 = inicio del horizonte) de arribo estimado a puerto
    need_by: Optional[int] = None  # fecha de ruptura de material: último día en que puede entrar a planta (None = sin fecha real)
    part_family: str = "N/D"  # familia de partes
    vessel: str = "N/D"  # buque o barco de origen para trazabilidad
    em_objetivo: Optional[int] = None
    em_previa: Optional[int] = None
    ruptura_real: Optional[int] = None
    need_by_estimado: bool = False
    origen: str = "N/D"
    etd: Optional[int] = None
    estado: Optional[EstadoContenedor] = None

    def __post_init__(self):
        if self.need_by is not None and self.need_by < self.eta:
            self.need_by = self.eta


def _broadcast(value: Union[Number, Sequence[Number]], horizon: int) -> List[float]:
    """Convierte un escalar o una lista en un arreglo diario de longitud `horizon`."""
    if isinstance(value, (int, float)):
        return [float(value)] * horizon
    values = list(value)
    if len(values) < horizon:
        values = values + [values[-1]] * (horizon - len(values))
    return [float(v) for v in values[:horizon]]


@dataclass
class Params:
    """Parámetros operativos y de costos (todos configurables).

    Los 6 parámetros expuestos al usuario:
      1. horizon (horizonte días)
      2. cap_sofasa_per_day (capacidad SOFASA por día)
      3. cap_suppla_per_week (capacidad Suppla por semana)
      4. cap_traslado_per_day (capacidad de traslado por día)
      5. transfer_days_allowed (días habilitados de traslado)
      6. start_weekday (fecha de planeación / día 0)
    """

    # --- 1. Horizonte de planeación ---
    horizon: int = 20  # días simulados/optimizados por defecto

    # --- 2. Capacidades operativas ---
    cap_sofasa_per_day: Union[Number, Sequence[Number]] = 14
    cap_suppla_per_week: Union[Number, Sequence[Number]] = 15
    cap_traslado_per_day: Union[Number, Sequence[Number]] = 2

    # --- 5. Días habilitados de traslado ---
    transfer_days_allowed: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])

    # --- 6. Fecha de planeación (día 0). start_weekday se deriva de esta fecha en build_params ---
    planning_date: Optional[date] = None
    start_weekday: int = 0

    # --- Constantes internas (regla del PDF / supuesto, no editable por el usuario) ---
    l_min: int = 7   # regla del PDF / supuesto: mínimo puerto->planta
    l_obj: int = 10  # regla del PDF / supuesto: objetivo puerto->planta
    l_max: int = 12  # regla del PDF / supuesto: máximo puerto->planta antes de demurrage
    dias_habiles_resta: int = 2  # regla del PDF / supuesto: días hábiles hábiles de holgura para EM objetivo
    USD_DEMURRAGE_DIA: float = 80.0  # regla del PDF / supuesto: costo diario demurrage por contenedor
    USD_TRASLADO_SUPPLA: float = 80.0  # regla del PDF / supuesto: costo fijo por traslado Suppla

    @property
    def horizon_solver(self) -> int:
        return self.horizon + self.l_max

    # --- Suppla reglas y permanencia ---
    min_suppla_stay_days: int = 1  # permanencia mínima en Suppla antes de traslado a SOFASA

    # --- Pesos de prioridad (unidades relativas, orden del PDF: ruptura > estándar > demurrage > capacidades > Suppla) ---
    cost_rupture: float = 1000.0        # Prioridad 1 (Ruptura): penalización por contenedor-día de retraso vs need_by real
    cost_rupture_event: float = 500.0   # Prioridad 1 (Ruptura): penalización fija por evento de ruptura (prioriza salvar)
    cost_em_objetivo_dia: float = 100.0 # Prioridad 2 (Estándar / Fecha objetivo): penalización por día de desviación vs em_objetivo
    cost_alert_day: float = 20.0        # Prioridad 3 (Estándar / Alertas): penalización por contenedor-día más allá de l_obj
    cost_suppla_day: float = 1.0        # Prioridad 5 (Suppla): costo por contenedor-día almacenado en Suppla

    # --- límite de tiempo del solver (constante interna, no editable por el usuario) ---
    solver_time_limit_s: float = 60.0

    # --- ventana máxima de espera que el optimizador puede considerar ---
    max_wait_days: int = 30  # tope de días desde ETA para restringir el tamaño del modelo

    # --- SOFASA días permitidos de recepción en planta (0=Lunes, ..., 6=Domingo) ---
    sofasa_days_allowed: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    sofasa_recibe_fin_de_semana: bool = True
    # festivos opcionales en Colombia
    holidays: List[date] = field(default_factory=list)

    def weekday_of(self, t: int) -> int:
        return (t + self.start_weekday) % 7

    def week_of(self, t: int) -> int:
        """Índice de semana calendario (lunes-domingo) del día t."""
        return (t + self.start_weekday) // 7

    def cap_sofasa(self) -> List[float]:
        base_arr = _broadcast(self.cap_sofasa_per_day, self.horizon_solver)
        return [
            v if (self.weekday_of(t) in self.sofasa_days_allowed and (self.sofasa_recibe_fin_de_semana or self.weekday_of(t) < 5)) else 0.0
            for t, v in enumerate(base_arr)
        ]

    def cap_traslado(self) -> List[float]:
        base_arr = _broadcast(self.cap_traslado_per_day, self.horizon_solver)
        return [
            val if self.weekday_of(t) in self.transfer_days_allowed else 0.0
            for t, val in enumerate(base_arr)
        ]

    def cap_suppla_weekly(self) -> List[float]:
        """Capacidad semanal de recepción en Suppla, una entrada por semana."""
        n_weeks = (self.horizon_solver // 7) + 2
        return _broadcast(self.cap_suppla_per_week, n_weeks)


@dataclass
class PlanEntry:
    """Decisión para un contenedor: ruta y fechas."""

    container_id: str
    route: str  # "direct" (puerto->SOFASA) o "suppla" (puerto->Suppla->SOFASA)
    em_day: int  # día de entrada a planta (EM)
    suppla_in_day: Optional[int] = None  # día de recepción en Suppla (si route == "suppla")


Plan = dict  # container_id -> PlanEntry
