# Deploy (F13): Railway (API) y Vercel (web)

Arquitectura: la API (`Dockerfile` + `railway.toml`) corre en Railway; la web (`web/`) en Vercel. El modelo llega como `deploy/model/` versionado en git ([ADR-008](adr/008-modelo-en-produccion.md)). **Mientras no exista `deploy/model/`, la API está viva (`/live` 200) pero no lista (`/health` 503)**, y la web muestra "servicio no disponible": es el estado esperado.

| Endpoint | Para qué | Sin modelo |
|---|---|---|
| `GET /live` | Liveness; healthcheck de Railway | 200 |
| `GET /health` | Readiness | 503 |
| `/predict`, `/barrios`, `/model-info` | Uso real | 503 |

## Variables de la API (Railway → servicio → Variables)

| Variable | Valor | Nota |
|---|---|---|
| `AVM_ENV` | `production` | También es el default de la imagen. Prohíbe el predictor `fake` y los modelos de prueba |
| `AVM_PREDICTOR` | `model` | |
| `AVM_MODEL_DIR` | `deploy/model` | Relativa al directorio de trabajo de la imagen (`/app`) |
| `AVM_CORS_ORIGIN` | `https://<dominio-de-vercel>` | Un solo origen, con `https://` y sin barra final |
| `AVM_TRUST_PROXY` | `1` | El rate limit usa el **último** valor de `X-Forwarded-For` |
| `AVM_RATE_LIMIT_PER_MIN` | (opcional) | Default 30 por IP en `POST /predict` |

No definir `PORT`: lo inyecta Railway.

## Paso a paso (el orden importa)

Necesitás la URL de Railway para Vercel y la de Vercel para CORS: **Railway → Vercel → Railway**. Ambos servicios piden iniciar sesión (con GitHub) y autorizar el acceso al repositorio `brianleckie/avm-gran-asuncion`.

1. **Railway: crear el servicio.** *New Project → Deploy from GitHub repo* → elegir el repositorio y la rama (`main`, o `f13-deploy` para probar antes del merge). Railway detecta el `Dockerfile` y lee `railway.toml` (builder Dockerfile, healthcheck `/live`).
2. **Railway: variables.** En el servicio → *Variables*: `AVM_ENV`, `AVM_PREDICTOR`, `AVM_MODEL_DIR`, `AVM_TRUST_PROXY` de la tabla. Todavía no `AVM_CORS_ORIGIN`.
3. **Railway: dominio.** *Settings → Networking → Generate Domain* → copiar `https://….up.railway.app`.
4. **Probar la API.** Cuando el deploy esté en verde:
   ```powershell
   just smoke https://<url-railway>
   ```
   Esperado sin modelo: `/live` OK, `/health` 503 informado ("sin modelo todavía"), `/barrios` 503 consistente, `RESULTADO: OK`.
5. **Vercel: crear el proyecto.** *Add New → Project* → importar el mismo repositorio → **Root Directory `web`** → Framework Preset *Vite* (Build Command `npm run build`, Output Directory `dist`).
6. **Vercel: variable.** *Environment Variables* → `VITE_API_URL=https://<url-railway>` (sin barra final), en *Production*. Se incrusta **al compilar**: si cambia la URL de Railway, hay que redeployar la web.
7. **Vercel: Node.** *Settings → Build and Deployment → Node.js Version*: 22.x (Vite 8 exige Node ≥ 20.19 o ≥ 22.12). *Deploy* y copiar el dominio de producción (`https://….vercel.app`).
8. **Railway otra vez: CORS.** Agregar `AVM_CORS_ORIGIN=https://<dominio-vercel>` → Railway redeploya. Verificar:
   ```powershell
   just smoke https://<url-railway> --origin https://<dominio-vercel>
   ```
   Tiene que mostrar "GET permitido" y "preflight de POST /predict permitido".
9. **Abrir la web.** Debe cargar (sin modelo, con el aviso de servicio no disponible). Solo el dominio de producción funciona contra la API: los *preview deployments* de Vercel tienen otra URL y CORS admite un único origen.

## Chequeo manual del rate limit detrás del proxy

`AVM_TRUST_PROXY=1` toma el último valor de `X-Forwarded-For`, que es el que agrega el proxy de Railway. No verifiqué cómo trata Railway ese header (la documentación de config as code no lo cubre). Para comprobarlo después del deploy:

1. Mandar `POST /predict` repetidos (más de `AVM_RATE_LIMIT_PER_MIN` por minuto) con y sin un `X-Forwarded-For: 1.2.3.4` inventado:
   ```powershell
   1..40 | ForEach-Object { curl.exe -s -o NUL -w "%{http_code} " -X POST https://<url-railway>/predict -H "Content-Type: application/json" -H "X-Forwarded-For: 1.2.3.$_" -d '{\"city\":\"luque\",\"property_type\":\"casa\",\"built_area_m2\":100}' }
   ```
2. Si aparecen 429 aunque cambie el `X-Forwarded-For` inventado, la API lee el valor que agrega el proxy (correcto). Si nunca aparecen 429, el proxy no agrega la IP al final: dejar `AVM_TRUST_PROXY` sin definir (se usa la IP de la conexión) y avisar.

Con `AVM_TRUST_PROXY` apagado, el header se ignora. No activarlo si la API es alcanzable sin pasar por el proxy. El límite es en memoria y por proceso (un solo worker, una réplica).

## Cuando llegue el modelo de Oscar

1. `Predictor` en `main` (`avm.model.predictor`) y sus dependencias en `pyproject.toml` + `uv.lock` (`uv add`): la imagen instala solo lo que está en `uv.lock` (`uv sync --frozen --no-dev`).
2. Copiar `models/<version>/` a `deploy/model/` (ver [deploy/README.md](../deploy/README.md)), correr `uv run python scripts/check_deploy_model.py`, commit y push. Railway redeploya.
3. `just smoke https://<url-railway> --origin https://<dominio-vercel>`: ahora `/health` 200 y el `/predict` de ejemplo se valida contra el contrato (falla si la API sirve un modelo de prueba).

## Docker Compose (local)

`docker-compose.yml` (raíz) levanta todo en la máquina, sin Railway ni Vercel:

```powershell
docker compose up --build
```

| Servicio | Imagen | URL | Notas |
|---|---|---|---|
| `api` | `Dockerfile` de la raíz | http://localhost:8000 | `AVM_ENV=production`, `AVM_PREDICTOR=model`, `AVM_MODEL_DIR=deploy/model`, `AVM_CORS_ORIGIN=http://localhost:8080`. Healthcheck sobre `/health` (listo solo con modelo cargado) |
| `web` | `web/Dockerfile` (multi-stage) | http://localhost:8080 | Build con Node 22 y `VITE_API_URL=http://localhost:8000`; se sirve con nginx (`web/nginx.conf`). Arranca cuando la API está sana |

- `VITE_API_URL` se incrusta al compilar y la usa el **navegador**, por eso es `localhost` y no el nombre del servicio. Si cambiás el puerto de la API o de la web, cambiá también `AVM_CORS_ORIGIN` y `VITE_API_URL` en el compose y reconstruí (`--build`).
- Smoke test: `just smoke http://localhost:8000 --origin http://localhost:8080`.
- Apagar: `docker compose down`.
- El modelo sale de `deploy/model/`, que se copia a la imagen: tras cambiarlo hay que reconstruir.
- `AVM_TRUST_PROXY` no se define: no hay proxy delante de la API y el rate limit usa la IP de la conexión.

**Estado de verificación:** la sintaxis del compose se validó con `docker compose config`. Las imágenes **no se construyeron** al escribir esto porque Docker Desktop estaba apagado. Sí se corrió la API (`uvicorn`) con las mismas variables de entorno y `just smoke http://localhost:8000 --origin http://localhost:8080` dio `RESULTADO: OK` (`/health` 200 con `model_version=2026-11-06-v3-lightgbm-cqr`, `/predict` válido contra el contrato, CORS permitido). Falta correr `docker compose up --build` con Docker encendido.

## Local

- API: `just serve` (ver README). Healthcheck local: `curl http://127.0.0.1:8000/live`.
- Imagen: `docker build -t avm-api .` y `docker run --rm -p 8080:8080 -e PORT=8080 -e AVM_PREDICTOR=model -e AVM_MODEL_DIR=deploy/model avm-api`, luego `just smoke http://127.0.0.1:8080`. (La imagen no se pudo construir en esta sesión porque Docker no estaba activo: se verificó el mismo arranque con `uv sync --frozen --no-dev` + `uvicorn`.)
