#!/usr/bin/env python3
"""
=============================================================================
  AS/RS MASTER CONTROLLER  —  LAPTOP VERSION (Windows/Linux/macOS)
  Chạy trực tiếp trên laptop trước khi nạp vào Raspberry Pi.
  Không cần: RPi.GPIO, mfrc522, os.sync()
  Cần cài đặt:
      pip install paho-mqtt snap7 psutil
  Nếu chưa có PLC thực, đặt SIMULATE_PLC = True để test offline.
=============================================================================
"""

import os, sys, time, json, ssl, threading, queue
from datetime import datetime
import psutil
import paho.mqtt.client as mqtt

# ── Fix encoding UTF-8 cho Windows console ────────────────────────────────────
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─── Kiểm tra snap7 ──────────────────────────────────────────────────────────
try:
    import snap7
    from snap7.util import set_bool, get_bool, set_int
    SNAP7_OK = True
except ImportError:
    SNAP7_OK = False
    print("⚠️  snap7 chưa được cài. Chạy: pip install python-snap7")
    print("    PLC sẽ ở chế độ SIMULATE tự động.\n")

# ══════════════════════════════════════════════════════════════════════════════
#  CẤU HÌNH — Chỉnh sửa theo môi trường của bạn
# ══════════════════════════════════════════════════════════════════════════════
# ─────────────────────────────────────────────────────────────────────────────
#  OFFLINE_MODE = True  → Không kết nối PLC thực, chỉ in lệnh ra console.
#                          Dùng khi chưa có điện / chưa có PLC.
#  OFFLINE_MODE = False → Dùng PLC thực (SIMULATE_PLC sẽ tự quyết dựa theo snap7).
# ─────────────────────────────────────────────────────────────────────────────
OFFLINE_MODE  = True           # ← ĐỔI THÀNH False KHI CÓ PLC THỰC
SIMULATE_PLC  = OFFLINE_MODE or (not SNAP7_OK)   # True = giả lập PLC

PLC_IP       = "192.168.0.1"
DB_NUMBER    = 14
TARGET_ADDR  = 0    # Int (2 bytes): slot index 0-8
CONTROL_BYTE = 2    # byte: bit0=BUSY, bit1=DONE
BUSY_BIT, DONE_BIT = 0, 1

MQTT_HOST = "5031841c1f8d4218bafa640220641d55.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "lhuy04"
MQTT_PASS = "Hcmute2026"

# Thư mục lưu dữ liệu (Windows: cùng thư mục script)
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "data")
DB_PATH   = os.path.join(DATA_DIR, "warehouse_9.json")
HIST_PATH = os.path.join(DATA_DIR, "history_9.json")
LOG_PATH  = os.path.join(DATA_DIR, "plc_commands.log")   # ← Log lệnh PLC

os.makedirs(DATA_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
#  TRẠNG THÁI HỆ THỐNG
# ══════════════════════════════════════════════════════════════════════════════
sys_state = {
    "plc_connected":      False,
    "is_busy":            False,
    "current_slot":       "N/A",
    "pending_action":     None,
    "pending_slot":       None,
    "pending_uid":        None,
    "pending_item":       None,
    "maintenance_mode":   False,
    "maintenance_ts":     "",
    # Giả lập PLC
    "_sim_busy":          False,
    "_sim_done":          False,
    "_sim_timer":         0.0,
}

# Hàng đợi log in ra console
log_queue = queue.Queue()

# ══════════════════════════════════════════════════════════════════════════════
#  LOGGER — In màu + ghi file
# ══════════════════════════════════════════════════════════════════════════════
RESET  = "\033[0m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
MAGENTA= "\033[95m"
BLUE   = "\033[94m"
GRAY   = "\033[90m"
BOLD   = "\033[1m"

def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def log(msg, color=RESET, tag="INFO"):
    line = f"[{_ts()}] [{tag}] {msg}"
    print(f"{color}{line}{RESET}")
    log_queue.put(line)

def log_plc_cmd(direction: str, description: str, payload: dict):
    """
    Ghi log lệnh truyền giữa RPi ↔ PLC.
    direction: "→ PLC" hoặc "← PLC"
    """
    ts  = _ts()
    arrow = "▶" if "→" in direction else "◀"
    line  = (
        f"[{ts}] [{arrow} PLC] "
        f"{direction} | {description} | "
        f"Payload: {json.dumps(payload, ensure_ascii=False)}"
    )
    print(f"{MAGENTA}{BOLD}{line}{RESET}")
    # Ghi vào file log riêng
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"{RED}[LOG FILE ERROR] {e}{RESET}")

def _log_writer():
    """Thread phụ ghi log vào file chung (không block main)."""
    pass  # log_queue đã xử lý inline ở log_plc_cmd

# ══════════════════════════════════════════════════════════════════════════════
#  JSON HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def load_json(path, default):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        save_json(path, default)
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def log_event(sid, act, item, uid):
    hist = load_json(HIST_PATH, [])
    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "slot": str(sid),
        "act":  act,
        "item": item,
        "uid":  uid,
    }
    hist.append(entry)
    save_json(HIST_PATH, hist[-200:])
    try:
        mqtt_client.publish("warehouse/history", json.dumps(entry, ensure_ascii=False))
    except Exception:
        pass
    log(f"EVENT: {act} | Slot {sid} | {item} | UID={uid}", GREEN, "EVENT")

# ══════════════════════════════════════════════════════════════════════════════
#  PLC — snap7 hoặc SIMULATE
# ══════════════════════════════════════════════════════════════════════════════
if SNAP7_OK:
    plc      = snap7.client.Client()
    plc_lock = threading.Lock()
else:
    plc      = None
    plc_lock = threading.Lock()

def _plc_connect():
    if SIMULATE_PLC:  # bao gồm cả OFFLINE_MODE
        sys_state["plc_connected"] = True
        if OFFLINE_MODE:
            log("OFFLINE MODE — PLC giả lập (không kết nối thực)", YELLOW, "PLC")
        return
    try:
        plc.connect(PLC_IP, 0, 1)
        sys_state["plc_connected"] = plc.get_connected()
    except Exception as e:
        sys_state["plc_connected"] = False
        log(f"Kết nối PLC thất bại: {e}", RED, "PLC")

def write_plc_bit(byte_off, bit_off, value):
    payload = {"byte": byte_off, "bit": bit_off, "value": value}
    direction = "→ PLC WRITE BIT"
    desc = f"DB{DB_NUMBER}.B{byte_off}.{bit_off} = {'1' if value else '0'}"
    log_plc_cmd(direction, desc, payload)

    if SIMULATE_PLC:  # OFFLINE_MODE cũng vào đây
        if byte_off == CONTROL_BYTE:
            if bit_off == BUSY_BIT:
                sys_state["_sim_busy"] = value
            elif bit_off == DONE_BIT:
                sys_state["_sim_done"] = value
        return  # ← không gửi TCP
    with plc_lock:
        try:
            data = plc.db_read(DB_NUMBER, byte_off, 1)
            set_bool(data, 0, bit_off, value)
            plc.db_write(DB_NUMBER, byte_off, data)
        except Exception as e:
            log(f"PLC bit write error: {e}", RED, "PLC")

def write_plc_slot(slot_index):
    payload = {"db": DB_NUMBER, "addr": TARGET_ADDR, "slot_index": slot_index}
    desc = f"DB{DB_NUMBER}.W{TARGET_ADDR} = {slot_index}  (slot_index 0-based)"
    log_plc_cmd("→ PLC WRITE INT", desc, payload)

    if SIMULATE_PLC:  # OFFLINE_MODE cũng vào đây
        mode_tag = "OFFLINE" if OFFLINE_MODE else "SIM"
        log(f"[{mode_tag}] Target slot set to {slot_index}", CYAN, mode_tag)
        return  # ← không gửi TCP
    with plc_lock:
        try:
            data = bytearray(2)
            set_int(data, 0, int(slot_index))
            plc.db_write(DB_NUMBER, TARGET_ADDR, data)
        except Exception as e:
            log(f"PLC slot write error: {e}", RED, "PLC")

def read_plc_ctrl():
    """Đọc control byte từ PLC. Trả về bytearray(1)."""
    if SIMULATE_PLC:
        b = bytearray(1)
        if sys_state["_sim_busy"]: b[0] |= (1 << BUSY_BIT)
        if sys_state["_sim_done"]: b[0] |= (1 << DONE_BIT)
        return b
    with plc_lock:
        try:
            return plc.db_read(DB_NUMBER, CONTROL_BYTE, 1)
        except Exception:
            return None

def plc_start(slot_id):
    """Gửi lệnh START tới PLC: set slot + set BUSY bit."""
    log(f"PLC START: slot_id={slot_id} → slot_index={slot_id - 1}", YELLOW, "PLC")
    write_plc_slot(slot_id - 1)
    write_plc_bit(CONTROL_BYTE, BUSY_BIT, True)
    sys_state["is_busy"]      = True
    sys_state["current_slot"] = str(slot_id)

    # Giả lập: PLC tự "hoàn thành" sau 5 giây
    if SIMULATE_PLC:
        sys_state["_sim_timer"] = time.time() + 5.0
        log("[SIM] PLC sẽ báo DONE sau 5 giây...", CYAN, "SIM")

def _do_emergency_reset():
    """Reset khẩn cấp PLC và trạng thái hệ thống — dùng chung cho EMERGENCY_RESET, CANCEL."""
    write_plc_bit(CONTROL_BYTE, BUSY_BIT, False)
    write_plc_bit(CONTROL_BYTE, DONE_BIT, False)
    write_plc_slot(-1)
    for k in ("_sim_busy", "_sim_done"):
        sys_state[k] = False
    sys_state["_sim_timer"] = 0.0
    sys_state.update({
        "is_busy":        False,
        "current_slot":   "N/A",
        "pending_action": None,
        "pending_slot":   None,
        "pending_uid":    None,
        "pending_item":   None,
    })
    _pub("warehouse/robot_state",
         {"state": "IDLE", "slot": "N/A", "message": "RESET / CANCELLED"}, retain=True)
    _pub("warehouse/ack", {"action": "RESET"})
    publish_device_status()
    publish_motor_data()
    log("Emergency reset hoàn thành.", YELLOW, "RESET")

# ══════════════════════════════════════════════════════════════════════════════
#  PUBLISH HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _pub(topic, payload_dict, retain=False):
    try:
        mqtt_client.publish(topic, json.dumps(payload_dict, ensure_ascii=False), retain=retain)
    except Exception:
        pass

def publish_system_info():
    try:
        cpu  = psutil.cpu_percent(interval=None)
        ram  = psutil.virtual_memory().percent
        # Nhiệt độ: RPi có file thermal, laptop dùng psutil (nếu hỗ trợ)
        try:
            temps = psutil.sensors_temperatures()
            temp  = list(temps.values())[0][0].current if temps else 0.0
        except Exception:
            try:
                with open("/sys/class/thermal/thermal_zone0/temp") as f:
                    temp = int(f.read().strip()) / 1000.0
            except Exception:
                temp = 0.0
        _pub("warehouse/system_info", {
            "cpu":  round(cpu, 1),
            "ram":  round(ram, 1),
            "temp": round(temp, 1),
        })
    except Exception as e:
        log(f"system_info error: {e}", RED, "SYS")

def publish_device_status():
    _pub("warehouse/status", {
        "plc":  "connected" if sys_state["plc_connected"] else "disconnected",
        "rfid": "simulated" if SIMULATE_PLC else "ready",
    })

def publish_motor_data():
    running = sys_state["is_busy"]
    try:
        n = int(sys_state["current_slot"])
        slot_label = f"Slot {n}"
    except (ValueError, TypeError):
        slot_label = "--"
    st = "running" if running else "idle"
    _pub("warehouse/motor_data", {
        "m1": {"speed": 150 if running else 0, "status": st},
        "m2": {"slot": slot_label, "status": st},
        "m3": {"slot": slot_label, "status": st},
        "m4": {"conveyor": "on" if running else "off", "status": st},
    })

def publish_maintenance(active: bool):
    ts = datetime.now().strftime("%H:%M:%S %d/%m/%Y")
    payload = {"active": active, "timestamp": ts}
    # Retain=True để message tồn tại sau reconnect;
    # Khi active=False (AUTO) vẫn retain để ghi đè retained cũ
    try:
        mqtt_client.publish("warehouse/maintenance_mode",
                            json.dumps(payload, ensure_ascii=False),
                            retain=True)
    except Exception:
        pass
    sys_state["maintenance_mode"] = active
    sys_state["maintenance_ts"]   = ts if active else ""
    status = "BẬT" if active else "TẮT"
    log(f"MAINTENANCE MODE {status}", YELLOW if active else GREEN, "MAINT")

# ══════════════════════════════════════════════════════════════════════════════
#  MONITOR LOOP (thread)
# ══════════════════════════════════════════════════════════════════════════════
def monitor_logic():
    last_pub = 0.0
    log("Monitor thread khởi động.", CYAN, "MON")
    while True:
        # ── Kết nối PLC ────────────────────────────────────────────────────
        if not SIMULATE_PLC:  # chỉ thử reconnect khi KHÔNG phải offline/sim
            connected = plc.get_connected() if SNAP7_OK else False
            if not connected:
                sys_state["plc_connected"] = False
                log("PLC mất kết nối, đang reconnect...", YELLOW, "PLC")
                _plc_connect()
            else:
                sys_state["plc_connected"] = True

        # ── Giả lập DONE bit sau timer ─────────────────────────────────────
        if SIMULATE_PLC and sys_state["_sim_timer"] > 0:
            if time.time() >= sys_state["_sim_timer"]:
                sys_state["_sim_done"]  = True
                sys_state["_sim_timer"] = 0.0
                log("[SIM] PLC gửi DONE bit!", CYAN, "SIM")

        # ── Đọc PLC control byte ───────────────────────────────────────────
        ctrl = read_plc_ctrl()
        if ctrl is not None:
            busy_bit_val = bool(ctrl[0] & (1 << BUSY_BIT))
            done_bit_val = bool(ctrl[0] & (1 << DONE_BIT))

            if SIMULATE_PLC:
                # Log đọc PLC (giả lập) mỗi khi có thay đổi
                pass
            else:
                log_plc_cmd(
                    "← PLC READ",
                    f"DB{DB_NUMBER}.B{CONTROL_BYTE}: BUSY={int(busy_bit_val)} DONE={int(done_bit_val)}",
                    {"ctrl_byte": ctrl[0], "BUSY": busy_bit_val, "DONE": done_bit_val},
                )

            sys_state["is_busy"] = busy_bit_val

            if done_bit_val and busy_bit_val:
                log("DONE bit nhận được! Đang reset PLC...", GREEN, "PLC")
                write_plc_bit(CONTROL_BYTE, BUSY_BIT, False)
                write_plc_bit(CONTROL_BYTE, DONE_BIT, False)
                sys_state["is_busy"]      = False
                sys_state["current_slot"] = "N/A"

                p_action = sys_state.get("pending_action")
                p_slot   = sys_state.get("pending_slot")
                p_uid    = sys_state.get("pending_uid")
                p_item   = sys_state.get("pending_item")
                for k in ("pending_action","pending_slot","pending_uid","pending_item"):
                    sys_state[k] = None

                if p_action:
                    _pub("warehouse/ack", {"action": p_action, "slot": p_slot,
                                           "uid": p_uid, "item": p_item})
                    log(f"ACK gửi: {p_action} | Slot {p_slot}", GREEN, "ACK")

                db = load_json(DB_PATH, {})
                _pub("warehouse/slot_data", db, retain=True)
                _pub("warehouse/robot_state",
                     {"state": "IDLE", "slot": "N/A", "message": "Ready"}, retain=True)

        # ── Publish định kỳ mỗi 2 giây ───────────────────────────────────
        if time.time() - last_pub > 2:
            publish_system_info()
            publish_device_status()
            publish_motor_data()
            last_pub = time.time()

        time.sleep(0.2)

# ══════════════════════════════════════════════════════════════════════════════
#  IMPORT / EXPORT HANDLERS
# ══════════════════════════════════════════════════════════════════════════════
def find_nearest_slot(db):
    for i in range(1, 10):
        if db.get(f"slot_{i}", {}).get("status", "Available") == "Available":
            return i
    return None

def handle_import(uid_from_web="", item_from_web=""):
    """Luồng IMPORT với bước chờ RFID:
    1. Tìm slot trống
    2. Publish WAITING_RFID → Web hiện dialog chờ quét
    3. Giả lập đọc RFID (hoặc dùng UID từ web)
    4. Publish rfid_result {success, uid, message}
    5. Nếu thành công → MOVING → PLC → ACK
       Nếu thất bại → IDLE + error
    """
    if sys_state["is_busy"]:
        _pub("warehouse/error", {"message": "System busy"})
        log("IMPORT bị từ chối: hệ thống bận", YELLOW, "CMD")
        return

    db      = load_json(DB_PATH, {})
    slot_id = find_nearest_slot(db)
    if slot_id is None:
        _pub("warehouse/error", {"message": "Warehouse full!"})
        log("IMPORT bị từ chối: kho đầy", RED, "CMD")
        return

    log(f"IMPORT → Slot {slot_id} | UID={uid_from_web} | Item={item_from_web}", GREEN, "CMD")

    # ── BƯỚC 1: Thông báo đang chờ quét RFID ──────────────────────────────
    sys_state["is_busy"]      = True
    sys_state["current_slot"] = str(slot_id)
    _pub("warehouse/robot_state",
         {"state": "WAITING_RFID", "slot": str(slot_id), "message": "Đặt thẻ RFID vào đầu đọc"}, retain=True)

    # ── BƯỚC 2: Giả lập thời gian chờ quét RFID (2 giây) ─────────────────
    # Trên Raspberry Pi thực, đây là nơi đọc mfrc522
    time.sleep(2.0)

    # Kiểm tra nếu bị hủy trong khi chờ
    if not sys_state["is_busy"]:
        log("IMPORT bị hủy trong khi chờ RFID", YELLOW, "CMD")
        return

    # ── BƯỚC 3: Xử lý kết quả RFID ────────────────────────────────────────
    # Laptop mode: UID từ web = RFID tag. Nếu trống → giả lập scan thành công với SIM_UID
    if uid_from_web and str(uid_from_web).strip() and str(uid_from_web).strip() != "N/A":
        tag_uid  = str(uid_from_web).strip()
        rfid_ok  = True
        rfid_msg = f"Quét thẻ thành công: {tag_uid}"
        log(f"RFID OK: uid={tag_uid}", GREEN, "RFID")
    else:
        # Giả lập: 90% thành công, 10% lỗi (để test)
        import random
        rfid_ok  = True  # Đặt False để test lỗi RFID
        tag_uid  = f"SIM_{random.randint(10000,99999)}"
        rfid_msg = f"Quét thẻ thành công (giả lập): {tag_uid}"
        log(f"RFID SIMULATE OK: uid={tag_uid}", CYAN, "RFID")

    # Publish kết quả RFID để web nhận
    _pub("warehouse/rfid_result", {
        "success": rfid_ok,
        "uid":     tag_uid if rfid_ok else "",
        "slot":    slot_id,
        "message": rfid_msg if rfid_ok else "Quét thẻ RFID thất bại! Không đọc được thẻ."
    })

    if not rfid_ok:
        # ── Thất bại: dừng ngay, reset hệ thống ──────────────────────────
        sys_state["is_busy"]      = False
        sys_state["current_slot"] = "N/A"
        _pub("warehouse/robot_state",
             {"state": "IDLE", "slot": "N/A", "message": "RFID scan failed"}, retain=True)
        log("IMPORT thất bại: RFID không đọc được", RED, "RFID")
        return

    item_name = str(item_from_web).strip() or "Linh kien"

    # ── BƯỚC 4: Di chuyển robot đến slot ──────────────────────────────────
    _pub("warehouse/robot_state",
         {"state": "MOVING", "slot": str(slot_id), "message": f"Di chuyển đến Slot {slot_id}"}, retain=True)

    # Ghi PLC
    plc_start(slot_id)
    publish_device_status()
    publish_motor_data()

    # Cập nhật DB
    db[f"slot_{slot_id}"] = {
        "id":        slot_id,
        "status":    "Occupied",
        "uid":       tag_uid,
        "item_name": item_name,
        "time":      datetime.now().strftime("%H:%M:%S"),
    }
    save_json(DB_PATH, db)
    _pub("warehouse/slot_data", db, retain=True)
    log_event(slot_id, "IMPORT", item_name, tag_uid)

    sys_state["pending_action"] = "IMPORT"
    sys_state["pending_slot"]   = slot_id
    sys_state["pending_uid"]    = tag_uid
    sys_state["pending_item"]   = item_name

def handle_export(slot_id_direct=None, uid_search=""):
    if sys_state["is_busy"]:
        mqtt_client.publish("warehouse/error", "System busy")
        log("EXPORT bị từ chối: hệ thống bận", YELLOW, "CMD")
        return

    db = load_json(DB_PATH, {})
    slot_id, tag_uid = None, "N/A"

    if slot_id_direct is not None:
        try:
            sid  = int(str(slot_id_direct))
            if not (1 <= sid <= 9):
                mqtt_client.publish("warehouse/error", "Invalid slot (1-9)"); return
            info = db.get(f"slot_{sid}", {})
            if info.get("status") != "Occupied":
                mqtt_client.publish("warehouse/error", f"Slot {sid} is empty"); return
            slot_id, tag_uid = sid, info.get("uid", "N/A")
        except (ValueError, TypeError):
            mqtt_client.publish("warehouse/error", "Invalid slot number"); return
    elif uid_search:
        for i in range(1, 10):
            info = db.get(f"slot_{i}", {})
            if str(info.get("uid", "")) == uid_search and info.get("status") == "Occupied":
                slot_id, tag_uid = i, info.get("uid", "N/A")
                break

    if slot_id is None:
        mqtt_client.publish("warehouse/error", "Item not found"); return

    log(f"EXPORT → Slot {slot_id} | UID={tag_uid}", BLUE, "CMD")

    _pub("warehouse/robot_state",
         {"state": "MOVING", "slot": str(slot_id), "message": ""}, retain=True)

    plc_start(slot_id)
    publish_device_status()
    publish_motor_data()

    db[f"slot_{slot_id}"] = {"id": slot_id, "status": "Available"}
    save_json(DB_PATH, db)
    _pub("warehouse/slot_data", db, retain=True)
    log_event(slot_id, "EXPORT", "Xuat kho", tag_uid)

    sys_state["pending_action"] = "EXPORT"
    sys_state["pending_slot"]   = slot_id
    sys_state["pending_uid"]    = tag_uid

# ══════════════════════════════════════════════════════════════════════════════
#  MQTT CALLBACKS
# ══════════════════════════════════════════════════════════════════════════════
def on_connect(c, u, flags, rc, p=None):
    if rc == 0:
        log("MQTT kết nối thành công!", GREEN, "MQTT")
        c.subscribe("warehouse/command")
        c.subscribe("warehouse/set_maintenance")
        c.subscribe("warehouse/cancel_operation")   # Nhận lệnh hủy từ web
        log("Đã subscribe: warehouse/command, warehouse/set_maintenance, warehouse/cancel_operation", CYAN, "MQTT")
        # Phát lại trạng thái bảo trì khi reconnect
        publish_maintenance(sys_state["maintenance_mode"])
    else:
        log(f"MQTT kết nối thất bại, rc={rc}", RED, "MQTT")

def on_disconnect(c, u, flags, rc, p=None):
    log(f"MQTT ngắt kết nối (rc={rc}), đang tái kết nối...", YELLOW, "MQTT")

def on_message(client, userdata, msg):
    try:
        raw = msg.payload.decode()
        topic = msg.topic
        log(f"← MQTT [{topic}]: {raw}", GRAY, "MQTT")

        cmd = json.loads(raw)
        act = cmd.get("action", "").upper()

        # ── Xử lý lệnh từ web ──────────────────────────────────────────────
        if topic == "warehouse/set_maintenance":
            active = cmd.get("active", False)
            publish_maintenance(bool(active))
            return

        if topic != "warehouse/command":
            return

        log(f"→ Xử lý lệnh: {act}", YELLOW, "CMD")

        if topic == "warehouse/cancel_operation":
            # Lệnh hủy từ web (nút Hủy trong dialog)
            log("HỦY THAO TÁC nhận được từ web!", RED, "CMD")
            _do_emergency_reset()
            return

        if act == "EMERGENCY_RESET" or act == "CANCEL":
            log("EMERGENCY RESET nhận được!", RED, "CMD")
            _do_emergency_reset()


        elif act == "IMPORT":
            if sys_state["maintenance_mode"]:
                mqtt_client.publish("warehouse/error",
                    json.dumps({"message": "Hệ thống đang bảo trì. Lệnh bị từ chối."}))
                log("IMPORT bị từ chối: bảo trì", YELLOW, "MAINT")
                return
            threading.Thread(
                target=handle_import,
                kwargs={
                    "uid_from_web":  str(cmd.get("uid")  or "").strip(),
                    "item_from_web": str(cmd.get("item") or "").strip(),
                },
                daemon=True,
            ).start()

        elif act == "EXPORT":
            if sys_state["maintenance_mode"]:
                mqtt_client.publish("warehouse/error",
                    json.dumps({"message": "Hệ thống đang bảo trì. Lệnh bị từ chối."}))
                log("EXPORT bị từ chối: bảo trì", YELLOW, "MAINT")
                return
            threading.Thread(
                target=handle_export,
                kwargs={
                    "slot_id_direct": cmd.get("slot_id"),
                    "uid_search":     str(cmd.get("uid") or "").strip(),
                },
                daemon=True,
            ).start()

        elif act == "GET_STATUS":
            publish_device_status()
            _pub("warehouse/slot_data", load_json(DB_PATH, {}), retain=True)
            # Gửi lại trạng thái bảo trì
            publish_maintenance(sys_state["maintenance_mode"])

        elif act == "GET_HISTORY":
            hist = load_json(HIST_PATH, [])
            mqtt_client.publish("warehouse/history_init",
                                json.dumps(hist, ensure_ascii=False))
            log(f"GET_HISTORY: gửi {len(hist)} bản ghi", CYAN, "CMD")

        elif act == "SET_MAINTENANCE":
            active = cmd.get("active", False)
            publish_maintenance(bool(active))

        else:
            log(f"Lệnh không xác định: {act}", RED, "CMD")

    except Exception as e:
        log(f"on_message error: {e}", RED, "ERR")

# ══════════════════════════════════════════════════════════════════════════════
#  KHỞI TẠO & MAIN
# ══════════════════════════════════════════════════════════════════════════════
# Mặc định dữ liệu kho
if not os.path.exists(DB_PATH):
    default_db = {f"slot_{i}": {"id": i, "status": "Available"} for i in range(1, 10)}
    save_json(DB_PATH, default_db)

# MQTT client
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect    = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_message    = on_message
mqtt_client.reconnect_delay_set(min_delay=2, max_delay=30)
mqtt_client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)

def print_banner():
    mode_label = f"{RED}OFFLINE (không kết nối PLC){RESET}" if OFFLINE_MODE else (f"{YELLOW}SIMULATE{RESET}" if SIMULATE_PLC else f"{GREEN}PLC THỰC{RESET}")
    print(f"""
{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════╗
║         AS/RS MASTER CONTROLLER — LAPTOP VERSION             ║
║         Phiên bản chạy trên Windows/Linux trước khi nạp RPi  ║
╚══════════════════════════════════════════════════════════════╝{RESET}

{YELLOW}Cấu hình:{RESET}
  • PLC IP       : {PLC_IP}  (DB{DB_NUMBER})
  • CHẾ ĐỘ PLC  : {mode_label}
  • MQTT         : {MQTT_HOST}:{MQTT_PORT}
  • Dữ liệu      : {DATA_DIR}
  • Log PLC      : {LOG_PATH}

{GREEN}Topics MQTT:{RESET}
  SUB: warehouse/command          ← Nhận lệnh từ web
  SUB: warehouse/set_maintenance  ← Bật/tắt bảo trì
  PUB: warehouse/robot_state      → Trạng thái robot
  PUB: warehouse/slot_data        → Bản đồ kho
  PUB: warehouse/ack              → Xác nhận
  PUB: warehouse/error            → Lỗi
  PUB: warehouse/maintenance_mode → Trạng thái bảo trì
  PUB: warehouse/history          → Log real-time
  PUB: warehouse/status           → Trạng thái thiết bị
  PUB: warehouse/system_info      → CPU/RAM/Temp
  PUB: warehouse/motor_data       → Dữ liệu động cơ

{MAGENTA}Log lệnh PLC sẽ được lưu tại: {LOG_PATH}{RESET}
{GRAY}Nhấn Ctrl+C để thoát.{RESET}
""")

if __name__ == "__main__":
    print_banner()

    # Khởi động PLC (hoặc simulator)
    _plc_connect()

    # Monitor thread
    threading.Thread(target=monitor_logic, daemon=True).start()

    # Kết nối MQTT
    try:
        log("Đang kết nối MQTT...", CYAN, "MQTT")
        mqtt_client.connect(MQTT_HOST, MQTT_PORT)
        mqtt_client.loop_forever()
    except KeyboardInterrupt:
        log("Đang tắt...", YELLOW, "SYS")
        mqtt_client.disconnect()
        sys.exit(0)
    except Exception as e:
        log(f"Lỗi nghiêm trọng: {e}", RED, "SYS")
        sys.exit(1)
