"""Entrena un baseline I4 sin mezclar clusters de entrenamiento/calibración/test."""

import argparse
import json
from pathlib import Path

from avm.model.training import train_baseline


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--geo", type=Path, required=True)
    parser.add_argument("--gazetteer", type=Path, required=True)
    parser.add_argument("--model", choices=["baseline", "lightgbm-cqr"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--min-clusters", type=int, default=20)
    parser.add_argument("--without-geo", action="store_true")
    parser.add_argument("--dataset-version", default="unspecified")
    parser.add_argument("--stage", choices=["development", "final"], default="development")
    args = parser.parse_args(argv)
    if args.model == "baseline":
        if args.without_geo:
            parser.error("--without-geo solo se aplica a lightgbm-cqr")
        metadata = train_baseline(
            args.dataset,
            args.geo,
            args.gazetteer,
            args.out,
            seed=args.seed,
            min_clusters=args.min_clusters,
        )
    else:
        from avm.model.experiment import train_lightgbm

        metadata = train_lightgbm(
            args.dataset,
            args.geo,
            args.gazetteer,
            args.out,
            seed=args.seed,
            min_clusters=args.min_clusters,
            with_geo=not args.without_geo,
            dataset_version=args.dataset_version,
            stage=args.stage,
        )
    print(
        json.dumps(
            {"model_version": metadata["model_version"], "metrics": metadata["metrics"]},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
