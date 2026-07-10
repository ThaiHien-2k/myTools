"""
discord_purge.py
Xóa toàn bộ tin nhắn Discord đã được bot gửi (lưu trong discord_state.json).
Chạy một lần để dọn sạch spam do bị tấn công.
"""

import requests
import json
import os
import sys
import datetime

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "discord_state.json")
SECRETS_FILE = os.path.join(BASE_DIR, "secrets.json")

try:
    with open(SECRETS_FILE, "r") as f:
        _secrets = json.load(f)
        DISCORD_WEBHOOK_URL = _secrets.get("DISCORD_WEBHOOK_URL", "")
except Exception:
    DISCORD_WEBHOOK_URL = ""

def delete_message(msg_id):
    if not msg_id:
        return
    try:
        r = requests.delete(
            f"{DISCORD_WEBHOOK_URL}/messages/{msg_id}",
            timeout=8
        )
        if r.status_code == 204:
            print(f"  OK Xoa message {msg_id}")
        elif r.status_code == 404:
            print(f"  -- Message {msg_id} khong ton tai (da bi xoa truoc)")
        else:
            print(f"  ERR Xoa {msg_id}: HTTP {r.status_code} -- {r.text[:80]}")
    except Exception as e:
        print(f"  ERR Ket noi: {e}")

def reset_state():
    clean = {
        "last_message_id": None,
        "last_sent_status": "SAFE",
        "last_sent_time": 0,
        "state_date": datetime.date.today().isoformat(),
        "daily_message_ids": [],
        "safe_since": None,
        "consecutive_warning_count": 0,
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)
    print("\ndiscord_state.json da duoc reset ve trang thai sach.")

def main():
    print("=" * 50)
    print("Discord Purge -- xoa tat ca tin nhan da luu")
    print("=" * 50)

    if not os.path.exists(STATE_FILE):
        print("Khong tim thay discord_state.json.")
        reset_state()
        return

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    ids_to_delete = []
    last_id = state.get("last_message_id")
    if last_id:
        ids_to_delete.append(last_id)
    ids_to_delete.extend(state.get("daily_message_ids", []))
    ids_to_delete = list(dict.fromkeys(filter(None, ids_to_delete)))

    if not ids_to_delete:
        print("Khong co message ID nao duoc luu trong state.")
    else:
        print(f"\nTim thay {len(ids_to_delete)} message(s) can xoa:\n")
        for msg_id in ids_to_delete:
            delete_message(msg_id)

    reset_state()
    print("\nHoan tat. Bot se hoat dong binh thuong tu lan chay tiep theo.")

if __name__ == "__main__":
    main()
