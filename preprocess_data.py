
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent

# 1. Doc dataset
df = pd.read_csv(ROOT / "data/pond_iot_2023.csv")

# 2. Chuyen doi thoi gian
df["timestamp"] = pd.to_datetime(
    df["created_date"],
    format="%m/%d/%Y %H:%M"
)

df["timestamp"] = df["timestamp"].dt.floor("min")

# 3. Gop du lieu trung thoi diem
df = df.groupby("timestamp", as_index=False).agg(
    water_pH=("water_pH", "median"),
    water_temp=("water_temp", "median"),
    TDS=("TDS", "median"),
    samples_count=("water_pH", "size")
)

df = df.sort_values("timestamp")

print("So ban ghi sau khi gop:", len(df))

# 4. Tao nhan du bao sau 30 phut
future = df[
    ["timestamp", "water_pH", "water_temp", "TDS"]
].copy()

future["timestamp"] -= pd.Timedelta(minutes=30)

future = future.rename(columns={
    "water_pH": "ph_after_30min",
    "water_temp": "temp_after_30min",
    "TDS": "tds_after_30min"
})

# 5. Ghep theo timestamp thuc te
result = df.merge(
    future,
    on="timestamp",
    how="inner"
)

# 6. Luu dataset moi
result.to_csv(
    ROOT / "data/pond_pairs_30min.csv",
    index=False
)

print("\n===== KET QUA =====")
print("So ban ghi co du lieu sau 30 phut:", len(result))
print("\n5 dong dau:")
print(result.head())

print("\nGia tri thieu:")
print(result.isnull().sum())

print("\nDa luu: data/pond_pairs_30min.csv")
