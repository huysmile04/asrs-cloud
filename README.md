# AS/RS Cloud - Real-Time MQTT System

Hệ thống lưu kho tự động với kết nối real-time giữa Dashboard và Raspberry Pi qua MQTT.

## 🌐 Truy cập Dashboard

**Link:** https://huysmile04.github.io/asrs-cloud/

**Đăng nhập:**
- Username: `admin`
- Password: `hcmute2026`

## 📋 Tổng quan

- **Dashboard**: Giao diện web để điều khiển và giám sát kho hàng
- **Raspberry Pi**: Bộ điều khiển phần cứng, gửi dữ liệu real-time
- **MQTT Broker**: HiveMQ Cloud làm trung gian truyền tin

## 🚀 Cài đặt và Chạy

### 1. Dashboard (Web Interface)

Mở file `index.html` hoặc `warehouse.html` trong trình duyệt web.

### 2. Raspberry Pi Logger

```bash
# Cài đặt dependencies
pip install paho-mqtt

# Chạy logger
python3 raspberry_logger.py
```

## 📡 MQTT Configuration

```javascript
// JavaScript (Dashboard)
const MQTT_BROKER = 'wss://5031841c1f8d4218bafa640220641d55.s1.eu.hivemq.cloud:8884/mqtt';
const MQTT_USERNAME = 'lhuy04';
const MQTT_PASSWORD = 'Hcmute2026';
```

```python
# Python (Raspberry Pi)
MQTT_BROKER = '5031841c1f8d4218bafa640220641d55.s1.eu.hivemq.cloud'
MQTT_PORT = 8884
MQTT_USERNAME = 'lhuy04'
MQTT_PASSWORD = 'Hcmute2026'
```

## 📋 MQTT Topics

| Topic | Direction | Description |
|-------|-----------|-------------|
| `warehouse/command` | Dashboard → Pi | Gửi lệnh điều khiển |
| `warehouse/status` | Pi → Dashboard | Trạng thái kho hàng |
| `warehouse/history` | Pi → Dashboard | Logs hoạt động real-time |
| `warehouse/history_init` | Pi → Dashboard | Dữ liệu lịch sử ban đầu |
| `warehouse/robot_state` | Pi → Dashboard | Trạng thái robot |
| `warehouse/ack` | Pi → Dashboard | Xác nhận hoàn thành |
| `warehouse/error` | Pi → Dashboard | Thông báo lỗi |

## 🔄 Real-Time Data Flow

### 1. Khi Dashboard kết nối:
- Tự động kết nối MQTT tới HiveMQ
- Subscribe các topics cần thiết
- Yêu cầu dữ liệu lịch sử ban đầu

### 2. Khi Raspberry Pi hoạt động:
- Gửi logs real-time mỗi khi có hoạt động IMPORT/EXPORT
- Cập nhật trạng thái robot
- Phản hồi lệnh từ dashboard

### 3. Logs tự động cập nhật:
- Mỗi log mới được thêm vào đầu bảng
- Highlight dòng mới trong 2 giây
- Tự động export Excel khi cần

## 📊 Lệnh MQTT

### Từ Dashboard:
```json
// IMPORT
{
  "action": "IMPORT",
  "slot_id": 3,
  "uid": "102077844"
}

// EXPORT
{
  "action": "EXPORT",
  "slot_id": 2,
  "uid": "584197470"
}

// Yêu cầu lịch sử
{
  "action": "GET_HISTORY"
}
```

### Từ Raspberry Pi:
```json
// Log hoạt động
{
  "time": "14:30:25",
  "slot": 3,
  "act": "IMPORT",
  "item": "Linh kiện điện tử"
}

// Xác nhận
"IMPORT thành công - Slot 3"

// Lỗi
"Lỗi kết nối PLC S7-1200"
```

## 🔧 Files Structure

```
asrs-cloud/
├── index.html          # Trang chủ
├── login.html          # Đăng nhập
├── dashboard.html      # Dashboard chính
├── warehouse.html      # Bản đồ kho (có MQTT)
├── logs.html          # Logs real-time (có MQTT)
├── raspberry_logger.py # Script Python cho Pi
└── README.md          # Tài liệu này
```

## 🛠️ Troubleshooting

### MQTT không kết nối:
1. Kiểm tra username/password
2. Kiểm tra kết nối internet
3. Kiểm tra firewall

### Logs không cập nhật:
1. Kiểm tra Raspberry Pi có chạy script không
2. Kiểm tra MQTT connection status
3. Xem console log trong browser

### Export Excel không hoạt động:
1. Đảm bảo thư viện XLSX đã load
2. Kiểm tra dữ liệu logs có tồn tại không

## 📞 Support

- **Author**: Student Huy - HCMUTE
- **Project**: AS/RS Graduation Project 2026
- **Contact**: bit.ly/asrs-cloud

---

*🚀 Real-time AS/RS System with MQTT Protocol*
