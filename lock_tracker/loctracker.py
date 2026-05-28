import win32gui
import win32con
import win32ts
import os
import json
import time
import logging
import traceback
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# File lưu trữ dữ liệu (absolute paths)
STATE_FILE = os.path.join(BASE_DIR, "lock_tracker.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_FILE = os.path.join(BASE_DIR, "loctracker.log")

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Some pywin32 versions may not expose WM_WTSSESSION_CHANGE in win32con
# Define fallback constant (WM_WTSSESSION_CHANGE = 0x02B1)
WM_WTSSESSION_CHANGE = getattr(win32con, 'WM_WTSSESSION_CHANGE', 0x02B1)

def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def get_month_file(month_key):
    ensure_data_dir()
    return os.path.join(DATA_DIR, f"{month_key}.json")


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logging.exception(f"JSON decode error reading {path}")
    except Exception:
        logging.exception(f"Unexpected error reading {path}")
    return default


def save_json(path, data):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp, path)
    except Exception:
        logging.exception(f"Failed to save JSON to {path}")


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            try:
                ts = datetime.now().strftime('%Y%m%d-%H%M%S')
                corrupt_backup = STATE_FILE + f".corrupt.{ts}"
                os.replace(STATE_FILE, corrupt_backup)
                logging.exception(f"State file was corrupt. Backed up to {corrupt_backup}")
            except Exception:
                logging.exception("Failed to backup corrupted state file")
            return {"last_lock_date": "", "current_lock_start": None}
        except Exception:
            logging.exception("Unexpected error loading state file")
            return {"last_lock_date": "", "current_lock_start": None}

        if data.get("days"):
            migrate_legacy_data(data)
            return {"last_lock_date": data.get("last_lock_date", ""), "current_lock_start": data.get("current_lock_start")}
        return {"last_lock_date": data.get("last_lock_date", ""), "current_lock_start": data.get("current_lock_start")}
    return {"last_lock_date": "", "current_lock_start": None}


def save_state(state):
    save_json(STATE_FILE, state)


def load_month_data(month_key):
    return load_json(get_month_file(month_key), {}) or {}


def save_month_data(month_key, month_data):
    save_json(get_month_file(month_key), month_data)


def ensure_current_month_file():
    month_key = datetime.now().strftime('%Y-%m')
    if not os.path.exists(get_month_file(month_key)):
        save_month_data(month_key, {})


def migrate_legacy_data(data):
    if not data.get("days"):
        return
    ensure_data_dir()
    for date_str, day_data in data.get("days", {}).items():
        month_key = date_str[:7]
        month_data = load_month_data(month_key)
        month_data.setdefault(date_str, {"total_seconds": 0, "sessions": []})
        month_data[date_str]["total_seconds"] = day_data.get("total_seconds", 0)
        month_data[date_str]["sessions"] = day_data.get("sessions", [])
        save_month_data(month_key, month_data)
    save_state({"last_lock_date": data.get("last_lock_date", ""), "current_lock_start": data.get("current_lock_start")})

def format_duration(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours} giờ {minutes} phút {secs} giây"

def handle_lock_event():
    """Xử lý khi nhận được sự kiện KHÓA màn hình từ Windows"""
    state = load_state()
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    logging.info(f"🔒 Màn hình vừa bị khóa.")
    
    # Kiểm tra tính tổng ngày hôm trước nếu đây là lần đầu của ngày mới
    last_date = state.get("last_lock_date")
    if last_date and last_date != today_str:
        prev_month = last_date[:7]
        month_data = load_month_data(prev_month)
        prev_day_data = month_data.get(last_date, {})
        total_secs = prev_day_data.get("total_seconds", 0)
        logging.info(f"Previous day summary for {last_date}: {format_duration(total_secs)}")

    if state.get("current_lock_start"):
        logging.warning("Received lock event but current_lock_start already set. Ignoring duplicate lock.")
        return

    state["current_lock_start"] = now.timestamp()
    state["last_lock_date"] = today_str
    save_state(state)

def handle_unlock_event():
    """Xử lý khi nhận được sự kiện MỞ KHÓA màn hình từ Windows"""
    state = load_state()
    now = datetime.now()
    logging.info(f"🔓 Màn hình đã mở khóa.")
    
    start_time = state.get("current_lock_start")
    if not start_time:
        logging.warning("Received unlock event but no current_lock_start recorded. Ignoring.")
        return

    duration = now.timestamp() - start_time
    lock_datetime = datetime.fromtimestamp(start_time)
    lock_date_str = lock_datetime.strftime("%Y-%m-%d")
    month_key = lock_date_str[:7]
    month_data = load_month_data(month_key)
    day_data = month_data.setdefault(lock_date_str, {"total_seconds": 0, "sessions": []})
    day_data["total_seconds"] += duration
    day_data["sessions"].append({
        "lock_at": lock_datetime.strftime("%H:%M:%S"),
        "unlock_at": now.strftime("%H:%M:%S"),
        "duration_seconds": round(duration, 2),
        "duration_formatted": format_duration(duration)
    })
    save_month_data(month_key, month_data)

    state["current_lock_start"] = None
    save_state(state)
    logging.info(f"-> Thời gian lock lượt vừa rồi: {format_duration(duration)}")

def window_proc(hwnd, msg, wparam, lparam):
    """Hàm chặn và bắt các tín hiệu thay đổi trạng thái từ Windows"""
    if msg == WM_WTSSESSION_CHANGE:
        # Sự kiện Lock màn hình (WTS_SESSION_LOCK = 0x7)
        if wparam == 0x7: 
            handle_lock_event()
        # Sự kiện Mở khóa màn hình (WTS_SESSION_UNLOCK = 0x8)
        elif wparam == 0x8: 
            handle_unlock_event()
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

def main():
    logging.info("==================================================")
    logging.info("Bot đang lắng nghe sự kiện Hệ thống (0% CPU)...")
    logging.info("==================================================")
    ensure_current_month_file()
    
    # Tạo một cửa sổ ngầm ẩn danh để hứng sự kiện từ hệ thống
    wc = win32gui.WNDCLASS()
    wc.lpfnWndProc = window_proc
    wc.lpszClassName = "LockBotSessionListener"
    h_instance = win32gui.GetModuleHandle(None)
    wc.hInstance = h_instance
    
    class_atom = win32gui.RegisterClass(wc)
    hwnd = win32gui.CreateWindow(
        class_atom, "LockBotWindow", 0, 0, 0, 0, 0, 0, 0, h_instance, None
    )
    
    # Đăng ký nhận thông báo khi trạng thái Session thay đổi
    win32ts.WTSRegisterSessionNotification(hwnd, win32ts.NOTIFY_FOR_THIS_SESSION)
    
    # Giữ script luôn chạy bằng cách đợi sự kiện từ Windows (Không dùng vòng lặp vô hạn)
    try:
        win32gui.PumpMessages()
    except Exception:
        logging.exception("Exception in message pump")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Unhandled exception in main")

if __name__ == "__main__":
    main()