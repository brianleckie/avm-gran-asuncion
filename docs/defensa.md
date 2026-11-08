# Defensa y demo

## Preparación

Abrir la [web](https://avm-gran-asuncion.vercel.app), la [información del modelo activo](https://avm-gran-asuncion-production.up.railway.app/model-info), el [informe v3](results/2026-11-06-v3.md) y las [limitaciones](limitaciones.md). Tener el reporte descargado como respaldo; si falla la red, mostrarlo sin fingir una respuesta en vivo.

Antes del ensayo ejecutar el smoke indicado en [deploy/README](../deploy/README.md). Comparar `model_version` de la API con la del artefacto: la web puede seguir sirviendo el baseline hasta el merge y redeploy del candidato. Las métricas de v3 pertenecen al informe, no a una versión activa que no se haya verificado.

Estado comprobado el 08/11/2026: Railway sirve v3 y el smoke pasó después del merge de #23. [Registro y alcance de la verificación](results/smoke-v3-2026-11-08.md). Repetir antes de la presentación porque el estado del servicio puede cambiar.

## Guion propuesto de diez minutos

Estos tiempos son una agenda de ensayo, no mediciones de rendimiento.

**0:00–1:00 — Problema y alcance.** Brian presenta la calculadora de precio de oferta por superficie y total. Aclarar que el portal muestra ofertas y no transacciones. Mencionar ciudades y tipos del formulario sin ampliar el alcance. Respaldo: [ADR-001](adr/001-precio-publicado.md) y [contrato](../src/avm/contract/prediction.py).

**1:00–3:00 — Entrada y recorrido.** Brian elige ciudad, un barrio disponible, tipo y superficie construida. Completar atributos solo cuando se conocen; no transformar “No sé” en “No”. Ejecutar la estimación y señalar unidad, total, intervalo y advertencias. El ejemplo se elige para mostrar el flujo: no es una observación validada del dataset. Respaldo: [frontend](../web/src/), [request/response](../src/avm/contract/prediction.py) y [API](../src/avm/api/).

**3:00–4:30 — Datos y geo [OSCAR].** Mostrar el embudo de calidad y la diferencia entre barrio reconocido y fallback a ciudad. Explicar que los alias corrigen escrituras, sin mirar precios; los nombres ambiguos se dejan sin barrio. Decir “27,8 % con barrio reconocido”, no cobertura completa de la ciudad. Respaldo: [quality report](results/v3-quality-report.md) y [auditoría](alias-barrios-v3.md).

**4:30–6:00 — Modelo [OSCAR].** Explicar baseline de medianas y LightGBM, separación por clusters y calibración independiente por tipo. La selección favorece LightGBM con geo por MdAPE medio de desarrollo: 18,32 % frente a 18,63 % sin geo y 22,06 % del baseline. Aclarar que es análisis exploratorio, no un ensayo prospectivo. Respaldo: [selección](results/v3-selection-metrics.csv) y [metodología](metodologia.md).

**6:00–7:30 — Resultados e incertidumbre [OSCAR].** Mostrar el test del candidato: MdAPE 20,92 %, cobertura global 78,53 % y casas 74,05 %. Explicar que el 80 % es nominal y casas sigue por debajo. No presentar la menor MdAPE de departamentos como un éxito porque 393 de 510 superficies entraron sin tipo explícito. Respaldo: [metadata](results/v3-model-summary.json) y [calidad, sección 5](results/v3-quality-report.md).

**7:30–9:00 — Pregunta de investigación [OSCAR].** Mostrar ablation con/sin features numéricas geo. La señal es mixta: no afirmar que geo mejora siempre. Ciudad y barrio siguen en ambas variantes. Reconocer fuente única, período corto, fallback mayoritario y cotización única. Respaldo: [ablation](results/2026-11-06-v3.md) y [limitaciones](limitaciones.md).

**9:00–10:00 — Cierre de la demo.** Brian muestra la página de metodología, la versión activa y el recorrido API/web. Proponer nuevos snapshots, revisión de superficies y más cobertura de barrios como próximos pasos; distinguirlos del trabajo ya entregado. Respaldo: [deploy](deploy.md), [ROADMAP](../ROADMAP.md) y [limitaciones](limitaciones.md).

## Preguntas probables y respuestas cortas

### Respuestas orales de modelo y geo [OSCAR]

Guía para ensayar el domingo 08/11/2026 a las 19:30, hora de Asunción. Las respuestas siguientes son texto de práctica, no una transcripción de un ensayo ya realizado. Recordar la idea y el límite de cada respuesta, sin memorizar cifras de protocolos distintos.

**(a) ¿Por qué LightGBM le gana al baseline?** «El baseline asigna medianas por ubicación y tipo: dos inmuebles del mismo grupo pueden recibir el mismo precio por metro cuadrado aunque cambien sus atributos. LightGBM puede aprender relaciones no lineales e interacciones entre superficie, ambientes y amenities. En nuestros folds agrupados, el MdAPE medio baja de 22,1 % del baseline a 18,2 % con geo. Ese resultado es compatible con aprovechar mejor esos atributos; no probamos qué feature explica la mejora ni que ocurra en cualquier muestra». Fuentes: [baseline](../src/avm/model/baseline.py), [LightGBM](../src/avm/model/lgbm.py) y [CV completa](results/v3-all-folds-metrics.csv).

**(b) ¿Por qué la geo no mejora?** «Al retirar distancias y conteos, el MdAPE medio pasa de 18,2 % con geo a 18,1 % sin geo: no vemos una mejora consistente. Solo el 27,8 % tiene barrio reconocido; el resto usa referencias de ciudad, y dentro de cada barrio esas features son iguales para todos. Eso puede limitar su aporte y redundar con ciudad/barrio, que siguen presentes en ambas variantes. Son explicaciones plausibles, no causas demostradas: el RMSE log sí mejora con geo y en desarrollo separado la selección la favoreció». Fuentes: [ablation completa](results/v3-all-folds-ablation.csv), [calidad](results/v3-quality-report.md), [informe que separa ambos protocolos](results/2026-11-06-v3.md) y [features](../src/avm/model/lgbm.py).

**(c) ¿Por qué la cobertura de casas es 74 % y no 80 %?** «El 80 % es una cobertura nominal del procedimiento bajo intercambiabilidad de clusters de casas, no un porcentaje exacto que deba repetirse en cada test. En este test, 97 de 131 casas quedaron dentro: 74,05 %. Calibramos con otros 125 clusters de casas, pero el tamaño finito y posibles diferencias entre calibración y test pueden afectar la cobertura observada. No medimos una causa única ni podemos asegurar que solo sea azar: es subcobertura observada que reportamos como limitación, sin retocar el intervalo con el test». Fuentes: [metadata por tipo](results/v3-model-summary.json), [calibración publicada](../deploy/model/calibration.json), [cálculo](../src/avm/model/conformal.py) y [referencias conformales](referencias.md#conformal-prediction-y-cqr).

**(d) CQR en una frase.** «CQR toma un intervalo de regresión cuantílica y lo corrige con errores de un conjunto de calibración separado para buscar la cobertura nominal bajo intercambiabilidad; nosotros calibramos por tipo y usamos el peor error de cada cluster». Fuentes: [Romano, Patterson y Candès (2019)](https://arxiv.org/abs/1905.03222), [adaptación implementada](../src/avm/model/conformal.py) y [referencias](referencias.md).

**Repregunta: ¿cómo explicás Fernando de la Mora?** «Doce coincidencias con Zona Sur daban una precisión de barrio que no podíamos sostener. Las bloqueamos; entró un exacto nuevo y por eso el total exacto baja once. De los 86 ambiguos, 74 ya estaban sin match: no perdimos 86 barrios». Respaldo: [párrafo auditado](alias-barrios-v3.md) y [transiciones](results/fdlm-match-transitions-v3.json).

Para evitar mezclar resultados: las cifras 22,1 / 18,2 / 18,1 % son **medias de MdAPE de folds de la CV completa**, no una mediana global concatenada, ni el test del artefacto. La selección en desarrollo separado da 22,06 / 18,32 / 18,63 % (baseline / con geo / sin geo); el test del candidato da MdAPE 20,92 %. Fuentes: [CV completa](results/v3-all-folds-metrics.csv), [selección](results/v3-selection-metrics.csv) y [test](results/v3-model-summary.json).

Ensayo sugerido: responder cada letra sin leer, explicar qué compara cada cifra y aceptar la repregunta «¿cómo lo comprobaste?». La respuesta debe señalar el archivo correspondiente y distinguir evidencia de hipótesis. No presentar el análisis exploratorio como validación prospectiva.

### Banco general de preguntas

1. **¿Qué predice exactamente?** Precio publicado de oferta por m² construido; el total multiplica por la superficie. No conocemos el monto de cierre. Respaldo: [ADR-001](adr/001-precio-publicado.md) y [contrato](../src/avm/contract/prediction.py).

2. **¿Por qué una sola fuente?** Clasipar fue la fuente utilizable dentro del alcance; InfoCasas se descartó por sus términos. Eso limita representatividad. Respaldo: [sources.md](sources.md).

3. **¿Cuántos datos usaron y de cuándo?** El v3 tiene 1.769 filas a partir de snapshots del 06/10/2026 y 04/11/2026. Son observaciones de un portal, no un censo. Respaldo: [calidad, secciones 0–2](results/v3-quality-report.md).

4. **¿Cómo convierten guaraníes?** Con 6.085 PYG/USD del 04/11/2026 para todos los snapshots; es el desvío por plazo documentado y su variación temporal no fue medida. Respaldo: [ADR-004](adr/004-moneda.md).

5. **¿Por qué desconfiar del resultado en departamentos?** En 393 de 510 se acepta superficie sin tipo explícito; puede contaminar el denominador. Se advierte confianza reducida y no se presume un logro por menor error. Respaldo: [calidad, sección 5](results/v3-quality-report.md) y [Predictor](../src/avm/model/predictor.py).

6. **¿Cómo evitan que un aviso repetido infle las métricas?** Deduplicamos y dividimos por cluster, sin compartir clusters entre ajuste, calibración y test. La identidad es heurística y puede fallar. Respaldo: [dedup](../src/avm/pipeline/dedup.py) y [splits](../src/avm/model/splits.py).

7. **¿Hay fuga de información?** El código ajusta vocabularios/modelos en train y calibra aparte; el holdout se excluye del cálculo de selección. Fue un análisis exploratorio con inspección de resultados completos, por lo que falta confirmación prospectiva. Respaldo: [experimento](../src/avm/model/experiment.py) y [metodología](metodologia.md).

8. **¿Qué aporta la geografía?** Features compartidas por barrio o ciudad, no coordenadas del inmueble. Su aporte incremental es mixto; no demostramos mejora consistente de MdAPE. Respaldo: [geo](geo.md) y [ablation v3](results/2026-11-06-v3.md).

9. **¿Por qué no asignar todos los barrios por parecido?** Un nombre amplio u homónimo puede ubicar mal el inmueble. Preferimos fallback antes que una precisión inventada; fuzzy queda en 90 y los alias manuales requieren equivalencia. Respaldo: [normalización](../src/avm/pipeline/neighborhood.py), [CSV de alias](../src/avm/pipeline/neighborhood_aliases.csv) y [auditoría](alias-barrios-v3.md).

10. **¿Por qué el modelo elegido tiene geo si algunas métricas empeoran?** La regla usa MdAPE medio en CV de desarrollo, donde gana con geo. No cambiamos la elección mirando el test; informamos también que sin geo obtuvo menor MdAPE en ese test y que el efecto completo es mixto. Respaldo: [criterio y resultados](results/2026-11-06-v3.md).

11. **¿Qué significa el intervalo del 80 %?** Es cobertura nominal de un procedimiento calibrado bajo intercambiabilidad de clusters del mismo tipo, no probabilidad garantizada para cada propiedad. La cobertura observada se informa aparte. Respaldo: [CQR](../src/avm/model/conformal.py) y [LightGBM/CQR](lightgbm-cqr.md).

12. **¿Alcanza esa cobertura en casas?** No: el test del candidato da 74,05 %, debajo del nominal. Lo reportamos incluso con calibración por tipo; hace falta más evidencia y revisar heterogeneidad. Respaldo: [metadata por segmento](results/v3-model-summary.json).

13. **¿Qué pasa con barrio desconocido o atributos faltantes?** Se usan referencias de ciudad y warnings; categorías nuevas/faltantes se manejan como desconocidas. Cocheras y superficie de calle se excluyeron por falta de datos. Respaldo: [Predictor](../src/avm/model/predictor.py), [features](../src/avm/model/data.py) y [calidad](results/v3-quality-report.md).

14. **¿Cómo se conectan modelo, API y web sin filtrar avisos?** Predictor implementa I4; la API valida el contrato y sirve estimación/metadata. El deploy incluye parámetros, agregados y referencias geográficas, sin filas del dataset. Respaldo: [interfaces](interfaces.md), [guardia](../scripts/check_deploy_model.py) y [ADR-008](adr/008-modelo-en-produccion.md).

15. **¿Qué falta para generalizar mejor?** Nuevos períodos, revisión de superficies, cobertura de barrios y evaluación independiente temporal/espacial. OLS, RF, SHAP y comparables no se presentan como completados. Respaldo: [limitaciones](limitaciones.md) y [ROADMAP](../ROADMAP.md).

## Referencias para la defensa

Consultar [referencias con metadatos, enlaces originales y alcance](referencias.md). Revisar a mano los pendientes **VERIFICAR** y el formato exigido por la facultad; no atribuir los umbrales PE10/PE20 a un estándar sin comprobarlo. Los archivos enlazados en cada respuesta respaldan lo implementado y medido.
