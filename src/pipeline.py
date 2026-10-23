"""
pipeline.py
-----------
Núcleo compartido por el modo lote, el modo manual (app.py) y main.py. TODA la lógica vive aquí;
app.py y main.py solo llaman estas funciones.

El usuario solo controla 6 parámetros (build_params): fecha de planeación, horizonte, capacidad SOFASA/día,
capacidad Suppla/semana, capacidad de traslado/día y días habilitados de traslado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import pandas as pd

from src.costs import CostResult, compute_costs
from src.data_processor import classify_universe, finalize_universe, process_real_tracking_data
from src.model import Container, Params, Plan
from src.optimization import OptimizationResult, baseline_plan, optimize_plan
from src.simulation import SimulationResult, run_simulation

Validacion = Tuple[str, str, str]  # (nombre, "OK"/"FALLA", valor encontrado)


def build_params(fecha_base, horizonte: int, cap_sofasa: float, cap_suppla_semana: float,
                 cap_traslado: float, dias_traslado: Sequence[int]) -> Params:
    """Los ÚNICOS 6 parámetros del usuario. Todo lo demás son constantes internas de Params."""
    f = pd.Timestamp(fecha_base).normalize()
    return Params(
        horizon=int(horizonte), cap_sofasa_per_day=cap_sofasa, cap_suppla_per_week=cap_suppla_semana,
        cap_traslado_per_day=cap_traslado, transfer_days_allowed=[int(d) for d in dias_traslado],
        planning_date=f.date(), start_weekday=f.weekday(),
    )


def _base_dt(params: Params) -> pd.Timestamp:
    if params.planning_date is None:
        raise ValueError("Params sin fecha de planeación: use build_params().")
    return pd.Timestamp(params.planning_date).normalize()


def prepare_universe(fuente: Union[str, Dict[str, Any], Sequence[Dict[str, Any]]], params: Params
                     ) -> Tuple[List[Container], pd.DataFrame]:
    """Devuelve (programables, df_universo) con la misma clasificación para archivos y para ingreso manual.
    - Archivos: str (carpeta/archivo) o dict {"tracking":..., "diel":..., "prio":...}.
    - Manual: lista de dicts {id, eta (fecha), ruptura (fecha u opcional), vessel, family}.
    """
    base = _base_dt(params)
    if isinstance(fuente, str):
        return process_real_tracking_data(fuente, base_date=base, params=params)
    if isinstance(fuente, dict):
        return process_real_tracking_data(fuente.get("tracking"), fuente.get("diel"), fuente.get("prio"),
                                          base_date=base, params=params)
    rows = []
    for m in fuente:
        eta = pd.Timestamp(m["eta"]).normalize()
        rup = m.get("ruptura")
        rows.append({
            "id": str(m["id"]), "eta": eta, "eta_dia": int((eta - base).days),
            "ruptura": pd.Timestamp(rup).normalize() if rup is not None and not pd.isna(rup) else pd.NaT,
            "vessel": m.get("vessel") or "N/D", "family": m.get("family") or "N/D",
            "sourcing": pd.NA, "etd": pd.NaT, "em": pd.NaT, "fecha_em_prog": pd.NaT,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return [], df
    df["ruptura_estimada"] = df["ruptura"].isna()
    df = classify_universe(df, params, base)
    return finalize_universe(df, set(df["id"]), base)


@dataclass
class Resultado:
    params: Params
    base_date: pd.Timestamp
    containers: List[Container]
    df_universo: pd.DataFrame
    embudo: Dict[str, int]
    base_plan: Plan
    plan: Plan                      # plan óptimo
    base: SimulationResult
    optimo: SimulationResult
    solver: OptimizationResult
    costos_base: CostResult
    costos_opt: CostResult
    estados: pd.DataFrame           # id, estado_base, estado_optimo
    uso_capacidad: Dict[str, Dict[str, float]] = field(default_factory=dict)
    validaciones: List[Validacion] = field(default_factory=list)

    @property
    def ahorro_usd(self) -> float:
        return self.costos_base.totals["usd_total"] - self.costos_opt.totals["usd_total"]


def capacity_usage(plan: Plan, params: Params) -> Dict[str, float]:
    """Uso máximo vs capacidad (SOFASA/día, Suppla/semana calendario, traslados/día)."""
    H = params.horizon_solver
    s = [0] * H
    t_ = [0] * H
    w: Dict[int, int] = {}
    for e in plan.values():
        if e.em_day < H:
            s[e.em_day] += 1
        if e.route == "suppla":
            if e.em_day < H:
                t_[e.em_day] += 1
            if e.suppla_in_day is not None:
                w[params.week_of(e.suppla_in_day)] = w.get(params.week_of(e.suppla_in_day), 0) + 1
    cs, ct, cw = params.cap_sofasa(), params.cap_traslado(), params.cap_suppla_weekly()
    return {
        "sofasa_max": max(s) if s else 0, "sofasa_cap": max(cs),
        "suppla_semana_max": max(w.values()) if w else 0, "suppla_semana_cap": max(cw),
        "traslado_max": max(t_) if t_ else 0, "traslado_cap": max(ct),
        "exceso": int(sum(max(0, s[t] - cs[t]) for t in range(H)) + sum(max(0, t_[t] - ct[t]) for t in range(H))
                      + sum(max(0, n - cw[k]) for k, n in w.items())),
    }


def run_pipeline(programables: List[Container], params: Params, df_universo: pd.DataFrame,
                 time_limit_s: Optional[float] = None, workers: int = 8, seed: int = 0, verbose: bool = False) -> Resultado:
    base_date = _base_dt(params)
    bplan = baseline_plan(programables, params)
    base = run_simulation(programables, params, bplan)
    opt = optimize_plan(programables, params, time_limit_s=time_limit_s, verbose=verbose, workers=workers, seed=seed)
    oplan = opt.plan
    optimo = run_simulation(programables, params, oplan)
    cb = compute_costs(programables, bplan, params)
    co = compute_costs(programables, oplan, params)
    estados = pd.DataFrame({"id": [c.id for c in programables]})
    eb, eo = cb.df.set_index("id")["estado"], co.df.set_index("id")["estado"]
    estados["estado_base"] = estados["id"].map(eb)
    estados["estado_optimo"] = estados["id"].map(eo)
    from src.model import EstadoContenedor
    for c in programables:
        c.estado = EstadoContenedor(eo[c.id])
    res = Resultado(params, base_date, programables, df_universo, dict(df_universo.attrs.get("embudo", {})),
                    bplan, oplan, base, optimo, opt, cb, co, estados,
                    {"base": capacity_usage(bplan, params), "optimo": capacity_usage(oplan, params)})
    res.validaciones = compute_validations(res, params, df_universo)
    return res


def _ok(cond: bool) -> str:
    return "OK" if cond else "FALLA"


def compute_validations(res: Resultado, params: Params, df_universo: pd.DataFrame) -> List[Validacion]:
    v: List[Validacion] = []
    tr = df_universo.attrs.get("tracking_ids", set(df_universo["id"]))
    v.append(("IDs del universo ⊂ Tracking", _ok(set(df_universo["id"]).issubset(tr)), f"{len(df_universo)} IDs"))
    e = res.embudo
    suma = e.get("excluidos", 0) + e.get("fuera_ventana", 0) + e.get("programables", 0)
    v.append(("Embudo: excluidos + fuera de ventana + programables = Tracking",
              _ok(suma == e.get("tracking_total", -1)), f"{suma} vs {e.get('tracking_total')}"))
    prog = df_universo[df_universo["estado_universo"] == "PROGRAMABLE"]
    emax = int(prog["eta_dia"].max()) if len(prog) else 0
    v.append(("ETA de programables dentro de la ventana", _ok(emax <= params.horizon - 1),
              f"ETA máx día {emax} (límite {params.horizon - 1})"))
    for nombre, uso in res.uso_capacidad.items():
        v.append((f"Capacidades respetadas ({nombre})", _ok(uso["exceso"] == 0),
                  f"SOFASA {uso['sofasa_max']}/{uso['sofasa_cap']:.0f} · Suppla/sem {uso['suppla_semana_max']}/"
                  f"{uso['suppla_semana_cap']:.0f} · traslado {uso['traslado_max']}/{uso['traslado_cap']:.0f}"))
    for nombre, plan in (("base", res.base_plan), ("optimo", res.plan)):
        eta = {c.id: c.eta for c in res.containers}
        mn = min((e_.em_day - eta[cid] for cid, e_ in plan.items()), default=params.l_min)
        v.append((f"EM − ETA ≥ l_min ({nombre})", _ok(mn >= params.l_min), f"mínimo {mn} (l_min={params.l_min})"))
    nb, no = len(res.base.container_df), len(res.optimo.container_df)
    v.append(("Mismo n de contenedores en base y óptimo", _ok(nb == no == len(res.containers)), f"{nb} vs {no}"))
    for nombre, sim in (("base", res.base), ("optimo", res.optimo)):
        cdf = sim.container_df
        bad = int(((cdf["rupture_days"] > 0) & (~cdf["tiene_ruptura_real"])).sum())
        v.append((f"Rupturas solo sobre ruptura real ({nombre})", _ok(bad == 0), f"{bad} rupturas sin fecha real"))
        
        # Recalcular demurrage y suppla independientemente desde container_df sin usar usd_* del DF
        dem_recalc = ((cdf["salida_puerto"] - cdf["eta"] - params.l_max).clip(lower=0) * params.USD_DEMURRAGE_DIA).sum()
        suppla_recalc = 0.0
        for _, r in cdf.iterrows():
            if r["route"] == "suppla" and pd.notna(r["suppla_in"]) and pd.notna(r["em"]):
                dias_s = max(0, int(r["em"]) - int(r["suppla_in"]))
                suppla_recalc += dias_s * params.USD_SUPPLA_DIA
        
        rep = sim.costs.totals["usd_total"]
        v.append((f"Costo recalculado = costo reportado ({nombre})", _ok(abs(dem_recalc + suppla_recalc - rep) < 1e-6),
                  f"{dem_recalc + suppla_recalc:,.0f} vs {rep:,.0f} USD"))

    for nombre, costs in (("base", res.costos_base), ("optimo", res.costos_opt)):
        dias_sup_total = costs.totals["dias_suppla"]
        n_suppla = costs.totals["n_via_suppla"]
        min_esperado = n_suppla * params.min_suppla_stay_days
        v.append((f"Dias Suppla >= n_via_suppla * min_suppla_stay_days ({nombre})", _ok(dias_sup_total >= min_esperado),
                  f"dias {dias_sup_total} >= {min_esperado} (n={n_suppla})"))

    estados_ok = res.estados[["estado_base", "estado_optimo"]].notna().all().all()
    v.append(("Todo programable tiene estado", _ok(bool(estados_ok)), f"{len(res.estados)} contenedores"))
    base_c, opt_c = res.costos_base.totals["usd_total"], res.costos_opt.totals["usd_total"]
    v.append(("Ahorro = costo base − costo óptimo", _ok(abs(res.ahorro_usd - (base_c - opt_c)) < 1e-6),
              f"{res.ahorro_usd:,.0f} USD"))
    return v


def print_validaciones(res: Resultado) -> None:
    n_ok = sum(1 for _, est, _ in res.validaciones if est == "OK")
    n_falla = sum(1 for _, est, _ in res.validaciones if est == "FALLA")
    for nombre, estado, valor in res.validaciones:
        print(f"  [{estado}] {nombre}: {valor}")
    print(f"Validaciones: {n_ok} OK / {n_falla} FALLA")
