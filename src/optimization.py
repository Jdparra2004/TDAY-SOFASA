"""
optimization.py
----------------
Modelo de optimización (MILP / CP) para decidir, por cada contenedor:
  - la ruta: directo a SOFASA, o vía Suppla
  - el día exacto de entrada a planta (EM)
  - si aplica, el día de recepción en Suppla

Implementado con **OR-Tools CP-SAT** (Google), el motor estándar de la
industria para problemas de *scheduling* / asignación con restricciones de
capacidad -- exactamente la naturaleza de este problema. Se prefiere sobre
un MILP genérico (p.ej. PuLP+CBC) porque:
  - Maneja nativamente variables enteras/booleanas y restricciones
    condicionales (`OnlyEnforceIf`) sin necesitar trucos de "big-M".
  - Suele resolver instancias de scheduling de este tamaño mucho más rápido.
  - No requiere un solver externo: el solver CP-SAT viene incluido.

Ver MODELO_MATEMATICO.md sección 4-6 para la formulación matemática completa
que este código implementa.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ortools.sat.python import cp_model

from src.model import Container, Params, Plan, PlanEntry


@dataclass
class OptimizationResult:
    plan: Plan
    status: str
    objective_value: float
    solve_time_s: float
    kpis: Dict[str, float]


def optimize_plan(
    containers: List[Container],
    params: Params,
    time_limit_s: float = 30.0,
    verbose: bool = False,
) -> OptimizationResult:
    model = cp_model.CpModel()

    horizon = params.horizon
    cap_sofasa = params.cap_sofasa()
    cap_traslado = params.cap_traslado()
    cap_suppla_week = params.cap_suppla_weekly()

    # Ventana factible de días por contenedor dentro del horizonte
    windows = {}
    active_containers = []
    for c in containers:
        start = c.eta
        if start >= horizon or (start + params.l_min) >= horizon:
            continue
        end = min(horizon - 1, c.eta + params.max_wait_days)
        direct_start = start + params.l_min
        if end < direct_start:
            end = direct_start
        windows[c.id] = (start, min(horizon - 1, end))
        active_containers.append(c)

    if not active_containers and containers:
        # Fallback si ninguno cumple estrictamente, tomar los primeros con margen
        for c in containers:
            start = min(c.eta, horizon - 1)
            direct_start = min(start + params.l_min, horizon - 1)
            end = min(horizon - 1, start + params.max_wait_days)
            windows[c.id] = (start, max(start, end))
            active_containers.append(c)

    yd: Dict[tuple, cp_model.IntVar] = {}  # (c.id, t) -> entra directo a SOFASA el día t
    zs: Dict[tuple, cp_model.IntVar] = {}  # (c.id, t) -> recibido en Suppla el día t
    ys: Dict[tuple, cp_model.IntVar] = {}  # (c.id, t) -> transferido Suppla->SOFASA el día t
    use_suppla: Dict[str, cp_model.IntVar] = {}
    em_day: Dict[str, cp_model.IntVar] = {}
    suppla_in_day: Dict[str, cp_model.IntVar] = {}
    r_slack: Dict[str, cp_model.IntVar] = {}   # incumplimiento de need_by
    s_slack: Dict[str, cp_model.IntVar] = {}   # incumplimiento de l_max (demurrage)
    a_slack: Dict[str, cp_model.IntVar] = {}   # incumplimiento de l_obj (alerta preventiva)
    suppla_days: Dict[str, cp_model.IntVar] = {}

    for c in active_containers:
        start, end = windows[c.id]
        direct_start = max(start + params.l_min, start)

        yd_terms = []
        for t in range(direct_start, end + 1):
            v = model.NewBoolVar(f"yd_{c.id}_{t}")
            yd[(c.id, t)] = v
            yd_terms.append(v)

        zs_terms = []
        for t in range(start, end + 1):
            v = model.NewBoolVar(f"zs_{c.id}_{t}")
            zs[(c.id, t)] = v
            zs_terms.append(v)

        ys_terms = []
        for t in range(direct_start, end + 1):
            v = model.NewBoolVar(f"ys_{c.id}_{t}")
            ys[(c.id, t)] = v
            ys_terms.append(v)

        u = model.NewBoolVar(f"use_suppla_{c.id}")
        use_suppla[c.id] = u

        # (R1) exactamente una ruta de llegada a planta
        model.Add(sum(yd_terms) + sum(ys_terms) == 1)
        # el uso de Suppla queda determinado por si se usó la ruta ys
        model.Add(sum(ys_terms) == u)
        model.Add(sum(zs_terms) == u)

        em = model.NewIntVar(start, end, f"em_{c.id}")
        model.Add(em == sum(t * yd[(c.id, t)] for t in range(direct_start, end + 1))
                  + sum(t * ys[(c.id, t)] for t in range(direct_start, end + 1)))
        em_day[c.id] = em

        sin_ = model.NewIntVar(0, end, f"suppla_in_{c.id}")
        model.Add(sin_ == sum(t * zs[(c.id, t)] for t in range(start, end + 1)))
        suppla_in_day[c.id] = sin_

        # orden lógico: si se recibe en Suppla, la salida a planta es >= día de recepción
        model.Add(em >= sin_)

        # --- penalizaciones (slacks, min-forzado por el objetivo) ---
        r = model.NewIntVar(0, horizon, f"r_{c.id}")
        model.Add(r >= em - c.need_by)
        r_slack[c.id] = r

        s = model.NewIntVar(0, horizon, f"s_{c.id}")
        model.Add(s >= em - c.eta - params.l_max)
        s_slack[c.id] = s

        a = model.NewIntVar(0, horizon, f"a_{c.id}")
        model.Add(a >= em - c.eta - params.l_obj)
        a_slack[c.id] = a

        sd = model.NewIntVar(0, horizon, f"suppla_days_{c.id}")
        model.Add(sd == em - sin_).OnlyEnforceIf(u)
        model.Add(sd == 0).OnlyEnforceIf(u.Not())
        suppla_days[c.id] = sd

    # --- (R4) capacidad diaria de recepción en SOFASA (con slack blando) ---
    sofasa_slacks = {}
    for t in range(horizon):
        terms = []
        for c in active_containers:
            if (c.id, t) in yd:
                terms.append(yd[(c.id, t)])
            if (c.id, t) in ys:
                terms.append(ys[(c.id, t)])
        if terms:
            slack_t = model.NewIntVar(0, len(active_containers), f"sofasa_slack_{t}")
            model.Add(sum(terms) <= int(round(cap_sofasa[t])) + slack_t)
            sofasa_slacks[t] = slack_t

    # --- (R5) capacidad semanal de recepción en Suppla (con slack blando) ---
    suppla_slacks = {}
    n_weeks = len(cap_suppla_week)
    for w in range(n_weeks):
        t_start, t_end = w * 7, w * 7 + 6
        terms = []
        for c in active_containers:
            for t in range(t_start, t_end + 1):
                if (c.id, t) in zs:
                    terms.append(zs[(c.id, t)])
        if terms:
            slack_w = model.NewIntVar(0, len(active_containers), f"suppla_slack_{w}")
            model.Add(sum(terms) <= int(round(cap_suppla_week[w])) + slack_w)
            suppla_slacks[w] = slack_w

    # --- (R6) capacidad diaria de traslado Suppla -> SOFASA (con slack blando) ---
    traslado_slacks = {}
    for t in range(horizon):
        terms = [ys[(c.id, t)] for c in active_containers if (c.id, t) in ys]
        if terms:
            slack_tr = model.NewIntVar(0, len(active_containers), f"traslado_slack_{t}")
            model.Add(sum(terms) <= int(round(cap_traslado[t])) + slack_tr)
            traslado_slacks[t] = slack_tr

    # --- función objetivo ---
    objective_terms = []
    scale = 100
    for c in active_containers:
        objective_terms.append(int(round(params.cost_rupture * scale)) * r_slack[c.id])
        objective_terms.append(int(round(params.cost_demurrage_day * scale)) * s_slack[c.id])
        objective_terms.append(int(round(params.cost_alert_day * scale)) * a_slack[c.id])
        objective_terms.append(int(round(params.cost_suppla_day * scale)) * suppla_days[c.id])

    cost_capacity_violation = 50.0
    for slk in sofasa_slacks.values():
        objective_terms.append(int(round(cost_capacity_violation * scale)) * slk)
    for slk in suppla_slacks.values():
        objective_terms.append(int(round(cost_capacity_violation * scale)) * slk)
    for slk in traslado_slacks.values():
        objective_terms.append(int(round(cost_capacity_violation * scale)) * slk)

    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 8
    if verbose:
        solver.parameters.log_search_progress = True
    status = solver.Solve(model)

    status_name = solver.StatusName(status)
    plan: Plan = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for c in active_containers:
            em = solver.Value(em_day[c.id])
            if solver.Value(use_suppla[c.id]) == 1:
                plan[c.id] = PlanEntry(
                    container_id=c.id,
                    route="suppla",
                    em_day=em,
                    suppla_in_day=solver.Value(suppla_in_day[c.id]),
                )
            else:
                plan[c.id] = PlanEntry(container_id=c.id, route="direct", em_day=em)

    kpis = _compute_plan_kpis(active_containers, plan, params)

    return OptimizationResult(
        plan=plan,
        status=status_name,
        objective_value=solver.ObjectiveValue() / scale if plan else float("nan"),
        solve_time_s=solver.WallTime(),
        kpis=kpis,
    )


def _compute_plan_kpis(containers: List[Container], plan: Plan, params: Params) -> Dict[str, float]:
    if not plan:
        return {}
    n = len(containers)
    lead_times = []
    n_obj = n_alert = n_critical = 0
    n_rupture = 0
    suppla_days_total = 0
    n_suppla = 0
    for c in containers:
        entry = plan[c.id]
        lt = entry.em_day - c.eta
        lead_times.append(lt)
        if lt <= params.l_obj:
            n_obj += 1
        elif lt <= params.l_max:
            n_alert += 1
        else:
            n_critical += 1
        if entry.em_day > c.need_by:
            n_rupture += 1
        if entry.route == "suppla":
            n_suppla += 1
            suppla_days_total += entry.em_day - (entry.suppla_in_day or entry.em_day)
    return {
        "n_containers": n,
        "pct_dentro_objetivo": 100 * n_obj / n,
        "pct_alerta_preventiva": 100 * n_alert / n,
        "pct_alerta_critica": 100 * n_critical / n,
        "n_rupturas": n_rupture,
        "pct_via_suppla": 100 * n_suppla / n,
        "dias_contenedor_suppla": suppla_days_total,
        "lead_time_promedio": sum(lead_times) / n,
    }
