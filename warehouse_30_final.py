import os, time, json, ssl, snap7, psutil
import threading
from snap7.util import *
import paho.mqtt.client as mqtt
from datetime import datetime
from mfrc522 import SimpleMFRC522
import RPi.GPIO as GPIO

# --- CẤU HÌNH THƯ MỤC & FILE ---
DATA_DIR  = "/home/lhuy/data"
DB_PATH   = os.path.join(DATA_DIR, "warehouse_9.json")
HIST_PATH = os.path.join(DATA_DIR, "history_9.json")
GPIO.setwarnings(False)
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)

# --- CẤU HÌNH PLC S7-1200 ---
PLC_IP       = "192.168.0.1"
DB_NUMBER    = 14
TARGET_ADDR  = 0    # Offset 0 (Int - 2 bytes): slot index 0-8
CONTROL_BYTE = 2    # Byte 2: bit 0 = BUSY, bit 1 = DONE
BUSY_BIT     = 0
DONE_BIT     = 1

reader   = SimpleMFRC522()
client   = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
plc      = snap7.client.Client()
plc_lock = threading.Lock()

sys_state = {
    "plc_connected": False,
    "is_busy":       False,
    "current_slot":  "N/A"
}

# ─── JSON HELPERS ─────────────────────────────────────────────────────────────

def load_json(path, default_data):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, 'w') as f: json.dump(default_data, f)
        return default_data
    with open(path, 'r') as f: return json.load(f)

def save_json(path, data):
    with open(path, 'w') as f: json.dump(data, f, indent=4)
    os.sync()

def log_event(sid, act, item_name, uid):
    """Ghi lịch sử và publish lên warehouse/history (cho logs.html & report.html)."""
    hist    = load_json(HIST_PATH, [])
    new_log = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "slot": str(sid),     # logs.html: raw.slot
        "act":  act,          # logs.html: raw.act
        "item": item_name,    # logs.html: raw.item
        "uid":  uid
    }
    hist.append(new_log)
    save_json(HIST_PATH, hist[-100:])
    client.publish("warehouse/history", json.dumps(new_log))

# ─── GIAO TIẾP PLC ────────────────────────────────────────────────────────────

def write_plc_bit(byte_offset, bit_offset, value):
    with plc_lock:
        try:
            data = plc.db_read(DB_NUMBER, byte_offset, 1)
            set_bool(data, 0, bit_offset, value)
            plc.db_write(DB_NUMBER, byte_offset, data)
        except Exception as e:
            print(f"Lỗi ghi Bit PLC: {e}")

def write_plc_slot(slot_index):
    with plc_lock:
        try:
            data = bytearray(2)
            set_int(data, 0, int(slot_index))
            plc.db_write(DB_NUMBER, TARGET_ADDR, data)
        except Exception as e:
            print(f"Lỗi ghi Slot PLC: {e}")

# ─── PUBLISH CHO TOOLS.HTML ───────────────────────────────────────────────────

def publish_system_info():
    """
    Publish CPU, RAM, nhiệt độ → tools.html nhận topic warehouse/system_info.
    Web expect: { "cpu": float, "ram": float, "temp": float }
    """
    try:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
        try:
            with open('/sys/class/thermal/thermal_zone0/temp') as f:
                temp = int(f.read().strip()) / 1000.0
        except:
            temp = 0.0
        client.publish("warehouse/system_info", json.dumps({
            "cpu":  round(cpu,  1),
            "ram":  round(ram,  1),
            "temp": round(temp, 1)
        }))
    except Exception as e:
        print(f"Lỗi đọc system info: {e}")

def publish_device_status():
    """
    Publish trạng thái PLC & RFID → tools.html nhận topic warehouse/status.
    Web expect: { "plc": "connected"|"disconnected", "rfid": "ready"|"error" }
    """
    client.publish("warehouse/status", json.dumps({
        "plc":  "connected" if sys_state["plc_connected"] else "disconnected",
        "rfid": "ready"
    }))

def publish_motor_data():
    """
    Publish trạng thái motor → tools.html nhận topic warehouse/motor_data.
    m1 (băng tải), m2 (Robot X-Y), m3 (trục nâng), m4 (xoay RFID)
    """
    running = sys_state["is_busy"]
    slot    = sys_state["current_slot"]   # "N/A" hoặc "1"-"9"

    try:
        slot_num = int(slot)
        slot_label = f"Slot {slot_num}"
        level      = str(((slot_num - 1) // 3) + 1)   # slot 1-3→L1, 4-6→L2, 7-9→L3
    except (ValueError, TypeError):
        slot_label = "--"
        level      = "--"

    client.publish("warehouse/motor_data", json.dumps({
        "m1": {
            "speed":  150 if running else 0,
            "power":  round(12.5 if running else 0.0, 1),
            "status": "running" if running else "idle"
        },
        "m2": {
            "slot":   slot_label,
            "status": "running" if running else "idle"
        },
        "m3": {
            "level":  level,
            "status": "running" if running else "idle"
        },
        "m4": {
            "angle":  90 if running else 0,
            "temp":   35,
            "status": "running" if running else "idle"
        }
    }))

# ─── LUỒNG MONITOR CHÍNH ──────────────────────────────────────────────────────

def monitor_logic():
    global sys_state
    last_publish = 0

    while True:
        # Kiểm tra / tự kết nối lại PLC
        if not plc.get_connected():
            sys_state["plc_connected"] = False
            try: plc.connect(PLC_IP, 0, 1)
            except: pass
        else:
            sys_state["plc_connected"] = True
            try:
                with plc_lock:
                    ctrl = plc.db_read(DB_NUMBER, CONTROL_BYTE, 1)
                is_busy = get_bool(ctrl, 0, BUSY_BIT)
                is_done = get_bool(ctrl, 0, DONE_BIT)
                sys_state["is_busy"] = is_busy

                if is_done and is_busy:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] PLC báo DONE! Tắt Busy...")
                    write_plc_bit(CONTROL_BYTE, BUSY_BIT, False)
                    write_plc_bit(CONTROL_BYTE, DONE_BIT, False)
                    sys_state["is_busy"]      = False
                    sys_state["current_slot"] = "N/A"
            except:
                pass

        # Publish tất cả thông tin hệ thống mỗi 2 giây
        if time.time() - last_publish > 2:
            publish_system_info()
            publish_device_status()
            publish_motor_data()
            last_publish = time.time()

        time.sleep(0.2)

# ─── XỬ LÝ IMPORT / EXPORT ────────────────────────────────────────────────────

def handle_import(sid, uid_from_web=""):
    global sys_state
    if sys_state["is_busy"]:
        client.publish("warehouse/error", "Hệ thống đang bận, vui lòng chờ!")
        return

    # Thông báo đang chờ RFID
    client.publish("warehouse/robot_state", json.dumps({
        "state":   "WAITING_RFID",
        "slot":    str(sid),
        "message": f"Chờ quét RFID cho ô {sid}"
    }))

    # Dùng UID từ Web nếu có, không thì đọc thẻ vật lý
    if uid_from_web and str(uid_from_web).strip() not in ("", "N/A"):
        tag_uid = str(uid_from_web).strip()
    else:
        rfid_id, _ = reader.read()
        tag_uid    = str(rfid_id)

    # Ra lệnh PLC
    write_plc_slot(int(sid) - 1)         # slot 1-9 → index 0-8
    write_plc_bit(CONTROL_BYTE, BUSY_BIT, True)
    sys_state["is_busy"]      = True
    sys_state["current_slot"] = str(sid)
    publish_device_status()
    publish_motor_data()

    # Lưu DB & ghi lịch sử
    db = load_json(DB_PATH, {})
    db[f"slot_{sid}"] = {
        "id":        sid,
        "status":    "Occupied",
        "uid":       tag_uid,
        "item_name": "Linh kiện",
        "time":      datetime.now().strftime("%H:%M:%S")
    }
    save_json(DB_PATH, db)
    log_event(sid, "IMPORT", "Linh kiện", tag_uid)

    # Xác nhận cho warehouse.html
    client.publish("warehouse/ack", f"IMPORT thành công! Slot {sid} — UID: {tag_uid}")

def handle_export(sid):
    global sys_state
    if sys_state["is_busy"]:
        client.publish("warehouse/error", "Hệ thống đang bận, vui lòng chờ!")
        return

    db        = load_json(DB_PATH, {})
    item_info = db.get(f"slot_{sid}", {})
    tag_uid   = item_info.get("uid", "N/A")

    # Ra lệnh PLC
    write_plc_slot(int(sid) - 1)
    write_plc_bit(CONTROL_BYTE, BUSY_BIT, True)
    sys_state["is_busy"]      = True
    sys_state["current_slot"] = str(sid)
    publish_device_status()
    publish_motor_data()

    # Xóa DB & ghi lịch sử
    db[f"slot_{sid}"] = {"id": sid, "status": "Available"}
    save_json(DB_PATH, db)
    log_event(sid, "EXPORT", "Xuất kho", tag_uid)

    # Xác nhận cho warehouse.html
    client.publish("warehouse/ack", f"EXPORT thành công! Slot {sid} — UID: {tag_uid}")

# ─── XỬ LÝ LỆNH TỪ WEB (warehouse/command) ───────────────────────────────────

def on_message(client, userdata, msg):
    try:
        cmd = json.loads(msg.payload.decode('utf-8'))
        act = cmd.get("action", "").upper()

        if act == "EMERGENCY_RESET":
            write_plc_bit(CONTROL_BYTE, BUSY_BIT, False)
            write_plc_bit(CONTROL_BYTE, DONE_BIT, False)
            write_plc_slot(-1)
            sys_state["is_busy"]      = False
            sys_state["current_slot"] = "N/A"
            client.publish("warehouse/ack", "Đã RESET hệ thống!")
            publish_device_status()
            publish_motor_data()

        elif act == "IMPORT":
            threading.Thread(
                target=handle_import,
                args=(cmd.get("slot_id"), cmd.get("uid", "")),
                daemon=True
            ).start()

        elif act == "EXPORT":
            threading.Thread(
                target=handle_export,
                args=(cmd.get("slot_id"),),
                daemon=True
            ).start()

        elif act == "GET_STATUS":
            # Trả về trạng thái PLC & RFID cho tools.html
            publish_device_status()

        elif act == "GET_HISTORY":
            # Trả toàn bộ lịch sử cho logs.html & report.html
            client.publish("warehouse/history_init", json.dumps(load_json(HIST_PATH, [])))

    except Exception as e:
        print(f"Lỗi phân tích lệnh MQTT: {e}")

# ─── KHỞI TẠO & MAIN ──────────────────────────────────────────────────────────

default_db = {f"slot_{i}": {"id": i, "status": "Available"} for i in range(1, 10)}
if not os.path.exists(DB_PATH): save_json(DB_PATH, default_db)

print("--- KHỞI ĐỘNG HỆ THỐNG AS/RS (9 Ô) ---")
threading.Thread(target=monitor_logic, daemon=True).start()

client.on_disconnect = lambda c, u, rc, p=None: print(f"[{datetime.now().strftime('%H:%M:%S')}] MQTT ngắt kết nối (rc={rc}), đang reconnect...")
client.on_connect   = lambda c, u, f, rc, p=None: print(f"[{datetime.now().strftime('%H:%M:%S')}] MQTT kết nối thành công!")
client.reconnect_delay_set(min_delay=2, max_delay=30)
client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
client.username_pw_set("lhuy04", "Hcmute2026")
client.on_message = on_message
client.connect("5031841c1f8d4218bafa640220641d55.s1.eu.hivemq.cloud", 8883)
client.subscribe("warehouse/command")

try:
    client.loop_forever()
finally:
    GPIO.cleanup()
