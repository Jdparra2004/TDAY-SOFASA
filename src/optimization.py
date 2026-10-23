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

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ortools.sat.python import cp_model

from src.costs import weighted_objective
from src.model import Container, EstadoContenedor, Params, Plan, PlanEntry

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    plan: Plan
    status: str
    solver_status_raw: str
    objective_value: float
    best_objective_bound: float
    gap: float
    solve_time_s: float
    kpis: Dict[str, float]
    deferred: List[str] = field(default_factory=list)


def optimize_plan(
    containers: List[Container],
    params: Params,
    time_limit_s: Optional[float] = None,
    verbose: bool = False,
    workers: int = 8,
    seed: int = 0,
) -> OptimizationResult:
    model = cp_model.CpModel()

    horizon = params.horizon
    H = params.horizon_solver
    cap_sofasa = params.cap_sofasa()
    cap_traslado = params.cap_traslado()
    cap_suppla_week = params.cap_suppla_weekly()

    # Generar baseline_plan primero para garantizar que la ventana contenga siempre la solución base
    bplan = baseline_plan(containers, params)

    windows = {}
    active_containers = []
    for c in containers:
        start = max(0, c.eta)
        direct_start = max(0, c.eta + params.l_min)
        entry = bplan.get(c.id)
        baseline_em = entry.em_day if entry is not None else direct_start
        baseline_sup = entry.suppla_in_day if (entry is not None and entry.suppla_in_day is not None) else baseline_em
        # B1: La ventana debe contener siempre la solución de la línea base
        end = min(H - 1, max(start + params.max_wait_days, direct_start, baseline_em, baseline_sup))
        windows[c.id] = (start, end, direct_start)
        active_containers.append(c)

    if not active_containers:
        return OptimizationResult(
            plan={}, status="SIN_SOLUCION", solver_status_raw="NO_CONTAINERS_IN_HORIZON",
            objective_value=float("nan"), best_objective_bound=float("nan"), gap=0.0,
            solve_time_s=0.0, kpis={}, deferred=[]
        )

    yd_vars: Dict[str, Dict[int, cp_model.IntVar]] = {}
    zs_vars: Dict[str, Dict[int, cp_model.IntVar]] = {}
    ys_vars: Dict[str, Dict[int, cp_model.IntVar]] = {}
    use_suppla: Dict[str, cp_model.IntVar] = {}
    pending: Dict[str, cp_model.IntVar] = {}
    em_day: Dict[str, cp_model.IntVar] = {}
    suppla_in_day: Dict[str, cp_model.IntVar] = {}
    r_slack: Dict[str, cp_model.IntVar] = {}
    o_slack: Dict[str, cp_model.IntVar] = {}
    s_slack: Dict[str, cp_model.IntVar] = {}
    a_slack: Dict[str, cp_model.IntVar] = {}
    suppla_days: Dict[str, cp_model.IntVar] = {}
    late: Dict[str, cp_model.IntVar] = {}

    for c in active_containers:
        start, end, direct_start = windows[c.id]
        has_rup = c.need_by is not None  # ruptura real; sin fecha real no hay restricción ni penalidad de ruptura
        big = H + max(0, -c.eta) + (max(0, -c.need_by) if has_rup else 0) + 1

        yd_terms = []
        yd_dict = {}
        for t in range(direct_start, end + 1):
            v = model.NewBoolVar(f"yd_{c.id}_{t}")
            yd_dict[t] = v
            yd_terms.append(v)
        yd_vars[c.id] = yd_dict

        zs_terms = []
        zs_dict = {}
        for t in range(start, end + 1):
            v = model.NewBoolVar(f"zs_{c.id}_{t}")
            zs_dict[t] = v
            zs_terms.append(v)
        zs_vars[c.id] = zs_dict

        ys_terms = []
        ys_dict = {}
        for t in range(direct_start, end + 1):
            v = model.NewBoolVar(f"ys_{c.id}_{t}")
            ys_dict[t] = v
            ys_terms.append(v)
        ys_vars[c.id] = ys_dict

        u = model.NewBoolVar(f"use_suppla_{c.id}")
        use_suppla[c.id] = u
        pend = model.NewBoolVar(f"pend_{c.id}")
        pending[c.id] = pend

        model.Add(sum(yd_terms) + sum(ys_terms) + pend == 1)
        model.Add(sum(ys_terms) == u)
        model.Add(sum(zs_terms) == u)

        em = model.NewIntVar(start, H, f"em_{c.id}")
        model.Add(em == sum(t * yd_dict[t] for t in range(direct_start, end + 1) if t in yd_dict)
                  + sum(t * ys_dict[t] for t in range(direct_start, end + 1) if t in ys_dict)
                  + H * pend)
        em_day[c.id] = em

        sin_ = model.NewIntVar(0, end, f"suppla_in_{c.id}")
        model.Add(sin_ == sum(t * zs_dict[t] for t in range(start, end + 1) if t in zs_dict))
        suppla_in_day[c.id] = sin_

        model.Add(em >= sin_ + params.min_suppla_stay_days).OnlyEnforceIf(u)
        model.Add(em >= sin_).OnlyEnforceIf(u.Not())

        port_exit = model.NewIntVar(start, H, f"port_exit_{c.id}")
        model.Add(port_exit == em).OnlyEnforceIf(u.Not())
        model.Add(port_exit == sin_).OnlyEnforceIf(u)

        # need_by slack (solo si need_by_estimado es False)
        r = model.NewIntVar(0, big, f"r_{c.id}")
        if has_rup:
            model.Add(r >= em - c.need_by)
        else:
            model.Add(r == 0)
        r_slack[c.id] = r

        l = model.NewBoolVar(f"late_{c.id}")
        model.Add(r <= big * l)
        late[c.id] = l

        # em_objetivo slack
        o = model.NewIntVar(0, big, f"o_{c.id}")
        if has_rup and c.em_objetivo is not None:  # EM objetivo penaliza solo con ruptura real
            model.Add(o >= em - c.em_objetivo)
        else:
            model.Add(o == 0)
        o_slack[c.id] = o

        s = model.NewIntVar(0, big, f"s_{c.id}")
        model.Add(s >= port_exit - c.eta - params.l_max)
        s_slack[c.id] = s

        a = model.NewIntVar(0, big, f"a_{c.id}")
        model.Add(a >= em - c.eta - params.l_obj)
        a_slack[c.id] = a

        sd = model.NewIntVar(0, H, f"suppla_days_{c.id}")
        model.Add(sd == em - sin_).OnlyEnforceIf(u)
        model.Add(sd == 0).OnlyEnforceIf(u.Not())
        suppla_days[c.id] = sd

    # Capacidades duras sobre horizon_solver (H)
    for t in range(H):
        terms = []
        for c in active_containers:
            yd_dict = yd_vars.get(c.id, {})
            ys_dict = ys_vars.get(c.id, {})
            if t in yd_dict:
                terms.append(yd_dict[t])
            if t in ys_dict:
                terms.append(ys_dict[t])
        if terms:
            model.Add(sum(terms) <= int(round(cap_sofasa[t])))

    days_by_week: Dict[int, List[int]] = {}
    for t in range(H):
        days_by_week.setdefault(params.week_of(t), []).append(t)
    for w, days in days_by_week.items():
        terms = [zs_vars[c.id][t] for c in active_containers for t in days if c.id in zs_vars and t in zs_vars[c.id]]
        if terms:
            model.Add(sum(terms) <= int(round(cap_suppla_week[w])))

    for t in range(H):
        terms = [ys_vars[c.id][t] for c in active_containers if c.id in ys_vars and t in ys_vars[c.id]]
        if terms:
            model.Add(sum(terms) <= int(round(cap_traslado[t])))

    # Función objetivo
    objective_terms = []
    scale = 100
    for c in active_containers:
        has_rup = c.need_by is not None
        if has_rup and params.cost_rupture > 0:
            objective_terms.append(int(round(params.cost_rupture * scale)) * r_slack[c.id])
        if has_rup and params.cost_em_objetivo_dia > 0 and c.em_objetivo is not None:
            objective_terms.append(int(round(params.cost_em_objetivo_dia * scale)) * o_slack[c.id])
        if has_rup and params.cost_rupture_event > 0:
            objective_terms.append(int(round(params.cost_rupture_event * scale)) * late[c.id])
        if params.USD_DEMURRAGE_DIA > 0:
            objective_terms.append(int(round(params.USD_DEMURRAGE_DIA * scale)) * s_slack[c.id])
        if params.cost_alert_day > 0:
            objective_terms.append(int(round(params.cost_alert_day * scale)) * a_slack[c.id])
        if params.USD_SUPPLA_DIA > 0:
            objective_terms.append(int(round(params.USD_SUPPLA_DIA * scale)) * suppla_days[c.id])

    model.Minimize(sum(objective_terms))

    # B3: Solución inicial (hint) eficiente indexada por contenedor (sin bucles anidados)
    try:
        for c in active_containers:
            e = bplan.get(c.id)
            yd_dict = yd_vars.get(c.id, {})
            ys_dict = ys_vars.get(c.id, {})
            zs_dict = zs_vars.get(c.id, {})
            if e is None:
                model.AddHint(pending[c.id], 1)
                model.AddHint(use_suppla[c.id], 0)
            else:
                model.AddHint(pending[c.id], 0)
                model.AddHint(use_suppla[c.id], int(e.route == "suppla"))
                if e.route == "direct":
                    if e.em_day in yd_dict:
                        model.AddHint(yd_dict[e.em_day], 1)
                elif e.route == "suppla":
                    if e.em_day in ys_dict:
                        model.AddHint(ys_dict[e.em_day], 1)
                    if e.suppla_in_day is not None and e.suppla_in_day in zs_dict:
                        model.AddHint(zs_dict[e.suppla_in_day], 1)
    except Exception as exc:  # el hint es opcional
        logger.warning("No se pudo construir el hint de la línea base: %s", exc)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s if time_limit_s is not None else params.solver_time_limit_s
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = seed
    if verbose:
        solver.parameters.log_search_progress = True
    status = solver.Solve(model)

    raw_status_name = solver.StatusName(status)
    
    # B4: status solo en {"OPTIMAL","FEASIBLE","FALLBACK_LINEA_BASE","SIN_SOLUCION"}
    if status == cp_model.OPTIMAL:
        status_str = "OPTIMAL"
    elif status == cp_model.FEASIBLE:
        status_str = "FEASIBLE"
    else:
        status_str = "SIN_SOLUCION"

    plan: Plan = {}
    deferred: List[str] = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for c in active_containers:
            if solver.Value(pending[c.id]) == 1:
                deferred.append(c.id)
                continue
            em = solver.Value(em_day[c.id])
            if em >= H:
                deferred.append(c.id)
                continue

            if solver.Value(use_suppla[c.id]) == 1:
                plan[c.id] = PlanEntry(
                    container_id=c.id,
                    route="suppla",
                    em_day=em,
                    suppla_in_day=solver.Value(suppla_in_day[c.id]),
                )
            else:
                plan[c.id] = PlanEntry(container_id=c.id, route="direct", em_day=em)
    else:
        plan = {}
        deferred = [c.id for c in active_containers]

    # B4: Garantía: el plan reportado nunca es peor que la línea base según el mismo objetivo ponderado
    wo_base = weighted_objective(active_containers, bplan, params)
    wo_opt = weighted_objective(active_containers, plan, params) if plan else float("inf")

    if not plan or wo_opt > wo_base + 1e-6:
        status_str = "FALLBACK_LINEA_BASE"
        plan = dict(bplan)
        deferred = [c.id for c in active_containers if c.id not in plan]
        wo_opt = wo_base
        print(f"AVISO: Se aplica FALLBACK_LINEA_BASE (objetivo solver = {wo_opt:.1f} vs base = {wo_base:.1f}).")

    planned = [c for c in active_containers if c.id in plan]
    kpis = _compute_plan_kpis(planned, plan, params)

    # B4: objective_value y gap calculados sobre el plan DEVUELTO (weighted_objective)
    obj_val = wo_opt
    best_bound = solver.BestObjectiveBound() / scale if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else obj_val
    gap = abs(obj_val - best_bound) / (abs(obj_val) + 1e-9) if not math.isnan(obj_val) else 0.0

    return OptimizationResult(
        plan=plan,
        status=status_str,
        solver_status_raw=raw_status_name,
        objective_value=obj_val,
        best_objective_bound=best_bound,
        gap=gap,
        solve_time_s=solver.WallTime(),
        kpis=kpis,
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
        if c.id not in plan:
            continue
        entry = plan[c.id]
        lt = entry.em_day - c.eta
        lead_times.append(lt)
        if lt <= params.l_obj:
            n_obj += 1
        elif lt <= params.l_max:
            n_alert += 1
        else:
            n_critical += 1
        if c.need_by is not None and entry.em_day > c.need_by:
            n_rupture += 1
        if entry.route == "suppla":
            n_suppla += 1
            suppla_days_total += entry.em_day - (entry.suppla_in_day or entry.em_day)
    if not lead_times:
        return {"n_containers": 0}
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
    H = params.horizon_solver
    used_s, used_t, used_w, plan = [0]*H, [0]*H, {}, {}
    key = lambda c: (c.em_objetivo if c.em_objetivo is not None else c.eta + params.l_obj, c.eta)
    for c in sorted(containers, key=key):
        tgt = max(0, c.eta + params.l_min, c.em_objetivo if c.em_objetivo is not None else c.eta + params.l_obj)
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
            e = next((t for t in range(max(s + params.min_suppla_stay_days, c.eta + params.l_min), H) if used_t[t] < cap_t[t] and used_s[t] < cap_s[t]), None)
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
        elif not placed:
            pass
    return plan
