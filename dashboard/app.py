from flask import Flask, render_template, jsonify, request, make_response
import json
import os
import subprocess
import threading
import time

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Dictionary to store process objects
processes = {}
process_logs = {}

def load_config():
    with open('tools_config.json', 'r', encoding='utf-8') as f:
        return json.load(f)

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

@app.route('/nowcast')
def nowcast_ui():
    return render_template('nowcast.html')

@app.route('/api/nowcast/status', methods=['GET'])
def get_nowcast_status():
    status_file = os.path.join(NOWCAST_DIR, 'latest_status.json')
    if os.path.exists(status_file):
        with open(status_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
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
    config = load_config()
    tool = next((t for t in config if t['id'] == tool_id), None)
    
    if not tool:
        return jsonify({"success": False, "message": "Tool not found"}), 404
        
    if tool_id in processes and processes[tool_id].poll() is None:
        return jsonify({"success": False, "message": "Tool is already running"}), 400

    try:
        # Resolve full paths
        base_dir = os.path.dirname(os.path.abspath(__file__))
        tool_dir = os.path.normpath(os.path.join(base_dir, tool['directory']))
        command = tool['command'].split()
        
        # Initialize log buffer for this tool
        process_logs[tool_id] = [
            f"--- STARTING TOOL: {tool['name']} ---",
            f"Directory: {tool_dir}",
            f"Command: {tool['command']}",
            "---------------------------------------"
        ]

        if not os.path.exists(tool_dir):
            process_logs[tool_id].append(f"ERROR: Directory not found: {tool_dir}")
            return jsonify({"success": False, "message": f"Directory not found: {tool['directory']}"}), 404

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
                # CREATE_NO_WINDOW (0x08000000)
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
        return jsonify({"success": True, "message": f"Started {tool['name']}"})
        
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
    app.run(host='0.0.0.0', port=1101, debug=False)
