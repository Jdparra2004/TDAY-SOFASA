"""
export.py
---------
Generación de reportes y entregables en Excel (plan_prescriptivo_sofasa.xlsx) y CSV
con todas las hojas requeridas por el estándar Transformation Day 2026.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from src.model import Container, Params, Plan
from src.optimization import OptimizationResult
from src.simulation import SimulationResult


def export_prescriptive_plan(
    containers: List[Container],
    opt_result: OptimizationResult,
    base_result: SimulationResult,
    opt_sim_result: SimulationResult,
    params: Params,
    base_date: pd.Timestamp,
    excluded_count: int = 24,
    df_raw: Optional[pd.DataFrame] = None,
    out_path: str = "plan_prescriptivo_sofasa.xlsx",
) -> str:
    plan = opt_result.plan
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) if os.path.dirname(os.path.abspath(out_path)) else ".", exist_ok=True)

    horizon = params.horizon

    # 1. Programación semanal
    prog_rows = []
    nd_count = 0
    for c in containers:
        entry = plan.get(c.id)
        if not entry and c.id in opt_result.out_of_horizon:
            route = "Fuera de ventana"
            em_day = None
            suppla_in = None
            alert = "Llega a puerto en el horizonte, no alcanza a entrar"
            comment = "Fuera de horizonte"
        elif not entry and c.id in opt_result.deferred:
            route = "Diferido"
            em_day = None
            suppla_in = None
            alert = "Reprogramar próxima semana"
            comment = "Sin cupo en horizonte"
        elif entry:
            route = entry.route
            em_day = entry.em_day
            suppla_in = entry.suppla_in_day
            port_exit = suppla_in if (route == "suppla" and suppla_in is not None) else em_day
            dias_puerto = port_exit - c.eta
            lead_time = em_day - c.eta

            alerts_list = []
            if lead_time < params.l_min:
                alerts_list.append("Riesgo de incumplimiento operativo: programación por debajo del tiempo mínimo estándar puerto-planta.")
            if lead_time > params.l_obj:
                alerts_list.append("Programación por encima del estándar objetivo puerto-planta.")
            if dias_puerto > params.l_max:
                alerts_list.append("Riesgo de demurrage: programación supera el tiempo máximo permitido en puerto.")
            alert = " | ".join(alerts_list) if alerts_list else "OK"
            comment = "Programado"
        else:
            route = "No asignado"
            em_day = None
            suppla_in = None
            alert = "N/A"
            comment = "No asignado"

        em_date = (base_date + pd.Timedelta(days=em_day)).strftime("%Y-%m-%d") if em_day is not None else "N/A"
        eta_date = (base_date + pd.Timedelta(days=c.eta)).strftime("%Y-%m-%d") if pd.notna(c.eta) else "N/A"
        etd_date = (base_date + pd.Timedelta(days=c.etd)).strftime("%Y-%m-%d") if getattr(c, "etd", None) is not None and pd.notna(c.etd) else "N/D"
        if etd_date == "N/D":
            nd_count += 1
        ruptura_date = (base_date + pd.Timedelta(days=c.need_by)).strftime("%Y-%m-%d") if pd.notna(c.need_by) else "N/A"
        em_previa_val = (base_date + pd.Timedelta(days=c.em_previa)).strftime("%Y-%m-%d") if getattr(c, "em_previa", None) is not None and pd.notna(c.em_previa) else "N/D"
        if em_previa_val == "N/D":
            nd_count += 1
        orig = getattr(c, "origen", "N/D")
        if not orig or orig == "GEN":
            orig = "N/D"
        if orig == "N/D":
            nd_count += 1

        cambio_val = "Sí" if (getattr(c, "em_previa", None) is not None and pd.notna(c.em_previa) and em_day is not None and c.em_previa != em_day) else "No" if (getattr(c, "em_previa", None) is not None and pd.notna(c.em_previa)) else "N/D"
        if cambio_val == "N/D":
            nd_count += 1

        semana_cal = params.week_of(em_day) if em_day is not None else 999

        prog_rows.append({
            "Semana": semana_cal,
            "Ruptura": ruptura_date,
            "Contenedor": c.id,
            "Buque": c.vessel,
            "EM Plan": em_date,
            "Origen": orig,
            "ETD": etd_date,
            "ETA": eta_date,
            "Ruta": route,
            "Recepción Suppla": (base_date + pd.Timedelta(days=suppla_in)).strftime("%Y-%m-%d") if suppla_in is not None else "N/A",
            "EM previa": em_previa_val,
            "Cambió": cambio_val,
            "Lead Time": (em_day - c.eta) if em_day is not None else "N/A",
            "Días en puerto": (suppla_in - c.eta) if (route == "suppla" and suppla_in is not None) else ((em_day - c.eta) if em_day is not None else "N/A"),
            "Alertas": alert,
            "Comentarios": comment,
            "_em_day": em_day if em_day is not None else 9999,
        })

    df_prog = pd.DataFrame(prog_rows).sort_values(by=["Semana", "_em_day"]).drop(columns=["_em_day"])

    # 2. Capacidad SOFASA
    sofasa_cap = params.cap_sofasa()
    sofasa_days = range(horizon)
    sofasa_usage = [0] * horizon
    for entry in plan.values():
        if entry.em_day < horizon:
            sofasa_usage[entry.em_day] += 1

    sofasa_rows = []
    for t in sofasa_days:
        cap = sofasa_cap[t]
        used = sofasa_usage[t]
        pct = (used / cap * 100) if cap > 0 else 0.0
        sofasa_rows.append({
            "Día": t,
            "Fecha": (base_date + pd.Timedelta(days=t)).strftime("%Y-%m-%d"),
            "Usado": used,
            "Capacidad": cap,
            "% Utilización": round(pct, 1),
        })
    df_sofasa = pd.DataFrame(sofasa_rows)

    # 3. Capacidad Suppla
    n_weeks = (horizon // 7) + 1
    suppla_cap_weekly = params.cap_suppla_weekly()
    suppla_weekly_counts = {}
    for entry in plan.values():
        if entry.route == "suppla" and entry.suppla_in_day is not None:
            w = params.week_of(entry.suppla_in_day)
            suppla_weekly_counts[w] = suppla_weekly_counts.get(w, 0) + 1

    suppla_weekly_rows = []
    for w in range(n_weeks):
        received = suppla_weekly_counts.get(w, 0)
        cap = suppla_cap_weekly[w] if w < len(suppla_cap_weekly) else params.cap_suppla_per_week
        pct = (received / cap * 100) if cap > 0 else 0.0
        suppla_weekly_rows.append({
            "Semana Calendario": w,
            "Contenedores Recibidos": received,
            "Capacidad Semanal": cap,
            "% Utilización Semanal": round(pct, 1),
        })
    df_suppla_weekly = pd.DataFrame(suppla_weekly_rows)

    # 4. Traslados Suppla-SOFASA
    traslado_cap = params.cap_traslado()
    traslado_usage = [0] * horizon
    for entry in plan.values():
        if entry.route == "suppla" and entry.em_day < horizon:
            traslado_usage[entry.em_day] += 1

    traslado_rows = []
    for t in range(horizon):
        cap = traslado_cap[t]
        used = traslado_usage[t]
        traslado_rows.append({
            "Día": t,
            "Fecha": (base_date + pd.Timedelta(days=t)).strftime("%Y-%m-%d"),
            "Traslados Programados": used,
            "Capacidad Traslado": cap,
            "% Utilización": round((used / cap * 100) if cap > 0 else 0.0, 1),
        })
    df_traslado = pd.DataFrame(traslado_rows)

    # 5. Riesgo Demurrage
    demurrage_rows = []
    for c in containers:
        entry = plan.get(c.id)
        if entry:
            port_exit = entry.suppla_in_day if (entry.route == "suppla" and entry.suppla_in_day is not None) else entry.em_day
            dias_p = port_exit - c.eta
            if dias_p >= params.l_min:
                demurrage_rows.append({
                    "Contenedor": c.id,
                    "ETA": (base_date + pd.Timedelta(days=c.eta)).strftime("%Y-%m-%d"),
                    "Salida Puerto": (base_date + pd.Timedelta(days=port_exit)).strftime("%Y-%m-%d"),
                    "Días en Puerto": dias_p,
                    "Estado Demurrage": "Riesgo de demurrage: programación supera el tiempo máximo permitido en puerto." if dias_p > params.l_max else "Alerta preventiva",
                })
    df_demurrage = pd.DataFrame(demurrage_rows)

    # 6. Riesgo Ruptura (Sin 999, con Estado y Días de retraso mínimo estimado)
    rupture_rows = []
    for c in containers:
        entry = plan.get(c.id)
        em_obj = getattr(c, "em_objetivo", None)
        if em_obj is None:
            em_obj = c.need_by
        if entry:
            retraso = entry.em_day - em_obj
            rupture_rows.append({
                "Contenedor": c.id,
                "Ruptura Original": (base_date + pd.Timedelta(days=c.need_by)).strftime("%Y-%m-%d"),
                "EM Objetivo": (base_date + pd.Timedelta(days=em_obj)).strftime("%Y-%m-%d"),
                "EM Plan": (base_date + pd.Timedelta(days=entry.em_day)).strftime("%Y-%m-%d"),
                "Días de Retraso vs Objetivo": max(0, retraso),
                "Días de Retraso vs Ruptura": max(0, entry.em_day - c.need_by),
                "Estado": "Programado con retraso" if retraso > 0 else "A tiempo",
                "Días de retraso mínimo estimado": "",
            })
        elif c.id in opt_result.deferred or c.id in opt_result.out_of_horizon:
            estado_str = "Diferido: sin cupo en horizonte" if c.id in opt_result.deferred else "Fuera de ventana (ETA > 3 semanas)"
            dias_retraso_min = max(0, (horizon) - em_obj)
            rupture_rows.append({
                "Contenedor": c.id,
                "Ruptura Original": (base_date + pd.Timedelta(days=c.need_by)).strftime("%Y-%m-%d"),
                "EM Objetivo": (base_date + pd.Timedelta(days=em_obj)).strftime("%Y-%m-%d"),
                "EM Plan": "",
                "Días de Retraso vs Objetivo": "",
                "Días de Retraso vs Ruptura": "",
                "Estado": estado_str,
                "Días de retraso mínimo estimado": dias_retraso_min,
            })
    df_rupture = pd.DataFrame(rupture_rows)

    # 7. Fuera de ventana (ETA > 3 semanas)
    out_window_rows = []
    if df_raw is not None and "fuera_ventana_etd" in df_raw.attrs:
        pass
    for cid in opt_result.out_of_horizon:
        c = next((x for x in containers if x.id == cid), None)
        if c:
            out_window_rows.append({
                "Contenedor": c.id,
                "ETA": (base_date + pd.Timedelta(days=c.eta)).strftime("%Y-%m-%d"),
                "Ruptura": (base_date + pd.Timedelta(days=c.need_by)).strftime("%Y-%m-%d"),
                "Buque": c.vessel,
                "Motivo": "Fuera de ventana (ETA > 3 semanas)",
            })
    df_out_window = pd.DataFrame(out_window_rows)

    # 8. Llega a puerto en el horizonte, no alcanza a entrar / diferidos
    deferred_rows = []
    for cid in opt_result.deferred:
        c = next((x for x in containers if x.id == cid), None)
        if c:
            deferred_rows.append({
                "Contenedor": c.id,
                "ETA": (base_date + pd.Timedelta(days=c.eta)).strftime("%Y-%m-%d"),
                "Ruptura": (base_date + pd.Timedelta(days=c.need_by)).strftime("%Y-%m-%d"),
                "Buque": c.vessel,
                "Motivo": "Diferido: sin cupo en horizonte",
            })
    df_deferred = pd.DataFrame(deferred_rows)

    # 9. No están en Tracking
    no_tracking_rows = []
    if df_raw is not None and hasattr(df_raw, "attrs") and "no_tracking_df" in df_raw.attrs:
        nt_df = df_raw.attrs["no_tracking_df"]
        if not nt_df.empty:
            for r in nt_df.itertuples(index=False):
                no_tracking_rows.append({"Contenedor": getattr(r, "id", "N/D"), "Fuente": getattr(r, "fuente", "N/D")})
    df_no_tracking = pd.DataFrame(no_tracking_rows)

    # 10. Excluidos (ya en planta)
    excluded_rows = []
    if df_raw is not None and hasattr(df_raw, "attrs") and "excluded_in_plant_df" in df_raw.attrs:
        ex_df = df_raw.attrs["excluded_in_plant_df"]
        if not ex_df.empty:
            for r in ex_df.itertuples(index=False):
                excluded_rows.append({"Contenedor": getattr(r, "id", "N/D"), "EM Previa": getattr(r, "em_diel", getattr(r, "fecha_em_prog", "N/D"))})
    df_excluded = pd.DataFrame(excluded_rows)

    # 11. KPIs (con capacidad requerida vs disponible)
    kpi_keys = list(base_result.kpis.keys())
    kpi_base_vals = list(base_result.kpis.values())
    kpi_opt_vals = [opt_sim_result.kpis.get(k, 0) for k in kpi_keys]

    df_kpis = pd.DataFrame({
        "KPI": kpi_keys,
        "Línea Base": kpi_base_vals,
        "Plan Optimizado": kpi_opt_vals,
    })

    # Capacidad requerida vs disponible
    reception_biz_days = sum(1 for t in range(horizon) if params.weekday_of(t) in params.sofasa_days_allowed)
    total_sofasa_slots = 14 * reception_biz_days
    programmable_count = len(containers)
    gap_slots = total_sofasa_slots - programmable_count
    scheduled_count = len([e for e in plan.values() if e.em_day < horizon])
    scheduled_gt12 = sum(1 for e in plan.values() if e.em_day < horizon and (e.em_day - next(c.eta for c in containers if c.id == e.container_id)) > 12)
    pct_gt12 = (scheduled_gt12 / scheduled_count * 100) if scheduled_count > 0 else 0.0

    df_kpis.loc[len(df_kpis)] = ["Capacidad requerida (contenedores programables)", programmable_count, programmable_count]
    df_kpis.loc[len(df_kpis)] = ["Capacidad SOFASA disponible horizonte (14 x dias habiles)", total_sofasa_slots, total_sofasa_slots]
    df_kpis.loc[len(df_kpis)] = ["Brecha capacidad SOFASA", gap_slots, gap_slots]
    df_kpis.loc[len(df_kpis)] = ["% programados con mas de 12 dias en puerto", pct_gt12, pct_gt12]
    df_kpis.loc[len(df_kpis)] = ["solver_status", "N/A", opt_result.status]
    df_kpis.loc[len(df_kpis)] = ["solver_gap", "N/A", opt_result.gap]
    df_kpis.loc[len(df_kpis)] = ["best_objective_bound", "N/A", opt_result.best_objective_bound]

    # 12. Parámetros y validaciones
    df_params = pd.DataFrame([
        {"Parámetro": "Horizonte (días)", "Valor": horizon},
        {"Parámetro": "Capacidad SOFASA / día", "Valor": str(params.cap_sofasa_per_day)},
        {"Parámetro": "Capacidad Suppla / semana", "Valor": str(params.cap_suppla_per_week)},
        {"Parámetro": "Capacidad Traslado / día", "Valor": str(params.cap_traslado_per_day)},
        {"Parámetro": "Lead Time Mínimo (l_min)", "Valor": params.l_min},
        {"Parámetro": "Lead Time Objetivo (l_obj)", "Valor": params.l_obj},
        {"Parámetro": "Lead Time Máximo / Demurrage (l_max)", "Valor": params.l_max},
        {"Parámetro": "Contenedores Excluidos (ya en planta)", "Valor": excluded_count},
        {"Parámetro": "Conteo de campos N/D", "Valor": nd_count},
        {"Parámetro": "Status Solver", "Valor": opt_result.status},
        {"Parámetro": "Gap Solver", "Valor": opt_result.gap},
        {"Parámetro": "Best Bound Solver", "Valor": opt_result.best_objective_bound},
    ])

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df_prog.to_excel(writer, sheet_name="Programacion semanal", index=False)
        df_sofasa.to_excel(writer, sheet_name="Capacidad SOFASA", index=False)
        df_suppla_weekly.to_excel(writer, sheet_name="Capacidad Suppla", index=False)
        df_traslado.to_excel(writer, sheet_name="Traslados Suppla-SOFASA", index=False)
        df_demurrage.to_excel(writer, sheet_name="Riesgo Demurrage", index=False)
        df_rupture.to_excel(writer, sheet_name="Riesgo Ruptura", index=False)
        df_out_window.to_excel(writer, sheet_name="Fuera de ventana (ETA > 3 sem)", index=False)
        df_deferred.to_excel(writer, sheet_name="Diferidos y fuera de ventana", index=False)
        df_no_tracking.to_excel(writer, sheet_name="No están en Tracking", index=False)
        df_excluded.to_excel(writer, sheet_name="Excluidos (ya en planta)", index=False)
        df_kpis.to_excel(writer, sheet_name="KPIs", index=False)
        df_params.to_excel(writer, sheet_name="Parametros y validaciones", index=False)

    csv_path = out_path.replace(".xlsx", ".csv")
    df_prog.to_csv(csv_path, index=False)

    return out_path
