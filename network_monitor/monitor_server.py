import psutil
import socket
import ipaddress
from datetime import datetime, timedelta
import time
import os
import threading
import requests
import json
import csv

# ===================== CẤU HÌNH =====================
PORTS = {80, 443, 3000, 5000, 8080, 5500, 5501}
TIMEOUT = 60            # Thời gian (giây) trước khi xóa client không còn hoạt động
REFRESH_INTERVAL = 5    # Chu kỳ làm mới màn hình (giây)
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1503940604810235945/BCIRdsHM3507ktWnqZTU4AVyQVdTXqgnACBMIpvdspzGsLR7T6JoHndOVgGYGINu3EIh" # Điền webhook URL của bạn vào đây
MSG_LOG_FILE = "discord_msg_log.json"
PC_NAME_CACHE_FILE = "pc_name_cache.csv"
file_lock = threading.Lock()

active_clients = {}
hostname_cache = {}
resolving_ips = set()

def load_pc_names():
    """Tải danh sách PC Name đã lưu từ file CSV."""
    if os.path.exists(PC_NAME_CACHE_FILE):
        try:
            with open(PC_NAME_CACHE_FILE, mode="r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) == 2:
                        hostname_cache[row[0]] = row[1]
        except Exception:
            pass

def save_pc_names():
    """Lưu danh sách IP và PC Name vào file CSV để nạp lại lần sau."""
    try:
        with file_lock:
            with open(PC_NAME_CACHE_FILE, mode="w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                for ip, name in list(hostname_cache.items()):
                    if name != "Resolving...":
                        writer.writerow([ip, name])
    except Exception:
        pass

load_pc_names()

def clean_old_discord_messages():
    """Xóa các tin nhắn Discord đã gửi cách đây hơn 1 tiếng."""
    if not DISCORD_WEBHOOK_URL: return
    
    with file_lock:
        try:
            if os.path.exists(MSG_LOG_FILE):
                with open(MSG_LOG_FILE, "r") as f:
                    logs = json.load(f)
            else:
                logs = []
                
            now = time.time()
            new_logs = []
            base_url = DISCORD_WEBHOOK_URL.split('?')[0]
            
            for msg in logs:
                msg_id = msg.get("id")
                timestamp = msg.get("time")
                
                # 3600 giây = 1 tiếng
                if now - timestamp >= 3600:
                    del_url = f"{base_url}/messages/{msg_id}"
                    try:
                        requests.delete(del_url, timeout=5)
                    except:
                        pass
                else:
                    new_logs.append(msg)
                    
            with open(MSG_LOG_FILE, "w") as f:
                json.dump(new_logs, f)
        except Exception:
            pass

def save_message_id(msg_id):
    """Lưu ID tin nhắn để có thể xóa sau 1 tiếng."""
    with file_lock:
        try:
            if os.path.exists(MSG_LOG_FILE):
                with open(MSG_LOG_FILE, "r") as f:
                    logs = json.load(f)
            else:
                logs = []
                
            logs.append({"id": msg_id, "time": time.time()})
            
            with open(MSG_LOG_FILE, "w") as f:
                json.dump(logs, f)
        except Exception:
            pass

def send_discord_alert_async(ip, hostname, port, process, active_list_str, active_count):
    """Luồng gửi thông báo Discord & dọn dẹp tin cũ."""
    # Xóa tin cũ trước khi gửi tin mới
    clean_old_discord_messages()
    
    data = {
        "embeds": [{
            "title": "🚨 NEW CONNECTION DETECTED",
            "color": 0xFF0000, # Màu đỏ rực
            "fields": [
                {"name": "🌐 IP", "value": f"`{ip}`", "inline": True},
                {"name": "💻 Device", "value": f"`{hostname}`", "inline": True},
                {"name": "🔌 Port", "value": f"`{port}`", "inline": True},
                {"name": "🚀 Process", "value": f"**{process}**", "inline": False},
                {"name": f"👥 Đang hoạt động ({active_count})", "value": active_list_str, "inline": False}
            ],
            "footer": {"text": f"Time: {datetime.now().strftime('%H:%M:%S')}"}
        }]
    }
    try:
        url = DISCORD_WEBHOOK_URL
        url += "&wait=true" if "?" in url else "?wait=true"
        
        res = requests.post(url, json=data, timeout=5)
        if res.status_code in (200, 201):
            msg_data = res.json()
            if "id" in msg_data:
                save_message_id(msg_data["id"])
    except:
        pass

def send_discord_alert(ip, hostname, port, process, active_list_str, active_count):
    """Gửi thông báo khi có kết nối mới (không làm block main thread)."""
    if DISCORD_WEBHOOK_URL:
        threading.Thread(target=send_discord_alert_async, args=(ip, hostname, port, process, active_list_str, active_count), daemon=True).start()


# ===================== THÔNG TIN MÁY =====================
LOCAL_HOSTNAME = socket.gethostname()

def get_primary_ip():
    """Lấy địa chỉ IP chính của máy."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "Unknown"

PRIMARY_IP = get_primary_ip()

# ===================== HÀM TIỆN ÍCH =====================
def is_local_ip(ip):
    """Kiểm tra IP có phải là IP nội bộ hoặc loopback không."""
    try:
        ip_obj = ipaddress.ip_address(ip)
        return ip_obj.is_loopback or ip == PRIMARY_IP
    except ValueError:
        return True

def query_netbios_name(ip, timeout=1):
    """Query tên PC qua NetBIOS (UDP port 137) - hiệu quả trên LAN Windows."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        # NetBIOS Node Status Request
        packet = (
            b'\x00\x00'  # Transaction ID
            b'\x00\x00'  # Flags (query)
            b'\x00\x01'  # Questions: 1
            b'\x00\x00'  # Answers: 0
            b'\x00\x00'  # Authority: 0
            b'\x00\x00'  # Additional: 0
            b'\x20'      # Name length: 32
            b'CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'  # Encoded wildcard "*"
            b'\x00'      # Name terminator
            b'\x00\x21'  # Type: NBSTAT
            b'\x00\x01'  # Class: IN
        )
        sock.sendto(packet, (ip, 137))
        data, _ = sock.recvfrom(1024)
        sock.close()
        if len(data) > 56:
            num_names = data[56]
            if num_names > 0 and len(data) >= 57 + 18:
                name = data[57:72].decode('ascii', errors='ignore').strip()
                if name:
                    return name
    except Exception:
        pass
    return None

def resolve_pc_name_async(ip):
    """Luồng ngầm để phân giải tên PC."""
    # 1. Thử NetBIOS (nhanh trên LAN Windows)
    name = query_netbios_name(ip)
    # 2. Fallback: DNS reverse lookup
    if not name:
        try:
            name = socket.gethostbyaddr(ip)[0]
        except Exception:
            name = None
    # 3. Fallback cuối: hiển thị IP thay vì Unknown
    if not name:
        name = ip
    
    hostname_cache[ip] = name
    resolving_ips.discard(ip)
    save_pc_names()

def get_pc_name(ip):
    """Lấy tên PC từ IP, không làm block chương trình chính."""
    if ip in hostname_cache:
        # Nếu đã có kết quả (hoặc đang Resolving), trả về luôn
        if ip in resolving_ips or hostname_cache[ip] != "Resolving...":
            return hostname_cache[ip]
            
    # Nếu chưa có trong cache hoặc cần resolve lại
    resolving_ips.add(ip)
    hostname_cache[ip] = "Resolving..."
    threading.Thread(target=resolve_pc_name_async, args=(ip,), daemon=True).start()
    
    return hostname_cache[ip]

def get_process_name(pid):
    """Lấy tên tiến trình từ PID."""
    try:
        return psutil.Process(pid).name() if pid else "Unknown"
    except Exception:
        return "Unknown"

def clear_console():
    """Clear screen marker for Web Dashboard."""
    print("---CLR---")

# ===================== HIỂN THỊ =====================
def format_url(ip, port):
    """Trả về URL thân thiện từ IP và port."""
    if port == 80:
        return f"http://{ip}/"
    elif port == 443:
        return f"https://{ip}/"
    else:
        return f"http://{ip}:{port}/"

def print_header():
    print("📡 NETWORK PORT MONITOR")
    print("=" * 110)
    print(f"🖥️  Hostname       : {LOCAL_HOSTNAME}")
    print(f"🌐 Primary IP      : {PRIMARY_IP}")
    print(f"🔌 Tracking Ports  : {', '.join(map(str, sorted(PORTS)))}")
    print(f"⏱️  Timeout        : {TIMEOUT} seconds")
    print(f"🔄 Refresh Every   : {REFRESH_INTERVAL} seconds")
    print("=" * 110)

def print_table():
    print(f"{'IP Address':<18} {'PC Name':<20} {'Port':<6} {'URL':<26} "
          f"{'Process':<18} {'PID':<7} {'Last Seen':<10}")
    print("-" * 110)

    if not active_clients:
        print("No external devices connected.")
    else:
        for (ip, port), info in sorted(active_clients.items()):
            pid_display = str(info['pid']) if info['pid'] is not None else "-"
            url = format_url(PRIMARY_IP, port)
            print(f"{ip:<18} {info['hostname']:<20} {port:<6} {url:<26} "
                  f"{info['process']:<18} {pid_display:<7} "
                  f"{info['last_seen'].strftime('%H:%M:%S')}")
    print("=" * 110)

# ===================== CHƯƠNG TRÌNH CHÍNH =====================
def monitor_ports():
    while True:
        now = datetime.now()
        seen_active = set()

        try:
            connections = psutil.net_connections(kind='inet')
        except Exception:
            time.sleep(REFRESH_INTERVAL)
            continue

        for conn in connections:
            # Chỉ xét các kết nối có địa chỉ local và remote
            if not (conn.laddr and conn.raddr):
                continue

            # Chỉ xét các cổng cần theo dõi
            if conn.laddr.port not in PORTS:
                continue

            # Chỉ xét các kết nối đang ESTABLISHED
            if conn.status != psutil.CONN_ESTABLISHED:
                continue

            ip = conn.raddr.ip
            if is_local_ip(ip):
                continue

            port = conn.laddr.port
            pid = conn.pid
            process_name = get_process_name(pid)
            hostname = get_pc_name(ip)

            key = (ip, port)
            seen_active.add(key)

            if key not in active_clients:
                active_clients[key] = {
                    "hostname": hostname,
                    "process": process_name,
                    "pid": pid,
                    "last_seen": now,
                    "notified": True
                }
                
                # Lấy danh sách đang hoạt động
                active_count = len(active_clients)
                active_list_str = ""
                count = 0
                for (c_ip, c_port), c_info in active_clients.items():
                    if count >= 15:
                        active_list_str += f"... và {active_count - 15} thiết bị khác."
                        break
                    c_name = c_ip if c_info['hostname'] == "Resolving..." else c_info['hostname']
                    active_list_str += f"• `{c_ip}:{c_port}` ({c_name})\n"
                    count += 1
                
                # Gửi thông báo LUÔN lập tức, nếu chưa có tên thì hiện tạm IP
                display_name = ip if hostname == "Resolving..." else hostname
                send_discord_alert(ip, display_name, port, process_name, active_list_str, active_count)
                
            else:
                # Cập nhật thời gian hoạt động gần nhất
                active_clients[key]["last_seen"] = now

                # Cập nhật hostname phòng trường hợp vừa resolve xong
                active_clients[key]["hostname"] = hostname

                # Cập nhật PID nếu trước đó chưa có
                if active_clients[key]["pid"] is None and pid is not None:
                    active_clients[key]["pid"] = pid
                    active_clients[key]["process"] = process_name

        # ===================== XÓA CLIENT HẾT HẠN =====================
        for key in list(active_clients.keys()):
            elapsed = (now - active_clients[key]["last_seen"]).total_seconds()
            if key not in seen_active and elapsed >= TIMEOUT:
                del active_clients[key]

        # ===================== HIỂN THỊ =====================
        clear_console()
        print_header()
        print_table()

        time.sleep(REFRESH_INTERVAL)

# ===================== CHẠY CHƯƠNG TRÌNH =====================
if __name__ == "__main__":
    try:
        monitor_ports()
    except KeyboardInterrupt:
        print("\n🛑 Monitoring stopped by user.")