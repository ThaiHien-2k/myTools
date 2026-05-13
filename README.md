# myTools - Local Control Center Dashboard

A centralized system to manage and monitor background Python scripts with a modern Web UI, supporting real-time logs and remote controls.

## 🚀 Key Features
- **Professional Web UI**: Dark mode, optimized horizontal layout for better readability.
- **Real-time Log Management**: Stream logs directly to your browser with expandable terminal views.
- **Centralized Control**: Start/Stop tools with a single click.
- **Automation**: Run hidden on Windows startup and automatic system cleanup on shutdown.
- **Zero-loop UI**: Smart log updates that prevent redundant data rendering.

---

## 🛠 Installation Guide

### 1. System Requirements
- OS: **Windows 10/11** (recommended).
- **Python 3.x** installed.

### 2. Install Dependencies
Open CMD in the `myTools` root directory and run:
```bash
pip install flask
```

---

## 💻 How to Use

### 1. Launching the Dashboard
- **Standard Mode**: Run `start_dashboard.bat`. Access via `http://localhost:1101`.
- **Hidden Mode**: Run `start_hidden.vbs`. The dashboard will run in the background.

### 2. Controlling Tools
- Navigate to `http://localhost:1101`.
- Click **Start** to run a tool, **Stop** to terminate it.
- Click **Logs** to view the live activity. Use the **Maximize** button inside the log box to expand the view.

### 3. System Shutdown
- Click the red **Shutdown Dashboard** button on the Web UI to kill the dashboard and all running tools.
- In case of issues, run **`kill_all.bat`** to forcefully terminate all Python processes.

---

## ⚙️ Setup Run on Startup
To automatically launch the dashboard in hidden mode when Windows starts:
1. Right-click `start_hidden.vbs` -> **Show more options** -> **Create shortcut**.
2. Press `Windows + R`, type `shell:startup`, and press Enter.
3. Paste the shortcut into the Startup folder.

---

## ➕ Adding New Tools
To integrate your own scripts into the dashboard:
1. Open `dashboard/tools_config.json`.
2. Add a new configuration block:
```json
{
    "id": "unique_tool_id",
    "name": "Display Name",
    "directory": "../path_to_tool_folder",
    "command": "python -u script_name.py",
    "has_gui": false
}
```
3. Refresh the Dashboard to see your new tool.

---

## 📁 Project Structure
- `dashboard/`: Flask backend and Web frontend source code.
- `network_monitor/`: Network monitoring scripts.
- `vietlott/`: Prediction and checking scripts for Vietlott.
- `kill_all.bat`: Emergency system cleanup tool.
- `start_dashboard.bat`: Manual dashboard launcher.

---
*Developed by ThaiHien-2k*
