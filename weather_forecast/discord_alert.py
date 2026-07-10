import requests
import json
import os
import time
import datetime
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "discord_state.json")
SECRETS_FILE = os.path.join(BASE_DIR, "secrets.json")

try:
    with open(SECRETS_FILE, "r") as f:
        _secrets = json.load(f)
        DISCORD_WEBHOOK_URL = _secrets.get("DISCORD_WEBHOOK_URL", "")
except Exception:
    DISCORD_WEBHOOK_URL = ""

# URL dashboard để gắn vào nút trên thông báo (có thể override bằng biến môi trường)
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://dashboard.example.com")

# ──────────────────────────────────────────────────────────────────────────────
# Cấu hình chống spam và xóa cảnh báo
# ──────────────────────────────────────────────────────────────────────────────
# Nếu vẫn ở DANGER nhưng thông báo cũ đã mất, chỉ gửi lại sau tối thiểu 30 phút.
MIN_DANGER_RESEND_MINUTES = 30
# Nếu vẫn ở DANGER thì sau 10 phút cập nhật tình hình vào tin cũ.
MIN_DANGER_UPDATE_MINUTES = 10
# Nếu trạng thái chuyển qua SAFE thì phải chờ ít nhất 30 phút an toàn trước khi xóa cảnh báo DANGER cũ.
MIN_SAFE_DELETE_MINUTES = 30

# Mức độ nghiêm trọng để so sánh leo thang
SEVERITY = {"SAFE": 0, "WARNING": 1, "DANGER": 2}

# ──────────────────────────────────────────────────────────────────────────────
def load_state():
    default = {
        "last_message_id": None,
        "last_sent_status": "SAFE",
        "last_sent_time":   0,      # unix timestamp
        "state_date": datetime.date.today().isoformat(),
        "daily_message_ids": [],
        "safe_since": None,
        "consecutive_warning_count": 0, # đếm số lần quét liên tiếp cảnh báo
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                saved = json.load(f)
                # Đảm bảo luôn có đủ các key mới
                for k, v in default.items():
                    if k not in saved:
                        saved[k] = v
                return saved
        except:
            pass
    return default

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def today_key():
    return datetime.date.today().isoformat()

def is_timestamp_today(timestamp):
    try:
        msg_date = datetime.datetime.fromtimestamp(float(timestamp)).date()
        return msg_date == datetime.date.today()
    except Exception:
        return False

def delete_message(msg_id):
    if not msg_id:
        return
    try:
        r = requests.delete(f"{DISCORD_WEBHOOK_URL}/messages/{msg_id}", timeout=5)
        if r.status_code == 204:
            print("✅ [Discord] Đã xóa tin nhắn cũ.")
        else:
            print(f"⚠️ [Discord] Xóa không được (HTTP {r.status_code})")
    except Exception as e:
        print(f"❌ [Discord] Lỗi xóa: {e}")


def discord_message_exists(msg_id):
    if not msg_id:
        return False
    try:
        r = requests.get(f"{DISCORD_WEBHOOK_URL}/messages/{msg_id}", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def edit_message(msg_id, payload):
    if not msg_id:
        return False
    try:
        url = f"{DISCORD_WEBHOOK_URL}/messages/{msg_id}"
        r = requests.patch(url, json=payload, timeout=8)
        if r.status_code == 200:
            print("✅ [Discord] Đã cập nhật cảnh báo DANGER vào tin cũ.")
            return True
        print(f"⚠️ [Discord] Không cập nhật được tin cũ (HTTP {r.status_code})")
        return False
    except Exception as e:
        print(f"❌ [Discord] Lỗi edit: {e}")
        return False


def cleanup_old_day_messages(state):
    """
    Sang ngày mới thì xóa toàn bộ tin nhắn Discord đã lưu từ ngày cũ.
    Chỉ xóa được các message ID mà bot đã lưu trong discord_state.json.
    """
    current_day = today_key()
    state_day = state.get("state_date")
    last_sent_time = state.get("last_sent_time", 0)

    if state_day == current_day and (not last_sent_time or is_timestamp_today(last_sent_time)):
        return state

    old_ids = []
    if state.get("last_message_id"):
        old_ids.append(state["last_message_id"])
    old_ids.extend(state.get("daily_message_ids", []))

    for msg_id in dict.fromkeys(old_ids):
        delete_message(msg_id)

    state["last_message_id"] = None
    state["last_sent_status"] = "SAFE"
    state["last_sent_time"] = 0
    state["state_date"] = current_day
    state["daily_message_ids"] = []
    state["consecutive_warning_count"] = 0
    save_state(state)
    if old_ids:
        print("🧹 [Discord] Đã dọn thông báo thời tiết của ngày cũ.")
    return state

# ──────────────────────────────────────────────────────────────────────────────
def should_send_alert(state, new_status):
    """
    Trả về (bool: có nên gửi hoặc cập nhật, str: lý do).
    WARNING/SAFE chỉ cập nhật trạng thái; DANGER dùng để gửi hoặc edit thông báo.
    """
    if new_status != "DANGER":
        return False, "Chỉ gửi Discord khi trạng thái DANGER"

    last_status = state.get("last_sent_status", "SAFE")
    last_time = float(state.get("last_sent_time", 0) or 0)
    minutes_since_last = (time.time() - last_time) / 60 if last_time else 9999

    if last_status != "DANGER":
        state["consecutive_warning_count"] = 0
        state["safe_since"] = None
        save_state(state)
        return True, f"Bắt đầu cảnh báo DANGER từ trạng thái {last_status}"

    if state.get("last_message_id"):
        if discord_message_exists(state["last_message_id"]):
            if minutes_since_last >= MIN_DANGER_UPDATE_MINUTES:
                return True, "Cập nhật DANGER vào tin cũ sau 10 phút"
            return False, "Đang giữ cảnh báo DANGER hiện tại"
        state["last_message_id"] = None
        save_state(state)
        return True, "Discord chưa có thông báo DANGER, gửi lại"

    if minutes_since_last >= MIN_DANGER_RESEND_MINUTES:
        return True, "Thông báo DANGER cũ đã hết, gửi lại sau 30 phút"

    return False, f"Đợi {MIN_DANGER_RESEND_MINUTES} phút để tránh spam khi không có tin DANGER trên Discord"


def send_discord_alert(status, message, details):
    """
    Gửi cập nhật thời tiết:
    - DANGER: gửi cảnh báo nếu chưa có thông báo DANGER hiện tại
    - WARNING: chỉ cập nhật trạng thái cảnh báo để xóa thông báo DANGER sau 2 lần liên tiếp
    - SAFE: chỉ xóa cảnh báo DANGER nếu đã ổn định 30 phút
    """
    state = load_state()
    state = cleanup_old_day_messages(state)

    if status in ("SAFE", "WARNING"):
        now = time.time()
        if status == "SAFE":
            state["safe_since"] = state.get("safe_since") or now
            state["consecutive_warning_count"] = 0
        else:
            state["safe_since"] = None
            state["consecutive_warning_count"] = state.get("consecutive_warning_count", 0) + 1

        if state.get("last_message_id"):
            delete_message(state["last_message_id"])
            state["last_message_id"] = None
            state["last_sent_time"] = 0
            state["last_sent_status"] = status
            state["state_date"] = today_key()
            save_state(state)
            print(f"✅ [Discord] Đã xóa cảnh báo DANGER lập tức vì trạng thái là {status}.")
            return

        if not (state.get("last_sent_status") == "DANGER" and state.get("last_message_id")):
            state["last_sent_status"] = status
        save_state(state)
        return

    # Kiểm tra có nên gửi hoặc cập nhật DANGER
    do_send, reason = should_send_alert(state, status)
    if not do_send:
        print(f"🔕 [Discord] Bỏ qua gửi ({reason})")
        return

    print(f"📢 [Discord] Xử lý cảnh báo [{status}] — {reason}")
    state["safe_since"] = None
    state["consecutive_warning_count"] = 0

    # Màu embed
    color_map = {"DANGER": 0xFF0000, "WARNING": 0xFF8C00}
    color = color_map.get(status, 0x00BFFF)
    title_map = {
        "DANGER": "🌧️ Cảnh Báo Mưa Khẩn Cấp — Nowcast AI",
        "WARNING": "🌦️ Theo Dõi Mưa Sắp Tới — Nowcast AI",
    }

    embed = {
        "title": title_map.get(status, "🌧️ Cảnh Báo Mưa Tức Thời — Nowcast AI"),
        "description": message,
        "color": color,
        "fields": [
            {"name": "📊 Thông số chi tiết", "value": details or "N/A", "inline": False}
        ],
        "footer": {
            "text": f"Nowcast AI Pro • {datetime.datetime.now().strftime('%H:%M:%S %d/%m/%Y')}"
        },
    }

    # Thêm nút link tới dashboard để người dùng mở trang web nhanh
    components = [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 5,
                    "label": "Mở Dashboard",
                    "url": DASHBOARD_URL
                }
            ]
        }
    ]

    payload = {"embeds": [embed], "components": components}
    url     = f"{DISCORD_WEBHOOK_URL}?wait=true"

    try:
        current_message_id = state.get("last_message_id")
        if current_message_id and discord_message_exists(current_message_id):
            if edit_message(current_message_id, payload):
                state["last_sent_time"] = time.time()
                state["last_sent_status"] = status
                state["state_date"] = today_key()
                save_state(state)
                return
            state["last_message_id"] = None

        # Nếu không edit được hoặc tin đã bị xóa thì gửi mới
        res = requests.post(url, json=payload, timeout=8)
        if res.status_code in [200, 201]:
            res_data = res.json()
            state["last_message_id"]  = res_data.get("id")
            state["last_sent_status"] = status
            state["last_sent_time"]   = time.time()
            state["state_date"]       = today_key()
            save_state(state)
            print(f"✅ [Discord] Đã gửi cảnh báo [{status}] thành công!")
        else:
            print(f"❌ [Discord] Lỗi API: {res.status_code} — {res.text[:100]}")
    except Exception as e:
        print(f"❌ [Discord] Lỗi kết nối: {e}")


def send_daily_summary(location_name, details):
    """
    Gửi báo cáo thời tiết tổng hợp (10h, 14h, 16h) — không phụ thuộc trạng thái cảnh báo.
    Tin nhắn này là tin riêng biệt, nhưng vẫn được lưu ID để sang ngày mới dọn sạch.
    """
    temp  = details.get("temperature", "--")
    fl    = details.get("feels_like",  "--")
    hum   = details.get("humidity",    "--")
    prob  = details.get("precipitation_probability", 0)
    rain  = details.get("rain_mm",     0)
    desc  = details.get("weather_desc", "Không rõ")
    ws    = details.get("wind_speed",  0)

    # Chọn màu theo xác suất mưa
    if prob >= 70:
        color = 0xFF8C00
    elif prob >= 40:
        color = 0xFFD700
    else:
        color = 0x00BFFF

    hour = datetime.datetime.now().hour
    session = "Buổi sáng" if hour < 12 else ("Buổi chiều" if hour < 17 else "Buổi tối")

    embed = {
        "title": f"☀️ Dự báo {session} — {location_name}",
        "color": color,
        "fields": [
            {
                "name": "🌡️ Nhiệt độ",
                "value": f"{temp}°C (Cảm giác {fl}°C)",
                "inline": True
            },
            {
                "name": "💧 Độ ẩm",
                "value": f"{hum}%",
                "inline": True
            },
            {
                "name": "☁️ Thời tiết",
                "value": desc,
                "inline": True
            },
            {
                "name": "🎲 Xác suất mưa",
                "value": f"**{prob}%**",
                "inline": True
            },
            {
                "name": "🌧️ Lượng mưa",
                "value": f"{rain:.1f} mm",
                "inline": True
            },
            {
                "name": "💨 Tốc độ gió",
                "value": f"{ws:.1f} km/h",
                "inline": True
            },
            # ETA / clear estimates inserted below if available
        ],
        "footer": {
            "text": f"Nowcast AI Pro • Cập nhật {datetime.datetime.now().strftime('%H:%M %d/%m/%Y')}"
        },
    }

    # Thêm ETA (mưa tiến vào) và ước tính tạnh nếu có dữ liệu
    try:
        eta = details.get('eta_minutes') if isinstance(details, dict) else None
    except Exception:
        eta = None

    clear_est = None
    try:
        # Nếu có cloud_distance (km) và cloud_speed (km/h), ước tính thời gian tạnh
        cloud_distance = float(details.get('cloud_distance', 0) or 0)
        cloud_speed = float(details.get('cloud_speed', 0) or 0)
        if cloud_distance > 0 and cloud_speed > 0:
            clear_est = int((cloud_distance / cloud_speed) * 60)
    except Exception:
        clear_est = None

    if eta is not None:
        embed['fields'].append({
            'name': '⏱️ Mưa tiến vào',
            'value': f"Khoảng {int(eta)} phút nữa" if isinstance(eta, (int, float)) else str(eta),
            'inline': True
        })

    if clear_est is not None:
        embed['fields'].append({
            'name': '⏳ Dự đoán tạnh sau',
            'value': f"Khoảng {int(clear_est)} phút sau khi tiến vào",
            'inline': True
        })

    try:
        state = load_state()
        
        # Xóa tất cả các daily summary cũ trước khi gửi cái mới
        for msg_id in state.get("daily_message_ids", []):
            delete_message(msg_id)
        state["daily_message_ids"] = []
        
        url = f"{DISCORD_WEBHOOK_URL}?wait=true"
        components = [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 5,
                        "label": "Mở Dashboard",
                        "url": DASHBOARD_URL
                    }
                ]
            }
        ]
        res = requests.post(url, json={"embeds": [embed], "components": components}, timeout=8)
        if res.status_code in [200, 201]:
            msg_id = res.json().get("id")
            if msg_id:
                state.setdefault("daily_message_ids", []).append(msg_id)
                state["state_date"] = today_key()
                save_state(state)
            print(f"✅ [Discord] Đã gửi báo cáo {session} thành công!")
        else:
            print(f"❌ [Discord] Lỗi gửi báo cáo: {res.status_code}")
    except Exception as e:
        print(f"❌ [Discord] Lỗi kết nối báo cáo: {e}")
