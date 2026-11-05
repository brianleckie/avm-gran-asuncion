import type { InfoState } from "./App";
import {
  coverageInWords,
  isTestModel,
  metaNumber,
  metaString,
  metricRows,
  nominalCoverage,
} from "./lib";

function ModelFacts({ info }: { info: InfoState }) {
  if (info.status === "loading") return <p className="hint">Leyendo los datos del modelo…</p>;
  if (info.status === "error") {
    return (
      <p className="error-text">
        No pudimos leer los datos del modelo ({info.message}). Los números de esta sección se
        muestran solo cuando el servicio los informa.
      </p>
    );
  }
  const model = info.info;
  if (isTestModel(model)) {
    return (
      <p className="banner banner-test inline">
        Modelo de prueba: no tiene datos de entrenamiento ni métricas, y sus valores no significan
        nada.
      </p>
    );
  }
  const rows: { label: string; value: string }[] = [];
  const version = metaString(model, "model_version");
  if (version) rows.push({ label: "Versión del modelo", value: version });
  const snapshot = metaString(model, "snapshot_date");
  if (snapshot) rows.push({ label: "Fecha de los datos (snapshot)", value: snapshot });
  const trained = metaString(model, "trained_at");
  if (trained) rows.push({ label: "Entrenado", value: trained });
  const n = metaNumber(model, "n_train");
  if (n !== null) {
    rows.push({ label: "Avisos de entrenamiento", value: new Intl.NumberFormat("es-PY").format(n) });
  }
  const words = coverageInWords(nominalCoverage(model));
  if (words) rows.push({ label: "Cobertura nominal del intervalo", value: words });
  rows.push(...metricRows(model));
  if (rows.length === 0) {
    return <p className="hint">El servicio no informó datos del modelo.</p>;
  }
  return (
    <dl className="facts">
      {rows.map((row) => (
        <div key={row.label}>
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Methodology({ info }: { info: InfoState }) {
  return (
    <article className="prose">
      <h1>Metodología y limitaciones</h1>
      <p className="lead">
        Esta herramienta estima el <strong>precio de oferta</strong> por m² y el valor total de
        casas, departamentos y dúplex en venta en Asunción, Luque, San Lorenzo y Fernando de la
        Mora. Antes de usar un resultado, leé qué es y qué no es.
      </p>

      <h2>Datos del modelo en uso</h2>
      <p>Estos datos vienen del servicio de estimación, no están escritos en esta página.</p>
      <ModelFacts info={info} />

      <h2>Qué estima</h2>
      <p>
        Estima a qué precio se <em>publican</em> propiedades parecidas, junto con un rango. El rango
        tiene una cobertura nominal (del tipo «en N de cada 10 casos», con el N que informa el modelo): es el nivel con el que
        se calibró el modelo, no una garantía para una propiedad en particular.
      </p>

      <h2>Precio publicado no es precio de transacción</h2>
      <p>
        Los datos son precios de avisos. En Paraguay no existe un registro público de los precios
        de cierre de las ventas, así que no se puede saber a cuánto se vendió cada propiedad. Un
        aviso puede publicarse por encima de lo que finalmente se cobra, y las métricas del modelo
        miden qué tan bien se predice el precio publicado, no el de una venta concretada. Por eso
        todo valor se presenta como «precio de oferta estimado» y no reemplaza una tasación.
      </p>

      <h2>Fuente de datos</h2>
      <ul>
        <li>
          <strong>Una sola fuente:</strong> el portal Clasipar. Los resultados heredan sus sesgos
          (qué propiedades se publican allí, y cómo).
        </li>
        <li>
          <strong>Un solo período:</strong> los avisos corresponden a una toma puntual de datos.
          No hay serie temporal ni se mide cómo cambian los precios con el tiempo; los precios de
          hoy pueden diferir de los del período de entrenamiento.
        </li>
        <li>
          Se recorrió una muestra de las páginas de resultados, no el portal completo.
        </li>
      </ul>

      <h2>Cómo se obtuvieron los datos (scraping ético)</h2>
      <ul>
        <li>Se respetó el archivo robots.txt del sitio y se usó un identificador propio y visible.</li>
        <li>Se esperó varios segundos entre pedidos para no recargar el servidor.</li>
        <li>
          No se guardan teléfonos, nombres de anunciantes ni correos. La copia local de las páginas
          se guarda ya sanitizada, nunca el HTML crudo con datos de anunciantes.
        </li>
        <li>Los documentos del proyecto publican solo datos agregados, no avisos individuales.</li>
      </ul>

      <h2>Ubicación: barrio, no dirección</h2>
      <p>
        La geografía es a nivel de <strong>barrio</strong>. Dos propiedades del mismo barrio
        reciben la misma información de ubicación, aunque una esté sobre una avenida y la otra no.
        Esta herramienta no estima a nivel de calle ni de manzana.
      </p>
      <p>
        Si no elegís barrio, o el barrio no se reconoce, la estimación se hace con datos de la{" "}
        <strong>ciudad</strong>: es menos precisa y el sistema lo avisa. Los barrios y los puntos
        de interés (colegios, hospitales, vías, etc.) provienen de OpenStreetMap.
      </p>

      <h2>Moneda: una cotización única</h2>
      <p>
        Parte de los avisos publica el precio en guaraníes. Para llevarlos a dólares se usó una{" "}
        <strong>única cotización de una casa de cambios</strong> para todos los datos, en lugar de
        la cotización de cada fecha (ADR-004). El monto en dólares de un aviso en guaraníes depende
        de esa cotización. Los avisos publicados en dólares no se ven afectados.
      </p>

      <h2>Otras limitaciones</h2>
      <ul>
        <li>
          <strong>Departamentos:</strong> hay menos datos que para casas. En los avisos de
          departamentos, cuando la superficie publicada no dice si es construida o de terreno, se
          tomó la primera como superficie construida (un departamento no tiene terreno propio),
          pero no se verificó aviso por aviso. Las estimaciones de departamentos tienen más
          incertidumbre.
        </li>
        <li>
          <strong>Barrios con pocos avisos:</strong> el rango es menos confiable. Cuando el modelo
          detecta pocos datos, lo informa con una advertencia en el resultado.
        </li>
        <li>
          La superficie que se usa es la construida; el modelo no ve fotos, estado de conservación,
          terminaciones ni orientación.
        </li>
        <li>Solo cubre las cuatro ciudades y los tres tipos de inmueble indicados, en venta.</li>
      </ul>

      <h2>Atribuciones</h2>
      <p>© OpenStreetMap contributors. Datos disponibles bajo la licencia ODbL.</p>
    </article>
  );
}
