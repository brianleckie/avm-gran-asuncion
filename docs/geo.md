# Geografía base (F6.1–F6.3)

## Estado y ejecución

La extracción enumera objetos encontrados en OSM, no un padrón oficial exhaustivo de barrios.
Los huecos no observables en OSM requieren contrastar con una fuente externa antes de llamar
«definitivo» al gazetteer. No se inventan barrios ni coordenadas.

```powershell
uv run python scripts/build_geo.py --snapshot data/raw/osm/2026-11-03
```

La fecha es una etiqueta explícita del snapshot, no una consulta histórica: el manifest guarda
el instante real UTC de cada respuesta y el servidor devuelve su fecha de base OSM.
Repetir con el mismo directorio reutiliza la caché. Para actualizar, crear otro snapshot.
`--overpass` permite seleccionar explícitamente otra instancia; no hay rotación automática.

## Formato propuesto de entrega

`docs/interfaces.md` no existe en la versión del repositorio usada para empezar esta tarea.
Por eso este formato es una **propuesta de I2 pendiente de coordinación con Brian**, no una
implementación de una interfaz previamente acordada. No modifica schemas de `avm.contract`.

`data/reference/gazetteer.csv`, UTF-8, columnas en este orden:

- `city`: valores de `avm.contract.enums.City`.
- `neighborhood`: nombre OSM normalizado a minúsculas, sin tildes, espacios colapsados.
- `aliases`: nombres alternativos OSM normalizados, separados por `|`; incluye abreviatura
  `v.` si el nombre contiene `villa`, y variantes sin `barrio`/con `b°` cuando hay ese prefijo.
- `lat`, `lon`: punto representativo, o vacíos si no hay geometría utilizable.
- `centroid_method`: `polygon_representative_point`, `osm_node` o `missing`.
- `osm_type`, `osm_id`, `source_url`: procedencia del objeto seleccionado.

La clave es `(city, neighborhood)`. Un polígono tiene prioridad sobre un nodo de igual nombre.
Varios candidatos de igual prioridad se excluyen y van a `geo_issues.json` para revisión manual.
No se fusionan nombres diferentes mediante fuzzy matching.

## Selección y geometría

Las ciudades se descubren dentro de Paraguay (`ISO3166-1=PY`), por nombre exacto, como relaciones
administrativas `admin_level=8`. Se exige encontrar exactamente una de cada ciudad y un
polígono válido. Esto evita confundir San Lorenzo con barrios homónimos de otras ciudades.

Por ciudad se consultan `place=neighbourhood|suburb|quarter` y relaciones administrativas
`admin_level=9|10|11`. `geo_summary.json` registra las etiquetas observadas por ciudad;
su clasificación administrativa no se presume equivalente a un listado oficial de barrios.
Los puntos fuera del polígono de la ciudad se excluyen y reportan para revisión.
Los polígonos deben estar completamente cubiertos por el límite municipal OSM (`covers`);
no basta que su punto representativo esté dentro. Los que cruzan se reportan y excluyen,
sin recortarlos ni alterar sus coordenadas. `covers` incluye el borde compartido.

Shapely reconstruye anillos outer/inner de relaciones y respeta huecos. Una geometría inválida
no se corrige silenciosamente. Se usa `representative_point`, que produce un punto interior;
no es el centroide geométrico y no representa necesariamente el centro poblacional. Las
coordenadas son WGS84, en orden lon/lat para geometría y lat/lon en el CSV.

## Consultas, caché y políticas

Cada respuesta HTTP se conserva en `data/raw/osm/<snapshot>/`, también si falla; el manifest
registra consulta, endpoint, fecha, estado y hash SHA-256. Una respuesta Overpass con `remark`
se rechaza para no aceptar extracciones parciales. Sin reintentos automáticos; máximo doce
solicitudes Overpass por snapshot. Una ejecución normal requiere seis consultas.

El cliente incluye geocodificación puntual optativa, con presupuesto menor de 200 solicitudes
por snapshot y caché. El pipeline no invoca Nominatim automáticamente: los casos ambiguos
requieren revisión de contexto, no elegir el primer resultado. Consultas secuenciales y
separación mínima de dos segundos. No ejecutar procesos concurrentes con el mismo directorio.
No usar Nominatim para enumerar barrios o descargar POIs.

- Política Nominatim: https://operations.osmfoundation.org/policies/nominatim/
- Overpass: https://wiki.openstreetmap.org/wiki/Overpass_API
- Atribución: **© OpenStreetMap contributors**; datos bajo ODbL:
  https://www.openstreetmap.org/copyright

## POIs y cobertura

El bbox es la unión de los límites de las cuatro ciudades más 0,02 grados por lado.
Sus coordenadas calculadas se guardan en el manifest. No se escriben coordenadas de memoria.
Categorías: vías `highway=primary|trunk`, `shop=mall`, `amenity=school|university|hospital`,
`leisure=park`. El snapshot conserva geometrías completas de los objetos seleccionados.
Los conteos son de objetos OSM: una institución puede estar representada por varios objetos;
no deben interpretarse como conteos de instituciones sin deduplicación en F6.4.

`geo_summary.json` contiene conteos por ciudad y método, etiquetas observadas y conteos de POIs;
`geo_issues.json` registra exclusiones. Los datos y reportes JSON están fuera de Git.
F6.4 deberá considerar efectos de borde: un POI más cercano podría quedar fuera del bbox.
Las features por barrio no discriminan entre propiedades del mismo barrio (F6.7).

## Resultado inicial observado: snapshot 2026-11-03

Los conteos de esta sección corresponden al algoritmo inicial. La revisión de contención
completa al final de este documento actualiza la selección de Maramburé y el total.

Extracción realizada el 3 de noviembre de 2026 en horario de Paraguay (las fechas UTC del
manifest corresponden al 4 de noviembre). Seis consultas Overpass y una consulta puntual
Nominatim. Reejecución completa desde caché verificada.

- Asunción: 76 entradas; 60 con polígono, 15 con nodo, 1 sin ubicación utilizable.
  Predomina `place=neighbourhood` y `admin_level=10`; también hay relaciones sin `place`.
- Luque: 35 entradas aceptadas; 27 con polígono y 8 con nodo. Se observan relaciones de
  nivel 9, nodos `suburb`, y algunos `neighbourhood` de nivel 10 y `quarter`.
- San Lorenzo: 41 entradas aceptadas, todas con nodo. Las etiquetas observadas incluyen
  `neighbourhood`, algunos nivel 10 y un `quarter`; no se obtuvo un polígono utilizable
  para las entradas aceptadas.
- Fernando de la Mora: 16 entradas; 15 con polígono y 1 con nodo. Se observan relaciones
  de nivel 9 y nodos `quarter`/`suburb`.

Son 168 entradas, 167 con ubicación. Son unidades candidatas de distinta jerarquía, no
168 barrios oficialmente validados. Una misma zona podría aparecer con nombres diferentes.

Casos pendientes de revisión (no resueltos mediante selección arbitraria):

- Asunción, `banado`: relación 3676723 sin anillos, solamente `admin_centre`. Una consulta
  puntual a Nominatim devolvió Bañado Tacumbú, Bañado Norte y Bañado Santa Ana, además de una
  escuela. Ninguno se asignó a la entrada genérica: el nombre no identifica una ubicación única.
- Luque, `marambure`: dos polígonos homónimos (relación 11271234 y vía 1383659528) y un nodo
  (7683289217). Excluido de la entrega automática hasta acordar cuál representa la unidad buscada.
- San Lorenzo, `san felipe`: nodos 1969335519 y 2979211659 con posiciones diferentes.
  Excluido hasta revisión.

POIs observados en el bbox: 2.346 vías, 88 objetos mall, 1.192 school, 106 university,
134 hospital y 838 park. Estos conteos incluyen objetos de áreas vecinas dentro del margen
y no están deduplicados por institución.

Para cerrar F6.1 como gazetteer definitivo faltan validar el universo de barrios, resolver
las unidades homónimas y acordar I2 con Brian. Los archivos ya sirven para revisar cobertura
y preparar F6.4, conservando estas limitaciones.

## Aclaraciones iniciales aportadas por Oscar

Oscar confirmó Maramburé como perteneciente a Luque. La extracción ya lo ubicaba en Luque:
el conflicto pendiente es elegir entre geometrías diferentes, no cambiar de distrito.
No se incorpora el código electoral `0302`: no forma parte del contrato inmobiliario ni
resuelve la elección del polígono.

Oscar identificó San Felipe en el sector Banco San Miguel/Ricardo Brugada de Asunción.
El gazetteer ya contiene un San Felipe de Asunción; eso no demuestra que los dos objetos
homónimos encontrados dentro de San Lorenzo deban trasladarse o borrarse. Se conserva
la separación por ciudad y la revisión pendiente de esos dos nodos.

Oscar indicó que «Bañado» debe distinguirse por sectores norte y sur. Esto es compatible
con no asignar un centroide único a la entrada genérica. No se convierten automáticamente
Cará Cará, Tacumbú, Santa Ana, Barrio Obrero o Roberto L. Petit en alias equivalentes:
una zona amplia puede abarcar barrios diferentes. Los nombres específicos observados en
OSM conservan sus propias entradas y fuentes.

La verificación documental posterior se registra a continuación. Las geometrías ambiguas
siguen sin resolverse: una lista de nombres no define sus límites espaciales.

## Verificación contra el catálogo INE 2022

Fuente: **INE. Lista de barrios y localidades del Paraguay. Año 2022**, archivo original:
https://www.ine.gov.py/microdatos/register/CODIGO-GEOGRAFICO-2022/Codigos%20de%20barrios%20y%20localidades%20INE%202022.xlsx

Archivo descargado para comprobación; SHA-256:
`24702c74a1252c1e2ec52ced84d3f60120e4eefeb6f4c6c443bf4acfd80ef404`.
Localización: primera hoja del libro, columnas A:F; encabezados en la fila 3:
`COD_DEP`, `DEPARTAMENTO`, `COD_DIS`, `DISTRITO`, `COD_BARLOC`, `BARRIOS Y LOCALIDADES`.
Los códigos conservan ceros iniciales y se interpretan como campos separados.

- Fila 6095: `11`, CENTRAL, `09`, LUQUE, `015`, MARAMBURE.
  Confirma pertenencia a Luque, pero no selecciona uno de los dos polígonos OSM.
- Fila 6185: `11`, CENTRAL, `14`, SAN LORENZO, `024`, SAN FELIPE.
  San Felipe sí figura en esta lista oficial de barrios y localidades de San Lorenzo.
  No debe eliminarse ni trasladarse a Asunción por homonimia. La lista no identifica
  cuál de los dos nodos OSM representa esa unidad ni prueba su relación con Reducto/Calle'i.
- Fila 29: `00`, ASUNCIÓN, `00`, ASUNCIÓN, `026`, BANCO SAN MIGUEL.
  El código de barrio/localidad de esta fuente es `026`, no `029`.
- Fila 15: Asunción, código de barrio/localidad `012`, RICARDO BRUGADA.
- Fila 25: Asunción, código de barrio/localidad `022`, BAÑADO CARA CARA.

No hay una fila de nombre exacto SAN FELIPE entre las filas de Asunción de este libro.
Eso no invalida el topónimo local observado en OSM, pero tampoco prueba que esté contenido
en Banco San Miguel o Ricardo Brugada: esa relación requiere límites o una fuente específica.

Los códigos `0302` para Luque y `1109` para San Lorenzo aportados inicialmente no se adoptan
como códigos INE 2022. En este libro `COD_DEP=11`, `COD_DIS=09` corresponde a Luque;
San Lorenzo tiene `COD_DIS=14`. No se presume equivalencia entre códigos censales y electorales.

El portal https://www.tsje.gov.py/ aportado por Oscar no identifica un documento, versión,
página o registro específico que permita validar los códigos electorales propuestos.
Por ahora no se declaran verificados ni se incorporan al contrato inmobiliario.

Resultado: pertenencia nominal de Maramburé a Luque y San Felipe a San Lorenzo corroborada;
selección de geometrías y correspondencia de sectores de Asunción pendientes. Esta revisión
no modifica coordenadas ni cierra por sí sola F6.1.

## Revisión de contención completa de las geometrías

Se aplicó la propuesta de Oscar de comprobar toda la geometría, además del punto interior.
Se reutilizó el snapshot; no hubo consultas nuevas. Referencia territorial: relaciones
municipales **OSM**, no cartografía oficial INE/TSJE. El Excel INE contiene códigos y nombres,
pero no polígonos. No se presenta GADM como fuente oficial paraguaya.

- Maramburé: relación `11271234` completamente cubierta por el límite OSM de Luque
  (`6002474`). La vía `1383659528` lo intersecta pero no está completamente cubierta:
  se excluye con `polygon_crosses_city_boundary`, sin recortarla. Tras esta exclusión
  queda una sola candidata poligonal válida y se selecciona la relación; el nodo
  `7683289217` también cae en Luque. La selección es provisional respecto de límites oficiales.
- San Felipe: el nodo `1764370853` cae en Asunción; los nodos `1969335519` y `2979211659`
  caen en San Lorenzo. La contención municipal distingue las ciudades pero no decide
  entre los dos nodos de San Lorenzo. No se sustituyen por centroides de otros barrios.
- Bañado: no se introduce un corte por latitud sin delimitación documentada. La entrada
  genérica permanece sin ubicación; las entradas específicas conservan sus coordenadas OSM.

Resultado actualizado: **169 entradas, 168 ubicadas**. Asunción: 76 (60 polígono, 15 nodo,
1 sin ubicación); Luque: 36 (28 polígono, 8 nodo); San Lorenzo: 41 nodos;
Fernando de la Mora: 16 (15 polígono, 1 nodo). POIs sin cambios.

Prueba de regresión: un polígono cuyo punto interior cae dentro de la ciudad pero que cruza
su límite debe excluirse, permitiendo seleccionar el candidato completamente contenido.
Las 14 pruebas geo pasan sin red. F6.1 sigue pendiente de validar el universo oficial y
acordar I2; San Felipe de San Lorenzo continúa en revisión y Bañado genérico sin centroide.
