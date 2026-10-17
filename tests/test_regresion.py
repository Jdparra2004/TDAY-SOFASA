import pandas as pd
import numpy as np
import sys
from pathlib import Path

# Añadir src al path
sys.path.append(str(Path(__file__).parent.parent))
from src.model import Params
from src.simulation import run_simulation
from src.optimization import optimize_plan
from src.data_processor import process_real_tracking_data, process_real_tracking_dataframe

def run_pipeline_for_folder(folder_path: str):
    print("=" * 70)
    print(f"VALIDACIÓN DE DATOS REALES DE SOFASA ({folder_path})")
    print("=" * 70)
    
    df = process_real_tracking_dataframe(folder_path)
    containers = process_real_tracking_data(folder_path)
    
    print(f"Contenedores cargados desde {folder_path}: {len(containers)}")
    assert len(containers) > 0, f"Debe cargar contenedores de {folder_path}"

    n_ruptura_real = int((~df["ruptura_estimada"]).sum())
    print(f"Contenedores con ruptura real: {n_ruptura_real}")

    params = Params(horizon=60)
    
    print(f"\n--- Ejecutando Simulación Línea Base (SimPy) [{folder_path}] ---")
    base_res = run_simulation(containers, params, plan=None)
    print(f"Rupturas línea base: {base_res.kpis['n_rupturas']}")

    print(f"\n--- Ejecutando Optimización (OR-Tools CP-SAT) [{folder_path}] ---")
    opt_res = optimize_plan(containers, params, time_limit_s=25.0)
    print(f"Status optimizador: {opt_res.status}, Objetivo: {opt_res.objective_value}")

    if opt_res.plan:
        opt_sim_res = run_simulation(containers, params, plan=opt_res.plan)
        print(f"Rupturas plan optimizado: {opt_sim_res.kpis['n_rupturas']}")
        assert opt_sim_res.kpis['n_rupturas'] <= base_res.kpis['n_rupturas'], "El plan optimizado no debe tener mas rupturas que la linea base."

    print(f"\n[OK] Pipeline con {folder_path} validado exitosamente.")

def test_all_datasets():
    run_pipeline_for_folder("data/1st Data")
    run_pipeline_for_folder("data/2nd Data")

if __name__ == "__main__":
    test_all_datasets()
    print("\n¡Pruebas de integración con ambos datasets completadas exitosamente!")
