"""
export.py
---------
Entregable prescriptivo (.xlsx + .csv). TODO sale del objeto `Resultado` (src/pipeline.py):
no hay capacidades ni conteos escritos a mano. Fechas AAAA-MM-DD; "N/D" si falta el dato.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

import pandas as pd

from src.costs import ESTADO_DIFERIDO, ESTADO_HORIZONTE, ESTADO_PROYECTADA
from src.pipeline import Resultado


def _d(base: pd.Timestamp, v: Any) -> str:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return "N/D"
    return (base + pd.Timedelta(days=int(v))).strftime("%Y-%m-%d")


def _fecha(v: Any) -> str:
    dt = pd.to_datetime(v, errors="coerce")
    return "N/D" if pd.isna(dt) else dt.strftime("%Y-%m-%d")


def build_programacion(res: Resultado) -> pd.DataFrame:
    p, base = res.params, res.base_date
    cdf = res.costos_opt.df.set_index("id")
    rows = []
    for c in res.containers:
        e = res.plan.get(c.id)
        k = cdf.loc[c.id]
        em = e.em_day if e is not None else None
        lt = (em - c.eta) if em is not None else None
        alertas: List[str] = []
        if c.need_by is None:
            alertas.append("Ruptura: N/D (sin fecha real)")
        elif em is not None and em > c.need_by:
            alertas.append(f"Ruptura: {em - c.need_by} día(s) después de la fecha real")
        if lt is not None and lt > p.l_max:
            alertas.append(f"Crítica: lead time {lt} > {p.l_max}")
        elif lt is not None and lt > p.l_obj:
            alertas.append(f"Preventiva: lead time {lt} > {p.l_obj}")
        if k["estado"] == ESTADO_PROYECTADA:
            alertas.append("EM proyectada (fuera del horizonte)")
        if k["estado"] == ESTADO_DIFERIDO:
            alertas.append("Diferido sin cupo (demurrage estimado)")
        is_suppla = (e is not None and e.route == "suppla")
        rows.append({
            "ID": c.id, "Estado": k["estado"], "Buque": c.vessel, "Origen": c.origen,
            "ETD": _d(base, c.etd), "ETA": _d(base, c.eta),
            "Ruptura": _d(base, c.ruptura_real), "Tipo ruptura": "Real" if c.need_by is not None else "Sin ruptura",
            "EM objetivo": _d(base, c.em_objetivo), "EM previa": _d(base, c.em_previa), "EM plan": _d(base, em),
            "Ruta": {"direct": "Directo", "suppla": "Vía Suppla"}.get(e.route, "N/D") if e is not None else "N/D",
            "Recepción Suppla": _d(base, e.suppla_in_day) if is_suppla else "N/D",
            "Cambió": ("N/D" if (c.em_previa is None or em is None) else ("Sí" if em != c.em_previa else "No")),
            "Lead time": lt if lt is not None else "N/D",
            "Días en puerto": int(k["dias_puerto"]), "Días demurrage": int(k["dias_demurrage"]),
            "USD demurrage": float(k["usd_demurrage"]),
            "Días en Suppla": int(k["dias_suppla"]) if is_suppla else 0,
            "USD almacenamiento Suppla": float(k["usd_suppla"]) if is_suppla else 0.0,
            "Alertas": "; ".join(alertas) if alertas else "",
        })
    return pd.DataFrame(rows)


def build_impacto(res: Resultado) -> pd.DataFrame:
    cb, co = res.costos_base, res.costos_opt
    p = res.params
    filas = []

    def bloque(titulo: str, key: str | None):
        b = cb.totals if key is None else cb.by_block[key]
        o = co.totals if key is None else co.by_block[key]
        for nombre, f in (("Demurrage (días)", "dias_demurrage"),
                          ("Demurrage (USD)", "usd_demurrage"),
                          ("Almacenamiento Suppla (contenedor-días)", "dias_suppla"),
                          ("Almacenamiento Suppla (USD)", "usd_suppla"),
                          ("Contenedores vía Suppla (n)", "n_via_suppla"),
                          ("Total (USD)", "usd_total")):
            filas.append({"Bloque": titulo, "Concepto": nombre, "Línea base": b[f], "Plan optimizado": o[f], "Ahorro (base − óptimo)": b[f] - o[f]})

    bloque("Total", None)
    bloque("Dentro del horizonte", "horizonte")
    bloque("EM proyectada (fuera del horizonte)", "proyectada")
    bloque("Diferidos sin cupo (demurrage estimado)", "diferido")
    filas.append({"Bloque": "Informativo", "Concepto": "Demurrage ya acumulado antes del día 0 (días, inevitable)",
                  "Línea base": cb.acumulado_previo_dias, "Plan optimizado": co.acumulado_previo_dias, "Ahorro (base − óptimo)": cb.acumulado_previo_dias - co.acumulado_previo_dias})
    filas.append({"Bloque": "Informativo", "Concepto": "Demurrage ya acumulado antes del día 0 (USD, inevitable)",
                  "Línea base": cb.acumulado_previo_usd, "Plan optimizado": co.acumulado_previo_usd, "Ahorro (base − óptimo)": cb.acumulado_previo_usd - co.acumulado_previo_usd})
    filas.append({"Bloque": "Evitable", "Concepto": "Costo evitable (USD) = total − demurrage previo al día 0",
                  "Línea base": res.costo_evitable_base, "Plan optimizado": res.costo_evitable_opt,
                  "Ahorro (base − óptimo)": res.costo_evitable_base - res.costo_evitable_opt})
    filas.append({"Bloque": "Rupturas", "Concepto": "Contenedores con ruptura (n)",
                  "Línea base": res.rupturas_base, "Plan optimizado": res.rupturas_opt,
                  "Ahorro (base − óptimo)": res.rupturas_evitadas})
    filas.append({"Bloque": "Rupturas", "Concepto": "Costo neto por ruptura evitada (USD)",
                  "Línea base": "", "Plan optimizado": "",
                  "Ahorro (base − óptimo)": res.costo_por_ruptura_evitada})
    filas.append({"Bloque": "Nota", "Concepto": f"Ahorro contra la línea base simulada. Almacenamiento Suppla = {p.USD_SUPPLA_MES_40FT:,.2f} USD/mes por contenedor de 40 pies, prorrateado por día (supuesto).",
                  "Línea base": "", "Plan optimizado": "", "Ahorro (base − óptimo)": ""})
    return pd.DataFrame(filas)


def build_parametros(res: Resultado) -> pd.DataFrame:
    p = res.params
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    f = [("Usuario", "Fecha de planeación (día 0)", res.base_date.strftime("%Y-%m-%d")),
         ("Usuario", "Horizonte (días)", p.horizon),
         ("Usuario", "Capacidad SOFASA por día", p.cap_sofasa_per_day),
         ("Usuario", "Capacidad Suppla por semana", p.cap_suppla_per_week),
         ("Usuario", "Capacidad de traslado por día", p.cap_traslado_per_day),
         ("Usuario", "Días habilitados de traslado", ", ".join(dias[d] for d in p.transfer_days_allowed))]
    k = [("Constante (regla del PDF)", "l_min (mínimo puerto→planta)", p.l_min),
         ("Constante (regla del PDF)", "l_obj (objetivo)", p.l_obj),
         ("Constante (regla del PDF)", "l_max (máximo antes de demurrage)", p.l_max),
         ("Constante (regla del PDF)", "Días hábiles de holgura para EM objetivo", p.dias_habiles_resta),
         ("Constante (supuesto)", "USD demurrage por día", p.USD_DEMURRAGE_DIA),
         ("Constante (supuesto)", "USD_SUPPLA_MES_40FT", p.USD_SUPPLA_MES_40FT),
         ("Constante (supuesto)", "DIAS_MES_SUPPLA", p.DIAS_MES_SUPPLA),
         ("Constante (derivada)", "USD_SUPPLA_DIA", round(p.USD_SUPPLA_DIA, 4)),
         ("Constante (derivada)", "horizon_solver", p.horizon_solver),
         ("Peso de prioridad", "cost_rupture (por día)", p.cost_rupture),
         ("Peso de prioridad", "cost_rupture_event", p.cost_rupture_event),
         ("Peso de prioridad", "cost_em_objetivo_dia", p.cost_em_objetivo_dia),
         ("Peso de prioridad", "cost_alert_day", p.cost_alert_day),
         ("Solver", "Estado", res.solver.status), ("Solver", "Gap", round(res.solver.gap, 4))]
    return pd.DataFrame(f + k, columns=["Tipo", "Parámetro", "Valor"])


def build_embudo(res: Resultado) -> pd.DataFrame:
    e, est = res.embudo, res.estados["estado_optimo"].value_counts()
    filas = [("Tracking total", e.get("tracking_total", 0)), ("Excluidos (EM real anterior al día 0)", e.get("excluidos", 0)),
             ("Fuera de ventana (ETA posterior al horizonte)", e.get("fuera_ventana", 0)),
             ("Programables", e.get("programables", 0)),
             ("  · con ruptura real", e.get("programables_con_ruptura_real", 0)),
             ("  · sin ruptura (sin fecha real)", e.get("programables_sin_ruptura", 0)),
             ("  · en horizonte (plan óptimo)", int(est.get(ESTADO_HORIZONTE, 0))),
             ("  · EM proyectada (plan óptimo)", int(est.get(ESTADO_PROYECTADA, 0))),
             ("  · diferidos (plan óptimo)", int(est.get(ESTADO_DIFERIDO, 0))),
             ("IDs de DIEL/Prioridades que no están en el Tracking", e.get("no_tracking", 0))]
    return pd.DataFrame(filas, columns=["Métrica del embudo", "Valor"])


def export_prescriptive_plan(res: Resultado, out_path: str = "plan_prescriptivo_sofasa.xlsx") -> str:
    base = res.base_date
    prog = build_programacion(res)
    impacto, params_df, embudo = build_impacto(res), build_parametros(res), build_embudo(res)
    proy = prog[prog["Estado"] == ESTADO_PROYECTADA]
    a = res.df_universo.attrs
    exc = a.get("excluded_df", pd.DataFrame())
    fue = a.get("fuera_ventana_df", pd.DataFrame())
    nt = a.get("no_tracking_df", pd.DataFrame(columns=["id", "fuente"]))
    exc_x = pd.DataFrame({"ID": exc.get("id", []), "EM real": [_fecha(v) for v in exc.get("em", [])],
                          "ETA": [_fecha(v) for v in exc.get("eta", [])], "Motivo": exc.get("motivo_estado", [])}) if len(exc) else pd.DataFrame(columns=["ID", "EM real", "ETA", "Motivo"])
    fue_x = pd.DataFrame({"ID": fue.get("id", []), "ETA": [_fecha(v) for v in fue.get("eta", [])],
                          "Motivo": fue.get("motivo_estado", [])}) if len(fue) else pd.DataFrame(columns=["ID", "ETA", "Motivo"])
    nt_x = nt.rename(columns={"id": "ID", "fuente": "Fuente"}) if len(nt) else pd.DataFrame(columns=["ID", "Fuente"])
    val = pd.DataFrame(res.validaciones, columns=["Validación", "Estado", "Valor encontrado"])

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as w:
        prog.to_excel(w, sheet_name="Programacion semanal", index=False)
        impacto.to_excel(w, sheet_name="Impacto económico", index=False)
        proy.to_excel(w, sheet_name="EM proyectada (fuera horizonte)", index=False)
        exc_x.to_excel(w, sheet_name="Excluidos (ya en planta)", index=False)
        fue_x.to_excel(w, sheet_name="Fuera de ventana", index=False)
        nt_x.to_excel(w, sheet_name="No están en Tracking", index=False)
        embudo.to_excel(w, sheet_name="Embudo del universo", index=False)
        val.to_excel(w, sheet_name="Validaciones", index=False)
        params_df.to_excel(w, sheet_name="Parámetros", index=False)
        for ws in w.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(60, max(10, max(len(str(x.value or "")) for x in col[:200]) + 2))
    prog.to_csv(os.path.splitext(out_path)[0] + ".csv", index=False, encoding="utf-8-sig")
    return out_path
