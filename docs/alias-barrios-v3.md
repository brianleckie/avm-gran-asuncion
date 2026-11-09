# Curación de barrios v3 (F4.4)

Fuente de decisiones: solo ciudad y zona del crudo, nombres/alias del gazetteer y consultas OSM locales.
El script de auditoría únicamente lee listing_key de I1 y city_raw/neighborhood_raw del crudo.

Se revisaron 40 zonas frecuentes por ciudad. Clasificación de 160 textos: a=28, b=117, c=12, d=3.
El archivo neighborhood_aliases.csv contiene exclusivamente variantes revisadas de tipo a.
Las categorías b/d quedan fuera del archivo manual. El umbral fuzzy continúa en 90.
Las referencias amplias norte/sur de Fernando de la Mora quedan sin asignación a barrio.

En Fernando de la Mora, los «exactos» bajan de 23 a 12 porque se retiran **12 coincidencias antiguas con el nombre canónico «Zona Sur»** del gazetteer y entra **1 exacto nuevo**: 11 se conservan y 1 se incorpora. Antes, variantes de mayúsculas de «Zona Sur» coincidían literalmente con esa entrada; esa igualdad de texto no identificaba un barrio concreto dentro de una zona amplia. Son falsos positivos de **precisión barrial**, no ubicaciones erróneas comprobadas individualmente. Ahora la normalización retira ciudad y marcadores como «zona» y bloquea explícitamente «norte»/«sur» en ese municipio como ambiguos. Las 86 filas ambiguas son las 12 que antes figuraban como exactas más 74 que ya estaban sin match y ahora reciben un motivo más informativo; no se perdieron 86 barrios válidos. Con 2 matches manuales nuevos, el total reconocido pasa de 23 a 14 sobre 277 filas (8,3 % a 5,1 %), priorizando no asignar un barrio sin evidencia. Fuente: [transiciones auditadas sobre los mismos registros, sin precios](results/fdlm-match-transitions-v3.json), [matcher](../src/avm/pipeline/neighborhood.py) y sección 3 antes/después de este documento.

Las consultas OSM no confirmaron nuevas geometrías municipales para los faltantes revisados.
Laguna Grande encontrado pertenece a Fernando de la Mora y Laurelty a Luque. Ambos ya figuran en I2.
Los candidatos restantes requieren una fuente espacial antes de agregarlos.

Cambios de claves tras expandir abreviaturas que quedan ambiguos se bloquean.
El reporte incluye ahora la columna manual y cuenta manual en el porcentaje con barrio.

## Sección 3 antes

## 3. Barrio por ciudad (filas del dataset)

| ciudad | filas | exacto | alias | fuzzy | sin_match | % con barrio | sin_match: sin_zona | sin_match: igual_a_la_ciudad | sin_match: sin_gazetteer | sin_match: no_matchea | sin_match: ambiguo |
|---|---|---|---|---|---|---|---|---|---|---|---|
| asuncion | 674 | 238 | 0 | 3 | 433 | 35,8 % | 94 | 10 | 0 | 329 | 0 |
| luque | 564 | 76 | 0 | 6 | 482 | 14,5 % | 100 | 75 | 0 | 307 | 0 |
| san_lorenzo | 254 | 29 | 0 | 9 | 216 | 15,0 % | 29 | 50 | 0 | 137 | 0 |
| fernando_de_la_mora | 277 | 23 | 0 | 0 | 254 | 8,3 % | 48 | 19 | 0 | 187 | 0 |
| total | 1769 | 366 | 0 | 18 | 1385 | 21,7 % | 271 | 154 | 0 | 960 | 0 |


## Sección 3 después

## 3. Barrio por ciudad (filas del dataset)

| ciudad | filas | exacto | alias | fuzzy | manual | sin_match | % con barrio | sin_match: sin_zona | sin_match: igual_a_la_ciudad | sin_match: sin_gazetteer | sin_match: no_matchea | sin_match: ambiguo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| asuncion | 674 | 253 | 0 | 3 | 46 | 372 | 44,8 % | 94 | 10 | 0 | 268 | 0 |
| luque | 564 | 95 | 0 | 8 | 24 | 437 | 22,5 % | 100 | 93 | 0 | 244 | 0 |
| san_lorenzo | 254 | 35 | 0 | 9 | 5 | 205 | 19,3 % | 29 | 56 | 0 | 120 | 0 |
| fernando_de_la_mora | 277 | 12 | 0 | 0 | 2 | 263 | 5,1 % | 48 | 29 | 0 | 100 | 86 |
| total | 1769 | 395 | 0 | 20 | 77 | 1277 | 27,8 % | 271 | 188 | 0 | 732 | 86 |


## Reproducción

1. Ejecutar scratchpad/audit_neighborhoods.py con el I1 anterior y el gazetteer.
2. Ejecutar scratchpad/classify_neighborhoods.py sobre el archivo before.csv de esa auditoría.
3. Ejecutar just build-dataset con los parámetros del reporte y --out-root data/processed/dataset-v3.

Los CSV crudos, auditorías y datasets quedan en data/ fuera de git.
