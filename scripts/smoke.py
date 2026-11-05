"""Smoke test post-deploy de la API (F13.3).

Uso: `uv run python scripts/smoke.py https://<api> [--origin https://<web>] [--allow-test-model]`
(o `just smoke <url>`).

Pasos:
1. `/live` debe dar 200 (se reintenta unas veces: el servicio puede estar arrancando).
2. `/health`: 200 = listo; 503 = sin modelo todavía (se informa, NO falla); otro código falla.
3. `/barrios?ciudad=asuncion`: con modelo, 200 y lista no vacía; sin modelo, se espera 503.
4. `/predict` de ejemplo, SOLO si `/health` dio 200: valida la respuesta contra el contrato y falla
   si viene marcada como modelo de prueba (salvo `--allow-test-model`, para `just serve` con fake).
5. Con `--origin`: verifica CORS (GET y preflight de POST /predict) para ese origen.

Sale con 0 si el servicio está sano o degradado de forma esperada (sin modelo); con 1 si falla algo.
"""

import argparse
import sys
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import ValidationError

from avm.contract import PredictionResponse

TEST_MODEL_HEADER = "X-AVM-Test-Model"
EXPECTED_LABEL = "precio de oferta estimado"
SAMPLE_CITY = "asuncion"
SAMPLE_AREA_M2 = 120


class Smoke:
    def __init__(self) -> None:
        self.failed = False

    def ok(self, message: str) -> None:
        print(f"  OK     {message}")

    def info(self, message: str) -> None:
        print(f"  INFO   {message}")

    def fail(self, message: str) -> None:
        self.failed = True
        print(f"  FALLA  {message}")


def _get(client: httpx.Client, path: str, **kwargs: Any) -> httpx.Response | None:
    try:
        return client.get(path, **kwargs)
    except httpx.HTTPError as exc:
        print(f"  ...    {path}: {type(exc).__name__}")
        return None


def check_live(
    client: httpx.Client, smoke: Smoke, retries: int, wait: float, sleep: Callable[[float], None]
) -> bool:
    print("/live")
    for attempt in range(1, retries + 1):
        response = _get(client, "/live")
        if response is not None and response.status_code == 200:
            smoke.ok("200: el proceso está arriba")
            return True
        if response is not None:
            print(f"  ...    HTTP {response.status_code}")
        if attempt < retries:
            sleep(wait)
    smoke.fail(f"/live no respondió 200 tras {retries} intentos")
    return False


def check_health(client: httpx.Client, smoke: Smoke) -> bool:
    """True si la API está lista (modelo cargado)."""
    print("/health")
    response = _get(client, "/health")
    if response is None:
        smoke.fail("sin respuesta")
        return False
    if response.status_code == 200:
        smoke.ok(f"200: listo (model_version={response.json().get('model_version')})")
        return True
    if response.status_code == 503:
        smoke.info("503: sin modelo todavía (esperado hasta que se publique deploy/model/)")
        return False
    smoke.fail(f"HTTP {response.status_code} (se esperaba 200 o 503)")
    return False


def check_barrios(client: httpx.Client, smoke: Smoke, ready: bool) -> list[str]:
    print("/barrios")
    response = _get(client, "/barrios", params={"ciudad": SAMPLE_CITY})
    if response is None:
        smoke.fail("sin respuesta")
        return []
    if not ready:
        if response.status_code == 503:
            smoke.info("503: consistente con /health (sin modelo)")
        else:
            smoke.fail(f"HTTP {response.status_code} (sin modelo se esperaba 503)")
        return []
    if response.status_code != 200:
        smoke.fail(f"HTTP {response.status_code} (se esperaba 200)")
        return []
    names = response.json()
    if not isinstance(names, list) or not names:
        smoke.fail(f"lista de barrios vacía o inválida para {SAMPLE_CITY}")
        return []
    smoke.ok(f"200: {len(names)} barrios en {SAMPLE_CITY}")
    return [str(name) for name in names]


def check_predict(
    client: httpx.Client, smoke: Smoke, neighborhoods: list[str], allow_test_model: bool
) -> None:
    print("/predict")
    body: dict[str, Any] = {
        "city": SAMPLE_CITY,
        "property_type": "casa",
        "built_area_m2": SAMPLE_AREA_M2,
    }
    if neighborhoods:
        body["neighborhood"] = neighborhoods[0]
    try:
        response = client.post("/predict", json=body)
    except httpx.HTTPError as exc:
        smoke.fail(type(exc).__name__)
        return
    if response.status_code != 200:
        smoke.fail(f"HTTP {response.status_code} (se esperaba 200)")
        return
    try:
        result = PredictionResponse.model_validate(response.json())
    except ValidationError:
        smoke.fail("la respuesta no cumple el contrato PredictionResponse")
        return
    if result.label != EXPECTED_LABEL:
        smoke.fail(f"label inesperado: {result.label!r}")
    elif not result.p_low <= result.usd_per_m2 <= result.p_high:
        smoke.fail("el intervalo no contiene la estimación")
    else:
        smoke.ok(f"200: contrato válido (model_version={result.model_version})")
    if response.headers.get(TEST_MODEL_HEADER) == "true":
        if allow_test_model:
            smoke.info("modelo de prueba (permitido con --allow-test-model)")
        else:
            smoke.fail("la API sirve un MODELO DE PRUEBA: no puede estar en producción")


def check_cors(client: httpx.Client, smoke: Smoke, origin: str) -> None:
    print(f"CORS para {origin}")
    simple = _get(client, "/live", headers={"Origin": origin})
    if simple is None or simple.headers.get("access-control-allow-origin") != origin:
        smoke.fail(
            "GET no devuelve access-control-allow-origin para ese origen (¿AVM_CORS_ORIGIN?)"
        )
    else:
        smoke.ok("GET permitido")
    try:
        preflight = client.options(
            "/predict",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    except httpx.HTTPError as exc:
        smoke.fail(f"preflight: {type(exc).__name__}")
        return
    allowed = preflight.headers.get("access-control-allow-origin") == origin
    if preflight.status_code == 200 and allowed:
        smoke.ok("preflight de POST /predict permitido")
    else:
        smoke.fail(f"preflight HTTP {preflight.status_code}: el navegador bloquearía POST /predict")


def run_smoke(
    client: httpx.Client,
    *,
    origin: str | None = None,
    allow_test_model: bool = False,
    live_retries: int = 5,
    retry_wait: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """True si todo pasó (o se degradó de forma esperada)."""
    smoke = Smoke()
    if not check_live(client, smoke, live_retries, retry_wait, sleep):
        return False
    ready = check_health(client, smoke)
    neighborhoods = check_barrios(client, smoke, ready)
    if ready:
        check_predict(client, smoke, neighborhoods, allow_test_model)
    else:
        print("/predict")
        smoke.info("omitido: /health no dio 200")
    if origin:
        check_cors(client, smoke, origin)
    return not smoke.failed


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Smoke test post-deploy de la API del AVM.")
    parser.add_argument("url", help="URL base de la API, p. ej. https://xxx.up.railway.app")
    parser.add_argument("--origin", help="origen de la web para verificar CORS")
    parser.add_argument(
        "--allow-test-model", action="store_true", help="aceptar el modelo de prueba"
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="segundos por pedido")
    args = parser.parse_args(argv)
    with httpx.Client(base_url=args.url.rstrip("/"), timeout=args.timeout) as client:
        passed = run_smoke(client, origin=args.origin, allow_test_model=args.allow_test_model)
    print("RESULTADO:", "OK" if passed else "FALLÓ")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
