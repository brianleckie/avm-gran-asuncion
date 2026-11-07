# Limitaciones

## Qué representa la estimación

El target es un **precio publicado de oferta**. No se observan negociaciones, descuentos ni transacciones cerradas; el error de test mide reproducción de avisos. El total depende de la superficie cargada. No se debe usar el sistema como tasación profesional ni como evidencia de un precio de cierre. Fuentes: [ADR-001](adr/001-precio-publicado.md) y [contrato](../src/avm/contract/prediction.py).

## Muestra y período

Hay una sola fuente, Clasipar, y un período limitado representado por snapshots del 06/10/2026 y 04/11/2026. Los avisos y las ciudades no son una muestra probabilística del parque inmobiliario. Disponibilidad de superficie, forma de publicación y filtros condicionan quién entra: 1.769 de 3.239 avisos únicos tienen target utilizable. No se midió representatividad contra ventas ni se puede inferir evolución temporal. Fuentes: [calidad, secciones 0–2](results/v3-quality-report.md) y [fuentes](sources.md).

## Moneda

Se usa una cotización única de 6.085 PYG/USD del 04/11/2026 para todos los snapshots. No se ajusta por la fecha de publicación ni por la cotización histórica de cada scrape. Su efecto temporal no se cuantificó. Los avisos en USD no requieren conversión. Fuentes: [ADR-004, desvío documentado](adr/004-moneda.md) y [calidad](results/v3-quality-report.md).

## Superficie y datos faltantes

En departamentos, 393 de 510 filas ingresan por superficie sin tipo explícito. La hipótesis de que corresponde a construcción no se validó individualmente; el denominador del target puede contener errores. El MdAPE menor de departamentos no se presenta como un logro: mantiene advertencia de confianza reducida. Fuentes: [calidad, sección 5](results/v3-quality-report.md), [ADR-006](adr/006-contrato-v0.1.md) y [Predictor](../src/avm/model/predictor.py).

`garages` está vacío en el 100 % de las filas; `street_surface` tiene 96,6 % faltante. Ambas variables se excluyen del modelo. Ausencia de dato no significa ausencia del atributo. Los otros campos faltantes y categorías desconocidas también reducen la información disponible. Fuentes: [calidad, completitud](results/v3-quality-report.md), [whitelist](../src/avm/model/data.py) y [LightGBM](../src/avm/model/lgbm.py).

## Cobertura y resolución geográfica [OSCAR]

Solo 492 de 1.769 filas, 27,8 %, tienen barrio reconocido; 1.277 usan resolución de ciudad. La cobertura varía: Asunción 44,8 %, Luque 22,5 %, San Lorenzo 19,3 % y Fernando de la Mora 5,1 %. La mejora global desde 21,7 % no resuelve el faltante y no justifica forzar zonas amplias a un barrio. Fuentes: [calidad, sección 3](results/v3-quality-report.md) y [auditoría antes/después](alias-barrios-v3.md).

Los centroides/puntos interiores representan barrios, no ubicaciones individuales. Propiedades del mismo barrio reciben las mismas features geo, sin distinguir cuadra, calle, accesibilidad efectiva ni calidad constructiva. Los límites y POIs de OSM pueden estar incompletos o desactualizados; no se equiparan automáticamente con unidades censales o electorales. Fuentes: [ADR-003](adr/003-geo-a-nivel-barrio.md), [geo y huecos de cobertura](geo.md) e [I3](interfaces.md). © OpenStreetMap contributors, ODbL.

La ablation agrega o retira las columnas numéricas de I3; ciudad y barrio siguen presentes. Por ello no estima el efecto de eliminar toda información geográfica. El aporte observado es mixto, sin mejora consistente del MdAPE en los folds del conjunto completo. Fuente: [evaluación v3](results/2026-11-06-v3.md) y [selección de features](../src/avm/model/lgbm.py).

## Duplicados y generalización [OSCAR]

Las particiones respetan clusters, pero la heurística puede no detectar republicaciones con identificador o precio modificado y puede agrupar avisos distintos. No hay validación exhaustiva de identidad ni deduplicación por imágenes. Un split por cluster no prueba ausencia absoluta de inmuebles repetidos. Fuentes: [dedup](../src/avm/pipeline/dedup.py) y [advertencias del quality report](results/v3-quality-report.md).

Esta entrega usa particiones agrupadas, no test prospectivo, temporal ni leave-barrio-out. La selección separada del holdout fue incorporada durante un análisis exploratorio, que también inspeccionó la evaluación completa; no hubo prerregistro. Aunque el código excluye sus filas de la selección, se necesita una muestra futura independiente para confirmar resultados. Fuentes: [metodología](metodologia.md), [evaluación](../src/avm/model/experiment.py) e [informe](results/2026-11-06-v3.md).

## Cobertura de intervalos [OSCAR]

CQR se calibra por tipo, con nominal 80 % bajo intercambiabilidad de clusters. En el test del candidato la cobertura global es 78,53 % y en casas 74,05 %; departamentos 80,85 % y dúplex 81,40 %. **Casas queda por debajo del nominal incluso después de calibrar por tipo.** La calibración no elimina todos los desbalances y su garantía no es condicional a cada ciudad, barrio o inmueble. Fuentes: [metadata por tipo](results/v3-model-summary.json) y [calibración](../src/avm/model/conformal.py).

El ancho relativo medio es 84,41 % global y 102,82 % en casas: el intervalo puede ser poco preciso para tomar decisiones individuales. Un intervalo amplio no corrige un target mal medido. Esos anchos se calculan respecto de la predicción puntual. Fuentes: [metadata](results/v3-model-summary.json), [métricas](../src/avm/model/metrics.py) e [I4](interfaces.md).

## Operación y pendientes

La versión documentada es un candidato revisable. Solo se considera publicada cuando el merge humano y el redeploy terminan, `/model-info` informa su versión y pasa el smoke real. La salud del baseline anterior no prueba la del candidato. Fuentes: [deploy](../deploy/README.md) y [smoke](../scripts/smoke.py).

Quedan fuera de esta entrega OLS, Random Forest y los tests temporal/leave-barrio-out. Tampoco se presentan SHAP, comparables ni una serie histórica de cotizaciones como entregados. Se priorizaron pipeline, Predictor, ablation y calibración por tipo. Fuente: [ROADMAP](../ROADMAP.md).

## Referencias

[REFERENCIAS — completar a mano]
