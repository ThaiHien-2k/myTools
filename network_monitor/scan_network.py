import socket
import ipaddress
import csv
import os
import concurrent.futures

PC_NAME_CACHE_FILE = "pc_name_cache.csv"

def get_primary_ip():
    """Lấy địa chỉ IP chính của máy."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "192.168.0.140" # Fallback IP

def query_netbios_name(ip, timeout=0.5):
    """Query tên PC qua NetBIOS (UDP port 137)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        packet = (
            b'\x00\x00' b'\x00\x00' b'\x00\x01' b'\x00\x00' 
            b'\x00\x00' b'\x00\x00' b'\x20' 
            b'CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' 
            b'\x00' b'\x00\x21' b'\x00\x01'
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

def resolve_ip(ip_str):
    """Phân giải 1 IP ra Tên máy tính."""
    # Thử NetBIOS trước vì nó rất nhanh trên mạng nội bộ
    name = query_netbios_name(ip_str, timeout=0.5)
    
    if not name:
        # Nếu NetBIOS không được, thử dùng DNS ngược
        try:
            # Set timeout cho socket để gethostbyaddr không bị treo quá lâu
            socket.setdefaulttimeout(0.5)
            name = socket.gethostbyaddr(ip_str)[0]
        except Exception:
            name = None
            
    if name and name != ip_str:
        return ip_str, name
    return ip_str, None

def scan_network():
    primary_ip = get_primary_ip()
    print(f"[*] IP máy tính hiện tại: {primary_ip}")
    
    # Suy ra mạng nội bộ (ví dụ: 192.168.0.x)
    try:
        network_prefix = ".".join(primary_ip.split(".")[:3]) + ".0/24"
        network = ipaddress.IPv4Network(network_prefix, strict=False)
    except Exception as e:
        print(f"[!] Không thể xác định mạng: {e}")
        return

    print(f"[*] Đang quét toàn bộ dải mạng: {network_prefix} (sẽ tốn khoảng 10-15 giây)...")
    print("-" * 50)
    
    found_devices = {}

    # Tạo danh sách IP để quét (bỏ IP kết thúc bằng .0 và .255)
    ips_to_scan = [str(ip) for ip in network.hosts()]
    
    # Quét đa luồng cực nhanh
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(resolve_ip, ip): ip for ip in ips_to_scan}
        
        for future in concurrent.futures.as_completed(futures):
            ip, name = future.result()
            if name:
                print(f"[+] Tìm thấy: {ip:<15} -> {name}")
                found_devices[ip] = name
                
    print("-" * 50)
    
    # Sắp xếp theo IP tăng dần
    sorted_devices = sorted(found_devices.items(), key=lambda x: ipaddress.ip_address(x[0]))
    
    print(f"[*] Tổng cộng có {len(sorted_devices)} thiết bị đang online có tên (lần quét này):")
    for ip, name in sorted_devices:
        print(f"    {ip:<15} -> {name}")
    print("-" * 50)
    
    # Ghi toàn bộ ra file CSV (đã sắp xếp)
    try:
        with open(PC_NAME_CACHE_FILE, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            for ip, name in sorted_devices:
                writer.writerow([ip, name])
        print(f"[*] Đã lưu thành công vào file: {PC_NAME_CACHE_FILE}")
    except Exception as e:
        print(f"[!] Lỗi khi lưu file: {e}")

if __name__ == "__main__":
    scan_network()

