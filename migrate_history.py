import json, os
from datetime import date

HIST_PATH = "/home/lhuy/data/history_9.json"

if not os.path.exists(HIST_PATH):
    print("File not found:", HIST_PATH)
    exit(1)

with open(HIST_PATH) as f:
    data = json.load(f)

today = date.today().strftime("%Y-%m-%d")
count = 0

for entry in data:
    t = str(entry.get("time", ""))
    # chỉ sửa entry chưa có ngày (format "HH:MM:SS", không có khoảng trắng)
    if t and ' ' not in t:
        entry["time"] = today + " " + t
        count += 1

with open(HIST_PATH, 'w') as f:
    json.dump(data, f, indent=4, ensure_ascii=False)

print(f"Done: updated {count}/{len(data)} entries with date {today}")
