# Evidencia: tiempo de inferencia, ejemplo de respuesta y Docker Compose (2026-11-09)

Respaldo de las cifras de la sección III del informe IEEE (tiempo de inferencia y ejemplo de precio).

## Cómo se midió

```bash
uv run python scripts/bench_inference.py --model-dir deploy/model --repeats 10
```

- Modelo: `2026-11-06-v3-lightgbm-cqr` (el publicado en `deploy/model/`).
- 600 predicciones en proceso, sin HTTP ni red: 4 ciudades × 3 tipos × 5 superficies
  ({60, 90, 120, 180, 250} m²), con barrios del nomenclador, repetidas 10 veces tras 5 de calentamiento.
- Máquina: contenedor Linux de 2 vCPU (Intel Xeon @ 2.10GHz), Python 3.13.18.
  No es el hardware de producción (Railway), así que los tiempos son orientativos.

## Resultados

| Corrida | Carga del modelo | Mediana | p95 | Máximo |
|---|---|---|---|---|
| 1 (en frío, primera ejecución tras instalar) | 5.208 s | 21.35 ms | 32.97 ms | 84.78 ms |
| 2 (en caliente) | 0.869 s | 21.95 ms | 32.17 ms | 45.81 ms |

El informe cita la corrida 2.

## Ejemplo de pedido y respuesta (corrida 2)

```json
{
  "request": {
    "city": "asuncion",
    "neighborhood": "Barrio San Francisco",
    "property_type": "casa",
    "built_area_m2": 120.0,
    "land_area_m2": null,
    "bedrooms": null,
    "bathrooms": null,
    "garages": null,
    "has_pool": null,
    "has_quincho": null,
    "is_new": null,
    "in_gated_community": null,
    "has_elevator": null,
    "street_surface": null
  },
  "response": {
    "label": "precio de oferta estimado",
    "usd_per_m2": 813.5301683378462,
    "p_low": 586.2704068424056,
    "p_high": 1231.4787642902309,
    "total_usd": 97623.62020054155,
    "total_low": 70352.44882108866,
    "total_high": 147777.4517148277,
    "coverage_nominal": 0.8,
    "warnings": [
      {
        "code": "pocos_datos",
        "message": "Hay pocos grupos de entrenamiento para este segmento."
      }
    ],
    "model_version": "2026-11-06-v3-lightgbm-cqr",
    "contract_version": "0.1.1"
  }
}
```

## Docker Compose

`docker compose up --build` en Windows 11 con Docker Desktop (Brian, 09/11/2026 00:46): se construyeron
las imágenes `api` y `web`, la API quedó *healthy* y `just smoke http://localhost:8000 --origin
http://localhost:8080` dio `RESULTADO: OK` (`/live`, `/health` con `2026-11-06-v3-lightgbm-cqr`,
`/barrios`, `/predict` con contrato válido y CORS para GET y el preflight de POST).

La prueba de humo de producción está en [smoke-v3-2026-11-08.md](smoke-v3-2026-11-08.md).
