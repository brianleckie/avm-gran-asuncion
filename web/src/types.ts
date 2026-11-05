// Espejo escrito a mano de los schemas de src/avm/contract/prediction.py y enums.py.
// Si el contrato cambia, hay que actualizar este archivo.

export type City = "asuncion" | "luque" | "san_lorenzo" | "fernando_de_la_mora";
export type PropertyType = "casa" | "departamento" | "duplex";
export type StreetSurface = "pavimento" | "empedrado" | "tierra";
export type WarningCode = "barrio_desconocido" | "fallback_ciudad" | "pocos_datos";

export interface PredictionRequest {
  city: City;
  neighborhood: string | null;
  property_type: PropertyType;
  built_area_m2: number;
  land_area_m2: number | null;
  bedrooms: number | null;
  bathrooms: number | null;
  garages: number | null;
  has_pool: boolean | null;
  has_quincho: boolean | null;
  is_new: boolean | null;
  in_gated_community: boolean | null;
  has_elevator: boolean | null;
  street_surface: StreetSurface | null;
}

export interface PredictionWarning {
  code: WarningCode;
  message: string;
}

export interface PredictionResponse {
  label: "precio de oferta estimado";
  usd_per_m2: number;
  p_low: number;
  p_high: number;
  total_usd: number;
  total_low: number;
  total_high: number;
  coverage_nominal: number;
  warnings: PredictionWarning[];
  model_version: string;
  contract_version: string;
}

/** Metadata de GET /model-info (docs/interfaces.md, I4). Todo es opcional salvo lo que se verifique. */
export type ModelInfo = Record<string, unknown>;

/** Respuesta de un campo tri-estado del formulario: "no sé" se envía como null. */
export type Tri = "si" | "no" | "nose";

export const CITY_LABELS: Record<City, string> = {
  asuncion: "Asunción",
  luque: "Luque",
  san_lorenzo: "San Lorenzo",
  fernando_de_la_mora: "Fernando de la Mora",
};

export const PROPERTY_LABELS: Record<PropertyType, string> = {
  casa: "Casa",
  departamento: "Departamento",
  duplex: "Dúplex",
};

export const STREET_LABELS: Record<StreetSurface, string> = {
  pavimento: "Pavimento",
  empedrado: "Empedrado",
  tierra: "Tierra",
};
