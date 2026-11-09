"""Mide el tiempo de inferencia del modelo publicado y guarda un ejemplo de respuesta.

Uso: uv run python scripts/bench_inference.py --model-dir deploy/model --repeats 10

Corre en proceso (sin HTTP ni red): mide solo Predictor.predict. Imprime un JSON con la
latencia (mediana, p95, máximo), el tiempo de carga y un ejemplo de pedido y respuesta.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from pathlib import Path

from avm.contract import City, PredictionRequest
from avm.model.predictor import Predictor

AREAS = (60, 90, 120, 180, 250)
TYPES = ("casa", "departamento", "duplex")


def build_requests(predictor: Predictor) -> list[PredictionRequest]:
    """Una grilla fija de ciudad x tipo x superficie, con barrios del nomenclador."""
    requests = []
    for city in City:
        hoods = predictor.neighborhoods(city)
        for prop_type in TYPES:
            for i, area in enumerate(AREAS):
                requests.append(
                    PredictionRequest(
                        city=city,
                        neighborhood=hoods[i % len(hoods)] if hoods else None,
                        property_type=prop_type,
                        built_area_m2=area,
                    )
                )
    return requests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--repeats", required=True, type=int)
    args = parser.parse_args()

    start = time.perf_counter()
    predictor = Predictor.load(args.model_dir)
    load_s = time.perf_counter() - start

    requests = build_requests(predictor)
    for req in requests[:5]:
        predictor.predict(req)  # calentamiento

    latencies_ms = []
    for _ in range(args.repeats):
        for req in requests:
            t0 = time.perf_counter()
            predictor.predict(req)
            latencies_ms.append((time.perf_counter() - t0) * 1000)
    latencies_ms.sort()

    example = PredictionRequest(
        city=City("asuncion"),
        neighborhood=predictor.neighborhoods(City("asuncion"))[2],
        property_type="casa",
        built_area_m2=120,
    )
    result = {
        "model_version": predictor.metadata.get("model_version"),
        "n_predictions": len(latencies_ms),
        "load_s": round(load_s, 3),
        "p50_ms": round(statistics.median(latencies_ms), 2),
        "p95_ms": round(latencies_ms[int(0.95 * len(latencies_ms)) - 1], 2),
        "max_ms": round(latencies_ms[-1], 2),
        "machine": {
            "cpu": platform.processor() or platform.machine(),
            "n_cpu": os.cpu_count(),
            "python": platform.python_version(),
        },
        "example_request": json.loads(example.model_dump_json()),
        "example_response": json.loads(predictor.predict(example).model_dump_json()),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
