
import pandas as pd

df = pd.read_csv("data/pond_iot_2023.csv")

# Chuyen cot thoi gian
df["created_date"] = pd.to_datetime(
    df["created_date"],
    format="%m/%d/%Y %H:%M",
    errors="coerce"
)

# Sap xep theo thoi gian
df = df.sort_values("created_date")

print("===== THONG TIN DU LIEU =====")
print("Tong ban ghi:", len(df))
print("Thoi gian bat dau:", df["created_date"].min())
print("Thoi gian ket thuc:", df["created_date"].max())

print("\n===== THOI GIAN =====")
print("Ngay gio khong hop le:",
      df["created_date"].isna().sum())

print("So timestamp trung:",
      df["created_date"].duplicated().sum())

# Khoang cach giua cac lan do
intervals = df["created_date"].diff().dt.total_seconds() / 60

print("\nKhoang cach do (phut):")
print(intervals.describe())

print("\n5 khoang cach pho bien:")
print(intervals.value_counts().head())

print("\n===== THONG KE PH =====")
print(df["water_pH"].describe())

print("\n===== THONG KE NHIET DO =====")
print(df["water_temp"].describe())

print("\n===== GIA TRI BAT THUONG =====")
print("pH ngoai 0-14:",
      ((df["water_pH"] < 0) |
       (df["water_pH"] > 14)).sum())

print("Nhiet do ngoai 0-50°C:",
      ((df["water_temp"] < 0) |
       (df["water_temp"] > 50)).sum())
