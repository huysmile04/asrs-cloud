import os, time, json, ssl, snap7
import threading
from snap7.util import *
import paho.mqtt.client as mqtt
from datetime import datetime
from mfrc522 import SimpleMFRC522
import RPi.GPIO as GPIO

# --- Cáº¤U HÃŒNH THÆ¯ Má»¤C & FILE ---
DATA_DIR = "/home/lhuy/data"
DB_PATH = os.path.join(DATA_DIR, "warehouse_9.json")
HIST_PATH = os.path.join(DATA_DIR, "history_9.json")
GPIO.setwarnings(False)

if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)

# --- Cáº¤U HÃŒNH PLC S7-1200 ---
PLC_IP = "192.168.0.1" 
DB_NUMBER = 14          # DB chuáº©n cá»§a báº¡n
TARGET_ADDR = 0         # Offset 0.0 (Kiá»ƒu Int - 2 bytes)
CONTROL_BYTE = 2        # Byte chá»©a cÃ¡c bit Ä‘iá»u khiá»ƒn
BUSY_BIT = 0            # Offset 2.0 (Busy)
DONE_BIT = 1            # Offset 2.1 (Done)

reader = SimpleMFRC522()
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
plc = snap7.client.Client()
plc_lock = threading.Lock()

# CÃ¡c biáº¿n tráº¡ng thÃ¡i toÃ n cá»¥c Ä‘á»ƒ bÃ¡o lÃªn Web
sys_state = {
    "plc_connected": False,
    "is_busy": False,
    "current_slot": "N/A"
}

# --- HÃ€M Xá»¬ LÃ Dá»® LIá»†U Táº I CHá»– (JSON) ---
def load_json(path, default_data):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, 'w') as f: json.dump(default_data, f)
        return default_data
    with open(path, 'r') as f: return json.load(f)

def save_json(path, data):
    with open(path, 'w') as f: json.dump(data, f, indent=4)
    os.sync()

def log_event(sid, act, item_name, uid):
    hist = load_json(HIST_PATH, [])
    new_log = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "slot": sid,
        "act": act,
        "item": item_name,
        "uid": uid
    }
    hist.append(new_log)
    save_json(HIST_PATH, hist[-100:])
    client.publish("warehouse/history", json.dumps(new_log))

# --- HÃ€M GIAO TIáº¾P PLC (Báº¢O Vá»† Báº°NG LOCK) ---
def write_plc_bit(byte_offset, bit_offset, value):
    with plc_lock:
        try:
            data = plc.db_read(DB_NUMBER, byte_offset, 1)
            set_bool(data, 0, bit_offset, value)
            plc.db_write(DB_NUMBER, byte_offset, data)
        except Exception as e:
            print(f"Lá»—i ghi Bit PLC: {e}")

def write_plc_slot(slot_index):
    with plc_lock:
        try:
            data = bytearray(2)
            set_int(data, 0, int(slot_index))
            plc.db_write(DB_NUMBER, TARGET_ADDR, data)
        except Exception as e:
            print(f"Lá»—i ghi Slot PLC: {e}")

# --- LUá»’NG QUÃ‰T LOGIC CHÃNH ---
def monitor_logic():
    global sys_state
    last_publish_time = 0
    
    while True:
        # Kiá»ƒm tra káº¿t ná»‘i PLC
        if not plc.get_connected():
            sys_state["plc_connected"] = False
            try: plc.connect(PLC_IP, 0, 1)
            except: pass
        else:
            sys_state["plc_connected"] = True
            try:
                # Äá»c tráº¡ng thÃ¡i tá»« Byte 2
                with plc_lock:
                    ctrl_byte_data = plc.db_read(DB_NUMBER, CONTROL_BYTE, 1)
                
                is_busy = get_bool(ctrl_byte_data, 0, BUSY_BIT)
                is_done = get_bool(ctrl_byte_data, 0, DONE_BIT)
                sys_state["is_busy"] = is_busy

                # Xá»­ lÃ½ tá»± táº¯t Busy khi Done
                if is_done and is_busy:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] PLC bÃ¡o DONE! Táº¯t Busy...")
                    write_plc_bit(CONTROL_BYTE, BUSY_BIT, False)
                    write_plc_bit(CONTROL_BYTE, DONE_BIT, False)
                    sys_state["is_busy"] = False
                    sys_state["current_slot"] = "N/A" # XÃ³a má»¥c tiÃªu khi cháº¡y xong
            except Exception as e:
                pass

        # Publish tráº¡ng thÃ¡i lÃªn Web má»—i 1 giÃ¢y (Ä‘á»ƒ UI cáº­p nháº­t)
        if time.time() - last_publish_time > 1:
            client.publish("warehouse/sys_state", json.dumps(sys_state))
            last_publish_time = time.time()
            
        time.sleep(0.2) # QuÃ©t 200ms 1 láº§n

# --- QUY TRÃŒNH NHáº¬P / XUáº¤T ---
def handle_import(sid, uid_from_web=""):
    global sys_state
    if sys_state["is_busy"]:
        client.publish("warehouse/error", "Há»‡ thá»‘ng Ä‘ang báº­n cháº¡y!")
        return

    # 1. Äá»c RFID váº­t lÃ½ (QuÃ¡ trÃ¬nh nÃ y sáº½ chá» cho Ä‘áº¿n khi cÃ³ tháº» Ä‘áº·t vÃ o)
    print(f"Vui lÃ²ng Ä‘áº·t váº­t cáº£n vÃ o mÃ¡y quÃ©t RFID cho Ã´ {sid}...")
    client.publish("warehouse/robot_state", f"CHO QUET RFID CHO O {sid}")
    
    # Náº¿u Web gá»­i UID thÃ¬ dÃ¹ng luÃ´n, khÃ´ng thÃ¬ Ä‘á»c tháº» váº­t lÃ½
    if uid_from_web and uid_from_web != "N/A":
        tag_uid = uid_from_web
    else:
        id, text = reader.read()
        tag_uid = str(id)
    
    print(f"ÄÃ£ nháº­n tháº»: {tag_uid}. Ra lá»‡nh PLC di chuyá»ƒn...")

    # 2. Gá»­i lá»‡nh xuá»‘ng PLC
    slot_index = int(sid) - 1 # Chuyá»ƒn tá»« Ã´ 1-9 sang slot 0-8
    write_plc_slot(slot_index)
    write_plc_bit(CONTROL_BYTE, BUSY_BIT, True) # Báº¬T BIT 2.0
    
    sys_state["current_slot"] = sid
    client.publish("warehouse/sys_state", json.dumps(sys_state)) # Cáº­p nháº­t gáº¥p lÃªn Web

    # 3. LÆ°u Database
    db = load_json(DB_PATH, {})
    db[f"slot_{sid}"] = {"id": sid, "status": "Occupied", "uid": tag_uid, "item_name": "Linh kiá»‡n", "time": datetime.now().strftime("%H:%M:%S")}
    save_json(DB_PATH, db)
    client.publish("warehouse/status", json.dumps(db), retain=True)
    log_event(sid, "IMPORT", "Linh kiá»‡n", tag_uid)

def handle_export(sid):
    global sys_state
    if sys_state["is_busy"]: return
    
    db = load_json(DB_PATH, {})
    item_info = db.get(f"slot_{sid}", {})
    tag_u = item_info.get("uid", "N/A")

    # 1. Gá»­i lá»‡nh PLC
    slot_index = int(sid) - 1
    write_plc_slot(slot_index)
    write_plc_bit(CONTROL_BYTE, BUSY_BIT, True)
    
    sys_state["current_slot"] = sid
    client.publish("warehouse/sys_state", json.dumps(sys_state))

    # 2. XÃ³a Data
    db[f"slot_{sid}"] = {"id": sid, "status": "Available"}
    save_json(DB_PATH, db)
    client.publish("warehouse/status", json.dumps(db), retain=True)
    log_event(sid, "EXPORT", "Xuáº¥t kho", tag_u)

# --- Xá»¬ LÃ Lá»†NH Tá»ª WEB ---
def on_message(client, userdata, msg):
    try:
        cmd = json.loads(msg.payload.decode('utf-8'))
        act = cmd.get("action")
        
        # Báº¯t lá»‡nh Reset kháº©n cáº¥p
        if act == "EMERGENCY_RESET":
            print("Nháº­n lá»‡nh RESET tá»« Web!")
            write_plc_bit(CONTROL_BYTE, BUSY_BIT, False)
            write_plc_bit(CONTROL_BYTE, DONE_BIT, False)
            write_plc_slot(-1)
            
        elif act == "IMPORT": 
            threading.Thread(target=handle_import, args=(cmd.get("slot_id"), cmd.get("uid"))).start()
        elif act == "EXPORT": 
            threading.Thread(target=handle_export, args=(cmd.get("slot_id"),)).start()
        elif act == "GET_STATUS": 
            client.publish("warehouse/status", json.dumps(load_json(DB_PATH, {})))
        elif act == "GET_HISTORY": 
            client.publish("warehouse/history_init", json.dumps(load_json(HIST_PATH, [])))
            
    except Exception as e: print(f"Lá»—i phÃ¢n tÃ­ch lá»‡nh MQTT: {e}")

# Khá»Ÿi táº¡o DB máº·c Ä‘á»‹nh cho 9 Ã´ náº¿u chÆ°a cÃ³
default_db = {f"slot_{i}": {"id": i, "status": "Available"} for i in range(1, 10)}
if not os.path.exists(DB_PATH): save_json(DB_PATH, default_db)

# --- MAIN KHá»žI Äá»˜NG ---
print("--- KHá»žI Äá»˜NG Há»† THá»NG AS/RS (9 Ã”) ---")
threading.Thread(target=monitor_logic, daemon=True).start()

client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
client.username_pw_set("lhuy04", "Hcmute2026")
client.on_message = on_message
client.connect("5031841c1f8d4218bafa640220641d55.s1.eu.hivemq.cloud", 8883)
client.subscribe("warehouse/command")

try: client.loop_forever()
finally: GPIO.cleanup()