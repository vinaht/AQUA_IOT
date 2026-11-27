# Giám sát ao cá rô phi đỏ

ESP32 đọc pH, DS18B20 và TDS, hiển thị trên OLED và gửi số đo qua Wi-Fi. Máy tính lưu SQLite, dự báo ba thông số sau 30 phút và hiển thị cảnh báo.

Từ thư mục `D:\IoT_Water_Quality_AI`:

```powershell
& .\.venv\Scripts\python.exe .\IoT_WiFi\server.py
```

Nếu dùng môi trường Python khác, cài các phiên bản trong `ml_review/requirements.txt`. Mở http://127.0.0.1:8000 trên máy tính; trang tự kết nối và cập nhật mỗi 3 giây, không cần nhập API key. Các đường dẫn xem số đo, dự báo và tải CSV không yêu cầu key. ESP32 vẫn dùng API_KEY đã cấu hình để gửi số đo tại `/api/readings`. Trong Arduino IDE mở sketch `IoT_WiFi/WaterMonitorWiFi/WaterMonitorWiFi.ino`. Tab `config.h` chứa Wi-Fi, SERVER_URL (IPv4 LAN của máy tính và đường dẫn /api/readings), API_KEY và MEASUREMENT_CONTEXT. Chọn `calibration` cho dung dịch chuẩn và `water` cho nước cần theo dõi, sau đó nạp sketch. Dùng thư viện GravityTDS đã chỉnh cho ESP32 trên máy. GPIO34 nhận pH qua chia áp 10k/10k, DS18B20 dùng GPIO18, TDS GPIO35 và OLED SDA21/SCL22 tại 0x3C. TDS dùng nhiệt độ thực để bù và hệ số hiệu chuẩn tại địa chỉ EEPROM 8.

Cấu hình trong `alert_config.json` áp dụng sau khi khởi động lại server. pH có khoảng 6,5–7,5, nhiệt độ có khoảng 25–35 °C. Mốc TDS là 500 ppm theo bộ dữ liệu tham khảo. Hệ thống phân biệt cảnh báo số đo hiện tại và giá trị dự báo; TDS đúng bằng 500 ppm vẫn nằm trong mốc. Đặt `tds_high` thành `null` để tắt riêng cảnh báo TDS. Mỗi cặp ngưỡng khác cũng có thể cùng đặt thành `null`.

Mỗi ô số đo và dự báo có tín hiệu riêng: xanh ✓ khi trong ngưỡng, đỏ ▲ khi vượt ngưỡng. Khi chưa đánh giá được, ô dùng màu trung tính. Vượt ngưỡng không dừng đo, lưu hoặc dự báo. Trang không hiển thị các câu cảnh báo dài bên dưới bảng. Nếu mất kết nối, số đo lần nhận trước vẫn được giữ và chuyển màu trung tính trong khi trang tự thử lại.

Âm thanh mặc định tắt. Bật ô “Âm thanh cảnh báo” để cho phép trình duyệt phát tiếng bíp ngắn khi phát hiện một cảnh báo vượt ngưỡng mới ở số đo hoặc dự báo. Cảnh báo kéo dài không bíp lặp lại sau mỗi lần cập nhật; trở về trong ngưỡng rồi vượt lại sẽ báo lại. Mất dữ liệu tạm thời không đặt lại trạng thái cảnh báo. Các lỗi cảm biến, kết nối hoặc trạng thái chờ dữ liệu không kích hoạt tiếng bíp. Bật âm thanh không phát lại những cảnh báo đã hiển thị trước đó; các lần phát hiện vượt ngưỡng tiếp theo mới phát tiếng.

Mỗi phút cần ít nhất 3 mẫu nước hợp lệ, và mỗi dự báo cần đủ 15 phút liên tiếp của các kênh đầu vào, từ cùng thiết bị và lần khởi động. Khi cần, mô hình sử dụng thêm các đặc trưng trễ 5, 15 và 30 phút. Server ghi thời điểm kết thúc phút và đối chiếu dự báo với trung vị phút kết thúc sau 30 phút. Gói tin cũ thiếu TDS vẫn được nhận. Bản ghi hiệu chuẩn, số đo lỗi và mẫu quá cũ được loại khỏi luồng dự báo tương ứng.

`/export.csv` chứa số đo. `/forecasts.csv` chứa dự báo và giá trị thực, gồm `tds_predicted`, `tds_actual` và `tds_baseline`. Ô thực tế để trống cho tới khi có đủ số đo ở phút đích. Server tự bổ sung các cột vào cơ sở dữ liệu cũ khi khởi động.
