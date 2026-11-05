import { describe, expect, it } from "vitest";
import {
  EMPTY_FORM,
  buildRequest,
  coverageInWords,
  isTestModel,
  markerPosition,
  metricRows,
  nominalCoverage,
  parseOptionalNumber,
  triToBool,
  warningText,
} from "./lib";

describe("coverageInWords", () => {
  it("usa 'de cada 10' cuando la cobertura es de décimas", () => {
    expect(coverageInWords(0.8)).toBe("en 8 de cada 10 casos");
    expect(coverageInWords(0.9)).toBe("en 9 de cada 10 casos");
    expect(coverageInWords(0.1)).toBe("en 1 de cada 10 casos");
  });
  it("usa 'de cada 100' si no", () => {
    expect(coverageInWords(0.85)).toBe("en 85 de cada 100 casos");
  });
  it("no inventa nada con valores inválidos", () => {
    expect(coverageInWords(undefined)).toBeNull();
    expect(coverageInWords(0)).toBeNull();
    expect(coverageInWords(1)).toBeNull();
    expect(coverageInWords("0.8")).toBeNull();
  });
});

describe("markerPosition", () => {
  it("ubica el estimado dentro de la barra", () => {
    expect(markerPosition(800, 1000, 1200)).toBe(50);
    expect(markerPosition(800, 900, 1200)).toBeCloseTo(25);
  });
  it("acota y tolera intervalos degenerados", () => {
    expect(markerPosition(800, 700, 1200)).toBe(0);
    expect(markerPosition(800, 2000, 1200)).toBe(100);
    expect(markerPosition(1000, 1000, 1000)).toBe(50);
  });
});

describe("parseOptionalNumber / triToBool", () => {
  it("vacío o inválido es null; acepta coma", () => {
    expect(parseOptionalNumber("")).toBeNull();
    expect(parseOptionalNumber("abc")).toBeNull();
    expect(parseOptionalNumber("12,5")).toBe(12.5);
  });
  it("'no sé' es null", () => {
    expect(triToBool("si")).toBe(true);
    expect(triToBool("no")).toBe(false);
    expect(triToBool("nose")).toBeNull();
  });
});

describe("buildRequest", () => {
  const base = { ...EMPTY_FORM, city: "luque" as const, propertyType: "casa" as const };

  it("exige ciudad, tipo y m² construidos", () => {
    expect(buildRequest(EMPTY_FORM).ok).toBe(false);
    expect(buildRequest({ ...base, builtArea: "" }).ok).toBe(false);
    expect(buildRequest({ ...base, builtArea: "0" }).ok).toBe(false);
    expect(buildRequest({ ...EMPTY_FORM, city: "luque", builtArea: "10" }).ok).toBe(false);
  });

  it("manda null en lo que no se cargó y en cocheras", () => {
    const result = buildRequest({ ...base, builtArea: "120" });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.request).toEqual({
      city: "luque",
      neighborhood: null,
      property_type: "casa",
      built_area_m2: 120,
      land_area_m2: null,
      bedrooms: null,
      bathrooms: null,
      garages: null,
      has_pool: null,
      has_quincho: null,
      is_new: null,
      in_gated_community: null,
      has_elevator: null,
      street_surface: null,
    });
  });

  it("incluye los detalles cargados", () => {
    const result = buildRequest({
      ...base,
      neighborhood: "Centro",
      builtArea: "90,5",
      landArea: "300",
      bedrooms: "3",
      bathrooms: "2",
      hasPool: "si",
      hasElevator: "no",
      streetSurface: "pavimento",
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.request).toMatchObject({
      neighborhood: "Centro",
      built_area_m2: 90.5,
      land_area_m2: 300,
      bedrooms: 3,
      bathrooms: 2,
      has_pool: true,
      has_elevator: false,
      street_surface: "pavimento",
    });
  });

  it("rechaza terreno no positivo", () => {
    expect(buildRequest({ ...base, builtArea: "50", landArea: "-1" }).ok).toBe(false);
  });
});

describe("metadata", () => {
  it("detecta el modelo de prueba solo si es exactamente true", () => {
    expect(isTestModel({ is_test_model: true })).toBe(true);
    expect(isTestModel({ is_test_model: "true" })).toBe(false);
    expect(isTestModel({})).toBe(false);
    expect(isTestModel(null)).toBe(false);
  });

  it("la cobertura sale de /model-info y, si falta, de la respuesta", () => {
    expect(nominalCoverage({ coverage_nominal: 0.9 }, 0.8)).toBe(0.9);
    expect(nominalCoverage({}, 0.8)).toBe(0.8);
    expect(nominalCoverage(null)).toBeNull();
  });

  it("muestra métricas con etiqueta y claves desconocidas crudas", () => {
    const rows = metricRows({
      metrics: { mdape: 0.12, n_test: 1500, rmse_log: 0.25, otro: "x" },
    });
    expect(rows.map((r) => r.label)).toEqual([
      "Error porcentual absoluto mediano (MdAPE)",
      "Avisos de prueba (test)",
      "rmse_log",
    ]);
    expect(rows[0].value).toContain("12");
    expect(metricRows({})).toEqual([]);
    expect(metricRows({ metrics: [1] })).toEqual([]);
  });
});

describe("warningText", () => {
  it("traduce los códigos conocidos y usa el mensaje del servidor para los demás", () => {
    expect(warningText("fallback_ciudad", "x")).toContain("ciudad");
    expect(warningText("pocos_datos", "x")).toContain("pocos avisos");
    expect(warningText("nuevo_codigo", "mensaje del servidor")).toBe("mensaje del servidor");
  });
});
