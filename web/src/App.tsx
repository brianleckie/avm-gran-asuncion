import { useEffect, useState } from "react";
import { getModelInfo } from "./api";
import { EstimatePage } from "./EstimatePage";
import { isTestModel } from "./lib";
import { Methodology } from "./Methodology";
import type { ModelInfo } from "./types";

export type InfoState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; info: ModelInfo };

function currentRoute(): "estimar" | "metodologia" {
  return window.location.hash === "#/metodologia" ? "metodologia" : "estimar";
}

export function App() {
  const [route, setRoute] = useState(currentRoute);
  const [info, setInfo] = useState<InfoState>({ status: "loading" });

  useEffect(() => {
    const onHash = () => {
      setRoute(currentRoute());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    let cancelled = false;
    getModelInfo()
      .then((value) => !cancelled && setInfo({ status: "ok", info: value }))
      .catch((error: unknown) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "No se pudo leer el modelo.";
        setInfo({ status: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const testModel = info.status === "ok" && isTestModel(info.info);

  return (
    <>
      {testModel && (
        <div className="banner banner-test" role="alert">
          Modelo de prueba: estos valores no significan nada.
        </div>
      )}
      <header className="site-header">
        <div className="wrap header-row">
          <a className="brand" href="#/">
            AVM Gran Asunción
          </a>
          <nav aria-label="Principal">
            <a href="#/" aria-current={route === "estimar" ? "page" : undefined}>
              Estimar
            </a>
            <a href="#/metodologia" aria-current={route === "metodologia" ? "page" : undefined}>
              Metodología y limitaciones
            </a>
          </nav>
        </div>
      </header>
      <main className="wrap">
        {route === "estimar" ? <EstimatePage info={info} /> : <Methodology info={info} />}
      </main>
      <footer className="site-footer">
        <div className="wrap">
          <p>
            Todo valor de este sitio es un <strong>precio de oferta estimado</strong>: se basa en
            precios publicados en avisos, no en precios de venta concretados.
          </p>
          <p>© OpenStreetMap contributors (datos de barrios y puntos de interés).</p>
        </div>
      </footer>
    </>
  );
}
