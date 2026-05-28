import math
import time
import json
import cv2
import numpy as np
import requests
import os
import sys
from vrain_fetcher import get_vrain_rainfall, get_weather_data
from discord_alert import send_discord_alert

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


OWM_API_KEY = "caba72153195e76e835b0e35a82e4edb"
ZOOM_LEVEL = 7
PATH_RAIN_SAMPLE_COUNT = 3
MAX_CLOUD_CANDIDATES = 5
FULL_ANALYSIS_CANDIDATES = 3
RISK_HISTORY_LIMIT = 8
DANGER_ENTER_SCORE = 75
DANGER_IMMEDIATE_SCORE = 85
DANGER_EXIT_SCORE = 58
WARNING_ENTER_SCORE = 40

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RISK_HISTORY_FILE = os.path.join(BASE_DIR, "risk_history.json")

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
    if alpha_channel is None:
        return None
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

def find_cloud_candidates(alpha_channel, limit=MAX_CLOUD_CANDIDATES):
    if alpha_channel is None:
        return []
    _, thresh = cv2.threshold(alpha_channel, 30, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < 35:
            continue
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        mask = np.zeros(alpha_channel.shape, dtype=np.uint8)
        cv2.drawContours(mask, [c], -1, 255, -1)
        mean_alpha = float(cv2.mean(alpha_channel, mask=mask)[0])
        candidates.append({
            "x": cx,
            "y": cy,
            "contour": c,
            "area": float(area),
            "mean_alpha": round(mean_alpha, 1),
        })
    candidates.sort(key=lambda item: item["area"] * item["mean_alpha"], reverse=True)
    return candidates[:limit]

def analyze_radar_rings(alpha_channel, target_x, target_y, km_per_pixel):
    rings = [(0, 5), (5, 15), (15, 30), (30, 60)]
    yy, xx = np.ogrid[:alpha_channel.shape[0], :alpha_channel.shape[1]]
    dist_px = np.sqrt((xx - target_x) ** 2 + (yy - target_y) ** 2)
    result = []
    for inner_km, outer_km in rings:
        inner_px = inner_km / km_per_pixel
        outer_px = outer_km / km_per_pixel
        mask = (dist_px >= inner_px) & (dist_px < outer_px)
        total = int(np.count_nonzero(mask))
        if total == 0:
            rainy_ratio = 0.0
            mean_alpha = 0.0
        else:
            values = alpha_channel[mask]
            rainy = values > 30
            rainy_ratio = float(np.count_nonzero(rainy) / total)
            mean_alpha = float(values[rainy].mean()) if np.any(rainy) else 0.0
        result.append({
            "range_km": f"{inner_km}-{outer_km}",
            "rainy_ratio": round(rainy_ratio, 4),
            "mean_alpha": round(mean_alpha, 1),
        })
    return result

def radar_ring_score(radar_rings):
    score = 0
    reasons = []
    weights = {"0-5": 42, "5-15": 28, "15-30": 16, "30-60": 8}
    labels = {
        "0-5": "Radar thấy mưa trong vòng 5km",
        "5-15": "Radar thấy mưa trong vòng 15km",
        "15-30": "Radar thấy mưa trong vòng 30km",
        "30-60": "Radar thấy mưa ở vùng xa hơn",
    }
    for ring in radar_rings:
        key = ring["range_km"]
        ratio = ring["rainy_ratio"]
        if ratio <= 0:
            continue
        contribution = int(clamp(ratio * weights.get(key, 0) * 8, 0, weights.get(key, 0)))
        score += contribution
        if contribution >= 4:
            reasons.append(labels.get(key, f"Radar có mưa vùng {key}km"))
    return int(clamp(score, 0, 45)), reasons

def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))

def interpolate_latlon(lat1, lon1, lat2, lon2, ratio):
    return lat1 + (lat2 - lat1) * ratio, lon1 + (lon2 - lon1) * ratio

def format_eta(minutes):
    h = int(minutes) // 60
    m = int(minutes) % 60
    return f"{h}h{m:02d}p" if h > 0 else f"{m}p"

def sample_path_rain(cloud_lat, cloud_lon, target_lat, target_lon):
    """
    Lấy mưa tại vài điểm trên đường mây bay vào vị trí theo dõi.
    Dùng Open-Meteo miễn phí qua get_vrain_rainfall, nên giới hạn số điểm để nhẹ API.
    """
    points = []
    values = []
    for i in range(1, PATH_RAIN_SAMPLE_COUNT + 1):
        ratio = i / (PATH_RAIN_SAMPLE_COUNT + 1)
        lat, lon = interpolate_latlon(cloud_lat, cloud_lon, target_lat, target_lon, ratio)
        rain = get_vrain_rainfall(lat, lon)
        points.append({"lat": round(lat, 4), "lon": round(lon, 4), "rain_mm": round(rain, 2)})
        values.append(rain)

    return {
        "points": points,
        "max": max(values) if values else 0.0,
        "avg": (sum(values) / len(values)) if values else 0.0,
    }

def load_risk_history():
    if not os.path.exists(RISK_HISTORY_FILE):
        return []
    try:
        with open(RISK_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []

def smooth_risk_score(raw_risk, target_lat, target_lon):
    now = time.time()
    history = [
        item for item in load_risk_history()
        if now - float(item.get("timestamp", 0) or 0) <= 3600
    ]
    recent_same_place = [
        item for item in history
        if abs(float(item.get("target_lat", 0)) - target_lat) < 0.02
        and abs(float(item.get("target_lon", 0)) - target_lon) < 0.02
    ]

    previous_scores = [float(item.get("risk_score", 0) or 0) for item in recent_same_place[-3:]]
    if len(previous_scores) >= 2:
        smoothed = raw_risk * 0.55 + previous_scores[-1] * 0.30 + previous_scores[-2] * 0.15
    elif previous_scores:
        smoothed = raw_risk * 0.70 + previous_scores[-1] * 0.30
    else:
        smoothed = raw_risk

    previous = previous_scores[-1] if previous_scores else raw_risk
    delta = int(round(raw_risk - previous))
    if delta >= 8:
        trend = "rising"
    elif delta <= -8:
        trend = "falling"
    else:
        trend = "stable"

    return int(round(clamp(smoothed, 0, 100))), trend, delta

def save_risk_history(raw_risk, risk_score, status, target_lat, target_lon, danger_pending=False):
    history = load_risk_history()
    history.append({
        "timestamp": time.time(),
        "target_lat": target_lat,
        "target_lon": target_lon,
        "raw_risk_score": int(round(raw_risk)),
        "risk_score": int(round(risk_score)),
        "status": status,
        "danger_pending": bool(danger_pending),
    })
    history = history[-RISK_HISTORY_LIMIT:]
    try:
        with open(RISK_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def recent_danger_active(target_lat, target_lon):
    now = time.time()
    for item in reversed(load_risk_history()):
        if now - float(item.get("timestamp", 0) or 0) > 45 * 60:
            continue
        if abs(float(item.get("target_lat", 0)) - target_lat) >= 0.02:
            continue
        if abs(float(item.get("target_lon", 0)) - target_lon) >= 0.02:
            continue
        if item.get("status") == "DANGER":
            return True
    return False

def recent_danger_pending(target_lat, target_lon):
    now = time.time()
    for item in reversed(load_risk_history()):
        if now - float(item.get("timestamp", 0) or 0) > 15 * 60:
            continue
        if abs(float(item.get("target_lat", 0)) - target_lat) >= 0.02:
            continue
        if abs(float(item.get("target_lon", 0)) - target_lon) >= 0.02:
            continue
        return bool(item.get("danger_pending")) or item.get("status") == "DANGER"
    return False

def choose_status(risk_score, baseline_rain, distance_km=None, rain_mm=0.0, target_lat=None, target_lon=None):
    in_danger_session = (
        target_lat is not None
        and target_lon is not None
        and recent_danger_active(target_lat, target_lon)
    )
    near_active_rain = distance_km is not None and distance_km <= 5 and rain_mm >= 0.1
    has_recent_pending = (
        target_lat is not None
        and target_lon is not None
        and recent_danger_pending(target_lat, target_lon)
    )

    if baseline_rain >= 0.5 or near_active_rain:
        return "DANGER", False
    if in_danger_session:
        status = "DANGER" if risk_score >= DANGER_EXIT_SCORE else ("WARNING" if risk_score >= WARNING_ENTER_SCORE else "SAFE")
        return status, False
    if risk_score >= DANGER_IMMEDIATE_SCORE:
        return "DANGER", False
    if risk_score >= DANGER_ENTER_SCORE:
        if baseline_rain >= 0.1 or has_recent_pending:
            return "DANGER", False
        return "WARNING", True
    if risk_score >= WARNING_ENTER_SCORE:
        return "WARNING", False
    if baseline_rain >= 0.1:
        return "WARNING", False
    return "SAFE", False

def score_nowcast(distance_km, cloud_speed_kph, approach_angle_deg, rain_mm, path_rain, wx, eta_minutes, radar_rings=None):
    risk = 0
    reasons = []

    prob = int(wx.get("precipitation_probability", 0) or 0)
    local_rain = float(wx.get("precipitation", 0.0) or 0.0)
    path_max = float(path_rain.get("max", 0.0) or 0.0)
    path_avg = float(path_rain.get("avg", 0.0) or 0.0)
    ring_score, ring_reasons = radar_ring_score(radar_rings or [])
    risk += ring_score
    reasons.extend(ring_reasons[:2])

    if distance_km <= 5:
        risk += 35
        reasons.append("Vùng mưa rất gần vị trí theo dõi")
    elif distance_km <= 15:
        risk += 25
        reasons.append("Vùng mưa ở trong bán kính 15km")
    elif distance_km <= 35:
        risk += 16
        reasons.append("Có vùng mưa trong bán kính 35km")
    elif distance_km <= 70:
        risk += 8
        reasons.append("Có vùng mưa ở xa hơn nhưng vẫn cần theo dõi")

    if approach_angle_deg is not None:
        if approach_angle_deg <= 25:
            risk += 26
            reasons.append("Vector mây đang tiến thẳng về vị trí theo dõi")
        elif approach_angle_deg <= 45:
            risk += 18
            reasons.append("Vector mây có xu hướng tiến về vị trí theo dõi")
        elif approach_angle_deg <= 70:
            risk += 8
            reasons.append("Vector mây hơi lệch nhưng vẫn có khả năng ảnh hưởng")

    if cloud_speed_kph >= 80:
        risk += 8
        reasons.append("Mây di chuyển nhanh")
    elif cloud_speed_kph >= 20:
        risk += 5
        reasons.append("Mây đang có chuyển động rõ")

    if rain_mm >= 2.0:
        risk += 24
        reasons.append("Cường độ mưa tại vùng mây cao")
    elif rain_mm >= 0.5:
        risk += 16
        reasons.append("Vùng mây có mưa đáng kể")
    elif rain_mm >= 0.1:
        risk += 8
        reasons.append("Vùng mây có tín hiệu mưa nhẹ")

    if path_max >= 1.0:
        risk += 18
        reasons.append("Dọc đường mây bay vào đang có mưa")
    elif path_max >= 0.3 or path_avg >= 0.15:
        risk += 12
        reasons.append("Dọc đường mây bay vào có tín hiệu mưa")

    if local_rain >= 0.5:
        risk += 18
        reasons.append("Ngay vị trí theo dõi đã có mưa")
    elif local_rain >= 0.1:
        risk += 8
        reasons.append("Ngay vị trí theo dõi có mưa nhẹ")

    if prob >= 75:
        risk += 16
        reasons.append(f"Dự báo giờ tới xác suất mưa cao ({prob}%)")
    elif prob >= 50:
        risk += 10
        reasons.append(f"Dự báo giờ tới xác suất mưa tăng ({prob}%)")
    elif prob >= 35:
        risk += 5
        reasons.append(f"Dự báo giờ tới có khả năng mưa ({prob}%)")

    if eta_minutes is not None:
        if eta_minutes <= 20:
            risk += 18
            reasons.append(f"ETA rất gần, khoảng {format_eta(eta_minutes)}")
        elif eta_minutes <= 45:
            risk += 12
            reasons.append(f"ETA khoảng {format_eta(eta_minutes)}")
        elif eta_minutes <= 90:
            risk += 6
            reasons.append(f"ETA xa hơn, khoảng {format_eta(eta_minutes)}")

    risk = int(clamp(risk, 0, 100))
    signal_count = sum([
        distance_km > 0,
        approach_angle_deg is not None,
        cloud_speed_kph > 1,
        rain_mm > 0,
        path_max > 0,
        prob > 0,
    ])
    confidence = clamp(0.35 + signal_count * 0.1, 0.35, 0.95)
    return risk, round(confidence, 2), reasons

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
            "risk_score": 0,
            "confidence": 0.0,
            "approach_angle_deg": None,
            "path_rain_mm": 0.0,
            "path_rain_avg": 0.0,
            "path_rain_points": [],
            "radar_rings": [],
            "cloud_candidates": [],
            "raw_risk_score": 0,
            "risk_trend": "stable",
            "risk_delta": 0,
            "analysis_reasons": [],
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
        analysis_frames = past_frames[-6:]
        frame_old = analysis_frames[0]
        frame_new = past_frames[-1]
        result["details"]["rainviewer_host"] = host
        result["details"]["rainviewer_path"] = frame_new["path"]
    except Exception as e:
        result["status"]  = "ERROR"
        result["message"] = f"Lỗi metadata Radar: {e}"
        return result

    # ── 4. Tải & phân tích tile Radar ────────────────────────────────────
    xtile, ytile = deg2num(target_lat, target_lon, ZOOM_LEVEL)
    uX, uY       = get_pixel_coords(target_lat, target_lon, ZOOM_LEVEL, xtile, ytile)
    km_per_pixel = (math.cos(math.radians(target_lat)) * 40075) / ((2**ZOOM_LEVEL) * 512)

    cloud_tracks = []
    for frame in analysis_frames:
        alpha = fetch_radar_frame(host, frame["path"], xtile, ytile)
        cloud = find_largest_cloud(alpha)
        if cloud:
            cX, cY, _, area = cloud
            cloud_tracks.append({
                "time": frame["time"],
                "x": cX,
                "y": cY,
                "area": area,
            })

    alpha_new = fetch_radar_frame(host, frame_new["path"], xtile, ytile)

    if alpha_new is None:
        result["status"]  = "ERROR"
        result["message"] = "Không thể tải ảnh Radar từ RainViewer."
        return result

    radar_rings = analyze_radar_rings(alpha_new, uX, uY, km_per_pixel)
    result["details"]["radar_rings"] = radar_rings
    cloud_candidates = find_cloud_candidates(alpha_new)
    result["details"]["cloud_candidates"] = [
        {
            "distance_km": round(math.sqrt((uX - c["x"])**2 + (uY - c["y"])**2) * km_per_pixel, 2),
            "area": round(c["area"], 1),
            "mean_alpha": c["mean_alpha"],
        }
        for c in cloud_candidates
    ]
    cloud_new = cloud_candidates[0] if cloud_candidates else None

    # ── 5. Phân tích nhiều cụm mây và chọn cụm nguy hiểm nhất ─────────────
    if cloud_new:
        best_analysis = None
        movement = None
        if len(cloud_tracks) >= 2:
            first = cloud_tracks[0]
            last = cloud_tracks[-1]
            elapsed = max(1, last["time"] - first["time"])
            dx_move = last["x"] - first["x"]
            dy_move = last["y"] - first["y"]
            move_px = math.sqrt(dx_move**2 + dy_move**2)
            move_km = move_px * km_per_pixel
            if move_km > 0.1:
                movement = {
                    "dx": dx_move,
                    "dy": dy_move,
                    "speed_kph": (move_km / elapsed) * 3600,
                }

        ranked_candidates = sorted(
            cloud_candidates[:MAX_CLOUD_CANDIDATES],
            key=lambda c: (
                clamp(80 - math.sqrt((uX - c["x"])**2 + (uY - c["y"])**2) * km_per_pixel, 0, 80)
                + clamp((c["area"] * c["mean_alpha"]) / 4000, 0, 40)
            ),
            reverse=True,
        )

        for candidate in ranked_candidates[:FULL_ANALYSIS_CANDIDATES]:
            cX_new = candidate["x"]
            cY_new = candidate["y"]
            dist_px = math.sqrt((uX - cX_new)**2 + (uY - cY_new)**2)
            distance_km = dist_px * km_per_pixel
            cloud_lat, cloud_lon = pixel_to_latlon(cX_new, cY_new, xtile, ytile, ZOOM_LEVEL)

            cloud_speed_kph = 0.0
            approach_angle_deg = None
            eta_minutes = None
            if movement:
                cloud_speed_kph = movement["speed_kph"]
                dx_home = uX - cX_new
                dy_home = uY - cY_new
                dot = movement["dx"] * dx_home + movement["dy"] * dy_home
                mag_move = math.sqrt(movement["dx"]**2 + movement["dy"]**2)
                mag_home = math.sqrt(dx_home**2 + dy_home**2)
                if mag_move > 0 and mag_home > 0:
                    cos_a = max(-1.0, min(1.0, dot / (mag_move * mag_home)))
                    approach_angle_deg = math.degrees(math.acos(cos_a))
                if distance_km > 0 and cloud_speed_kph > 1 and approach_angle_deg is not None and approach_angle_deg <= 70:
                    eta_minutes = int((distance_km / cloud_speed_kph) * 60)

            rain_mm = max(get_vrain_rainfall(cloud_lat, cloud_lon), baseline_rain)
            path_rain = sample_path_rain(cloud_lat, cloud_lon, target_lat, target_lon)
            rain_mm = max(rain_mm, path_rain["max"])

            raw_risk, confidence, reasons = score_nowcast(
                distance_km=distance_km,
                cloud_speed_kph=cloud_speed_kph,
                approach_angle_deg=approach_angle_deg,
                rain_mm=rain_mm,
                path_rain=path_rain,
                wx=wx,
                eta_minutes=eta_minutes,
                radar_rings=radar_rings,
            )

            analysis = {
                "raw_risk_score": raw_risk,
                "confidence": confidence,
                "reasons": reasons,
                "distance_km": distance_km,
                "cloud_lat": cloud_lat,
                "cloud_lon": cloud_lon,
                "rain_mm": rain_mm,
                "path_rain": path_rain,
                "cloud_speed_kph": cloud_speed_kph,
                "approach_angle_deg": approach_angle_deg,
                "eta_minutes": eta_minutes,
                "candidate": candidate,
            }
            if best_analysis is None or raw_risk > best_analysis["raw_risk_score"]:
                best_analysis = analysis

        raw_risk = best_analysis["raw_risk_score"]
        risk_score, risk_trend, risk_delta = smooth_risk_score(raw_risk, target_lat, target_lon)
        reasons = best_analysis["reasons"]
        if risk_trend == "rising":
            reasons.insert(0, f"Điểm rủi ro đang tăng nhanh (+{risk_delta})")
        elif risk_trend == "falling":
            reasons.insert(0, f"Điểm rủi ro đang giảm ({risk_delta})")

        # Nếu mưa đang diễn ra ngay tại vị trí (baseline_rain hoặc rain_mm cao),
        # đặt marker mây ngay lên vị trí theo dõi để UI hiển thị mây "trên đầu".
        raining_here = (baseline_rain >= 0.5) or (best_analysis.get("rain_mm", 0) >= 0.5)

        if raining_here:
            # Khi đang mưa tại vị trí, cloud đặt vào tọa độ target
            result["details"]["cloud_distance"] = 0.0
            result["details"]["cloud_lat"] = round(target_lat, 4)
            result["details"]["cloud_lon"] = round(target_lon, 4)
            # Mưa trên đầu → ETA = 0
            result["details"]["eta_minutes"] = 0
        else:
            result["details"]["cloud_distance"] = round(best_analysis["distance_km"], 2)
            result["details"]["cloud_lat"] = round(best_analysis["cloud_lat"], 4)
            result["details"]["cloud_lon"] = round(best_analysis["cloud_lon"], 4)
        result["details"]["rain_mm"] = round(best_analysis["rain_mm"], 2)
        result["details"]["cloud_speed"] = round(best_analysis["cloud_speed_kph"], 1)
        result["details"]["approach_angle_deg"] = (
            round(best_analysis["approach_angle_deg"], 1)
            if best_analysis["approach_angle_deg"] is not None else None
        )
        # Nếu chưa set eta above (raining_here sets to 0), keep best_analysis otherwise
        if not result["details"].get("eta_minutes"):
            result["details"]["eta_minutes"] = best_analysis["eta_minutes"] or 0
        result["details"]["path_rain_mm"] = round(best_analysis["path_rain"]["max"], 2)
        result["details"]["path_rain_avg"] = round(best_analysis["path_rain"]["avg"], 2)
        result["details"]["path_rain_points"] = best_analysis["path_rain"]["points"]
        result["details"]["raw_risk_score"] = raw_risk
        result["details"]["risk_score"] = risk_score
        result["details"]["risk_trend"] = risk_trend
        result["details"]["risk_delta"] = risk_delta
        result["details"]["confidence"] = best_analysis["confidence"]
        result["details"]["analysis_reasons"] = reasons[:5]

        eta_text = format_eta(best_analysis["eta_minutes"]) if best_analysis["eta_minutes"] is not None else "chưa rõ"
        status, danger_pending = choose_status(
            risk_score,
            baseline_rain,
            distance_km=best_analysis["distance_km"],
            rain_mm=best_analysis["rain_mm"],
            target_lat=target_lat,
            target_lon=target_lon,
        )
        if danger_pending:
            reasons.insert(0, "Tín hiệu gần DANGER, đang chờ xác nhận ở lần quét kế tiếp")
            result["details"]["analysis_reasons"] = reasons[:5]
        save_risk_history(raw_risk, risk_score, status, target_lat, target_lon, danger_pending=danger_pending)

        if status == "DANGER":
            result["status"] = "DANGER"
            result["message"] = f"⛈️ Nguy cơ mưa cao ({risk_score}/100). ETA {eta_text}."
        elif status == "WARNING":
            result["status"] = "WARNING"
            result["message"] = f"🌧️ Có tín hiệu mưa cần theo dõi ({risk_score}/100). ETA {eta_text}."
        else:
            result["status"] = "SAFE"
            if reasons:
                result["message"] = f"✅ Rủi ro thấp ({risk_score}/100). {reasons[0]}."
            else:
                result["message"] = "✅ Bầu trời ổn định, chưa có tín hiệu mưa đáng kể."
        # Nếu an toàn (SAFE) thì ẩn marker mây để UI không vẽ cloud
        if result.get("status") == "SAFE":
            result["details"]["cloud_lat"] = None
            result["details"]["cloud_lon"] = None
            result["details"]["cloud_distance"] = 0.0
    else:
        ring_score, ring_reasons = radar_ring_score(radar_rings)
        raw_risk = ring_score
        if baseline_rain >= 0.5:
            raw_risk += 35
            ring_reasons.insert(0, "Ngay vị trí theo dõi đã có mưa")
        elif baseline_rain >= 0.1:
            raw_risk += 12
            ring_reasons.insert(0, "Ngay vị trí theo dõi có mưa nhẹ")
        raw_risk = int(clamp(raw_risk, 0, 100))
        risk_score, risk_trend, risk_delta = smooth_risk_score(raw_risk, target_lat, target_lon)
        result["details"]["raw_risk_score"] = raw_risk
        result["details"]["risk_score"] = risk_score
        result["details"]["risk_trend"] = risk_trend
        result["details"]["risk_delta"] = risk_delta
        result["details"]["confidence"] = 0.45 if ring_score else 0.35
        result["details"]["analysis_reasons"] = ring_reasons[:5]
        status, danger_pending = choose_status(risk_score, baseline_rain, target_lat=target_lat, target_lon=target_lon)
        if danger_pending:
            ring_reasons.insert(0, "Tín hiệu gần DANGER, đang chờ xác nhận ở lần quét kế tiếp")
            result["details"]["analysis_reasons"] = ring_reasons[:5]
        save_risk_history(raw_risk, risk_score, status, target_lat, target_lon, danger_pending=danger_pending)

        if status == "DANGER":
            result["status"] = "DANGER"
            result["message"] = f"⛈️ Radar quanh vị trí có tín hiệu mưa mạnh ({risk_score}/100)."
        elif status == "WARNING":
            result["status"] = "WARNING"
            result["message"] = f"🌧️ Radar quanh vị trí có tín hiệu cần theo dõi ({risk_score}/100)."
        else:
            result["status"] = "SAFE"
            result["message"] = "🌤️ Trời quang mây tạnh, hoàn toàn an toàn."

    # ── 7. Gửi Discord (Anti-Spam tích hợp trong discord_alert) ──────────
    d = result["details"]
    if result["status"] == "DANGER":
        prob_str  = f"{d.get('precipitation_probability', 0)}%"
        temp_str  = f"{d.get('temperature', '--')}°C"
        reasons = d.get("analysis_reasons", [])
        reasons_str = "\n".join([f"• {r}" for r in reasons]) if reasons else "• Chưa có lý do nổi bật"
        details_str = (
            f"🌡️ Nhiệt độ: {temp_str} (Cảm giác {d.get('feels_like','--')}°C)\n"
            f"💧 Độ ẩm: {d.get('humidity','--')}%\n"
            f"🧠 Điểm rủi ro: {d.get('risk_score', 0)}/100 (tin cậy {int(d.get('confidence', 0) * 100)}%)\n"
            f"🌧️ Lượng mưa: {d.get('rain_mm', 0):.1f} mm\n"
            f"🛣️ Mưa dọc đường mây: {d.get('path_rain_mm', 0):.1f} mm\n"
            f"🎲 Xác suất mưa: {prob_str}\n"
            f"💨 Tốc độ mây: {d.get('cloud_speed', 0):.1f} km/h\n"
            f"📏 Khoảng cách: {d.get('cloud_distance', 0):.1f} km\n"
            f"🧭 Góc tiến vào: {d.get('approach_angle_deg', '--')}°\n"
            f"📌 Lý do:\n{reasons_str}"
        )
        if d.get("eta_minutes"):
            details_str += f"\n⏱️ ETA: {format_eta(d['eta_minutes'])}"
        send_discord_alert("DANGER", result["message"], details_str)
    else:
        send_discord_alert(result["status"], "", "")

    return result

if __name__ == "__main__":
    res = run_analysis()
    print(f"Status: {res['status']}")
    print(f"Message: {res['message']}")
    import json
    print(json.dumps(res["details"], ensure_ascii=False, indent=2))
