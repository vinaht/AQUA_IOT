"""Train and evaluate 30-minute pond forecasts using the source dataset's local clock."""
from pathlib import Path
import hashlib
import json
import platform

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline

ROOT = Path(__file__).resolve().parent
COLS = ["water_pH", "water_temp", "TDS"]
INPUTS = {"water_pH": COLS[:2], "water_temp": COLS[:2], "TDS": ["TDS"]}
HORIZON = pd.Timedelta(minutes=30)
TDS_REFERENCE_PPM = 500.0


def prepare(raw, cols=None):
    cols = list(cols if cols is not None else [c for c in COLS if c in raw])
    d = raw[cols].apply(pd.to_numeric, errors="coerce")
    d.index = pd.to_datetime(raw["created_date"], format="%m/%d/%Y %H:%M", errors="coerce")
    valid = d.index.notna() & np.isfinite(d).all(axis=1)
    for col, bounds in {"water_pH": (0, 14), "water_temp": (0, 100), "TDS": (0, np.inf)}.items():
        if col in cols:
            valid &= d[col].between(*bounds)
    minutes = d.loc[valid].groupby(level=0).median().sort_index()
    audit = dict(raw_rows=len(d), rejected_rows=int((~valid).sum()), valid_rows=int(valid.sum()),
                 minutes=len(minutes), start=str(minutes.index.min()), end=str(minutes.index.max()),
                 max_gap_minutes=float(minutes.index.to_series().diff().dt.total_seconds().max() / 60))
    return minutes, audit


def features(d):
    x = d.copy()
    hour = d.index.hour + d.index.minute / 60
    x["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    x["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    for col in d.columns:
        for lag in (5, 15, 30):
            x[f"{col}_lag{lag}"] = d[col].shift(freq=pd.Timedelta(minutes=lag))
        roll = d[col].rolling("15min", min_periods=1)
        x[f"{col}_mean15"] = roll.mean()
        x[f"{col}_std15"] = roll.std(ddof=0)
    return x


def fit(name, x, y, current):
    if name in ("persistence", "mean15"):
        return None
    model = make_pipeline(SimpleImputer(strategy="median", add_indicator=True),
                          RandomForestRegressor(n_estimators=150, max_depth=12, min_samples_leaf=8,
                                                random_state=42, n_jobs=6))
    model.fit(x, y - current if name == "rf_residual" else y)
    return model


def predict(name, model, x, col):
    if name == "persistence":
        return x[col].to_numpy()
    if name == "mean15":
        return x[col + "_mean15"].to_numpy()
    y = model.predict(x)
    return y + x[col].to_numpy() if name == "rf_residual" else y


def scores(actual, predicted):
    return dict(mae=float(mean_absolute_error(actual, predicted)),
                rmse=float(mean_squared_error(actual, predicted) ** 0.5),
                r2=float(r2_score(actual, predicted)))


def exceedance(actual, predicted):
    actual = np.asarray(actual) > TDS_REFERENCE_PPM
    predicted = np.asarray(predicted) > TDS_REFERENCE_PPM
    tp = int((actual & predicted).sum())
    fp = int((~actual & predicted).sum())
    fn = int((actual & ~predicted).sum())
    return dict(reference_ppm=TDS_REFERENCE_PPM, positives=int(actual.sum()), tp=tp, fp=fp, fn=fn,
                tn=int((~actual & ~predicted).sum()), precision=tp/(tp+fp) if tp+fp else None,
                recall=tp/(tp+fn) if tp+fn else None)


def main():
    path = ROOT / "data/pond_iot_2023_raw.csv"
    raw = pd.read_csv(path)
    audit = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), sklearn=sklearn.__version__,
                 pandas=pd.__version__, numpy=np.__version__, python=platform.python_version(),
                 targets={}, selected={})
    validations, results = [], []
    for col in ("TDS", "water_temp", "water_pH"):
        d, info = prepare(raw, INPUTS[col])
        x = features(d)
        target = d[col].shift(freq=-HORIZON).rename("target")
        pairs = x.join(target, how="inner").sort_index()
        names = list(x.columns)
        cut60, cut70, cut85 = (pairs.index[int(len(pairs)*frac)] for frac in (.60, .70, .85))
        candidates = ("persistence", "mean15", "rf_direct", "rf_residual")
        errors = {k: [] for k in candidates}
        for fold, (start, end) in enumerate(((cut60, cut70), (cut70, cut85))):
            train = pairs.loc[pairs.index < start - HORIZON]
            val = pairs.loc[(pairs.index >= start) & (pairs.index < end - HORIZON)]
            for candidate in candidates:
                model = fit(candidate, train[names], train.target, train[col])
                pred = predict(candidate, model, val[names], col)
                metric = scores(val.target, pred)
                errors[candidate].append(metric["mae"])
                validations.append(dict(target=col, fold=fold, candidate=candidate,
                                        train_n=len(train), validation_n=len(val), **metric))
        selected = min(candidates, key=lambda k: np.mean(errors[k]))
        train = pairs.loc[pairs.index < cut85 - HORIZON]
        test = pairs.loc[pairs.index >= cut85]
        model = fit(selected, train[names], train.target, train[col])
        bundle = dict(candidate=selected, model=model, features=names, inputs=INPUTS[col], target=col,
                      horizon_minutes=30, training_end=str(train.index.max()), sklearn_version=sklearn.__version__)
        joblib.dump(bundle, ROOT / "models" / f"{col}.joblib", compress=3)
        prediction = predict(selected, model, test[names], col)
        for label, candidate, pred in (("selected", selected, prediction),
                                       ("persistence", "persistence", test[col].to_numpy())):
            row = dict(target=col, model=label, candidate=candidate, n=len(test), **scores(test.target, pred))
            if col == "TDS":
                row.update(exceedance(test.target, pred))
                below = test[col].to_numpy() <= TDS_REFERENCE_PPM
                new_events = exceedance(test.target.to_numpy()[below], pred[below])
                row.update({f"new_{k}": v for k, v in new_events.items() if k != "reference_ppm"})
            results.append(row)
        info.update(pairs=len(pairs), train_n=len(train), test_n=len(test),
                    fold_boundaries=list(map(str, (cut60, cut70, cut85))), test_end=str(test.index.max()))
        audit["targets"][col] = info
        audit["selected"][col] = selected
        pd.DataFrame(dict(timestamp=test.index, actual=test.target.values, prediction=prediction,
                          persistence=test[col].values)).to_csv(ROOT/"results"/f"{col}_predictions.csv", index=False)
        print(col, results[-2:], flush=True)
    (ROOT/"results/audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    pd.DataFrame(validations).to_csv(ROOT/"results/validation.csv", index=False)
    pd.DataFrame(results).to_csv(ROOT/"results/test_metrics.csv", index=False)


if __name__ == "__main__":
    main()

