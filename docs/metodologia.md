# Metodología

## Objetivo y alcance

El sistema estima el **precio de oferta** por superficie construida y el total de casas, departamentos y dúplex en Asunción, Luque, San Lorenzo y Fernando de la Mora. El total es el precio estimado por superficie multiplicado por los m² declarados. La salida incluye un intervalo y advertencias sobre soporte y ubicación. No se observa el precio de una operación concretada. Fuentes: [ADR-001](adr/001-precio-publicado.md), [ADR-002](adr/002-alcance.md) y [contrato de predicción](../src/avm/contract/prediction.py).

## Fuente, adquisición y privacidad

La versión evaluada usa exclusivamente Clasipar. InfoCasas se descartó por sus términos de uso; no se suman fuentes para ampliar artificialmente la muestra. El scraper respeta robots, usa un identificador y limita requests; la caché se sanitiza para excluir datos de contacto. No se distribuyen avisos en el repositorio. Fuentes: [evaluación de fuentes](sources.md), [scraper](../src/avm/scraping/base.py) y [ADR-007](adr/007-privacidad-cache.md).

Los snapshots son del 06/10/2026 y del 04/11/2026. Se leen 3.346 registros y quedan 3.239 avisos únicos tras deduplicación exacta; el dataset final tiene 1.769 filas: 672 casas, 510 departamentos y 587 dúplex. Estas cifras describen la muestra del portal durante ese período, no un censo de inmuebles. Fuente: [reporte de calidad v3, secciones 0–2](results/v3-quality-report.md).

## Limpieza, moneda y target

Se valida ciudad y tipo, precio interpretable, moneda y superficie construida; se rechazan conflictos de superficies y valores fuera de rangos definidos a priori. El embudo completo y sus descartes se conservan en el reporte generado. No se imputan targets. Fuentes: [pipeline](../src/avm/pipeline/clean.py), [construcción](../src/avm/pipeline/build.py) y [reporte de calidad](results/v3-quality-report.md).

Los precios en guaraníes se convierten con una cotización única de 6.085 PYG/USD, del 04/11/2026, punto medio de compra 5.980 y venta 6.190 de Cambios Chaco S.A. Se aplica a ambos snapshots y es un desvío documentado respecto de la cotización por fecha inicialmente prevista; no es una serie histórica del BCP. Los precios ya expresados en USD no se convierten. Fuentes: [ADR-004, desvío por plazo](adr/004-moneda.md) y [parámetros efectivos](results/v3-quality-report.md).

El target es `log(price_usd / built_area_m2)`. Los modelos vuelven a USD/m² por exponenciación. El contrato conserva el origen de la superficie; en departamentos se acepta el supuesto de superficie sin tipo explícito, con confianza reducida. Fuentes: [carga para modelado](../src/avm/model/data.py), [ADR-006](adr/006-contrato-v0.1.md) y [limitaciones](limitaciones.md).

## Deduplicación y particiones [OSCAR]

Se conserva la observación más reciente por identificador de origen. Los casi duplicados se agrupan usando ciudad, tipo, barrio, superficie redondeada y tolerancia de precio; el identificador de cluster no es una identificación jurídica del inmueble. La muestra v3 contiene 1.582 clusters. Fuentes: [deduplicación](../src/avm/pipeline/dedup.py) y [calidad, sección 4](results/v3-quality-report.md).

Las particiones son agrupadas por `cluster_id`: un cluster no se reparte entre ajuste, calibración y test. Se reserva el fold externo cero; sobre el desarrollo restante se compara el MdAPE medio de cinco folds. La selección utiliza 1.415 filas y excluye las 354 del holdout externo. El candidato final ajusta con 1.061 filas y calibra con otras 354; mantiene 354 para test. Fuentes: [splits](../src/avm/model/splits.py), [experimento](../src/avm/model/experiment.py), [diagnóstico de selección](results/v3-selection-evaluation.json) y [metadata final](results/v3-model-summary.json).

La validación interna elige entre configuraciones fijas únicamente dentro del entrenamiento. Los vocabularios categóricos se ajustan en train y los valores nuevos se tratan como desconocidos. No se usa target encoding global. Fuentes: [LightGBM](../src/avm/model/lgbm.py) y [experimento](../src/avm/model/experiment.py).

El trabajo es exploratorio: el protocolo de selección separado se incorporó durante el análisis y no fue prerregistrado; también se inspeccionaron los resultados de la evaluación completa. La exclusión computacional del holdout evita que sus filas entren en la selección, pero no convierte este análisis en una confirmación prospectiva independiente. Una evaluación futura necesita nuevos datos. Fuentes: [informe del análisis](results/2026-11-06-v3.md) y [opción de selección](../scripts/evaluate.py).

## Barrios y features geográficas [OSCAR]

El gazetteer usa OpenStreetMap y distingue homónimos por ciudad. Se emplea un punto interior cuando hay polígono y un nodo cuando solo hay un punto. La localización es de barrio, no del inmueble. Distancias y conteos de vías, centros comerciales, colegios, universidades, hospitales y parques se calculan desde esa referencia; si falta barrio se usan las features de ciudad. Fuentes: [geo](geo.md), [features](../src/avm/geo/features.py), [interfaz I3](interfaces.md) y [ADR-003](adr/003-geo-a-nivel-barrio.md). © OpenStreetMap contributors, ODbL.

La normalización elimina marcadores genéricos, reconoce abreviaturas y restringe el matching a la ciudad. Se auditan zonas no reconocidas sin consultar precios. Solo equivalencias de escritura se agregan como alias manuales versionados; zonas amplias, ambiguas o basura se mantienen sin barrio. El umbral fuzzy permanece en 90. Fuentes: [normalización](../src/avm/pipeline/neighborhood.py), [alias revisados](../src/avm/pipeline/neighborhood_aliases.csv) y [auditoría](alias-barrios-v3.md).

La cobertura de barrio pasa de 21,7 % a 27,8 %: 492 filas con barrio y 1.277 con resolución de ciudad. Fernando de la Mora baja a 5,1 % al bloquear zonas amplias; esa caída evita asignaciones arbitrarias. Se informan exactos, fuzzy, manuales y motivos de falta de match. Fuente: [comparación antes/después](alias-barrios-v3.md) y [calidad v3, sección 3](results/v3-quality-report.md).

## Modelos, incertidumbre y métricas [OSCAR]

El baseline usa medianas jerárquicas de log USD/m² por barrio y respaldos por tipo/ciudad y global, ajustadas en train. LightGBM usa categóricas nativas y features permitidas por el formulario más I3. Se excluyen cocheras y superficie de calle por falta de datos. Fuentes: [baseline](../src/avm/model/baseline.py), [features permitidas](../src/avm/model/data.py) y [LightGBM/CQR](lightgbm-cqr.md).

LightGBM estima cuantiles 0,1 / 0,5 / 0,9. El intervalo CQR se calibra **por tipo de propiedad**, con score máximo dentro de cada cluster de calibración y cuantil de rango finito `ceil((m+1)*0.8)`. El nominal es 80 %, bajo intercambiabilidad de clusters dentro del tipo; no garantiza cobertura en todo barrio ni en cada muestra de test. Fuentes: [calibración](../src/avm/model/conformal.py), [procedimiento](lightgbm-cqr.md) y [parámetros finales](../deploy/model/calibration.json).

Se reportan MdAPE, MAPE, proporciones dentro de tolerancia, RMSE en log, cobertura y ancho relativo. La ablation compara LightGBM con y sin columnas numéricas de I3 sobre las mismas particiones. Ambas variantes conservan ciudad y barrio: mide el aporte incremental de esas features, no toda la información espacial. Las medias entre folds no están ponderadas. Fuentes: [métricas](../src/avm/model/metrics.py), [selección de columnas](../src/avm/model/lgbm.py), [evaluación](../src/avm/model/experiment.py) y [resultados](results/2026-11-06-v3.md).

En desarrollo se elige LightGBM con geo: MdAPE medio 18,32 %, frente a 18,63 % sin geo y 22,06 % del baseline. En el test separado del candidato, MdAPE 20,92 %, cobertura 78,53 % y cobertura en casas 74,05 %. La evaluación completa muestra un efecto mixto de geo; no demuestra una mejora consistente. Fuentes: [métricas de selección](results/v3-selection-metrics.csv), [metadata](results/v3-model-summary.json) y [ablation](results/2026-11-06-v3.md).

OLS, Random Forest, leave-barrio-out y evaluación temporal no integran esta entrega por el alcance acordado. No se reportan resultados de esos experimentos ni se supone capacidad de generalización futura o a barrios nuevos. Fuente de alcance implementado: [ROADMAP](../ROADMAP.md) y [script de evaluación](../scripts/evaluate.py).

## Reproducción y publicación

Con los snapshots sanitizados y las referencias entregadas fuera de git, ejecutar desde la raíz, en una carpeta de salida nueva:

```powershell
uv sync --frozen
uv run python scripts/build_dataset.py --snapshot 2026-10-06 2026-11-04 --fx-pyg-per-usd 6085 --fx-date 2026-11-04 --fx-source "Cambios Chaco S.A., punto medio compra 5.980 / venta 6.190, 04/11/2026" --gazetteer data/reference/gazetteer.csv --out-root data/processed/reproduccion-v3
just evaluate data/processed/reproduccion-v3/2026-10-06_2026-11-04/dataset.csv data/reference/geo_features.csv data/processed/reproduccion-v3-selection v3 --stage final --selection-holdout
just evaluate data/processed/reproduccion-v3/2026-10-06_2026-11-04/dataset.csv data/reference/geo_features.csv data/processed/reproduccion-v3-all v3 --stage final
just train data/processed/reproduccion-v3/2026-10-06_2026-11-04/dataset.csv data/reference/geo_features.csv data/reference/gazetteer.csv lightgbm-cqr models/reproduccion-v3 --dataset-version v3 --stage final
just check
uv run python scripts/check_deploy_model.py
```

Parámetros de datos: [reporte generado](results/v3-quality-report.md). CLI y valores por defecto: [build](../src/avm/pipeline/build.py), [train](../scripts/train.py) y [evaluate](../scripts/evaluate.py). La fecha y el nombre del artefacto cambian al reproducir; el registro adicional del criterio de selección está en [metadata publicada](../deploy/model/metadata.json). Las referencias geo deben ser las mismas de la corrida: no consultar nuevamente OSM para comparar resultados idénticos.

El artefacto final contiene parámetros y agregados, no filas de avisos. Su merge humano dispara el redeploy; la versión activa se comprueba en la API, no por la existencia del PR. Fuentes: [ADR-008](adr/008-modelo-en-produccion.md), [guardia](../scripts/check_deploy_model.py) y [publicación](../deploy/README.md).

## Referencias

La [lista de referencias contrastadas](referencias.md) reúne autores, año o ausencia explícita de fecha, título, DOI/URL, tema y alcance de uso. Incluye los fundamentos de modelos hedónicos, métricas, LightGBM, CQR, particiones agrupadas, OSM/ODbL y robots.txt. Dos entradas complementarias tienen pendientes marcados **VERIFICAR**; no se afirma cumplimiento de IAAO. Las cifras de resultados siguen respaldadas por los reportes internos. Falta la revisión bibliográfica humana final y su adaptación al formato de la facultad.
