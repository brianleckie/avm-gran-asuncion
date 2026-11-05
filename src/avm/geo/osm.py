"""Cliente OSM secuencial, con caché auditable y presupuestos duros."""

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

USER_AGENT = (
    "AVM-GranAsuncion-Academic/0.1 "
    "(proyecto universitario; contacto: https://github.com/brianleckie)"
)
OVERPASS = "https://overpass-api.de/api/interpreter"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
CITY_NAMES = {
    "asuncion": "Asunción",
    "luque": "Luque",
    "san_lorenzo": "San Lorenzo",
    "fernando_de_la_mora": "Fernando de la Mora",
}
CITY_QUERY = """[out:json][timeout:120];
area["ISO3166-1"="PY"][admin_level=2]->.py;
rel(area.py)[boundary=administrative][admin_level=8]
[name~"^(Asunción|Luque|San Lorenzo|Fernando de la Mora)$"];out geom;"""


class OSMClient:
    """Una instancia, un hilo; sin reintentos automáticos ni consultas ocultas."""

    def __init__(self, root: Path, *, transport=None, overpass=OVERPASS, nominatim=NOMINATIM):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = root / "manifest.json"
        self.manifest = (
            json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if self.manifest_path.exists()
            else {"requests": [], "attribution": "© OpenStreetMap contributors (ODbL)"}
        )
        self.http = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=180, transport=transport
        )
        self.overpass_url, self.nominatim_url = overpass, nominatim
        self.last_request = 0.0

    def close(self):
        self.http.close()

    def _request(self, service, payload):
        endpoint = self.overpass_url if service == "overpass" else self.nominatim_url
        key = hashlib.sha256(json.dumps([endpoint, payload], sort_keys=True).encode()).hexdigest()
        target = self.root / f"{service}-{key}.json"
        if target.exists():
            data = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("remark"):
                raise ValueError(f"Respuesta Overpass incompleta: {data['remark']}")
            return data
        used = sum(r["service"] == service for r in self.manifest["requests"])
        if used >= (199 if service == "nominatim" else 12):
            raise RuntimeError(f"Presupuesto agotado: {service}; detener y revisar")
        time.sleep(max(0, 2 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        response = (
            self.http.post(endpoint, data=payload)
            if service == "overpass"
            else self.http.get(endpoint, params=payload)
        )
        raw = self.root / f"{service}-{key}-attempt-{used + 1}.response"
        raw.write_bytes(response.content)
        self.manifest["requests"].append(
            {
                "service": service,
                "endpoint": endpoint,
                "payload": payload,
                "date": datetime.now(UTC).isoformat(),
                "status": response.status_code,
                "sha256": hashlib.sha256(response.content).hexdigest(),
                "response": raw.name,
            }
        )
        self.manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("remark"):
            raise ValueError(f"Respuesta Overpass incompleta: {data['remark']}")
        target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def overpass(self, query):
        return self._request("overpass", {"data": query})

    def geocode(self, name, city):
        return self._request(
            "nominatim",
            {
                "q": f"{name}, {CITY_NAMES[city]}, Paraguay",
                "format": "jsonv2",
                "countrycodes": "py",
                "limit": 5,
            },
        )


def neighborhood_query(relation_id):
    return f"""[out:json][timeout:120];rel({relation_id});map_to_area->.city;
    (nwr(area.city)[place~"^(neighbourhood|suburb|quarter)$"];
    rel(area.city)[boundary=administrative][admin_level~"^(9|10|11)$"];);out geom;"""


def poi_query(bbox):
    box = ",".join(str(x) for x in bbox)
    return f"""[out:json][timeout:180];(
    way[highway~"^(primary|trunk)$"]({box});
    nwr[shop=mall]({box});nwr[amenity~"^(school|university|hospital)$"]({box});
    nwr[leisure=park]({box}););out geom;"""


def poi_categories(element):
    tags = element.get("tags", {})
    result = []
    if tags.get("highway") in {"primary", "trunk"}:
        result.append("road")
    for key, values in {
        "shop": {"mall"},
        "amenity": {"school", "university", "hospital"},
        "leisure": {"park"},
    }.items():
        if tags.get(key) in values:
            result.append(tags[key])
    return result
