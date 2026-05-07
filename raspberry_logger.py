#!/usr/bin/env python3
"""
Raspberry Pi MQTT Logger for AS/RS System
Gửi dữ liệu logs real-time tới dashboard qua MQTT
"""

import paho.mqtt.client as mqtt
import json
import time
from datetime import datetime
import random

# ========== MQTT CONFIGURATION ==========
MQTT_BROKER = '5031841c1f8d4218bafa640220641d55.s1.eu.hivemq.cloud'
# FIX 1: Đổi Port thành 8883 cho môi trường Python (Native TCP TLS)
MQTT_PORT = 8883 
MQTT_USERNAME = 'lhuy04'
MQTT_PASSWORD = 'Hcmute2026'
CLIENT_ID = 'raspberry_pi_logger_' + str(random.randint(0, 9999))

# MQTT Topics
TOPICS = {
    'command': 'warehouse/command',        # Nhận lệnh từ dashboard
    'status': 'warehouse/status',          # Gửi trạng thái kho
    'history': 'warehouse/history',        # Gửi lịch sử hoạt động (Real-time)
    'history_init': 'warehouse/history_init', # Gửi toàn bộ lịch sử ban đầu
    'robot_state': 'warehouse/robot_state', # Gửi trạng thái robot
    'ack': 'warehouse/ack',               # Gửi xác nhận
    'error': 'warehouse/error'            # Gửi lỗi
}

# ========== BỘ NHỚ LƯU TRỮ LOGS ==========
# FIX 2: Tạo mảng để lưu trữ các logs đã diễn ra
history_logs = []

def save_to_history(log_entry):
    """Lưu log vào mảng, giữ tối đa 100 dòng mới nhất"""
    history_logs.append(log_entry)
    if len(history_logs) > 100:
        history_logs.pop(0) # Xóa phần tử cũ nhất nếu vượt quá 100

# ========== MQTT CLIENT SETUP ==========
client = mqtt.Client(CLIENT_ID)
client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
client.tls_set()  # Enable SSL/TLS

# ========== CALLBACK FUNCTIONS ==========
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Đã kết nối tới MQTT Broker (Port 8883)!")
        client.subscribe(TOPICS['command'])
        print(f"📡 Đã subscribe topic: {TOPICS['command']}")
    else:
        print(f"❌ Kết nối thất bại. Code: {rc}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        print(f"\n📨 Nhận lệnh từ Web: {payload}")
        handle_command(payload)
    except json.JSONDecodeError as e:
        print(f"❌ Lỗi parse JSON: {e}")

def on_disconnect(client, userdata, rc):
    print("⚠️ Mất kết nối MQTT")
    if rc != 0:
        print("❌ Kết nối bất ngờ. Đang thử kết nối lại...")

# ========== BUSINESS LOGIC ==========
def handle_command(command):
    action = command.get('action', '').upper()

    if action == 'GET_HISTORY':
        print("🔍 Web đang yêu cầu dữ liệu lịch sử...")
        send_initial_history()

    elif action == 'IMPORT':
        slot_id = command.get('slot_id')
        uid = command.get('uid')
        print(f"📥 Xử lý IMPORT: Slot {slot_id}, UID: {uid}")

        new_log = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "slot": slot_id,
            "act": "IMPORT",
            "item": f"UID: {uid}"
        }
        
        save_to_history(new_log) # FIX 2: Lưu vào bộ nhớ
        send_log_entry(new_log)
        send_ack(f"IMPORT thành công - Slot {slot_id}")

    elif action == 'EXPORT':
        slot_id = command.get('slot_id')
        uid = command.get('uid')
        print(f"📤 Xử lý EXPORT: Slot {slot_id}, UID: {uid}")

        new_log = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "slot": slot_id,
            "act": "EXPORT",
            "item": f"UID: {uid}"
        }

        save_to_history(new_log) # FIX 2: Lưu vào bộ nhớ
        send_log_entry(new_log)
        send_ack(f"EXPORT thành công - Slot {slot_id}")

    else:
        print(f"⚠️ Lệnh không xác định: {action}")

def send_initial_history():
    """Gửi toàn bộ lịch sử đang có trong bộ nhớ lên Web"""
    payload = json.dumps(history_logs)
    client.publish(TOPICS['history_init'], payload)
    print(f"📤 Đã gửi {len(history_logs)} dòng lịch sử lên Web")

def send_log_entry(log_entry):
    """Gửi 1 dòng log mới (Real-time)"""
    payload = json.dumps(log_entry)
    client.publish(TOPICS['history'], payload)
    print(f"📤 Đã bắn Log mới: {log_entry}")

def send_ack(message):
    client.publish(TOPICS['ack'], message)

def send_error(error_msg):
    client.publish(TOPICS['error'], error_msg)

def simulate_real_time_logs():
    """Mô phỏng Raspberry Pi đang tự động hoạt động"""
    while True:
        time.sleep(random.randint(15, 30)) 

        actions = ["IMPORT", "EXPORT"]
        slots = [1, 2, 3, 4, 5, 6, 7, 8, 9]
        items = ["Linh kiện điện tử", "Phụ tùng cơ khí", "Chip xử lý", "Cảm biến quang"]

        new_log = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "slot": random.choice(slots),
            "act": random.choice(actions),
            "item": random.choice(items)
        }

        save_to_history(new_log) # FIX 2: Lưu lại log mô phỏng
        send_log_entry(new_log)
        print(f"🎲 [TỰ ĐỘNG] Sinh log mô phỏng: {new_log}")

# ========== MAIN FUNCTION ==========
def main():
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    try:
        print("🔄 Đang kết nối tới HiveMQ Cloud...")
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()

        print("🚀 Raspberry Pi Logger đã sẵn sàng!")
        print("📡 Đang lắng nghe lệnh từ Web Dashboard...")
        print("🎲 Bắt đầu giả lập hệ thống chạy tự động sau 15-30s...")

        simulate_real_time_logs()

    except KeyboardInterrupt:
        print("\n🛑 Đang tắt hệ thống...")
        client.loop_stop()
        client.disconnect()
    except Exception as e:
        print(f"❌ Lỗi nghiêm trọng: {e}")

if __name__ == "__main__":
    main()