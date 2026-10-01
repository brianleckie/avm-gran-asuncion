# ADR-005: Precios sin moneda explícita (`currency=None`)
- Estado: propuesto (pendiente revisión de Oscar Arce)
- Autores: Brian Leckie

## Contexto
`parse_price` (`src/avm/pipeline/parsing.py`, adelanto de F4.1) devuelve `currency=None` cuando el texto del precio no trae una moneda explícita. Incluye el caso de un `$` solo, que el parser no interpreta como dólares. Tampoco intenta adivinar la moneda por la magnitud del monto: esa decisión se dejó al pipeline y quedó anotada como pendiente en el ROADMAP, bajo F4.2.

Una moneda mal asignada no es un error marginal: cambia la escala del precio. Contamina el target (F8.1), dispara reglas de outliers (F4.6) y puede romper la comparación de precios entre avisos en la deduplicación (F5.2).

Cuántos avisos caen en este caso, y cómo se ven sus strings crudos: [dato pendiente de F3.1].

## Decisión
**Pendiente. Se decide con datos de F3.1.** Este ADR no elige ninguna alternativa.

Los datos que hacen falta para decidir, todos [dato pendiente de F3.1]:
- La proporción de avisos con `currency=None`, por fuente y por ciudad.
- El formato crudo de esos strings (por ejemplo, si traen un `$` solo o únicamente el número).
- Si el portal expone la moneda en otro campo del aviso (un campo estructurado, el título o la descripción).
- La distribución de los montos crudos por ciudad en los avisos con moneda explícita, para saber si las escalas de cada moneda se separan lo suficiente.

## Consecuencias
- **Medida transitoria, no una preferencia entre alternativas:** mientras la decisión esté pendiente no se asigna moneda de forma implícita. `currency=None` se preserva, y F4.2 solo convierte los avisos con moneda explícita.
- **El tratamiento intermedio de esos avisos lo define la implementación de F4.2**, de modo que la decisión de este ADR se pueda aplicar después sin volver a scrapear. Para eso se conserva el texto crudo del precio (F1.2).
- **Este ADR se actualiza** (estado y decisión) cuando F3.1 aporte los datos, y si corresponde se ajustan F4.2 y F4.6. También pueden aportarlos los fixtures reales de F3.4.

## Alternativas descartadas
Todavía no se descartó ninguna. Se listan las candidatas con sus ventajas y desventajas; pueden combinarse y este ADR no pre-selecciona una combinación.

**A. Descartar el aviso.**
- A favor: es simple y auditable, y no existe riesgo de asignar una moneda equivocada.
- En contra: pierde volumen (cuánto: [dato pendiente de F3.1]). Si los casos se concentran en una fuente, una ciudad o un segmento, introduce un sesgo muestral (F7.3), y habría que reportar el porcentaje descartado (F4.7).

**B. Inferir la moneda por la magnitud, con umbrales por ciudad.**
- A favor: recupera volumen, y es automático y reproducible.
- En contra: una moneda mal asignada cambia la escala del precio. Los umbrales dependen de la distribución de precios de cada ciudad [dato pendiente de F3.1/F7], y es posible que exista una zona de solape donde ambas monedas sean plausibles, que los umbrales no resolverían. [dato pendiente de F3.1/F7]
- Riesgo de leakage: los umbrales se derivan de la distribución de precios, es decir, de información del target. Si se calculan sobre todo el dataset, filtran información de los folds de validación y test (principio 4 del ROADMAP). Tendrían que calcularse solo con el fold de entrenamiento, o fijarse a priori con una justificación que hoy no existe. El mismo argumento vale para cualquier umbral derivado de la distribución de precios, como los rangos plausibles de USD/m² por ciudad de F4.6. Además, umbrales por ciudad multiplican parámetros en ciudades con pocos avisos.

**C. Revisión manual.**
- A favor: es la más fiable caso por caso, y permite aprender cómo cada fuente escribe sus precios.
- En contra: no escala, porque el equipo son dos personas (cuántos casos: [dato pendiente de F3.1]). Las decisiones manuales son subjetivas, así que tendrían que guardarse en un archivo versionado para que el dataset siga siendo reproducible (principio 6 del ROADMAP).

**D. Buscar la moneda en otro campo del aviso antes de recurrir a A, B o C.**
- A favor: usa información que el propio aviso ya trae, sin estimaciones, y podría recuperar volumen sin los riesgos de B.
- En contra: depende de lo que exponga cada fuente y podría no resolver todos los casos ni ser homogénea entre fuentes; una moneda mencionada en texto libre podría referirse a otro monto. [pendiente de F3.1]
- No es excluyente con las anteriores.
