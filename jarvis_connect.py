# ============================================================
# JARVIS CONNECT
# Windows background controller for Phone JARVIS
#
# Runs WITHOUT jarvisv2.py
# ============================================================

from flask import Flask, request, jsonify
import subprocess
import os
import ctypes
import time
import socket

app = Flask(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

HOST = "0.0.0.0"
PORT = 8000

# IMPORTANT:
# Change this to a long random secret.
AUTH_TOKEN = "MUKUND123"


# ============================================================
# HELPER
# ============================================================

def expand(path):
    """Expand Windows environment variables."""
    return os.path.expandvars(path)


# ============================================================
# APP PATHS
#
# Each app is stored as:
#
# "name": [executable, argument1, argument2, ...]
#
# This allows apps such as Discord and Valorant
# to use command-line arguments correctly.
# ============================================================

APP_PATHS = {

    # ========================================================
    # BROWSERS
    # ========================================================

    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    ],

    "google chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    ],

    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    ],


    # ========================================================
    # DEVELOPMENT
    # ========================================================

    "vs code": [
        expand(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe")
    ],

    "vscode": [
        expand(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe")
    ],

    "visual studio code": [
        expand(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe")
    ],


    # ========================================================
    # MICROSOFT OFFICE
    # ========================================================

    "word": [
        r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE"
    ],

    "microsoft word": [
        r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE"
    ],

    "excel": [
        r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"
    ],

    "microsoft excel": [
        r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"
    ],

    "powerpoint": [
        r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE"
    ],

    "microsoft powerpoint": [
        r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE"
    ],


    # ========================================================
    # APPS
    # ========================================================

    "discord": [
        expand(r"%LOCALAPPDATA%\Discord\Update.exe"),
        "--processStart",
        "Discord.exe"
    ],

    "spotify": [
        expand(
            r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe"
        )
    ],


    # ========================================================
    # WINDOWS UTILITIES
    # ========================================================

    "calculator": [
        "calc.exe"
    ],

    "notepad": [
        "notepad.exe"
    ],

    "paint": [
        "mspaint.exe"
    ],

    "powershell": [
        "powershell.exe"
    ],

    "command prompt": [
        "cmd.exe"
    ],

    "cmd": [
        "cmd.exe"
    ],


    # ========================================================
    # FILE EXPLORER
    # ========================================================

    "file explorer": [
        "explorer.exe"
    ],

    "explorer": [
        "explorer.exe"
    ],


    # ========================================================
    # GAMES
    # ========================================================

    "valorant": [
        r"C:\Riot Games\Riot Client\RiotClientServices.exe",
        "--launch-product=valorant",
        "--launch-patchline=live"
    ],

    "valo": [
        r"C:\Riot Games\Riot Client\RiotClientServices.exe",
        "--launch-product=valorant",
        "--launch-patchline=live"
    ],

    "roblox": [
        r"C:\Users\Akilan\AppData\Local\Roblox\Versions\version-ddf602d9cfe44005\RobloxPlayerBeta.exe"
    ],

    "epic": [
        r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe"
    ],

    "epic games": [
        r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe"
    ],

    "steam": [
        r"C:\Program Files (x86)\Steam\steam.exe"
    ],


    # ========================================================
    # VIDEO / EDITING
    # ========================================================

    "davinci resolve": [
        r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"
    ],

    "davinci": [
        r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"
    ],
}


# ============================================================
# FOLDERS
# ============================================================

FOLDERS = {

    "desktop": os.path.join(
        os.path.expanduser("~"),
        "Desktop"
    ),

    "downloads": os.path.join(
        os.path.expanduser("~"),
        "Downloads"
    ),

    "documents": os.path.join(
        os.path.expanduser("~"),
        "Documents"
    ),

    "pictures": os.path.join(
        os.path.expanduser("~"),
        "Pictures"
    ),

    "videos": os.path.join(
        os.path.expanduser("~"),
        "Videos"
    ),

    "music": os.path.join(
        os.path.expanduser("~"),
        "Music"
    ),
}


# ============================================================
# AUTHENTICATION
# ============================================================

def authorized(req):

    token = req.headers.get("X-JARVIS-TOKEN")

    return token == AUTH_TOKEN


# ============================================================
# FIND CHROME
# ============================================================

def find_chrome():

    chrome_paths = [

        r"C:\Program Files\Google\Chrome\Application\chrome.exe",

        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",

        expand(
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
        ),
    ]

    for path in chrome_paths:

        if os.path.exists(path):

            return path

    return None


# ============================================================
# OPEN CHROME
# ============================================================

def open_chrome():

    try:

        chrome_path = find_chrome()

        if not chrome_path:

            return False, (
                "I couldn't find Google Chrome."
            )

        subprocess.Popen([
            chrome_path,
            "--profile-directory=Profile 8"
        ])

        return True, (
            "Opening Chrome with your primary profile."
        )

    except Exception as e:

        return False, (
            f"Couldn't open Chrome: {e}"
        )


# ============================================================
# OPEN APPLICATION
# ============================================================

def open_app(app_name):

    app_name = app_name.lower().strip()

    if app_name not in APP_PATHS:

        return False, (
            f"I don't have permission to open {app_name}."
        )

    try:

        # ====================================================
        # CHROME
        # ====================================================

        if app_name in (
            "chrome",
            "google chrome"
        ):

            return open_chrome()


        # ====================================================
        # GET APP COMMAND
        # ====================================================

        command = APP_PATHS[app_name]

        executable = command[0]

        arguments = command[1:]


        # ====================================================
        # CHECK REAL FILE
        #
        # Windows commands such as calc.exe don't need
        # os.path.exists().
        # ====================================================

        if (
            os.path.isabs(executable)
            and not os.path.exists(executable)
        ):

            return False, (
                f"I couldn't find {app_name}."
            )


        # ====================================================
        # START APPLICATION
        # ====================================================

        subprocess.Popen(
            command,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )

        return True, (
            f"Opening {app_name}."
        )

    except FileNotFoundError:

        return False, (
            f"I couldn't find {app_name}."
        )

    except Exception as e:

        return False, (
            f"Couldn't open {app_name}: {e}"
        )


# ============================================================
# OPEN WEBSITE IN CHROME
# ============================================================

def open_url(url):

    try:

        if not url.startswith(
            ("http://", "https://")
        ):

            url = "https://" + url


        chrome_path = find_chrome()

        if not chrome_path:

            return False, (
                "I couldn't find Google Chrome."
            )


        subprocess.Popen([
            chrome_path,
            "--profile-directory=Profile 8",
            url
        ])


        return True, (
            f"Opening {url} in Chrome."
        )

    except Exception as e:

        return False, (
            f"Couldn't open website in Chrome: {e}"
        )


# ============================================================
# OPEN FOLDER
# ============================================================

def open_folder(folder_name):

    folder_name = folder_name.lower().strip()

    if folder_name not in FOLDERS:

        return False, (
            f"I don't know the {folder_name} folder."
        )

    path = FOLDERS[folder_name]

    try:

        subprocess.Popen(
            ["explorer.exe", path],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )

        return True, (
            f"Opening {folder_name}."
        )

    except Exception as e:

        return False, (
            f"Couldn't open folder: {e}"
        )


# ============================================================
# VOLUME UP
# ============================================================

def volume_up():

    try:

        for _ in range(2):

            ctypes.windll.user32.keybd_event(
                0xAF,
                0,
                0,
                0
            )

            ctypes.windll.user32.keybd_event(
                0xAF,
                0,
                2,
                0
            )

        return True, (
            "Volume increased."
        )

    except Exception as e:

        return False, (
            f"Couldn't change volume: {e}"
        )


# ============================================================
# VOLUME DOWN
# ============================================================

def volume_down():

    try:

        for _ in range(2):

            ctypes.windll.user32.keybd_event(
                0xAE,
                0,
                0,
                0
            )

            ctypes.windll.user32.keybd_event(
                0xAE,
                0,
                2,
                0
            )

        return True, (
            "Volume decreased."
        )

    except Exception as e:

        return False, (
            f"Couldn't change volume: {e}"
        )


# ============================================================
# MUTE
# ============================================================

def volume_mute():

    try:

        ctypes.windll.user32.keybd_event(
            0xAD,
            0,
            0,
            0
        )

        ctypes.windll.user32.keybd_event(
            0xAD,
            0,
            2,
            0
        )

        return True, (
            "Volume muted."
        )

    except Exception as e:

        return False, (
            f"Couldn't mute volume: {e}"
        )


# ============================================================
# TURN DISPLAY OFF
# ============================================================

def turn_display_off():

    try:

        ctypes.windll.user32.SendMessageW(
            0xFFFF,
            0x0112,
            0xF170,
            2
        )

        return True, (
            "Display turned off."
        )

    except Exception as e:

        return False, (
            f"Couldn't turn off display: {e}"
        )


# ============================================================
# LOCK COMPUTER
# ============================================================

def lock_pc():

    try:

        ctypes.windll.user32.LockWorkStation()

        return True, (
            "Computer locked."
        )

    except Exception as e:

        return False, (
            f"Couldn't lock computer: {e}"
        )


# ============================================================
# SCREENSHOT
# ============================================================

def take_screenshot():

    try:

        from PIL import ImageGrab

        screenshot_dir = os.path.join(
            os.path.expanduser("~"),
            "Pictures",
            "JARVIS"
        )

        os.makedirs(
            screenshot_dir,
            exist_ok=True
        )

        filename = time.strftime(
            "jarvis_%Y%m%d_%H%M%S.png"
        )

        path = os.path.join(
            screenshot_dir,
            filename
        )

        image = ImageGrab.grab()

        image.save(path)

        return True, (
            f"Screenshot saved to {path}."
        )

    except Exception as e:

        return False, (
            f"Couldn't take screenshot: {e}"
        )


# ============================================================
# PC STATUS
# ============================================================

def get_status():

    try:

        hostname = socket.gethostname()

        try:

            import psutil

            battery = psutil.sensors_battery()

            if battery:

                battery_text = (
                    f"{battery.percent}%"
                )

                if battery.power_plugged:

                    battery_text += (
                        " and charging"
                    )

            else:

                battery_text = (
                    "Not available"
                )

        except Exception:

            battery_text = (
                "Not available"
            )

        return True, (
            f"Laptop is online. "
            f"Computer name: {hostname}. "
            f"Battery: {battery_text}."
        )

    except Exception as e:

        return False, (
            f"Couldn't get laptop status: {e}"
        )


# ============================================================
# FILE / PATH OPENING
# ============================================================

def open_path(path):

    try:

        path = os.path.expandvars(
            os.path.expanduser(path)
        )

        if not os.path.exists(path):

            return False, (
                "That file or folder doesn't exist."
            )

        os.startfile(path)

        return True, (
            f"Opening {path}."
        )

    except Exception as e:

        return False, (
            f"Couldn't open path: {e}"
        )


# ============================================================
# COMMAND PROCESSOR
# ============================================================

def execute_command(text):

    original = text.strip()

    command = original.lower().strip()


    # ========================================================
    # OPEN
    # ========================================================

    if command.startswith("open "):

        target = command[5:].strip()


        # ----------------------------------------------------
        # FOLDERS
        # ----------------------------------------------------

        if target in FOLDERS:

            return open_folder(target)


        # ----------------------------------------------------
        # APPLICATIONS
        # ----------------------------------------------------

        if target in APP_PATHS:

            return open_app(target)


        # ----------------------------------------------------
        # WEBSITES
        # ----------------------------------------------------

        website_names = {

            "google":
                "https://www.google.com",

            "youtube":
                "https://www.youtube.com",

            "github":
                "https://github.com",

            "gmail":
                "https://mail.google.com",

            "chatgpt":
                "https://chatgpt.com",

            "facebook":
                "https://www.facebook.com",

            "instagram":
                "https://www.instagram.com",

            "whatsapp":
                "https://web.whatsapp.com",

            "netflix":
                "https://www.netflix.com",

            "amazon":
                "https://www.amazon.in",

            "hindu":
                "https://www.thehindu.com/"    
        }


        if target in website_names:

            return open_url(
                website_names[target]
            )


        return False, (
            f"I don't have {target} configured yet."
        )


    # ========================================================
    # GO TO WEBSITE
    # ========================================================

    if command.startswith("go to "):

        url = original[6:].strip()

        return open_url(url)


    # ========================================================
    # VOLUME UP
    # ========================================================

    if (
        "volume up" in command
        or "increase volume" in command
        or "raise volume" in command
    ):

        return volume_up()


    # ========================================================
    # VOLUME DOWN
    # ========================================================

    if (
        "volume down" in command
        or "decrease volume" in command
        or "lower volume" in command
    ):

        return volume_down()


    # ========================================================
    # MUTE
    # ========================================================

    if (
        "mute volume" in command
        or command == "mute"
        or "mute my laptop" in command
    ):

        return volume_mute()


    # ========================================================
    # DISPLAY
    # ========================================================

    if (
        "turn off display" in command
        or "turn off my display" in command
        or "turn off my monitor" in command
        or "turn off the monitor" in command
    ):

        return turn_display_off()


    # ========================================================
    # LOCK
    # ========================================================

    if (
        command == "lock"
        or "lock my laptop" in command
        or "lock my computer" in command
        or "lock the laptop" in command
    ):

        return lock_pc()


    # ========================================================
    # SCREENSHOT
    # ========================================================

    if (
        "take a screenshot" in command
        or "take screenshot" in command
        or command == "screenshot"
    ):

        return take_screenshot()


    # ========================================================
    # STATUS
    # ========================================================

    if (
        "laptop status" in command
        or "computer status" in command
        or command == "status"
        or "is my laptop on" in command
    ):

        return get_status()


    # ========================================================
    # OPEN FOLDER
    # ========================================================

    if command.startswith("open folder "):

        folder = command[
            len("open folder "):
        ].strip()

        return open_folder(folder)


    # ========================================================
    # OPEN PATH
    # ========================================================

    if command.startswith("open path "):

        path = original[
            len("open path "):
        ].strip()

        return open_path(path)


    # ========================================================
    # UNKNOWN
    # ========================================================

    return False, (
        "I received the command, "
        "but JARVIS CONNECT doesn't support it yet."
    )


# ============================================================
# HTTP API
# ============================================================

@app.route(
    "/command",
    methods=["POST"]
)
def command_endpoint():

    # ========================================================
    # AUTHENTICATION
    # ========================================================

    if not authorized(request):

        return jsonify({
            "reply": "Unauthorized."
        }), 401


    # ========================================================
    # JSON
    # ========================================================

    data = request.get_json(
        silent=True
    )

    if not data:

        return jsonify({
            "reply": "Invalid request."
        }), 400


    text = data.get(
        "text",
        ""
    )


    if not isinstance(text, str):

        return jsonify({
            "reply": "Invalid command."
        }), 400


    text = text.strip()


    if not text:

        return jsonify({
            "reply": "No command received."
        }), 400


    # ========================================================
    # EXECUTE
    # ========================================================

    try:

        success, reply = execute_command(
            text
        )

        return jsonify({
            "success": success,
            "reply": reply
        })


    except Exception as e:

        return jsonify({
            "success": False,
            "reply": (
                f"JARVIS CONNECT error: {e}"
            )
        }), 500


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route(
    "/status",
    methods=["GET"]
)
def status_endpoint():

    return jsonify({

        "service":
            "JARVIS CONNECT",

        "status":
            "online",

        "computer":
            socket.gethostname()
    })


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 55)
    print("              JARVIS CONNECT")
    print("=" * 55)
    print()

    print(
        f"Computer : {socket.gethostname()}"
    )

    print(
        f"IP       : "
        f"{socket.gethostbyname(socket.gethostname())}"
    )

    print(
        f"Port     : {PORT}"
    )

    print()

    print(
        "JARVIS CONNECT is running."
    )

    print(
        "Your main JARVIS does NOT need to be running."
    )

    print()

    print("=" * 55)
    print()


    app.run(
        host=HOST,
        port=PORT,
        debug=False,
        threaded=True
    )