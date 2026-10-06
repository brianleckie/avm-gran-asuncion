# ADR-007: Privacidad de la caché y retención de datos
- Estado: propuesto (pendiente revisión de Oscar Arce)
- Autores: Brian Leckie

## Contexto
CLAUDE.md prohíbe persistir teléfonos, nombres de agentes y emails, y prohíbe escribir HTML crudo con datos de anunciantes en la caché. Los ToS de Clasipar no mencionan el acceso automatizado, pero prohíben reproducir el contenido de los avisos (`docs/sources.md` §2.2). Hay tres lugares donde el contenido de los avisos queda en disco:
- `data/raw/<fecha>/<fuente>/`: la caché de HTML, el `requests.jsonl` y el `manifest.json` de `BaseScraper` (F3.2).
- `data/interim/<fecha>/<fuente>/`: los `RawListing` (`raw_listings.jsonl`) y el manifest del crawler (F3.3).
- `data/processed/`: lo que derive el pipeline (F4 en adelante).

El reconocimiento de F3.1 guardó el HTML tal como llegaba, con 110 links `/empresa/<nombre>` y los bloques de anunciante. Se borró y desde entonces la caché se escribe sanitizada (`docs/sources.md` §8.3).

## Decisión
1. **La caché se escribe sanitizada (D1).** Nunca se persiste HTML crudo. `sanitize_html` elimina los bloques de anunciante que indica cada fuente (nombre, foto o logo, perfil, formulario de contacto), las imágenes de logos y de fotos de perfil, los `<script>` (salvo el JSON-LD), reemplaza teléfonos, emails y links de WhatsApp, y los links a sitios de terceros por `[URL]`. Si después queda un rastro (`/empresa/`, `/corporate/`, `/users/` o un contacto) falla cerrado: la página no se escribe.
2. **El parser sanitiza antes de construir el `RawListing` (D3)** y el contrato rechaza el objeto si algún texto trae un teléfono, un email o un link de WhatsApp (ADR-006, punto 10). El nombre del anunciante nunca se extrae.
3. **Riesgo residual, aceptado y abierto en F3.5:**
   - **Nombres de personas en texto libre** (título o descripción): no se detectan con un regex y no se pueden quitar sin tocar el contenido.
   - **Dominios sin esquema** ("sitio.com.py"): `scrub_urls` solo reconoce links con esquema o `www.`.
   - Falsos negativos del regex de teléfonos (por ejemplo "981 123 456", sin el `0`).
4. **Mitigaciones del riesgo residual:**
   - `data/` nunca se versiona (`.gitignore`) y el hook `check-added-large-files` (500 KB) frena los volcados accidentales.
   - Acceso solo local: los datos viven en las máquinas de los autores. No van a CI, a un servicio de almacenamiento compartido ni a Railway o Vercel.
   - Los reportes y documentos del repositorio publican **solo agregados** (conteos, porcentajes, patrones de formato sin texto de los avisos). No reproducen títulos, descripciones ni fotos (ToS de Clasipar). Los fixtures de `tests/fixtures/` son la excepción ya existente: recortados y sanitizados, y pendientes de revisión con el tutor (`docs/sources.md` §4).
5. **Política de retención:**
   - `data/raw`, `data/interim` y `data/processed` se borran al cerrar el proyecto.
   - `models/` se conserva: solo contiene parámetros del modelo y sus metadatos, sin contenido de avisos.
   - Los datos se conservan mientras el proyecto está activo, porque cada snapshot es la base de reproducibilidad (ROADMAP, principio 6).

## Consecuencias
- Un nombre de persona escrito en una descripción puede estar en `data/raw` y `data/interim` hasta el borrado, aunque nunca en el repositorio ni en un reporte. F3.5 sigue abierta y el reporte del piloto (F3.3) cuenta cuántas descripciones tienen indicios (sin mostrar ninguna).
- Como la caché está sanitizada, no se puede volver a parsear con un parser nuevo ningún dato que el sanitizador haya eliminado. La caché se lee tal como se escribió, sin volver a sanitizar (`base.py`).
- Los reportes agregados limitan lo que se puede mostrar en la defensa: ejemplos de formato con los números reemplazados, nunca texto de avisos.
- El borrado al cerrar el proyecto implica que los resultados finales (F10, F15) tienen que estar en el repositorio como agregados antes de borrar.

## Alternativas descartadas
- **Guardar el HTML crudo y sanitizarlo después.** Persistiría datos de anunciantes mientras tanto, lo que CLAUDE.md prohíbe, y el borrado posterior no deja de ser una copia en disco.
- **No cachear.** Obligaría a pedir de nuevo cada página en cada corrida y rompería el principio de cortesía con la fuente (cada request cuenta contra el presupuesto y el rate limit).
- **Detectar nombres de personas con un regex o un modelo de lenguaje en el sanitizador.** Genera falsos positivos y falsos negativos que se esconderían detrás de una garantía aparente. Se prefiere mitigar con acceso local, retención limitada y agregados, y medir el problema (F3.5).
- **Cifrar `data/` en disco.** No cambia quién tiene acceso en las máquinas de los autores y agrega complejidad sin reducir el riesgo que importa (el repositorio y los reportes).

## Pregunta abierta para Oscar
- ¿Qué momento exacto es "al cerrar el proyecto" (después de la entrega final o de la defensa)? Y ¿quién hace el borrado y dónde queda registrado (ROADMAP u otro archivo)?
