import os
import sys
import time
import json
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from radar_nowcast import run_analysis
from discord_alert import send_daily_summary, cleanup_old_day_messages, load_state

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
STATUS_FILE   = os.path.join(BASE_DIR, "latest_status.json")

# ──────────────────────────────────────────────────────────────────────────────
def load_settings():
    default = {
        "target_lat":    10.8231,
        "target_lon":    106.6297,
        "location_name": "TP. Hồ Chí Minh"
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Lỗi đọc settings: {e}. Dùng mặc định.")
    else:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=4)
    return default

def save_status(data):
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"❌ Lỗi ghi status: {e}")

def is_status_today(data):
    try:
        saved_day = time.strftime("%Y-%m-%d", time.localtime(float(data.get("timestamp", 0))))
        return saved_day == time.strftime("%Y-%m-%d")
    except Exception:
        return False

def cleanup_old_status_file():
    if not os.path.exists(STATUS_FILE):
        return
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if is_status_today(data):
            return
        os.remove(STATUS_FILE)
        print("🧹 Đã xóa latest_status.json của ngày cũ.")
    except Exception as e:
        print(f"⚠️ Không thể kiểm tra/xóa status cũ: {e}")

# ──────────────────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler(timezone="Asia/Bangkok")

# ──────────────────────────────────────────────────────────────────────────────
def job_analyze_weather():
    """Chạy định kỳ mỗi 5 phút — quét Radar và gửi Discord nếu cần."""
    print(f"\n[{time.strftime('%H:%M:%S')}] 🕒 Bắt đầu quét Radar...")
    try:
        cleanup_old_status_file()
        settings = load_settings()
        lat      = float(settings.get("target_lat",    10.8231))
        lon      = float(settings.get("target_lon",    106.6297))
        loc_name = settings.get("location_name", "Unknown")

        print(f"   📍 {loc_name} ({lat}, {lon})")
        result = run_analysis(target_lat=lat, target_lon=lon)
        result["location_name"] = loc_name
        save_status(result)

        print(f"[{time.strftime('%H:%M:%S')}] ✅ Trạng thái: {result['status']} — {result['message']}")
    except Exception as e:
        print(f"❌ Lỗi Nowcast: {e}")

def job_daily_report():
    """
    Chạy vào 10:00, 14:00, 16:00 — gửi báo cáo thời tiết tổng hợp lên Discord.
    Không phụ thuộc vào trạng thái cảnh báo.
    """
    print(f"\n[{time.strftime('%H:%M:%S')}] 📋 Gửi báo cáo thời tiết định kỳ...")
    try:
        cleanup_old_status_file()
        settings = load_settings()
        loc_name = settings.get("location_name", "Không rõ")

        # Đọc dữ liệu mới nhất đã được Worker quét
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                last = json.load(f)
            if is_status_today(last):
                details = last.get("details", {})
            else:
                lat = float(settings.get("target_lat", 10.8231))
                lon = float(settings.get("target_lon", 106.6297))
                result = run_analysis(target_lat=lat, target_lon=lon)
                result["location_name"] = loc_name
                save_status(result)
                details = result.get("details", {})
        else:
            # Chưa có dữ liệu → chạy phân tích ngay
            lat = float(settings.get("target_lat", 10.8231))
            lon = float(settings.get("target_lon", 106.6297))
            result  = run_analysis(target_lat=lat, target_lon=lon)
            details = result.get("details", {})

        send_daily_summary(loc_name, details)
    except Exception as e:
        print(f"❌ Lỗi gửi báo cáo: {e}")

# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 Khởi động Nowcast Worker V3...")

    # Dọn sạch cảnh báo/Daily report cũ nếu qua ngày mới
    cleanup_old_day_messages(load_state())

    # Chạy phân tích ngay khi khởi động
    job_analyze_weather()

    # Quét Radar mỗi 5 phút
    scheduler.add_job(job_analyze_weather, 'interval', minutes=5, id='radar_scan')

    # Báo cáo định kỳ lúc 10:00, 14:00, 16:00 (giờ Việt Nam)
    for hour in [8, 10, 14, 16]:
        scheduler.add_job(
            job_daily_report,
            CronTrigger(hour=hour, minute=0, timezone="Asia/Bangkok"),
            id=f"daily_report_{hour}h"
        )
        print(f"   ⏰ Đã lên lịch báo cáo Discord lúc {hour:02d}:00")

    scheduler.start()

    print("⏳ Worker đang chạy ngầm. Nhấn Ctrl+C để thoát.")
    last_mtime = os.path.getmtime(SETTINGS_FILE) if os.path.exists(SETTINGS_FILE) else 0
    try:
        while True:
            time.sleep(2)
            current_mtime = os.path.getmtime(SETTINGS_FILE) if os.path.exists(SETTINGS_FILE) else 0
            if current_mtime != last_mtime:
                print("\n🔄 Phát hiện thay đổi vị trí → Quét lại ngay...")
                last_mtime = current_mtime
                job_analyze_weather()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("🛑 Worker đã dừng.")
