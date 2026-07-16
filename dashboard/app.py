from flask import Flask, render_template, jsonify, request, make_response, send_from_directory, redirect, url_for
import json
import os
import subprocess
import threading
import time
import sys
import tempfile
import uuid
import re
import urllib.request
import urllib.error

NPM_PROJECTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'npm_projects.json')
npm_processes = {}

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
        
        # Start auto-start NPM projects if npm_manager is started
        if tool_id == 'npm_manager':
            try:
                if os.path.exists(NPM_PROJECTS_FILE):
                    with open(NPM_PROJECTS_FILE, 'r', encoding='utf-8') as f:
                        npm_projs = json.load(f)
                    for proj in npm_projs:
                        if proj.get('auto_start'):
                            try:
                                script = "dev"
                                if "dev" not in proj.get("scripts", {}):
                                    script = "start" if "start" in proj.get("scripts", {}) else list(proj.get("scripts", {}).keys())[0] if proj.get("scripts") else "dev"
                                start_npm_project_internal(proj, script)
                            except Exception as e:
                                print(f"Failed to auto-start NPM project {proj.get('name')}: {e}")
            except Exception as e:
                print(f"NPM auto-start failed: {e}")
                
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
        if os.name == 'nt':
            subprocess.call(['taskkill', '/F', '/T', '/PID', str(proc.pid)])
        else:
            proc.terminate()
            proc.wait(timeout=3)
        del processes[tool_id]
        
        if tool_id == 'npm_manager':
            for pid, pdata in list(npm_processes.items()):
                try:
                    npm_proc = pdata['process']
                    if os.name == 'nt':
                        subprocess.call(['taskkill', '/F', '/T', '/PID', str(npm_proc.pid)])
                    else:
                        npm_proc.terminate()
                except:
                    pass
                    
        return jsonify({"success": True, "message": "Stopped tool"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/tools/<tool_id>/open_log', methods=['POST'])
def open_log_in_notepadpp(tool_id):
    """Ghi log hiện tại ra file tạm và mở bằng Notepad++"""
    try:
        tool = get_tool_config(tool_id)
        tool_name = tool['name'] if tool else tool_id
        # Đặc thù cho scan_network: mở file CSV thay vì log console
        if tool_id == 'scan_network':
            base_dir = os.path.dirname(os.path.abspath(__file__))
            log_filename = os.path.normpath(os.path.join(base_dir, '..', 'network_monitor', 'pc_name_cache.csv'))
            if not os.path.exists(log_filename):
                return jsonify({"success": False, "message": "File pc_name_cache.csv chưa được tạo"})
        else:
            # Các tool khác: Luôn tạo file log dù log rỗng
            logs = process_logs.get(tool_id, [])
            log_text = '\n'.join(logs) if logs else f"[{tool_name}] Chưa có log. Tool chưa được start hoặc chưa có output."

            # Ghi ra file tạm
            tmp_dir = tempfile.gettempdir()
            log_filename = os.path.join(tmp_dir, f"mytools_{tool_id}.log")
            with open(log_filename, 'w', encoding='utf-8') as f:
                f.write(log_text)

        # Tìm Notepad++ — thử registry trước, sau đó các path phổ biến
        npp_exe = None
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\notepad++.exe")
            npp_exe, _ = winreg.QueryValueEx(key, "")
            winreg.CloseKey(key)
        except Exception:
            pass

        if not npp_exe or not os.path.exists(npp_exe):
            for p in [
                r"C:\Program Files\Notepad++\notepad++.exe",
                r"C:\Program Files (x86)\Notepad++\notepad++.exe",
            ]:
                if os.path.exists(p):
                    npp_exe = p
                    break

        if npp_exe and os.path.exists(npp_exe):
            subprocess.Popen([npp_exe, log_filename])
            return jsonify({"success": True, "message": f"Đã mở log [{tool_name}] trong Notepad++"})
        else:
            subprocess.Popen(['notepad.exe', log_filename])
            return jsonify({"success": True, "message": "Notepad++ không tìm thấy, đã mở bằng Notepad"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500



@app.route('/api/tools/<tool_id>/rename', methods=['PATCH'])
def rename_tool(tool_id):
    """Đổi tên tool và lưu vào tools_config.json"""
    try:
        new_name = request.json.get('name', '').strip()
        if not new_name:
            return jsonify({"success": False, "message": "Tên không được để trống"}), 400

        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools_config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        tool = next((t for t in config if t['id'] == tool_id), None)
        if not tool:
            return jsonify({"success": False, "message": "Tool not found"}), 404

        tool['name'] = new_name
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

        return jsonify({"success": True, "message": f"Đã đổi tên thành '{new_name}'"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/tools/reorder', methods=['POST'])
def reorder_tools():
    """Lưu thứ tự mới của các tools vào tools_config.json"""
    try:
        new_order = request.json.get('order', [])  # list of tool ids
        if not new_order:
            return jsonify({"success": False, "message": "Danh sách rỗng"}), 400

        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools_config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        id_to_tool = {t['id']: t for t in config}
        reordered = [id_to_tool[tid] for tid in new_order if tid in id_to_tool]
        # Giữ lại các tool không có trong new_order (phòng trường hợp thiếu)
        existing_ids = set(new_order)
        for t in config:
            if t['id'] not in existing_ids:
                reordered.append(t)

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(reordered, f, ensure_ascii=False, indent=4)

        return jsonify({"success": True})
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


@app.route('/api/restart', methods=['POST'])
def restart_dashboard():
    """Restart toàn bộ dashboard bằng cách dọn dẹp task cũ, kill chính nó rồi start lại"""
    def do_restart():
        # B1: Tắt các tool con đang quản lý
        for t_id, proc in list(processes.items()):
            try:
                proc.kill()
            except:
                pass
        
        # B2: Tạo file batch tạm để kill process hiện tại và start lại
        base_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.normpath(os.path.join(base_dir, '..'))
        pid = os.getpid()
        
        bat_content = f"""@echo off
:: Cho 1 giay de API tra ve response
ping 127.0.0.1 -n 2 > nul
:: Kill python process cua dashboard cu
taskkill /F /PID {pid} >nul 2>&1
:: Chuyen ve thu muc goc va start lai
cd /d "{root_dir}"
if exist "start_hidden.vbs" (
    wscript.exe "start_hidden.vbs"
) else (
    start "" /b "start_dashboard.bat"
)
:: Tu xoa file bat
del "%~f0"
"""
        tmp_dir = tempfile.gettempdir()
        bat_path = os.path.join(tmp_dir, "restart_mytools.bat")
        with open(bat_path, "w", encoding='utf-8') as f:
            f.write(bat_content)
        
        # B3: Chay file batch doc lap an cua so terminal
        CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen(['cmd.exe', '/c', bat_path], creationflags=CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)

    threading.Thread(target=do_restart, daemon=True).start()
    return jsonify({"success": True, "message": "Dashboard đang restart..."})

# ======================================================================
# LOTTERY SCRAPER UI + API
# ======================================================================
LOTTERY_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../lottery_scraper'))

@app.route('/lottery')
def lottery_ui():
    return render_template('lottery.html')

@app.route('/api/lottery/data', methods=['GET'])
def get_lottery_data():
    quarter = request.args.get('quarter')
    year = request.args.get('year')
    region = request.args.get('region')
    exact_date = request.args.get('exact_date')
    
    import datetime
    
    if exact_date:
        try:
            date_obj = datetime.datetime.strptime(exact_date, '%Y-%m-%d')
            year = str(date_obj.year)
            quarter = str((date_obj.month - 1) // 3 + 1)
        except ValueError:
            pass
    elif not quarter or not year:
        # Default to current
        now = datetime.datetime.now()
        year = str(now.year)
        quarter = str((now.month - 1) // 3 + 1)
        
    csv_file = os.path.join(LOTTERY_DIR, 'data', f'lottery_{year}_Q{quarter}.csv')
    
    data = []
    if os.path.exists(csv_file):
        import csv
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if exact_date and row.get('Date') != exact_date:
                    continue
                if region and row.get('Region') != region and region != 'ALL':
                    continue
                data.append(row)
    
    # Sort data by Date descending
    data.sort(key=lambda x: x.get('Date', ''), reverse=True)
                
    resp = make_response(jsonify({
        "status": "OK",
        "quarter": quarter,
        "year": year,
        "region": region,
        "exact_date": exact_date,
        "data": data,
        "file_exists": os.path.exists(csv_file)
    }))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

# ==============================================================================
# NPM PROJECT MANAGER ROUTES
# ==============================================================================

def send_discord_crash_alert(project_name, exit_code, logs):
    secrets_path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'weather_forecast', 'secrets.json'))
    try:
        if not os.path.exists(secrets_path): return
        with open(secrets_path, 'r', encoding='utf-8') as f:
            secrets = json.load(f)
            webhook_url = secrets.get('discord_webhook_url')
            if not webhook_url: return
            
        last_logs = "\n".join(logs[-15:])
        data = {
            "content": f"🚨 **NPM Project Crashed:** `{project_name}`\n**Exit Code:** {exit_code}\n**Last Logs:**\n```\n{last_logs}\n```"
        }
        
        req = urllib.request.Request(webhook_url, json.dumps(data).encode('utf-8'), {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"Failed to send discord alert: {e}")

def load_npm_projects():
    if not os.path.exists(NPM_PROJECTS_FILE):
        return []
    with open(NPM_PROJECTS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_npm_projects(projects):
    with open(NPM_PROJECTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(projects, f, ensure_ascii=False, indent=4)

def parse_package_json(project_path):
    pkg_path = os.path.join(project_path, 'package.json')
    if not os.path.exists(pkg_path):
        raise FileNotFoundError(f"package.json not found in {project_path}")
    
    with open(pkg_path, 'r', encoding='utf-8') as f:
        pkg = json.load(f)
        
    deps = pkg.get('dependencies', {})
    dev_deps = pkg.get('devDependencies', {})
    all_deps = {**deps, **dev_deps}
    
    framework = "Node.js"
    if "next" in all_deps: framework = "Next.js"
    elif "nuxt" in all_deps: framework = "Nuxt.js"
    elif "vite" in all_deps: framework = "Vite"
    elif "react-scripts" in all_deps: framework = "React (CRA)"
    elif "@angular/core" in all_deps: framework = "Angular"
    elif "@sveltejs/kit" in all_deps: framework = "SvelteKit"
    elif "vue" in all_deps: framework = "Vue"
    
    return {
        "name": pkg.get("name", os.path.basename(project_path)),
        "scripts": pkg.get("scripts", {}),
        "framework": framework,
        "version": pkg.get("version", "1.0.0")
    }

def detect_package_manager(project_path):
    if os.path.exists(os.path.join(project_path, 'yarn.lock')): return "yarn"
    if os.path.exists(os.path.join(project_path, 'pnpm-lock.yaml')): return "pnpm"
    if os.path.exists(os.path.join(project_path, 'bun.lockb')): return "bun"
    return "npm"

def start_npm_project_internal(project, script_name="dev"):
    pid = project['id']
    if pid in npm_processes and npm_processes[pid]['process'].poll() is None:
        raise RuntimeError("Project is already running")
        
    pkg_mgr = detect_package_manager(project['path'])
    command = [pkg_mgr, "run", script_name]
    
    flags = 0
    if os.name == 'nt':
        flags = 0x08000000 # CREATE_NO_WINDOW
        command = ["cmd", "/c", pkg_mgr, "run", script_name]
        
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    
    proc = subprocess.Popen(
        command,
        cwd=project['path'],
        creationflags=flags,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
        env=env
    )
    
    log_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'npm_manager', 'logs'))
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, f"{pid}.log")
    
    initial_log = f"--- STARTING: {project['name']} ({pkg_mgr} run {script_name}) ---"
    with open(log_file_path, 'w', encoding='utf-8') as f:
        f.write(initial_log + '\n')
        
    npm_processes[pid] = {
        "process": proc,
        "logs": [initial_log],
        "url": None,
        "start_time": time.time(),
        "script": script_name,
        "pkg_mgr": pkg_mgr,
        "log_file": log_file_path
    }
    
    def read_logs(out, t_id, proj_name):
        try:
            for line in iter(out.readline, b''):
                if t_id in npm_processes:
                    decoded = line.decode('utf-8', errors='ignore').rstrip()
                    
                    # Remove ANSI escape codes
                    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                    clean_line = ansi_escape.sub('', decoded)
                    
                    npm_processes[t_id]["logs"].append(clean_line)
                    log_file_path = npm_processes[t_id].get("log_file")
                    if log_file_path:
                        try:
                            with open(log_file_path, 'a', encoding='utf-8') as f:
                                f.write(clean_line + '\n')
                        except: pass
                    
                    if not npm_processes[t_id]["url"]:
                        match = re.search(r'http://(?:localhost|127\.0\.0\.1):(?:\d+)', clean_line)
                        if match:
                            npm_processes[t_id]["url"] = match.group(0)
                            
                    if len(npm_processes[t_id]["logs"]) > 1000:
                        npm_processes[t_id]["logs"].pop(0)
        except Exception as e:
            if t_id in npm_processes:
                err_msg = "[LOG ERROR] " + str(e)
                npm_processes[t_id]["logs"].append(err_msg)
                log_file_path = npm_processes[t_id].get("log_file")
                if log_file_path:
                    try:
                        with open(log_file_path, 'a', encoding='utf-8') as f:
                            f.write(err_msg + '\n')
                    except: pass
        finally:
            out.close()
            proc.wait()
            if t_id in npm_processes:
                exit_code = proc.returncode
                exit_msg = f"--- EXITED (Code: {exit_code}) ---"
                npm_processes[t_id]["logs"].append(exit_msg)
                
                log_file_path = npm_processes[t_id].get("log_file")
                if log_file_path:
                    try:
                        with open(log_file_path, 'a', encoding='utf-8') as f:
                            f.write(exit_msg + '\n')
                    except: pass
                    
                if exit_code != 0:
                    send_discord_crash_alert(proj_name, exit_code, npm_processes[t_id]["logs"])

    t = threading.Thread(target=read_logs, args=(proc.stdout, pid, project['name']))
    t.daemon = True
    t.start()

@app.route('/dev_manager')
def dev_manager_ui():
    return render_template('dev_manager.html')

@app.route('/npm')
def npm_ui():
    return redirect(url_for('dev_manager_ui'))

@app.route('/api/dev_manager/projects', methods=['GET'])
def get_npm_projects():
    projects = load_npm_projects()
    for proj in projects:
        pid = proj['id']
        is_running = False
        if pid in npm_processes:
            if npm_processes[pid]['process'].poll() is None:
                is_running = True
                
        proj['status'] = 'Running' if is_running else 'Stopped'
        if is_running:
            proj['url'] = npm_processes[pid].get('url')
            proj['uptime'] = int(time.time() - npm_processes[pid]['start_time'])
            proj['current_script'] = npm_processes[pid].get('script')
        else:
            proj['url'] = None
            proj['uptime'] = 0
            
        proj['pkg_mgr'] = detect_package_manager(proj['path'])
            
    return jsonify(projects)

@app.route('/api/dev_manager/projects', methods=['POST'])
def add_npm_project():
    data = request.json
    path = data.get('path', '').strip()
    
    if not os.path.exists(path):
        return jsonify({"success": False, "message": "Directory not found"}), 404
        
    try:
        info = parse_package_json(path)
    except FileNotFoundError:
        return jsonify({"success": False, "message": "package.json not found in directory"}), 404
    except json.JSONDecodeError:
        return jsonify({"success": False, "message": "package.json is invalid"}), 400
        
    projects = load_npm_projects()
    new_proj = {
        "id": str(uuid.uuid4()),
        "path": path,
        "name": info['name'],
        "framework": info['framework'],
        "version": info['version'],
        "scripts": info['scripts'],
        "auto_start": False
    }
    projects.append(new_proj)
    save_npm_projects(projects)
    
    return jsonify({"success": True, "project": new_proj})

@app.route('/api/dev_manager/projects/<pid>', methods=['DELETE'])
def delete_npm_project(pid):
    projects = load_npm_projects()
    new_projects = [p for p in projects if p['id'] != pid]
    if len(projects) == len(new_projects):
        return jsonify({"success": False, "message": "Project not found"}), 404
        
    if pid in npm_processes and npm_processes[pid]['process'].poll() is None:
        try:
            proc = npm_processes[pid]['process']
            if os.name == 'nt':
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(proc.pid)])
            else:
                proc.terminate()
        except:
            pass
            
    save_npm_projects(new_projects)
    return jsonify({"success": True})

@app.route('/api/dev_manager/projects/<pid>/refresh', methods=['POST'])
def refresh_npm_project(pid):
    projects = load_npm_projects()
    for proj in projects:
        if proj['id'] == pid:
            try:
                info = parse_package_json(proj['path'])
                proj['name'] = info['name']
                proj['framework'] = info['framework']
                proj['version'] = info['version']
                proj['scripts'] = info['scripts']
                save_npm_projects(projects)
                return jsonify({"success": True, "project": proj})
            except Exception as e:
                return jsonify({"success": False, "message": str(e)}), 400
    return jsonify({"success": False, "message": "Project not found"}), 404

@app.route('/api/dev_manager/projects/<pid>/start', methods=['POST'])
def start_npm_project(pid):
    data = request.json or {}
    script_name = data.get('script', 'dev')
    
    projects = load_npm_projects()
    project = next((p for p in projects if p['id'] == pid), None)
    if not project:
        return jsonify({"success": False, "message": "Project not found"}), 404
        
    try:
        start_npm_project_internal(project, script_name)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/dev_manager/projects/<pid>/stop', methods=['POST'])
def stop_npm_project(pid):
    if pid not in npm_processes or npm_processes[pid]['process'].poll() is not None:
        return jsonify({"success": False, "message": "Project is not running"}), 400
        
    try:
        proc = npm_processes[pid]['process']
        if os.name == 'nt':
            subprocess.call(['taskkill', '/F', '/T', '/PID', str(proc.pid)])
        else:
            proc.terminate()
            proc.wait(timeout=3)
        return jsonify({"success": True})
    except subprocess.TimeoutExpired:
        proc.kill()
        return jsonify({"success": True, "message": "Force killed"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/dev_manager/projects/<pid>/logs', methods=['GET'])
def get_npm_project_logs(pid):
    if pid in npm_processes:
        return jsonify({"logs": npm_processes[pid]["logs"]})
    return jsonify({"logs": []})

@app.route('/api/dev_manager/projects/<pid>/input', methods=['POST'])
def input_npm_project(pid):
    if pid not in npm_processes or npm_processes[pid]['process'].poll() is not None:
        return jsonify({"success": False, "message": "Project is not running"}), 400
        
    data = request.json
    cmd = data.get('input', '') + '\n'
    try:
        proc = npm_processes[pid]['process']
        proc.stdin.write(cmd.encode('utf-8'))
        proc.stdin.flush()
        npm_processes[pid]['logs'].append(f"> {cmd.strip()}")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/dev_manager/projects/<pid>/toggle_autostart', methods=['POST'])
def toggle_npm_autostart(pid):
    projects = load_npm_projects()
    for p in projects:
        if p['id'] == pid:
            p['auto_start'] = not p.get('auto_start', False)
            save_npm_projects(projects)
            return jsonify({"success": True, "auto_start": p['auto_start']})
    return jsonify({"success": False, "message": "Project not found"}), 404

@app.route('/api/dev_manager/projects/<pid>/open_vscode', methods=['POST'])
def open_npm_vscode(pid):
    projects = load_npm_projects()
    project = next((p for p in projects if p['id'] == pid), None)
    if not project:
        return jsonify({"success": False, "message": "Project not found"}), 404
        
    try:
        subprocess.Popen(['code', '.'], cwd=project['path'], shell=True)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/dev_manager/projects/<pid>/rename', methods=['PATCH'])
def rename_npm_project(pid):
    """Đổi tên hiển thị của npm project"""
    try:
        new_name = request.json.get('name', '').strip()
        if not new_name:
            return jsonify({"success": False, "message": "Tên không được để trống"}), 400
        projects = load_npm_projects()
        project = next((p for p in projects if p['id'] == pid), None)
        if not project:
            return jsonify({"success": False, "message": "Project not found"}), 404
        project['name'] = new_name
        save_npm_projects(projects)
        return jsonify({"success": True, "message": f"Đã đổi tên thành '{new_name}'"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/dev_manager/projects/reorder', methods=['POST'])
def reorder_npm_projects():
    """Lưu thứ tự mới của các npm projects"""
    try:
        new_order = request.json.get('order', [])
        if not new_order:
            return jsonify({"success": False, "message": "Danh sách rỗng"}), 400
        projects = load_npm_projects()
        id_to_proj = {p['id']: p for p in projects}
        reordered = [id_to_proj[oid] for oid in new_order if oid in id_to_proj]
        existing_ids = set(new_order)
        for p in projects:
            if p['id'] not in existing_ids:
                reordered.append(p)
        save_npm_projects(reordered)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


if __name__ == '__main__':
    auto_start_tools()
    app.run(host='0.0.0.0', port=1101, debug=False)
