# LightGBM y CQR por tipo (F8.6, F9)

La implementación usa v2 para desarrollo. La evaluación final y la ablation final quedan
pendientes del dataset v3 que está curando Brian. El v2 recibido contiene 1.769 filas,
384 con barrio y 1.385 con respaldo de ciudad. Departamento mantiene confianza reducida
por la identificación de superficie construida. Su menor error requiere considerar ese
supuesto de medición, especialmente las 393 de 510 superficies aceptadas sin tipo en v1/v2.

## Ejecución

Desde la raíz del repositorio, con una carpeta de salida nueva para cada corrida.

```powershell
just train data/processed/dataset-v2/dataset.csv data/reference/geo_features.csv data/reference/gazetteer.csv lightgbm-cqr models/lgbm-cqr-v2-development --dataset-version v2 --stage development
just evaluate data/processed/dataset-v2/dataset.csv data/reference/geo_features.csv data/processed/evaluation-v2 v2 --stage development
```

Las mismas entradas sirven para v3 cambiando ruta, versión y carpetas de salida. Brian puede
reproducir la evaluación final con `--stage final` y guardar un reporte agregado mediante
`--report docs/results/<fecha>-v3.md`. La selección de la versión final del modelo requiere
revisar ese reporte y la calidad del v3. Los artefactos de desarrollo declaran
`is_test_model=true` y el cargador existente de la API los rechaza en modo production.

El baseline continúa disponible con `--model baseline` y su formato I4 original. Los
artefactos LightGBM usan `model.bin`, un JSON comprimido con gzip que contiene los tres
boosters de texto, vocabularios categóricos y conteos agregados de soporte. Su carga
reconstruye los boosters mediante la API nativa de LightGBM. La interfaz Predictor I4 se
conserva. La guardia `scripts/check_deploy_model.py` valida la carpeta completa.

## Entrenamiento sin leakage

Se reutilizan las particiones grouped_kfold de avm.model.splits. Cinco folds externos
separan test. Dentro de cada train externo se reserva uno de cuatro folds para calibrar.
El train restante se divide nuevamente por cluster para seleccionar entre dos
configuraciones fijas. La selección minimiza MAE de log USD/m² en validación interna.
Después se ajustan los tres cuantiles 0,1, 0,5 y 0,9 sobre todo ese train, con la configuración
seleccionada. Los conjuntos de calibración y test se mantienen fuera del ajuste y del tuning.

Las categóricas nativas usan vocabularios aprendidos en train y categorías desconocidas como
faltantes. Cada fila recibe peso 1/tamaño de su cluster, calculado dentro del train. Las
numéricas admiten faltantes. Garages y street_surface continúan excluidos por cobertura.

La ablation usa exactamente los mismos folds, semillas y presupuesto de tuning para ambos
casos. Elimina las columnas dist_* y n_* de I3 y conserva ciudad, barrio y geo_precision de I1.
Por tanto mide el aporte incremental de las variables espaciales sobre la información de
ubicación que ya aporta el formulario. El baseline global empírico queda como referencia
adicional y se vuelve a entrenar en los mismos folds de cada dataset.

## Calibración por tipo de propiedad

Antes de calibrar, la envolvente de los cuantiles inferiores y superiores incluye también
la predicción mediana para tratar cruces. Para cada observación de calibración se calcula
`max(q_low - y, y - q_high, 0)` en escala logarítmica. Para cada tipo se toma un score máximo
por cluster, evitando contar republicaciones como observaciones independientes.

Con m clusters del tipo, se selecciona el score ordenado en la posición
`ceil((m + 1) * 0.8)`. Ese valor expande ambos límites logarítmicos. El resultado vuelve a
USD/m² y los totales multiplican por la superficie construida. Si el tipo carece de suficientes
clusters para obtener un cuantil finito al 80 %, el entrenamiento falla de forma explícita.
La calibración guarda qhat, m, número de filas y rango elegido para cada tipo.

El argumento de cobertura requiere intercambiabilidad de los clusters dentro de cada tipo,
con un score máximo para sus observaciones. La cobertura empírica puede fluctuar en test
y por fold. Los cambios del mercado, errores de deduplicación y sesgos del portal afectan
esa hipótesis. El reporte muestra cobertura por fila y cobertura conjunta por cluster,
antes y después de CQR, globalmente y por tipo. La cobertura de subgrupos como una ciudad
o precisión geográfica se evalúa empíricamente.

## Reportes y trazabilidad

`scripts/evaluate.py` produce metrics.csv, evaluation.json y report.md. El CSV contiene
métricas por fold, tipo, ciudad, precisión geo, soporte barrial y tercil de USD/m². Los cortes
de tercil se calculan solo en train. Los JSON registran semillas, hashes de insumos,
configuraciones evaluadas y correcciones conformales de cada tipo en cada fold.

Los valores reportados como media de folds son medias sin ponderación y se acompañan de
mínimo y máximo. El artefacto del modelo conserva las métricas del fold externo cero como
test propio, separadas de la evaluación completa. Los modelos finales y los resultados
finales de ablation se regenerarán con v3.

Las métricas de ancho por precisión y soporte permiten investigar F9.4. La corrección por
tipo y los modelos cuantílicos adaptativos permiten anchos variables. El reporte conserva
el comportamiento observado para revisarlo con la muestra final.

## Runtime de Linux

Dockerfile instala libgomp1 mediante apt-get antes de sincronizar las dependencias de uv.
La verificación incluye construir python:3.12-slim e importar LightGBM dentro de esa imagen.
Vercel despliega desde main según la configuración de Brian. Los PRs quedan para revisión.

## Fuentes verificadas

- Romano, Patterson y Candès (2019), Conformalized Quantile Regression.
  https://arxiv.org/abs/1905.03222
- Documentación oficial de LGBMRegressor.
  https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.LGBMRegressor.html
- Guía oficial de instalación de LightGBM, runtime OpenMP.
  https://lightgbm.readthedocs.io/en/stable/Installation-Guide.html
