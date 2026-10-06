# Diccionario de datos

Contrato v0.1.1, PROPUESTA pendiente de revisión (docs/adr/006-contrato-v0.1.md).

**Archivo generado** por `scripts/gen_data_dictionary.py` desde `src/avm/contract/`: no
editarlo a mano. Las reglas entre campos (por ejemplo, valor y procedencia van juntos)
están en los docstrings de `src/avm/contract/` y en el ADR-006; el JSON Schema no las
expresa.

## Enums

| Enum | Valores | Descripción |
|---|---|---|
| `AdvertiserType` | `particular`, `inmobiliaria` | Tipo de anunciante. No es un dato personal: el nombre nunca se guarda. |
| `City` | `asuncion`, `luque`, `san_lorenzo`, `fernando_de_la_mora` | Ciudades del alcance (ADR-002). Cualquier otra ciudad es inválida. |
| `CoordinateFlag` | `compartidas` | Señales de que unas coordenadas no son la ubicación real del inmueble. `compartidas`: idénticas a las de otro aviso distinto (F3.1, docs/sources.md §1.5). |
| `Currency` | `USD`, `PYG` | Monedas observadas en F3.1 (docs/sources.md §5). |
| `GeoPrecision` | `exacta`, `aproximada`, `barrio`, `ciudad` | Resolución de la ubicación del aviso (ADR-003, ampliado por ADR-006 con `ciudad`). - exacta / aproximada: hay coordenadas; `exacta` solo si se validó la precisión de la fuente. - barrio: sin coordenadas, con barrio normalizado. - ciudad: sin coordenadas ni barrio normalizado (F3.1: avisos donde el "barrio" es la ciudad). |
| `NeighborhoodMatch` | `exacto`, `alias`, `fuzzy`, `manual`, `sin_match` | Método con el que se normalizó el barrio (F4.4). Nada se asigna en silencio. |
| `OperationType` | `venta` | Operación del alcance (ADR-002). Solo venta: un alquiler es inválido por construcción. |
| `PropertyType` | `casa`, `departamento`, `duplex` | Tipos de inmueble del alcance (ADR-002). |
| `Provenance` | `estructurado`, `texto` | De dónde salió un valor: un campo del portal o texto libre (título, descripción). |
| `Source` | `clasipar`, `infocasas`, `sintetico` | Portal de origen del aviso. `sintetico` es el generador de F2. |
| `StreetSurface` | `pavimento`, `empedrado`, `tierra` | Superficie de la calle (F4.5). |
| `WarningCode` | `barrio_desconocido`, `fallback_ciudad`, `pocos_datos` | Advertencias de una predicción (F11.3, F7.2, F9.4). |

## RawListing

Aviso tal como lo extrae el parser de una fuente.

| Campo | Tipo | Obligatorio | Admite null | Default | Validaciones | Descripción |
|---|---|---|---|---|---|---|
| `source` | `Source` | sí | no |  |  |  |
| `source_id` | string | sí | no |  | no vacío | Id del aviso en la fuente (dedup exacto, F5.1). |
| `url` | string | sí | no |  | URL http(s) absoluta, sin espacios, sin normalizar | URL del aviso, idéntica al crudo (sin normalizar). |
| `scraped_at` | date-time | sí | no |  | con zona horaria, en UTC | Momento del scrape, en UTC. |
| `content_hash` | string | sí | no |  | patrón `^[0-9a-f]{64}$`; sha256 hexadecimal | sha256 de un JSON canónico de los campos de contenido extraídos, sin scraped_at ni atributos volátiles de la fuente (D2, F3.6). |
| `title_raw` | string | no | sí | `null` | texto crudo; vacío → null |  |
| `description_raw` | string | no | sí | `null` | texto crudo; vacío → null |  |
| `price_raw` | string | no | sí | `null` | texto crudo; vacío → null | Precio como lo publica el portal. |
| `currency_raw` | string | no | sí | `null` | texto crudo; vacío → null | Moneda si el portal la da en un campo aparte. |
| `built_area_raw` | string | no | sí | `null` | texto crudo; vacío → null | m² construidos si vienen estructurados. |
| `land_area_raw` | string | no | sí | `null` | texto crudo; vacío → null | m² de terreno si vienen estructurados. |
| `bedrooms_raw` | string | no | sí | `null` | texto crudo; vacío → null |  |
| `bathrooms_raw` | string | no | sí | `null` | texto crudo; vacío → null |  |
| `garages_raw` | string | no | sí | `null` | texto crudo; vacío → null |  |
| `property_type_raw` | string | no | sí | `null` | texto crudo; vacío → null | Categoría o tipo según el portal. |
| `operation_raw` | string | no | sí | `null` | texto crudo; vacío → null |  |
| `city_raw` | string | no | sí | `null` | texto crudo; vacío → null |  |
| `neighborhood_raw` | string | no | sí | `null` | texto crudo; vacío → null | Barrio o zona como lo da el portal. |
| `address_raw` | string | no | sí | `null` | texto crudo; vacío → null |  |
| `latitude_raw` | string | no | sí | `null` | texto crudo; vacío → null |  |
| `longitude_raw` | string | no | sí | `null` | texto crudo; vacío → null |  |
| `published_at_raw` | string | no | sí | `null` | texto crudo; vacío → null |  |
| `advertiser_type_raw` | string | no | sí | `null` | texto crudo; vacío → null |  |
| `attributes_raw` | objeto clave-valor (string → string) | no | no |  |  | Otros pares clave-valor del portal (tags, ficha técnica). |

## Listing

Aviso limpio, tipado y dentro del alcance.

| Campo | Tipo | Obligatorio | Admite null | Default | Validaciones | Descripción |
|---|---|---|---|---|---|---|
| `source` | `Source` | sí | no |  |  |  |
| `source_id` | string | sí | no |  | no vacío |  |
| `url` | string | sí | no |  | URL http(s) absoluta, sin espacios, sin normalizar |  |
| `scraped_at` | date-time | sí | no |  | con zona horaria, en UTC |  |
| `content_hash` | string | sí | no |  | patrón `^[0-9a-f]{64}$`; sha256 hexadecimal |  |
| `operation` | `OperationType` | no | no | `"venta"` |  |  |
| `property_type` | `PropertyType` | sí | no |  |  |  |
| `property_type_raw` | string | no | sí | `null` |  | Categoría del portal, que no garantiza el tipo real (sources.md §6.7). |
| `city` | `City` | sí | no |  |  |  |
| `neighborhood_raw` | string | no | sí | `null` |  |  |
| `neighborhood_provenance` | `Provenance` | no | sí | `null` |  |  |
| `neighborhood_norm` | string | no | sí | `null` |  | Nombre en el gazetteer. |
| `neighborhood_match` | `NeighborhoodMatch` | no | sí | `null` |  |  |
| `price_amount` | decimal | sí | no |  | > 0.0 | Monto original, en su moneda. |
| `price_currency` | `Currency` | sí | sí |  |  | None: moneda desconocida (ADR-005). |
| `price_raw` | string | no | sí | `null` |  | Texto original del precio. |
| `price_provenance` | `Provenance` | sí | no |  |  |  |
| `currency_provenance` | `Provenance` | no | sí | `null` |  |  |
| `is_from_price` | boolean | sí | no |  |  | "desde" o rango: el precio es un mínimo. |
| `price_usd` | decimal | no | sí | `null` | > 0.0 |  |
| `fx_rate_pyg_per_usd` | decimal | no | sí | `null` | > 0.0 |  |
| `fx_date` | date | no | sí | `null` |  |  |
| `built_area_m2` | decimal | no | sí | `null` | > 0.0; <= 100000.0 |  |
| `built_area_provenance` | `Provenance` | no | sí | `null` |  |  |
| `land_area_m2` | decimal | no | sí | `null` | > 0.0; <= 100000.0 |  |
| `land_area_provenance` | `Provenance` | no | sí | `null` |  |  |
| `bedrooms` | integer | no | sí | `null` | >= 0 |  |
| `bathrooms` | integer | no | sí | `null` | >= 0 |  |
| `garages` | integer | no | sí | `null` | >= 0 |  |
| `has_pool` | boolean | no | sí | `null` |  |  |
| `has_quincho` | boolean | no | sí | `null` |  |  |
| `is_new` | boolean | no | sí | `null` |  | "A estrenar". |
| `in_gated_community` | boolean | no | sí | `null` |  | Condominio o barrio cerrado. |
| `has_elevator` | boolean | no | sí | `null` |  |  |
| `street_surface` | `StreetSurface` | no | sí | `null` |  |  |
| `advertiser_type` | `AdvertiserType` | no | sí | `null` |  |  |
| `published_at` | date | no | sí | `null` |  | Fecha que publica el portal; puede ser de republicación (§2.5). |
| `latitude` | number | no | sí | `null` | >= -90; <= 90 |  |
| `longitude` | number | no | sí | `null` | >= -180; <= 180 |  |
| `coordinates_provenance` | `Provenance` | no | sí | `null` |  |  |
| `coordinate_flags` | lista de `CoordinateFlag` | no | no | `[]` |  |  |
| `geo_precision` | `GeoPrecision` | sí | no |  |  |  |

## PredictionRequest

Inmueble a estimar. Ciudad y tipo fuera del alcance (ADR-002) son inválidos.

| Campo | Tipo | Obligatorio | Admite null | Default | Validaciones | Descripción |
|---|---|---|---|---|---|---|
| `city` | `City` | sí | no |  |  |  |
| `neighborhood` | string | no | sí | `null` |  | Barrio del gazetteer; si es desconocido se cae a la ciudad (F11.3). |
| `property_type` | `PropertyType` | sí | no |  |  |  |
| `built_area_m2` | number | sí | no |  | > 0; <= 100000 |  |
| `land_area_m2` | number | no | sí | `null` | > 0; <= 100000 |  |
| `bedrooms` | integer | no | sí | `null` | >= 0 |  |
| `bathrooms` | integer | no | sí | `null` | >= 0 |  |
| `garages` | integer | no | sí | `null` | >= 0 |  |
| `has_pool` | boolean | no | sí | `null` |  |  |
| `has_quincho` | boolean | no | sí | `null` |  |  |
| `is_new` | boolean | no | sí | `null` |  |  |
| `in_gated_community` | boolean | no | sí | `null` |  |  |
| `has_elevator` | boolean | no | sí | `null` |  |  |
| `street_surface` | `StreetSurface` | no | sí | `null` |  |  |

## PredictionResponse

Estimación puntual e intervalo, por m² y total, en USD.

| Campo | Tipo | Obligatorio | Admite null | Default | Validaciones | Descripción |
|---|---|---|---|---|---|---|
| `label` | string | no | no | `"precio de oferta estimado"` | fijo: `precio de oferta estimado` |  |
| `usd_per_m2` | number | sí | no |  | > 0 |  |
| `p_low` | number | sí | no |  | > 0 | Límite inferior del intervalo de USD/m². |
| `p_high` | number | sí | no |  | > 0 | Límite superior del intervalo de USD/m². |
| `total_usd` | number | sí | no |  | > 0 |  |
| `total_low` | number | sí | no |  | > 0 |  |
| `total_high` | number | sí | no |  | > 0 |  |
| `coverage_nominal` | number | sí | no |  | > 0; < 1 | Cobertura nominal del intervalo. |
| `warnings` | lista de `PredictionWarning` | no | no | `[]` |  |  |
| `model_version` | string | sí | no |  | no vacío |  |
| `contract_version` | string | no | no | `"0.1.1"` | patrón `^\d+\.\d+\.\d+$` |  |

## PredictionWarning

Advertencia de una predicción: código cerrado más un mensaje para mostrar al usuario.

| Campo | Tipo | Obligatorio | Admite null | Default | Validaciones | Descripción |
|---|---|---|---|---|---|---|
| `code` | `WarningCode` | sí | no |  |  |  |
| `message` | string | sí | no |  | no vacío |  |
