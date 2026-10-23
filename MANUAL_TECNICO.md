# Manual Técnico - Optimizador de Programación de Contenedores CKD (Renault-Sofasa)

Instalación, ejecución local, despliegue en Streamlit Cloud, validaciones y limitaciones conocidas. Última actualización: 2026-10-23.

---

## 1. Requisitos

- Python. Producción corre en Python 3.14; use una versión equivalente o cercana en local.
- Windows, Linux o macOS.
- `pip`.

## 2. Instalación

```bash
cd ruta/al/proyecto
python -m venv venv
venv\Scripts\Activate.ps1          # Windows PowerShell
# source venv/bin/activate         # Linux / macOS
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Librerías principales

- `pandas`, `numpy`: lectura y manipulación de los Excel y cálculos de tablas.
- `openpyxl`: lectura y escritura de `.xlsx` y `.xlsm`.
- `ortools` (CP-SAT): solver de programación por restricciones.
- `simpy`: simulación de eventos discretos de la línea base.
- `streamlit`: interfaz web.
- `matplotlib` y `plotly`: gráficos (ocupación de Suppla, Sankey).
- `pytest`: pruebas.

## 3. Datos de entrada

El Tracking de contenedores es obligatorio y define el universo. DIEL y Prioridades CKD aportan la fecha real de ruptura y la EM previa.

- Los archivos se pueden subir en la web o leer desde una carpeta en `main.py`.
- La carpeta `data/` contiene subcarpetas por entrega (`1st Data`, `2nd Data`, `3nd Data`). `main.py` necesita la ruta exacta de una de ellas con el argumento `--datos`.
- Si una hoja de Prioridades (por ejemplo `TD`) no comparte contenedores con la hoja maestra, se omite y la consola lo informa.
- El Tracking no trae fecha de salida del puerto ni de recepción en Suppla. La columna "Comentario" indica la ubicación actual ("PUERTO" o "SUPPLA-DHL"). En la entrega 3nd Data los dos contenedores en Suppla ya tienen EM real anterior al día 0 y quedan excluidos del universo.

## 4. Ejecución por consola

```bash
python main.py --datos "data\3nd Data"
```

Argumentos:

| Argumento | Descripción | Por defecto |
|---|---|---|
| `--datos` | Carpeta con Tracking, DIEL y Prioridades | `data/` (falla si hay subcarpetas) |
| `--fecha` | Fecha de planeación (día 0), AAAA-MM-DD | 2026-10-20 |
| `--horizonte` | Horizonte en días | 20 |
| `--cap-sofasa` | Capacidad SOFASA por día | 14 |
| `--cap-suppla-semana` | Capacidad Suppla por semana | 15 |
| `--cap-traslado` | Capacidad de traslado por día | 2 |
| `--dias-traslado` | Días habilitados (0 lunes a 6 domingo), separados por coma | 0,1,2,3,4 |
| `--tiempo` | Límite de tiempo del solver en segundos | 60 (constante `solver_time_limit_s`) |
| `--workers` | Hilos del solver | 8 |
| `--semilla` | Semilla del solver | 0 |

Para obtener una cifra de referencia más sólida se recomienda una corrida larga:

```bash
python main.py --datos "data\3nd Data" --tiempo 300 --workers 8 --semilla 1
```

La consola imprime el universo, el estado del solver, los costos de la línea base y del plan optimizado, el demurrage previo al día 0, el costo evitable, las rupturas evitadas y las validaciones. Los resultados se guardan en `output/datos_reales/`:

- `plan_prescriptivo_sofasa.xlsx` y `.csv`
- `contenedores_baseline.csv` y `contenedores_optimizado.csv`
- `diario_baseline.csv` y `diario_optimizado.csv`
- `comparacion_kpis.csv`
- Gráficos PNG (ocupación de Suppla, distribución de lead time, KPIs, costos)

## 5. Interfaz web local

```bash
streamlit run app.py
```

Abre en `http://localhost:8501`. La aplicación exige una contraseña leída de `st.secrets`. Cree `.streamlit/secrets.toml` (no debe versionarse) con:

```toml
[auth]
password = "SU_CONTRASEÑA"
```

Si falta el bloque, la aplicación bloquea el acceso y lo informa. Ver `MANUAL_USUARIO.md` para el uso.

En la web el solver corre con 8 hilos y un límite de 120 segundos (llamada en `_run_and_store` de `app.py`).

## 6. Despliegue en Streamlit Cloud

1. El código se despliega desde la rama `main`, archivo `app.py`.
2. Cada `git push` a `main` reconstruye la aplicación. Confirme en GitHub que el commit está en `main` antes de interpretar resultados de producción.
3. La contraseña se configura en Settings, Secrets, bloque `[auth]` de la aplicación en Streamlit Cloud.
4. No suba `.streamlit/secrets.toml` al repositorio. Verifique con `git ls-files .streamlit`.
5. La contraseña original estuvo escrita en el código y permanece en el historial de Git. Debe cambiarse en Secrets (ya hecho) y no reutilizarse.
6. Streamlit Cloud tiene CPU limitada y puede mostrar "Your app has been throttled". Con CPU reducida el solver encuentra planes peores que en local.

## 7. Pruebas

```bash
python -m pytest -q
```

Las pruebas viven en `tests/`. Las que leen datos reales necesitan que la carpeta de datos esté disponible en la ruta que esperan.

## 8. Validaciones automáticas (17)

Se calculan en `compute_validations` (`src/pipeline.py`), se imprimen en consola y se guardan en la hoja "Validaciones" del Excel. No se muestran en la interfaz.

1. IDs del universo contenidos en el Tracking.
2. Embudo: excluidos + fuera de ventana + programables = Tracking.
3. ETA de programables dentro de la ventana.
4. Capacidades respetadas, línea base.
5. Capacidades respetadas, plan óptimo.
6. EM - ETA mayor o igual que el mínimo, línea base.
7. EM - ETA mayor o igual que el mínimo, plan óptimo.
8. Mismo número de contenedores en base y óptimo.
9. Rupturas solo sobre ruptura real, línea base.
10. Costo recalculado igual al costo reportado, línea base.
11. Rupturas solo sobre ruptura real, plan óptimo.
12. Costo recalculado igual al costo reportado, plan óptimo.
13. Días de Suppla al menos el número de contenedores vía Suppla por la estancia mínima, línea base.
14. Lo mismo para el plan óptimo.
15. Todo programable tiene estado.
16. Objetivo ponderado del óptimo menor o igual al de la base.
17. Ahorro igual a costo base menos costo óptimo.

Limitación conocida: la validación 17 es tautológica (el ahorro se define como esa diferencia) y la 10 y 12 recalculan el demurrage con la misma columna de salida de puerto que usa el costo reportado. Están pendientes de reemplazo por comprobaciones independientes.

## 9. Interpretación del costo

Ver `docs/MODELO_MATEMATICO.md` para las fórmulas. Puntos clave para quien audite las cifras:

- El costo del indicador es demurrage más almacenamiento Suppla. Se calcula con una sola función (`compute_costs` en `src/costs.py`) para la línea base y para el plan optimizado.
- Cuenta hasta el día en que cada contenedor entra a planta, incluso fuera del horizonte (hasta el día `horizonte + 12`).
- Incluye el demurrage acumulado antes del día 0, que es igual en ambos planes (inevitable). En el Tracking 3nd Data son 488 días, 39.040 USD. El "costo evitable" es el total menos esa cifra.
- El ahorro se calcula contra la línea base simulada, no contra el gasto histórico real.
- El solver minimiza un objetivo ponderado donde un día de ruptura pesa 1.000 y el demurrage de un día 80, por lo que el plan puede costar más dólares y aun así ser mejor según el objetivo.

## 10. Resultados de referencia (Tracking 3nd Data, 550 contenedores)

Universo: 24 excluidos, 110 fuera de ventana, 416 programables (100 con ruptura real). Línea base: 169.101 USD (demurrage 152.000 más Suppla 17.101), 100 rupturas.

| Ejecución | Gap | Diferencia en USD (base menos óptimo) | Rupturas |
|---|---|---|---|
| Local 60 s, 8 hilos (4 corridas) | 50 a 56 % | de -4.000 a -14.800 | de 100 a 69-80 |
| Local 300 s, 8 hilos, semilla 0 | 36 % | -5.967 | 100 a 52 |
| Local 300 s, 8 hilos, semilla 1 | 33 % | -7.727 | 100 a 31 |
| Web 120 s, 8 hilos (3 corridas) | 43 a 50 % | de -5.700 a -12.800 | de 100 a 50-68 |

Con tiempo y CPU limitados el solver devuelve planes distintos en cada corrida y ninguno probado óptimo. En todas las corridas el plan evita entre 20 y 69 de las 100 rupturas, con un costo de entre unos 110 y 640 USD por ruptura evitada. Con 300 s el costo adicional se estabilizó entre 6.000 y 7.700 USD.

## 11. Limitaciones conocidas

- **No reproducible por tiempo límite.** El solver se corta por reloj; con 8 hilos dos corridas con la misma semilla pueden diferir. Para una cifra de referencia use una corrida local larga y repórtela como plan de referencia con su gap.
- **Web frente a local.** La web tiene menos CPU y menos tiempo; sus planes suelen ser peores que los de una corrida local de 300 s.
- **Diferidos.** Un contenedor sin cupo en `horizonte + 12` días se reporta como "diferido sin cupo" y su demurrage se cuenta solo hasta ese día. Esto abarata artificialmente diferir. Con el Tracking 3nd Data aparece como máximo uno.
- **Ubicación del contenedor.** El modelo supone que todo contenedor con ETA anterior al día 0 y sin EM real sigue en puerto. Si un Tracking futuro trae contenedores ya en Suppla sin EM real, el demurrage se sobrestimaría.
- **IDs sin Tracking.** Cerca de 387 IDs de DIEL y Prioridades no están en el Tracking; la hoja "No están en Tracking" del Excel los lista. Su formato no se ha revisado.
- **Costo de Suppla.** Es un supuesto: 1.049,17 USD por mes por contenedor de 40 pies, prorrateado a 30 días (34,97 USD por día).
