# Reporte de calidad del dataset

Generado por `avm.pipeline.build`. **Solo agregados**: ningún texto de avisos. Los precios son precios de oferta publicados, no de transacción.

## 0. Parámetros

- Contrato: v0.1.1. Fuente: clasipar.
- Snapshots: 2026-10-06 (227 líneas), 2026-11-04 (3119 líneas)
- Cotización: 6085 PYG por USD, fecha 2026-11-04, fuente: Cambios Chaco S.A., punto medio compra 5.980 / venta 6.190, 04/11/2026
- Gazetteer: gazetteer.csv. Umbral fuzzy: 90.
- Tolerancia tag vs. texto en m² construidos: 10.00 %. Tolerancia de precio para casi-duplicados: 1.00 %.
- Outliers a priori: m² construidos entre 15 y (máx. por tipo: departamento 600, duplex 1000, casa 2000); USD/m² entre 150 y 8000 (todos los tipos).

## 1. Embudo de descartes

| regla (en orden) | entran | descartados | salen |
|---|---|---|---|
| líneas leídas | 3346 |  | 3346 |
| registro_crudo_invalido | 3346 | 0 | 3346 |
| duplicado_exacto_mismo_source_id | 3346 | 107 | 3239 |
| operacion_fuera_de_alcance | 3239 | 0 | 3239 |
| tipo_de_inmueble_no_mapeable | 3239 | 0 | 3239 |
| ciudad_ausente_o_fuera_de_alcance | 3239 | 8 | 3231 |
| precio_sin_monto_interpretable | 3231 | 0 | 3231 |
| precio_cero | 3231 | 23 | 3208 |
| moneda_desconocida | 3208 | 0 | 3208 |
| precio_desde_o_rango | 3208 | 0 | 3208 |
| sin_m2_construidos | 3208 | 1186 | 2022 |
| m2_tag_y_texto_difieren_mas_de_10pct | 2022 | 139 | 1883 |
| rechazado_por_el_contrato | 1883 | 0 | 1883 |
| outlier_m2_construidos_minimo | 1883 | 7 | 1876 |
| outlier_m2_construidos_maximo | 1876 | 28 | 1848 |
| outlier_usd_por_m2_minimo | 1848 | 69 | 1779 |
| outlier_usd_por_m2_maximo | 1779 | 10 | 1769 |
| **filas en dataset.csv** |  |  | 1769 |

## 2. Target disponible por tipo y ciudad

Target disponible = el aviso llega a `dataset.csv` (precio válido y en dólares o guaraníes, m² construidos identificados, sin outliers). Denominador: avisos únicos (después de colapsar duplicados exactos).

| tipo | avisos únicos de entrada | en dataset | % con target |
|---|---|---|---|
| casa | 1444 | 672 | 46,5 % |
| departamento | 765 | 510 | 66,7 % |
| duplex | 1030 | 587 | 57,0 % |
| total | 3239 | 1769 | 54,6 % |

| ciudad | avisos únicos de entrada | en dataset | % con target |
|---|---|---|---|
| asuncion | 1179 | 674 | 57,2 % |
| luque | 995 | 564 | 56,7 % |
| san_lorenzo | 509 | 254 | 49,9 % |
| fernando_de_la_mora | 548 | 277 | 50,5 % |
| sin_ciudad | 8 | 0 | 0,0 % |
| total | 3239 | 1769 | 54,6 % |

| tipo | ciudad | avisos únicos de entrada | en dataset | % con target |
|---|---|---|---|---|
| casa | asuncion | 408 | 203 | 49,8 % |
| casa | luque | 414 | 188 | 45,4 % |
| casa | san_lorenzo | 318 | 149 | 46,9 % |
| casa | fernando_de_la_mora | 297 | 132 | 44,4 % |
| casa | sin_ciudad | 7 | 0 | 0,0 % |
| departamento | asuncion | 411 | 273 | 66,4 % |
| departamento | luque | 170 | 119 | 70,0 % |
| departamento | san_lorenzo | 65 | 42 | 64,6 % |
| departamento | fernando_de_la_mora | 119 | 76 | 63,9 % |
| duplex | asuncion | 360 | 198 | 55,0 % |
| duplex | luque | 411 | 257 | 62,5 % |
| duplex | san_lorenzo | 126 | 63 | 50,0 % |
| duplex | fernando_de_la_mora | 132 | 69 | 52,3 % |
| duplex | sin_ciudad | 1 | 0 | 0,0 % |

## 3. Barrio por ciudad (filas del dataset)

| ciudad | filas | exacto | alias | fuzzy | manual | sin_match | % con barrio | sin_match: sin_zona | sin_match: igual_a_la_ciudad | sin_match: sin_gazetteer | sin_match: no_matchea | sin_match: ambiguo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asuncion | 674 | 253 | 0 | 3 | 46 | 372 | 44,8 % | 94 | 10 | 0 | 268 | 0 |
| luque | 564 | 95 | 0 | 8 | 24 | 437 | 22,5 % | 100 | 93 | 0 | 244 | 0 |
| san_lorenzo | 254 | 35 | 0 | 9 | 5 | 205 | 19,3 % | 29 | 56 | 0 | 120 | 0 |
| fernando_de_la_mora | 277 | 12 | 0 | 0 | 2 | 263 | 5,1 % | 48 | 29 | 0 | 100 | 86 |
| total | 1769 | 395 | 0 | 20 | 77 | 1277 | 27,8 % | 271 | 188 | 0 | 732 | 86 |

## 4. Clusters (F5)

Filas: 1769. Clusters: 1582. Tamaño máximo: 6. Filas en clusters de más de una fila: 322 (18,2 %).

| tamaño del cluster | clusters |
|---|---|
| 1 | 1447 |
| 2 | 101 |
| 3 | 22 |
| 4 | 7 |
| 5 o más | 5 |

## 5. Origen de los datos

| m² construidos | filas | % |
|---|---|---|
| tag | 504 | 28,5 % |
| texto | 1265 | 71,5 % |

Filas que entran por la regla de departamento con superficie sin tipo (`kind=None`, F4.3): 393 (22,2 % de las filas; 77,1 % de los 510 departamentos del dataset).

Filas cuyo texto trae más de un valor distinto de m² construidos (se toma el primero; informativo): 326.

| amenity | 1 | 0 | vacío (no mencionado) | valor desde tag | valor desde regex |
|---|---|---|---|---|---|
| has_pool | 823 | 182 | 764 | 816 | 189 |
| has_quincho | 976 | 122 | 671 | 889 | 209 |
| is_new | 354 | 1 | 1414 | 0 | 355 |
| in_gated_community | 126 | 0 | 1643 | 0 | 126 |
| has_elevator | 119 | 4 | 1646 | 0 | 123 |

| street_surface | filas |
|---|---|
| pavimento | 34 |
| empedrado | 25 |
| tierra | 1 |
| vacío | 1709 |

| campo | con dato | vacío | % vacío |
|---|---|---|---|
| bedrooms | 1240 | 529 | 29,9 % |
| bathrooms | 710 | 1059 | 59,9 % |
| garages | 0 | 1769 | 100,0 % |

**`garages` queda vacío en el 100 % de las filas (1769 de 1769)**: el parser no extrae cocheras, así que no sirve como feature.

## 6. Limitaciones

- Precio de oferta publicado: no es un precio de transacción.
- Una sola cotización (casa de cambios) para todos los snapshots: los avisos en guaraníes del snapshot más viejo se convierten con la cotización de la fecha indicada arriba (ADR-004, sección «Desvío por plazo»). Los avisos en dólares no se ven afectados.
- Una superficie sin tipo (`kind=None`) NO se acepta como construida en casas y dúplex (decisión por plazo). En departamentos se acepta la primera expresión sin tipo cuando no hay tag ni superficie `construida` (F4.3): supuesto a priori de que un departamento no tiene terreno propio, no verificado a mano; puede incluir superficies que no son la construida.
- Sin gazetteer (`--gazetteer none`) ningún aviso tiene barrio: `geo_precision=ciudad` para todos.
- `garages` queda vacío salvo que el snapshot traiga `garages_raw`: el parser no lo extrae.
- Las coordenadas no se usan (geo a nivel barrio, ADR-003).
- Los tags de superficie de los snapshots anteriores a F3.4 se leen de `attributes_raw`; su `content_hash` es el del parser viejo.
- `snapshot_date` es la del snapshot de la observación más reciente de cada aviso: para un holdout temporal el train solo tendría avisos cuya última aparición fue antes del corte (sesgo de supervivencia). Conviene cortar con otra fecha o agregar la primera aparición.
- Una republicación con otro `source_id` y un precio que cambió más de 1 % no se agrupa en el mismo cluster: puede quedar a los dos lados de un split. `cluster_id` solo es comparable dentro de un mismo `dataset.csv`.
- Los rangos de outliers son supuestos a priori del equipo, no datos de mercado, y no se recalibraron mirando la distribución.
- Con `--gazetteer none` los clusters se arman sin barrio: pueden agrupar de más (lado seguro para leakage). El redondeo del m² a entero puede partir un par en el borde.
