# Dự báo chất lượng nước sau 30 phút

Từ thư mục gốc của dự án trong PowerShell:

```powershell
& .\.venv\Scripts\python.exe .\ml_review\predict.py .\ml_review\example_history.csv
```

Ba mô hình đã được chọn và huấn luyện trên `ml_review/data/pond_iot_2023_raw.csv`. Tệp đầu vào cho dự báo ngoại tuyến có các cột `created_date,water_pH,water_temp,TDS`; mẫu thời gian là `3/22/2023 17:53`. Dữ liệu cũ thiếu TDS vẫn dùng được cho các kênh còn lại. Nếu chủ động huấn luyện lại, dừng server rồi chạy:

```powershell
& .\.venv\Scripts\python.exe .\ml_review\pipeline.py
```

Pipeline gộp trung vị các mẫu cùng phút, ghép đúng thời điểm cách nhau 30 phút và chừa khoảng cách 30 phút giữa các phần huấn luyện và đánh giá. TDS dùng chuỗi TDS riêng và giữ cả giá trị trên 500 ppm. pH và nhiệt độ dùng các phút hợp lệ của hai kênh đó. Các ứng viên gồm giữ nguyên giá trị, trung bình trượt 15 phút, Random Forest trực tiếp và Random Forest dự báo phần thay đổi so với hiện tại. Chọn ứng viên có MAE trung bình thấp nhất trên hai lượt kiểm định theo thời gian trước khi chấm trên tập kiểm tra cuối.

Xem `results/test_metrics.csv` cho MAE, RMSE, R², precision và recall ở mốc TDS > 500 ppm. Các cột `new_*` chỉ xét lúc TDS hiện tại ≤ 500 ppm. Cột `n` là số cặp đánh giá và `positives` là số cặp có TDS thực sau 30 phút vượt mốc. Mốc này dùng để đối chiếu với bộ dữ liệu nghiên cứu. Hiệu quả tại ao cần được đánh giá trên chuỗi đo tại chỗ.

Mốc giờ của dữ liệu nguồn không ghi múi giờ. Phần phục vụ trực tuyến dùng giờ Việt Nam cho đặc trưng giờ trong ngày. Khi dữ liệu theo phút bị gián đoạn, kiểm định ngoại tuyến dùng các mẫu sẵn có trong cửa sổ; server áp dụng thêm điều kiện đủ 15 phút liên tiếp cho từng dự báo.
