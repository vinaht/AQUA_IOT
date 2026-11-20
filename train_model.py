"""Default: train all three 30-minute forecasts. --legacy: reproduce the old two-model run."""
import argparse
import pandas as pd
import numpy as np
import joblib
from pathlib import Path
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score
)
from ml_review.pipeline import main as train_all

ROOT = Path(__file__).resolve().parent


def train_legacy():
    # 1. Doc dataset
    df = pd.read_csv(
        ROOT / "data/pond_pairs_30min.csv",
        parse_dates=["timestamp"]
    )

    df = df.sort_values("timestamp").reset_index(drop=True)

    # 2. Tao dac trung thoi gian
    hour = (
        df["timestamp"].dt.hour +
        df["timestamp"].dt.minute / 60
    )

    df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24)

    features = [
        "water_pH",
        "water_temp",
        "hour_sin",
        "hour_cos"
    ]

    # 3. Chia train / validation / test theo thoi gian
    n = len(df)
    t_val = df.iloc[int(n * 0.70)]["timestamp"]
    t_test = df.iloc[int(n * 0.85)]["timestamp"]

    # Cach ly 30 phut de tranh ro ri nhan tuong lai
    gap = pd.Timedelta(minutes=30)

    train = df[df["timestamp"] < t_val - gap]
    val = df[
        (df["timestamp"] >= t_val) &
        (df["timestamp"] < t_test - gap)
    ]
    test = df[df["timestamp"] >= t_test]

    print("Train:", len(train))
    print("Validation:", len(val))
    print("Test:", len(test))

    # 4. Huan luyen hai mo hinh RFR
    targets = {
        "ph": ("ph_after_30min", "water_pH"),
        "temperature": ("temp_after_30min", "water_temp")
    }

    (ROOT / "models").mkdir(exist_ok=True)

    for name, (target, current_col) in targets.items():
        print(f"\n===== {name.upper()} =====")

        model = RandomForestRegressor(
            n_estimators=200,
            max_depth=14,
            min_samples_leaf=3,
            random_state=42,
            n_jobs=-1
        )

        model.fit(train[features], train[target])

        # Danh gia tren validation
        val_pred = model.predict(val[features])
        val_mae = mean_absolute_error(
            val[target], val_pred
        )

        # Danh gia tren test
        predictions = model.predict(test[features])

        mae = mean_absolute_error(test[target], predictions)
        rmse = np.sqrt(
            mean_squared_error(test[target], predictions)
        )
        r2 = r2_score(test[target], predictions)

        # Baseline: gia tri sau 30 phut bang hien tai
        baseline_mae = mean_absolute_error(
            test[target], test[current_col]
        )

        print("Validation MAE:", round(val_mae, 4))
        print("Test MAE:", round(mae, 4))
        print("Test RMSE:", round(rmse, 4))
        print("Test R2:", round(r2, 4))
        print("Baseline MAE:", round(baseline_mae, 4))

        joblib.dump(model, ROOT / "models" / f"rfr_{name}.pkl")

    print("\nDa luu hai mo hinh vao thu muc models/")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", action="store_true", help="Train the two original .pkl files on the filtered pairs")
    if parser.parse_args().legacy:
        train_legacy()
    else:
        train_all()
