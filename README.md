# Optimizador de Programación de Contenedores CKD - Renault-Sofasa

Aplicación para programar la entrada a planta (EM, Entrada de Mercancía) de los contenedores CKD que llegan a puerto, decidiendo para cada uno el día de ingreso y la ruta: directo a la planta SOFASA o vía la bodega externa Suppla (Rionegro). Desarrollada para el reto Transformation Day 2026.

Última actualización de la documentación: 2026-10-23.

---

## Qué hace

1. Lee tres archivos Excel: Tracking de contenedores (obligatorio), Programación DIEL y Prioridades CKD (aportan la fecha real de ruptura y la EM previa).
2. Clasifica el universo: excluye los contenedores que ya entraron a planta antes del día 0, deja para la siguiente planeación los que llegan después del horizonte y programa el resto.
3. Simula una línea base (heurística "as-is") con SimPy.
4. Optimiza con OR-Tools CP-SAT un plan que prioriza evitar rupturas de producción, respeta las capacidades y reduce demurrage y almacenamiento en Suppla.
5. Compara línea base y plan optimizado y entrega un Excel con la programación por contenedor, capacidad diaria, impacto económico y validaciones.

## Parámetros que controla el usuario

Solo seis, iguales en el proceso por lote, el modo manual y la línea de comandos:

| Parámetro | Valor por defecto |
|---|---|
| Fecha de planeación (día 0) | 2026-10-20 |
| Horizonte (días) | 20 |
| Capacidad SOFASA por día | 14 |
| Capacidad Suppla por semana | 15 |
| Capacidad de traslado Suppla a SOFASA por día | 2 |
| Días habilitados de traslado | Lunes a viernes |

Todo lo demás son constantes del modelo (`Params` en `src/model.py`): mínimo 7, objetivo 10 y máximo 12 días entre ETA y EM, demurrage de 80 USD por día, almacenamiento Suppla de 1.049,17 USD por mes por contenedor de 40 pies, entre otras. Ver `docs/MODELO_MATEMATICO.md`.

## Cómo leer los resultados (resumen)

- El indicador económico mide solo dólares de demurrage y Suppla. El optimizador no minimiza solo dólares: da prioridad a evitar rupturas, por lo que el indicador puede salir negativo mientras el plan mejora.
- Una parte del demurrage ya se acumuló antes del día 0 y ningún plan puede evitarla. La aplicación la informa por separado.
- El solver se detiene por tiempo límite y normalmente devuelve el estado FEASIBLE (plan válido, no probado óptimo). Las cifras pueden variar entre ejecuciones y deben tomarse como plan de referencia, no como una cifra oficial. Ver la sección de limitaciones en `MANUAL_TECNICO.md`.

## Estructura del proyecto

```
.
├── app.py                  # Interfaz web (Streamlit): modo por lote y modo manual
├── main.py                 # Ejecución por consola de punta a punta (CLI)
├── requirements.txt        # Dependencias
├── README.md
├── MANUAL_TECNICO.md       # Instalación, ejecución, despliegue y limitaciones
├── MANUAL_USUARIO.md       # Guía de uso de la aplicación web
│
├── src/
│   ├── model.py            # Container, Params (parámetros y constantes), Plan
│   ├── data_processor.py   # Lectura y limpieza de Tracking, DIEL y Prioridades; clasificación del universo
│   ├── costs.py            # compute_costs: única función de costo (demurrage y Suppla)
│   ├── simulation.py       # Línea base y simulación de eventos discretos (SimPy)
│   ├── optimization.py     # Modelo CP-SAT y línea base heurística
│   ├── pipeline.py         # build_params, prepare_universe, run_pipeline, validaciones
│   ├── export.py           # Excel de 10 hojas y CSV de la programación
│   ├── glossary.py         # Glosario de la guía rápida de la web
│   └── visualize.py        # Gráficos (ocupación de Suppla, Sankey, KPIs)
│
├── tests/                  # Pruebas automatizadas (pytest)
├── docs/
│   ├── ARCHITECTURE.md
│   └── MODELO_MATEMATICO.md
├── data/                   # Datos de prueba (subcarpetas con Tracking, DIEL y Prioridades)
└── output/                 # Resultados generados por main.py
```

`app.py` y `main.py` no contienen lógica de optimización, simulación ni costos: solo llaman a `src/pipeline.py`.

## Instalación y uso rápido

```bash
python -m venv venv
venv\Scripts\Activate.ps1          # Windows PowerShell; en Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
```

Interfaz web local:

```bash
streamlit run app.py
```

La web pide una contraseña definida en los secretos de Streamlit (ver `MANUAL_TECNICO.md`, sección de despliegue).

Ejecución por consola con los datos de prueba:

```bash
python main.py --datos "data\3nd Data"
```

Pruebas:

```bash
python -m pytest -q
```

## Documentación

- `MANUAL_USUARIO.md`: cómo usar la aplicación web.
- `MANUAL_TECNICO.md`: instalación, ejecución, despliegue, validaciones y limitaciones conocidas.
- `docs/ARCHITECTURE.md`: capas, módulos y flujo de datos.
- `docs/MODELO_MATEMATICO.md`: reglas de negocio, variables, restricciones y función objetivo.
