"""
main.py — ejecución de punta a punta con los datos reales (carpeta data/). Usa el mismo flujo de src/pipeline.py
que la app. Por CLI SOLO acepta los 6 parámetros del usuario.
"""
from __future__ import annotations

import argparse
import os

import matplotlib.pyplot as plt
import pandas as pd

import src.visualize as viz
from src.export import export_prescriptive_plan
from src.pipeline import build_params, prepare_universe, run_pipeline, print_validaciones

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output", "datos_reales")


def main(fecha="2026-10-20", horizonte=20, cap_sofasa=14, cap_suppla_semana=15, cap_traslado=2,
         dias_traslado=(0, 1, 2, 3, 4), data_dir=None, out_dir=None, time_limit_s=None, workers=8, seed=0, verbose=False):
    out_dir = out_dir or OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    params = build_params(fecha, horizonte, cap_sofasa, cap_suppla_semana, cap_traslado, dias_traslado)
    programables, df_universo = prepare_universe(data_dir or os.path.join(BASE_DIR, "data"), params)
    if not programables:
        print("ERROR: no hay contenedores programables. Verifique los Excel de data/.")
        return None
    res = run_pipeline(programables, params, df_universo, time_limit_s=time_limit_s, workers=workers, seed=seed, verbose=verbose)

    e = res.embudo
    print(f"Universo: Tracking {e['tracking_total']} = excluidos {e['excluidos']} + fuera de ventana {e['fuera_ventana']} + programables {e['programables']}")
    print(f"Solver: status={res.solver.status}  gap={res.solver.gap:.4f}")
    for nombre, c in (("Línea base", res.costos_base), ("Plan optimizado", res.costos_opt)):
        print(f"{nombre}: demurrage {c.totals['usd_demurrage']:,.0f} USD + almacenamiento Suppla {c.totals['usd_suppla']:,.0f} USD = {c.totals['usd_total']:,.0f} USD")
    print(f"Ahorro (base − óptimo, contra la línea base simulada): {res.ahorro_usd:,.0f} USD")
    print(f"Demurrage previo al día 0 (inevitable): {res.costos_base.acumulado_previo_dias} días = {res.costos_base.acumulado_previo_usd:,.0f} USD")
    print(f"Costo evitable: base {res.costo_evitable_base:,.0f} USD, óptimo {res.costo_evitable_opt:,.0f} USD")
    print(f"Rupturas: {res.rupturas_base} -> {res.rupturas_opt} (evitadas {res.rupturas_evitadas}); "
        f"costo neto por ruptura evitada: {res.costo_por_ruptura_evitada:,.0f} USD")

    xlsx = export_prescriptive_plan(res, os.path.join(out_dir, "plan_prescriptivo_sofasa.xlsx"))
    print(f"Entregable: {xlsx} (+ .csv)")

    res.base.container_df.to_csv(os.path.join(out_dir, "contenedores_baseline.csv"), index=False)
    res.optimo.container_df.to_csv(os.path.join(out_dir, "contenedores_optimizado.csv"), index=False)
    res.base.daily_df.to_csv(os.path.join(out_dir, "diario_baseline.csv"), index=False)
    res.optimo.daily_df.to_csv(os.path.join(out_dir, "diario_optimizado.csv"), index=False)
    pd.DataFrame({"linea_base": res.base.kpis, "plan_optimizado": res.optimo.kpis}).to_csv(os.path.join(out_dir, "comparacion_kpis.csv"))

    figs = {
        "01_ocupacion_suppla.png": viz.plot_suppla_occupancy(res.base.daily_df, res.optimo.daily_df),
        "02_lead_time.png": viz.plot_lead_time_distribution(res.base.container_df, res.optimo.container_df, params),
        "03_kpi_dashboard.png": viz.plot_kpi_dashboard(res.base.kpis, res.optimo.kpis),
        "04_costos_usd.png": viz.plot_cost_comparison(res.costos_base, res.costos_opt),
    }
    for name, fig in figs.items():
        fig.savefig(os.path.join(out_dir, name), bbox_inches="tight")
        plt.close(fig)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", default="2026-10-20", help="Fecha de planeación (día 0), AAAA-MM-DD.")
    ap.add_argument("--horizonte", type=int, default=20, help="Horizonte en días.")
    ap.add_argument("--cap-sofasa", type=float, default=14, help="Capacidad SOFASA por día.")
    ap.add_argument("--cap-suppla-semana", type=float, default=15, help="Capacidad Suppla por semana.")
    ap.add_argument("--cap-traslado", type=float, default=2, help="Capacidad de traslado por día.")
    ap.add_argument("--dias-traslado", default="0,1,2,3,4", help="Días habilitados de traslado (0=lunes ... 6=domingo), separados por coma.")
    ap.add_argument("--datos", default=None, help="Carpeta con Tracking, Prioridades y DIEL (por ejemplo: data\\3nd Data).")
    ap.add_argument("--tiempo", type=float, default=None, help="Límite de tiempo del solver en segundos (por defecto, el de Params).")
    ap.add_argument("--workers", type=int, default=8, help="Hilos del solver.")
    ap.add_argument("--semilla", type=int, default=0, help="Semilla del solver.")
    a = ap.parse_args()
    main(a.fecha, a.horizonte, a.cap_sofasa, a.cap_suppla_semana, a.cap_traslado,
         [int(x) for x in a.dias_traslado.split(",")], data_dir=a.datos,
         time_limit_s=a.tiempo, workers=a.workers, seed=a.semilla)
