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
from typing import List, Optional, Sequence, Union

Number = Union[int, float]


@dataclass
class Container:
    """Un contenedor CKD a programar."""

    id: str
    eta: int  # día (índice, 0 = inicio del horizonte) de arribo estimado a puerto
    need_by: int  # fecha de ruptura de material: último día en que puede entrar a planta
    part_family: str = "GEN"  # familia de partes (para refinamientos futuros por BOM)
    vessel: str = "GEN_BUQUE"  # buque o barco de origen para trazabilidad

    def __post_init__(self):
        if self.need_by < self.eta:
            # Una fecha de ruptura anterior al arribo es inconsistente; se relaja
            # a "arribo + margen mínimo" para que el modelo siga siendo resoluble
            # pero se reporta como caso crítico en las validaciones aguas abajo.
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

    Los valores por defecto son los de referencia de la diapositiva 7 del reto:
      - Recepción SOFASA: 14 contenedores/día
      - Recepción Suppla: 15 contenedores/semana
      - Traslado Suppla -> SOFASA: 3 contenedores/día
      - Estándar puerto->planta: mínimo 7, objetivo 10, máximo 12 días
    """

    horizon: int = 90  # días simulados/optimizados

    # --- capacidades operativas (pueden ser escalares o listas día a día) ---
    cap_sofasa_per_day: Union[Number, Sequence[Number]] = 14
    cap_suppla_per_week: Union[Number, Sequence[Number]] = 15
    cap_traslado_per_day: Union[Number, Sequence[Number]] = 3

    # --- estándar de tiempo puerto -> planta (días desde ETA) ---
    l_min: int = 7   # no es físicamente posible entrar antes de esto
    l_obj: int = 10  # objetivo: dentro del estándar
    l_max: int = 12  # máximo permitido antes de alerta crítica / demurrage

    # --- costos / penalizaciones (unidades relativas, calibrables) ---
    cost_suppla_day: float = 1.0       # costo por contenedor-día almacenado en Suppla
    cost_demurrage_day: float = 8.0    # costo por contenedor-día más allá de l_max
    cost_alert_day: float = 3.0        # penalización por contenedor-día más allá de l_obj
    cost_rupture: float = 100.0        # penalización por contenedor-día de retraso vs need_by

    # --- inventario inicial y consumo de producción ---
    init_inv_sofasa: int = 0
    init_inv_suppla: int = 0
    daily_consumption: Union[Number, Sequence[Number]] = 12  # contenedores-equivalentes/día

    # --- ventana máxima de espera que el optimizador puede considerar ---
    max_wait_days: int = 30  # tope de días desde ETA para restringir el tamaño del modelo

    # --- Suppla (Rionegro) días permitidos de traslado a fábrica (0=Lunes, ..., 6=Domingo) ---
    transfer_days_allowed: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])

    def cap_sofasa(self) -> List[float]:
        return _broadcast(self.cap_sofasa_per_day, self.horizon)

    def cap_traslado(self) -> List[float]:
        base_arr = _broadcast(self.cap_traslado_per_day, self.horizon)
        adjusted = []
        for t, val in enumerate(base_arr):
            day_of_week = t % 7
            if day_of_week in self.transfer_days_allowed:
                adjusted.append(val)
            else:
                adjusted.append(0.0)
        return adjusted

    def daily_consumption_arr(self) -> List[float]:
        return _broadcast(self.daily_consumption, self.horizon)

    def cap_suppla_weekly(self) -> List[float]:
        """Capacidad semanal de recepción en Suppla, una entrada por semana."""
        n_weeks = (self.horizon // 7) + 2
        return _broadcast(self.cap_suppla_per_week, n_weeks)


@dataclass
class PlanEntry:
    """Decisión para un contenedor: ruta y fechas."""

    container_id: str
    route: str  # "direct" (puerto->SOFASA) o "suppla" (puerto->Suppla->SOFASA)
    em_day: int  # día de entrada a planta (EM)
    suppla_in_day: Optional[int] = None  # día de recepción en Suppla (si route == "suppla")


Plan = dict  # container_id -> PlanEntry
