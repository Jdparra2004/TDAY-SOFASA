# Modelo Matemático — Reto 7: Cadena de Suministro CKD Sofasa (Multi-Bodega: SOFASA + Suppla Rionegro)

## 1. Contexto y Alcance

El reto consiste en decidir, para cada contenedor CKD que llega al puerto, **cuándo debe entrar a planta (fecha EM — Entrada de Mercancía)** y **si debe pasar o no por almacenamiento temporal en la bodega externa Suppla (ubicada en Rionegro)**, de forma que:

- No se interrumpa la producción por falta de material (ruptura).
- Se respete el estándar de tiempo puerto → planta (7–10–12 días).
- Se minimicen los costos de demurrage y almacenamiento en Suppla.
- Se respeten las capacidades operativas semanales/diarias de recepción en SOFASA, recepción en Suppla y **días específicos de traslado Suppla (Rionegro) → SOFASA**, incorporando holguras flexibles (*soft capacity slacks*) para garantizar robustez y factibilidad ante picos de demanda real.

El flujo físico es:

```
PROVEEDOR → DESPACHO/TRÁNSITO → PUERTO → [¿capacidad en SOFASA?]
                                              │
                          SÍ ──────────────►  SOFASA (ingreso directo, EM) → PRODUCCIÓN
                                              │
                          NO ──────────────►  SUPPLA (Rionegro - almacenamiento temporal)
                                                        │
                                                        └──► Traslado programado (días permitidos) → SOFASA (EM) → PRODUCCIÓN
```

---

## 2. Parámetros Clave y Suppla (Rionegro)

- $CapSOFASA_t$: Capacidad máxima de recepción en planta SOFASA el día $t$ (por defecto 14 contenedores/día).
- $CapSUPPLA_w$: Capacidad máxima de recepción semanal en bodega Suppla (Rionegro) (por defecto 15 contenedores/semana).
- $CapTraslado_t$: Capacidad máxima de traslado Suppla → SOFASA el día $t$ (por defecto 3 contenedores/día).
- $TransferDays$: Días de la semana habilitados para realizar traslados desde Suppla (Rionegro) hacia la planta SOFASA (configurable por el usuario en la interfaz).

---

## 3. Función Objetivo y Decisiones Prescriptivas

El modelo de optimización (OR-Tools CP-SAT) minimiza el costo total ponderado, incorporando penalizaciones por violación de capacidad:

$$
\min Z = \underbrace{cst_{ruptura} \sum_c r_c}_{\text{rupturas}} \; + \; \underbrace{cst_{demurrage} \sum_c s_c}_{\text{demurrage}} \; + \; \underbrace{cst_{Suppla} \sum_{c: x_c=1} \big(EM_c - \textstyle\sum_t t\cdot z_{c,t}\big)}_{\text{almacenamiento Suppla}} \; + \; \underbrace{cst_{alerta} \sum_c \max(0,\, EM_c - ETA_c - L_{obj})}_{\text{alerta preventiva}} \; + \; \underbrace{cst_{cap} \sum (\text{slacks})}_{\text{flexibilidad de capacidad}}
$$

Sujeto a:
1. **Asignación de ruta y fecha EM** por contenedor (filtrando ventanas factibles dentro del horizonte).
2. **Capacidades de recepción y traslados** con holguras flexibles para evitar infeasibilidad ante picos de volumen.
3. **Salida Prescriptiva:** Generación de un cuadro de decisiones operativas detallado por contenedor (ruta, fecha de recepción en Suppla, día de traslado a planta y fecha EM).
