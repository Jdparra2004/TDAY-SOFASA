import dataclasses
import io
import os
import tempfile

import pandas as pd
import streamlit as st

import src.visualize as viz
from src.data_processor import to_display_df
from src.export import build_programacion, export_prescriptive_plan
from src.glossary import get_glossary
from src.pipeline import build_params, prepare_universe, run_pipeline, print_validaciones

# NOTA: app.py NO contiene lógica de optimización, simulación ni costos: solo llama a src/pipeline.py.

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
            try:
                correct_pwd = st.secrets["auth"]["password"]
            except (KeyError, FileNotFoundError, AttributeError):
                st.error("Configuración de autenticación faltante en secrets.toml. Acceso bloqueado.")
                st.stop()
            if pwd == correct_pwd:
                st.session_state.auth_ok = True
                st.rerun()
            else:
                st.error("Contraseña incorrecta. Intente nuevamente.")
    st.stop()

DAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DEFAULT_PLANNING_DATE = pd.Timestamp("2026-10-20").date()
PAGE_SIZE = 100

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



# =============================================================================
# COMPONENTES COMPARTIDOS (los usan el modo lote y el modo manual por igual)
# =============================================================================
def render_params_panel(prefix: str):
    """EXACTAMENTE los 6 parámetros del usuario. Mismos controles, defaults y ayudas en lote y manual."""
    st.subheader("Parámetros de planeación")
    fecha = st.date_input("Fecha de planeación (día 0)", value=DEFAULT_PLANNING_DATE, key=f"{prefix}_fecha",
                          help="Día 0 del horizonte. También fija el día de la semana con el que arranca el calendario.")
    horizonte = st.slider("Horizonte (días)", 1, 365, 20, key=f"{prefix}_hor",
                          help="Entran los contenedores con ETA entre el día 0 y el último día del horizonte.")
    c1, c2 = st.columns(2)
    cap_sofasa = c1.number_input("Capacidad SOFASA por día", min_value=1, value=14, key=f"{prefix}_cs",
                                 help="Máximo de contenedores que entran a planta por día.")
    cap_suppla = c2.number_input("Capacidad Suppla por semana", min_value=0, value=15, key=f"{prefix}_cp",
                                 help="Máximo de contenedores que se reciben por semana calendario en Suppla.")
    cap_tras = c1.number_input("Capacidad de traslado por día", min_value=0, value=2, key=f"{prefix}_ct",
                               help="Máximo de contenedores trasladados de Suppla a SOFASA por día.")
    dias = st.multiselect("Días habilitados de traslado", DAY_NAMES, default=DAY_NAMES[:5], key=f"{prefix}_dias",
                          help="Días de la semana en que se permite el traslado Suppla -> SOFASA.")
    return build_params(fecha, horizonte, cap_sofasa, cap_suppla, cap_tras, [DAY_NAMES.index(d) for d in dias])


def render_guia_rapida(params):
    with st.expander("Guía rápida y glosario de términos", expanded=False):
        glossary = get_glossary(params)
        for termino, definicion, opciones in glossary:
            st.markdown(f"**{termino}**")
            st.caption(definicion)
            if opciones:
                df_op = pd.DataFrame(opciones, columns=["Valor / Opción", "Significado"])
                st.dataframe(df_op, width="stretch", hide_index=True)
            st.markdown("---")


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.attrs = {}
    return out


def _csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def _paginated(df: pd.DataFrame, key: str, height: int = 420):
    total = len(df)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    c1, c2 = st.columns([2, 6])
    page = c1.number_input("Página", min_value=1, max_value=pages, value=1, step=1, key=f"pg_{key}")
    c2.markdown(f"**{total}** filas · página {page} de {pages} (bloques de {PAGE_SIZE})")
    st.dataframe(_clean(df.iloc[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]), width="stretch", height=height)


def render_listado(df_universo: pd.DataFrame, key: str):
    st.markdown("#### Listado del universo")
    _paginated(to_display_df(df_universo), key)


def render_indicadores_universo(df_universo: pd.DataFrame, key: str):
    st.markdown("### Universo de contenedores")
    e = df_universo.attrs.get("embudo", {})
    a = df_universo.attrs
    c = st.columns(5)
    c[0].metric("Tracking", e.get("tracking_total", 0))
    c[1].metric("Excluidos (EM real < día 0)", e.get("excluidos", 0))
    c[2].metric("Fuera de ventana", e.get("fuera_ventana", 0))
    c[3].metric("Programables", e.get("programables", 0))
    c[4].metric("Con ruptura real / sin", f"{e.get('programables_con_ruptura_real', 0)} / {e.get('programables_sin_ruptura', 0)}")

    prog = df_universo[df_universo["estado_universo"] == "PROGRAMABLE"]
    n = max(1, len(prog))

    def pct(col):
        if col not in prog.columns:
            return 0.0
        s = prog[col]
        return 100 * (s.notna() & ~s.astype(str).isin(["", "nan", "NaT", "<NA>", "GEN", "BUQUE_GEN", "N/D"])).sum() / n

    st.caption(f"Cobertura de datos en programables: Origen {pct('sourcing'):.0f}% · ETD {pct('etd'):.0f}% · "
               f"EM previa {pct('fecha_em_prog'):.0f}% · ruptura real {100 * e.get('programables_con_ruptura_real', 0) / n:.0f}%")
    with st.expander("Detalle y descargas por bloque (con motivo)"):
        bloques = {
            "Excluidos (ya en planta)": a.get("excluded_df"),
            "Fuera de ventana (se programa en la siguiente planeación)": a.get("fuera_ventana_df"),
            "IDs de DIEL/Prioridades que no están en el Tracking": a.get("no_tracking_df"),
        }
        for i, (titulo, d) in enumerate(bloques.items()):
            st.markdown(f"**{titulo}: {0 if d is None else len(d)}**")
            if d is not None and len(d):
                cols = [x for x in ("id", "eta", "em", "fuente", "motivo_estado") if x in d.columns]
                st.dataframe(_clean(d[cols]), width="stretch", height=200)
                st.download_button("Descargar CSV", _csv_bytes(d[cols]), file_name=f"{titulo[:12].strip()}.csv".replace(" ", "_"),
                                   mime="text/csv", key=f"dl_u_{key}_{i}")


def render_indicadores_resultado(res):
    st.markdown("### Resultado: línea base vs. plan optimizado")
    b, o = res.base.kpis, res.optimo.kpis
    st.caption("Rupturas: solo cuentan los contenedores con fecha real de ruptura (Prioridades/DIEL).")
    stt = res.solver.status
    gap_txt = "N/D" if pd.isna(res.solver.gap) else f"{res.solver.gap:.1%}"
    if stt == "OPTIMAL":
        st.success(f"Solver OPTIMAL (gap {gap_txt}).")
    elif stt == "FEASIBLE":
        st.warning(f"Solver FEASIBLE: plan válido pero no probado óptimo (gap {gap_txt} al cerrar el tiempo límite). "
                   "Las cifras de costo y rupturas pueden variar entre ejecuciones; no usarlas como cifra oficial.")
    elif stt == "FALLBACK_LINEA_BASE":
        st.warning("El solver no encontró un plan mejor que la línea base según el objetivo ponderado; "
                   "se muestra la línea base como plan optimizado.")
    else:
        st.error(f"Estado del solver: {stt}. No se obtuvo un plan; revise los datos y parámetros.")
    rows = []
    for bloque, pref in (("Dentro del horizonte", "hor_"), ("EM proyectada (fuera del horizonte)", "proj_")):
        for etiqueta, k, fmt in (("Contenedores", "n_containers", "{:.0f}"), ("% ≤ objetivo", "pct_dentro_objetivo", "{:.1f}"),
                                 ("% > máximo", "pct_alerta_critica", "{:.1f}"), ("Rupturas", "n_rupturas", "{:.0f}"),
                                 ("Lead time promedio", "lead_time_promedio", "{:.1f}")):
            rows.append({"Bloque": bloque, "Indicador": etiqueta,
                         "Línea base": fmt.format(b.get(pref + k, float("nan"))), "Plan optimizado": fmt.format(o.get(pref + k, float("nan")))})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    c = st.columns(4)
    c[0].metric("Rupturas (base → óptimo)", f"{b['n_rupturas']:.0f} → {o['n_rupturas']:.0f}")
    c[1].metric("% > máximo (base → óptimo)", f"{b['pct_alerta_critica']:.1f}% → {o['pct_alerta_critica']:.1f}%")
    c[2].metric("Vía Suppla (base → óptimo)", f"{b['pct_via_suppla']:.1f}% → {o['pct_via_suppla']:.1f}%")
    c[3].metric("Diferidos sin cupo", f"{b['n_diferidos']:.0f} → {o['n_diferidos']:.0f}")
    cap = []
    for nombre, u in res.uso_capacidad.items():
        cap.append({"Plan": "Línea base" if nombre == "base" else "Plan optimizado",
                    "SOFASA (máx/cap por día)": f"{u['sofasa_max']} / {u['sofasa_cap']:.0f}",
                    "Suppla (máx/cap por semana)": f"{u['suppla_semana_max']} / {u['suppla_semana_cap']:.0f}",
                    "Traslados (máx/cap por día)": f"{u['traslado_max']} / {u['traslado_cap']:.0f}"})
    st.markdown("**Capacidad máxima usada vs. capacidad**")
    st.dataframe(pd.DataFrame(cap), width="stretch", hide_index=True)


def render_impacto_economico(res):
    st.markdown("### Impacto económico (indicador)")
    cb, co = res.costos_base.totals, res.costos_opt.totals
    p = res.params
    c = st.columns(3)
    c[0].metric("Costo línea base (USD)", f"{cb['usd_total']:,.0f}")
    c[1].metric("Costo plan optimizado (USD)", f"{co['usd_total']:,.0f}")
    c[2].metric("Diferencia en demurrage + Suppla (USD)", f"{res.ahorro_usd:,.0f}", delta=f"{res.ahorro_usd:,.0f}",
        help="Base menos óptimo. Mide solo USD de demurrage y Suppla; no es el beneficio total del plan.")
    e = st.columns(4)
    e[0].metric("Previo al día 0 (inevitable, USD)", f"{res.costos_base.acumulado_previo_usd:,.0f}")
    e[1].metric("Costo evitable base (USD)", f"{res.costo_evitable_base:,.0f}")
    e[2].metric("Costo evitable óptimo (USD)", f"{res.costo_evitable_opt:,.0f}")
    e[3].metric("Rupturas evitadas", f"{res.rupturas_evitadas}", help="Contenedores con ruptura real en la base menos los del plan optimizado.")
    if res.ahorro_usd < 0 and res.rupturas_evitadas > 0:
        st.info("El plan prioriza evitar rupturas sobre el costo en USD (orden de prioridad del PDF). "
                f"Costo neto: {res.costo_por_ruptura_evitada:,.0f} USD por ruptura evitada.")

    prom_dias_b = cb["dias_suppla"] / cb["n_via_suppla"] if cb["n_via_suppla"] > 0 else 0.0
    prom_dias_o = co["dias_suppla"] / co["n_via_suppla"] if co["n_via_suppla"] > 0 else 0.0

    def _f(v, d=0):
        return f"{v:,.{d}f}"

    desg = pd.DataFrame({
        "Concepto": ["Demurrage (días)", "Demurrage (USD)", "Contenedores vía Suppla (n)", "Almacenamiento Suppla (días / contenedor-días)", "Almacenamiento Suppla (USD)", "Días promedio en Suppla por contenedor", "Total (USD)"],
        "Línea base": [_f(cb["dias_demurrage"]), _f(cb["usd_demurrage"]), _f(cb["n_via_suppla"]), _f(cb["dias_suppla"]), _f(cb["usd_suppla"]), _f(prom_dias_b, 1), _f(cb["usd_total"])],
        "Plan optimizado": [_f(co["dias_demurrage"]), _f(co["usd_demurrage"]), _f(co["n_via_suppla"]), _f(co["dias_suppla"]), _f(co["usd_suppla"]), _f(prom_dias_o, 1), _f(co["usd_total"])],
    })
    st.dataframe(desg, width="stretch", hide_index=True)
    st.caption(f"Demurrage ya acumulado antes del día 0 (inevitable): {res.costos_base.acumulado_previo_dias} días "
               f"= {res.costos_base.acumulado_previo_usd:,.0f} USD. El ahorro es contra la línea base simulada, no contra el gasto histórico real. "
               f"Almacenamiento Suppla = {p.USD_SUPPLA_MES_40FT:,.2f} USD/mes por contenedor de 40 pies, prorrateado por día (supuesto).")


def _excel_bytes(res) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        path = export_prescriptive_plan(res, os.path.join(tmp, "plan_prescriptivo_sofasa.xlsx"))
        with open(path, "rb") as f:
            return f.read()


def _sub(sim, ids):
    return dataclasses.replace(sim, container_df=sim.container_df[sim.container_df["id"].isin(ids)]) if ids else sim


def render_resultados(res, key: str):
    n_proj = int((res.estados["estado_optimo"] == "EM_PROYECTADA").sum())
    if n_proj:
        st.info(f"{n_proj} contenedores llegan dentro del horizonte pero entran después; se muestran con EM proyectada.")
    render_indicadores_universo(res.df_universo, key)
    st.markdown("---")
    render_indicadores_resultado(res)
    st.markdown("---")
    render_impacto_economico(res)
    st.markdown("---")
    vista = st.radio("Vista de resultados", ["Decisiones por contenedor", "KPI Dashboard", "Diagrama de flujo (Sankey)"],
                     horizontal=True, key=f"radio_{key}")
    b, o = res.base, res.optimo
    if vista == "Decisiones por contenedor":
        prog = build_programacion(res)
        _paginated(prog, f"dec_{key}")
        d1, d2 = st.columns(2)
        d1.download_button("Descargar plan prescriptivo (.xlsx)", _excel_bytes(res), file_name="plan_prescriptivo_sofasa.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"dl_x_{key}")
        d2.download_button("Descargar plan prescriptivo (.csv)", _csv_bytes(prog), file_name="plan_prescriptivo_sofasa.csv",
                           mime="text/csv", key=f"dl_c_{key}")
    elif vista == "KPI Dashboard":
        k1, k2 = st.columns(2)
        k1.markdown("**Cumplimiento del estándar de tiempo (%)**")
        k1.bar_chart(pd.DataFrame({"Línea base": [b.kpis["pct_dentro_objetivo"], b.kpis["pct_alerta_preventiva"], b.kpis["pct_alerta_critica"]],
                                   "Optimizado": [o.kpis["pct_dentro_objetivo"], o.kpis["pct_alerta_preventiva"], o.kpis["pct_alerta_critica"]]},
                                  index=["≤ objetivo", "Alerta preventiva", "Alerta crítica"]))
        k2.markdown("**Rupturas (solo ruptura real)**")
        k2.bar_chart(pd.DataFrame({"Contenedores con ruptura": [b.kpis["n_rupturas"], o.kpis["n_rupturas"]]}, index=["Línea base", "Optimizado"]))
        k1.markdown("**% vía Suppla**")
        k1.bar_chart(pd.DataFrame({"% vía Suppla": [b.kpis["pct_via_suppla"], o.kpis["pct_via_suppla"]]}, index=["Línea base", "Optimizado"]))
        k2.markdown("**Costo en USD (indicador)**")
        k2.bar_chart(pd.DataFrame({"USD": [res.costos_base.totals["usd_total"], res.costos_opt.totals["usd_total"]]}, index=["Línea base", "Optimizado"]))
        st.pyplot(viz.plot_suppla_occupancy(b.daily_df, o.daily_df))
    elif vista == "Diagrama de flujo (Sankey)":
        ids = st.multiselect("Filtrar contenedores (vacío = todos)", options=o.container_df["id"].tolist(), key=f"sk_{key}")
        st.plotly_chart(viz.plot_sankey_comparison(_sub(b, ids), _sub(o, ids)), width="stretch")
        st.info("Puerto se bifurca en Directo a SOFASA o vía Suppla; ambas confluyen en SOFASA → Producción, y de ahí según haya o no ruptura de material.")


def _run_and_store(fuente, params, key: str, df_prev=None):
    with st.spinner("Clasificando universo, simulando la línea base y optimizando (CP-SAT)..."):
        programables, df_universo = prepare_universe(fuente, params)
        if not programables:
            st.warning("No hay contenedores programables con estos datos y parámetros.")
            st.session_state.pop(f"res_{key}", None)
            return
        res = run_pipeline(programables, params, df_universo, workers=4)
        print_validaciones(res)
        st.session_state[f"res_{key}"] = res
    st.success("Pipeline completado.")


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
                Carga de los archivos oficiales (Tracking, Programación DIEL, Prioridades) para depuración, optimización y simulación.
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
    st.markdown("Mismo flujo que el proceso por lote, con pocos contenedores ingresados a mano.")
    params_m = render_params_panel("manual")
    render_guia_rapida(params_m)

    col_form, col_list = st.columns([1, 1])
    with col_form:
        st.markdown("---")
        st.subheader("Registrar contenedor")
        plan_d = pd.Timestamp(params_m.planning_date)
        c_id = st.text_input("ID contenedor", value="CONT-TEST-001", key="m_id")
        c_vessel = st.text_input("Buque", value="BUQUE-ALPHA", key="m_vessel")
        c_family = st.selectbox("Familia de partes", ["MOTOR", "CHASIS", "ELECTRICO", "INTERIOR", "CARROCERIA"], key="m_fam")
        c_eta = st.date_input("ETA (llegada a puerto)", value=plan_d.date(), key="m_eta")
        c_rup = st.date_input("Fecha de ruptura (opcional)", value=None, key="m_rup",
                              help="Déjela vacía si no hay fecha real de ruptura.")
        if "manual_items" not in st.session_state:
            st.session_state.manual_items = []
        b1, b2, b3 = st.columns(3)
        if b1.button("Agregar a la lista"):
            if any(m["id"] == c_id for m in st.session_state.manual_items):
                st.error(f"El ID {c_id} ya está en la lista.")
            else:
                st.session_state.manual_items.append({"id": c_id, "vessel": c_vessel, "family": c_family, "eta": pd.Timestamp(c_eta), "ruptura": pd.Timestamp(c_rup) if c_rup else None})
        if b2.button("Cargar ejemplos"):
            ej = [("EJ-001", 0, 8), ("EJ-002", 1, 9), ("EJ-003", 2, None), ("EJ-004", 3, 14), ("EJ-005", 4, None)]
            st.session_state.manual_items = [{"id": i, "vessel": "BUQUE-EJ", "family": "MOTOR", "eta": plan_d + pd.Timedelta(days=e),
                                              "ruptura": None if r is None else plan_d + pd.Timedelta(days=r)} for i, e, r in ej]
        if b3.button("Limpiar lista"):
            st.session_state.manual_items = []
        run_m = st.button("Simular y optimizar", type="primary")

    with col_list:
        st.subheader("Contenedores ingresados")
        items = st.session_state.get("manual_items", [])
        if items:
            st.dataframe(pd.DataFrame([{"ID": m["id"], "Buque": m["vessel"], "Familia": m["family"], "ETA": m["eta"].strftime("%Y-%m-%d"),
                                        "Ruptura": m["ruptura"].strftime("%Y-%m-%d") if m["ruptura"] is not None else "N/D"} for m in items]),
                         width="stretch", height=260)
        else:
            st.info("No hay contenedores. Agregue al menos uno o cargue los ejemplos.")

    if run_m:
        if not items:
            st.warning("Agregue al menos un contenedor.")
        else:
            _run_and_store(items, params_m, "manual")
    if "res_manual" in st.session_state:
        st.markdown("---")
        res_m = st.session_state.res_manual
        render_listado(res_m.df_universo, "manual")
        render_resultados(res_m, "manual")

elif st.session_state.view == "lote":
    if st.button("Volver al Inicio"):
        st.session_state.view = "home"
        st.rerun()

    st.title("Proceso por Lote - Archivos Excel")
    st.markdown("Suba los archivos oficiales. El Tracking es obligatorio y define el universo; DIEL y Prioridades aportan ruptura y EM previa.")
    params_l = render_params_panel("lote")
    render_guia_rapida(params_l)
    st.markdown("---")
    st.subheader("Archivos")
    f1, f2, f3 = st.columns(3)
    up_tr = f1.file_uploader("Tracking de Contenedores (obligatorio)", type=["xlsx", "xls"], key="up_tr")
    up_di = f2.file_uploader("Programación DIEL", type=["xlsx", "xls"], key="up_di")
    up_pr = f3.file_uploader("Prioridades CKD", type=["xlsx", "xls", "xlsm"], key="up_pr")

    if st.button("Procesar y ejecutar pipeline completo", type="primary"):
        if up_tr is None:
            st.warning("El Tracking es obligatorio.")
        else:
            _run_and_store({"tracking": up_tr, "diel": up_di, "prio": up_pr}, params_l, "lote")
    if "res_lote" in st.session_state:
        st.markdown("---")
        res_l = st.session_state.res_lote
        render_listado(res_l.df_universo, "lote")
        render_resultados(res_l, "lote")
