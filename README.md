# Reto 7 Sofasa - Simulacion y Optimizacion de la Cadena CKD (Puerto -> Fabrica SOFASA / Suppla Rionegro -> Produccion)

Software avanzado de cadena de suministro CKD para Renault-Sofasa.
Este proyecto permite reproducir, simular, optimizar y generar planes prescriptivos de asignacion de rutas (Ingreso Directo a Fabrica vs. Almacenamiento en Bodega Suppla en Rionegro) y fechas de entrada de mercancia (EM) para contenedores CKD reales y sinteticos.

---

## Modulos y Librerias Clave

- [SimPy](https://simpy.readthedocs.io/) - Simulacion de eventos discretos. Se usa en `src/simulation.py` para modelar paso a paso el comportamiento operativo de recepciones, traslados y tiempos de transito.
- [OR-Tools CP-SAT](https://developers.google.com/optimization/cp) - Optimizador de programacion por restricciones de Google. Se usa en `src/optimization.py` para calcular el plan optimo de arribos y rutas que minimiza rupturas, demurrage y costos de almacenamiento en Suppla.
- [Streamlit](https://streamlit.io/) - Interfaz web interactiva en `app.py` que permite la carga interactiva de archivos Excel reales, calculo dinamico del horizonte, parametrizacion simplificada de Suppla y Sofasa, visualizacion de fechas calendario y generacion de recomendaciones operativas prescriptivas (sin emojis).
- [Pandas](https://pandas.pydata.org/) & [Openpyxl](https://openpyxl.readthedocs.io/) - Procesamiento, normalizacion y lectura robusta de Excels oficiales de Tracking, Programacion DIEL y Prioridades CKD.

---

## Caracteristicas Principales

1. **Visualizacion en Fechas Calendario:** Todas las fechas de ruptura (*Need By*), ETA Puerto, Entrada a Planta (EM) y Recepcion Suppla se visualizan en formato de fecha calendario (`YYYY-MM-DD`) tomando como base el dia de ejecucion actual (hoy), mientras que el sistema procesa los calculos internamente en dias.
2. **Interfaz Simplificada y Operativa:** Los planificadores solo configuran los parametros reales que reciben en su operacion:
   - **Bodega Suppla (Rionegro):** Capacidad semanal de recepcion, capacidad diaria de traslado hacia fabrica y dias de la semana habilitados para despachos.
   - **Fabrica SOFASA:** Capacidad maxima de recepcion diaria en planta.
   - Se prescinde de campos abstractos de inventario inicial, capacidad en uso o tasa de consumo diario.
3. **Carga Interactiva de Excels:** Carga directa por parte del usuario de archivos oficiales de Tracking, Programacion DIEL y Prioridades CKD desde la interfaz web.
4. **Horizonte de Planeacion Dinamico:** Calculo automatico del horizonte a partir de las fechas minimas de ETA y maximas de ruptura (`need_by`).
5. **Salida Prescriptiva y Accionable:** Cuadro detallado de decisiones operativas por contenedor (Ruta, Fecha Suppla, Dia de Traslado, Fecha EM y Estado de Riesgo) con opcion de descarga en CSV.
6. **Dashboards Interactivos de KPIs:** Diagramas interactivos de cumplimiento de lead time, rupturas, uso de Suppla y distribucion de tiempos corporativos.

---

## Organizacion y Estructura del Proyecto

```
sofasa_supply_chain_v1_2/
├── app.py                 # Aplicacion principal de interfaz web (Streamlit)
├── main.py                # Script de simulacion y optimizacion por CLI (ejecucion batch)
├── requirements.txt       # Dependencias del entorno
├── MANUAL_TECNICO.md      # Manual tecnico y de instalacion detallado
├── README.md              # Documentacion general del proyecto
│
├── src/                   # Codigo de produccion (Logica de Negocio)
│   ├── model.py           # Modelos de datos y parametros configurables (Params, Container)
│   ├── data_generator.py  # Generador de flujos de contenedores sinteticos
│   ├── data_processor.py  # Procesador y limpiador de archivos Excel subidos
│   ├── simulation.py      # Motor de simulacion en SimPy (dia a dia)
│   ├── optimization.py    # Modelo matematico del solver CP-SAT con holguras flexibles
│   └── visualize.py       # Renderizado de dashboards de KPIs y curvas de inventario
│
├── tests/                 # Pruebas automatizadas y de regresion
│   └── test_regresion.py  # Pruebas validadas contra benchmarks y datos reales
│
├── docs/                  # Documentacion tecnica
│   ├── ARCHITECTURE.md    # Arquitectura detallada del software
│   ├── MODELO_MATEMATICO.md # Formulacion matematica completa, variables y restricciones
│   └── SESSION_SUMMARY.md # Resumen de sesion y estado actual del proyecto
│
├── base_entendimiento/    # Modelos base, pedagogicos y del docente
└── output/                # Resultados generados (tablas CSV y graficos PNG)
```

---

## Instalacion y Uso

### 1. Configurar Entorno Virtual

```bash
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Ejecutar Pruebas de Regresion

```bash
python tests/test_regresion.py
```

### 3. Ejecutar la Interfaz Web (Streamlit)

```bash
streamlit run app.py
```

Abre tu navegador en `http://localhost:8501`.
