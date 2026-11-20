# Bổ sung dự báo pH và cảnh báo

Gói nâng cấp cho IoT_WiFi đang hoạt động. Python 3.10+, chỉ dùng thư viện có sẵn. Không phải nạp lại firmware nếu đang gửi context=water. Giữ nguyên API_KEY, IP, Wi-Fi và dây nối hiện tại.

## Cài vào bộ nhận đang chạy

1. Dừng server cũ bằng Ctrl+C. Sao lưu cả thư mục IoT_WiFi, đặc biệt server_config.json và data/readings.sqlite3.
2. Giải nén gói này. Chép server.py, forecast.py, monitor.html và alert_config.json vào thư mục IoT_WiFi cũ, thay server.py/monitor.html. Giữ nguyên server_config.json, thư mục data và firmware/config.h của bạn. Gói nâng cấp không chứa khóa hoặc dữ liệu người dùng.
3. Chạy `python server.py` trong thư mục IoT_WiFi. Mở http://127.0.0.1:8000, nhấn Ctrl+F5, nhập API_KEY cũ.
4. Nếu vẫn đo dung dịch chuẩn, trang hiện Đang đo dung dịch chuẩn — chưa dự báo. Khi chuyển sang mẫu nước, đổi MEASUREMENT_CONTEXT thành water trong config.h và nạp lại ESP32.
5. Giữ đo liên tục khoảng 16 phút để có 15 phút trọn vẹn. Trang hiển thị pH dự báo và thời điểm cần đối chiếu. Cần ít nhất 3 mẫu hợp lệ mỗi phút. Thiếu phút, khởi động lại ESP32, pH ngoài khoảng hiệu chuẩn hoặc dữ liệu cũ sẽ ngừng phát dự báo mới.

Nếu chọn chạy trong thư mục mới thay vì chép vào thư mục cũ, phải sao chép server_config.json và toàn bộ data từ thư mục cũ sau khi dừng server. Không chạy hai server cùng cổng 8000.

## Cảnh báo

Trong alert_config.json, mặc định hai ngưỡng đều null: chỉ báo trạng thái mất dữ liệu, pH lỗi/ngoài hiệu chuẩn, đang hiệu chuẩn hoặc chưa đủ lịch sử. Đây là cấu hình tránh tự gán ngưỡng sinh học chưa được xác nhận.

Để thử chức năng cảnh báo, sửa thành ví dụ:

```json
{"ph_low": 6.5, "ph_high": 8.5}
```

Đây chỉ là ngưỡng THỬ CHỨC NĂNG, không phải kết luận ngưỡng an toàn riêng cho cá rô phi đỏ. Dùng ngưỡng có căn cứ trong nghiên cứu trước khi vận hành thực tế. Sau mỗi lần sửa cấu hình cần khởi động lại server.

Trang sẽ báo riêng pH hiện tại vượt ngưỡng và pH dự báo sau 30 phút vượt ngưỡng. Một cảnh báo dự báo không chứng minh hệ thống sẽ luôn báo trước được 30 phút. Phương pháp trung bình có thể phản ứng chậm trước thay đổi đột ngột.

Cảnh báo hiển thị trên trang. Tích Âm thanh cảnh báo để bật tiếng bíp khi trạng thái bất thường thay đổi; cần mở trang, trình duyệt có thể hạn chế âm thanh ở tab nền. Không có SMS/email/Telegram. Điện thoại cùng mạng có thể mở http://IP_MAY_TINH:8000 và nhập khóa. Chưa hỗ trợ từ Internet ngoài nhà.

## Cách dự báo và đánh giá

- Dùng đúng phương pháp pH đã chọn: mean15 (trung bình trượt), không gọi là Random Forest. Không cần tải joblib cho phương pháp này vì không có tham số cần huấn luyện.
- Gộp số đo water có ph_status=ok bằng trung vị theo phút UTC của thời gian máy tính nhận. Mỗi phút ít nhất 3 mẫu; dữ liệu nhiệt độ thiếu không làm mất dữ liệu pH.
- Chỉ dùng phút đã kết thúc. Phút 20:00:00–20:00:59 được ghi nhãn kết thúc 20:01:00. Dự báo tại nhãn t là trung bình 15 phút kết thúc tại t, dành cho phút kết thúc t+30 phút. Dự báo phát vài giây sau nhãn t do chu kỳ nhận/xử lý. Đây là dự báo theo lưới phút, không phải một số đo tức thời ở đúng giây.
- Gating đủ 15 phút và trạng thái hiệu chuẩn là yêu cầu chất lượng khi chạy thật, chặt hơn pipeline offline. Chưa có đồng bộ thời gian ESP32; thời gian nhận chỉ xấp xỉ thời gian đo.
- Dữ liệu của từng device_id/boot_id riêng biệt. Không nối lịch sử giữa các lần khởi động. Dữ liệu calibration bị loại. Bản tin trùng không lưu lặp.
- Dự báo được lưu cố định vào bảng forecasts trong SQLite (không sửa khi có dữ liệu tương lai). Tiến trình nền chạy mỗi 5 giây, không cần mở trang để ghi dự báo. Không tạo lại dự báo cho các phút lịch sử đã bỏ lỡ khi server tắt.
- Sau khi có phút t+30 hoàn chỉnh và đủ số đo hợp lệ trong cùng phiên thiết bị, ghi giá trị thực vào dự báo tương ứng. Trang hiển thị số cặp, MAE và MAE của cách giữ nguyên giá trị phút hiện tại. Thiếu số đo ở thời điểm đích sẽ giữ dự báo chưa đối chiếu, không nội suy.
- Dự báo nhiệt độ chưa có. Hệ thống ghi nhận nhiệt độ null đúng như thiết bị gửi. Không sử dụng số đo giả.
- Nhật ký chuyển trạng thái lưu trong alert_events. Trang hiện 20 sự kiện gần nhất. Các lỗi/mất dữ liệu không được gắn nhãn “an toàn”. Mỗi lần khởi động server có thể ghi lại trạng thái đang có.
- Bộ xử lý lấy tối đa 20.000 mẫu gần nhất cho mỗi thiết bị. Với nhịp gửi khoảng 5 giây, đủ để đối chiếu dự báo sau 30 phút; không dành cho phục hồi đánh giá sau nhiều ngày mất dữ liệu.

## Kiểm tra toàn hệ thống ở nhà

1. Kiểm tra CSV và thời gian: chạy `python check_csv.py "C:\duong_dan\water_readings.csv"`. Sao chép check_csv.py vào thư mục đang chạy nếu cần. Kết quả cho biết loại mẫu, khoảng thời gian, khoảng ngắt, số trùng và dải pH. Khoảng thời gian thống kê là tổng CSV, không tự khẳng định nước được đo liên tục nếu có nhiều phiên.
2. Gửi water liên tục; trang đếm phút từ 0 đến 15 và xuất dự báo. Không cần chờ thêm 30 phút mới thấy dự báo đầu tiên.
3. Giữ đo thêm 30–35 phút sau dự báo đầu tiên: số cặp đối chiếu phải tăng. Tổng buổi thử nên ít nhất 50–60 phút. Tải cả số đo và dự báo CSV.
4. Thử cảnh báo không cần làm thay đổi hóa học nước: ghi lại ngưỡng thực đang dùng, đặt tạm một giới hạn trên thấp hơn pH hiện tại (nhưng lớn hơn giới hạn dưới), khởi động server; trang phải hiện vượt ngưỡng. Sau đó khôi phục cấu hình. Ghi rõ giai đoạn thử này trong nhật ký thí nghiệm.
5. Tắt nguồn ESP32 hơn 20 giây: trang báo mất dữ liệu. Bật lại: phiên mới tích lũy lịch sử từ đầu. Không đánh giá độ chính xác qua khoảng mất dữ liệu này.
6. Đo lại dung dịch chuẩn thì nạp context=calibration: trang không dự báo/cảnh báo ngưỡng nước từ mẫu chuẩn. Đổi lại water khi đo nước thật.

Chỉ ghi “thử toàn hệ thống thành công” sau khi thực hiện trên thiết bị và lưu kết quả. Phần nhận Wi-Fi đã được bạn xác nhận trước đây; phần dự báo/cảnh báo mới chưa được chạy trên thiết bị của bạn. Thử tại nhà một giờ chưa chứng minh độ chính xác hoặc hiệu quả nuôi cá ngoài ao.

## Kiểm thử phần mềm đã chạy

`python -m unittest test_server.py test_forecast.py`

11 kiểm thử đã qua trên môi trường phát triển: HTTP nhận/lưu/CSV/null; chống trùng/phiên mới; khóa sai; đầu vào lỗi; nhận nhiệt độ hoặc thiếu cảm biến; trang/health; dự báo đúng mốc +30 phút; chờ đủ lịch sử/khoảng ngắt/reset; loại calibration/ngoài hiệu chuẩn/mất dữ liệu; ngưỡng bật/tắt; lưu dự báo rồi đối chiếu tương lai không ghi đè dự báo.

Kiểm thử dùng dữ liệu mô phỏng trong thư mục tạm, không trộn vào dữ liệu thật. Không tuyên bố đã kiểm tra giao diện bằng trình duyệt hay thử trên mạch.

## Tệp CSV bạn gửi

Tệp được hiển thị là đính kèm nhưng không tồn tại tại đường dẫn được cung cấp trong môi trường đọc hiện tại. Vì vậy chưa kiểm tra được số dòng, nhãn water/calibration, thời gian hay sai số của CSV đó. Không có số liệu thực nghiệm nào được suy đoán từ tên tệp. Chạy check_csv.py tại máy bạn và gửi phần kết quả văn bản để tiếp tục kiểm tra mà không cần gửi tệp lại nhiều lần.
