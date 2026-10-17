"""
simulation.py
--------------
Simulador de eventos discretos (**SimPy**) del flujo:

    puerto -> [directo a SOFASA] o [Suppla -> traslado -> SOFASA] -> producción

SimPy es la librería estándar de Python para simulación de eventos discretos
(colas, inventarios, recursos con capacidad limitada) y es el motor natural
para "ver" cómo evoluciona el sistema en el tiempo -- que es exactamente lo
que pide el reto ("observar cómo el nivel de inventario va cambiando en el
tiempo en las bodegas, y en qué tiempos llegan a Sofasa").

Se usa `simpy.Container` para representar el inventario (nivel de stock) en
SOFASA y en Suppla, con eventos `put`/`get`, y un proceso controlador que
avanza día a día.

Dos modos de uso:

1. **Sin plan** (`plan=None`): aplica día a día la regla de negocio de la
   diapositiva 7 (heurística "as-is") -- si hay cupo hoy en SOFASA, entra
   directo; si no, va a Suppla y espera cupo de traslado -- priorizando por
   urgencia (`need_by`). Este es el escenario de referencia / línea base.
2. **Con plan**: recibe un `Plan` (por ejemplo la salida de
   `optimization.optimize_plan`) y reproduce esas decisiones exactamente,
   para poder comparar sus KPIs contra la línea base.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd
import simpy

from src.model import Container, Params, Plan


@dataclass
class SimulationResult:
    daily_df: pd.DataFrame
    container_df: pd.DataFrame
    kpis: Dict[str, float]


def run_simulation(
    containers: List[Container],
    params: Params,
    plan: Optional[Plan] = None,
) -> SimulationResult:
    env = simpy.Environment()
    sofasa_inv = simpy.Container(env, capacity=float("inf"), init=params.init_inv_sofasa)
    suppla_inv = simpy.Container(env, capacity=float("inf"), init=params.init_inv_suppla)

    cap_sofasa = params.cap_sofasa()
    cap_traslado = params.cap_traslado()
    cap_suppla_week = params.cap_suppla_weekly()
    consumption = params.daily_consumption_arr()

    state = {
        c.id: {"container": c, "suppla_in": None, "em": None} for c in containers
    }
    pending_port: List[str] = []  # esperando ruta (modo heurístico)
    suppla_wait: List[str] = []  # en Suppla esperando traslado (modo heurístico)

    daily_log = []

    def heuristic_step(t, sofasa_remaining, suppla_week_remaining, traslado_remaining):
        for c in containers:
            if c.eta == t:
                pending_port.append(c.id)

        # priorizar por urgencia: contenedores con need_by más próxima primero
        pending_port.sort(key=lambda cid: state[cid]["container"].need_by)
        still_pending = []
        for cid in pending_port:
            c = state[cid]["container"]
            can_direct_now = (t - c.eta) >= params.l_min
            if can_direct_now and sofasa_remaining > 0:
                state[cid]["em"] = t
                sofasa_remaining -= 1
                sofasa_inv.put(1)
            elif suppla_week_remaining > 0:
                state[cid]["suppla_in"] = t
                suppla_week_remaining -= 1
                suppla_inv.put(1)
                suppla_wait.append(cid)
            else:
                still_pending.append(cid)  # congestión: se queda esperando cupo
        pending_port[:] = still_pending

        suppla_wait.sort(key=lambda cid: state[cid]["container"].need_by)
        still_waiting = []
        for cid in suppla_wait:
            if traslado_remaining > 0 and sofasa_remaining > 0:
                state[cid]["em"] = t
                traslado_remaining -= 1
                sofasa_remaining -= 1
                suppla_inv.get(1)
                sofasa_inv.put(1)
            else:
                still_waiting.append(cid)
        suppla_wait[:] = still_waiting
        return sofasa_remaining, suppla_week_remaining, traslado_remaining

    def plan_step(t):
        for cid, entry in plan.items():
            if entry.route == "suppla" and entry.suppla_in_day == t:
                suppla_inv.put(1)
                state[cid]["suppla_in"] = t
            if entry.em_day == t:
                if entry.route == "suppla":
                    suppla_inv.get(1)
                sofasa_inv.put(1)
                state[cid]["em"] = t

    def controller(env):
        suppla_week_remaining = 0
        for t in range(params.horizon):
            sofasa_remaining = cap_sofasa[t]
            traslado_remaining = cap_traslado[t]
            if t % 7 == 0:
                suppla_week_remaining = cap_suppla_week[t // 7]

            if plan is None:
                sofasa_remaining, suppla_week_remaining, traslado_remaining = heuristic_step(
                    t, sofasa_remaining, suppla_week_remaining, traslado_remaining
                )
            else:
                plan_step(t)

            demand = consumption[t]
            available = sofasa_inv.level
            actual_consumption = min(demand, available)
            if actual_consumption > 0:
                sofasa_inv.get(actual_consumption)
            stockout = max(0, demand - available)

            daily_log.append(
                {
                    "day": t,
                    "inv_sofasa": sofasa_inv.level,
                    "inv_suppla": suppla_inv.level,
                    "consumo": actual_consumption,
                    "faltante_produccion": stockout,
                    "en_espera_puerto": len(pending_port) if plan is None else 0,
                    "en_espera_traslado_suppla": len(suppla_wait) if plan is None else 0,
                }
            )
            yield env.timeout(1)

    env.process(controller(env))
    env.run(until=params.horizon)

    daily_df = pd.DataFrame(daily_log)

    rows = []
    for c in containers:
        st = state[c.id]
        em = st["em"]
        if em is not None:
            rupture_days = max(0, em - c.need_by)
        else:
            # Nunca llegó a planta dentro del horizonte simulado: se trata como
            # ruptura total (peor caso que llegar tarde) para no subestimar el
            # efecto de dejar contenedores "colgados" en la cola de puerto/Suppla.
            rupture_days = max(0, params.horizon - c.need_by)
        rows.append(
            {
                "id": c.id,
                "eta": c.eta,
                "need_by": c.need_by,
                "part_family": c.part_family,
                "route": "suppla" if st["suppla_in"] is not None else "direct",
                "suppla_in": st["suppla_in"],
                "em": em,
                "lead_time": (em - c.eta) if em is not None else None,
                "rupture_days": rupture_days,
                "atendido": em is not None,
            }
        )
    container_df = pd.DataFrame(rows)

    kpis = _compute_kpis(container_df, daily_df, params)
    return SimulationResult(daily_df=daily_df, container_df=container_df, kpis=kpis)


def _compute_kpis(container_df: pd.DataFrame, daily_df: pd.DataFrame, params: Params) -> Dict[str, float]:
    n = len(container_df)
    atendidos = int(container_df["atendido"].sum())
    lt = container_df["lead_time"].dropna()
    n_lt = max(1, len(lt))
    return {
        "n_containers": n,
        "n_no_atendidos_en_horizonte": n - atendidos,
        "pct_dentro_objetivo": 100 * (lt <= params.l_obj).sum() / n_lt,
        "pct_alerta_preventiva": 100 * ((lt > params.l_obj) & (lt <= params.l_max)).sum() / n_lt,
        "pct_alerta_critica": 100 * (lt > params.l_max).sum() / n_lt,
        "n_rupturas": int((container_df["rupture_days"] > 0).sum()),
        "pct_via_suppla": 100 * (container_df["route"] == "suppla").sum() / n,
        "lead_time_promedio": float(lt.mean()) if len(lt) else float("nan"),
        "dias_totales_faltante_produccion": float(daily_df["faltante_produccion"].sum()),
        "inventario_suppla_promedio": float(daily_df["inv_suppla"].mean()),
        "inventario_sofasa_promedio": float(daily_df["inv_sofasa"].mean()),
        "max_cola_puerto": int(daily_df["en_espera_puerto"].max()) if "en_espera_puerto" in daily_df else 0,
    }
