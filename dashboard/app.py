from flask import Flask, render_template, jsonify, request, make_response, send_from_directory
import json
import os
import subprocess
import threading
import time

app = Flask(__name__, static_folder='asset', static_url_path='/asset')
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Dictionary to store process objects
processes = {}
process_logs = {}
AUTO_START_TOOLS = ['lock_tracker']


@app.route('/asset/<path:filename>')
def asset_file(filename):
    return send_from_directory(app.static_folder, filename)


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.static_folder, 'favicon'),
        'my-tools-favicon.png',
        mimetype='image/png'
    )


def load_config():
    with open('tools_config.json', 'r', encoding='utf-8') as f:
        return json.load(f)


def get_tool_config(tool_id):
    config = load_config()
    return next((t for t in config if t['id'] == tool_id), None)


def launch_tool(tool):
    tool_id = tool['id']
    if tool_id in processes and processes[tool_id].poll() is None:
        raise RuntimeError(f"Tool {tool_id} is already running")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    tool_dir = os.path.normpath(os.path.join(base_dir, tool['directory']))
    command = tool['command'].split()

    process_logs[tool_id] = [
        f"--- STARTING TOOL: {tool['name']} ---",
        f"Directory: {tool_dir}",
        f"Command: {tool['command']}",
        "---------------------------------------"
    ]

    if not os.path.exists(tool_dir):
        process_logs[tool_id].append(f"ERROR: Directory not found: {tool_dir}")
        raise FileNotFoundError(f"Directory not found: {tool['directory']}")

    flags = 0
    if tool.get('has_gui', False):
        if os.name == 'nt':
            flags = subprocess.CREATE_NEW_CONSOLE

        proc = subprocess.Popen(
            command,
            cwd=tool_dir,
            creationflags=flags
        )
    else:
        if os.name == 'nt':
            flags = 0x08000000

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        proc = subprocess.Popen(
            command,
            cwd=tool_dir,
            creationflags=flags,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env
        )

        def read_logs(out, t_id):
            try:
                for line in iter(out.readline, b''):
                    if t_id in process_logs:
                        decoded = line.decode('utf-8', errors='ignore').rstrip()
                        if decoded == "---CLR---":
                            process_logs[t_id] = [
                                f"--- REFRESHING TOOL: {tool['name']} ---",
                                "---------------------------------------"
                            ]
                        else:
                            process_logs[t_id].append(decoded)
                            if len(process_logs[t_id]) > 500:
                                process_logs[t_id].pop(0)
            except Exception as e:
                if t_id in process_logs:
                    process_logs[t_id].append("[LOG ERROR] " + str(e))
            finally:
                out.close()
                proc.wait()
                if t_id in process_logs:
                    process_logs[t_id].append(f"--- PROCESS EXITED (Code: {proc.returncode}) ---")

        t = threading.Thread(target=read_logs, args=(proc.stdout, tool_id))
        t.daemon = True
        t.start()

    processes[tool_id] = proc
    return proc


def auto_start_tools():
    for tool_id in AUTO_START_TOOLS:
        tool = get_tool_config(tool_id)
        if not tool:
            continue
        try:
            launch_tool(tool)
        except Exception as e:
            print(f"Auto-start failed for {tool_id}: {e}")

@app.route('/')
def index():
    response = make_response(render_template('index.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# ==============================================================================
# NOWCAST ROUTES
# ==============================================================================
NOWCAST_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../weather_forecast'))
LOCK_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../lock_tracker'))

@app.route('/nowcast')
def nowcast_ui():
    return render_template('nowcast.html')

@app.route('/api/nowcast/status', methods=['GET'])
def get_nowcast_status():
    status_file = os.path.join(NOWCAST_DIR, 'latest_status.json')
    if os.path.exists(status_file):
        with open(status_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            try:
                saved_day = time.strftime('%Y-%m-%d', time.localtime(float(data.get('timestamp', 0))))
                if saved_day != time.strftime('%Y-%m-%d'):
                    os.remove(status_file)
                    return jsonify({"status": "WAITING", "message": "Dữ liệu thời tiết đã cũ. Đang quét lại...", "details": {}})
            except Exception:
                return jsonify({"status": "WAITING", "message": "Dữ liệu thời tiết không hợp lệ. Đang quét lại...", "details": {}})
            resp = make_response(jsonify(data))
            resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
            return resp
    return jsonify({"status": "WAITING", "message": "Chưa có dữ liệu. Đang quét...", "details": {}})

@app.route('/api/nowcast/settings', methods=['GET', 'POST'])
def nowcast_settings():
    settings_file = os.path.join(NOWCAST_DIR, 'settings.json')
    if request.method == 'GET':
        if os.path.exists(settings_file):
            with open(settings_file, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
        return jsonify({"target_lat": 10.8231, "target_lon": 106.6297, "location_name": "TP. Hồ Chí Minh"})
    
    # POST
    data = request.json
    with open(settings_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return jsonify({"success": True})

@app.route('/api/nowcast/image')
def nowcast_image():
    from flask import send_file
    img_path = os.path.join(NOWCAST_DIR, 'static', 'radar_analysis.png')
    if os.path.exists(img_path):
        return send_file(img_path, mimetype='image/png')
    return "No image", 404


# ======================================================================
# LOCK TRACKER UI + API
# ======================================================================
@app.route('/lock')
def lock_ui():
    return render_template('lock.html')


@app.route('/api/lock/status', methods=['GET'])
def get_lock_status():
    data_dir = os.path.join(LOCK_DIR, 'data')
    days = {}
    last_updated = 0

    if os.path.exists(data_dir):
        for filename in sorted(os.listdir(data_dir)):
            if not filename.endswith('.json'):
                continue
            path = os.path.join(data_dir, filename)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    month_data = json.load(f)
                for date_str, day_data in month_data.items():
                    days[date_str] = day_data
                last_updated = max(last_updated, int(os.path.getmtime(path)))
            except Exception:
                continue

    # Fall back to legacy lock_tracker.json if no monthly files exist
    if not days:
        db_file = os.path.join(LOCK_DIR, 'lock_tracker.json')
        if os.path.exists(db_file):
            try:
                with open(db_file, 'r', encoding='utf-8') as f:
                    legacy = json.load(f)
                days = legacy.get('days', {})
                last_updated = int(os.path.getmtime(db_file))
            except Exception as e:
                return jsonify({"status": "ERROR", "message": f"Failed to read DB: {e}", "details": {}}), 500

    if days:
        details = {}
        today = time.strftime('%Y-%m-%d')
        today_data = days.get(today, {"total_seconds": 0, "sessions": []})

        details['today_total_seconds'] = today_data.get('total_seconds', 0)
        details['today_sessions'] = today_data.get('sessions', [])

        history = []
        month_map = {}
        year_map = {}
        total_seconds = 0
        total_sessions = 0

        for date_str in sorted(days.keys()):
            day_data = days[date_str]
            total = day_data.get('total_seconds', 0)
            sessions = day_data.get('sessions', [])
            session_count = len(sessions)

            history.append({
                "date": date_str,
                "total_seconds": total,
                "session_count": session_count,
            })

            total_seconds += total
            total_sessions += session_count

            month_key = date_str[:7]
            year_key = date_str[:4]

            month_map.setdefault(month_key, {"total_seconds": 0, "session_count": 0})
            month_map[month_key]["total_seconds"] += total
            month_map[month_key]["session_count"] += session_count

            year_map.setdefault(year_key, {"total_seconds": 0, "session_count": 0})
            year_map[year_key]["total_seconds"] += total
            year_map[year_key]["session_count"] += session_count

        recent_history = history[-30:]
        details['history'] = history
        details['recent_history'] = recent_history
        details['days'] = days
        details['month_totals'] = [
            {"month": month, "total_seconds": month_map[month]["total_seconds"], "session_count": month_map[month]["session_count"]}
            for month in sorted(month_map.keys())
        ]
        details['year_totals'] = [
            {"year": year, "total_seconds": year_map[year]["total_seconds"], "session_count": year_map[year]["session_count"]}
            for year in sorted(year_map.keys())
        ]
        details['total_seconds'] = total_seconds
        details['total_sessions'] = total_sessions
        details['total_days'] = len(history)
        details['last_updated'] = last_updated or int(time.time())

        resp = make_response(jsonify({"status": "OK", "message": "OK", "details": details, "timestamp": details['last_updated']}))
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp

    return jsonify({"status": "WAITING", "message": "Chưa có dữ liệu. Chạy loctracker trước.", "details": {}})


@app.route('/api/tools', methods=['GET'])
def get_tools():
    config = load_config()
    for tool in config:
        tool_id = tool['id']
        is_running = False
        if tool_id in processes:
            # Check if process is still running
            if processes[tool_id].poll() is None:
                is_running = True
            else:
                # Process finished/crashed
                del processes[tool_id]
        
        tool['status'] = 'Running' if is_running else 'Stopped'
    
    return jsonify(config)

@app.route('/api/tools/<tool_id>/start', methods=['POST'])
def start_tool(tool_id):
    tool = get_tool_config(tool_id)
    if not tool:
        return jsonify({"success": False, "message": "Tool not found"}), 404

    try:
        if tool_id in processes and processes[tool_id].poll() is None:
            return jsonify({"success": False, "message": "Tool is already running"}), 400

        launch_tool(tool)
        return jsonify({"success": True, "message": f"Started {tool['name']}"})
    except FileNotFoundError as e:
        return jsonify({"success": False, "message": str(e)}), 404
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/tools/<tool_id>/logs', methods=['GET'])
def get_tool_logs(tool_id):
    logs = process_logs.get(tool_id, [])
    return jsonify({"logs": logs})

@app.route('/api/tools/<tool_id>/stop', methods=['POST'])
def stop_tool(tool_id):
    if tool_id not in processes or processes[tool_id].poll() is not None:
        return jsonify({"success": False, "message": "Tool is not running"}), 400
        
    try:
        proc = processes[tool_id]
        proc.terminate()
        proc.wait(timeout=3)
        del processes[tool_id]
        return jsonify({"success": True, "message": "Stopped tool"})
    except subprocess.TimeoutExpired:
        proc.kill()
        del processes[tool_id]
        return jsonify({"success": True, "message": "Force killed tool"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    def kill_server():
        # The "Nuclear" option for Windows: 
        # Kill the current process and all its children (/T) forcefully (/F)
        try:
            subprocess.call(['taskkill', '/F', '/T', '/PID', str(os.getpid())])
        except:
            os._exit(0)
        
    threading.Timer(0.5, kill_server).start()
    return jsonify({"success": True, "message": "System-wide shutdown initiated..."})

if __name__ == '__main__':
    auto_start_tools()
    app.run(host='0.0.0.0', port=1101, debug=False)
