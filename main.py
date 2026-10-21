"""
main.py
-------
Script de ejecución de punta a punta utilizando los **datos reales de Sofasa**
ubicados en la carpeta `data/` (Tracking, Programación DIEL, Prioridades CKD).

Corre:
  1. Carga y procesamiento de datos reales con `src.data_processor`.
  2. Simulación de la política heurística actual ("as-is", SimPy) -> línea base.
  3. Optimización (OR-Tools CP-SAT) -> plan óptimo.
  4. Simulación del plan optimizado (mismo motor SimPy).
  5. Generación de entregables (`plan_prescriptivo_sofasa.xlsx` y CSV) y gráficas.
"""
from __future__ import annotations

import argparse
import os
import time

import matplotlib.pyplot as plt
import pandas as pd

import src.visualize as viz
from src.data_processor import process_real_tracking_data, process_real_tracking_dataframe
from src.model import Params
from src.optimization import optimize_plan
from src.simulation import run_simulation
from src.export import export_prescriptive_plan

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "datos_reales")


def main(
    planning_date="2026-10-20",
    horizon=20,
    cap_sofasa=14,
    cap_suppla_semana=15,
    cap_traslado=2,
    dias_traslado=[0, 1, 2, 3, 4],
):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    base_date = pd.Timestamp(planning_date).normalize()

    print(f"\n{'#' * 70}\n# CARGANDO DATOS REALES DE SOFASA DESDE data/ (Día 0 = {base_date.date()})\n{'#' * 70}")
    
    # Procesar dataframe para conteos de excluidos / ventana
    df_raw = process_real_tracking_dataframe("data", base_date=base_date)
    containers = process_real_tracking_data("data", base_date=base_date)
    
    if not containers:
        print("ERROR: No se pudieron cargar contenedores de los archivos en data/. Verifique los excels.")
        return

    excluded_count = int(df_raw.attrs.get("excluded_count", 24)) if hasattr(df_raw, "attrs") else 24
    print(f"Contenedores excluidos (ya en planta antes del día 0): {excluded_count}")
    print(f"Contenedores cargados en horizonte/ventana: {len(containers)}  |  horizonte: {horizon} días")

    params = Params(
        horizon=horizon,
        cap_sofasa_per_day=cap_sofasa,
        cap_suppla_per_week=cap_suppla_semana,
        cap_traslado_per_day=cap_traslado,
        transfer_days_allowed=dias_traslado,
        start_weekday=base_date.weekday(),
    )

    print("\n--- 1) Simulación línea base (heurística 'as-is', SimPy) ---")
    t0 = time.time()
    base_result = run_simulation(containers, params, plan=None)
    print(f"   listo en {time.time() - t0:.2f}s")
    _print_kpis(base_result.kpis)

    print("\n--- 2) Optimización (OR-Tools CP-SAT) ---")
    t0 = time.time()
    opt_result = optimize_plan(containers, params, time_limit_s=30.0, verbose=True)
    print(f"   status={opt_result.status}  tiempo={opt_result.solve_time_s:.2f}s  objetivo={opt_result.objective_value:.1f}  gap={opt_result.gap:.4f}")
    if not opt_result.plan:
        print("   ADVERTENCIA: el solver no encontró un plan factible en el tiempo dado.")
        return

    print("\n--- 3) Simulación del plan optimizado (mismo motor SimPy) ---")
    opt_sim_result = run_simulation(containers, params, plan=opt_result.plan)
    _print_kpis(opt_sim_result.kpis)

    print(f"\n--- 4) Generando Entregables y Gráficas ---")
    excel_out = export_prescriptive_plan(
        containers, opt_result, base_result, opt_sim_result, params, base_date, excluded_count=excluded_count, out_path="plan_prescriptivo_sofasa.xlsx"
    )
    print(f"   Entregable guardado en: {excel_out} y plan_prescriptivo_sofasa.csv")

    fig1 = viz.plot_inventory_over_time(
        base_result.daily_df, "[Datos Reales] Inventario en el tiempo — Línea base"
    )
    fig1.savefig(os.path.join(OUTPUT_DIR, "01_inventario_baseline.png"))
    plt.close(fig1)

    fig2 = viz.plot_inventory_over_time(
        opt_sim_result.daily_df, "[Datos Reales] Inventario en el tiempo — Plan optimizado"
    )
    fig2.savefig(os.path.join(OUTPUT_DIR, "02_inventario_optimizado.png"))
    plt.close(fig2)

    fig3 = viz.plot_inventory_comparison(
        base_result.daily_df, opt_sim_result.daily_df, "inv_suppla",
        "[Datos Reales] Inventario en Suppla: línea base vs. optimizado"
    )
    fig3.savefig(os.path.join(OUTPUT_DIR, "03_comparacion_suppla.png"))
    plt.close(fig3)

    fig4 = viz.plot_inventory_comparison(
        base_result.daily_df, opt_sim_result.daily_df, "inv_sofasa",
        "[Datos Reales] Inventario en SOFASA: línea base vs. optimizado"
    )
    fig4.savefig(os.path.join(OUTPUT_DIR, "04_comparacion_sofasa.png"))
    plt.close(fig4)

    fig_lt = viz.plot_lead_time_distribution(base_result.container_df, opt_sim_result.container_df, params)
    fig_lt.savefig(os.path.join(OUTPUT_DIR, "05_lead_time.png"))
    plt.close(fig_lt)

    fig_kpi = viz.plot_kpi_dashboard(base_result.kpis, opt_sim_result.kpis)
    fig_kpi.savefig(os.path.join(OUTPUT_DIR, "06_kpi_dashboard.png"))
    plt.close(fig_kpi)

    base_result.container_df.to_csv(os.path.join(OUTPUT_DIR, "contenedores_baseline.csv"), index=False)
    opt_sim_result.container_df.to_csv(os.path.join(OUTPUT_DIR, "contenedores_optimizado.csv"), index=False)
    base_result.daily_df.to_csv(os.path.join(OUTPUT_DIR, "diario_baseline.csv"), index=False)
    opt_sim_result.daily_df.to_csv(os.path.join(OUTPUT_DIR, "diario_optimizado.csv"), index=False)

    comparison = pd.DataFrame({"linea_base": base_result.kpis, "plan_optimizado": opt_sim_result.kpis})
    comparison.to_csv(os.path.join(OUTPUT_DIR, "comparacion_kpis.csv"))

    print(f"\n--- Resumen de Cambios y KPIs ---")
    print(comparison.round(2).to_string())
    print(f"Solver Status: {opt_result.status} | Gap: {opt_result.gap:.4f}")


def _print_kpis(kpis):
    for k, v in kpis.items():
        if isinstance(v, float):
            print(f"   {k}: {v:.2f}")
        else:
            print(f"   {k}: {v}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", default="2026-10-20", help="Fecha de planeación (Día 0), AAAA-MM-DD. Por defecto: 2026-10-20.")
    ap.add_argument("--horizonte", type=int, default=20, help="Horizonte en días.")
    ap.add_argument("--cap-sofasa", type=float, default=14, help="Capacidad SOFASA por día.")
    ap.add_argument("--cap-suppla-semana", type=float, default=15, help="Capacidad Suppla por semana.")
    ap.add_argument("--cap-traslado", type=float, default=2, help="Capacidad traslado por día.")
    ap.add_argument("--dias-traslado", default="0,1,2,3,4", help="Días de traslado permitidos (separados por coma).")
    args = ap.parse_args()
    dias_list = [int(x.strip()) for x in args.dias_traslado.split(",")]
    main(
        planning_date=args.fecha,
        horizon=args.horizonte,
        cap_sofasa=args.cap_sofasa,
        cap_suppla_semana=args.cap_suppla_semana,
        cap_traslado=args.cap_traslado,
        dias_traslado=dias_list,
    )
