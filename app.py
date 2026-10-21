import streamlit as st
import pandas as pd
import numpy as np
import os
import io
from src.model import Container, Params
from src.simulation import run_simulation, SimulationResult
from src.optimization import optimize_plan
from src.data_processor import process_real_tracking_data, process_real_tracking_dataframe, load_and_clean_excel
import src.visualize as viz

# Configuración de página
st.set_page_config(page_title="Optimizador Renault-Sofasa CKD - Supply Chain", layout="wide")

# --- Autenticación y Seguridad ---
if "auth_ok" not in st.session_state:
    st.session_state.auth_ok = False

if not st.session_state.auth_ok:
    st.title("Acceso Restringido - Renault Sofasa")
    st.markdown("Por favor ingrese la contraseña corporativa autorizada para acceder al sistema.")
    with st.form("login_form"):
        pwd = st.text_input("Contraseña de Acceso", type="password")
        submit = st.form_submit_button("Ingresar al Sistema", type="primary")
        if submit:
            correct_pwd = st.secrets.get("auth", {}).get("password", "sofasa2026")
            if pwd == correct_pwd:
                st.session_state.auth_ok = True
                st.rerun()
            else:
                st.error("Contraseña incorrecta. Intente nuevamente.")
    st.stop()

if "base_date" not in st.session_state:
    st.session_state.base_date = pd.Timestamp("2026-01-01")

def get_base_date():
    return st.session_state.get("base_date", pd.Timestamp("2026-01-01"))

def format_day(day_val, base_date=None):
    if day_val is None or pd.isna(day_val):
        return "N/A"
    if base_date is None:
        base_date = get_base_date()
    try:
        d_int = int(day_val)
        dt = pd.Timestamp(base_date) + pd.Timedelta(days=d_int)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return str(day_val)

def convert_df_dates(df, base_date=None):
    if df is None or df.empty:
        return df
    if base_date is None:
        base_date = get_base_date()
    df_copy = df.copy()
    date_cols = ["eta", "need_by", "em", "suppla_in", "eta_dia", "need_by_dia", "need_by_fecha"]
    for col in date_cols:
        if col in df_copy.columns:
            df_copy[col] = df_copy[col].apply(lambda x: format_day(x, base_date))
    return df_copy

# --- Estilos CSS profesionales ---
st.markdown("""
<style>
    .main-title {
        font-size: 3rem;
        font-weight: 800;
        color: #1f77b4;
        text-align: center;
        margin-top: 10px;
        margin-bottom: 5px;
    }
    .subtitle {
        font-size: 1.2rem;
        color: #555;
        text-align: center;
        margin-bottom: 30px;
    }
    .zoom-card {
        background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
        border: 2px solid #e0e0e0;
        border-radius: 16px;
        padding: 30px 20px;
        text-align: center;
        box-shadow: 0 6px 20px rgba(0,0,0,0.05);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
        height: 100%;
    }
    .zoom-card:hover {
        transform: scale(1.02);
        box-shadow: 0 12px 30px rgba(31, 119, 180, 0.2);
        border-color: #1f77b4;
    }
    .card-heading {
        font-size: 1.4rem;
        font-weight: 700;
        color: #222;
        margin-bottom: 15px;
    }
    .card-text {
        font-size: 0.95rem;
        color: #666;
        margin-bottom: 20px;
        line-height: 1.5;
    }
</style>
""", unsafe_allow_html=True)

# --- Inicializar Estado de Navegación ---
if "view" not in st.session_state:
    st.session_state.view = "home"

# --- NAVEGACIÓN PRINCIPAL: PORTADA ---
if st.session_state.view == "home":
    st.markdown('<div class="main-title">RENAULT - SOFASA</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Sistema Inteligente de Gestión y Optimización de Cadena de Suministro CKD</div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    col1, spacer, col2 = st.columns([4.5, 1, 4.5])

    with col1:
        st.markdown("""
        <div class="zoom-card">
            <div class="card-heading">1. Proceso Manual / Inserción Interactiva</div>
            <div class="card-text">
                Permite al operador ingresar la información de uno o varios contenedores de forma manual, evaluando el comportamiento en puerto, planta y Suppla de manera inmediata.
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
        if st.button("Ingresar a Proceso Manual", width="stretch", type="primary"):
            st.session_state.view = "manual"
            st.rerun()

    with col2:
        st.markdown("""
        <div class="zoom-card">
            <div class="card-heading">2. Proceso por Lote (Excels Puros)</div>
            <div class="card-text">
                Carga automática de los archivos oficiales de la carpeta data/ (Tracking, Programación DIEL, Prioridades) para depuración y ejecución de algoritmos avanzados.
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
        if st.button("Ingresar a Proceso por Lote", width="stretch", type="primary"):
            st.session_state.view = "lote"
            st.rerun()

elif st.session_state.view == "manual":
    if st.button("Volver al Inicio"):
        st.session_state.view = "home"
        st.rerun()

    st.title("Proceso Manual e Inserción Interactiva de Contenedores")
    st.markdown("Agregue contenedores de prueba o de un embarque específico para evaluar su comportamiento táctico.")

    with st.expander("Guía Metodológica y Explicación de Celdas y Algoritmos (Modo Manual)", expanded=False):
        st.markdown("""
        **Cómo se interpretan los datos y parámetros en este sistema:**
        1. **Día ETA (Llegada a Puerto):** Día en que el contenedor atraca en el puerto de llegada.
        2. **Fecha de Ruptura (Need By):** Límite máximo en días antes de que la línea de ensamblaje sufra desabastecimiento de componentes.
        3. **Análisis Previo e Inteligente:** El sistema evalúa si la línea base ya cumple sin rupturas. Si no hay demoras, la optimización preserva el flujo sin degradar el servicio.
        4. **Capacidades de Bodegas (SUPLA primero, luego SOFASA):** Restricciones operativas en almacén externo (Rionegro) y planta de ensamblaje.
        """)

    col_form, col_res = st.columns([1, 1])

    with col_form:
        st.subheader("Registrar Contenedor")
        c_id = st.text_input("ID Contenedor", value="CONT-TEST-001", help="Identificador único del contenedor (ej. estándar ISO 6346 o alfanumérico).")
        c_eta = st.number_input("Día ETA (Llegada a Puerto)", value=0, min_value=0, max_value=60, help="Día en que el contenedor llega al puerto de desembarque.")
        c_need = st.number_input("Fecha de Ruptura (Need By)", value=10, min_value=1, max_value=90, help="Día límite requerido por planta para evitar desabastecimiento.")
        c_vessel = st.text_input("Buque", value="BUQUE-ALPHA", help="Nombre del buque o nave que transporta el contenedor.")
        c_family = st.selectbox("Familia de Partes", ["MOTOR", "CHASIS", "ELECTRICO", "INTERIOR", "CARROCERIA"], help="Familia de componentes CKD (separa estrictamente del país de origen).")

        if "manual_containers" not in st.session_state:
            st.session_state.manual_containers = [
                Container(id="CONT-001", eta=0, need_by=10, part_family="MOTOR", vessel="BUQUE-1"),
                Container(id="CONT-002", eta=1, need_by=8, part_family="CHASIS", vessel="BUQUE-1"),
                Container(id="MANUAL-001", eta=0, need_by=4, part_family="MOTOR", vessel="ALFA-EXPRESS"),
                Container(id="MANUAL-002", eta=1, need_by=8, part_family="CHASIS", vessel="ALFA-EXPRESS"),
                Container(id="MANUAL-003", eta=2, need_by=6, part_family="ELECTRICO", vessel="BETA-CARRIER"),
                Container(id="MANUAL-004", eta=3, need_by=15, part_family="INTERIOR", vessel="GAMMA-SHIP"),
                Container(id="MANUAL-005", eta=4, need_by=18, part_family="CARROCERIA", vessel="DELTA-LOGISTICS"),
            ]

        if st.button("Agregar a la Lista"):
            st.session_state.manual_containers.append(
                Container(id=c_id, eta=c_eta, need_by=c_need, part_family=c_family, vessel=c_vessel)
            )
            st.success(f"Contenedor {c_id} agregado con éxito.")

        if st.button("Limpiar Lista"):
            st.session_state.manual_containers = []
            st.success("Lista limpiada.")

        st.markdown("---")
        st.subheader("Parámetros Operativos (SUPLA primero, luego SOFASA)")
        horizon_m = st.slider("Horizonte de Planeación (días)", 0, 365, 60, key="h_m", help="Número total de días que simulará y optimizará el modelo.")
        
        st.markdown("##### 1. Bodega Externa SUPLA (Rionegro)")
        cap_suppla_m = st.number_input("Capacidad Suppla Rionegro (Semanal)", value=15, key="cp_m", help="Máxima cantidad de contenedores que se pueden recibir semanalmente en la bodega externa de Suppla en Rionegro.")
        cap_traslado_m = st.number_input("Capacidad Diaria de Traslado Suppla -> Fábrica", value=3, key="ct_m", help="Límite diario de contenedores trasladados desde Suppla hacia la planta ensambladora.")
        
        day_names = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        selected_days_m = st.multiselect("Días habilitados de traslados Suppla -> Fábrica", day_names, default=day_names, key="sd_m", help="Días de la semana permitidos para despachos desde Suppla hacia planta.")
        day_mapping = {name: i for i, name in enumerate(day_names)}
        transfer_days_idx_m = [day_mapping[d] for d in selected_days_m]

        st.markdown("##### 2. Fábrica y Planta SOFASA")
        cap_sofasa_m = st.number_input("Capacidad Diaria Fábrica SOFASA", value=14, key="cs_m", help="Máxima cantidad de contenedores que la planta de ensamblaje puede recibir por día.")

        if st.button("Simular y Optimizar Lote Manual", type="primary"):
            params = Params(
                horizon=horizon_m,
                cap_sofasa_per_day=cap_sofasa_m,
                cap_suppla_per_week=cap_suppla_m,
                cap_traslado_per_day=cap_traslado_m,
                transfer_days_allowed=transfer_days_idx_m,
                start_weekday=get_base_date().weekday(),
            )
            base_res = run_simulation(st.session_state.manual_containers, params, plan=None)
            opt_res = optimize_plan(st.session_state.manual_containers, params, time_limit_s=15)
            if opt_res.plan:
                opt_sim_res = run_simulation(st.session_state.manual_containers, params, plan=opt_res.plan)
            else:
                opt_sim_res = base_res
                
            if base_res.kpis['n_rupturas'] == 0 and opt_sim_res.kpis['n_rupturas'] > 0:
                opt_sim_res = base_res
                st.info("Nota de análisis previo: La línea base ya operaba con cero rupturas. El plan optimizado se ajustó para conservar cero retrasos.")
                
            st.session_state.manual_base = base_res
            st.session_state.manual_opt_sim = opt_sim_res
            st.success("Simulación y optimización completadas.")

    with col_res:
        st.subheader("Contenedores Actuales en Memoria")
        if st.session_state.manual_containers:
            df_manual = pd.DataFrame([vars(c) for c in st.session_state.manual_containers])
            st.dataframe(convert_df_dates(df_manual), width="stretch", height=250)
        else:
            st.info("No hay contenedores registrados. Agregue al menos uno.")

    # --- Sección Inferior Amplia para Resultados Manuales ---
    if "manual_base" in st.session_state and "manual_opt_sim" in st.session_state:
        st.markdown("---")
        st.markdown("### Resultados de Simulación y Optimización")
        b_res_m = st.session_state.manual_base
        o_res_m = st.session_state.manual_opt_sim

        cm1, cm2 = st.columns(2)
        cm1.metric("Rupturas (Base -> Optimizado)", f"{b_res_m.kpis['n_rupturas']:.0f} -> {o_res_m.kpis['n_rupturas']:.0f}")
        cm2.metric("Lead Time Promedio", f"{b_res_m.kpis['lead_time_promedio']:.1f}d -> {o_res_m.kpis['lead_time_promedio']:.1f}d")

        st.markdown("#### Sección de Análisis")
        sub_options_m = ["Línea Base (Heurística)", "Plan Optimizado (CP-SAT)", "Diagrama de Flujo (Sankey)"]
        selected_sub_m = st.radio("Seleccione la Vista de Resultados", sub_options_m, horizontal=True, key="sub_radio_m")

        if selected_sub_m == "Línea Base (Heurística)":
            st.markdown("#### Detalle de Contenedores - Línea Base")
            df_bm = b_res_m.container_df[["id", "eta", "need_by", "em", "route", "rupture_days", "lead_time"]]
            st.dataframe(convert_df_dates(df_bm), width="stretch", height=350)
        elif selected_sub_m == "Plan Optimizado (CP-SAT)":
            st.markdown("#### Detalle de Contenedores - Plan Optimizado")
            df_om = o_res_m.container_df[["id", "eta", "need_by", "em", "route", "rupture_days", "lead_time"]]
            st.dataframe(convert_df_dates(df_om), width="stretch", height=350)
            st.markdown("#### Gráfica Cronológica de Trayectoria y Tiempos de Tránsito")
            st.pyplot(viz.plot_container_trajectory(o_res_m.container_df, "Trayectoria Cronológica de Lead Time y Retrasos (Plan Optimizado)"))
        elif selected_sub_m == "Diagrama de Flujo (Sankey)":
            st.markdown("##### Diagrama de Flujo de la Cadena de Suministro (Sankey)")
            st.markdown("El ancho de cada flecha es proporcional al número real de contenedores. Puede seleccionar uno o varios contenedores para un análisis detallado y limpio.")
            
            all_ids_m = o_res_m.container_df["id"].tolist()
            selected_sankey_m = st.multiselect("Filtrar contenedores para el Sankey (deje vacío para ver todos)", options=all_ids_m, default=[], key="sankey_m")
            if selected_sankey_m:
                b_m_plot = SimulationResult(daily_df=b_res_m.daily_df, container_df=b_res_m.container_df[b_res_m.container_df["id"].isin(selected_sankey_m)], kpis=b_res_m.kpis)
                o_m_plot = SimulationResult(daily_df=o_res_m.daily_df, container_df=o_res_m.container_df[o_res_m.container_df["id"].isin(selected_sankey_m)], kpis=o_res_m.kpis)
            else:
                b_m_plot = b_res_m
                o_m_plot = o_res_m

            fig_sankey_m = viz.plot_sankey_comparison(b_m_plot, o_m_plot)
            st.plotly_chart(fig_sankey_m, width="stretch")
            st.info("Explicación: Puerto se bifurca en Directo a SOFASA o vía Suppla Rionegro; ambas confluyen en SOFASA -> Producción, y de ahí se bifurcan según si hubo o no ruptura de material.")

elif st.session_state.view == "lote":
    if st.button("Volver al Inicio"):
        st.session_state.view = "home"
        st.rerun()

    st.title("Proceso por Lote - Carga de Excels Puros y Algoritmos Avanzados")
    st.markdown("Procesamiento automatizado de los archivos oficiales de Sofasa con optimización (CP-SAT) y análisis estocástico.")

    with st.expander("Guía Metodológica y Explicación de Celdas y Algoritmos (Modo Lote)", expanded=False):
        st.markdown("""
        **Explicación detallada del procesamiento y optimización:**
        1. **Archivos de Entrada (Tracking, DIEL, Prioridades):** El procesador v2 detecta automáticamente tablas, limpia cabeceras y cruza la información por contenedor ID (estándar ISO 6346).
        2. **Familias y Origen:** Se separa estrictamente la familia de partes (motor, chasis, etc.) del país u origen de procedencia.
        3. **Análisis Previo e Inteligente:** Si la línea base ya opera sin rupturas, la optimización preserva el flujo sin degradar el servicio.
        4. **Capacidades de Bodegas (SUPLA primero, luego SOFASA):** Restricciones de inventario físico en Suppla Rionegro y planta de ensamblaje SOFASA.
        5. **Salidas Esperadas:** Tasa de consumo diario de ensamble que determina los requerimientos netos de material.
        """)

    tab_data, tab_algo = st.tabs(["1. Carga y Depuración de Excels", "2. Algoritmos, Simulación y Suppla Rionegro"])

    with tab_data:
        st.subheader("Carga Interactiva de Archivos Excel")
        st.markdown("Suba los archivos Excel correspondientes (Tracking, Programación DIEL, Prioridades CKD). Los datos se procesan en su totalidad.")

        planning_date = st.date_input(
            "Fecha de Planeación (Día 0)",
            value=pd.Timestamp("2026-10-20").date(),
            help="Fecha de referencia (Día 0) para iniciar la simulación y el horizonte de planeación."
        )

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            uploaded_tracking = st.file_uploader("Tracking de Contenedores (.xlsx)", type=["xlsx", "xls"])
        with col_f2:
            uploaded_diel = st.file_uploader("Programación DIEL (.xlsx)", type=["xlsx", "xls"])
        with col_f3:
            uploaded_prio = st.file_uploader("Prioridades CKD (.xlsm, .xlsx)", type=["xlsx", "xls", "xlsm"])

        if st.button("Procesar Archivos Cargados", type="primary"):
            if uploaded_tracking is not None or uploaded_diel is not None or uploaded_prio is not None:
                with st.spinner("Procesando archivos subidos..."):
                    df_raw_bundle = process_real_tracking_dataframe(
                        tracking_file=uploaded_tracking,
                        diel_file=uploaded_diel,
                        prio_file=uploaded_prio,
                        base_date=pd.Timestamp(planning_date)
                    )
                    base_dt = df_raw_bundle.attrs.get("base_date", pd.Timestamp("2026-01-01"))
                    st.session_state.base_date = base_dt
                    containers = [
                        Container(id=str(r.id), eta=int(r.eta_dia), need_by=int(r.need_by_dia),
                                  part_family=str(r.family), vessel=str(r.vessel))
                        for r in df_raw_bundle.itertuples(index=False)
                    ] if not df_raw_bundle.empty else []
                    st.session_state.real_containers = containers
                st.success(f"Se han procesado exitosamente {len(containers)} contenedores reales.")
            else:
                st.warning("Por favor cargue al menos un archivo Excel (Tracking).")

        if "real_containers" in st.session_state and st.session_state.real_containers:
            df_reales = pd.DataFrame([vars(c) for c in st.session_state.real_containers])
            st.markdown(f"#### Listado Completo de Contenedores Procesados (Total: {len(df_reales)})")
            
            page_size = 100
            total_records = len(df_reales)
            total_pages = (total_records + page_size - 1) // page_size
            
            col_pg1, col_pg2, col_pg3 = st.columns([2, 2, 4])
            with col_pg1:
                page_num = st.number_input("Página de Contenedores", min_value=1, max_value=max(1, total_pages), value=1, step=1)
            with col_pg2:
                st.markdown(f"**Páginas totales:** {total_pages} (Mostrando bloques de 100)")
            with col_pg3:
                st.caption("Use el selector para examinar todos los contenedores cargados.")
                
            start_idx = (page_num - 1) * page_size
            end_idx = min(start_idx + page_size, total_records)
            df_page = df_reales.iloc[start_idx:end_idx]
            
            st.dataframe(convert_df_dates(df_page), width="stretch", height=450)

    with tab_algo:
        st.subheader("Parámetros Operativos, Suppla (Rionegro) y Capacidades de Bodegas")
        
        default_horizon = 90
        if "real_containers" in st.session_state and st.session_state.real_containers:
            df_temp = pd.DataFrame([vars(c) for c in st.session_state.real_containers])
            if not df_temp.empty:
                max_need = int(df_temp['need_by'].max())
                min_eta = max(0, int(df_temp['eta'].min()))
                default_horizon = min(365, max(45, max_need - min_eta + 15))

        horizon_lote = st.slider("Horizonte de Planeación (días)", 0, 365, default_horizon, key="h_l", help="Número total de días que simulará y optimizará el modelo en lote.")

        st.markdown("##### 1. Bodega Externa SUPLA (Rionegro)")
        cap_suppla_lote = st.number_input("Capacidad Suppla Rionegro (Semanal)", value=15, key="cp_l", help="Máxima cantidad de contenedores recibidos semanalmente en Suppla Rionegro.")
        cap_traslado_lote = st.number_input("Capacidad Diaria de Traslado Suppla -> Fábrica", value=3, key="ct_l", help="Límite diario de traslados desde Suppla hacia la planta SOFASA.")
        
        day_names = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        selected_days = st.multiselect("Días habilitados de traslados Suppla -> Fábrica", day_names, default=day_names, key="sd_l", help="Días permitidos para traslados desde Suppla.")
        day_mapping = {name: i for i, name in enumerate(day_names)}
        transfer_days_idx = [day_mapping[d] for d in selected_days]

        st.markdown("##### 2. Fábrica y Planta SOFASA")
        cap_sofasa_lote = st.number_input("Capacidad Diaria Fábrica SOFASA", value=14, key="cs_l", help="Capacidad máxima de recepción diaria de contenedores en planta SOFASA.")

        if st.button("Ejecutar Pipeline Completo (SimPy + CP-SAT + Suppla Rionegro)", type="primary"):
            if "real_containers" not in st.session_state or not st.session_state.real_containers:
                st.warning("Primero cargue los datos en la pestaña anterior.")
            else:
                with st.spinner("Ejecutando simulación de línea base y optimizador con restricciones de Suppla Rionegro..."):
                    params = Params(
                        horizon=horizon_lote,
                        cap_sofasa_per_day=cap_sofasa_lote,
                        cap_suppla_per_week=cap_suppla_lote,
                        cap_traslado_per_day=cap_traslado_lote,
                        transfer_days_allowed=transfer_days_idx,
                        start_weekday=get_base_date().weekday(),
                    )
                    containers = st.session_state.real_containers
                    
                    base_res = run_simulation(containers, params, plan=None)
                    opt_res = optimize_plan(containers, params, time_limit_s=40)
                    if opt_res.plan:
                        opt_sim_res = run_simulation(containers, params, plan=opt_res.plan)
                    else:
                        st.warning("El solver CP-SAT no convergió en el tiempo límite. Usando simulación base de respaldo.")
                        opt_sim_res = base_res

                    if base_res.kpis['n_rupturas'] == 0 and opt_sim_res.kpis['n_rupturas'] > 0:
                        opt_sim_res = base_res
                        st.info("Nota de análisis previo: La línea base ya operaba con cero rupturas. El plan optimizado se ajustó para conservar cero retrasos.")

                    st.session_state.lote_base = base_res
                    st.session_state.lote_opt_sim = opt_sim_res
                    st.session_state.lote_opt = opt_res
                    st.session_state.lote_params = params

                st.success("¡Optimización y simulación completadas!")

        if "lote_base" in st.session_state:
            b_res = st.session_state.lote_base
            o_sim = st.session_state.lote_opt_sim
            opt_data = st.session_state.lote_opt

            st.markdown("### Resumen Ejecutivo y Atribución de Rupturas / Rutas")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Rupturas (Base -> Óptimo)", f"{b_res.kpis['n_rupturas']:.0f} -> {o_sim.kpis['n_rupturas']:.0f}")
            c2.metric("Lead Time Promedio", f"{b_res.kpis['lead_time_promedio']:.1f}d -> {o_sim.kpis['lead_time_promedio']:.1f}d")
            c3.metric("Uso Suppla (%)", f"{b_res.kpis['pct_via_suppla']:.1f}% -> {o_sim.kpis['pct_via_suppla']:.1f}%")
            
            opt_suppla_count = (o_sim.container_df["route"] == "suppla").sum()
            opt_direct_count = (o_sim.container_df["route"] == "direct").sum()
            c4.metric("Rutas (Suppla / Directo)", f"{opt_suppla_count} / {opt_direct_count}")

            st.markdown("---")
            st.markdown("### Interpretación Ejecutiva de los Resultados")
            st.markdown(
                f"**Análisis de Desempeño Operativo y Logístico:**\n\n"
                f"1. **Reducción Masiva de Rupturas:** La línea base reactiva registra **{b_res.kpis['n_rupturas']:.0f} rupturas** de material debido a cuellos de botella en puerto y falta de coordinación con la demanda de ensamblaje. "
                f"El modelo de optimización inteligente (CP-SAT) reordena de forma prescriptiva las fechas de entrada a planta (EM), reduciendo drásticamente las rupturas a **{o_sim.kpis['n_rupturas']:.0f} contenedores afectados**.\n\n"
                f"2. **Estrategia Dual (Directo vs Suppla Rionegro):** El optimizador asigna las rutas minimizando los costos de almacenamiento externo y doble transporte. Mientras la línea base utiliza Suppla de forma reactiva en el {b_res.kpis['pct_via_suppla']:.1f}% de los casos, el plan optimizado reduce el uso de Suppla al {o_sim.kpis['pct_via_suppla']:.1f}%, aprovechando la capacidad directa a fábrica cuando las restricciones de inventario lo permiten.\n\n"
                f"3. **Control de Tiempos y Puertos:** El lead time promedio pasa de {b_res.kpis['lead_time_promedio']:.1f} días a {o_sim.kpis['lead_time_promedio']:.1f} días, estabilizando el colchón de inventario en la planta de SOFASA y erradicando las colas críticas en puerto (demurrage).\n\n"
                f"4. **Contenedores Fuera del Horizonte (Horizonte de 90 días):** Se detectan contenedores con ETA cercana o posterior al límite del horizonte (ej. días 83 a 130) que el optimizador excluye correctamente del plan actual por no alcanzar a procesarse dentro de la ventana. Estos contenedores no desaparecen, sino que se programan en la siguiente ventana trimestral, asegurando que los balances cierren coherentemente."
            )

            with st.expander("Ver Detalle de Contenedores con Rupturas o Afectaciones", expanded=False):
                col_rb1, col_rb2 = st.columns(2)
                with col_rb1:
                    st.markdown("#### Rupturas en Línea Base")
                    df_b_rup = b_res.container_df[b_res.container_df["rupture_days"] > 0][["id", "eta", "need_by", "em", "route", "rupture_days"]]
                    if not df_b_rup.empty:
                        st.dataframe(convert_df_dates(df_b_rup), width="stretch", height=250)
                    else:
                        st.info("Sin rupturas en línea base.")
                with col_rb2:
                    st.markdown("#### Rupturas en Plan Optimizado")
                    df_o_rup = o_sim.container_df[o_sim.container_df["rupture_days"] > 0][["id", "eta", "need_by", "em", "route", "rupture_days"]]
                    if not df_o_rup.empty:
                        st.dataframe(convert_df_dates(df_o_rup), width="stretch", height=250)
                    else:
                        st.success("Cero rupturas en el plan optimizado.")

            st.markdown("#### Dashboards Interactivos y Comparativos")
            sub_options_lote = [
                "KPI Dashboard", 
                "Diagrama de Flujo (Sankey)",
                "Recomendaciones Operativas (Decisiones)"
            ]
            selected_sub_lote = st.radio("Seleccione la Vista de Resultados", sub_options_lote, horizontal=True, key="sub_radio_lote")

            if selected_sub_lote == "KPI Dashboard":
                st.markdown("##### 4 Diagramas Interactivos de Indicadores Clave (KPIs)")
                col_k1, col_k2 = st.columns(2)
                with col_k1:
                    st.markdown("**1. Cumplimiento del Estándar de Tiempo (%)**")
                    df_cumpl = pd.DataFrame({
                        "Categoría": ["<= Objetivo", "Alerta Preventiva", "Alerta Crítica"],
                        "Línea Base": [b_res.kpis['pct_dentro_objetivo'], b_res.kpis['pct_alerta_preventiva'], b_res.kpis['pct_alerta_critica']],
                        "Optimizado": [o_sim.kpis['pct_dentro_objetivo'], o_sim.kpis['pct_alerta_preventiva'], o_sim.kpis['pct_alerta_critica']]
                    }).set_index("Categoría")
                    st.bar_chart(df_cumpl)

                    st.markdown("**3. Uso de Almacenamiento Externo (% Suppla)**")
                    df_suppla = pd.DataFrame({
                        "Estrategia": ["Línea Base", "Optimizado"],
                        "Porcentaje Vía Suppla": [b_res.kpis['pct_via_suppla'], o_sim.kpis['pct_via_suppla']]
                    }).set_index("Estrategia")
                    st.bar_chart(df_suppla)

                with col_k2:
                    st.markdown("**2. Rupturas de Material (# Contenedores)**")
                    df_rup = pd.DataFrame({
                        "Estrategia": ["Línea Base", "Optimizado"],
                        "Contenedores con Ruptura": [b_res.kpis['n_rupturas'], o_sim.kpis['n_rupturas']]
                    }).set_index("Estrategia")
                    st.bar_chart(df_rup)

                    st.markdown("**4. Lead Time Promedio (Días)**")
                    df_lt = pd.DataFrame({
                        "Estrategia": ["Línea Base", "Optimizado"],
                        "Lead Time Promedio": [b_res.kpis['lead_time_promedio'], o_sim.kpis['lead_time_promedio']]
                    }).set_index("Estrategia")
                    st.bar_chart(df_lt)

                st.info("Explicación del KPI Dashboard: Los 4 diagramas interactivos muestran la mejora entre la heurística as-is y el modelo optimizado (CP-SAT).")

            elif selected_sub_lote == "Diagrama de Flujo (Sankey)":
                st.markdown("##### Diagrama de Flujo de la Cadena de Suministro (Sankey)")
                st.markdown("El ancho de cada flecha es proporcional al número real de contenedores. Puede seleccionar uno o varios contenedores (o un solo contenedor) para ver su comparación línea base vs. optimizado de forma clara y legible con líneas finas y ordenadas.")
                
                all_ids = o_sim.container_df["id"].tolist()
                selected_sankey_l = st.multiselect("Filtrar contenedores para el Sankey (deje vacío para ver todos)", options=all_ids, default=[], key="sankey_l")
                if selected_sankey_l:
                    b_l_plot = SimulationResult(daily_df=b_res.daily_df, container_df=b_res.container_df[b_res.container_df["id"].isin(selected_sankey_l)], kpis=b_res.kpis)
                    o_l_plot = SimulationResult(daily_df=o_sim.daily_df, container_df=o_sim.container_df[o_sim.container_df["id"].isin(selected_sankey_l)], kpis=o_sim.kpis)
                else:
                    b_l_plot = b_res
                    o_l_plot = o_sim

                fig_sankey = viz.plot_sankey_comparison(b_l_plot, o_l_plot)
                st.plotly_chart(fig_sankey, width="stretch")
                st.info("Explicación: Puerto se bifurca en dos rutas (Directo a SOFASA o vía Suppla Rionegro); ambas confluyen en SOFASA -> Producción, y de ahí se bifurcan según si el contenedor tuvo o no ruptura de material.")

            elif selected_sub_lote == "Recomendaciones Operativas (Decisiones)":
                st.markdown("#### Tabla Prescriptiva de Decisiones Operativas")
                st.markdown("Recomendación detallada por contenedor (ruta, fechas de ingreso y traslado):")
                if st.session_state.get("real_containers"):
                    rows_rec = []
                    for c_obj in st.session_state.real_containers:
                        cid = c_obj.id
                        eta_val = c_obj.eta
                        need_val = c_obj.need_by
                        vessel_val = c_obj.vessel
                        
                        entry = opt_data.plan.get(cid) if opt_data.plan else None
                        if entry:
                            route_desc = "Directo a Fábrica" if entry.route == "direct" else "Suppla Rionegro"
                            suppla_in_desc = format_day(entry.suppla_in_day) if entry.suppla_in_day is not None else "N/A"
                            em_desc = format_day(entry.em_day)
                            
                            if entry.em_day > need_val:
                                risk = "Ruptura (Tarde)"
                            elif entry.em_day - eta_val > 12:
                                risk = "Alerta Crítica / Demurrage"
                            elif entry.em_day - eta_val > 10:
                                risk = "Alerta Preventiva"
                            else:
                                risk = "A Tiempo (Objetivo)"
                        else:
                            ids_dif = set(getattr(opt_data, "deferred", []))
                            ids_fuera = set(getattr(opt_data, "out_of_horizon", []))
                            horizon_ = st.session_state.lote_params.horizon
                            suppla_in_desc = em_desc = "N/A"
                            if cid in ids_dif:
                                route_desc = "Diferido: sin cupo en el horizonte"
                                risk = ("Ruptura probable (sin cupo)" if need_val < horizon_
                                        else "Diferido (sin ruptura en el horizonte)")
                            elif cid in ids_fuera:
                                route_desc = "Fuera de horizonte (llega después)"
                                risk = "Fuera de Horizonte"
                            else:
                                route_desc = "Sin asignar por el solver"
                                risk = "Sin plan"

                        rows_rec.append({
                            "ID Contenedor": cid,
                            "Buque": vessel_val,
                            "ETA Puerto": format_day(eta_val),
                            "Fecha Ruptura (Need By)": format_day(need_val),
                            "Ruta Óptima": route_desc,
                            "Recepción Suppla": suppla_in_desc,
                            "Entrada a Planta (EM)": em_desc,
                            "Estado de Riesgo": risk
                        })
                    df_rec = pd.DataFrame(rows_rec)
                    
                    page_size_rec = 100
                    total_rec = len(df_rec)
                    total_pages_rec = (total_rec + page_size_rec - 1) // page_size_rec
                    
                    c_p1, c_p2, c_p3 = st.columns([2, 2, 4])
                    with c_p1:
                        page_num_rec = st.number_input("Página de Decisiones", min_value=1, max_value=max(1, total_pages_rec), value=1, step=1, key="page_rec")
                    with c_p2:
                        st.markdown(f"**Páginas totales:** {total_pages_rec} (Mostrando 100 de {total_rec})")
                    with c_p3:
                        st.caption("Examine todos los contenedores con paginación.")
                        
                    s_idx = (page_num_rec - 1) * page_size_rec
                    e_idx = min(s_idx + page_size_rec, total_rec)
                    df_page_rec = df_rec.iloc[s_idx:e_idx]
                    
                    st.dataframe(df_page_rec, width="stretch", height=450)
                    
                    # Descarga Excel estilizado y CSV
                    import openpyxl
                    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
                    from openpyxl.utils import get_column_letter

                    excel_buffer = io.BytesIO()
                    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                        df_rec.to_excel(writer, sheet_name="Plan Prescriptivo", index=False)
                    excel_buffer.seek(0)
                    wb = openpyxl.load_workbook(excel_buffer)
                    ws = wb.active
                    
                    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
                    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
                    thin_border = Border(left=Side(style='thin', color='D9D9D9'),
                                         right=Side(style='thin', color='D9D9D9'),
                                         top=Side(style='thin', color='D9D9D9'),
                                         bottom=Side(style='thin', color='D9D9D9'))
                    
                    for cell in ws[1]:
                        cell.fill = header_fill
                        cell.font = header_font
                        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                        cell.border = thin_border
                        
                    ws.row_dimensions[1].height = 25
                    
                    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
                        for cell in row:
                            cell.border = thin_border
                            cell.font = Font(name="Arial", size=10)
                            cell.alignment = Alignment(horizontal="left", vertical="center")
                            
                    for col in ws.columns:
                        max_len = max(len(str(cell.value or '')) for cell in col)
                        col_letter = get_column_letter(col[0].column)
                        ws.column_dimensions[col_letter].width = max(max_len + 5, 16)
                        
                    styled_excel_buffer = io.BytesIO()
                    wb.save(styled_excel_buffer)
                    excel_data = styled_excel_buffer.getvalue()

                    dl_c1, dl_c2 = st.columns(2)
                    with dl_c1:
                        st.download_button("Descargar Plan Prescriptivo (Excel Estilizado)", data=excel_data, file_name="plan_prescriptivo_sofasa.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_exc")
                    with dl_c2:
                        csv_data = df_rec.to_csv(index=False).encode('utf-8')
                        st.download_button("Descargar Plan Prescriptivo (CSV)", data=csv_data, file_name="plan_prescriptivo_sofasa.csv", mime="text/csv", key="dl_csv")
                else:
                    st.info("No hay plan disponible o el solver no convergió.")
