# Arquitectura del Proyecto - Reto 7 Sofasa

Este documento describe la estructura modular y la arquitectura del software de cadena de suministro CKD para Renault-Sofasa, incorporando la gestion multi-bodega (Fabrica SOFASA + Bodega Suppla en Rionegro), visualizacion en fechas calendario (`YYYY-MM-DD`) con base en el dia actual (hoy), procesamiento avanzado de datos reales, simulacion en SimPy y optimizacion robusta mediante CP-SAT.

## 1. Visión General del Sistema

El sistema opera bajo una arquitectura modular en capas:
1. **Capa de Datos (`src/data_processor.py` y `src/data_generator.py`):** Carga, limpia y estructura datos tabulares provenientes de archivos Excel/XLSM oficiales (Tracking, Programacion DIEL y Prioridades CKD) o genera flujos sinteticos de prueba.
2. **Capa de Modelado y Simulación (`src/model.py` y `src/simulation.py`):** Define las estructuras base (`Container`, `Params`) y ejecuta simulaciones de eventos discretos en SimPy para modelar el comportamiento operativo del sistema.
3. **Capa de Optimización Prescriptiva (`src/optimization.py`):** Resuelve el modelo de programacion entera por restricciones mediante Google OR-Tools CP-SAT para determinar las rutas optimas (Directo vs. Suppla Rionegro) y las fechas de entrada a planta (EM).
4. **Capa de Visualización y Reportes (`src/visualize.py`):** Genera graficos analiticos de distribuciones de lead times y tableros de KPIs.
5. **Capa de Presentación e Interfaz Web (`app.py`):** Aplicacion interactiva en Streamlit que orquesta el flujo completo con paginacion, filtros avanzados, configuracion simplificada de capacidades de Suppla y Sofasa, visualizacion en fechas calendario y cuadros de decisiones operativas.

## 2. Estructura de Directorios

- `src/`: Codigo fuente principal de produccion (Logica de Negocio).
  - `model.py`: Clases de datos (`Container`, `Params` con configuracion de Suppla Rionegro) y costos.
  - `data_processor.py`: Procesamiento y normalizacion de archivos Excel/XLSM con validacion de esquemas y auto-descubrimiento.
  - `simulation.py`: Motor de eventos discretos en **SimPy** para la simulacion diaria y evaluacion de politicas.
  - `optimization.py`: Modelo matematico de programacion entera por restricciones mediante **OR-Tools CP-SAT** con restricciones de Suppla Rionegro y holguras flexibles.
  - `visualize.py`: Generacion de tableros de KPIs y curvas operativas para Matplotlib y Streamlit.
- `app.py`: Aplicacion web interactiva en Streamlit que gestiona:
  - Carga interactiva de archivos Excel (Tracking, DIEL, Prioridades).
  - Visualizacion de fechas en formato calendario (`YYYY-MM-DD`) tomando el dia actual como base.
  - Parametrizacion simplificada (capacidades de recepcion semanal en Suppla, traslado diario y recepcion diaria en SOFASA).
  - Tabla Prescriptiva de Decisiones Operativas y exportacion a CSV.
- `main.py`: Punto de entrada CLI para ejecucion de corridas batch con datos reales (`data/`).
- `docs/`: Documentacion tecnica, especificacion del modelo matematico y resumen de sesion.
- `tests/`: Pruebas de regresion automatizadas frente a los datos reales y desempeno del optimizador.
- `base_entendimiento/`: Material pedagogico, modelos de dos etapas y referencia historica.
- `output/`: Almacenamiento de reportes generados (CSV y PNG).
