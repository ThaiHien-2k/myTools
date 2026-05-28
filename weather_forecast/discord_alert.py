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


DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1509388087325622412/YGaBJuj5PhSZMFcaGq0fKu9OPjHJ8LSSurMZJK8d1DtQyCR391XItOLtJhfJgJLi8EjO"

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "discord_state.json")

# ──────────────────────────────────────────────────────────────────────────────
# Cấu hình chống spam
# ──────────────────────────────────────────────────────────────────────────────
# Chỉ gửi cảnh báo lại nếu đã quá MIN_RESEND_MINUTES phút kể từ lần gửi cuối
# (tránh gửi liên tục khi mây vẫn còn đó)
MIN_RESEND_MINUTES = 25

# Mức độ nghiêm trọng để so sánh leo thang
SEVERITY = {"SAFE": 0, "WARNING": 1, "DANGER": 2}

# ──────────────────────────────────────────────────────────────────────────────
def load_state():
    default = {
        "last_message_id": None,
        "last_sent_status": "SAFE",
        "last_sent_time":   0,      # unix timestamp
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

# ──────────────────────────────────────────────────────────────────────────────
def should_send_alert(state, new_status):
    """
    Trả về (bool: có nên gửi không, str: lý do)
    Chỉ gửi cảnh báo khi bắt đầu mưa (chuyển sang DANGER).
    Không gửi lại khi đang mưa liên tục (new_status là DANGER và last_sent_status là DANGER).
    """
    if new_status == "SAFE":
        state["consecutive_warning_count"] = 0
        return False, "Trạng thái an toàn, không cần gửi"

    last_status = state.get("last_sent_status", "SAFE")

    # Nếu đang mưa liên tục và đã gửi tin rồi -> không gửi lại nữa (chống spam mưa liên tục)
    if new_status == "DANGER":
        if last_status == "DANGER":
            return False, "Mưa đang tiếp diễn, đã có cảnh báo trên Discord trước đó"
        else:
            state["consecutive_warning_count"] = 2
            save_state(state)
            return True, "Bắt đầu mưa khẩn cấp (DANGER)"

    return False, "Không gửi cảnh báo cho WARNING hoặc trạng thái khác"


def send_discord_alert(status, message, details):
    """
    Gửi cảnh báo thời tiết:
    - SAFE: Xóa tin nhắn cũ (nếu có)
    - WARNING/DANGER: Kiểm tra anti-spam trước, nếu nên gửi thì xóa cũ và gửi mới
    """
    state = load_state()

    if status == "SAFE":
        # Xóa tin nhắn cảnh báo cũ nếu có
        was_deleted = False
        if state.get("last_message_id"):
            delete_message(state["last_message_id"])
            was_deleted = True
        
        state["last_message_id"] = None
        state["last_sent_status"] = "SAFE"
        state["consecutive_warning_count"] = 0
        save_state(state)
        
        if was_deleted:
            print("✅ [Discord] Bầu trời an toàn. Đã xóa cảnh báo cũ.")
        return

    # Kiểm tra có nên gửi không
    do_send, reason = should_send_alert(state, status)
    if not do_send:
        print(f"🔕 [Discord] Bỏ qua gửi ({reason})")
        return

    print(f"📢 [Discord] Gửi cảnh báo [{status}] — {reason}")

    # Màu embed
    color_map = {"DANGER": 0xFF0000, "WARNING": 0xFF8C00}
    color = color_map.get(status, 0x00BFFF)

    embed = {
        "title": "🌧️ Cảnh Báo Mưa Tức Thời — Nowcast AI",
        "description": message,
        "color": color,
        "fields": [
            {"name": "📊 Thông số chi tiết", "value": details or "N/A", "inline": False}
        ],
        "footer": {
            "text": f"Nowcast AI Pro • {datetime.datetime.now().strftime('%H:%M:%S %d/%m/%Y')}"
        },
    }

    payload = {"embeds": [embed]}
    url     = f"{DISCORD_WEBHOOK_URL}?wait=true"

    try:
        # Xóa tin cũ trước khi gửi mới
        if state.get("last_message_id"):
            delete_message(state["last_message_id"])
            state["last_message_id"] = None

        res = requests.post(url, json=payload, timeout=8)
        if res.status_code in [200, 201]:
            res_data = res.json()
            state["last_message_id"]  = res_data.get("id")
            state["last_sent_status"] = status
            state["last_sent_time"]   = time.time()
            save_state(state)
            print(f"✅ [Discord] Đã gửi cảnh báo [{status}] thành công!")
        else:
            print(f"❌ [Discord] Lỗi API: {res.status_code} — {res.text[:100]}")
    except Exception as e:
        print(f"❌ [Discord] Lỗi kết nối: {e}")


def send_daily_summary(location_name, details):
    """
    Gửi báo cáo thời tiết tổng hợp (10h, 14h, 16h) — không phụ thuộc trạng thái cảnh báo.
    Tin nhắn này KHÔNG bị xóa bởi logic anti-spam, nó là tin riêng biệt.
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
        ],
        "footer": {
            "text": f"Nowcast AI Pro • Cập nhật {datetime.datetime.now().strftime('%H:%M %d/%m/%Y')}"
        },
    }

    try:
        url = f"{DISCORD_WEBHOOK_URL}?wait=true"
        res = requests.post(url, json={"embeds": [embed]}, timeout=8)
        if res.status_code in [200, 201]:
            print(f"✅ [Discord] Đã gửi báo cáo {session} thành công!")
        else:
            print(f"❌ [Discord] Lỗi gửi báo cáo: {res.status_code}")
    except Exception as e:
        print(f"❌ [Discord] Lỗi kết nối báo cáo: {e}")
