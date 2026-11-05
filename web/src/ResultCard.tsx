import type { InfoState } from "./App";
import {
  coverageInWords,
  formatUsd,
  markerPosition,
  nominalCoverage,
  warningText,
} from "./lib";
import type { PredictionResponse } from "./types";

export function ResultCard({ result, info }: { result: PredictionResponse; info: InfoState }) {
  const model = info.status === "ok" ? info.info : null;
  const words = coverageInWords(nominalCoverage(model, result.coverage_nominal));
  const position = markerPosition(result.p_low, result.usd_per_m2, result.p_high);

  return (
    <section className="card result" aria-live="polite">
      <p className="legend">precio de oferta estimado</p>

      <div className="figures">
        <div>
          <p className="figure-label">Por m²</p>
          <p className="figure">{formatUsd(result.usd_per_m2)}</p>
        </div>
        <div>
          <p className="figure-label">Valor total</p>
          <p className="figure">{formatUsd(result.total_usd)}</p>
        </div>
      </div>

      <div
        className="range"
        role="img"
        aria-label={`Rango de precio por m²: de ${formatUsd(result.p_low)} a ${formatUsd(result.p_high)}, con el estimado en ${formatUsd(result.usd_per_m2)}`}
      >
        <div className="range-track">
          <div className="range-marker" style={{ left: `${position}%` }} />
        </div>
        <div className="range-ends">
          <span>{formatUsd(result.p_low)}</span>
          <span>{formatUsd(result.p_high)}</span>
        </div>
      </div>
      <p className="range-note">
        Rango por m²: de {formatUsd(result.p_low)} a {formatUsd(result.p_high)}. Rango del valor
        total: de {formatUsd(result.total_low)} a {formatUsd(result.total_high)}.
      </p>
      {words ? (
        <p>
          El intervalo está calibrado para que {words} el precio de oferta caiga dentro de este
          rango. Es una cobertura nominal: no garantiza el resultado de un caso puntual.
        </p>
      ) : (
        <p className="hint">El modelo no informó el nivel de cobertura del intervalo.</p>
      )}

      {result.warnings.length > 0 && (
        <div className="warnings">
          <h2>Tené en cuenta</h2>
          <ul>
            {result.warnings.map((warning, index) => (
              <li key={`${warning.code}-${index}`}>{warningText(warning.code, warning.message)}</li>
            ))}
          </ul>
        </div>
      )}

      <p className="hint">
        Se estima el precio al que se publican propiedades similares, no el precio de una venta.
        Más en <a href="#/metodologia">Metodología y limitaciones</a>.
      </p>
    </section>
  );
}
