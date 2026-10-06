# ADR-006: Contrato de datos v0.1.0
- Estado: propuesto (pendiente revisión de Oscar Arce)
- Autores: Brian Leckie

## Contexto
F1 es bloqueante para todo lo demás, y hasta ahora `src/avm/contract/` estaba vacío. El reconocimiento de fuentes de F3.1 (`docs/sources.md`) fijó las restricciones que el contrato tiene que absorber:
- La fuente principal es Clasipar (§4). Trae la superficie y el barrio solo en texto libre (§2.5, §3). InfoCasas queda en suspenso por sus ToS (§1.2): el contrato no puede depender de una fuente estructurada.
- Las coordenadas no son confiables. En InfoCasas, 74 de 272 avisos comparten coordenadas idénticas con otro aviso (§1.5). En Clasipar vienen vacías en algunos avisos (§2.5).
- El barrio a veces es la ciudad: en InfoCasas para Luque, San Lorenzo y Fernando de la Mora (§1.5), y en la "Zona" de Clasipar (§2.5).
- En la muestra no apareció ningún precio sin moneda explícita (§5), pero la decisión del ADR-005 sigue pendiente.

Este ADR es una **propuesta**: todo lo que decide se puede cambiar en la revisión. El detalle campo por campo está en `docs/data_dictionary.md`, que se genera desde los schemas (F1.6).

## Decisión
1. **Tres schemas y un cuarto diferido.**
   - `RawListing` (F1.2): lo que devuelve un parser.
   - `Listing` (F1.3): limpio y tipado.
   - `PredictionRequest` / `PredictionResponse` (F1.5).
   - `FeatureRow` (F1.4) se difiere hasta F6.4, porque sus columnas dependen de las features geo y del encoding del barrio. Su módulo solo tiene un docstring que lo explica.
2. **`RawListing` es agnóstico de la fuente.** Todo su contenido es `str | None`, incluso los valores que el portal da estructurados (por ejemplo `"400"`). Así representa tanto una fuente con JSON (InfoCasas) como una de puro texto (Clasipar, §3). Lo que no tiene un campo propio va en `attributes_raw` (pares clave-valor: tags, ficha técnica). Los strings vacíos pasan a `null` (§2.4: JSON-LD con `""`), pero el contenido no se recorta.
3. **Procedencia por campo** (`Provenance`: `estructurado` / `texto`) para precio, moneda, m² construidos, m² de terreno, barrio y coordenadas. El valor y su procedencia van juntos: los dos o ninguno. Sirve para medir la calidad del pipeline por origen del dato y para la defensa.
4. **El alcance de ADR-002 lo garantizan los tipos.** `OperationType` solo tiene `venta`, y `PropertyType` y `City` solo tienen los valores incluidos. La categoría del portal se guarda aparte (`property_type_raw`), porque no garantiza el tipo real (§6.7).
5. **Amenities tri-estado** (`True` / `False` / `None`). Que un aviso no mencione la piscina no significa que no la tenga.
6. **Geo** (amplía el ADR-003):
   - `lat`/`lon` son opcionales y van juntas.
   - `GeoPrecision` suma un cuarto nivel, **`ciudad`**, para avisos sin coordenadas ni barrio normalizado.
   - Con coordenadas, la precisión solo puede ser `exacta` o `aproximada`. Sin coordenadas, `barrio` (que exige un barrio normalizado) o `ciudad`.
   - `ciudad` excluye un barrio normalizado: con `neighborhood_norm` la precisión es `barrio`.
   - `coordinate_flags` marca coordenadas sospechosas; hoy solo `compartidas` (§1.5). Unas coordenadas marcadas no pueden ser `exacta`, pero se conservan como `aproximada` (no se pueden bajar a `barrio` sin borrarlas: ver P2).
   - `PredictionRequest` no admite coordenadas: el formulario pide barrio (ADR-003).
7. **Barrio crudo y normalizado.** `neighborhood_norm` (nombre en el gazetteer) siempre va con su método (`exacto`, `alias`, `fuzzy`, `manual`). Si no matchea, queda `sin_match` y sin barrio normalizado, de modo que nada se asigna en silencio (F4.4). A propósito no se exige más: puede haber barrio normalizado sin crudo (asignación `manual` a partir de otro texto) y crudo sin método (todavía no se intentó normalizar).
8. **Precio** (ADR-004):
   - Siempre se guardan el monto y la moneda originales (`price_amount`, `price_currency`). `price_raw` se guarda cuando existe y es **obligatorio si la moneda es desconocida**, porque es lo que permite aplicar el ADR-005 después.
   - `price_usd` es derivado.
   - En PYG hacen falta la cotización (`fx_rate_pyg_per_usd`) y su fecha (`fx_date`), y `price_usd` tiene que cuadrar con ellas.
   - `is_from_price` ("desde", rangos) viaja hasta `Listing`.
9. **Moneda ausente: ADR-005 sigue abierto y el schema no lo cierra.** `price_currency` es obligatorio como campo, pero acepta `None`. Con `None` no hay `price_usd` ni cotización, y el builder del dataset (F8) solo usa filas con `price_usd`. Cada alternativa del ADR-005 entra sin romper nada:
   - **A (descartar):** solo cambia el pipeline, que deja de emitir esos avisos. El schema queda igual.
   - **D (moneda en otro campo del aviso):** se completa `price_currency` con `currency_provenance` `estructurado` o `texto`. El schema queda igual, pero se pierde trazabilidad: una moneda leída del string del precio y una sacada de la descripción quedan las dos como `texto`, y el ADR-005 advierte que la segunda puede referirse a otro monto. Si se elige D, conviene un valor de procedencia propio (ver P4).
   - **B (inferir por magnitud) o C (revisión manual):** se agrega `inferido` o `manual` a `Provenance`. Es un cambio **menor** (0.2.0): los datos viejos siguen validando. Como `Provenance` es compartido, esos valores quedarían válidos también para superficies, barrio y coordenadas. Si eso no se quiere, la alternativa es un enum propio para la procedencia de la moneda (P4).
   - Recién prohibir el `None` sería un cambio mayor, con ADR y migración.
10. **Datos personales.** **Todos** los schemas (la base `ContractModel`) rechazan el objeto si cualquier texto, incluidas las claves y valores de diccionarios, contiene un teléfono paraguayo, un email o un link de WhatsApp (patrones en `avm.contract.pii`). Así lo cubre también `Listing`, que es lo que se persiste. Ni el mensaje ni el input del error repiten el dato (`hide_input_in_errors`). Los nombres no se detectan con un regex: los quita el parser (F3.5). Ningún schema tiene campos de contacto, y `extra="forbid"` impide agregarlos.
11. **URL como `str` validado, sin normalizar.** Se exige http(s) absoluta y sin espacios, y se guarda idéntica al crudo para no complicar la deduplicación exacta de F5.1. Un test verifica que no cambia en el round-trip JSON.
12. **Fechas (decisión provisoria, P5).** `scraped_at` va en UTC, con zona horaria. El builder del dataset la convierte a fecha local `America/Asuncion`, porque `avm.model.splits` rechaza fechas con zona horaria (F8.2). Para el holdout temporal, la fecha de cada fila es la **fecha del snapshot** (la de `data/raw/<fecha>/` y su manifest), constante para toda la corrida, y no la conversión fila por fila de `scraped_at`: una corrida larga puede cruzar la medianoche y partir un mismo snapshot entre train y test.
13. **`cluster_id` fuera de `Listing` (decisión provisoria, P6).** Va en una tabla de mapeo aparte, `(source, source_id) → cluster_id`, que produce F5.3. Así el dedup se puede rehacer sin regenerar los `Listing`.
14. **Denominador del target (decisión provisoria, P13).** USD/m² se calcula sobre los **m² construidos**, y `PredictionRequest` exige `built_area_m2`. Se revisa con los datos de F7 (ver Consecuencias).
15. **Sin campo de target** en `Listing` (USD/m² se calcula en F8.1) ni campos de popularidad (por ejemplo, "Nro. de Visitas" de Clasipar, §2.5).
16. **Versionado (F1.8).** `CONTRACT_VERSION = "0.1.0"`.
    - Agregar un valor de enum o un campo opcional es un cambio **menor**.
    - Quitar o renombrar un campo o un valor, o volver obligatorio un campo opcional, es un cambio **mayor**, con ADR y migración.
    - `PredictionResponse` informa la versión del contrato con la que se generó.
17. **Convenciones.**
    - Modelos inmutables y sin campos extra.
    - Identificadores en inglés (CLAUDE.md) y valores de enum en español, porque son datos del dominio.
    - Montos y superficies de `Listing` en `Decimal`, como los devuelve `avm.pipeline.parsing`. Los valores de la API en `float`.

## Consecuencias
- **El denominador del target condiciona cuántos avisos tienen target.** Con USD/m² sobre m² construidos, un aviso sin `built_area_m2` no tiene target y no entra al entrenamiento.
  - En Clasipar la superficie solo aparece en texto (§2.5). En la validación de F3.1, de 22 strings de superficie (títulos de las 13 páginas filtradas y descripciones de los 3 detalles) solo 3 quedaron como `construida`, 2 como `terreno` y 17 sin tipo (§5, cifras corregidas el 2026-10-06: ver `docs/sources.md` §8.1).
  - Si F4.3 no logra resolver el tipo de superficie, el volumen con target puede ser bajo. La magnitud no se puede estimar con 3 detalles (§4) y queda para F3.4/F7.
  - Para departamentos, la superficie construida es la natural. Para casas no es obvio: el terreno pesa en el precio, y USD por m² construido mezcla el valor del lote con el de la construcción.
  - Si F7 muestra que conviene otra definición (m² de terreno para casas, una "superficie principal" por tipo, o modelar el precio total con las dos superficies como features), cambian F8.1 y `PredictionRequest`. Volver opcional `built_area_m2` o exigir otra superficie es un cambio de contrato con ADR.
- **`geo_precision=ciudad` amplía el ADR-003**, que hoy lista tres niveles. Si se acepta, hay que actualizar el ADR-003 y alinear F6.5. El modelo va a ver avisos con resolución de ciudad, que necesitan el fallback de F7.2.
- **`exacta` existe pero nada debería producirlo** hasta que alguna fuente demuestre coordenadas precisas (§1.5, §6.4).
- **Rechazar objetos con datos personales puede descartar avisos** si el regex da un falso positivo. Se prefirió fallar en lugar de enmascarar en silencio dentro del contrato. El sanitizador del parser (F3.5) tiene que correr antes. El regex tampoco es exhaustivo: no detecta, por ejemplo, un celular escrito sin el `0` inicial ("981 123 456").
- **El builder del dataset tiene responsabilidades explícitas:**
  - usar la fecha del snapshot para los splits (punto 12);
  - unir con la tabla de `cluster_id` exigiendo que **todas** las filas tengan cluster. Si falta alguno, tiene que fallar: rellenar con ids únicos convertiría duplicados en singletons. Además, guardar la versión del mapeo en el manifest del dataset y del modelo. La tabla de mapeo todavía no tiene schema: se define en F5.3 (`source`, `source_id`, `cluster_id`, versión del dedup);
  - filtrar las filas sin `price_usd` o sin `built_area_m2`;
  - **excluir los avisos con `is_from_price=True`** de train, validación, test y calibración (F9.2): su precio es una cota inferior, no un precio publicado, y sesga el target hacia abajo;
  - reportar cuántas filas descarta cada filtro (F4.7).
- **Riesgos de leakage para tareas posteriores** (leakage-auditor sobre esta propuesta). No afectan al contrato, pero se derivan de él:
  - **F4.6:** los rangos plausibles de USD/m² dependen del target. Tienen que fijarse a priori con justificación, o calcularse solo con el fold de train. Antes del split, solo reglas que no miren la distribución (un cero de más evidente, alquileres colados). También quedan para F4.6 los controles de plausibilidad que el contrato no hace: `fx_date` vs. `scraped_at`, `published_at` futura, coordenadas fuera del área (o `(0, 0)`) y cotizaciones absurdas.
  - **F5:** el mismo `(source, source_id)` en distintos snapshots tiene que forzar el mismo cluster aunque cambie el precio. Con la tolerancia de ±5 % de F5.2, una republicación con rebaja quedaría a los dos lados del split.
  - **`coordinate_flags=compartidas`** compara avisos entre sí. Se calcula por snapshot, solo con los avisos disponibles hasta esa fecha, y no se usa como feature.
  - **F4.4:** la revisión manual de barrios (`manual`) tiene que hacerse sin ver precio ni moneda.
  - **FeatureRow (F1.4):**
    - Ningún campo de precio, moneda, cotización, procedencia, trazabilidad o `is_from_price` puede ser feature.
    - Conviene que sus columnas salgan solo de `PredictionRequest` más datos externos (gazetteer, POIs), y que el target encoding y la mediana por barrio se calculen dentro del fold.
    - Hay que decidir el encoding de `None` en las amenities: en el aviso significa "no lo menciona" y en el request, "el usuario no respondió".
    - `built_area_m2` es legítima como feature, pero un intercambio construida↔terreno en F4.3 entra en la feature y en el target con signo opuesto. Conviene medirlo en F4.3 y F7.5.
- **`FeatureRow` sigue abierto** (F1.4). Hasta F6.4 no hay un schema para el input del modelo.

## Alternativas descartadas
- **Un `RawListing` con campos tipados (números, fechas).** Obliga a parsear dentro del parser de cada fuente y duplica la lógica de F4. Además, una fuente de texto libre dejaría casi todo en `null` sin conservar el crudo.
- **Un campo de procedencia global por aviso.** Un mismo aviso puede tener el precio estructurado y la superficie sacada del texto (§3), así que la procedencia tiene que ser por campo.
- **Amenities booleanas con default `False`.** Confunde "no lo menciona" con "no lo tiene" y sesga el modelo hacia la ausencia.
- **`url` como `AnyHttpUrl` de pydantic.** Normaliza la URL (en pydantic 2.13 pasa el host a minúsculas, agrega la barra final y codifica los espacios), así que ya no queda idéntica al crudo y complica la deduplicación exacta (F5.1).
- **`cluster_id` dentro de `Listing`.** Rehacer el dedup obligaría a regenerar todos los `Listing`, y mezcla una propiedad del aviso con una del dataset.
- **Asignar la moneda por defecto (USD o PYG) cuando falta.** Decide el ADR-005 de forma implícita, que es justo lo que ese ADR prohíbe como medida transitoria.
- **Enmascarar los teléfonos dentro del contrato.** Ocultaría fallas del parser; se prefiere un rechazo ruidoso.
- **Chequear datos personales solo en `RawListing`.** Dejaría sin garantía a `Listing`, que es lo que se persiste en `data/interim` y `data/processed`. La garantía dependería de que todo `Listing` venga de un `RawListing` validado, y el contrato no puede asegurarlo.
- **Definir `FeatureRow` ahora.** Obligaría a inventar columnas que dependen de F6.4.

## Preguntas abiertas para Oscar
Son decisiones provisorias de esta propuesta:
- **P13 (la más importante). Denominador del target:** ¿USD/m² sobre m² construidos, de terreno o una "superficie principal" según el tipo? Provisorio: construidos, con `built_area_m2` obligatorio en el request. Se revisa con F7 (ver Consecuencias).
- **P1.** ¿Se acepta el nivel `ciudad` en `GeoPrecision`? Si se acepta, hay que actualizar el ADR-003.
- **P2.** ¿Mantenemos `exacta` aunque hoy nada lo produzca, o lo sacamos hasta tener evidencia? ¿Y unas coordenadas marcadas `compartidas` se conservan como `aproximada` (actual) o se descartan y el aviso baja a `barrio`?
- **P3.** ¿Rechazo (actual) o enmascarado automático de datos personales? El regex no es exhaustivo (por ejemplo, no detecta "981 123 456" sin el `0`): ¿lo ampliamos a costa de más falsos positivos?
- **P4.** ¿Agregamos ya `inferido` y `manual` a `Provenance`, o cuando se decida el ADR-005? ¿Enum compartido (actual) o uno propio para la procedencia de la moneda, que además distinga "moneda en el string del precio" de "moneda en la descripción"?
- **P5 (provisoria, punto 12).** `scraped_at` en UTC y conversión a fecha local en el builder. ¿O fechas naive en hora local?
- **P6 (provisoria, punto 13).** `cluster_id` en una tabla de mapeo aparte. ¿O en `Listing` o en `FeatureRow`?
- **P7.** "desde N m²" (§5): ¿hace falta un flag de superficie "desde", como `is_from_price`?
- **P8.** `published_at` puede ser una fecha de republicación (§2.5). ¿Se usa en algo o queda solo informativa?
- **P9.** ¿`Source` como enum (sumar una fuente es un cambio menor) o como string libre?
- **P10.** ¿`Decimal` en `Listing` y `float` en la API, o unificamos?
- **P11.** La descripción queda solo en `RawListing`, por la cláusula de propiedad intelectual de Clasipar (§2.2) y para que `Listing` sea liviano. ¿La necesita algún paso posterior a F4.5?
- **P14.** `PredictionRequest` no admite lat/lon (ADR-003: el formulario pide barrio). CLAUDE.md pide lat/lon "opcionales en todos los schemas": ¿confirmamos que en el request se omiten, o las agregamos como opcionales? Si se agregan, las features por coordenadas de F6.5 podrían usarse también en producción.
- **P12.** Identificadores en inglés y valores en español. El ROADMAP usa nombres en español (`precio_usd`, `fecha_scrape`): ¿lo actualizamos?
