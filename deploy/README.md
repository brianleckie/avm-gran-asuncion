# deploy/

Lo que viaja a producción (ver [ADR-008](../docs/adr/008-modelo-en-produccion.md)).

`deploy/model/` es el artefacto del modelo (el contenido de `models/<version>/`, sin la subcarpeta de versión). **Todavía no existe**: mientras no haya modelo, la API de Railway responde `/live` 200 y `/health` 503.

Para publicar el modelo:

```powershell
Copy-Item -Recurse models/<version> deploy/model
Set-Content deploy/model/ATTRIBUTION.md "© OpenStreetMap contributors"   # si Oscar no la incluyó
uv run python scripts/check_deploy_model.py
git add deploy/model; git commit -m "F13.x: publica el modelo <version>"; git push
```

Nunca va acá nada de `data/` ni filas de avisos: `pytest` falla si `deploy/model/` tiene algo con forma de aviso.
