// Lógica pura de la web (sin React ni red), cubierta por lib.test.ts.

import type {
  City,
  ModelInfo,
  PredictionRequest,
  PropertyType,
  StreetSurface,
  Tri,
  WarningCode,
} from "./types";

export interface FormState {
  city: City | "";
  neighborhood: string; // "" = no sé / otro
  propertyType: PropertyType | "";
  builtArea: string;
  landArea: string;
  bedrooms: string;
  bathrooms: string;
  hasPool: Tri;
  hasQuincho: Tri;
  isNew: Tri;
  inGatedCommunity: Tri;
  hasElevator: Tri;
  streetSurface: StreetSurface | "";
}

export const EMPTY_FORM: FormState = {
  city: "",
  neighborhood: "",
  propertyType: "",
  builtArea: "",
  landArea: "",
  bedrooms: "",
  bathrooms: "",
  hasPool: "nose",
  hasQuincho: "nose",
  isNew: "nose",
  inGatedCommunity: "nose",
  hasElevator: "nose",
  streetSurface: "",
};

export function triToBool(value: Tri): boolean | null {
  if (value === "si") return true;
  if (value === "no") return false;
  return null;
}

/** Número opcional: vacío o inválido → null. Acepta coma decimal. */
export function parseOptionalNumber(text: string): number | null {
  const clean = text.trim().replace(",", ".");
  if (clean === "") return null;
  const value = Number(clean);
  return Number.isFinite(value) ? value : null;
}

function parseCount(text: string): number | null {
  const value = parseOptionalNumber(text);
  return value !== null && Number.isInteger(value) && value >= 0 ? value : null;
}

export type BuildResult =
  | { ok: true; request: PredictionRequest }
  | { ok: false; error: string };

/** Arma el PredictionRequest. `garages` y lo que el usuario no cargó viajan como null. */
export function buildRequest(form: FormState): BuildResult {
  if (form.city === "") return { ok: false, error: "Elegí una ciudad." };
  if (form.propertyType === "") return { ok: false, error: "Elegí el tipo de inmueble." };
  const area = parseOptionalNumber(form.builtArea);
  if (area === null || area <= 0) {
    return { ok: false, error: "Indicá los m² construidos (un número mayor que cero)." };
  }
  const land = parseOptionalNumber(form.landArea);
  if (land !== null && land <= 0) {
    return { ok: false, error: "El terreno, si lo cargás, tiene que ser mayor que cero." };
  }
  return {
    ok: true,
    request: {
      city: form.city,
      neighborhood: form.neighborhood === "" ? null : form.neighborhood,
      property_type: form.propertyType,
      built_area_m2: area,
      land_area_m2: land,
      bedrooms: parseCount(form.bedrooms),
      bathrooms: parseCount(form.bathrooms),
      garages: null,
      has_pool: triToBool(form.hasPool),
      has_quincho: triToBool(form.hasQuincho),
      is_new: triToBool(form.isNew),
      in_gated_community: triToBool(form.inGatedCommunity),
      has_elevator: triToBool(form.hasElevator),
      street_surface: form.streetSurface === "" ? null : form.streetSurface,
    },
  };
}

/** Número de coberturas en palabras: 0,8 → "en 8 de cada 10 casos". null si no hay dato válido. */
export function coverageInWords(coverage: unknown): string | null {
  if (typeof coverage !== "number" || !(coverage > 0 && coverage < 1)) return null;
  const tenths = Math.round(coverage * 10);
  if (Math.abs(coverage * 10 - tenths) < 1e-9 && tenths >= 1 && tenths <= 9) {
    return `en ${tenths} de cada 10 casos`;
  }
  const hundredths = Math.round(coverage * 100);
  if (hundredths >= 1 && hundredths <= 99) return `en ${hundredths} de cada 100 casos`;
  return null;
}

/** Posición (0–100) del estimado dentro de la barra que va de `low` a `high`. */
export function markerPosition(low: number, estimate: number, high: number): number {
  if (!(high > low)) return 50;
  const pct = ((estimate - low) / (high - low)) * 100;
  return Math.min(100, Math.max(0, pct));
}

export function formatUsd(value: number): string {
  return `US$ ${new Intl.NumberFormat("es-PY", { maximumFractionDigits: 0 }).format(value)}`;
}

export function formatPercent(fraction: number): string {
  return `${new Intl.NumberFormat("es-PY", { maximumFractionDigits: 1 }).format(fraction * 100)} %`;
}

export function isTestModel(info: ModelInfo | null): boolean {
  return info?.is_test_model === true;
}

/** Cobertura nominal: primero la de /model-info; si no está, la de la respuesta (también del modelo). */
export function nominalCoverage(info: ModelInfo | null, fromResponse?: number): number | null {
  const fromInfo = info?.coverage_nominal;
  if (typeof fromInfo === "number" && fromInfo > 0 && fromInfo < 1) return fromInfo;
  return typeof fromResponse === "number" ? fromResponse : null;
}

const METRIC_LABELS: Record<string, { label: string; kind: "fraction" | "count" }> = {
  mdape: { label: "Error porcentual absoluto mediano (MdAPE)", kind: "fraction" },
  pe10: { label: "Predicciones dentro de ±10 % del precio publicado", kind: "fraction" },
  pe20: { label: "Predicciones dentro de ±20 % del precio publicado", kind: "fraction" },
  interval_coverage: { label: "Cobertura empírica del intervalo", kind: "fraction" },
  mean_interval_width: {
    label: "Ancho medio del intervalo (relativo a la estimación)",
    kind: "fraction",
  },
  n_test: { label: "Avisos de prueba (test)", kind: "count" },
};

export interface MetricRow {
  label: string;
  value: string;
}

/** Filas de `metadata.metrics`. Claves conocidas con etiqueta en español; las otras, crudas. */
export function metricRows(info: ModelInfo | null): MetricRow[] {
  const metrics = info?.metrics;
  if (typeof metrics !== "object" || metrics === null || Array.isArray(metrics)) return [];
  const rows: MetricRow[] = [];
  for (const [key, raw] of Object.entries(metrics as Record<string, unknown>)) {
    if (typeof raw !== "number" || !Number.isFinite(raw)) continue;
    const known = METRIC_LABELS[key];
    if (!known) {
      rows.push({ label: key, value: String(raw) });
    } else if (known.kind === "count") {
      rows.push({ label: known.label, value: new Intl.NumberFormat("es-PY").format(raw) });
    } else {
      rows.push({ label: known.label, value: formatPercent(raw) });
    }
  }
  return rows;
}

/** Texto para el usuario de cada warning. El mensaje del servidor queda como respaldo. */
export function warningText(code: WarningCode | string, serverMessage: string): string {
  switch (code) {
    case "barrio_desconocido":
      return "No reconocemos ese barrio. Revisá el nombre o elegí «No sé / otro».";
    case "fallback_ciudad":
      return "Sin un barrio reconocido, la estimación usa datos de toda la ciudad: es menos precisa y el rango es más amplio.";
    case "pocos_datos":
      return "Hay pocos avisos de referencia para esta combinación. Tomá el rango con más cautela.";
    default:
      return serverMessage;
  }
}

export function metaString(info: ModelInfo | null, key: string): string | null {
  const value = info?.[key];
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

export function metaNumber(info: ModelInfo | null, key: string): number | null {
  const value = info?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
