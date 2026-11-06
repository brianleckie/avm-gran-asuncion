import { useEffect, useRef, useState } from "react";
import type { InfoState } from "./App";
import { ApiError, getNeighborhoods, predict } from "./api";
import { EMPTY_FORM, buildRequest, type FormState } from "./lib";
import { ResultCard } from "./ResultCard";
import {
  CITY_LABELS,
  PROPERTY_LABELS,
  STREET_LABELS,
  type City,
  type PredictionResponse,
  type PropertyType,
  type StreetSurface,
  type Tri,
} from "./types";

const TRI_FIELDS: { key: keyof FormState; label: string }[] = [
  { key: "hasPool", label: "Piscina" },
  { key: "hasQuincho", label: "Quincho" },
  { key: "inGatedCommunity", label: "Barrio cerrado o condominio" },
  { key: "hasElevator", label: "Ascensor" },
  { key: "isNew", label: "A estrenar" },
];

function TriField(props: { name: string; label: string; value: Tri; onChange: (v: Tri) => void }) {
  const options: { value: Tri; label: string }[] = [
    { value: "si", label: "Sí" },
    { value: "no", label: "No" },
    { value: "nose", label: "No sé" },
  ];
  return (
    <fieldset className="tri">
      <legend>{props.label}</legend>
      <div className="segmented">
        {options.map((option) => (
          <label key={option.value}>
            <input
              type="radio"
              name={props.name}
              value={option.value}
              checked={props.value === option.value}
              onChange={() => props.onChange(option.value)}
            />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function EstimatePage({ info }: { info: InfoState }) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [neighborhoods, setNeighborhoods] = useState<string[]>([]);
  const [neighborhoodsError, setNeighborhoodsError] = useState<string | null>(null);
  const [loadingNeighborhoods, setLoadingNeighborhoods] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<PredictionResponse | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((previous) => ({ ...previous, [key]: value }));

  useEffect(() => {
    setNeighborhoods([]);
    setNeighborhoodsError(null);
    if (form.city === "") return;
    let cancelled = false;
    setLoadingNeighborhoods(true);
    getNeighborhoods(form.city)
      .then((list) => !cancelled && setNeighborhoods(list))
      .catch((e: unknown) => {
        if (!cancelled) {
          setNeighborhoodsError(e instanceof Error ? e.message : "No se pudieron cargar los barrios.");
        }
      })
      .finally(() => !cancelled && setLoadingNeighborhoods(false));
    return () => {
      cancelled = true;
    };
  }, [form.city]);

  useEffect(() => {
    if (!result) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    resultRef.current?.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
  }, [result]);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const built = buildRequest(form);
    if (!built.ok) {
      setError(built.error);
      return;
    }
    setSubmitting(true);
    try {
      setResult(await predict(built.request));
    } catch (e) {
      setResult(null);
      setError(e instanceof ApiError || e instanceof Error ? e.message : "Error inesperado.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid estimate">
      <section className="intro">
        <h1>Estimá el precio de oferta de un inmueble</h1>
        <p className="lead">
          Casas, departamentos y dúplex en venta en Asunción, Luque, San Lorenzo y Fernando de la
          Mora. El resultado es un <strong>precio de oferta estimado</strong> con un rango, no una
          tasación.
        </p>
      </section>

      <form onSubmit={onSubmit} noValidate className="form">
        <div className="field">
          <label htmlFor="city">Ciudad</label>
          <select
            id="city"
            value={form.city}
            onChange={(e) => {
              set("city", e.target.value as City | "");
              set("neighborhood", "");
            }}
          >
            <option value="">Elegí una ciudad</option>
            {(Object.keys(CITY_LABELS) as City[]).map((city) => (
              <option key={city} value={city}>
                {CITY_LABELS[city]}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="neighborhood">Barrio</label>
          <select
            id="neighborhood"
            value={form.neighborhood}
            disabled={form.city === "" || loadingNeighborhoods}
            onChange={(e) => set("neighborhood", e.target.value)}
          >
            <option value="">No sé / otro</option>
            {neighborhoods.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          {loadingNeighborhoods && <p className="hint">Cargando barrios…</p>}
          {neighborhoodsError && <p className="hint error-text">{neighborhoodsError}</p>}
          {form.city !== "" && form.neighborhood === "" && !loadingNeighborhoods && (
            <p className="hint">
              Sin barrio, la estimación usa datos de toda la ciudad y es menos precisa.
            </p>
          )}
        </div>

        <div className="field">
          <label htmlFor="type">Tipo de inmueble</label>
          <select
            id="type"
            value={form.propertyType}
            onChange={(e) => set("propertyType", e.target.value as PropertyType | "")}
          >
            <option value="">Elegí un tipo</option>
            {(Object.keys(PROPERTY_LABELS) as PropertyType[]).map((type) => (
              <option key={type} value={type}>
                {PROPERTY_LABELS[type]}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="area">Superficie construida (m²)</label>
          <input
            id="area"
            type="text"
            inputMode="decimal"
            autoComplete="off"
            value={form.builtArea}
            onChange={(e) => set("builtArea", e.target.value)}
          />
        </div>

        <details className="more">
          <summary>Más detalles (opcional)</summary>
          <p className="hint">Si no sabés un dato, dejalo en «No sé»: no se tiene en cuenta.</p>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="land">Terreno (m²)</label>
              <input
                id="land"
                type="text"
                inputMode="decimal"
                value={form.landArea}
                onChange={(e) => set("landArea", e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="bedrooms">Dormitorios</label>
              <input
                id="bedrooms"
                type="text"
                inputMode="numeric"
                value={form.bedrooms}
                onChange={(e) => set("bedrooms", e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="bathrooms">Baños</label>
              <input
                id="bathrooms"
                type="text"
                inputMode="numeric"
                value={form.bathrooms}
                onChange={(e) => set("bathrooms", e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="street">Calle</label>
              <select
                id="street"
                value={form.streetSurface}
                onChange={(e) => set("streetSurface", e.target.value as StreetSurface | "")}
              >
                <option value="">No sé</option>
                {(Object.keys(STREET_LABELS) as StreetSurface[]).map((surface) => (
                  <option key={surface} value={surface}>
                    {STREET_LABELS[surface]}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {TRI_FIELDS.map(({ key, label }) => (
            <TriField
              key={key}
              name={key}
              label={label}
              value={form[key] as Tri}
              onChange={(value) => set(key, value as never)}
            />
          ))}
        </details>

        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="primary" disabled={submitting}>
          {submitting ? "Estimando…" : "Estimar precio de oferta"}
        </button>
      </form>

      <div ref={resultRef} className="result-slot">
        {result && <ResultCard result={result} info={info} />}
      </div>
    </div>
  );
}
