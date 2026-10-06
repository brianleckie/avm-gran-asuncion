"""FeatureRow (F1.4): DIFERIDO. Este módulo todavía no define ningún schema.

FeatureRow es el input del modelo, con columnas y tipos congelados. No se define en el contrato
v0.1.0 porque sus columnas dependen de decisiones que todavía no se tomaron:

- Las features geo (F6.4): distancia del centroide del barrio (o de las coordenadas, F6.5) al POI
  más cercano por categoría, conteos de POIs en un radio y distancia a centros de empleo. Las
  categorías, el radio y los centros de empleo se fijan en F6.3/F6.4.
- El encoding del barrio (F8.6: target encoding dentro del fold) y el denominador del target
  (USD/m² sobre m² construidos, ADR-006 P13).

Definirlo ahora obligaría a inventar columnas y a cambiar el contrato apenas se definan las
features. Lo desbloquea F6.4. Mientras tanto, F1.4 queda abierta en el ROADMAP.
"""
