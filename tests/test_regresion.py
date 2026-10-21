import pandas as pd
import numpy as np
import sys
from pathlib import Path
from collections import Counter

# Añadir src al path
sys.path.append(str(Path(__file__).parent.parent))
from src.model import Params
from src.simulation import run_simulation
from src.optimization import optimize_plan
from src.data_processor import process_real_tracking_data, process_real_tracking_dataframe

def test_3nd_data_pipeline():
    folder_path = "data/3nd Data"
    base_date = pd.Timestamp("2026-10-20")
    print("=" * 70)
    print(f"VALIDACIÓN DE DATOS REALES DE SOFASA ({folder_path}) - Fecha base: {base_date.date()}")
    print("=" * 70)
    
    df = process_real_tracking_dataframe(folder_path, base_date=base_date)
    containers = process_real_tracking_data(folder_path, base_date=base_date)
    
    print(f"Contenedores cargados desde {folder_path}: {len(containers)}")
    assert len(containers) > 0, f"Debe cargar contenedores de {folder_path}"

    n_en_puerto = int(df["ya_en_puerto"].sum()) if "ya_en_puerto" in df.columns else 0
    print(f"Contenedores ya en puerto antes del día 0: {n_en_puerto}")

    params = Params(
        horizon=20,
        cap_sofasa_per_day=14,
        cap_suppla_per_week=15,
        cap_traslado_per_day=2,
        transfer_days_allowed=[0, 1, 2, 3, 4],  # Lunes a Viernes
        sofasa_days_allowed=[0, 1, 2, 3, 4],    # Lunes a Viernes
        cost_rupture_event=500.0,
        start_weekday=base_date.weekday(),
    )
    
    print(f"\n--- Ejecutando Simulación Línea Base (SimPy) [{folder_path}] ---")
    base_res = run_simulation(containers, params, plan=None)
    print(f"Rupturas línea base: {base_res.kpis['n_rupturas']}")

    print(f"\n--- Ejecutando Optimización (OR-Tools CP-SAT) [{folder_path}] ---")
    opt_res = optimize_plan(containers, params, time_limit_s=30.0, verbose=True)
    print(f"Status optimizador: {opt_res.status}, Objetivo: {opt_res.objective_value}")

    if opt_res.plan:
        plan = opt_res.plan
        wd = lambda t: (base_date.weekday() + t) % 7

        em_dia = Counter(e.em_day for e in plan.values())
        assert max(em_dia.values(), default=0) <= 14, f"SOFASA excede 14/día: {em_dia.most_common(3)}"
        assert all(wd(t) in params.sofasa_days_allowed for t in em_dia), "Entradas en días no habilitados de SOFASA"

        sup_sem = Counter((base_date.weekday() + e.suppla_in_day) // 7
                          for e in plan.values() if e.route == "suppla" and e.suppla_in_day is not None)
        assert max(sup_sem.values(), default=0) <= 15, f"Suppla excede 15/semana: {sup_sem}"

        traslados = Counter(e.em_day for e in plan.values() if e.route == "suppla")
        assert max(traslados.values(), default=0) <= 2, f"Traslado excede 2/día: {traslados}"
        assert all(wd(t) <= 4 for t in traslados), "Hay traslados en sábado o domingo"

        print(f"Diferidos/fuera de horizonte: {len(opt_res.out_of_horizon)} de {len(containers)}")

        opt_sim_res = run_simulation(containers, params, plan=opt_res.plan)
        print(f"Rupturas plan optimizado: {opt_sim_res.kpis['n_rupturas']}")
        assert opt_sim_res.kpis['n_rupturas'] <= base_res.kpis['n_rupturas'], "El plan optimizado no debe tener mas rupturas que la linea base."

    print(f"\n[OK] Pipeline con {folder_path} validado exitosamente.")

if __name__ == "__main__":
    test_3nd_data_pipeline()
    print("\n¡Prueba de integración con 3nd Data completada exitosamente!")
