import type { City, ModelInfo, PredictionRequest, PredictionResponse } from "./types";

const BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function messageFor(status: number): string {
  switch (status) {
    case 422:
      return "Revisá los datos ingresados: alguno no es válido.";
    case 429:
      return "Hiciste muchos pedidos seguidos. Esperá un momento y volvé a intentar.";
    case 503:
      return "El servicio de estimación no está disponible por ahora.";
    default:
      return "No se pudo calcular la estimación. Probá de nuevo más tarde.";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (BASE === "") {
    throw new ApiError(0, "Falta configurar VITE_API_URL (ver web/.env.example).");
  }
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError(0, "No se pudo conectar con el servicio de estimación.");
  }
  if (!response.ok) throw new ApiError(response.status, messageFor(response.status));
  return (await response.json()) as T;
}

export function getNeighborhoods(city: City): Promise<string[]> {
  return request<string[]>(`/barrios?ciudad=${encodeURIComponent(city)}`);
}

export function getModelInfo(): Promise<ModelInfo> {
  return request<ModelInfo>("/model-info");
}

export function predict(body: PredictionRequest): Promise<PredictionResponse> {
  return request<PredictionResponse>("/predict", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
