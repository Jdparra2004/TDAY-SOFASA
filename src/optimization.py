"""
optimization.py
----------------
Modelo de optimización (MILP / CP) para decidir, por cada contenedor:
  - la ruta: directo a SOFASA, o vía Suppla
  - el día exacto de entrada a planta (EM)
  - si aplica, el día de recepción en Suppla

Implementado con **OR-Tools CP-SAT** (Google), el motor estándar de la
industria para problemas de *scheduling* / asignación con restricciones de
capacidades duras -- exactamente la naturaleza de este problema.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List

from ortools.sat.python import cp_model

from src.model import Container, Params, Plan, PlanEntry


@dataclass
class OptimizationResult:
    plan: Plan
    status: str
    objective_value: float
    best_objective_bound: float
    gap: float
    solve_time_s: float
    kpis: Dict[str, float]
    out_of_horizon: List[str] = field(default_factory=list)  # ids que no caben en el horizonte
    deferred: List[str] = field(default_factory=list)


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

    # Ventana factible de días por contenedor. El día 0 es la fecha de planeación: un contenedor
    # con ETA negativa ya está en puerto, así que no se puede decidir nada antes del día 0, pero su
    # lead time y sus holguras SÍ se miden contra la ETA real (negativa).
    windows = {}
    active_containers = []
    out_of_horizon: List[str] = []
    for c in containers:
        start = max(0, c.eta)                          # primer día en que se puede actuar
        direct_start = max(0, c.eta + params.l_min)    # primer día en que puede entrar directo a planta
        if direct_start >= horizon:
            out_of_horizon.append(c.id)
            continue
        end = min(horizon - 1, max(start + params.max_wait_days, direct_start))
        windows[c.id] = (start, end, direct_start)
        active_containers.append(c)

    if not active_containers:
        return OptimizationResult(plan={}, status="NO_CONTAINERS_IN_HORIZON", objective_value=float("nan"),
                                  solve_time_s=0.0, kpis={}, out_of_horizon=out_of_horizon)

    yd: Dict[tuple, cp_model.IntVar] = {}  # (c.id, t) -> entra directo a SOFASA el día t
    zs: Dict[tuple, cp_model.IntVar] = {}  # (c.id, t) -> recibido en Suppla el día t
    ys: Dict[tuple, cp_model.IntVar] = {}  # (c.id, t) -> transferido Suppla->SOFASA el día t
    use_suppla: Dict[str, cp_model.IntVar] = {}
    pending: Dict[str, cp_model.IntVar] = {}   # 1 = se difiere fuera del horizonte
    em_day: Dict[str, cp_model.IntVar] = {}
    suppla_in_day: Dict[str, cp_model.IntVar] = {}
    r_slack: Dict[str, cp_model.IntVar] = {}   # incumplimiento de need_by
    o_slack: Dict[str, cp_model.IntVar] = {}   # incumplimiento de em_objetivo
    s_slack: Dict[str, cp_model.IntVar] = {}   # incumplimiento de l_max (demurrage)
    a_slack: Dict[str, cp_model.IntVar] = {}   # incumplimiento de l_obj (alerta preventiva)
    suppla_days: Dict[str, cp_model.IntVar] = {}
    late: Dict[str, cp_model.IntVar] = {}      # 1 = el contenedor termina en ruptura

    for c in active_containers:
        start, end, direct_start = windows[c.id]
        # cota superior de las holguras (la ETA/need_by pueden ser negativas)
        big = horizon + max(0, -c.eta) + max(0, -c.need_by) + 1

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
        pend = model.NewBoolVar(f"pend_{c.id}")
        pending[c.id] = pend

        # (R1) o entra por una ruta dentro del horizonte, o se difiere
        model.Add(sum(yd_terms) + sum(ys_terms) + pend == 1)
        model.Add(sum(ys_terms) == u)
        model.Add(sum(zs_terms) == u)

        # un contenedor diferido se penaliza como si entrara el día `horizon`
        em = model.NewIntVar(start, horizon, f"em_{c.id}")
        model.Add(em == sum(t * yd[(c.id, t)] for t in range(direct_start, end + 1))
                  + sum(t * ys[(c.id, t)] for t in range(direct_start, end + 1))
                  + horizon * pend)
        em_day[c.id] = em

        sin_ = model.NewIntVar(0, end, f"suppla_in_{c.id}")
        model.Add(sin_ == sum(t * zs[(c.id, t)] for t in range(start, end + 1)))
        suppla_in_day[c.id] = sin_

        # orden lógico: si se recibe en Suppla, la salida a planta es >= día de recepción + min_suppla_stay_days
        model.Add(em >= sin_ + params.min_suppla_stay_days).OnlyEnforceIf(u)
        model.Add(em >= sin_).OnlyEnforceIf(u.Not())

        # DEMURRAGE RULE: demurrage is port waiting time (ETA -> day leaving port).
        # port_exit_day = em if direct (u=0), or suppla_in_day if suppla (u=1)
        port_exit = model.NewIntVar(start, horizon, f"port_exit_{c.id}")
        model.Add(port_exit == em).OnlyEnforceIf(u.Not())
        model.Add(port_exit == sin_).OnlyEnforceIf(u)

        # --- penalizaciones (slacks, min-forzado por el objetivo) ---
        r = model.NewIntVar(0, big, f"r_{c.id}")
        model.Add(r >= em - c.need_by)
        r_slack[c.id] = r

        l = model.NewBoolVar(f"late_{c.id}")
        model.Add(r <= big * l)                # r > 0  =>  late = 1
        late[c.id] = l

        s = model.NewIntVar(0, big, f"s_{c.id}")
        model.Add(s >= port_exit - c.eta - params.l_max)
        s_slack[c.id] = s

        a = model.NewIntVar(0, big, f"a_{c.id}")
        model.Add(a >= em - c.eta - params.l_obj)
        a_slack[c.id] = a

        sd = model.NewIntVar(0, horizon, f"suppla_days_{c.id}")
        model.Add(sd == em - sin_).OnlyEnforceIf(u)
        model.Add(sd == 0).OnlyEnforceIf(u.Not())
        suppla_days[c.id] = sd

    # --- (R4) capacidad diaria de recepción en SOFASA (dura) ---
    for t in range(horizon):
        terms = []
        for c in active_containers:
            if (c.id, t) in yd:
                terms.append(yd[(c.id, t)])
            if (c.id, t) in ys:
                terms.append(ys[(c.id, t)])
        if terms:
            model.Add(sum(terms) <= int(round(cap_sofasa[t])))

    # --- (R5) capacidad semanal (calendario) de recepción en Suppla (dura) ---
    days_by_week: Dict[int, List[int]] = {}
    for t in range(horizon):
        days_by_week.setdefault(params.week_of(t), []).append(t)
    for w, days in days_by_week.items():
        terms = [zs[(c.id, t)] for c in active_containers for t in days if (c.id, t) in zs]
        if terms:
            model.Add(sum(terms) <= int(round(cap_suppla_week[w])))

    # --- (R6) capacidad diaria de traslado Suppla -> SOFASA (dura) ---
    for t in range(horizon):
        terms = [ys[(c.id, t)] for c in active_containers if (c.id, t) in ys]
        if terms:
            model.Add(sum(terms) <= int(round(cap_traslado[t])))

    # --- función objetivo (Orden de pesos según PDF: ruptura >> puerto-planta >> demurrage >> Suppla cost) ---
    objective_terms = []
    scale = 100
    for c in active_containers:
        objective_terms.append(int(round(params.cost_rupture * scale)) * r_slack[c.id])
        if params.cost_rupture_event > 0:
            objective_terms.append(int(round(params.cost_rupture_event * scale)) * late[c.id])
        objective_terms.append(int(round(params.cost_demurrage_day * scale)) * s_slack[c.id])
        objective_terms.append(int(round(params.cost_alert_day * scale)) * a_slack[c.id])
        objective_terms.append(int(round(params.cost_suppla_day * scale)) * suppla_days[c.id])
        if params.cost_suppla_move > 0:
            objective_terms.append(int(round(params.cost_suppla_move * scale)) * use_suppla[c.id])

    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 8
    if verbose:
        solver.parameters.log_search_progress = True
    status = solver.Solve(model)

    status_name = solver.StatusName(status)
    if status_name != "OPTIMAL":
        if verbose:
            print(f"Solver status {status_name}. Reintentando con time_limit_s=60...")
        solver.parameters.max_time_in_seconds = max(60.0, time_limit_s)
        status = solver.Solve(model)
        status_name = solver.StatusName(status)

    plan: Plan = {}
    deferred: List[str] = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for c in active_containers:
            if solver.Value(pending[c.id]) == 1:
                deferred.append(c.id)
                continue
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

    planned = [c for c in active_containers if c.id in plan]
    kpis = _compute_plan_kpis(planned, plan, params)
    obj_val = solver.ObjectiveValue() / scale if plan else float("nan")
    best_bound = solver.BestObjectiveBound() / scale if plan else float("nan")
    gap = abs(obj_val - best_bound) / (abs(obj_val) + 1e-9) if not math.isnan(obj_val) else 0.0

    return OptimizationResult(
        plan=plan,
        status=status_name,
        objective_value=obj_val,
        best_objective_bound=best_bound,
        gap=gap,
        solve_time_s=solver.WallTime(),
        kpis=kpis,
        out_of_horizon=out_of_horizon,
        deferred=deferred,
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


def baseline_plan(containers: List[Container], params: Params) -> Plan:
    cap_s = params.cap_sofasa()
    cap_t = params.cap_traslado()
    cap_w = params.cap_suppla_weekly()
    H = params.horizon
    used_s, used_t, used_w, plan = [0]*H, [0]*H, {}, {}
    key = lambda c: (c.em_objetivo if c.em_objetivo is not None else c.need_by, c.need_by)
    for c in sorted(containers, key=key):
        tgt = max(0, c.eta + params.l_min, c.em_objetivo if c.em_objetivo is not None else c.need_by)
        d = next((t for t in range(tgt, H) if used_s[t] < cap_s[t]), None)
        if d is not None and d - c.eta <= params.l_max:
            used_s[d] += 1
            plan[c.id] = PlanEntry(c.id, "direct", d)
            continue
        placed = False
        for s in range(max(0, c.eta), min(H, c.eta + params.l_max + 1)):
            w = params.week_of(s)
            if used_w.get(w, 0) >= cap_w[w]:
                continue
            e = next((t for t in range(s + params.min_suppla_stay_days, H) if used_t[t] < cap_t[t] and used_s[t] < cap_s[t]), None)
            if e is None:
                continue
            used_w[w] = used_w.get(w, 0) + 1
            used_t[e] += 1
            used_s[e] += 1
            plan[c.id] = PlanEntry(c.id, "suppla", e, s)
            placed = True
            break
        if not placed and d is not None:
            used_s[d] += 1
            plan[c.id] = PlanEntry(c.id, "direct", d)
    return plan
