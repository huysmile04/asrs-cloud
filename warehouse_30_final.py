import os, time, json, ssl, threading, snap7, psutil
from snap7.util import *
import paho.mqtt.client as mqtt
from datetime import datetime
from mfrc522 import SimpleMFRC522
import RPi.GPIO as GPIO

# ── CONFIG ────────────────────────────────────────────────────────────────────
DATA_DIR  = "/home/lhuy/data"
DB_PATH   = os.path.join(DATA_DIR, "warehouse_9.json")
HIST_PATH = os.path.join(DATA_DIR, "history_9.json")

PLC_IP       = "192.168.0.1"
DB_NUMBER    = 14
TARGET_ADDR  = 0   # Int (2 bytes): slot index 0-8
CONTROL_BYTE = 2   # bit 0 = BUSY, bit 1 = DONE
BUSY_BIT, DONE_BIT = 0, 1

MQTT_HOST = "5031841c1f8d4218bafa640220641d55.s1.eu.hivemq.cloud"
MQTT_USER = "lhuy04"
MQTT_PASS = "Hcmute2026"

GPIO.setwarnings(False)
os.makedirs(DATA_DIR, exist_ok=True)

reader   = SimpleMFRC522()
client   = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
plc      = snap7.client.Client()
plc_lock = threading.Lock()

sys_state = {
    "plc_connected":  False,
    "is_busy":        False,
    "current_slot":   "N/A",
    "pending_action": None,
    "pending_slot":   None,
    "pending_uid":    None,
    "pending_item":   None,
}

# ── JSON ──────────────────────────────────────────────────────────────────────

def load_json(path, default):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        save_json(path, default)
        return default
    with open(path) as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=4)
    os.sync()

def log_event(sid, act, item, uid):
    hist = load_json(HIST_PATH, [])
    entry = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "slot": str(sid),
             "act": act, "item": item, "uid": uid}
    hist.append(entry)
    save_json(HIST_PATH, hist[-100:])
    client.publish("warehouse/history", json.dumps(entry))

# ── PLC ───────────────────────────────────────────────────────────────────────

def write_plc_bit(byte_off, bit_off, value):
    with plc_lock:
        try:
            data = plc.db_read(DB_NUMBER, byte_off, 1)
            set_bool(data, 0, bit_off, value)
            plc.db_write(DB_NUMBER, byte_off, data)
        except Exception as e:
            print(f"PLC bit write error: {e}")

def write_plc_slot(slot_index):
    with plc_lock:
        try:
            data = bytearray(2)
            set_int(data, 0, int(slot_index))
            plc.db_write(DB_NUMBER, TARGET_ADDR, data)
        except Exception as e:
            print(f"PLC slot write error: {e}")

def plc_start(slot_id):
    write_plc_slot(slot_id - 1)
    write_plc_bit(CONTROL_BYTE, BUSY_BIT, True)
    sys_state["is_busy"]      = True
    sys_state["current_slot"] = str(slot_id)

# ── PUBLISH (tools.html) ──────────────────────────────────────────────────────

def publish_system_info():
    try:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
        try:
            with open('/sys/class/thermal/thermal_zone0/temp') as f:
                temp = int(f.read().strip()) / 1000.0
        except:
            temp = 0.0
        client.publish("warehouse/system_info", json.dumps({
            "cpu": round(cpu, 1), "ram": round(ram, 1), "temp": round(temp, 1)
        }))
    except Exception as e:
        print(f"system_info error: {e}")

def publish_device_status():
    client.publish("warehouse/status", json.dumps({
        "plc":  "connected" if sys_state["plc_connected"] else "disconnected",
        "rfid": "ready"
    }))

def publish_motor_data():
    running = sys_state["is_busy"]
    try:
        n = int(sys_state["current_slot"])
        slot_label, level = f"Slot {n}", str(((n - 1) // 3) + 1)
    except (ValueError, TypeError):
        slot_label, level = "--", "--"

    st = "running" if running else "idle"
    client.publish("warehouse/motor_data", json.dumps({
        "m1": {"speed": 150 if running else 0, "status": st},
        "m2": {"slot":  slot_label, "status": st},
        "m3": {"slot":  slot_label, "status": st},
        "m4": {"conveyor": "on" if running else "off", "fan": "on" if running else "off", "status": st},
    }))

# ── MONITOR LOOP ──────────────────────────────────────────────────────────────

def monitor_logic():
    last_pub = 0
    while True:
        if not plc.get_connected():
            sys_state["plc_connected"] = False
            try: plc.connect(PLC_IP, 0, 1)
            except: pass
        else:
            sys_state["plc_connected"] = True
            try:
                with plc_lock:
                    ctrl = plc.db_read(DB_NUMBER, CONTROL_BYTE, 1)
                sys_state["is_busy"] = get_bool(ctrl, 0, BUSY_BIT)

                if get_bool(ctrl, 0, DONE_BIT) and sys_state["is_busy"]:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] DONE bit detected")
                    write_plc_bit(CONTROL_BYTE, BUSY_BIT, False)
                    write_plc_bit(CONTROL_BYTE, DONE_BIT, False)
                    sys_state["is_busy"]      = False
                    sys_state["current_slot"] = "N/A"

                    p_action = sys_state.pop("pending_action", None)
                    p_slot   = sys_state.pop("pending_slot",   None)
                    p_uid    = sys_state.pop("pending_uid",    None)
                    p_item   = sys_state.pop("pending_item",   None)
                    if p_action:
                        client.publish("warehouse/ack", json.dumps({
                            "action": p_action, "slot": p_slot, "uid": p_uid, "item": p_item
                        }))

                    db = load_json(DB_PATH, {})
                    client.publish("warehouse/slot_data", json.dumps(db), retain=True)
                    client.publish("warehouse/robot_state", json.dumps({
                        "state": "IDLE", "slot": "N/A", "message": "Ready"
                    }), retain=True)
            except:
                pass

        if time.time() - last_pub > 2:
            publish_system_info()
            publish_device_status()
            publish_motor_data()
            last_pub = time.time()

        time.sleep(0.2)

# ── IMPORT / EXPORT ───────────────────────────────────────────────────────────

def find_nearest_slot(db):
    for i in range(1, 10):
        if db.get(f"slot_{i}", {}).get("status", "Available") == "Available":
            return i
    return None

def handle_import(uid_from_web="", item_from_web=""):
    if sys_state["is_busy"]:
        client.publish("warehouse/error", "System busy"); return

    db      = load_json(DB_PATH, {})
    slot_id = find_nearest_slot(db)
    if slot_id is None:
        client.publish("warehouse/error", "Warehouse full!"); return

    client.publish("warehouse/robot_state", json.dumps({
        "state": "WAITING_RFID", "slot": str(slot_id), "message": ""
    }), retain=True)

    uid_str = str(uid_from_web).strip()
    if uid_str and uid_str != "N/A":
        tag_uid = uid_str
    else:
        rfid_id, _ = reader.read()
        tag_uid    = str(rfid_id)

    item_name = str(item_from_web).strip() or "Linh kien"

    client.publish("warehouse/robot_state", json.dumps({
        "state": "MOVING", "slot": str(slot_id), "message": ""
    }), retain=True)

    plc_start(slot_id)
    publish_device_status()
    publish_motor_data()

    db[f"slot_{slot_id}"] = {
        "id": slot_id, "status": "Occupied", "uid": tag_uid,
        "item_name": item_name, "time": datetime.now().strftime("%H:%M:%S")
    }
    save_json(DB_PATH, db)
    client.publish("warehouse/slot_data", json.dumps(db), retain=True)
    log_event(slot_id, "IMPORT", item_name, tag_uid)

    sys_state["pending_action"] = "IMPORT"
    sys_state["pending_slot"]   = slot_id
    sys_state["pending_uid"]    = tag_uid
    sys_state["pending_item"]   = item_name

def handle_export(slot_id_direct=None, uid_search=""):
    if sys_state["is_busy"]:
        client.publish("warehouse/error", "System busy"); return

    db      = load_json(DB_PATH, {})
    slot_id, tag_uid = None, "N/A"

    if slot_id_direct is not None:
        try:
            sid = int(str(slot_id_direct))
            if not (1 <= sid <= 9):
                client.publish("warehouse/error", "Invalid slot (1-9)"); return
            info = db.get(f"slot_{sid}", {})
            if info.get("status") != "Occupied":
                client.publish("warehouse/error", f"Slot {sid} is empty"); return
            slot_id, tag_uid = sid, info.get("uid", "N/A")
        except (ValueError, TypeError):
            client.publish("warehouse/error", "Invalid slot number"); return
    elif uid_search:
        for i in range(1, 10):
            info = db.get(f"slot_{i}", {})
            if str(info.get("uid", "")) == uid_search and info.get("status") == "Occupied":
                slot_id, tag_uid = i, info.get("uid", "N/A")
                break

    if slot_id is None:
        client.publish("warehouse/error", "Item not found"); return

    client.publish("warehouse/robot_state", json.dumps({
        "state": "MOVING", "slot": str(slot_id), "message": ""
    }), retain=True)

    plc_start(slot_id)
    publish_device_status()
    publish_motor_data()

    db[f"slot_{slot_id}"] = {"id": slot_id, "status": "Available"}
    save_json(DB_PATH, db)
    client.publish("warehouse/slot_data", json.dumps(db), retain=True)
    log_event(slot_id, "EXPORT", "Xuat kho", tag_uid)

    sys_state["pending_action"] = "EXPORT"
    sys_state["pending_slot"]   = slot_id
    sys_state["pending_uid"]    = tag_uid

# ── MQTT COMMAND HANDLER ──────────────────────────────────────────────────────

def on_message(client, userdata, msg):
    try:
        cmd = json.loads(msg.payload.decode())
        act = cmd.get("action", "").upper()

        if act == "EMERGENCY_RESET":
            write_plc_bit(CONTROL_BYTE, BUSY_BIT, False)
            write_plc_bit(CONTROL_BYTE, DONE_BIT, False)
            write_plc_slot(-1)
            sys_state.update({"is_busy": False, "current_slot": "N/A",
                               "pending_action": None, "pending_slot": None, "pending_uid": None})
            client.publish("warehouse/robot_state", json.dumps({"state": "IDLE", "slot": "N/A", "message": "RESET"}), retain=True)
            client.publish("warehouse/ack", json.dumps({"action": "RESET"}))
            publish_device_status()
            publish_motor_data()

        elif act == "IMPORT":
            threading.Thread(target=handle_import, kwargs={
                "uid_from_web":  str(cmd.get("uid")  or "").strip(),
                "item_from_web": str(cmd.get("item") or "").strip()
            }, daemon=True).start()

        elif act == "EXPORT":
            threading.Thread(target=handle_export, kwargs={
                "slot_id_direct": cmd.get("slot_id"),
                "uid_search":     str(cmd.get("uid") or "").strip()
            }, daemon=True).start()

        elif act == "GET_STATUS":
            publish_device_status()
            client.publish("warehouse/slot_data", json.dumps(load_json(DB_PATH, {})), retain=True)

        elif act == "GET_HISTORY":
            client.publish("warehouse/history_init", json.dumps(load_json(HIST_PATH, [])))

    except Exception as e:
        print(f"on_message error: {e}")

# ── STARTUP ───────────────────────────────────────────────────────────────────

default_db = {f"slot_{i}": {"id": i, "status": "Available"} for i in range(1, 10)}
if not os.path.exists(DB_PATH):
    save_json(DB_PATH, default_db)

print("--- AS/RS SYSTEM STARTING (9 slots) ---")
threading.Thread(target=monitor_logic, daemon=True).start()

def _on_connect(c, u, flags, rc, p=None):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] MQTT connected")
    c.subscribe("warehouse/command")

def _on_disconnect(c, u, flags, rc, p=None):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] MQTT disconnected (rc={rc}), reconnecting...")

client.on_connect    = _on_connect
client.on_disconnect = _on_disconnect
client.on_message    = on_message
client.reconnect_delay_set(min_delay=2, max_delay=30)
client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.connect(MQTT_HOST, 8883)

try:
    client.loop_forever()
finally:
    GPIO.cleanup()
