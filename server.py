from flask import Flask, request, render_template
import requests
import time
import json
import os
import math

app = Flask(__name__)

BOT_TOKEN = "YOUR_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"


# =========================
# 🔥 데이터 저장 구조
# =========================
DATA_FILE = "data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)

    return {
        "users": {},
        "points": {},
        "history": {},
        "daily_points": {},
        "last_reset": time.strftime("%Y-%m-%d"),
        "last_time": {},
        "distance": {},
        "regions": {},
        "region_state": {},
        "last_move_time": {},
        "last_pos": {},
    }

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)


data = load_data()


# =========================
# Telegram
# =========================
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": message
        })
    except Exception as e:
        print("Telegram error:", e)


# =========================
# 거리 계산
# =========================
def calc_distance(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


# =========================
# 🔥 지역 체크 (핵심)
# =========================
def check_region(user_id, lat, lon):

    current_region = None

    for rid, region in data["regions"].items():

        inside = True
        points = region["points"]

        j = len(points) - 1

        for i in range(len(points)):

            xi, yi = points[i]
            xj, yj = points[j]

            intersect = ((yi > lon) != (yj > lon)) and (
                lat < (xj - xi) * (lon - yi) / (yj - yi + 0.000001) + xi
            )

            if intersect:
                inside = not inside

            j = i

        if inside:
            current_region = rid
            break


    prev_region = data["region_state"].get(user_id)

    if prev_region != current_region:

        if current_region is not None:
            send_telegram(f"🚨 {user_id} → {data['regions'][current_region]['name']} 진입")

        if prev_region is not None and current_region is None:
            send_telegram(f"🚪 {user_id} → 구역 이탈")

        data["region_state"][user_id] = current_region


# =========================
# 메인
# =========================
@app.route("/")
def home():
    return render_template("index.html")


# =========================
# 위치 수신 (🔥 핵심 수정)
# =========================
@app.route("/location", methods=["POST"])
def location():

    req = request.json

    user_id = req.get("user_id")
    lat = float(req.get("latitude"))
    lon = float(req.get("longitude"))

    if not user_id:
        return {"status": "ignored"}

    now = time.time()

    prev = data["users"].get(user_id)

    # =========================
    # 위치 저장
    # =========================
    data["users"][user_id] = {
        "lat": lat,
        "lon": lon,
        "time": now
    }

    # =========================
    # 이동 기록
    # =========================
    data["history"].setdefault(user_id, [])
    data["history"][user_id].append({
        "lat": lat,
        "lon": lon,
        "time": time.strftime("%H:%M:%S", time.localtime(now))
    })

    # =========================
    # 거리 누적
    # =========================
    data["distance"].setdefault(user_id, 0)

    if prev:
        move_distance = calc_distance(
            prev["lat"], prev["lon"],
            lat, lon
        )
        data["distance"][user_id] += move_distance

    # =========================
    # 포인트
    # =========================
    data["points"].setdefault(user_id, 0)
    data["daily_points"].setdefault(user_id, 0)
    data["last_time"].setdefault(user_id, 0)

    if now - data["last_time"][user_id] >= 3600:
        data["points"][user_id] += 20
        data["daily_points"][user_id] += 20
        data["last_time"][user_id] = now

    # =========================
    # 🔥 이동 감지 (30m + 10초 필터)
    # =========================

    last_pos = data["last_pos"].get(user_id)
    real_move = 0

    if last_pos:
        real_move = calc_distance(
            last_pos["lat"], last_pos["lon"],
            lat, lon
        )

        if real_move < 0.01:
           real_move = 0

    # 30m 이상 이동 발생 시 시간 기록
    if real_move >= 0.03:
        data["last_move_time"][user_id] = now

    # 현재 위치 업데이트
    data["last_pos"][user_id] = {
        "lat": lat,
        "lon": lon
    }

    # 마지막 이동 시간 가져오기
    last_move = data["last_move_time"].get(user_id, 0)

    # 10초 이내 + 30m 이동만 알림
    if real_move >= 0.03 and (now - last_move <= 10):
        send_telegram(f"[{user_id}] {lat}, {lon}")

    # =========================
    # 구역 체크
    # =========================
    check_region(user_id, lat, lon)

    save_data()

    return {"status": "ok"}


# =========================
# 🔥 지역 등록 API
# =========================
@app.route("/region/add", methods=["POST"])
def add_region():

    req = request.json

    region_id = req["id"]
    name = req["name"]
    points = req["points"]

    data["regions"][region_id] = {
        "name": name,
        "points": points
    }

    save_data()

    return {"status": "saved"}


# =========================
# 조회 API (그대로 유지)
# =========================
@app.route("/positions")
def positions():
    return data["users"]

@app.route("/points")
def points():
    return data["points"]

@app.route("/daily_points")
def daily():
    return data["daily_points"]

@app.route("/distance")
def distance():
    return data["distance"]

@app.route("/status")
def status():

    now = time.time()
    result = {}

    for u, v in data["users"].items():
        diff = now - v["time"]

        result[u] = {
            "online": diff < 60,
            "last_seen": time.strftime("%H:%M:%S", time.localtime(v["time"]))
        }

    return result


@app.route("/history/<user_id>")
def history(user_id):
    return data["history"].get(user_id, [])


# =========================
# admin
# =========================
@app.route("/admin")
def admin():
    return render_template("admin.html")


@app.route("/reset_month", methods=["POST"])
def reset_month():

    print("🔥 RESET REQUEST RECEIVED")

    data["points"] = {}
    data["daily_points"] = {}
    data["distance"] = {}
    data["history"] = {}

    save_data()

    return {"status": "ok", "message": "reset done"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)