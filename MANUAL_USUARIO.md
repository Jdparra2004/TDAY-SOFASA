# Manual de Usuario - Optimizador de Programación de Contenedores CKD (Renault-Sofasa)

Guía para usar la aplicación web: cargar los archivos, configurar los parámetros, ejecutar la optimización, leer los resultados y descargar el plan. Última actualización: 2026-10-23.

---

## 1. Para qué sirve

La aplicación propone, para cada contenedor CKD en puerto o en tránsito, el día en que debe entrar a la planta SOFASA (EM) y si debe ir directo o pasar por la bodega Suppla (Rionegro). Prioriza evitar rupturas de producción, respeta las capacidades de la operación y reduce el demurrage y el almacenamiento externo.

## 2. Ingreso

1. Abra la dirección de la aplicación.
2. Escriba la contraseña corporativa y pulse "Ingresar al Sistema".
3. Si la contraseña es incorrecta, la aplicación lo informa y permite reintentar. Si aparece un mensaje de configuración de autenticación faltante, comuníquese con el administrador.

## 3. Pantalla de inicio

Hay dos modos:

- **Proceso Manual / Inserción Interactiva:** para probar con pocos contenedores escritos a mano.
- **Proceso por Lote (Excels Puros):** para trabajar con los archivos oficiales. Es el modo de uso normal.

En ambos modos el botón "Volver al Inicio" regresa a esta pantalla.

## 4. Parámetros de planeación

Son los mismos seis en los dos modos. Son los únicos que usted controla.

| Parámetro | Qué significa | Defecto |
|---|---|---|
| Fecha de planeación (día 0) | Primer día del horizonte. También fija con qué día de la semana arranca el calendario | 2026-10-20 |
| Horizonte (días) | Entran los contenedores con ETA entre el día 0 y el último día del horizonte | 20 |
| Capacidad SOFASA por día | Máximo de contenedores que entran a planta por día | 14 |
| Capacidad Suppla por semana | Máximo de contenedores que se reciben por semana calendario en Suppla | 15 |
| Capacidad de traslado por día | Máximo de contenedores trasladados de Suppla a SOFASA por día | 2 |
| Días habilitados de traslado | Días de la semana en que se permite el traslado de Suppla a SOFASA | Lunes a viernes |

Los demás valores del modelo (mínimo 7, objetivo 10 y máximo 12 días entre ETA y EM, costos por día, etc.) son fijos y no se editan en la pantalla.

Debajo de los parámetros está el desplegable "Guía rápida y glosario de términos", con la definición de cada término.

## 5. Proceso por lote

### 5.1 Cargar archivos

- **Tracking de Contenedores (obligatorio):** define el universo de contenedores.
- **Programación DIEL:** aporta fecha de ruptura y EM previa.
- **Prioridades CKD:** aporta fecha de ruptura y EM previa (acepta también `.xlsm`).

Sin fecha real de ruptura el contenedor no se considera en riesgo de ruptura. Por eso conviene cargar DIEL y Prioridades.

### 5.2 Ejecutar

Pulse "Procesar y ejecutar pipeline completo". Si no cargó el Tracking, aparece una advertencia. La ejecución clasifica el universo, simula la línea base y optimiza el plan; tarda alrededor de 2 minutos. No cierre ni recargue la página mientras corre.

Al terminar aparece "Pipeline completado" y los resultados debajo.

## 6. Proceso manual

1. Complete los parámetros.
2. En "Registrar contenedor" escriba el ID, el buque, la familia de partes, la ETA y, si la hay, la fecha de ruptura (déjela vacía si no existe una fecha real).
3. Pulse "Agregar a la lista". No se permiten IDs repetidos.
4. "Cargar ejemplos" llena la lista con cinco contenedores de muestra. "Limpiar lista" la vacía.
5. Pulse "Simular y optimizar". Los resultados aparecen debajo con el mismo formato que en el modo por lote.

## 7. Cómo leer los resultados

### 7.1 Universo de contenedores

Muestra cuántos contenedores trae el Tracking y cómo se reparten:

- **Excluidos (EM real < día 0):** ya entraron a planta; no se programan.
- **Fuera de ventana:** llegan después del horizonte; se programan en la siguiente planeación.
- **Programables:** los que optimiza la aplicación.
- **Con ruptura real / sin:** cuántos programables tienen fecha real de ruptura.

El desplegable "Detalle y descargas por bloque" lista cada grupo con su motivo y permite descargarlo en CSV, incluidos los IDs de DIEL y Prioridades que no están en el Tracking.

### 7.2 Resultado: línea base frente a plan optimizado

La **línea base** es lo que daría una programación sencilla sin optimizar. El **plan optimizado** es la propuesta del modelo.

**Aviso del solver:**

- *Solver OPTIMAL:* el plan es el mejor posible.
- *Solver FEASIBLE:* el plan es válido y mejor que la línea base, pero no está probado como óptimo (se muestra el gap, la distancia estimada al óptimo). Es lo normal. Las cifras de costo y rupturas pueden cambiar entre ejecuciones y no deben usarse como cifra oficial.
- *Línea base como plan:* el solver no encontró un plan mejor que la línea base y se muestra la línea base.
- *Error:* no se obtuvo un plan; revise datos y parámetros.

**Tabla de indicadores**, separada en "Dentro del horizonte" y "EM proyectada (fuera del horizonte)": cantidad de contenedores, porcentaje en el objetivo, porcentaje sobre el máximo, rupturas y lead time promedio (días entre ETA y EM).

**Cuatro indicadores resumen:**

- Rupturas (base a óptimo): contenedores con ruptura real.
- % sobre el máximo: contenedores con más de 12 días entre ETA y EM.
- Vía Suppla: porcentaje de contenedores que pasan por Suppla.
- Diferidos sin cupo: contenedores que no encuentran cupo hasta el final del cálculo.

**Capacidad máxima usada frente a capacidad:** para SOFASA por día, Suppla por semana y traslados por día, en base y óptimo. Nunca debe superar la capacidad configurada.

### 7.3 Impacto económico

- **Costo línea base y costo plan optimizado (USD):** demurrage (80 USD por contenedor y por día después de 12 días en puerto) más almacenamiento en Suppla (1.049,17 USD por mes por contenedor de 40 pies, prorrateado por día).
- **Diferencia en demurrage + Suppla (USD):** costo base menos costo óptimo. Es una diferencia solo en dólares de esos dos conceptos; no es el beneficio total del plan. Si es negativa, el plan cuesta más dólares.
- **Previo al día 0 (inevitable):** demurrage que los contenedores ya en puerto acumularon antes del día 0. Es igual en ambos planes y nadie puede evitarlo.
- **Costo evitable base y óptimo:** el costo total menos lo inevitable. Es la parte que el plan realmente controla.
- **Rupturas evitadas:** contenedores con ruptura real en la línea base menos los del plan optimizado.

Cuando la diferencia es negativa y hay rupturas evitadas, la aplicación lo explica: el plan prioriza evitar rupturas sobre el costo en dólares, según el orden de prioridad definido, e indica el costo neto por ruptura evitada.

Un desglose detallado muestra días y USD de demurrage, contenedores vía Suppla, días y USD de Suppla y el promedio de días en Suppla.

### 7.4 Vistas de resultados

Elija con el selector:

- **Decisiones por contenedor:** tabla paginada (100 filas por página) con la ruta, la recepción en Suppla, la EM del plan, el lead time, los costos y las alertas de cada contenedor. Desde aquí se descarga el plan en Excel y en CSV.
- **KPI Dashboard:** barras de cumplimiento del estándar de tiempo, rupturas, porcentaje vía Suppla y costo en USD, y la curva de ocupación de Suppla.
- **Diagrama de flujo (Sankey):** muestra cómo se reparten los contenedores entre ruta directa o vía Suppla y su resultado frente a la ruptura. Puede filtrar por contenedor. Un símbolo "⏭" junto al ID indica EM proyectada (el contenedor llega dentro del horizonte pero entra después, por capacidad).

## 8. Alertas del estándar puerto a planta

Se calculan con los días entre la ETA y la EM:

| Condición | Alerta |
|---|---|
| Menos de 7 días | Riesgo de incumplimiento operativo: por debajo del tiempo mínimo estándar puerto-planta |
| Más de 10 días | Alerta preventiva: por encima del estándar objetivo |
| Más de 12 días | Alerta crítica: riesgo de demurrage, supera el máximo permitido en puerto |

Cada contenedor del Excel muestra sus alertas junto con su estado de ruptura (fecha real, sin fecha real) y si su EM es proyectada.

## 9. Archivo Excel descargable

El archivo `plan_prescriptivo_sofasa.xlsx` tiene 10 hojas:

1. **Programacion semanal:** decisión por contenedor.
2. **Impacto económico:** costos de base y óptimo, bloques, costo evitable y rupturas.
3. **Capacidad diaria:** uso de SOFASA, Suppla y traslados por día, frente a la capacidad.
4. **EM proyectada (fuera horizonte):** contenedores que entran después del horizonte.
5. **Excluidos (ya en planta).**
6. **Fuera de ventana.**
7. **No están en Tracking:** IDs de DIEL y Prioridades ausentes del Tracking.
8. **Embudo del universo.**
9. **Validaciones:** 17 controles automáticos de consistencia; todos deben estar en OK.
10. **Parámetros:** los seis parámetros usados y las constantes del modelo.

En la hoja de capacidad diaria, "Capacidad Suppla por semana" se refiere a recepciones; la ocupación de Suppla es el inventario acumulado y puede superar ese número.

## 10. Preguntas frecuentes

**¿Por qué el plan optimizado cuesta más dólares que la línea base?**
El modelo no minimiza solo dólares. Cada día de ruptura de producción pesa unas 12 veces un día de demurrage, por lo que acepta pagar más demurrage con tal de evitar rupturas. Revise "Rupturas evitadas" y el costo neto por ruptura evitada.

**¿Por qué cada ejecución da cifras un poco distintas?**
El solver trabaja con un tiempo límite y no siempre llega al óptimo probado. Con los mismos datos puede devolver planes distintos. Use las cifras como plan de referencia y, para una cifra más estable, solicite una ejecución local de mayor duración al equipo técnico.

**¿Por qué el costo incluye dinero de antes del día 0?**
Los contenedores que ya estaban en puerto acumularon demurrage antes de la fecha de planeación. Esa parte se informa como "previo al día 0" y no depende del plan.

**¿Qué significa EM proyectada?**
El contenedor llega dentro del horizonte, pero por capacidad entra a planta después del último día del horizonte. Se muestra con su fecha proyectada.

**¿Qué hago con los diferidos sin cupo?**
Son contenedores que no encuentran cupo hasta el final del cálculo. Revise sus fechas y considere ampliar capacidades o el horizonte.

**¿Se ven las validaciones en pantalla?**
No. Están en la hoja "Validaciones" del Excel y en la consola del equipo técnico.

**La aplicación se demora o se detiene.**
La ejecución del lote tarda unos 2 minutos. Si aparece un mensaje de error, anote su texto completo y avise al equipo técnico.
