# ADR-003: Geolocalización a nivel barrio, con lat/lon opcional
- Estado: propuesto (pendiente revisión de Oscar Arce)
- Autores: Brian Leckie

## Contexto
El principio 2 del ROADMAP dice que no se asumen coordenadas. Los portales pueden o no exponer latitud y longitud, y cuando lo hacen la precisión puede variar. Qué fuentes las exponen y con qué precisión: [dato pendiente de F3.1].

El modelo necesita señal espacial: el aporte de las features geo es la pregunta de investigación que responde la ablation de F10.3. Hace falta una geografía que funcione aunque ningún aviso traiga coordenadas.

## Decisión
1. **La unidad geográfica base es el barrio.** Se define con un gazetteer de las cuatro ciudades con fuente documentada (F6.1). Los nombres de barrio de los avisos se normalizan con alias y fuzzy matching; lo que no matchea va a revisión manual y no se asigna en silencio (F4.4).
2. **Las features espaciales se calculan a nivel barrio.** Se parte del centroide del barrio y se calculan distancias a puntos de interés (POIs) de OpenStreetMap, conteos de POIs en un radio y distancia a centros de empleo (F6.3 y F6.4). El centroide sale del polígono de OSM cuando existe; si no, de Nominatim con caché, y el método usado se registra por barrio (F6.2). Los POIs se obtienen con Overpass en un snapshot fechado.
3. **`lat` y `lon` son opcionales en todos los schemas.** La precisión se registra en el flag `geo_precision ∈ {exacta, aproximada, barrio, ciudad}` de `Listing` (F1.3; `ciudad` se agregó en el contrato v0.1.0, ver ADR-006 y su pregunta P1), que se informa al modelo (F6.5). Sin coordenadas, la precisión es `barrio` si el aviso tiene un barrio normalizado y `ciudad` si no (F3.1: en Luque, San Lorenzo y Fernando de la Mora el "barrio" de InfoCasas es la ciudad, y la "Zona" de Clasipar a veces la repite). Si el aviso trae coordenadas, se usan como enriquecimiento opcional (F6.5): se calculan las mismas features desde ellas y la precisión pasa a ser `aproximada` o `exacta`, según lo que se observe en F3.1 sobre cada fuente. [pendiente de F3.1]

Este ADR describe la decisión; los schemas se definen y versionan en F1, no acá. F6.5 del ROADMAP quedó alineado con los niveles `aproximada` y `exacta`, y F1.3 con los cuatro niveles.

## Consecuencias
- **Las features geo no discriminan dentro de un mismo barrio.** Dos propiedades del mismo barrio reciben los mismos valores de distancia y de conteo, aunque una esté sobre una avenida y la otra no. Esto acota lo que puede mostrar la ablation geo (F10.3) y debe figurar en limitaciones (F6.7 y F15.2).
- **Un error de normalización de barrio se propaga.** Si un aviso se asigna al barrio equivocado, todas sus features espaciales quedan equivocadas (F4.4).
- **Cuanto más extenso o irregular es un barrio, peor lo representa su centroide.** [dato pendiente de F6.1/F7: heterogeneidad de tamaño entre barrios]
- **Puede haber resoluciones mezcladas.** Si una fuente trae coordenadas y otra no, los avisos tendrían features de distinta resolución. El flag evita tratarlas como equivalentes y permite evaluar el error por precisión, como un segmento más además de los de F10.4.
- **Los barrios con pocos avisos necesitan un fallback a nivel ciudad** (F7.2).
- **El producto no puede presentarse como una estimación a nivel de calle o de manzana.** El formulario pide barrio, no dirección (F12.1).

## Alternativas descartadas
- **Exigir lat/lon en cada aviso.** Excluye los avisos sin coordenadas, condiciona la elección de fuentes y viola el principio 2.
- **Geocodificar la dirección de cada aviso.** Depende de que el aviso traiga una dirección usable y de un servicio de geocodificación con sus límites de uso, y produciría coordenadas inferidas que parecen más precisas de lo que son. [pendiente de F3.1: qué campos de ubicación expone cada fuente]
- **Usar solo la ciudad.** Pierde la señal espacial y deja sin respuesta la pregunta de investigación de F10.3.
- **Basar la geografía en la zona fiscal catastral.** No se evaluó todavía cuánta señal aporta, así que no se adopta como base; queda como feature o benchmark opcional (F6.6).
