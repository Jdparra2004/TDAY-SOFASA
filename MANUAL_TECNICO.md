# Manual Tecnico y de Instalacion - Optimizador Renault-Sofasa CKD

Este manual detalla los pasos para la instalacion local, configuracion de entorno, explicacion de librerias, visualizacion de fechas calendario y ejecucion de pruebas y de la interfaz de usuario simplificada del sistema de gestion y optimizacion de cadena de suministro CKD para Renault-Sofasa.

---

## 1. Requisitos Previos

- **Python**: Version 3.9 o superior instalada en el sistema.
- **Entorno operativo**: Compatible con Windows, Linux y macOS.
- **Gestor de paquetes**: `pip` (incluido por defecto con Python).

---

## 2. Instalacion y Clonacion del Proyecto

1. Clone o descargue el repositorio en su maquina local.
2. Abra una terminal en la raiz del proyecto:

```bash
cd ruta/al/proyecto/sofasa_supply_chain_v1_2
```

3. Cree un entorno virtual de Python y activelo:

```bash
# En Windows (PowerShell)
python -m venv venv
venv\Scripts\Activate.ps1

# En Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

---

## 3. Instalacion de Dependencias (`requirements.txt`)

Con el entorno virtual activado, instale todas las librerias requeridas ejecutando:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Librerias Utilizadas y su Propósito

- **`pandas`**: Manipulacion, limpieza, depuracion y estructuracion de tablas de datos tabulares (Excels de Tracking, Programacion DIEL y Prioridades CKD).
- **`numpy`**: Operaciones vectorizadas y calculos numericos eficientes.
- **`matplotlib`**: Generacion de graficas estandarizadas de distribuciones de lead time y mapas de movimiento de contenedores.
- **`streamlit`**: Desarrollo de la interfaz web interactiva con navegacion por pestanas, flujos por lote y modo manual corporativo (sin emojis).
- **`simpy`**: Motor de simulacion de eventos discretos para modelar la linea base (heuristica As-Is) y el comportamiento estocastico en puerto y plantas.
- **`ortools`** (Google OR-Tools CP-SAT): Solver matematico de programacion entera por restricciones para determinar el plan prescriptivo optimo (rutas directas vs. Suppla Rionegro y fechas de entrada a planta EM).
- **`openpyxl`**: Motor para lectura y escritura de archivos de Excel (`.xlsx`, `.xlsm`).

---

## 4. Parametros Operativos Simplificados y Fechas Calendario

La aplicacion ha sido optimizada para reflejar la operacion real del planificador:
1. **Fechas Calendario:** Todas las fechas mostradas en tablas, KPIs, inspectores y recomendaciones operativas se presentan en formato de fecha calendario (`YYYY-MM-DD`), tomando como dia base la fecha de ejecucion actual (hoy), facilitando la programacion a 30 o mas dias. Internamente, el sistema procesa los calculos en dias numéricos para el solver.
2. **Capacidades Operativas Reales:** Se han omitido los campos abstractos de inventario inicial, capacidad en uso y tasa de consumo diario. El operador unicamente configura:
   - **Bodega Suppla (Rionegro):** Capacidad semanal de recepcion y capacidad diaria de traslado hacia planta, seleccionando los dias de la semana habilitados.
   - **Fabrica SOFASA:** Capacidad maxima de recepcion diaria de contenedores en planta.

---

## 5. Ejecucion de Pruebas de Regresion Locales

Para verificar que el pipeline de datos, simulacion y optimizacion funciona correctamente frente a los datos reales:

```bash
python tests/test_regresion.py
```

El script validara de forma automatizada:
- Carga de los contenedores reales del dataset.
- Verificacion de variables en DIEL y Prioridades.
- Ejecucion exitosa de SimPy y OR-Tools CP-SAT.

---

## 6. Ejecucion del Script por Lotes (Batch)

Para ejecutar el pipeline completo de punta a punta por consola generando reportes y graficos en la carpeta `output/`:

```bash
python main.py
```

---

## 7. Ejecucion de la Interfaz Web (Streamlit)

Para levantar la aplicacion web interactiva localmente:

```bash
streamlit run app.py
```

La aplicacion abrira automaticamente en su navegador web predeterminado (por defecto en `http://localhost:8501`), permitiendo cargar archivos de Excel, configurar capacidades de Suppla y Sofasa, visualizar fechas calendario y exportar el plan prescriptivo en CSV.
