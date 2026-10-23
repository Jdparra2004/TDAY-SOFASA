# Arquitectura - Optimizador de Programación de Contenedores CKD (Renault-Sofasa)

Estructura modular del software y flujo de datos. Última actualización: 2026-10-23.

## 1. Principio de diseño

Toda la lógica vive en `src/`. `app.py` (web) y `main.py` (consola) solo llaman a `src/pipeline.py`, de modo que el proceso por lote, el modo manual y la consola comparten exactamente la misma lógica y los mismos parámetros.

## 2. Flujo de punta a punta

```
Excel (Tracking, DIEL, Prioridades) o lista manual
        |
        v
build_params            -> Params (6 parámetros del usuario + constantes)
prepare_universe        -> clasifica: excluidos / fuera de ventana / programables
        |
        v
run_pipeline
   1. baseline_plan     -> plan de la línea base (heurística as-is)
   2. optimize_plan     -> plan optimizado (CP-SAT, partiendo de la línea base como pista)
   3. run_simulation    -> simula ambos planes (SimPy) y obtiene KPIs diarios y por contenedor
   4. compute_costs     -> costo de ambos planes (una sola función)
   5. capacity_usage    -> uso máximo de capacidades
   6. compute_validations -> 17 validaciones
        |
        v
Resultado -> app.py (pantalla) / export.py (Excel de 10 hojas y CSV) / main.py (consola y gráficos)
```

## 3. Módulos

| Módulo | Responsabilidad |
|---|---|
| `src/model.py` | `Container`, `Params` (parámetros del usuario y constantes del modelo), `Plan`, estados de contenedor |
| `src/data_processor.py` | Lectura y limpieza de Tracking, DIEL y Prioridades; cálculo de EM objetivo; clasificación del universo (`classify_universe`, `finalize_universe`); `process_real_tracking_data` |
| `src/optimization.py` | `baseline_plan` (heurística) y `optimize_plan` (modelo CP-SAT) con estados OPTIMAL, FEASIBLE, FALLBACK_LINEA_BASE y SIN_SOLUCION |
| `src/simulation.py` | Simulación de eventos discretos con SimPy; KPIs diarios y por contenedor |
| `src/costs.py` | `compute_costs` (única función de costo) y `weighted_objective` (objetivo ponderado del solver evaluado sobre cualquier plan) |
| `src/pipeline.py` | `build_params`, `prepare_universe`, `run_pipeline`, `compute_validations`, `print_validaciones`; dataclass `Resultado` con costo evitable, rupturas y costo por ruptura evitada |
| `src/export.py` | Construcción de las hojas del Excel y exportación a Excel y CSV |
| `src/glossary.py` | Glosario de la guía rápida de la web |
| `src/visualize.py` | Gráficos: ocupación de Suppla, distribución de lead time, KPIs, costos y Sankey |
| `app.py` | Interfaz Streamlit: login, portada, modo manual, modo por lote, resultados y descargas |
| `main.py` | Ejecución por consola con argumentos de los 6 parámetros, carpeta de datos y control del solver |

## 4. Clasificación del universo

Cada contenedor del Tracking cae en exactamente un bloque:

- **Excluido:** tiene EM real anterior al día 0 (ya está en planta).
- **Fuera de ventana:** su ETA es posterior a `horizonte - 1`; se programa en la siguiente planeación.
- **Programable:** el resto. El solver lo deja dentro del horizonte, en EM proyectada o diferido.

Los tres bloques suman el total del Tracking (validación 2).

## 5. Estados de un contenedor programado

- `PROGRAMADO_EN_HORIZONTE`: EM dentro de los días del horizonte.
- `EM_PROYECTADA`: EM después del horizonte pero antes de `horizonte + 12` (llega dentro del horizonte, entra después por capacidad).
- `DIFERIDO_SIN_CUPO`: sin cupo hasta `horizonte + 12`.

## 6. Garantías del optimizador

- El plan devuelto nunca es peor que la línea base según `weighted_objective`. Si el solver no logra superarla, se devuelve la línea base con estado `FALLBACK_LINEA_BASE`.
- La línea base se entrega al solver como pista inicial (todas las variables 0/1) y el solver usa `repair_hint`.
- El tiempo límite, los hilos y la semilla son argumentos de `run_pipeline`: 60 s por defecto, 8 hilos en consola, 120 s y 8 hilos en la web.

## 7. Interfaz web

- Autenticación por contraseña leída de `st.secrets["auth"]["password"]`.
- Portada con dos modos: manual (pocos contenedores ingresados a mano, con "Cargar ejemplos") y por lote (tres archivos Excel).
- Los dos modos usan el mismo panel de seis parámetros y `_run_and_store`, que llama a `prepare_universe` y `run_pipeline`.
- El resultado se guarda en `st.session_state` (`res_manual`, `res_lote`) y se muestra con `render_resultados`: indicadores del universo, indicadores de resultado, impacto económico y tres vistas (decisiones por contenedor, KPI Dashboard y Sankey).
- Las validaciones no se muestran en la interfaz; viajan en la hoja "Validaciones" del Excel.

## 8. Despliegue

Streamlit Cloud, rama `main`, archivo `app.py`. La contraseña vive en Secrets. Ver `MANUAL_TECNICO.md`.

## 9. Pruebas

`tests/` contiene pruebas con pytest sobre el pipeline y los datos de prueba. Las pruebas que leen `data/` necesitan la ruta exacta de una de sus subcarpetas.
