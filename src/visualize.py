from __future__ import annotations

"""
visualize.py
------------
Gráficas de apoyo para leer los resultados de la simulación/optimización:
comparación línea base vs. optimizado, distribución de lead times y tablero de KPIs.

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


def plot_suppla_occupancy(daily_baseline: pd.DataFrame, daily_opt: pd.DataFrame,
                          title: str = "Ocupación de Suppla: línea base vs. plan optimizado") -> Any:
    """Contenedores almacenados en Suppla por día (no hay inventario SOFASA en el modelo)."""
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(daily_baseline["day"], daily_baseline["ocupacion_suppla"], color=COLOR_BASELINE, linewidth=2, label="Línea base")
    ax.plot(daily_opt["day"], daily_opt["ocupacion_suppla"], color=COLOR_OPTIMIZADO, linewidth=2, label="Plan optimizado")
    ax.set_xlabel("Día del horizonte")
    ax.set_ylabel("Contenedores en Suppla")
    ax.set_title(title)
    ax.legend(frameon=False)
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    return fig


def plot_cost_comparison(costos_base, costos_opt, title: str = "Costo en USD: línea base vs. plan optimizado") -> Any:
    """Costo por componente (demurrage, almacenamiento Suppla, total) de ambos planes."""
    comps = [("Demurrage", "usd_demurrage"), ("Almacenamiento Suppla", "usd_suppla"), ("Total", "usd_total")]
    fig, ax = plt.subplots(figsize=(8, 4.6))
    x = range(len(comps))
    w = 0.35
    bv = [costos_base.totals[k] for _, k in comps]
    ov = [costos_opt.totals[k] for _, k in comps]
    ax.bar([i - w / 2 for i in x], bv, w, color=COLOR_BASELINE, label="Línea base")
    ax.bar([i + w / 2 for i in x], ov, w, color=COLOR_OPTIMIZADO, label="Plan optimizado")
    for i, (a_, b_) in enumerate(zip(bv, ov)):
        ax.text(i - w / 2, a_, f"{a_:,.0f}", ha="center", va="bottom", fontsize=8)
        ax.text(i + w / 2, b_, f"{b_:,.0f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(list(x))
    ax.set_xticklabels([n for n, _ in comps])
    ax.set_ylabel("USD")
    ax.set_title(title)
    ax.margins(y=0.15)
    ax.legend(frameon=False)
    fig.tight_layout()
    return fig


def plot_lead_time_distribution(container_df_baseline: pd.DataFrame, container_df_opt: pd.DataFrame, params) -> Any:
    fig, ax = plt.subplots(figsize=(9, 4))
    lt_base = container_df_baseline["lead_time"].dropna() if "lead_time" in container_df_baseline.columns else pd.Series(dtype=float)
    lt_opt = container_df_opt["lead_time"].dropna() if "lead_time" in container_df_opt.columns else pd.Series(dtype=float)
    max_val = max(lt_base.max() if not lt_base.empty else 0, lt_opt.max() if not lt_opt.empty else 0, params.l_max)
    bins = range(0, int(max_val + 5))
    if not lt_base.empty:
        ax.hist(lt_base, bins=bins, alpha=0.55, color=COLOR_BASELINE, label="Línea base (heurística)")
    if not lt_opt.empty:
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
    "Rupturas y ruteo": [
        "n_rupturas",
        "pct_via_suppla",
    ],
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


def _outcome_label(row) -> str:
    if not row.get("atendido", True) or row.get("estado_optimo") == "DIFERIDO_SIN_CUPO" or row.get("estado_base") == "DIFERIDO_SIN_CUPO":
        return "Diferido sin cupo"
    if not row.get("tiene_ruptura_real", True):
        return "Sin fecha de ruptura (N/D)"
    rupture_days = row.get("rupture_days", 0)
    if rupture_days <= 0:
        return "Sin ruptura"
    if rupture_days <= 3:
        return "Ruptura 1-3 d"
    if rupture_days <= 7:
        return "Ruptura 4-7 d"
    return "Ruptura > 7 d"


_OUTCOME_ORDER = ["Sin ruptura", "Ruptura 1-3 d", "Ruptura 4-7 d", "Ruptura > 7 d", "Sin fecha de ruptura (N/D)", "Diferido sin cupo"]
_OUTCOME_COLOR = {
    "Sin ruptura": COLOR_OPTIMIZADO,
    "Ruptura 1-3 d": "#F0C000",
    "Ruptura 4-7 d": COLOR_BASELINE,
    "Ruptura > 7 d": COLOR_CRITICO,
    "Sin fecha de ruptura (N/D)": "#999999",
    "Diferido sin cupo": "#333333",
}
_ROUTE_LABEL = {"direct": "Directo", "suppla": "Suppla Rionegro"}


_PX_PER_CONTAINER = 14   # grosor objetivo de cada línea (px)


def _sankey_nodes_links(result, show_container_labels: bool = True):
    df = result.container_df.sort_values("eta").reset_index(drop=True)
    id_col = "id" if "id" in df.columns else ("container_id" if "container_id" in df.columns else None)

    n = len(df)
    df = df.assign(_out=df.apply(_outcome_label, axis=1))

    used_routes = [r for r in ("direct", "suppla") if (df["route"] == r).any()]
    used_outcomes = [o for o in _OUTCOME_ORDER if (df["_out"] == o).any()]

    labels, colors = [], []
    for i, row in df.iterrows():
        name = str(row[id_col]) if (id_col and show_container_labels) else ""
        estado = row.get("estado_optimo", row.get("estado_base", ""))
        if estado == "EM_PROYECTADA":
            name += " ⏭"
        labels.append(name)
        colors.append(COLOR_SOFASA if row["route"] == "direct" else COLOR_SUPPLA)
    route_idx = {}
    for r in used_routes:
        route_idx[r] = len(labels)
        labels.append(_ROUTE_LABEL[r])
        colors.append(COLOR_SOFASA if r == "direct" else COLOR_SUPPLA)
    out_idx = {}
    for o in used_outcomes:
        out_idx[o] = len(labels)
        labels.append(o)
        colors.append(_OUTCOME_COLOR[o])

    src, tgt, val, lcol = [], [], [], []
    for i, row in df.iterrows():
        src.append(i)
        tgt.append(route_idx[row["route"]])
        val.append(1)
        lcol.append(_hex_to_rgba(_OUTCOME_COLOR[row["_out"]], 0.45))
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
    *_, n_b, m_b = _sankey_nodes_links(base_result, show_container_labels)
    *_, n_o, m_o = _sankey_nodes_links(opt_result, show_container_labels)
    h_b = _panel_height(n_b, m_b)
    h_o = _panel_height(n_o, m_o)

    ann_px = 28
    gap_px = 40
    plot_px = h_b + h_o + 2 * ann_px + gap_px

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
    fig.update_layout(
        height=plot_px + margin_t + margin_b,
        margin=dict(t=margin_t, b=margin_b, l=10, r=10),
        annotations=[
            dict(x=0.5, y=b_hi + 4/plot_px, xref="paper", yref="paper", text=f"<b>{title_base}</b>", showarrow=False, yanchor="bottom"),
            dict(x=0.5, y=o_hi + 4/plot_px, xref="paper", yref="paper", text=f"<b>{title_opt}</b>", showarrow=False, yanchor="bottom"),
        ],
    )
    return fig

