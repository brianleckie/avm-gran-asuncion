# ADR-004: Normalización de moneda: target en USD con cotización de la fecha del scrape
- Estado: propuesto (pendiente revisión de Oscar Arce)
- Autores: Brian Leckie

## Contexto
Los avisos pueden publicar su precio en dólares o en guaraníes; el ROADMAP ya lista la moneda mixta como un riesgo conocido (F4.2). La proporción de avisos por moneda y por fuente: [dato pendiente de F3.1/F7].

El target del modelo es `log(USD/m²)` (F8.1), así que todos los precios tienen que expresarse en una misma moneda. Convertir no cambia la naturaleza del dato: sigue siendo un precio de oferta (ADR-001).

## Decisión
1. **El target y la unidad de modelado son USD.**
2. **Los precios en PYG se convierten a USD con la cotización de la fecha del scrape** del aviso (`fecha_scrape`, F1.2). La cotización usada (valor, fuente y fecha) se registra junto al snapshot, lo que extiende el manifest de F3.7, que hoy solo describe conteos y hash. Si un snapshot abarca varios días (modo incremental, F3.6), falta definir si rige la fecha de cada aviso o una fecha única del snapshot. [pendiente de definir en F3.6/F3.7 y F4.2]
3. **Siempre se guardan el monto y la moneda originales.** El monto en USD es un campo derivado y nunca reemplaza al original (F4.2). Un aviso que ya está en USD no se convierte.
4. **La fuente oficial de la cotización y cuál de sus cotizaciones se usa (compra, venta u otra) quedan a confirmar en implementación (F4.2).** F4.2 del ROADMAP menciona la cotización del BCP; este ADR no confirma esa fuente ni fija ninguna URL o serie.
5. Los avisos sin moneda explícita quedan fuera de esta decisión (ADR-005).

## Consecuencias
- **El USD de un aviso en PYG depende de la fecha del scrape, no de la de publicación.** Un aviso publicado antes del scrape se convierte con la cotización del scrape. Si el tipo de cambio varió entre ambas fechas, el monto en USD difiere del que correspondía al publicarse. Magnitud del efecto: [dato pendiente de F3.1/F7: antigüedad de los avisos y variación de la cotización].
- **Con snapshots sucesivos, el mismo aviso en PYG puede cambiar de valor en USD** solo por la cotización. Hay que tenerlo presente al interpretar el holdout temporal (F8.2) y cualquier comparación entre snapshots.
- **La incertidumbre de la conversión se concentra en los avisos en PYG.** Conviene reportar el error por moneda de origen, además de los segmentos de F10.4.
- **Reproducibilidad.** Sin la cotización guardada junto al snapshot, el target de ese snapshot no se puede reconstruir. Con el monto y la moneda originales siempre disponibles, se puede reconvertir sin volver a scrapear.
- **Dónde se guardan el monto y la moneda originales** (en `RawListing`, en `Listing` o en ambos) se define en F1. Hoy F1.3 lista solo `precio_usd` en `Listing`: si hicieran falta campos nuevos, sería un cambio de contrato que requiere ADR y nueva versión (F1.8). [pendiente de F1]
- **Cambiar la fuente o la regla de cotización cambia el target de todo el histórico.** Requiere un ADR nuevo y regenerar los snapshots.

## Alternativas descartadas
- **Target en PYG.** Los avisos en USD también habría que convertirlos, así que la conversión no se evita. USD es una decisión del equipo (F8.1), no una conclusión empírica; la proporción de avisos por moneda puede reabrir la pregunta. [dato pendiente de F3.1/F7]
- **Cotización de la fecha de publicación del aviso.** Es más fiel en teoría, pero necesita una fecha de publicación confiable en cada aviso y una serie histórica de cotizaciones. [pendiente de F3.1: qué fuentes exponen la fecha de publicación]
- **Una cotización fija para todo el dataset.** Es simple y estable, pero queda desactualizada respecto de la fecha del scrape y borra la variación entre snapshots.
- **Promedio de la cotización sobre una ventana de fechas.** Suaviza el ruido, pero agrega un parámetro (el tamaño de la ventana) sin criterio disponible para elegirlo.
