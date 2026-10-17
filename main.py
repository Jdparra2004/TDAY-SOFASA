"""
main.py
-------
Script de ejecución de punta a punta utilizando los **datos reales de Sofasa**
ubicados en la carpeta `data/` (Tracking, Programación DIEL, Prioridades CKD).

Corre:
  1. Carga y procesamiento de datos reales con `src.data_processor`.
  2. Simulación de la política heurística actual ("as-is", SimPy) -> línea base.
  3. Optimización (OR-Tools CP-SAT) -> plan óptimo.
  4. Simulación del plan óptimo (SimPy).
  5. Generación de gráficas y tablas de KPIs en `output/datos_reales/`.
"""
from __future__ import annotations

import os
import time

import matplotlib.pyplot as plt
import pandas as pd

import src.visualize as viz
from src.data_processor import process_real_tracking_data
from src.model import Params
from src.optimization import optimize_plan
from src.simulation import run_simulation

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "datos_reales")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"\n{'#' * 70}\n# CARGANDO DATOS REALES DE SOFASA DESDE data/\n{'#' * 70}")
    containers = process_real_tracking_data("data")
    
    if not containers:
        print("ERROR: No se pudieron cargar contenedores de los archivos en data/. Verifique los excels.")
        return

    params = Params(horizon=90)
    print(f"Contenedores cargados: {len(containers)}  |  horizonte: {params.horizon} días")

    print("\n--- 1) Simulación línea base (heurística 'as-is', SimPy) ---")
    t0 = time.time()
    base_result = run_simulation(containers, params, plan=None)
    print(f"   listo en {time.time() - t0:.2f}s")
    _print_kpis(base_result.kpis)

    print("\n--- 2) Optimización (OR-Tools CP-SAT) ---")
    t0 = time.time()
    opt_result = optimize_plan(containers, params, time_limit_s=45.0, verbose=True)
    print(f"   status={opt_result.status}  tiempo={opt_result.solve_time_s:.2f}s  objetivo={opt_result.objective_value:.1f}")
    if not opt_result.plan:
        print("   ADVERTENCIA: el solver no encontró un plan factible en el tiempo dado.")
        return

    print("\n--- 3) Simulación del plan optimizado (mismo motor SimPy) ---")
    opt_sim_result = run_simulation(containers, params, plan=opt_result.plan)
    _print_kpis(opt_sim_result.kpis)

    print(f"\n--- 4) Gráficas y tablas -> {OUTPUT_DIR} ---")
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

    # Diagrama de flujo (Sankey) lado a lado: linea base vs. plan optimizado.
    # Exportado como imagen estatica (via kaleido) para usar en los documentos LaTeX.
    # Requiere Chrome instalado (kaleido lo usa para renderizar); si falla, revisar
    # que "plotly_get_chrome" se haya corrido una vez en esta maquina.
    try:
        fig_sankey = viz.plot_sankey_comparison(base_result, opt_sim_result)
        fig_sankey.write_image(
            os.path.join(OUTPUT_DIR, "07_sankey_comparacion.png"), width=1600, height=700, scale=2
        )
    except Exception as e:  # noqa: BLE001
        print(f"   ADVERTENCIA: no se pudo exportar el diagrama Sankey a imagen ({e}).")

    base_result.container_df.to_csv(os.path.join(OUTPUT_DIR, "contenedores_baseline.csv"), index=False)
    opt_sim_result.container_df.to_csv(os.path.join(OUTPUT_DIR, "contenedores_optimizado.csv"), index=False)
    base_result.daily_df.to_csv(os.path.join(OUTPUT_DIR, "diario_baseline.csv"), index=False)
    opt_sim_result.daily_df.to_csv(os.path.join(OUTPUT_DIR, "diario_optimizado.csv"), index=False)

    comparison = pd.DataFrame({"linea_base": base_result.kpis, "plan_optimizado": opt_sim_result.kpis})
    comparison.to_csv(os.path.join(OUTPUT_DIR, "comparacion_kpis.csv"))

    print(f"\n--- Comparación de KPIs [Datos Reales] ---")
    print(comparison.round(2).to_string())


def _print_kpis(kpis):
    for k, v in kpis.items():
        if isinstance(v, float):
            print(f"   {k}: {v:.2f}")
        else:
            print(f"   {k}: {v}")


if __name__ == "__main__":
    main()
