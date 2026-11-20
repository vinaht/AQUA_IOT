"""Usage: python predict.py history.csv (created_date, water_pH, water_temp, TDS)."""
from functools import lru_cache
import json
import sys

import joblib
import pandas as pd
import sklearn

from pipeline import ROOT, COLS, INPUTS, HORIZON, features, prepare, predict


@lru_cache(maxsize=3)
def load_model(target):
    audit = json.loads((ROOT / "results/audit.json").read_text(encoding="utf-8"))
    if audit["sklearn"] != sklearn.__version__:
        raise RuntimeError(f"Models require scikit-learn {audit['sklearn']}; installed {sklearn.__version__}")
    bundle = joblib.load(ROOT / "models" / f"{target}.joblib")
    if bundle["target"] != target or bundle["horizon_minutes"] != 30:
        raise ValueError(f"Incompatible bundle for {target}")
    return bundle


def infer(target, history):
    bundle = load_model(target)
    x = features(history).tail(1)[bundle["features"]]
    value = predict(bundle["candidate"], bundle["model"], x, target)[0]
    return float(value)


def forecast(path):
    raw = pd.read_csv(path)
    latest = pd.to_datetime(raw["created_date"], format="%m/%d/%Y %H:%M", errors="coerce").max()
    if pd.isna(latest):
        raise ValueError("No valid timestamp")
    out = {"measured_at": str(latest), "forecast_at": str(latest + HORIZON), "rejected_by_target": {}}
    for target in COLS:
        inputs = INPUTS[target]
        if not set(inputs).issubset(raw):
            out[target] = None
            continue
        d, audit = prepare(raw, inputs)
        out["rejected_by_target"][target] = audit["rejected_rows"]
        out[target] = infer(target, d) if not d.empty and d.index.max() == latest else None
    if all(out[c] is None for c in COLS):
        raise ValueError("No valid measurements at the latest timestamp")
    return out


if __name__ == "__main__":
    print(json.dumps(forecast(sys.argv[1]), indent=2))
