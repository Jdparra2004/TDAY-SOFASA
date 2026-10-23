"""
glossary.py
-----------
Fuente única de textos para la guía rápida / glosario.
Funciones puras que consumen Params (sin números literales hardcodeados).
"""
from __future__ import annotations

from typing import List, Tuple
from src.model import Params


def get_glossary(params: Params) -> List[Tuple[str, str, List[Tuple[str, str]]]]:
    horizon_limit = params.horizon - 1
    return [
        (
            "ETD",
            "Fecha de salida (zarpe) desde el origen. Se obtiene de las columnas con tokens ETD (ETD REAL, ETD INICIAL, ETD) en los archivos de Tracking o DIEL. En modo manual no existe y se muestra N/D.",
            [("Fecha AAAA-MM-DD", "Zarpe registrado"), ("N/D", "Sin dato disponible (o modo manual)")]
        ),
        (
            "ETA",
            f"Fecha de arribo a puerto (real si existe, de lo contrario inicial o estimada). Define la ventana de planeación: un contenedor entra al universo si ETA <= día 0 + {horizon_limit} (horizonte de {params.horizon} días menos 1). Se obtiene de columnas con tokens ETA (ETA REAL, ETA VTT, ETA INICIAL, ETA BUQUE, ETA PUERTO, ETA).",
            [("Fecha AAAA-MM-DD", "Arribo dentro del horizonte"), ("Fuera de ventana", "ETA posterior al horizonte (se programa en la siguiente planeación)")]
        ),
        (
            "EM objetivo",
            f"Fecha objetivo de entrada a planta (EM). Si hay fecha real de ruptura (Prioridades/DIEL), se calcula como Fecha de Ruptura menos {params.dias_habiles_resta} días hábiles. Si no hay fecha de ruptura, se calcula como ETA más el objetivo de lead time ({params.l_obj} días).",
            [("Fecha AAAA-MM-DD", "Meta óptima de entrada a planta"), ("N/D", "Sin fecha calculada")]
        ),
        (
            "EM previa",
            "Fecha de entrada a planta (EM) según la programación anterior (archivos DIEL o Prioridades, con tokens EM, EM DIEL, FECHA EM PROG, FECHA EM PLAN). N/D si no existe. No excluye a ningún contenedor por sí sola.",
            [("Fecha AAAA-MM-DD", "Programación previa"), ("N/D", "Sin registro previo (o modo manual)")]
        ),
        (
            "Ruptura / Tipo ruptura",
            "Fecha límite de requerimiento de material. Tipo 'Real' si existe fecha en Prioridades/DIEL (columnas con tokens RUPTURA, NEED, FECHA NECESIDAD, etc.); Tipo 'Sin ruptura' si no hay fecha real (N/D), en cuyo caso no cuenta para los KPIs de ruptura.",
            [("Real", "Con fecha real de necesidad (Prioridades/DIEL)"), ("Sin ruptura", "Sin fecha real de necesidad (N/D)")]
        ),
        (
            "Estado del universo (listado de entrada)",
            f"Clasificación inicial de cada contenedor del Tracking frente a la fecha base (día 0) y el horizonte de {params.horizon} días.",
            [
                ("PROGRAMABLE", "Contenedor activo dentro de la ventana de planeación"),
                ("EXCLUIDO_EN_PLANTA", "Contenedor con EM real previa al día 0 (ya ingresó a planta)"),
                ("FUERA_VENTANA", f"Contenedor con ETA posterior al horizonte (ETA > día 0 + {horizon_limit})")
            ]
        ),
        (
            "Estado (plan, hoja Programacion semanal)",
            f"Estado operativo asignado al contenedor dentro del modelo de optimización y simulación (horizonte del solver de {params.horizon_solver} días).",
            [
                ("PROGRAMADO_EN_HORIZONTE", f"Entrada a planta (EM) programada dentro del horizonte (< día {params.horizon})"),
                ("EM_PROYECTADA", f"Llega dentro del horizonte pero su EM óptima ocurre después (día {params.horizon} o posterior)"),
                ("DIFERIDO_SIN_CUPO", f"Sin cupo en capacidad hasta el cierre del solver (día {params.horizon_solver}); demurrage y Suppla estimados")
            ]
        ),
        (
            "Ruta",
            "Decisión logística asignada al contenedor: despacho directo desde puerto a SOFASA (Rionegro) o almacenamiento temporal en bodega Suppla antes del traslado a SOFASA.",
            [("Directo", "Puerto -> SOFASA"), ("Vía Suppla", "Puerto -> Bodega Suppla -> SOFASA")]
        ),
        (
            "Días en puerto",
            "Tiempo total que el contenedor permanece en puerto desde su ETA hasta su salida (hacia SOFASA o Suppla).",
            [("Días (entero)", "Duración de estadía en puerto")]
        ),
        (
            "Días demurrage",
            f"Días transcurridos en puerto que exceden el límite libre de sobreestadía ({params.l_max} días). Cada día adicional genera costo de demurrage.",
            [("0", "Sin sobreestadía acumulada"), (f"> 0 (ej. > {params.l_max})", "Días cobrables por demurrage")]
        ),
        (
            "Días en Suppla",
            "Tiempo (días naturales) que el contenedor permanece almacenado en la bodega Suppla antes de ser despachado a SOFASA (solo aplica a ruta Vía Suppla).",
            [("0", "Ruta directa (sin paso por Suppla)"), ("> 0", "Días de almacenamiento en Suppla")]
        ),
        (
            "Alertas",
            f"Indicadores de desempeño de lead time evaluados frente al objetivo óptimo ({params.l_obj} días) y el límite máximo sin demurrage ({params.l_max} días).",
            [
                ("Preventiva", f"Lead time total > {params.l_obj} días (alerta de demora menor)"),
                ("Crítica", f"Lead time total > {params.l_max} días (retraso severo con sobreestadía)"),
                ("EM proyectada", "La entrada a planta ocurre fuera del horizonte de planeación"),
                ("Diferido sin cupo", "Contenedor diferido por saturación de capacidad")
            ]
        ),
    ]
