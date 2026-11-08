# Referencias y alcance de cada cita

Consulta y contraste web: 08/11/2026. Se indican autores institucionales cuando corresponde. «s. f.» significa que la página no identifica una fecha de publicación inequívoca; la fecha de consulta no se presenta como año de publicación. **VERIFICAR** señala un punto pendiente, no una referencia ficticia. La revisión bibliográfica humana final sigue pendiente.

## AVM y modelos hedónicos

- **Rosen, Sherwin (1974).** *Hedonic Prices and Implicit Markets: Product Differentiation in Pure Competition*. Journal of Political Economy, 82(1), 34–55. DOI: [10.1086/260169](https://doi.org/10.1086/260169). [Ficha del editor](https://www.journals.uchicago.edu/doi/10.1086/260169). Autores, año, volumen y páginas verificados en el editor. Fundamenta modelar precios en función de características; no demuestra que nuestros avisos representen transacciones ni que hayamos entrenado OLS.

- **International Association of Assessing Officers — IAAO (2018).** *Standard on Automated Valuation Models (AVMs)*. [Documento institucional](https://www.iaao.org/media/standards/Standard_on_Automated_Valuation_Models.pdf). **VERIFICAR** edición y pasajes/páginas en el PDF descargado antes de citar una exigencia concreta: el índice identifica título/año, pero la apertura directa del documento quedó bloqueada por verificación JavaScript. Se propone como contexto de evaluación de AVM, sin afirmar cumplimiento, certificación ni trasladar umbrales a precios de oferta paraguayos.

## MdAPE, PE10 y PE20

- **Hyndman, Rob J.; Koehler, Anne B. (2006).** *Another look at measures of forecast accuracy*. International Journal of Forecasting, 22(4), 679–688. DOI: [10.1016/j.ijforecast.2006.03.001](https://doi.org/10.1016/j.ijforecast.2006.03.001). [Ficha y cita del autor](https://otext.robjhyndman.com/publications/another-look-at-measures-of-forecast-accuracy/); [borrador del autor](https://robjhyndman.com/papers/mase.pdf). La ficha confirma la publicación de 2006; el borrador está fechado en 2005. Trata MdAPE y límites de errores porcentuales; no recomienda universalmente nuestra métrica principal ni define nuestros nombres PE10/PE20.

- **Arce, Oscar; Leckie, Brian (2026).** *AVM Gran Asunción: definiciones implementadas de métricas*. Repositorio del proyecto, revisión `67c277d`. [Código versionado](https://github.com/brianleckie/avm-gran-asuncion/blob/67c277d/src/avm/model/metrics.py). Fuente primaria para las definiciones exactas usadas aquí: `MdAPE = median(abs(y_pred-y)/y)` y `PE(t) = mean(abs(y_pred-y)/y <= t)`, con `t=0.10` y `0.20`. Son fracciones y se multiplican por cien al presentarlas como porcentajes. Los dos umbrales son decisiones del proyecto, no se atribuyen a IAAO. La bibliografía externa no sustituye este contrato operativo.

- **Ecker, Mark; Isakson, Hans; Kennedy, Lee (2020).** *An Exposition of AVM Performance Metrics*. Journal of Real Estate Practice and Education, 22(1), 22–39. DOI: [10.1080/15214842.2020.1757352](https://doi.org/10.1080/15214842.2020.1757352). [Ficha/PDF del editor](https://www.tandfonline.com/doi/pdf/10.1080/15214842.2020.1757352). Metadatos y resumen identificados en el editor; el artículo aborda métricas de AVM y bandas de error. **VERIFICAR** el pasaje exacto antes de atribuirle las tolerancias PE10/PE20 o una fórmula específica: el texto completo no se pudo abrir directamente. Referencia complementaria, no prueba de cumplimiento de estándares.

## Conformal prediction y CQR

- **Angelopoulos, Anastasios N.; Bates, Stephen (2021; revisión consultada de 2022).** *A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification*. arXiv:2107.07511, versión 6. DOI: [10.48550/arXiv.2107.07511](https://doi.org/10.48550/arXiv.2107.07511); [registro de autores, versiones y texto](https://arxiv.org/abs/2107.07511). Introducción a cobertura marginal y supuestos conformales. Se cita este preprint, sin inventar datos de otra edición editorial.

- **Romano, Yaniv; Patterson, Evan; Candès, Emmanuel J. (2019).** *Conformalized Quantile Regression*. Advances in Neural Information Processing Systems, 32. [Publicación original](https://proceedings.neurips.cc/paper/2019/hash/5103c3584b063c431bd1268e9b5e76fb-Abstract.html); [preprint de los autores](https://arxiv.org/abs/1905.03222). Fundamenta combinar regresión cuantílica con calibración conformal. Nuestra calibración por tipo y score máximo por cluster es una adaptación implementada en [conformal.py](../src/avm/model/conformal.py); el artículo no valida por sí solo nuestros clusters, la intercambiabilidad ni cobertura en cada barrio.

## LightGBM

- **Ke, Guolin; Meng, Qi; Finley, Thomas; Wang, Taifeng; Chen, Wei; Ma, Weidong; Ye, Qiwei; Liu, Tie-Yan (2017).** *LightGBM: A Highly Efficient Gradient Boosting Decision Tree*. Advances in Neural Information Processing Systems, 30. [Publicación original y autores](https://papers.nips.cc/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html). Fundamenta el algoritmo. La mejora medida en este proyecto procede de [los resultados v3](results/2026-11-06-v3.md), no de los benchmarks del artículo; no se afirma haber activado todas las optimizaciones que describe.

## Particiones agrupadas y leakage

- **scikit-learn developers (s. f.).** *GroupKFold*. Documentación de scikit-learn, versión mostrada 1.9.1, consulta 08/11/2026. [Documentación oficial](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupKFold.html). Explica folds con grupos disjuntos. El proyecto implementa su propio `grouped_kfold` en [splits.py](../src/avm/model/splits.py); se cita como fundamento del principio, sin afirmar que llama a esa clase ni que produce exactamente su reparto.

- **scikit-learn developers (s. f.).** *Common pitfalls and recommended practices*, apartado *Data leakage*. Documentación de scikit-learn, versión mostrada 1.9.1, consulta 08/11/2026. [Documentación oficial](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage). Sustenta separar test y aprender transformaciones solo con train. No certifica nuestro experimento: el protocolo exploratorio y sus límites están en [metodología](metodologia.md).

## OpenStreetMap y licencia

- **OpenStreetMap Foundation y colaboradores de OpenStreetMap (s. f.).** *Copyright and License*. [Página oficial](https://www.openstreetmap.org/copyright), consulta 08/11/2026. Identifica datos OSM bajo ODbL y requisitos de atribución. Usar «© OpenStreetMap contributors» y enlazar licencia según el tipo de publicación. No acredita exhaustividad ni equivalencia entre barrios OSM y unidades oficiales.

- **Open Data Commons (s. f.).** *Open Data Commons Open Database License (ODbL), v1.0*. [Texto de licencia](https://opendatacommons.org/licenses/odbl/1-0/), consulta 08/11/2026. La página consultada identifica la versión, sin una fecha de publicación inequívoca; por eso no se inventa año. Se cita la licencia de la base, no una licencia general para todos los contenidos del proyecto.

## robots.txt

- **Koster, Martijn; Illyes, Gary; Zeller, Henner; Sassman, Lizzi (2022).** *Robots Exclusion Protocol*. RFC 9309, IETF, septiembre de 2022. DOI: [10.17487/RFC9309](https://doi.org/10.17487/RFC9309); [ficha y autores](https://www.rfc-editor.org/info/rfc9309/); [texto](https://www.rfc-editor.org/rfc/rfc9309.html). Fundamenta lectura de reglas de rastreo, tratamiento de errores y caché. Respetar robots no equivale a autorización legal ni reemplaza los términos del sitio.

## Uso en el informe

Las cifras del proyecto se citan desde reportes internos, no desde estos artículos. Incorporar al formato bibliográfico de la facultad solo las referencias efectivamente utilizadas y comprobar a mano los dos pendientes marcados **VERIFICAR**. La lista cubre los temas solicitados sin afirmar cumplimiento de un estándar de valuación.
