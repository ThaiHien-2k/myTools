import math
import time
import cv2
import numpy as np
import requests
import os
import sys
from vrain_fetcher import get_vrain_rainfall, get_weather_data, calculate_cloud_coords
from discord_alert import send_discord_alert

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


OWM_API_KEY = "caba72153195e76e835b0e35a82e4edb"
ZOOM_LEVEL = 7

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    return xtile, ytile

def get_pixel_coords(lat, lon, zoom, xtile, ytile):
    n = 2.0 ** zoom
    lat_rad = math.radians(lat)
    x_exact = (lon + 180.0) / 360.0 * n
    y_exact = (1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi) / 2.0 * n
    pixel_x = int((x_exact - xtile) * 512)
    pixel_y = int((y_exact - ytile) * 512)
    return pixel_x, pixel_y

def pixel_to_latlon(px, py, xtile, ytile, zoom):
    """Chuyển đổi tọa độ pixel trong tile sang Lat/Lon thực tế"""
    n = 2.0 ** zoom
    tile_x = xtile + px / 512.0
    tile_y = ytile + py / 512.0
    lon = tile_x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * tile_y / n)))
    lat = math.degrees(lat_rad)
    return lat, lon

def get_wind_data(lat, lon, api_key):
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
    try:
        res = requests.get(url, timeout=5).json()
        speed = res["wind"]["speed"]
        deg   = res["wind"]["deg"]
        return speed, deg
    except:
        return 4.0, 270

def fetch_radar_frame(host, path, xtile, ytile):
    tile_url = f"{host}{path}/512/{ZOOM_LEVEL}/{xtile}/{ytile}/1/1_1.png"
    try:
        res = requests.get(tile_url, timeout=8)
        if res.status_code == 200:
            arr = np.frombuffer(res.content, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
            if img is not None and img.shape[2] >= 4:
                return img[:, :, 3]
    except:
        pass
    return None

def find_largest_cloud(alpha_channel):
    _, thresh = cv2.threshold(alpha_channel, 30, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    max_area, best_c, best_cx, best_cy = 0, None, None, None
    for c in contours:
        area = cv2.contourArea(c)
        if area < 50: continue
        if area > max_area:
            M = cv2.moments(c)
            if M["m00"] != 0:
                max_area = area
                best_c   = c
                best_cx  = int(M["m10"] / M["m00"])
                best_cy  = int(M["m01"] / M["m00"])
    if best_c is not None:
        return best_cx, best_cy, best_c, max_area
    return None

def run_analysis(target_lat=10.8231, target_lon=106.6297):
    result = {
        "status": "SAFE",
        "message": "Đang phân tích...",
        "details": {
            "wind_speed": 0, "wind_deg": 0,
            "cloud_distance": 0, "cloud_speed": 0,
            "rain_mm": 0, "eta_minutes": 0,
            "cloud_lat": None, "cloud_lon": None,
            "target_lat": target_lat, "target_lon": target_lon,
            "rainviewer_path": None, "rainviewer_host": None,
            # Thêm các trường thời tiết đầy đủ
            "temperature": None,
            "feels_like": None,
            "humidity": None,
            "precipitation_probability": 0,
            "weather_desc": "Đang tải...",
        },
        "timestamp": time.time(),
    }

    # ── 1. Gió bề mặt (OWM) ──────────────────────────────────────────────
    wind_speed, wind_deg = get_wind_data(target_lat, target_lon, OWM_API_KEY)
    result["details"]["wind_speed"] = round(wind_speed * 3.6, 1)  # m/s -> km/h
    result["details"]["wind_deg"]   = wind_deg

    # ── 2. Thời tiết chi tiết (Open-Meteo) ───────────────────────────────
    wx = get_weather_data(target_lat, target_lon)
    result["details"]["temperature"]              = wx["temperature"]
    result["details"]["feels_like"]               = wx["feels_like"]
    result["details"]["humidity"]                 = wx["humidity"]
    result["details"]["precipitation_probability"] = wx["precipitation_probability"]
    result["details"]["weather_desc"]             = wx["weather_desc"]
    # Ưu tiên dùng lượng mưa từ Open-Meteo làm baseline
    baseline_rain = wx["precipitation"]

    # ── 3. Metadata Radar (RainViewer) ───────────────────────────────────
    try:
        rv_meta     = requests.get("https://api.rainviewer.com/public/weather-maps.json", timeout=5).json()
        host        = rv_meta["host"]
        past_frames = rv_meta["radar"]["past"]
        if len(past_frames) < 2:
            raise Exception("Không đủ khung hình radar.")
        frame_old = past_frames[-2]
        frame_new = past_frames[-1]
        result["details"]["rainviewer_host"] = host
        result["details"]["rainviewer_path"] = frame_new["path"]
        time_diff_sec = frame_new["time"] - frame_old["time"]
        if time_diff_sec <= 0:
            time_diff_sec = 600
    except Exception as e:
        result["status"]  = "ERROR"
        result["message"] = f"Lỗi metadata Radar: {e}"
        return result

    # ── 4. Tải & phân tích tile Radar ────────────────────────────────────
    xtile, ytile = deg2num(target_lat, target_lon, ZOOM_LEVEL)
    uX, uY       = get_pixel_coords(target_lat, target_lon, ZOOM_LEVEL, xtile, ytile)
    km_per_pixel = (math.cos(math.radians(target_lat)) * 40075) / ((2**ZOOM_LEVEL) * 512)

    alpha_old = fetch_radar_frame(host, frame_old["path"], xtile, ytile)
    alpha_new = fetch_radar_frame(host, frame_new["path"], xtile, ytile)

    if alpha_new is None:
        result["status"]  = "ERROR"
        result["message"] = "Không thể tải ảnh Radar từ RainViewer."
        return result

    cloud_old = find_largest_cloud(alpha_old) if alpha_old is not None else None
    cloud_new = find_largest_cloud(alpha_new)

    # ── 5. Phân tích vector mây ───────────────────────────────────────────
    if cloud_new:
        cX_new, cY_new, _, _ = cloud_new

        dist_px     = math.sqrt((uX - cX_new)**2 + (uY - cY_new)**2)
        distance_km = dist_px * km_per_pixel
        result["details"]["cloud_distance"] = round(distance_km, 2)

        # Tọa độ thực của tâm mây → để Leaflet vẽ marker
        cloud_lat, cloud_lon = pixel_to_latlon(cX_new, cY_new, xtile, ytile, ZOOM_LEVEL)
        result["details"]["cloud_lat"] = round(cloud_lat, 4)
        result["details"]["cloud_lon"] = round(cloud_lon, 4)

        # Lượng mưa tại vùng mây (Open-Meteo)
        rain_mm = get_vrain_rainfall(cloud_lat, cloud_lon)
        # Dùng giá trị lớn hơn giữa vị trí nhà và vị trí mây
        rain_mm = max(rain_mm, baseline_rain)
        result["details"]["rain_mm"] = round(rain_mm, 2)

        # Vector chuyển động mây
        cloud_speed_kph  = 0.0
        is_heading_towards = False

        if cloud_old:
            cX_old, cY_old, _, _ = cloud_old
            move_px = math.sqrt((cX_new - cX_old)**2 + (cY_new - cY_old)**2)
            move_km = move_px * km_per_pixel

            if move_km > 0.1:
                cloud_speed_kph = (move_km / time_diff_sec) * 3600
                result["details"]["cloud_speed"] = round(cloud_speed_kph, 1)

                dx_move = cX_new - cX_old
                dy_move = cY_new - cY_old
                dx_home = uX - cX_new
                dy_home = uY - cY_new

                dot      = dx_move * dx_home + dy_move * dy_home
                mag_move = math.sqrt(dx_move**2 + dy_move**2)
                mag_home = math.sqrt(dx_home**2 + dy_home**2)

                if mag_move > 0 and mag_home > 0:
                    cos_a = max(-1.0, min(1.0, dot / (mag_move * mag_home)))
                    angle_deg          = math.degrees(math.acos(cos_a))
                    is_heading_towards = angle_deg < 45

        # ── 6. Phán quyết cuối cùng ──────────────────────────────────────
        is_raining_hard   = rain_mm >= 0.5
        cloud_moving      = cloud_speed_kph > 1.0
        rain_prob_high    = wx["precipitation_probability"] >= 40

        if is_heading_towards and cloud_moving and (is_raining_hard or rain_prob_high):
            if distance_km > 0 and cloud_speed_kph > 0:
                eta_minutes = int((distance_km / cloud_speed_kph) * 60)
            else:
                eta_minutes = 0
            result["details"]["eta_minutes"] = eta_minutes

            h = eta_minutes // 60
            m = eta_minutes % 60
            eta_str = f"{h}h{m:02d}p" if h > 0 else f"{m}p"

            if distance_km < 5:
                result["status"]  = "DANGER"
                result["message"] = f"⛈️ Mưa đang đổ xuống khu vực của bạn!"
            else:
                result["status"]  = "WARNING"
                result["message"] = f"🌧️ Mây đen đang tiến vào! Dự kiến {eta_str} nữa có mưa."
        elif is_raining_hard and not is_heading_towards:
            result["status"]  = "SAFE"
            result["message"] = "🌥️ Mây đang mưa nhưng hướng lệch khỏi khu vực bạn."
        elif rain_prob_high and not is_heading_towards:
            result["status"]  = "SAFE"
            result["message"] = f"☁️ Xác suất mưa {wx['precipitation_probability']}% nhưng mây không tiến về phía bạn."
        else:
            result["status"]  = "SAFE"
            result["message"] = "✅ Bầu trời ổn định, không có nguy cơ mưa."
    else:
        result["status"]  = "SAFE"
        result["message"] = "🌤️ Trời quang mây tạnh, hoàn toàn an toàn."

    # ── 7. Gửi Discord (Anti-Spam tích hợp trong discord_alert) ──────────
    d = result["details"]
    if result["status"] == "DANGER":
        prob_str  = f"{d.get('precipitation_probability', 0)}%"
        temp_str  = f"{d.get('temperature', '--')}°C"
        details_str = (
            f"🌡️ Nhiệt độ: {temp_str} (Cảm giác {d.get('feels_like','--')}°C)\n"
            f"💧 Độ ẩm: {d.get('humidity','--')}%\n"
            f"🌧️ Lượng mưa: {d.get('rain_mm', 0):.1f} mm\n"
            f"🎲 Xác suất mưa: {prob_str}\n"
            f"💨 Tốc độ mây: {d.get('cloud_speed', 0):.1f} km/h\n"
            f"📏 Khoảng cách: {d.get('cloud_distance', 0):.1f} km"
        )
        if d.get("eta_minutes"):
            h = d["eta_minutes"] // 60
            m = d["eta_minutes"] % 60
            eta_str = f"{h}h{m:02d}p" if h > 0 else f"{m}p"
            details_str += f"\n⏱️ ETA: {eta_str}"
        send_discord_alert("DANGER", result["message"], details_str)
    else:
        send_discord_alert("SAFE", "", "")

    return result

if __name__ == "__main__":
    res = run_analysis()
    print(f"Status: {res['status']}")
    print(f"Message: {res['message']}")
    import json
    print(json.dumps(res["details"], ensure_ascii=False, indent=2))