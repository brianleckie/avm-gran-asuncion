# ADR-002: Alcance: venta de casas, departamentos y dúplex en cuatro ciudades
- Estado: propuesto (pendiente revisión de Oscar Arce)
- Autores: Brian Leckie

## Contexto
El modelo estima el precio de oferta (ADR-001) por m² y el precio de oferta total de un inmueble. Un modelo hedónico por m² (F8) solo es defendible si todas las observaciones comparten la misma lógica de formación del precio; mezclar segmentos con lógicas distintas vuelve ininterpretables los coeficientes y el USD/m².

Además, el proyecto lo desarrollan dos personas con recursos acotados, y cada ciudad y cada tipo de inmueble agrega trabajo de scraping, normalización de barrios y features geo. El alcance tiene que ser el más chico que todavía responda la pregunta de investigación.

F1.1 del ROADMAP define un alcance base y sigue abierta hasta que este ADR se acepte.

## Decisión
**Incluido**
- Operación: venta.
- Tipos de inmueble: casa, departamento y dúplex (`duplex` en el código).
- Ciudades: Asunción, Luque, San Lorenzo y Fernando de la Mora.

**Excluido**, cada ítem por tener otra lógica de precio:
- **Terrenos.** No hay construcción: faltan los m² construidos y las features de edificación, y el precio queda determinado por el lote y su ubicación. Incluirlos mezclaría superficies de lote con superficies construidas dentro de un mismo USD/m².
- **Alquileres.** El precio es un flujo periódico, no el precio de compra de un activo. Mezclarlos introduce montos de otra escala y otra unidad (el ROADMAP ya los trata como "alquileres colados" en F4.6).
- **Locales comerciales.** El precio responde al uso comercial del inmueble y a la renta que puede generar, no a las características de una vivienda (dormitorios, baños, cocheras).
- **Quintas.** El valor está dominado por el terreno y por un uso que no es el de una vivienda urbana, de modo que los m² construidos informan poco sobre el precio.
- **Propiedades en pozo o preventa.** El precio corresponde a un inmueble que todavía no existe y depende de condiciones que no aparecen en un aviso comparable con una unidad terminada (plan de pagos, avance y plazo de entrega).

Las justificaciones describen la lógica de cada segmento en términos conceptuales; todavía no están cuantificadas ni respaldadas con datos propios. [dato pendiente de F3.1/F7]

## Consecuencias
- **Menos volumen.** Cada exclusión descarta avisos. Cuántos, por exclusión y por ciudad: [dato pendiente de F3.1/F7].
- **Las exclusiones se aplican filtrando, y el filtro puede fallar.** Cada portal categoriza los avisos con sus propias etiquetas y puede clasificar mal un inmueble (por ejemplo, una quinta publicada como casa). La regla concreta de filtrado (qué campo y qué señales usar) se define con lo que se observe en F3.1 y se implementa en F3.3 y F4.6. [pendiente de F3.1]
- **El modelo no aplica fuera de este alcance.** El schema de request (F1.5) y el formulario (F12.1) solo deberían aceptar los tipos y las ciudades incluidos, y la documentación tiene que decir que no hay estimaciones para el resto.
- **Debe figurar en limitaciones** (F15.2), en la UI y en la defensa.
- **Ampliar el alcance cambia el contrato** (los valores admitidos de tipo y ciudad), así que requiere un ADR nuevo y una nueva versión del contrato (F1.8).
- **Inconsistencia con el ROADMAP.** F1.1 solo deja afuera terrenos y alquileres. Si este ADR se acepta, F1.1 debe actualizarse para incluir también locales comerciales, quintas y propiedades en pozo o preventa. Este ADR no modifica el ROADMAP.

## Alternativas descartadas
- **Un único modelo para todos los tipos y operaciones, con el tipo como variable.** Más datos, pero mezcla lógicas de precio y le quita sentido al modelo hedónico interpretable (F8.4).
- **Un modelo aparte para terrenos (o para alquileres).** Es otra pregunta de investigación; queda como posible extensión futura, fuera de este proyecto.
- **Incluir pozo y preventa con un flag.** Mantiene el volumen, pero obliga a modelar condiciones de pago y de entrega que los avisos no traen de forma sistemática. [pendiente de F3.1: qué fuentes marcan estos avisos]
- **Sumar más ciudades del área metropolitana.** Cada ciudad nueva exige gazetteer, normalización de barrios y POIs propios, y agrava la cobertura despareja que el ROADMAP ya identifica en San Lorenzo y Fernando de la Mora. [dato pendiente de F7: cobertura por ciudad]
