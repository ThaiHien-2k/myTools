# myTools Dashboard Setup & Guide

This dashboard (Control Center) allows you to easily manage, start, and stop your background scripts/tools via a modern web interface.

## Directory Structure
Every tool should be placed in its own folder inside the root `myTools` directory.
Example:
```text
myTools/
├── dashboard/               (Web interface source code)
├── network_monitor/         (Network monitor tool)
├── vietlott/                (Vietlott tool)
└── your_new_tool/           <-- (Add your new tools here)
```

## How to Add a New Tool

### Step 1: Place your code in a folder
- Create a new folder inside `myTools` (e.g., `auto_clicker`).
- Put all your script files (.py, .exe, etc.) into that folder.

### Step 2: Update the Configuration
- Open `myTools/dashboard/tools_config.json` with a text editor.
- Copy and paste a new configuration block at the end of the list.

**Example Configuration:**
```json
    {
        "id": "tool_id_unique",
        "name": "Display Name on Web",
        "directory": "../your_folder_name",
        "command": "python -u main.py",
        "has_gui": false
    }
```

### Explanation of Configuration Fields:

1. `"id"`: Unique identifier for the tool (use lowercase, numbers, and underscores, NO spaces).
2. `"name"`: The title displayed on the dashboard card.
3. `"directory"`: Path to the tool folder relative to the `dashboard` folder. Usually starts with `../`.
4. `"command"`: The command line to execute the tool. Use `python -u` for Python scripts to ensure real-time log streaming.
5. `"has_gui"`: 
   - `true`: Opens a separate CMD window (visible).
   - `false`: Runs hidden in the background and streams output directly to the Web Dashboard terminal box.

## Automatic Startup with Windows
To have the dashboard start automatically when you turn on your computer:
1. Press `Win + R`, type `shell:startup`, and press Enter.
2. Right-click `start_hidden.vbs` (in the `myTools` root) and select **Copy**.
3. Right-click inside the Startup folder and select **Paste Shortcut**.

---

## Important Notes

### 1. Real-time Logs
For Python tools, always use the `-u` flag in the command (e.g., `python -u script.py`). This prevents output buffering and ensures logs appear instantly on the web.

### 2. Shutdown Button
The "Shutdown Dashboard" button on the web interface will completely kill the `app.py` process to free up system resources. You will need to run `start_dashboard.bat` manually to turn it back on.
