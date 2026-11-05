# Baseline y Predictor I4 (F8.3)

Entrenar desde la raíz del proyecto con una versión de salida nueva.

```powershell
just train data/processed/dataset-v1/dataset.csv data/reference/geo_features.csv data/reference/gazetteer.csv baseline models/2026-11-05-baseline-real-v1
```

El equivalente es `uv run python scripts/train.py --dataset <I1> --geo <I3> --gazetteer <I2> --model baseline --out models/<version>/`.
La salida contiene model.json, calibration.json, metadata.json, gazetteer.csv, geo_features.csv
más la atribución OSM. Un artefacto existente exige elegir otra versión.

## Datos y features

La lista de entradas se deriva de PredictionRequest y se agregan las columnas dist_* y n_* de I3.
Se ignoran garages y street_surface por indicación de Brian. El join usa city y neighborhood,
con fila de ciudad si el barrio está ausente o sin correspondencia. Se aceptan las columnas I3
originales del sintético y las nuevas de geo porque se leen del archivo suministrado.

El baseline usa city, neighborhood y property_type. El resto de X queda disponible para la
siguiente entrega de modelado. Cada cluster tiene un voto mediante la mediana de sus targets.
La jerarquía es barrio, tipo+ciudad, ciudad y global. Cada nivel requiere 20 clusters de
entrenamiento y el global es el último respaldo. El umbral es un parámetro explícito del CLI.

## Evaluación e intervalos

Se usan grouped_kfold de avm.model.splits con cinco folds y semilla 7. El primer fold es el
test del artefacto. Su train se divide con cuatro folds y semilla 8, reservando uno para
calibración. Aproximadamente 60 % de filas entrenan, 20 % calibran y 20 % evalúan. Los clusters
quedan completos y disjuntos en las tres particiones. El modelo entregado conserva esa separación.

Los límites provienen de los cuantiles 0,1 y 0,9 de residuos firmados de log USD/m² del set de
calibración. Se extienden hasta cero si hace falta para contener la estimación puntual. La
cobertura nominal declarada es 80 %. Este método empírico se reemplazará por CQR en F9.
Los folds externos también se evalúan con entrenamiento y calibración internos separados.
metadata.metrics contiene el test del artefacto y grouped_kfold contiene los cinco folds.
Las métricas por tipo y ciudad quedan en metrics_by_segment, siempre en fracciones.

## Conexión con la API

La clase avm.model.predictor.Predictor cumple load, predict, neighborhoods y metadata de I4.
La API existente puede cargarla con su configuración habitual.

```powershell
$env:AVM_PREDICTOR="model"
$env:AVM_MODEL_DIR="models/2026-11-05-baseline-real-v1"
just serve
```

El Predictor reconoce nombres canónicos y alias. Un barrio desconocido informa
barrio_desconocido y usa el respaldo de ciudad. Un barrio con menos de 20 clusters de train
informa pocos_datos. Departamento conserva confianza reducida por el supuesto de identificación
de superficie, incluso si supera ese umbral. El mensaje lo explica y la política queda en
metadata.low_confidence_property_types. Los totales multiplican USD/m² por built_area_m2.

## Dataset real recibido

El ZIP de 52.729 bytes contiene 1.769 filas con 672 casas, 510 departamentos y 587 dúplex.
El reporte del ZIP y el CSV coinciden. Las cifras de 1.376 filas y 117 departamentos del mensaje
corresponden a otra versión. Todos los avisos del archivo recibido tienen resolución de ciudad.
El reporte señala 393 departamentos cuya superficie se aceptó sin tipo identificado.

Los artefactos sintéticos se marcan is_test_model=true. El artefacto real se marca false.
Ambos incluyen hashes de los insumos y pasan scripts/check_deploy_model.py. Los archivos de
entrenamiento y las carpetas models permanecen fuera de git y se entregan en ZIP privado.
