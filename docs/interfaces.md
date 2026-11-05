# Interfaces de integración

## I3 · Variables geográficas (propuesta para revisión)

`data/reference/geo_features.csv` es UTF-8 y usa coma como separador. Incluye una fila
por `(city, neighborhood)` del catálogo de O1 y una fila por ciudad con `neighborhood`
vacío. Las claves usan los identificadores de `avm.contract.enums.City` y los nombres
normalizados de O1. `geo_precision` vale `barrio` o `ciudad` según el origen espacial.

Orden de columnas:

1. `city`, `neighborhood`, `geo_precision`, `dist_cbd_km`.
2. `dist_<cat>_km` para `road`, `mall`, `school`, `university`, `hospital`, `park`, en ese orden.
3. `n_<cat>_<R>km` para esas categorías, con `R` igual a `1`, `3` y `5` en cada categoría.

Los radios se proponen para comparar proximidad inmediata y acceso en el entorno ampliado.
Las distancias son números en kilómetros y quedan vacías si el snapshot carece de objetos
utilizables de esa categoría. Los conteos son enteros no negativos. La fila de respaldo usa
el punto representativo del polígono municipal OSM. Para integrar, buscar primero la clave
de barrio y usar la fila con barrio vacío cuando la clave no esté disponible.

La distancia a vías usa el vértice más cercano. Los demás objetos usan su nodo o el punto
representativo del polígono. Se cuenta cada objeto OSM una vez por categoría y radio, incluso
si varios vértices de la misma vía caen dentro del radio. Una institución con varias
representaciones OSM puede aportar varios objetos. Las distancias son en línea geodésica
sobre una esfera, sin red vial ni tiempos de viaje.

`dist_cbd_km` usa el nodo OSM `249854726`, miembro `admin_centre` del límite de Asunción
en el snapshot O1. Es el punto de referencia único pedido para el centro de la capital.

```powershell
uv run python scripts/build_geo_features.py --snapshot data/raw/osm/2026-11-03
```

El comando usa las respuestas O1 guardadas. `geo_features.json` incluye hashes de los
insumos, objetos descartados por geometría y casos expuestos al borde del bbox. Cada
caso indica qué radios pueden estar truncados y en qué categorías la distancia mínima
podría cambiar con una extracción mayor. El CSV conserva las métricas observadas.
