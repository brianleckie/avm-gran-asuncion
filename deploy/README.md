# deploy/

Lo que viaja a producción (ver [ADR-008](../docs/adr/008-modelo-en-produccion.md)).

`deploy/model/` contiene el candidato `2026-11-06-v3-lightgbm-cqr`. Su publicación requiere el merge humano del PR y el redeploy de Railway. El estado del repositorio no prueba qué versión está sirviendo la API: verificar `/model-info` y ejecutar el smoke test después del merge.

La selección usa el menor MdAPE medio en validación de desarrollo, excluyendo el holdout final. Se eligió LightGBM con geo; la ablation completa no demuestra una mejora consistente por geo. Resultados, cobertura por tipo y límites en [el informe v3](../docs/results/2026-11-06-v3.md).

Para publicar el modelo:

```powershell
Copy-Item -Recurse models/<version> deploy/model
uv run python scripts/check_deploy_model.py
git add deploy/model; git commit -m "F13.x: publica el modelo <version>"; git push
```

Nunca va acá nada de `data/` ni filas de avisos: `pytest` falla si `deploy/model/` tiene algo con forma de aviso.

El candidato usa `model.bin` (JSON comprimido: boosters, vocabularios y agregados), `calibration.json`, `metadata.json`, gazetteer, features geo y atribución. No contiene filas de avisos. `Dockerfile` instala `libgomp1` para LightGBM.

Después del merge, confirmar `model_version=2026-11-06-v3-lightgbm-cqr` en `/model-info` y ejecutar:

```powershell
just smoke https://avm-gran-asuncion-production.up.railway.app --origin https://avm-gran-asuncion.vercel.app
```

El smoke realizado antes de este PR pasó contra `2026-11-05-baseline-real-v1`; no valida el despliegue del candidato v3. No se reemplaza el artefacto por resultados de test: el criterio de selección y la separación de conjuntos están registrados en `model/metadata.json`.
