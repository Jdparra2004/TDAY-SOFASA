"""
costs.py
--------
UNA sola función de costo (`compute_costs`) usada por la línea base y por el plan optimizado.

Por contenedor:
  salida_puerto  = día de EM (si va directo)  |  día de recepción en Suppla (si va vía Suppla)
  dias_puerto    = salida_puerto - ETA        (la ETA puede ser anterior al día 0)
  dias_demurrage = max(0, dias_puerto - l_max)
  usd_demurrage  = dias_demurrage * USD_DEMURRAGE_DIA
  usd_traslado   = USD_TRASLADO_SUPPLA si va vía Suppla
Contenedores diferidos (sin cupo en horizon_solver): demurrage ESTIMADO hasta el cierre de horizon_solver.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import pandas as pd

from src.model import Container, EstadoContenedor, Params, Plan

ESTADO_HORIZONTE = EstadoContenedor.PROGRAMADO_EN_HORIZONTE.value
ESTADO_PROYECTADA = EstadoContenedor.EM_PROYECTADA.value
ESTADO_DIFERIDO = EstadoContenedor.DIFERIDO_SIN_CUPO.value


@dataclass
class CostResult:
    df: pd.DataFrame
    totals: Dict[str, float]            # totales generales
    by_block: Dict[str, Dict[str, float]]  # "horizonte" | "proyectada" | "diferido"
    acumulado_previo_dias: int          # días de demurrage ya acumulados antes del día 0 (inevitables)
    acumulado_previo_usd: float


def _state_of(em_day, params: Params) -> str:
    if em_day is None or em_day >= params.horizon_solver:
        return ESTADO_DIFERIDO
    return ESTADO_HORIZONTE if em_day < params.horizon else ESTADO_PROYECTADA


def compute_costs(containers: List[Container], plan: Plan, params: Params) -> CostResult:
    H = params.horizon_solver
    rows = []
    for c in containers:
        e = plan.get(c.id)
        if e is None:
            em, route, salida, est = None, "sin plan", H, True
        else:
            em, route = e.em_day, e.route
            salida = e.suppla_in_day if (route == "suppla" and e.suppla_in_day is not None) else em
            est = False
        estado = _state_of(em, params)
        if estado == ESTADO_DIFERIDO:
            est = True
        dias_puerto = salida - c.eta
        dias_dem = max(0, dias_puerto - params.l_max)
        # días de demurrage que caen antes del día 0: días (eta+l_max+1 ... salida) con índice < 0
        previo = max(0, min(salida, 0) - (c.eta + params.l_max)) if dias_dem > 0 else 0
        rows.append({
            "id": c.id, "estado": estado, "route": route, "em": em, "salida_puerto": salida,
            "dias_puerto": dias_puerto, "dias_demurrage": dias_dem,
            "usd_demurrage": dias_dem * params.USD_DEMURRAGE_DIA,
            "usd_traslado": params.USD_TRASLADO_SUPPLA if route == "suppla" else 0.0,
            "demurrage_estimado": est, "dias_demurrage_previo_dia0": previo,
        })
    df = pd.DataFrame(rows, columns=["id", "estado", "route", "em", "salida_puerto", "dias_puerto", "dias_demurrage",
                                     "usd_demurrage", "usd_traslado", "demurrage_estimado", "dias_demurrage_previo_dia0"])

    def agg(d: pd.DataFrame) -> Dict[str, float]:
        return {
            "n": int(len(d)), "dias_demurrage": int(d["dias_demurrage"].sum()),
            "usd_demurrage": float(d["usd_demurrage"].sum()),
            "n_traslados": int((d["route"] == "suppla").sum()), "usd_traslado": float(d["usd_traslado"].sum()),
            "usd_total": float(d["usd_demurrage"].sum() + d["usd_traslado"].sum()),
        }

    by_block = {"horizonte": agg(df[df["estado"] == ESTADO_HORIZONTE]),
                "proyectada": agg(df[df["estado"] == ESTADO_PROYECTADA]),
                "diferido": agg(df[df["estado"] == ESTADO_DIFERIDO])}
    prev_dias = int(df["dias_demurrage_previo_dia0"].sum())
    return CostResult(df=df, totals=agg(df), by_block=by_block, acumulado_previo_dias=prev_dias,
                      acumulado_previo_usd=prev_dias * params.USD_DEMURRAGE_DIA)


def weighted_objective(containers: List[Container], plan: Plan, params: Params) -> float:
    """Objetivo ponderado del solver (mismos pesos y términos que optimize_plan) evaluado sobre un plan.
    Sirve para verificar que el plan reportado como óptimo nunca es peor que la línea base."""
    H = params.horizon_solver
    tot = 0.0
    for c in containers:
        e = plan.get(c.id)
        em = e.em_day if e is not None else H
        salida = e.suppla_in_day if (e is not None and e.route == "suppla") else em
        if c.need_by is not None:  # solo ruptura real
            r = max(0, em - c.need_by)
            tot += params.cost_rupture * r + params.cost_rupture_event * (1 if r > 0 else 0)
            if c.em_objetivo is not None:
                tot += params.cost_em_objetivo_dia * max(0, em - c.em_objetivo)
        tot += params.USD_DEMURRAGE_DIA * max(0, salida - c.eta - params.l_max)
        tot += params.cost_alert_day * max(0, em - c.eta - params.l_obj)
        if e is not None and e.route == "suppla":
            tot += params.cost_suppla_day * (em - (e.suppla_in_day if e.suppla_in_day is not None else em))
            tot += params.USD_TRASLADO_SUPPLA
    return tot
