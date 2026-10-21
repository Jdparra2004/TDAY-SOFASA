from __future__ import annotations

"""
visualize.py
------------
Gráficas de apoyo para leer los resultados de la simulación/optimización:
niveles de inventario en el tiempo, comparación línea base vs. optimizado,
distribución de lead times y tablero de KPIs.

Paleta fija y consistente por entidad (colorblind-safe, Okabe-Ito) para que
el mismo color siempre signifique lo mismo entre gráficas.
"""

from typing import Dict, Any, Tuple

import matplotlib.pyplot as plt
import pandas as pd

# Paleta categórica fija (Okabe-Ito, segura para daltonismo). El orden no cambia.
COLOR_SOFASA = "#0072B2"      # azul
COLOR_SUPPLA = "#E69F00"      # naranja
COLOR_BASELINE = "#D55E00"    # vermellón
COLOR_OPTIMIZADO = "#009E73"  # verde
COLOR_CRITICO = "#CC2222"
COLOR_NEUTRAL = "#666666"

plt.rcParams.update(
    {
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "#888888",
        "axes.grid": True,
        "grid.color": "#e6e6e6",
        "grid.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.size": 10,
    }
)


def plot_inventory_over_time(daily_df: pd.DataFrame, title: str) -> Any:
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(daily_df["day"], daily_df["inv_sofasa"], color=COLOR_SOFASA, linewidth=2, label="Inventario SOFASA")
    ax.plot(daily_df["day"], daily_df["inv_suppla"], color=COLOR_SUPPLA, linewidth=2, label="Inventario Suppla")
    ax.set_xlabel("Día del horizonte")
    ax.set_ylabel("Contenedores en bodega")
    ax.set_title(title)
    ax.legend(frameon=False)
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    return fig


def plot_inventory_comparison(
    daily_baseline: pd.DataFrame, daily_opt: pd.DataFrame, warehouse: str, title: str
) -> Any:
    """warehouse: 'inv_sofasa' o 'inv_suppla'"""
    fig, ax = plt.subplots(figsize=(10, 5))
    
    # Asegurar que el eje X cubra el horizonte completo
    max_day = max(daily_baseline["day"].max(), daily_opt["day"].max())
    
    ax.plot(daily_baseline["day"], daily_baseline[warehouse], color=COLOR_BASELINE, linewidth=2, label="Línea base (heurística)")
    ax.plot(daily_opt["day"], daily_opt[warehouse], color=COLOR_OPTIMIZADO, linewidth=2, label="Plan optimizado")
    
    ax.set_xlabel("Día del horizonte")
    ax.set_ylabel("Contenedores en bodega")
    ax.set_title(title)
    ax.legend(frameon=True, loc='best')
    
    # Ajustar escalas y límites
    ax.set_xlim(0, max_day)
    ax.set_ylim(bottom=0)
    
    # Añadir grid mejorado
    ax.grid(True, which='both', linestyle='--', linewidth=0.5)
    
    fig.tight_layout()
    return fig


def plot_lead_time_distribution(container_df_baseline: pd.DataFrame, container_df_opt: pd.DataFrame, params) -> Any:
    fig, ax = plt.subplots(figsize=(9, 4))
    lt_base = container_df_baseline["lead_time"].dropna()
    lt_opt = container_df_opt["lead_time"].dropna()
    bins = range(0, int(max(lt_base.max(), lt_opt.max(), params.l_max) + 5))
    ax.hist(lt_base, bins=bins, alpha=0.55, color=COLOR_BASELINE, label="Línea base (heurística)")
    ax.hist(lt_opt, bins=bins, alpha=0.55, color=COLOR_OPTIMIZADO, label="Plan optimizado")
    ax.axvline(params.l_obj, color=COLOR_NEUTRAL, linestyle="--", linewidth=1.2, label=f"Objetivo ({params.l_obj}d)")
    ax.axvline(params.l_max, color=COLOR_CRITICO, linestyle="--", linewidth=1.2, label=f"Máximo ({params.l_max}d)")
    ax.set_xlabel("Lead time puerto → planta (días)")
    ax.set_ylabel("Número de contenedores")
    ax.set_title("Distribución de lead time: línea base vs. plan optimizado")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    return fig


# KPIs que tiene sentido comparar en el mismo tipo de eje (magnitud comparable)
_KPI_GROUPS = {
    "Cumplimiento del estándar de tiempo (%)": [
        "pct_dentro_objetivo",
        "pct_alerta_preventiva",
        "pct_alerta_critica",
    ],
    "Rupturas de material (# contenedores)": ["n_rupturas"],
    "Uso de almacenamiento externo (% contenedores vía Suppla)": ["pct_via_suppla"],
    "Lead time promedio (días)": ["lead_time_promedio"],
}


def plot_kpi_dashboard(kpis_baseline: Dict[str, float], kpis_opt: Dict[str, float]) -> Any:
    n_panels = len(_KPI_GROUPS)
    fig, axes = plt.subplots(1, n_panels, figsize=(4 * n_panels, 4.6))
    if n_panels == 1:
        axes = [axes]

    bars_for_legend = None
    for ax, (group_title, keys) in zip(axes, _KPI_GROUPS.items()):
        labels = [k for k in keys]
        base_vals = [kpis_baseline.get(k, 0) for k in keys]
        opt_vals = [kpis_opt.get(k, 0) for k in keys]
        x = range(len(labels))
        width = 0.35
        b1 = ax.bar([i - width / 2 for i in x], base_vals, width, color=COLOR_BASELINE, label="Línea base")
        b2 = ax.bar([i + width / 2 for i in x], opt_vals, width, color=COLOR_OPTIMIZADO, label="Optimizado")
        bars_for_legend = (b1, b2)
        ax.set_xticks(list(x))
        ax.set_xticklabels([_short_label(k) for k in labels], rotation=20, ha="right", fontsize=8)
        ax.set_title(group_title, fontsize=9, pad=10)
        ax.margins(y=0.15)
        for i, v in enumerate(base_vals):
            ax.text(i - width / 2, v, f"{v:.1f}", ha="center", va="bottom", fontsize=7, color=COLOR_NEUTRAL)
        for i, v in enumerate(opt_vals):
            ax.text(i + width / 2, v, f"{v:.1f}", ha="center", va="bottom", fontsize=7, color=COLOR_NEUTRAL)

    fig.legend(
        bars_for_legend, ["Línea base (heurística)", "Plan optimizado"],
        loc="upper center", ncol=2, frameon=False, fontsize=9, bbox_to_anchor=(0.5, 1.03),
    )
    fig.suptitle("Comparación de KPIs: línea base (heurística) vs. plan optimizado", y=1.14, fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    return fig


def _short_label(key: str) -> str:
    mapping = {
        "pct_dentro_objetivo": "≤ objetivo",
        "pct_alerta_preventiva": "alerta prev.",
        "pct_alerta_critica": "alerta crítica",
        "n_rupturas": "rupturas",
        "pct_via_suppla": "% vía Suppla",
        "lead_time_promedio": "lead time prom.",
    }
    return mapping.get(key, key)


def plot_container_trajectory(container_df: pd.DataFrame, title: str = "Evolución Cronológica de Tiempos y Retrasos por Contenedor") -> Any:
    """Gráfica de trayectoria paso a paso en el tiempo (eje X = día ETA de llegada a puerto)."""
    fig, ax = plt.subplots(figsize=(10, 5))
    if container_df.empty or "lead_time" not in container_df.columns:
        ax.text(0.5, 0.5, "Sin datos de contenedores", ha="center", va="center")
        return fig
    
    df_sorted = container_df.sort_values(by="eta").reset_index(drop=True)
    ax.plot(df_sorted["eta"], df_sorted["lead_time"], marker="o", color=COLOR_SOFASA, linewidth=1.5, label="Lead Time Total (Puerto -> Planta)")
    if "rupture_days" in df_sorted.columns:
        ax.plot(df_sorted["eta"], df_sorted["rupture_days"], marker="x", color=COLOR_CRITICO, linewidth=1.2, label="Días de Ruptura (Retraso)")
        
    ax.set_xlabel("Día ETA (Llegada a Puerto)")
    ax.set_ylabel("Días")
    ax.set_title(title)
    ax.legend(frameon=True, loc="best")
    ax.grid(True, linestyle="--", alpha=0.6)
    fig.tight_layout()
    return fig


def plot_single_container_journey(container_id: str, container_row: pd.Series, title: str = "Mapa de Movimiento del Contenedor") -> Any:
    """Gráfica el ciclo de vida y tiempos de un contenedor específico con espaciado optimizado."""
    fig, ax = plt.subplots(figsize=(10, 4))
    eta = container_row.get("eta", 0)
    need = container_row.get("need_by", 10)
    em = container_row.get("em", eta)
    route = container_row.get("route", "direct")

    events = [("ETA Puerto", eta), ("Entrada Planta (EM)", em), ("Fecha Ruptura (Need By)", need)]
    if route == "suppla":
        suppla_in = container_row.get("suppla_in_day", eta)
        events.insert(1, ("Recepción Suppla", suppla_in))

    names = [e[0] for e in events]
    days = [e[1] for e in events]

    ax.scatter(days, [1]*len(days), color=COLOR_SOFASA, s=160, zorder=3)
    ax.plot(days, [1]*len(days), color=COLOR_NEUTRAL, linestyle="--", zorder=2)

    for i, (name, day) in enumerate(zip(names, days)):
        # Alternar etiquetas arriba y abajo para evitar saturación de texto
        offset_y = 22 if i % 2 == 0 else -30
        va_align = "bottom" if i % 2 == 0 else "top"
        ax.annotate(f"{name}\n(Día {int(day)})", (day, 1), textcoords="offset points", 
                    xytext=(0, offset_y), ha="center", va=va_align, fontsize=9, fontweight="bold")

    ax.set_yticks([])
    ax.set_ylim(0.6, 1.4)
    ax.set_xlabel("Días del Horizonte", fontsize=10)
    ax.set_title(f"Contenedor: {container_id} | Ruta: {route.upper()}", fontsize=11, pad=15)
    ax.set_xlim(min(days) - 5, max(days) + 8)
    ax.grid(True, axis="x", linestyle="--", alpha=0.6)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Diagrama de Flujo (Sankey): Puerto -> Directo/Suppla -> SOFASA -> Producción
# -> Sin Ruptura / Con Ruptura. El ancho de cada flujo es proporcional al
# numero real de contenedores que pasaron por esa ruta (no es un esquema fijo:
# se recalcula a partir de container_df de cada corrida de simulacion).
# ---------------------------------------------------------------------------
import plotly.graph_objects as go


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _outcome_label(rupture_days: float) -> str:
    if rupture_days <= 0:
        return "Sin ruptura"
    if rupture_days <= 3:
        return "Ruptura 1-3 d"
    if rupture_days <= 7:
        return "Ruptura 4-7 d"
    return "Ruptura > 7 d"


_OUTCOME_ORDER = ["Sin ruptura", "Ruptura 1-3 d", "Ruptura 4-7 d", "Ruptura > 7 d"]
_OUTCOME_COLOR = {
    "Sin ruptura": COLOR_OPTIMIZADO,
    "Ruptura 1-3 d": "#F0C000",
    "Ruptura 4-7 d": COLOR_BASELINE,
    "Ruptura > 7 d": COLOR_CRITICO,
}
_ROUTE_LABEL = {"direct": "Directo", "suppla": "Suppla Rionegro"}


_PX_PER_CONTAINER = 14   # grosor objetivo de cada línea (px); bájalo si quieres líneas más finas


def _sankey_nodes_links(result, show_container_labels: bool = True):
    """Nodos: [contenedores...] -> [Directo, Suppla] -> [resultados].
    Solo se crean los nodos de ruta/resultado que realmente tienen flujo,
    para que no ocupen espacio (ni distorsionen el grosor) cuando están vacíos."""
    df = result.container_df.sort_values("eta").reset_index(drop=True)
    id_col = "id" if "id" in df.columns else ("container_id" if "container_id" in df.columns else None)

    n = len(df)
    df = df.assign(_out=df["rupture_days"].apply(_outcome_label))

    used_routes = [r for r in ("direct", "suppla") if (df["route"] == r).any()]
    used_outcomes = [o for o in _OUTCOME_ORDER if (df["_out"] == o).any()]

    labels, colors = [], []
    # Columna 0: un nodo por contenedor (ordenado por ETA)
    for i, row in df.iterrows():
        name = str(row[id_col]) if (id_col and show_container_labels) else ""
        labels.append(name)
        colors.append(COLOR_SOFASA if row["route"] == "direct" else COLOR_SUPPLA)
    # Columna 1: ruta
    route_idx = {}
    for r in used_routes:
        route_idx[r] = len(labels)
        labels.append(_ROUTE_LABEL[r])
        colors.append(COLOR_SOFASA if r == "direct" else COLOR_SUPPLA)
    # Columna 2: resultado
    out_idx = {}
    for o in used_outcomes:
        out_idx[o] = len(labels)
        labels.append(o)
        colors.append(_OUTCOME_COLOR[o])

    src, tgt, val, lcol = [], [], [], []
    # Contenedor -> ruta (valor 1 cada uno, color según resultado final)
    for i, row in df.iterrows():
        src.append(i)
        tgt.append(route_idx[row["route"]])
        val.append(1)
        lcol.append(_hex_to_rgba(_OUTCOME_COLOR[row["_out"]], 0.45))
    # Ruta -> resultado (agregado)
    for (r, o), v in df.groupby(["route", "_out"]).size().items():
        src.append(route_idx[r])
        tgt.append(out_idx[o])
        val.append(int(v))
        lcol.append(_hex_to_rgba(_OUTCOME_COLOR[o], 0.45))

    max_col_nodes = max(n, len(used_routes), len(used_outcomes), 1)
    return labels, colors, src, tgt, val, lcol, n, max_col_nodes


def _sankey_pad(n: int) -> int:
    return 4 if n > 40 else 12


def _panel_height(n: int, max_col_nodes: int) -> int:
    """Altura (px) del panel para que cada contenedor mida ~_PX_PER_CONTAINER.
    Plotly reparte: grosor = (altura - (nodos_columna - 1) * pad) / n_contenedores.
    Despejando la altura se obtiene un grosor constante sin importar cuántos haya."""
    pad = _sankey_pad(n)
    h = n * _PX_PER_CONTAINER + (max_col_nodes - 1) * pad
    return max(int(h), 60)


def _sankey_trace(result, y_domain: Tuple[float, float], show_container_labels: bool) -> go.Sankey:
    labels, colors, src, tgt, val, lcol, n, _ = _sankey_nodes_links(result, show_container_labels)
    return go.Sankey(
        arrangement="snap",
        domain=dict(x=[0.0, 1.0], y=list(y_domain)),
        node=dict(
            label=labels,
            color=colors,
            pad=_sankey_pad(n),
            thickness=14,
            line=dict(color="rgba(0,0,0,0.3)", width=0.5),
        ),
        link=dict(source=src, target=tgt, value=val, color=lcol),
        textfont=dict(size=10, color="#1a1a1a", family="Arial, sans-serif"),
    )


def plot_sankey_comparison(
    base_result,
    opt_result,
    title_base: str = "Línea Base (Heurística 'as-is')",
    title_opt: str = "Plan Optimizado (CP-SAT)",
    show_container_labels: bool = True,
) -> go.Figure:
    """Sankey por contenedor, apilado (base arriba, optimizado abajo).
    Contenedor -> Ruta -> Resultado. La altura de cada panel se calcula con el
    número de contenedores, así cada línea mide lo mismo con 1 o con 700."""
    *_, n_b, m_b = _sankey_nodes_links(base_result, show_container_labels)
    *_, n_o, m_o = _sankey_nodes_links(opt_result, show_container_labels)
    h_b = _panel_height(n_b, m_b)
    h_o = _panel_height(n_o, m_o)

    ann_px = 28      # espacio para el título de cada panel
    gap_px = 40      # separación entre paneles
    plot_px = h_b + h_o + 2 * ann_px + gap_px

    # Dominios en fracción de la altura útil (y=0 abajo)
    o_lo, o_hi = 0.0, h_o / plot_px
    b_lo = (h_o + ann_px + gap_px) / plot_px
    b_hi = b_lo + h_b / plot_px

    margin_t, margin_b = 80, 20
    fig = go.Figure(
        data=[
            _sankey_trace(base_result, (b_lo, b_hi), show_container_labels),
            _sankey_trace(opt_result, (o_lo, o_hi), show_container_labels),
        ]
    )
def export_prescriptive_plan_excel(
    opt_result,
    containers,
    base_result,
    params,
    base_date: pd.Timestamp,
    filename: str = "plan_prescriptivo_sofasa.xlsx",
) -> str:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    base = pd.Timestamp(base_date).normalize()
    plan = opt_result.plan

    # Sheet 1: Programación semanal
    rows_prog = []
    for c in containers:
        entry = plan.get(c.id) if plan else None
        route = entry.route if entry else ("diferido" if c.id in opt_result.deferred else "fuera_horizonte")
        em_day = entry.em_day if entry else None
        suppla_in = entry.suppla_in_day if entry and entry.route == "suppla" else None
        
        em_date = (base + pd.Timedelta(days=em_day)).strftime("%Y-%m-%d") if em_day is not None else "N/A"
        eta_date = (base + pd.Timedelta(days=c.eta)).strftime("%Y-%m-%d")
        
        port_exit = em_day if route == "direct" else (suppla_in if suppla_in is not None else em_day)
        days_port = (port_exit - c.eta) if port_exit is not None else (params.horizon - c.eta)
        lt = (em_day - c.eta) if em_day is not None else None

        alerts = []
        if lt is not None and lt < params.l_min:
            alerts.append("Riesgo de incumplimiento operativo: programación por debajo del tiempo mínimo estándar puerto-planta.")
        if lt is not None and lt > params.l_obj:
            alerts.append("Programación por encima del estándar objetivo puerto-planta.")
        if days_port > params.l_max:
            alerts.append("Riesgo de demurrage: programación supera el tiempo máximo permitido en puerto.")
        alert_str = " | ".join(alerts) if alerts else "Normal"

        sem = (base.weekday() + (em_day or 0)) // 7 if em_day is not None else 99
        rows_prog.append({
            "Semana": f"Semana {sem + 1}",
            "Ruptura": f"Semana {base.weekofyear if hasattr(base, 'weekofyear') else 1}",
            "Contenedor": c.id,
            "Buque": c.vessel,
            "EM Plan": em_date,
            "Origen": getattr(c, "part_family", "GEN"),
            "ETD": "N/A",
            "ETA": eta_date,
            "Ruta": "Directo" if route == "direct" else ("Suppla" if route == "suppla" else route),
            "Recepción Suppla": (base + pd.Timedelta(days=suppla_in)).strftime("%Y-%m-%d") if suppla_in is not None else "N/A",
            "EM previa": "N/A",
            "Cambió": "Sí",
            "Lead Time": lt if lt is not None else "N/A",
            "Días en puerto": days_port,
            "Alertas": alert_str,
            "Comentarios": "Programado" if entry else "Diferido / Fuera"
        })
    df_prog = pd.DataFrame(rows_prog)
    if not df_prog.empty and "Semana" in df_prog.columns and "EM Plan" in df_prog.columns:
        df_prog = df_prog.sort_values(by=["Semana", "EM Plan"])

    # Sheet 2: Capacidad SOFASA
    sofasa_used = {t: 0 for t in range(params.horizon)}
    for entry in plan.values():
        if entry.em_day is not None and entry.em_day < params.horizon:
            sofasa_used[entry.em_day] += 1
    cap_sofasa_arr = params.cap_sofasa()
    rows_sofasa = []
    for t in range(params.horizon):
        d_str = (base + pd.Timedelta(days=t)).strftime("%Y-%m-%d")
        cap = cap_sofasa_arr[t]
        used = sofasa_used[t]
        pct = (100 * used / cap) if cap > 0 else 0.0
        rows_sofasa.append({
            "Día": t,
            "Fecha": d_str,
            "Usado": used,
            "Capacidad": cap,
            "% Utilización": round(pct, 1)
        })
    df_sofasa = pd.DataFrame(rows_sofasa)

    # Sheet 3: Capacidad Suppla
    suppla_weeks_used = {}
    for entry in plan.values():
        if entry.route == "suppla" and entry.suppla_in_day is not None:
            w = params.week_of(entry.suppla_in_day)
            suppla_weeks_used[w] = suppla_weeks_used.get(w, 0) + 1
    cap_suppla_w = params.cap_suppla_weekly()
    rows_suppla = []
    for w in range(len(cap_suppla_w)):
        received = suppla_weeks_used.get(w, 0)
        cap = cap_suppla_w[w]
        pct = (100 * received / cap) if cap > 0 else 0.0
        rows_suppla.append({
            "Semana Calendario": w + 1,
            "Recibidos": received,
            "Capacidad": cap,
            "% Utilización": round(pct, 1)
        })
    df_suppla = pd.DataFrame(rows_suppla)

    # Sheet 4: Traslados Suppla-SOFASA
    traslados_used = {t: 0 for t in range(params.horizon)}
    for entry in plan.values():
        if entry.route == "suppla" and entry.em_day is not None and entry.em_day < params.horizon:
            traslados_used[entry.em_day] += 1
    cap_traslado_arr = params.cap_traslado()
    rows_traslado = []
    for t in range(params.horizon):
        d_str = (base + pd.Timedelta(days=t)).strftime("%Y-%m-%d")
        cap = cap_traslado_arr[t]
        prog = traslados_used[t]
        rows_traslado.append({
            "Día": t,
            "Fecha": d_str,
            "Programados": prog,
            "Capacidad": cap
        })
    df_traslado = pd.DataFrame(rows_traslado)

    # Sheet 5: Riesgo Demurrage
    rows_dem = [r for r in rows_prog if r["Días en puerto"] >= 11]
    df_dem = pd.DataFrame(rows_dem) if rows_dem else pd.DataFrame(columns=["Contenedor", "Días en puerto", "Alertas"])

    # Sheet 6: Riesgo Ruptura
    rows_rup = [r for r in rows_prog if "Ruptura" in str(r["Comentarios"]) or r["Lead Time"] == "N/A"]
    df_rup = pd.DataFrame(rows_rup) if rows_rup else pd.DataFrame(columns=["Contenedor", "Comentarios"])

    # Sheet 7: Diferidos y fuera de ventana
    rows_dif = [{"Contenedor": cid, "Motivo": "Diferido por capacidad"} for cid in opt_result.deferred]
    rows_dif += [{"Contenedor": cid, "Motivo": "Llega a puerto en el horizonte, no alcanza a entrar"} for cid in opt_result.out_of_horizon]
    df_dif = pd.DataFrame(rows_dif) if rows_dif else pd.DataFrame(columns=["Contenedor", "Motivo"])

    # Sheet 8: KPIs
    df_kpi = pd.DataFrame({
        "Métrica": list(opt_result.kpis.keys()),
        "Valor Optimizado": list(opt_result.kpis.values()),
        "Solver Status": [opt_result.status] * len(opt_result.kpis),
        "Solver Gap (%)": [round(opt_result.gap * 100, 2)] * len(opt_result.kpis),
        "Objective Bound": [opt_result.best_objective_bound] * len(opt_result.kpis)
    })

    # Sheet 9: Parámetros y validaciones
    df_params = pd.DataFrame({
        "Parámetro": ["Horizonte", "Capacidad SOFASA/día", "Capacidad Suppla/semana", "Capacidad Traslado/día", "L_min", "L_obj", "L_max"],
        "Valor": [params.horizon, str(params.cap_sofasa_per_day), str(params.cap_suppla_per_week), str(params.cap_traslado_per_day), params.l_min, params.l_obj, params.l_max]
    })

    with pd.ExcelWriter(filename, engine='openpyxl') as writer:
        df_prog.to_excel(writer, sheet_name="Programación semanal", index=False)
        df_sofasa.to_excel(writer, sheet_name="Capacidad SOFASA", index=False)
        df_suppla.to_excel(writer, sheet_name="Capacidad Suppla", index=False)
        df_traslado.to_excel(writer, sheet_name="Traslados Suppla-SOFASA", index=False)
        df_dem.to_excel(writer, sheet_name="Riesgo Demurrage", index=False)
        df_rup.to_excel(writer, sheet_name="Riesgo Ruptura", index=False)
        df_dif.to_excel(writer, sheet_name="Diferidos y fuera de ventana", index=False)
        df_kpi.to_excel(writer, sheet_name="KPIs", index=False)
        df_params.to_excel(writer, sheet_name="Parámetros y validaciones", index=False)

    return filename

