# ADR-001: El modelo estima precio de oferta, no de transacción
- Estado: aceptado
- Autores: Brian Leckie, Oscar Arce

## Contexto
Paraguay no tiene MLS ni un registro público de precios de cierre. Los únicos datos masivos disponibles son los avisos de portales.

## Decisión
El target es el precio publicado (USD/m²). Todo output se rotula "precio de oferta estimado".

## Consecuencias
- No se puede medir el descuento de negociación (gap oferta→cierre).
- Las métricas miden la capacidad de predecir precios publicados, no valores de cierre.
- Debe figurar en limitaciones, en la UI y en la defensa.

## Alternativas descartadas
- Usar avalúo fiscal de Catastro como proxy de mercado: está muy por debajo del valor comercial.
