"""
simulation.py
--------------
Simulador de eventos discretos (**SimPy**) que reproduce día a día un plan (línea base u óptimo):

    puerto -> [directo a SOFASA] o [Suppla -> traslado -> SOFASA]

Siempre recibe un plan explícito (la línea base se genera con `baseline_plan`). No hay consumo ni inventario SOFASA:
solo se registra la ocupación de Suppla, las entradas diarias y los costos (demurrage y traslado, vía `compute_costs`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import pandas as pd
import simpy

from src.costs import CostResult, compute_costs
from src.model import Container, Params, Plan


@dataclass
class SimulationResult:
    daily_df: pd.DataFrame
    container_df: pd.DataFrame
    kpis: Dict[str, float]
    costs: CostResult


def run_simulation(containers: List[Container], params: Params, plan: Plan) -> SimulationResult:
    if plan is None:
        raise ValueError("run_simulation requiere un plan explícito (use baseline_plan para la línea base).")
    env = simpy.Environment()
    suppla_stock = simpy.Container(env, capacity=float("inf"), init=0)
    H = params.horizon_solver
    state = {c.id: {"suppla_in": None, "em": None} for c in containers}
    daily_log: List[dict] = []

    def controller(env):
        for t in range(H):
            em_hoy = rec_suppla = traslados = 0
            for cid, e in plan.items():
                if cid not in state:
                    continue
                if e.route == "suppla" and e.suppla_in_day == t:
                    suppla_stock.put(1)
                    state[cid]["suppla_in"] = t
                    rec_suppla += 1
                if e.em_day == t:
                    if e.route == "suppla":
                        suppla_stock.get(1)
                        traslados += 1
                    state[cid]["em"] = t
                    em_hoy += 1
            daily_log.append({"day": t, "ocupacion_suppla": suppla_stock.level, "em_sofasa": em_hoy,
                              "recepcion_suppla": rec_suppla, "traslados": traslados})
            yield env.timeout(1)

    env.process(controller(env))
    env.run(until=H)
    daily_df = pd.DataFrame(daily_log)

    costs = compute_costs(containers, plan, params)
    cdf = costs.df.set_index("id")
    rows = []
    for c in containers:
        st = state[c.id]
        em = st["em"]
        # Ruptura solo con fecha real; los no atendidos no cuentan como ruptura
        rupture_days = max(0, em - c.need_by) if (em is not None and c.need_by is not None) else 0
        k = cdf.loc[c.id]
        rows.append({
            "id": c.id, "eta": c.eta, "need_by": c.need_by, "part_family": c.part_family,
            "route": "suppla" if st["suppla_in"] is not None else "direct",
            "suppla_in": st["suppla_in"], "em": em,
            "lead_time": (em - c.eta) if em is not None else None,
            "rupture_days": rupture_days, "atendido": em is not None,
            "tiene_ruptura_real": c.need_by is not None,
            "estado": k["estado"], "salida_puerto": k["salida_puerto"], "dias_puerto": k["dias_puerto"],
            "dias_demurrage": k["dias_demurrage"], "usd_demurrage": k["usd_demurrage"],
            "usd_traslado": k["usd_traslado"], "demurrage_estimado": k["demurrage_estimado"],
        })
    container_df = pd.DataFrame(rows)
    return SimulationResult(daily_df, container_df, _compute_kpis(container_df, daily_df, params, costs), costs)


def _block(df: pd.DataFrame, params: Params) -> Dict[str, float]:
    lt = df["lead_time"].dropna()
    n = len(lt)
    real = df[df["tiene_ruptura_real"] & df["atendido"]]
    return {
        "n_containers": len(df),
        "pct_dentro_objetivo": 100 * (lt <= params.l_obj).sum() / n if n else 0.0,
        "pct_alerta_preventiva": 100 * ((lt > params.l_obj) & (lt <= params.l_max)).sum() / n if n else 0.0,
        "pct_alerta_critica": 100 * (lt > params.l_max).sum() / n if n else 0.0,
        "n_rupturas": int((real["rupture_days"] > 0).sum()),
        "lead_time_promedio": float(lt.mean()) if n else float("nan"),
    }


def _compute_kpis(container_df: pd.DataFrame, daily_df: pd.DataFrame, params: Params, costs: CostResult) -> Dict[str, float]:
    n = len(container_df)
    att = container_df[container_df["atendido"]]
    hor = _block(att[att["em"] < params.horizon], params)
    proj = _block(att[att["em"] >= params.horizon], params)
    gen = _block(att, params)
    lt = att["lead_time"].dropna()
    nl = len(lt)
    k: Dict[str, float] = {
        "n_containers": n,
        "n_atendidos": len(att),
        "n_diferidos": int((~container_df["atendido"]).sum()),
        "n_con_ruptura_real": int(container_df["tiene_ruptura_real"].sum()),
        "n_sin_ruptura": int((~container_df["tiene_ruptura_real"]).sum()),
    }
    for pref, b in (("hor_", hor), ("proj_", proj)):
        for key, v in b.items():
            k[pref + key] = v
    k.update({
        "pct_dentro_objetivo": gen["pct_dentro_objetivo"],
        "pct_alerta_preventiva": gen["pct_alerta_preventiva"],
        "pct_alerta_critica": gen["pct_alerta_critica"],
        "n_rupturas": gen["n_rupturas"],
        "pct_via_suppla": 100 * (container_df["route"] == "suppla").sum() / n if n else 0.0,
        "lead_time_promedio": gen["lead_time_promedio"],
        "ocupacion_suppla_promedio": float(daily_df["ocupacion_suppla"].mean()) if len(daily_df) else 0.0,
        "ocupacion_suppla_maxima": float(daily_df["ocupacion_suppla"].max()) if len(daily_df) else 0.0,
        "cumplimiento_lt_7": 100 * (lt <= params.l_min).sum() / nl if nl else 0.0,
        "cumplimiento_lt_10": 100 * (lt <= params.l_obj).sum() / nl if nl else 0.0,
        "cumplimiento_lt_12": 100 * (lt <= params.l_max).sum() / nl if nl else 0.0,
        "usd_demurrage": costs.totals["usd_demurrage"],
        "usd_traslado": costs.totals["usd_traslado"],
        "usd_total": costs.totals["usd_total"],
        "dias_demurrage": costs.totals["dias_demurrage"],
        "usd_demurrage_previo_dia0": costs.acumulado_previo_usd,
    })
    return k
