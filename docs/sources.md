# Fuentes de datos: reconocimiento (F3.1)

Relevamiento hecho el 5 de octubre de 2026 (hora de Paraguay) desde una IP residencial, con
`scripts/recon/`. No es un scraping: son pocas páginas para documentar qué ofrece cada portal.

- User-agent: `AVM-GranAsuncion-Academic/0.1 (proyecto universitario; contacto: https://github.com/brianleckie)`.
- 6 s entre requests, una a la vez, sin reintentos, tope de 25 requests por fuente (las fallidas
  también cuentan). Las URLs se validaron contra robots.txt antes de pedirlas.
- Requests usadas: **InfoCasas 19/25** (frenada por sus ToS, ver abajo) y **Clasipar 22/25**.
  No hubo ningún 403, 429 ni challenge.
- Todo lo que sigue sale de esas páginas. Lo que no se vio se marca como "no relevado". Los
  porcentajes son sobre la muestra indicada en cada caso, no sobre el portal entero.

**Decisión del equipo (5/10/2026):** los ToS de InfoCasas prohíben de forma expresa el acceso
automatizado. Se frenó esa fuente después de 19 requests: no se pidieron páginas de detalle, no se
guardaron fixtures y se borró el crudo local. La información de InfoCasas de este documento sale
de estadísticas agregadas calculadas antes del borrado.

---

## 1. InfoCasas (`www.infocasas.com.py`)

### 1.1 robots.txt
- Respondió 200. No declara `Crawl-delay`.
- 1773 líneas `User-agent:`, casi todas de una lista pública de "bad bots" con `Disallow: /`.
  Nuestro user-agent no coincide con ninguna.
- En el grupo `*` prohíbe, entre otras: `/venta/*-y-*`, `/proyectos/*-y-*`, `/alquiler/*-y-*`,
  `/sitio/?mid=propiedades*`, `/mobile/`, `/apps/` y rutas de administración. **Las búsquedas que
  combinan tipos (`/venta/casas-y-departamentos/...`) están prohibidas: cada tipo va con su
  propia URL.**
- Declara 18 sitemaps, entre ellos `sitemaps/properties-{1,2}-sitemap.xml` y `rss-listings`. El
  índice `sitemap.xml` está fechado el 2026-10-05.

### 1.2 Términos de uso (ToS)
`/informacion` redirige (301) a `/faq`, donde están los T&C. Cláusula **XVII. Prohibición de
scraping y uso automatizado**:
> "Se prohíbe expresamente: el uso de bots, crawlers o scrapers · la extracción masiva de datos ·
> la recolección sistemática de anuncios o contactos [...]. InfoCasas podrá: bloquear accesos ·
> iniciar acciones legales."

La política de cookies agrega que usan cookies para "detectar patrones de navegación inusuales" y
"bloquear herramientas automatizadas de extracción masiva de datos (scraping)".

### 1.3 URLs de búsqueda (venta)
- Patrón: `/venta/{tipo}/{departamento}/{ciudad}`. Asunción va sin departamento:
  `/venta/casas/asuncion`. Las ciudades de Central llevan `central/`: `/venta/casas/central/luque`.
- Tipos: `casas` (`property_type_id` 1), `departamentos` (2) y `duplex` (14).
- Paginación: `/venta/casas/asuncion/pagina2`, permitida por robots. 21 avisos por página, sin
  solapamiento entre las páginas 1 y 2 de casas en Asunción. Orden por defecto: "Popularidad".
- En las 13 páginas pedidas, los 21 avisos eran siempre del tipo, la ciudad y la operación pedidos.

Conteos. `paginatorInfo.total` sale de la búsqueda en vivo. "Texto SEO" sale del campo
`description` del JSON-LD `CollectionPage` de la misma página ("tenemos más de N ..."). **Los dos números no coinciden y la diferencia no va siempre
para el mismo lado**, así que ninguno sirve como volumen confiable sin verificarlo.

| Tipo | Ciudad | `paginatorInfo.total` | Texto SEO "más de" |
|---|---|---:|---:|
| casas | Asunción | 24 782 | 2 940 |
| casas | Luque | 7 737 | 8 083 |
| casas | San Lorenzo | 3 981 | 3 707 |
| casas | Fernando de la Mora | 3 606 | 5 725 |
| departamentos | Asunción | 45 427 | 1 228 |
| departamentos | Luque | 3 911 | 6 529 |
| departamentos | San Lorenzo | 834 | 4 586 |
| departamentos | Fernando de la Mora | 1 982 | 5 033 |
| dúplex | Asunción | 3 186 | 2 170 |
| dúplex | Luque | 4 385 | 8 122 |
| dúplex | San Lorenzo | 1 155 | 7 558 |
| dúplex | Fernando de la Mora | 1 551 | 2 036 |

### 1.4 Cómo vienen los datos
- **JSON embebido (Next.js).** `<script id="__NEXT_DATA__">` → `props.pageProps.fetchResult.searchFast`:
  - `data[]`: el objeto completo de cada aviso (precio, superficies, ubicación, coordenadas,
    descripción, fechas, ficha técnica). **El listado ya trae lo que normalmente aparece en el
    detalle.**
  - `paginatorInfo`: `{currentPage, lastPage, perPage, total, hasMorePages}`.
- `props.pageProps.apolloState` tiene un caché de Apollo/GraphQL. `props.runtimeConfig.API_URL`
  apunta a `https://graph.infocasas.com.uy`: hay una **API GraphQL interna**, referenciada pero
  **no explorada**.
- JSON-LD en el listado: `CollectionPage` + `ItemList` + `BreadcrumbList`.
- Detalle: la URL es `/{slug}/{id}` (campo `link`, ej. `/residencia-en-barrio-herrera/193495360`).
  **No relevado**, porque se frenó la fuente.

### 1.5 Matriz de campos
Muestra: 273 avisos únicos de los 13 listados. Paths relativos a `searchFast.data[i]`.
"Siempre" = 100 %, "casi siempre" ≥ 98 %, "a veces" entre 1 % y 98 %, "nunca" 0 %.

| Campo | Presencia | Path | Ejemplo crudo |
|---|---|---|---|
| precio | siempre (273/273, ninguno oculto) | `price.amount` | `2900000000` |
| moneda | siempre: 176 `U$S`, 97 `Gs.` | `price.currency.name` | `"Gs."` |
| precio en USD (calculado por el portal) | siempre | `price_amount_usd` | `494379` |
| m² construidos | a veces (266/273) | `m2Built` (también `m2`) | `400` |
| m² de terreno | a veces (152/273) | `m2Terrain` | `480` |
| dormitorios | a veces (246/273) | `bedrooms` | `4` |
| baños | casi siempre (270/273) | `bathrooms` | `5` |
| cocheras | a veces (195/273 no cero) | `garage` | `0` |
| barrio | siempre presente, pero **en Central es la ciudad** (ver nota) | `locations.neighbourhood[0].name` | `"Herrera"` |
| ciudad / departamento | siempre | `locations.state[0].name` + `neighbourhood` | `"Asunción"`, `"Central"` |
| lat/lon | casi siempre (272/273) | `latitude`, `longitude` (float) y `locations.location_point` (WKT) | `-25.302142` |
| descripción | casi siempre (271/273) | `description` | texto libre |
| fecha | siempre | `created_at`, `updated_at` (`YYYY-MM-DD`) | `"2026-03-11"` |
| id | siempre | `id` (y `code`, código alfanumérico) | `193495360` |
| operación | siempre | `operation_type.name` | `"Venta"` |
| tipo | siempre | `property_type.name` | `"Casa"` |
| amenities | a veces (236/273) | `facilities[]`, más campos de `technicalSheet[]` | lista |
| año de construcción | a veces (52/273) | `construction_year` | `null` |
| tipo de anunciante | casi siempre | `owner.type` | `"inmobiliaria"` |

Notas:
- **Barrio:** en los 189 avisos de Luque, San Lorenzo y Fernando de la Mora,
  `neighbourhood[0].name` es el nombre de la ciudad. En esos avisos el barrio estructurado no
  existe; habría que sacarlo de `address`, `title` o `description`. En Asunción sí trae barrios
  (Herrera, Mburucuyá, Recoleta...).
- **Precisión de lat/lon:** los decimales van de 3 a 15, así que la cantidad de decimales no
  indica la precisión. 74 de 272 avisos comparten coordenadas idénticas con otro aviso (18 puntos
  distintos): al menos esos no son la ubicación exacta del inmueble. El campo `pointType`
  (booleano) y `zoom` (14/15) no tienen significado documentado. **No se puede afirmar
  precisión "exacta".**
- En 10 casas `m2Built > m2Terrain`, que es plausible en casas de varias plantas, pero conviene
  controlarlo en F4.3.

### 1.6 Datos personales
- `owner.name`: nombre de la inmobiliaria y a veces del agente (ej. "marca - Nombre Apellido").
- `owner.whatsapp_phone`: **número completo, en 272/273 avisos, dentro del JSON del listado.**
  También `owner.masked_phone` (truncado), `owner.address` y `owner.subsidiaries[].masked_phone`.
- `seller`: id numérico (114/273), sin nombre.
- `description`: 9/273 (3 %) con un teléfono paraguayo en el texto. No se vieron emails.
- El parser de F3.4 tiene que descartar todo `owner.*` salvo `owner.type`.

### 1.7 Señales anti-bot observadas
- La cláusula XVII de los ToS y la política de cookies citada arriba.
- La lista de 1773 user-agents bloqueados en robots.txt.
- La cookie de sesión `PHPSESSIDIC` en robots.txt y los headers `X-Cache-Status` y
  `X-Debug-Server`. No se vio ningún challenge, captcha ni 429.

---

## 2. Clasipar (`clasipar.paraguay.com`)

### 2.1 robots.txt
- Respondió 200. No declara `Crawl-delay`.
- En el grupo `*` solo prohíbe `/error/`, `/app/` y `/config-paper/`. Bloquea por completo a
  `bingbot` e `ia_archiver`.
- Sitemap: `/sitemap/index.xml` (no relevado).

### 2.2 Términos de uso (ToS)
En `/reglas-de-uso` no hay una cláusula sobre acceso automatizado, bots ni scraping
(`/advertencia-legal` tampoco la tiene). Sí hay una de propiedad intelectual:
> "el acceso a los contenidos protegidos no autoriza al Usuario bajo ningún sentido, a alterar,
> modificar, explotar, reproducir, distribuir, comunicar públicamente, o de cualquier forma hacer
> uso de los mismos."

Afecta sobre todo a **reproducir** contenido (fixtures en un repo público, publicar el dataset).

### 2.3 URLs de búsqueda (venta)
- Patrón: `/inmuebles/{tipo}/intencion:vendo-t_s/localidad:{ciudad}-{id}`. Se armó a partir del JS
  de la página, que concatena `categoría + intención + localidad`.
- Tipos (categorías): `casas`, `departamentos` y `duplex`. Existe además
  `residencias-mansiones`, una categoría aparte que puede tener casas dentro del alcance
  (no relevada).
- Ciudades: `asuncion-3`, `luque-30`, `san-lorenzo-35` y `fernando-de-la-mora-23`.
- Paginación: `.../page-2`. Muestra 23 a 25 tarjetas por página, incluidas las de destacado y
  premium (en casas de Asunción: 6 `box-anuncio--destacado` y 7 `box-anuncio--premium`).
- En las 13 páginas pedidas, el 100 % de las tarjetas tenía la ciudad y la intención ("Vendo")
  pedidas en sus etiquetas estructuradas. Algunos títulos nombran otra ciudad (Lambaré, Itauguá):
  es una inconsistencia del anunciante, no del filtro.
- La navegación de páginas por JS hace antes un `POST /src/async/request` con un token. Es un
  endpoint interno, **no explorado**. Los links `/page-N` funcionan sin pasar por él.

Conteos ("N Resultados" visible en cada página):

| Tipo | Asunción | Luque | San Lorenzo | Fernando de la Mora |
|---|---:|---:|---:|---:|
| casas | 2 773 | 886 | 404 | 409 |
| departamentos | 3 592 | 237 | 67 | 154 |
| dúplex | 549 | 599 | 167 | 166 |

El total es de 10 003, sin deduplicar. Incluye avisos fuera de alcance publicados en esas
categorías: en la muestra hubo un terreno dentro de "casas" y un local comercial con vivienda.

### 2.4 Cómo vienen los datos
- **No hay `__NEXT_DATA__` ni estado inicial.** Es HTML renderizado del lado del servidor.
- **JSON-LD en el detalle** (`<script type="application/ld+json">`, schema.org `House` o
  `Apartment`; los dúplex salen como `House`). **Viene mal formado**: los strings tienen saltos de
  línea sin escapar, así que hay que leerlo con `json.loads(..., strict=False)`. Campos: `$.name`,
  `$.description`, `$.photo`, `$.latitude`, `$.longitude`, `$.numberOfRooms` y
  `$.numberOfBathroomsTotal`. Todos son strings y pueden venir vacíos (`""`). **No trae precio ni
  superficie.**
- HTML del detalle:
  - Precio: `h3.user-price`.
  - Ficha (`.anuncio-detalles`): pares `<span>Etiqueta</span> <h6>valor</h6>` con
    `Departamento`, `Ciudad`, `Nro. de Anuncio`, `Zona`, `Nro. de Visitas` y `Publicado el`.
  - Atributos: `span.ads_tag` → "Dormitorios: <strong>2</strong>", "Baños", "Habitación en
    suite", "Piscina", "Quincho"...
  - Descripción: `p.desc-user`. Título: `h1.tit-anuncio`.
- HTML del listado: `article.box-anuncio` → `a.titAnuncio` (título y URL), `p.price` (precio) y
  `h6` ("<strong>Vendo</strong> | Ofrecido por: <strong>Particular|Inmobiliaria</strong>" + link de
  ciudad).
- **Marca de agua:** el título y la descripción tienen `<span style="font-size:0 !important;"
  class="...">` con texto invisible ("Fuente del anuncio: URL", "Encontrá todo lo que
  necesitas"). La clase cambia en cada página (`3mmkjr8y`, `7kl0qmk`, `hk9lcj6x`), así que **el
  parser tiene que descartar estos spans por el estilo, no por la clase.**

### 2.5 Matriz de campos
Las tarjetas son 318 avisos únicos de los 13 listados. Los detalles son **solo 3**, así que en el
detalle "siempre/a veces" describe esa muestra, no el portal.

| Campo | Presencia | Path | Ejemplo crudo |
|---|---|---|---|
| precio | tarjeta: siempre (1/318 "Consultar precio."); detalle 3/3 | `p.price`, `h3.user-price` | `US$. 235.000,00` |
| moneda | dentro del string del precio: `US$.` o `Gs.` | idem | `Gs. 1.200.000.000` |
| m² construidos | **nunca estructurado**; a veces en título o descripción | texto libre | `Construcción: 90 m²` |
| m² de terreno | **nunca estructurado**; a veces en texto | texto libre | `Terreno: 180 m²` |
| dormitorios | detalle: a veces (tag 2/3; JSON-LD 2/3) | `span.ads_tag` "Dormitorios", `$.numberOfRooms` | `"2"` |
| baños | detalle: a veces (1/3) | tag "Baños", `$.numberOfBathroomsTotal` | `"1"` |
| cocheras | detalle: no visto estructurado (0/3); a veces en texto | descripción | — |
| barrio | detalle: 3/3 con "Zona", texto libre, a veces repite la ciudad | ficha "Zona" | `Villa Aurelia`, `Luque` |
| ciudad | siempre | tarjeta `h6 a`, ficha "Ciudad" | `Asunción` |
| lat/lon | detalle: a veces (2/3), strings | `$.latitude`, `$.longitude` | `"-25.3148..."` (15 decimales) |
| descripción | detalle 3/3 | `p.desc-user`, `$.description` | texto libre |
| fecha | detalle 3/3 | ficha "Publicado el" (`dd/mm/aaaa`) | `03/09/2026` |
| id | siempre | ficha "Nro. de Anuncio" = sufijo numérico de la URL | `2919242` |
| operación | tarjeta: siempre | `h6 strong` | `Vendo` |
| amenities | detalle: a veces, como tags | `span.ads_tag` | `Quincho: SI` |
| tipo de anunciante | tarjeta: siempre | "Ofrecido por" | `Particular` / `Inmobiliaria` |
| visitas | detalle 3/3 | ficha "Nro. de Visitas" | `35` |

Precisión de lat/lon: no se pudo evaluar con 2 casos. Que "Publicado el" sea la fecha original o
la de la última republicación es **no verificado**.

### 2.6 Datos personales
- **Detalle:** el nombre del anunciante (persona o asesor/inmobiliaria) está en
  `.infoAnunciante__header h5`, en `title`/`alt` de su imagen y en el slug de
  `/empresa/{nombre}-{id}`; el avatar del usuario está en `/users/...`. Teléfono y email aparecen
  enmascarados (`*********`, `*******@********`) y se revelan con "MOSTRAR LOS DATOS DE CONTACTO".
  El botón de WhatsApp/Llamar usa `r.phones_to_call`, que se carga por JS. No se vieron teléfonos
  en las descripciones de los 3 detalles.
- **Listado:** "Vendido por <a href=/empresa/...>Nombre</a>", y el logo con nombre en `alt`/`title`
  (en tarjetas premium).
- En el footer hay un email institucional (`@mic.gov.py`). No es personal, pero se reemplaza en
  los fixtures para que el test de PII no tenga excepciones.

### 2.7 Señales anti-bot observadas
- La marca de agua invisible con clase aleatoria por página.
- Los datos de contacto enmascarados, que requieren interacción (y para el mensajero, login).
- reCAPTCHA en los formularios (denuncia de aviso).
- El token en `POST /src/async/request`.
- No se vio ningún challenge, captcha bloqueante ni 429 en 22 requests a 6 s.

---

## 3. Tabla comparativa

| | InfoCasas | Clasipar |
|---|---|---|
| robots.txt | permite listados y detalles; prohíbe búsquedas `-y-` | permisivo |
| ToS sobre acceso automatizado | **prohibido expresamente (XVII)** | no lo menciona; prohíbe reproducir contenido |
| Formato | JSON embebido completo (`__NEXT_DATA__`) + GraphQL | HTML + JSON-LD mal formado e incompleto |
| Precio y moneda | estructurados (`amount` + `currency`) | string (`US$. 235.000,00`) |
| m² construidos / terreno | estructurados (97 % / 56 %) | solo texto libre |
| Barrio | estructurado en Asunción; **en Central es la ciudad** | "Zona", texto libre |
| lat/lon | 272/273, precisión dudosa (coordenadas compartidas) | 2/3 en JSON-LD |
| Datos personales | teléfono WhatsApp completo en el JSON del listado | nombres en HTML; contacto enmascarado |
| Volumen declarado (12 combinaciones) | inconsistente (`total` vs. JSON-LD) | 10 003 "Resultados" sin deduplicar |
| Bloqueos observados | ninguno (19 requests) | ninguno (22 requests) |

## 4. Recomendación

**Priorizar Clasipar para F3.2–F3.4 y no scrapear InfoCasas sin un permiso escrito.**

Fundamentos:
1. Es la única de las dos fuentes cuyo acceso automatizado no prohíben los ToS. robots.txt es
   permisivo y no se vieron bloqueos.
2. Sus filtros de tipo, operación y ciudad son estrictos en las etiquetas estructuradas (100 % en
   la muestra), y la paginación es una URL simple.
3. Declara volumen en las 12 combinaciones (10 003 resultados sin deduplicar), con
   Asunción > Luque > Fernando de la Mora ≈ San Lorenzo.

Riesgos de Clasipar:
- **La superficie viene solo en texto libre.** Esto pega en el target (USD/m²): habrá avisos sin
  m² o con m² ambiguos (construida vs. terreno). Cuántos: no medible con 3 detalles, se mide en
  F3.4/F4.3.
- **Barrio en texto libre ("Zona")**, a veces igual a la ciudad. Depende de F4.4 (gazetteer y
  fuzzy matching) y va a dejar avisos con precisión "ciudad".
- **Calidad del dato:** 17 de 415 precios con montos implausibles para una venta (ver §5),
  inmuebles fuera de alcance dentro de las categorías y títulos que nombran otra ciudad. Hacen
  falta las reglas de F4.6 y un filtro de tipo por texto.
- **Propiedad intelectual:** no publicar descripciones ni fotos, ni el dataset crudo. Los fixtures
  se recortaron y sanitizaron. Conviene revisarlo con el tutor.
- La marca de agua y el JSON-LD mal formado vuelven frágil al parser. Por eso los tests de F3.4
  van con fixtures reales.

InfoCasas tiene los datos más ricos (m² y coordenadas estructurados) pero su cláusula XVII lo
prohíbe. Si el equipo quiere usarla, el camino es pedir autorización a InfoCasas como proyecto
académico (su política de privacidad, en `/faq`, nombra como responsable a "Infocasas S.A."). Si la dan, el JSON embebido del listado alcanzaría sin pedir detalles.

**Pendiente:** el ROADMAP menciona "otras" fuentes; no se relevaron en esta tarea.

## 5. Validación de los parsers (adelanto F4.1/F4.3)

Se corrió `scripts/recon/validate_parsers.py` sobre los strings crudos reales. `parsing.py` no se
modificó. Se cuentan ocurrencias: un destacado que se repite en dos páginas cuenta dos veces.

**InfoCasas** (tarjetas de 13 listados; el JSON de la misma página sirve como control):
- `parse_price`: **273/273 strings parseados**. 272 coinciden en monto y moneda con
  `price.amount`/`currency`. El restante ("Desde U$S 73.244", `is_from_price=True`) es una tarjeta
  de proyecto cuyo monto no figura en el JSON: no se pudo emparejar.
- Formatos: `U$S 999.999`, `Gs. 9.999.999.999`, `Desde U$S 99.999`.
- `parse_area`: **267/267 parseados**. 266 coinciden con `m2`/`m2Built`; uno ("51 m²") no figura
  en esos campos (dato de la fuente). Todos con `kind=None`, porque la tarjeta muestra
  "135 m²" sin indicar si es construida o terreno (el JSON sí lo distingue).

**Clasipar** (tarjetas y 3 detalles; sin valores estructurados, revisión manual):
- `parse_price`: **414/415 parseados**. El único `None` es "Consultar precio.", que es el
  comportamiento esperado.
  - Formatos: `US$. 999.999,99` (coma decimal con centavos), `Gs. 999.999.999`.
  - Revisados a mano: en todos los casos el monto leído coincide con el string.
  - **17 strings tienen montos implausibles para una venta** (`US$. 1,00`, `US$. 999,99`,
    `Gs. 110`, `Gs. 1.500.000`...). No es un error del parser: van a tener que filtrarse en F4.6.
- `parse_area`: 23 strings con m² en títulos y descripciones; **23/23 con el número correcto**
  (revisión manual), incluido `1.213 m2` → 1213.
  - `kind`: 18 `None`, 3 `construida`, 2 `terreno`.
  - Uno dudoso: "940M2 C/ CONSTRUCCION" → `construida`, cuando probablemente se refiere al lote
    *con* construcción.
  - "desde 68 m2" se lee como 68, sin marca de "desde": `ParsedArea` no tiene ese flag.

**Datos para el ADR-005** (`currency=None`): de 688 strings de precio de las dos fuentes se
parsearon 687, y **ninguno** quedó con `currency=None`. Las dos publican la moneda explícita en el campo
del precio (InfoCasas además en un campo estructurado). En la muestra, el caso sin moneda no
aparece en el precio principal. Puede existir en otros lugares (descripciones) o en otras
fuentes. El ADR-005 no se modificó.

**Datos para el ADR-004** (moneda): InfoCasas 176 USD / 97 PYG (n=273). Clasipar 229 USD /
185 PYG (n=414). Son muestras de las primeras páginas, no proporciones del portal.

## 6. Implicancias para el contrato (F1)

Propuestas para discutir en F1. **Este documento no modifica `src/avm/contract/`**: cualquier
cambio lleva ADR.

1. **Precio crudo + estructurado.** `RawListing` debería guardar el string crudo del precio
   (Clasipar solo tiene eso) y, opcionalmente, el monto y la moneda estructurados cuando la fuente
   los da (InfoCasas). Rótulos de moneda vistos: `U$S`, `US$.`, `Gs.`.
2. **Superficies opcionales y con origen.** Los m² construidos y de terreno tienen que ser
   opcionales, por separado y con su procedencia (campo estructurado o texto libre), porque en
   Clasipar solo aparecen en texto y `kind` suele quedar indeterminado.
3. **Barrio opcional y crudo.** InfoCasas no da barrio en Central y Clasipar lo da como texto
   libre ("Zona"). `RawListing` debería conservar el texto crudo de ubicación (zona, dirección,
   título) para F4.4. Muchos avisos van a quedar con precisión "ciudad", un nivel que el
   ADR-003 no contempla hoy (`barrio | aproximada | exacta`).
4. **lat/lon opcionales y nunca "exactas" por defecto.** InfoCasas trae coordenadas compartidas
   entre avisos y Clasipar las trae vacías a veces. Apoya el ADR-003: sin validación, como mucho
   precisión `aproximada`.
5. **Fechas en formatos distintos:** ISO (`YYYY-MM-DD`) en InfoCasas y `dd/mm/aaaa` en Clasipar,
   con semántica (publicación vs. republicación) no verificada.
6. **Tipo de anunciante (particular/inmobiliaria)** está en las dos fuentes y no es un dato
   personal: candidato a campo. El nombre del anunciante **no** se persiste (CLAUDE.md, F3.5).
7. **Tipo de inmueble validado.** Las categorías del portal no garantizan el tipo: en Clasipar se
   vieron un terreno y un local dentro de "casas". Conviene guardar la categoría del portal aparte
   del tipo normalizado.
8. **Id de fuente** (`id` de InfoCasas, `Nro. de Anuncio` de Clasipar) para dedup dentro de la
   fuente (F5).

## 7. Decisiones abiertas
- InfoCasas: pedir autorización o descartarla definitivamente.
- Nombre de la inmobiliaria (empresa, no persona): en los fixtures se reemplazó por `[NOMBRE]`.
  Si sirve para deduplicar (F5), se decide en F3.5 si se persiste.
- Clasipar: si se incluye la categoría `residencias-mansiones`.
- Relevar otras fuentes.
- Actualizar los ADR propuestos con estos datos. No se modificaron en F3.1:
  - ADR-003: qué fuentes exponen lat/lon y con qué precisión (§1.5, §2.5, §6.4), y si hace
    falta un nivel de precisión "ciudad".
  - ADR-004: moneda por fuente (§5).
  - ADR-005: ningún `currency=None` en la muestra (§5).
- Fixtures: el código interno al final de algunas descripciones ("ID: 38434 vf") se dejó tal cual.
  Podría contener iniciales del agente; si el equipo lo prefiere, se reemplaza.

## Reproducir
```powershell
$env:PYTHONPATH = "scripts"
uv run --group scraping python -m recon.fetch clasipar <nombre>=<url> ...   # respeta tope y robots
$env:PYTHONPATH = "src;scripts"
uv run python -m recon.validate_parsers clasipar [--ver]
$env:PYTHONPATH = "scripts"
uv run python -m recon.sanitize clasipar <crudo>=<fixture> ...
```
El crudo y el ledger de requests quedan en `data/raw/recon/` (gitignored). El ledger tiene
InfoCasas marcada como bloqueada, así que el cliente rechaza cualquier request nueva a esa fuente.
