# Abrir y probar O1 en Windows

## Visual Studio Code

Abrir la carpeta completa `avm-gran-asuncion` mediante Archivo → Abrir carpeta.
En el explorador aparecen los archivos que se editaron. Los cambios guardados por Codex
se ven en esa misma carpeta; no hay que copiarlos desde el chat.

Archivos para revisar:

- `docs/geo.md`: metodología, cobertura y casos pendientes.
- `src/avm/geo/gazetteer.py`: nombres, alias y puntos representativos.
- `src/avm/geo/osm.py`: consultas y caché.
- `scripts/build_geo.py`: ejecución completa.
- `data/reference/gazetteer.csv`: resultado local; no se sube a GitHub.
- `data/reference/geo_issues.json`: casos que requieren revisión.

## Prueba local

Abrir Terminal → Nueva terminal, con PowerShell, desde la raíz del repositorio.
Estos comandos usan el entorno local ya instalado en esta computadora:

```powershell
.\.venv\Scripts\python -m pytest tests/geo -q --basetemp ..\work\pytest-manual
.\.venv\Scripts\python scripts/build_geo.py --snapshot data/raw/osm/2026-11-03
Import-Csv data/reference/gazetteer.csv | Format-Table city,neighborhood,centroid_method
Get-Content data/reference/geo_issues.json
```

La segunda orden reutiliza las respuestas guardadas. En otra computadora sin ese snapshot
consulta OSM: leer antes las políticas y los límites de `docs/geo.md`.
No ejecutar dos extracciones simultáneas.

Para filtrar una ciudad:

```powershell
Import-Csv data/reference/gazetteer.csv | Where-Object city -eq luque | Format-Table
```

Esto todavía no es la calculadora web: O1 genera los insumos geográficos.
La web y la API dependen de entregas posteriores de modelado e integración.

## GitHub

La rama de trabajo es `f6-geo-base`. El código, las pruebas y la documentación se versionan;
los snapshots y el CSV permanecen fuera de Git. Publicar la rama no implica fusionarla con
`main`: los cambios se revisan mediante un pull request antes de integrarlos.
