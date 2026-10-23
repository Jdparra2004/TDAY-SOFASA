# Modelo Matemático - Programación de Contenedores CKD (SOFASA y Suppla Rionegro)

Descripción de las reglas de negocio, las decisiones, las restricciones, la función objetivo y el cálculo de costos. Es una formulación descriptiva: el código (`src/optimization.py`, `src/costs.py`, `src/model.py`) es la fuente definitiva ante cualquier diferencia de detalle. Última actualización: 2026-10-23.

---

## 1. Problema

Para cada contenedor CKD que llega a puerto, decidir cuándo entra a planta (fecha EM, Entrada de Mercancía) y por qué ruta:

- **Directa:** puerto a SOFASA el día de la EM.
- **Vía Suppla:** puerto a la bodega externa Suppla (Rionegro) el día de recepción, y traslado a SOFASA el día de la EM.

```
PUERTO --> SOFASA (EM)                         [directo]
PUERTO --> SUPPLA (recepción) --> SOFASA (EM)  [vía Suppla, traslado en días habilitados]
```

Orden de prioridad (PDF del reto): 1) evitar la ruptura de producción, 2) cumplir el estándar puerto a planta, 3) evitar demurrage, 4) cumplir las capacidades, 5) preferir el ingreso directo para reducir movimientos y almacenamiento externo.

## 2. Parámetros

### 2.1 Controlados por el usuario (6)

| Símbolo | Parámetro | Defecto |
|---|---|---|
| día 0 | Fecha de planeación | 2026-10-20 |
| $H$ | Horizonte (días) | 20 |
| $Cap^{S}$ | Capacidad SOFASA por día | 14 |
| $Cap^{W}$ | Capacidad de recepción en Suppla por semana calendario | 15 |
| $Cap^{T}$ | Capacidad de traslado Suppla a SOFASA por día | 2 |
| $D_T$ | Días de la semana habilitados para traslado | lunes a viernes |

### 2.2 Constantes (en `Params`)

| Constante | Valor |
|---|---|
| $L_{min}$, $L_{obj}$, $L_{max}$ (días entre ETA y EM) | 7, 10, 12 |
| Días hábiles que se restan a la ruptura para fijar la EM objetivo | 2 |
| Demurrage por día | 80 USD |
| Almacenamiento Suppla por mes y contenedor de 40 pies | 1.049,17 USD |
| Días por mes para prorratear Suppla | 30 (34,97 USD por día) |
| Horizonte del solver $H_s$ | $H + L_{max}$ |
| Estancia mínima en Suppla | 1 día |
| Espera máxima desde la ETA para limitar el tamaño del modelo | 30 días |
| Límite de tiempo del solver | 60 s (120 s en la web) |
| Peso de ruptura por día / por evento | 1.000 / 500 |
| Peso de desviación respecto a la EM objetivo (por día) | 100 |
| Peso de alerta sobre $L_{obj}$ (por día) | 20 |

Todas las constantes son valores de referencia con variaciones reales; viven en un solo lugar para poder ajustarlas.

## 3. Universo y fechas clave

- **Excluidos:** contenedores con EM real anterior al día 0.
- **Fuera de ventana:** ETA posterior a $H - 1$ (siguiente planeación).
- **Programables:** el resto.
- **Ruptura:** solo existe con fecha real (Prioridades o DIEL). Sin ella no hay restricción ni se cuenta en los indicadores de ruptura.
- **EM objetivo:** con ruptura real, la fecha de ruptura menos 2 días hábiles; sin ella, ETA más $L_{obj}$.
- **ETA** puede ser anterior al día 0 (contenedor ya en puerto).

Los días se numeran desde el día 0 (día 0 = fecha de planeación).

## 4. Decisiones

Para cada contenedor programable $c$ con ETA $a_c$:

- Una de tres opciones: entrar directo el día $t$, entrar vía Suppla (recepción el día $r$, EM el día $t$), o quedar **diferido sin cupo** (no entra hasta $H_s$).
- Las fechas posibles están limitadas a una ventana por contenedor que empieza cerca de la ETA y termina como máximo en $H_s - 1$, y que siempre contiene la solución de la línea base.

Variables binarias (nombres descriptivos): directo en el día $t$; EM en el día $t$ vía Suppla; recepción en Suppla el día $r$; uso de Suppla; diferido.

## 5. Restricciones

1. **Una opción por contenedor:** exactamente una entre directo, vía Suppla o diferido.
2. **Recepción en SOFASA:** los contenedores con EM el día $t$ (directos y trasladados) no superan $Cap^S$.
3. **Traslados:** los contenedores trasladados de Suppla a SOFASA el día $t$ no superan $Cap^T$, y son cero en los días no habilitados ($t \notin D_T$).
4. **Recepción semanal en Suppla:** las recepciones de cada semana calendario no superan $Cap^W$. La semana calendario empieza el lunes, por lo que la primera semana puede ser corta según el día de la semana de la fecha de planeación.
5. **Mínimo puerto a planta:** $EM_c - a_c \ge L_{min}$.
6. **Estancia en Suppla:** para los contenedores vía Suppla, $EM_c - r_c \ge 1$.
7. **Ruptura:** con fecha de ruptura real $b_c$, los días de ruptura son $\max(0,\, EM_c - b_c)$. Sin fecha real no hay ruptura.

## 6. Función objetivo

El solver minimiza un objetivo ponderado, no solo dólares:

$$
\min \; 1000 \sum_c \text{díasRuptura}_c \;+\; 500 \sum_c \text{eventoRuptura}_c \;+\; 100 \sum_{c\,\text{con ruptura real}} |EM_c - EMobj_c| \;+\; 20 \sum_c \max(0,\, EM_c - a_c - L_{obj}) \;+\; \text{Demurrage (USD)} \;+\; \text{Suppla (USD)}
$$

- $\text{eventoRuptura}_c = 1$ si el contenedor tiene al menos un día de ruptura.
- La desviación respecto a la EM objetivo solo cuenta con ruptura real.
- Los costos de demurrage y Suppla entran en dólares; el coeficiente de Suppla se escala exactamente ($1049{,}17/30$ USD por día).
- Un día de ruptura (1.000) pesa unas 12 veces un día de demurrage (80). Por eso el plan puede subir los dólares y aun así bajar el objetivo.

Garantía: el plan devuelto nunca es peor que la línea base según `weighted_objective` (`src/costs.py`). Si el solver no la supera, se devuelve la línea base con estado `FALLBACK_LINEA_BASE`. Estados posibles: `OPTIMAL`, `FEASIBLE`, `FALLBACK_LINEA_BASE`, `SIN_SOLUCION`.

## 7. Cálculo del costo (indicador económico)

Una sola función (`compute_costs`) para la línea base y el plan optimizado. Para cada contenedor:

- **Salida de puerto** $s_c$: la EM si va directo; la recepción en Suppla si va vía Suppla.
- **Días en puerto** $= s_c - a_c$ (puede empezar antes del día 0).
- **Días de demurrage** $= \max(0,\; s_c - a_c - L_{max})$.
- **Demurrage** $= $ días de demurrage $\times 80$ USD.
- **Almacenamiento Suppla** $= (EM_c - r_c) \times 1049{,}17 / 30$ USD, solo vía Suppla.
- **Costo del indicador** $=$ demurrage $+$ Suppla.

### Ejemplos (línea base, Tracking 3nd Data)

| Contenedor | ETA | Ruta | Cálculo | Costo |
|---|---|---|---|---|
| SUDU6971194 | día -24 | directo, EM día 0 | 24 días en puerto, 12 sobre el límite | 960 USD |
| TCNU3886074 | día 4 | directo, EM día 20 | 16 días en puerto, 4 sobre el límite | 320 USD |
| SUDU6580939 | día 1 | Suppla día 13, EM día 31 | 12 días en puerto, 18 días en Suppla | 629,50 USD |

### Demurrage previo al día 0 y costo evitable

Parte del demurrage de los contenedores ya en puerto se acumuló antes del día 0 y ningún plan puede evitarla:

$$
\text{previo}_c = \max\big(0,\; \min(s_c, 0) - (a_c + L_{max})\big) \quad\text{(en días, si hay demurrage)}
$$

$$
\text{Costo evitable} = \text{Costo total} - 80 \times \sum_c \text{previo}_c
$$

El ahorro es costo de la línea base menos costo del plan optimizado, contra la línea base simulada, no contra el gasto histórico real.

### Qué no mide el indicador

- No incluye el beneficio de evitar rupturas de producción (solo dólares de demurrage y Suppla).
- Cuenta hasta el día en que cada contenedor entra a planta, aunque sea fuera del horizonte.
- El demurrage de un diferido se cuenta solo hasta $H_s$ (limitación: abarata diferir).

## 8. Indicadores y alertas del estándar puerto a planta

Con $\ell_c = EM_c - a_c$:

- $\ell_c < L_{min}$ (7): alerta de riesgo de incumplimiento operativo.
- $\ell_c > L_{obj}$ (10): alerta preventiva.
- $\ell_c > L_{max}$ (12): alerta crítica de demurrage.

También se informan las rupturas (solo con fecha real), el porcentaje por tipo de alerta, el porcentaje vía Suppla y los diferidos sin cupo, separados en bloque "dentro del horizonte" y bloque "EM proyectada".

## 9. Salida

Programación por contenedor (ruta, recepción en Suppla, EM plan, lead time, demurrage, alertas), capacidad utilizada por día en SOFASA, Suppla y traslados, contenedores con riesgo de demurrage y de ruptura (vía alertas), impacto económico y validaciones, exportables en un Excel de 10 hojas y en CSV.
