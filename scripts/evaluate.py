"""Evalúa baseline y LightGBM con/sin geo con CQR por tipo en cinco folds agrupados."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

from avm.model.experiment import evaluate_lightgbm


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--geo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--stage", choices=["development", "final"], default="development")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.out.exists() or (args.report and args.report.exists()):
        raise FileExistsError("Elegí otra carpeta o reporte para conservar la corrida anterior")
    rows, diagnostics = evaluate_lightgbm(args.dataset, args.geo, seed=args.seed)
    summary = {
        "dataset_version": args.dataset_version,
        "stage": args.stage,
        "seed": args.seed,
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "geo_sha256": hashlib.sha256(args.geo.read_bytes()).hexdigest(),
        "diagnostics": diagnostics,
    }
    args.out.mkdir(parents=True)
    with (args.out / "metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "evaluation.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8"
    )
    metrics = pd.DataFrame(rows)
    all_rows = metrics[(metrics.segment == "all") & (metrics.interval != "raw_quantile")]
    lgbm_rows = all_rows[all_rows.model == "lightgbm"]
    paired = lgbm_rows[~lgbm_rows.with_geo].merge(
        lgbm_rows[lgbm_rows.with_geo], on="fold", suffixes=("_without_geo", "_with_geo")
    )
    ablation = pd.DataFrame({"fold": paired.fold})
    for metric in ["mdape", "rmse_log", "pe20", "interval_coverage"]:
        ablation[f"{metric}_without_geo"] = paired[f"{metric}_without_geo"]
        ablation[f"{metric}_with_geo"] = paired[f"{metric}_with_geo"]
        ablation[f"{metric}_delta"] = paired[f"{metric}_with_geo"] - paired[f"{metric}_without_geo"]
    ablation.to_csv(args.out / "ablation.csv", index=False)
    lines = [
        f"# Evaluación {args.dataset_version} · {args.stage}",
        "",
        "Resultados provisionales pendientes de v3."
        if args.stage == "development"
        else "Resultados sobre la versión declarada final.",
        "",
        "Se muestran medias y extremos por fold. Los folds usan los mismos clusters.",
        "",
    ]
    for keys, group in all_rows.groupby(["model", "with_geo", "interval"], sort=True):
        lines.extend([f"## {keys[0]} · geo={keys[1]} · {keys[2]}", ""])
        for column in [
            "mdape",
            "pe10",
            "pe20",
            "rmse_log",
            "interval_coverage",
            "mean_interval_width",
        ]:
            lines.append(
                f"- {column} media {group[column].mean():.6f}, "
                f"mínimo {group[column].min():.6f}, máximo {group[column].max():.6f}."
            )
        lines.append("")
    lines.extend(["## Diferencias pareadas con geo menos sin geo", ""])
    for metric in ["mdape", "rmse_log", "pe20", "interval_coverage"]:
        lines.append(f"- {metric} diferencia media {ablation[f'{metric}_delta'].mean():.6f}.")
    lines.append("")
    type_rows = metrics[
        (metrics.segment == "property_type") & (metrics.model == "lightgbm") & metrics.with_geo
    ]
    lines.extend(["## Cobertura por tipo antes y después de CQR", ""])
    for (kind, interval), group in type_rows.groupby(["value", "interval"], sort=True):
        lines.append(
            f"- {kind}, {interval}. Cobertura media {group.interval_coverage.mean():.6f}, "
            f"mínimo {group.interval_coverage.min():.6f}, "
            f"ancho relativo medio {group.mean_interval_width.mean():.6f}."
        )
    lines.extend(
        [
            "",
            "## Límites de interpretación",
            "",
            "Departamento mantiene confianza reducida por la identificación de superficie.",
            "Una métrica menor de departamento requiere considerar ese supuesto de medición.",
            "La cobertura nominal por tipo es del 80 % bajo intercambiabilidad de clusters. "
            "La cobertura empírica puede fluctuar por fold.",
            "El CSV incluye ciudad, precisión geo, terciles de USD/m² con cortes de train "
            "y soporte barrial.",
            "La ablation elimina dist_* y n_*. Conserva ciudad, barrio y geo_precision de I1.",
            "",
        ]
    )
    report = args.report or args.out / "report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"Evaluación {args.stage}: {len(rows)} agregados en {args.out}")


if __name__ == "__main__":
    main()
