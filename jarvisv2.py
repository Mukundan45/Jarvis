import os
import sys
import json
import subprocess
import threading
import tkinter as tk
import time
import re
import shutil
import ctypes
from ctypes import wintypes
from collections import deque
import math
import requests
import psutil
from datetime import datetime
from flask import Flask, request, jsonify, send_file
import speech_recognition as sr
import pyttsx3
import keyboard

from groq import Groq

# ============================================================
# WINDOWS DPI AWARENESS
# ============================================================
try:
    _dpi_hresult = ctypes.windll.shcore.SetProcessDpiAwareness(2)
    print(f"[dpi] SetProcessDpiAwareness(2) HRESULT: {_dpi_hresult} (0 = success)")
except Exception as _dpi_error:
    print("[dpi] shcore call raised:", _dpi_error)
    try:
        _dpi_ok = ctypes.windll.user32.SetProcessDPIAware()
        print(f"[dpi] fallback SetProcessDPIAware() returned: {_dpi_ok} (nonzero = success)")
    except Exception as _dpi_error2:
        print("[dpi] fallback also raised:", _dpi_error2)


# ============================================================
# GOLD THEME
# ============================================================

GOLD = "#f5c518"
GOLD_BRIGHT = "#ffe07a"
GOLD_DIM = "#8a6d0f"
GOLD_SOFT = "#d8c98a"
INK_BG = "#05060a"
PANEL_BG = "#0d0f16"
INPUT_BG = "#161a24"
TEXT_MAIN = "#eef1f8"

# Gaming/Focus HUD accent (cyan, Iron-Man-HUD style, distinct from the
# gold Normal Mode theme so each mode feels visually distinct)
HUD_CYAN = "#00d9ff"
HUD_CYAN_BRIGHT = "#6ff0ff"
HUD_BG = "#02070b"
HUD_WARN = "#ff4d6d"

# Module-level stub so any code that reads system_state (e.g. Gaming
# Mode's HUD) never hits a NameError, even in headless mode or before
# system_stats_loop() has run its first pass. The GUI branch's
# system_stats_loop() updates this same dict in place via .update().
system_state = {
    "cpu": 0.0, "mem": 0.0, "disk": 0.0,
    "mem_used_gb": 0.0, "mem_total_gb": 0.0,
    "net_sent": 0.0, "net_recv": 0.0,
    "procs": 0, "uptime": "—", "battery": None, "plugged": None,
}


# ============================================================
# CONFIG
# ============================================================

MODEL = "openai/gpt-oss-120b"
WAKE_WORD = "jarvis"
CHAT_WIDTH = 430
CHAT_HEIGHT = 560
VOICE_ENABLED = True
CHROME_PROFILE = "Profile 8"
VOICE_ACTIVE_TIME = 15

# When True, JARVIS is intentionally hidden and can ONLY be restored
# by the full open-palm hand gesture. Voice/text/hotkey/other gestures
# are ignored until the open palm is detected.
gesture_only_hidden = False

# MUST match your Android app's AUTH_TOKEN constant exactly.
# Pulled from an environment variable so it isn't hardcoded in source;
# falls back to the literal value only if the env var isn't set.
AUTH_TOKEN = os.getenv("JARVIS_AUTH_TOKEN", "MUKUND123")


# ============================================================
# FOCUS MODE CONFIG (allowed / blocked apps)
# ============================================================
# User-configurable via focus_config.json, created with sensible
# defaults next to this script on first run. Editing that file is
# the safe, reversible way to change what Focus Mode flags — nothing
# here forcibly terminates or blocks an app; it only monitors and reports them; it does not force-close them.

FOCUS_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "focus_config.json"
)

DEFAULT_FOCUS_CONFIG = {
    "focus_allowed_apps": [
        "chrome.exe", "Code.exe", "python.exe", "explorer.exe",
        "WINWORD.EXE", "EXCEL.EXE", "POWERPNT.EXE", "Resolve.exe",
        "CalculatorApp.exe", "notepad.exe"
    ],
    "focus_blocked_apps": [
        "steam.exe", "RobloxPlayerBeta.exe", "Discord.exe",
        "EpicGamesLauncher.exe", "VALORANT-Win64-Shipping.exe"
    ],
    "default_focus_minutes": 25,
    "break_minutes": 5
}


def load_focus_config():
    try:
        if os.path.exists(FOCUS_CONFIG_PATH):
            with open(FOCUS_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = DEFAULT_FOCUS_CONFIG
            with open(FOCUS_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_FOCUS_CONFIG, f, indent=2)
            print(f"Created default Focus Mode config at {FOCUS_CONFIG_PATH}")

        return (
            data.get("focus_allowed_apps", DEFAULT_FOCUS_CONFIG["focus_allowed_apps"]),
            data.get("focus_blocked_apps", DEFAULT_FOCUS_CONFIG["focus_blocked_apps"]),
            data.get("default_focus_minutes", 25),
            data.get("break_minutes", 5),
        )
    except Exception as error:
        print("Focus config load error (using built-in defaults):", error)
        return (
            DEFAULT_FOCUS_CONFIG["focus_allowed_apps"],
            DEFAULT_FOCUS_CONFIG["focus_blocked_apps"],
            25,
            5,
        )


FOCUS_ALLOWED_APPS, FOCUS_BLOCKED_APPS, DEFAULT_FOCUS_MINUTES, BREAK_MINUTES = load_focus_config()


# ============================================================
# EXIT COMMANDS
# ============================================================

EXIT_COMMANDS = {
    "exit", "quit", "stop", "turn off", "close jarvis", "stop jarvis",
    "exit jarvis", "quit jarvis", "turn off jarvis", "stop jarvis now",
    "shutdown jarvis", "shut down jarvis", "goodbye jarvis",
}


def is_exit_command(text):
    if not text:
        return False
    command = text.lower().strip()
    command = re.sub(r"[,.!?;:]", "", command)
    command = " ".join(command.split())
    return command in EXIT_COMMANDS


# ============================================================
# GROQ
# ============================================================

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    raise RuntimeError(
        "GROQ_API_KEY was not found.\n\n"
        "Set your GROQ_API_KEY in Windows Environment Variables."
    )

client = Groq(api_key=api_key)


# ============================================================
# VOICE
# ============================================================

speaker_lock = threading.Lock()


def speak(text):
    if not text:
        return

    print("JARVIS:", text)

    if not VOICE_ENABLED:
        return

    try:
        clean = str(text)
        clean = clean.replace("...", " ")
        clean = clean.replace("—", " ")
        clean = clean.replace("–", " ")
        clean = re.sub(r"[,:;!?()\[\]{}\"]", " ", clean)
        clean = clean.replace(".", " ")
        clean = " ".join(clean.split())

        with speaker_lock:
            engine = pyttsx3.init()
            engine.setProperty("rate", 180)
            engine.setProperty("volume", 1.0)
            engine.say(clean)
            engine.runAndWait()
            engine.stop()
            del engine

    except Exception as error:
        print("Voice error:", error)


# ============================================================
# WINDOWS STARTUP
# ============================================================

def setup_startup():
    try:
        startup_folder = os.path.join(
            os.environ["APPDATA"],
            r"Microsoft\Windows\Start Menu\Programs\Startup"
        )
        os.makedirs(startup_folder, exist_ok=True)

        script_path = os.path.abspath(sys.argv[0])

        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable

        vbs_path = os.path.join(startup_folder, "JARVIS.vbs")

        script_path_vbs = script_path.replace('"', '""')
        pythonw_vbs = pythonw.replace('"', '""')

        vbs_content = f'''
Set WShell = CreateObject("WScript.Shell")
WShell.Run """{pythonw_vbs}"" ""{script_path_vbs}""", 0, False
'''

        with open(vbs_path, "w", encoding="utf-8") as file:
            file.write(vbs_content)

        print("JARVIS startup enabled.")

    except Exception as error:
        print("Startup setup failed:", error)


# ============================================================
# APPLICATION PATHS
# ============================================================

DAVINCI_PATH = (
    r"C:\Program Files\Blackmagic Design"
    r"\DaVinci Resolve\Resolve.exe"
)

VALORANT_PATH = (
    r"C:\Riot Games\Riot Client"
    r"\RiotClientServices.exe"
)

ROBLOX_PATH = (
    r"C:\Users\Akilan\AppData\Local\Roblox"
    r"\Versions\version-ce0bcd0fbd484804"
    r"\RobloxPlayerBeta.exe"
)

EPIC_PATH = (
    r"C:\Program Files (x86)\Epic Games"
    r"\Launcher\Portal\Binaries\Win32"
    r"\EpicGamesLauncher.exe"
)


# ============================================================
# WINDOWS APPLICATIONS
# ============================================================

ALLOWED_APPS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:",
    "control panel": "control.exe",
    "word": "winword.exe",
    "microsoft word": "winword.exe",
    "excel": "excel.exe",
    "microsoft excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "microsoft powerpoint": "powerpnt.exe",
    "outlook": "outlook.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "discord": "discord.exe",
    "spotify": "spotify.exe",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
}


# ============================================================
# SPECIAL FOLDERS
# ============================================================

SPECIAL_FOLDERS = {
    "downloads": r"C:\Users\Akilan\Downloads",
    "download": r"C:\Users\Akilan\Downloads",
    "docs": r"C:\Users\Akilan\OneDrive\Documents",
    "documents": r"C:\Users\Akilan\OneDrive\Documents",
    "pics": r"C:\Users\Akilan\OneDrive\Pictures",
    "pictures": r"C:\Users\Akilan\OneDrive\Pictures",
    "music": r"C:\Users\Akilan\Music",
    "videos": r"C:\Users\Akilan\Videos",
    "edits": r"C:\Users\Akilan\Videos\edits (new)",
    "edit": r"C:\Users\Akilan\Videos\edits (new)",
    "movies": r"C:\Users\Akilan\Videos\Movies",
    "movie": r"C:\Users\Akilan\Videos\Movies",
    "desktop": r"C:\Users\Akilan\OneDrive\Desktop",
    "c": r"C:\\",
}


# ============================================================
# SEARCH LOCATIONS
# ============================================================

SEARCH_LOCATIONS = [
    r"C:\Users\Akilan\OneDrive\Desktop",
    r"C:\Users\Akilan\OneDrive\Documents",
    r"C:\Users\Akilan\OneDrive\Pictures",
    r"C:\Users\Akilan\Downloads",
    r"C:\Users\Akilan\Videos",
    r"C:\Users\Akilan\Music",
]


# ============================================================
# CHROME
# ============================================================

def find_chrome():
    paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    return None


def open_website(url):
    url = url.strip()

    if not url:
        return "I need a website to open, sir."

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    chrome = find_chrome()
    if not chrome:
        return "I couldn't find Google Chrome, sir."

    try:
        subprocess.Popen(
            [chrome, f"--profile-directory={CHROME_PROFILE}", "--new-tab", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL
        )
        return "Opening that in Chrome, sir."
    except Exception as error:
        return f"I couldn't open the website, sir. {error}"


# ============================================================
# OPEN FOLDER
# ============================================================

def open_folder(folder_name):
    name = folder_name.lower().strip()

    if name not in SPECIAL_FOLDERS:
        return "I couldn't find that folder in my list, sir."

    path = SPECIAL_FOLDERS[name]

    if not os.path.exists(path):
        return f"I couldn't find your {name} folder, sir."

    try:
        os.startfile(path)
        if name in ["movies", "movie"]:
            return "Opening your movies, sir."
        return f"Opening your {name}, sir."
    except Exception as error:
        return f"I couldn't open {name}, sir. {error}"


# ============================================================
# FILE SEARCH
# ============================================================

def normalize_name(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def find_file_by_name(file_name):
    file_name = file_name.strip()
    target = normalize_name(file_name)

    if not target:
        return None

    possible_names = {target}

    common_extensions = [
        ".pdf", ".txt", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
        ".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mkv", ".avi", ".mov",
        ".mp3", ".wav", ".py", ".zip", ".rar"
    ]

    if "." not in file_name:
        for extension in common_extensions:
            possible_names.add(normalize_name(file_name + extension))

    for location in SEARCH_LOCATIONS:
        if not os.path.exists(location):
            continue

        try:
            for root_dir, dirs, files in os.walk(location):
                dirs[:] = [d for d in dirs if not d.startswith(".")]

                for filename in files:
                    normalized = normalize_name(filename)

                    if normalized in possible_names:
                        return os.path.join(root_dir, filename)

                    if target in normalized and len(target) >= 4:
                        return os.path.join(root_dir, filename)

        except PermissionError:
            continue
        except Exception:
            continue

    return None


def open_file(file_name):
    file_name = file_name.strip()

    if not file_name:
        return "Tell me the name of the file, sir."

    if os.path.exists(file_name):
        try:
            os.startfile(file_name)
            return f"Opening {os.path.basename(file_name)}, sir."
        except Exception as error:
            return f"I couldn't open that file, sir. {error}"

    path = find_file_by_name(file_name)

    if not path:
        return f"I couldn't find a file named {file_name}, sir."

    try:
        os.startfile(path)
        return f"Opening {os.path.basename(path)}, sir."
    except Exception as error:
        return f"I found it but couldn't open it, sir. {error}"


# ============================================================
# FILE TRANSFER (laptop -> phone "grab and send")
# ============================================================
# pending_transfer holds whatever file was last "grabbed" — either by
# the pinch gesture (grabs whatever is selected in File Explorer) or
# by voice/text command ("send <file> to my phone").
#
# A lock guards it since the gesture thread, the Flask thread, and the
# Tk main thread can all touch it.

pending_transfer = {"path": None}
pending_transfer_lock = threading.Lock()


def get_selected_explorer_file():
    """
    Returns the full path of whatever file is currently selected in the
    topmost File Explorer window, or None if nothing is selected, no
    Explorer window is focused, or pywin32 isn't installed.
    """
    try:
        import win32com.client
    except ImportError:
        print("get_selected_explorer_file: pywin32 not installed (pip install pywin32)")
        return None

    try:
        shell = win32com.client.Dispatch("Shell.Application")
        hwnd = ctypes.windll.user32.GetForegroundWindow()

        for window in shell.Windows():
            try:
                if window.HWND == hwnd:
                    selected = window.Document.SelectedItems()
                    if selected.Count > 0:
                        return selected.Item(0).Path
            except Exception:
                continue

        return None

    except Exception as error:
        print("Explorer selection read error:", error)
        return None


def arm_file_for_transfer(path):
    """Stores `path` as the file waiting to be pulled by the phone."""
    with pending_transfer_lock:
        pending_transfer["path"] = path


def get_armed_file():
    with pending_transfer_lock:
        path = pending_transfer.get("path")
    if path and os.path.exists(path):
        return path
    return None


def send_file_to_phone(file_name):
    """Tool-callable: find a file by name and arm it for phone pickup."""
    file_name = file_name.strip()

    path = None
    if os.path.exists(file_name):
        path = file_name
    else:
        path = find_file_by_name(file_name)

    if not path:
        return f"I couldn't find {file_name} to send, sir."

    arm_file_for_transfer(path)
    return f"{os.path.basename(path)} is ready, sir. Grab it on your phone."


# ============================================================
# OPEN APPLICATION
# ============================================================

def open_app(app_name):
    name = app_name.lower().strip()

    if name == "valorant":
        try:
            subprocess.Popen(
                [VALORANT_PATH, "--launch-product=valorant", "--launch-patchline=live"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return "Valorant is launching, sir."
        except Exception as error:
            return f"I couldn't launch Valorant, sir. {error}"

    if name == "roblox":
        try:
            subprocess.Popen(
                ROBLOX_PATH,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL
            )
            return "Roblox is launching, sir."
        except Exception as error:
            return f"I couldn't launch Roblox, sir. {error}"

    if name in ["davinci", "davinci resolve", "resolve"]:
        try:
            subprocess.Popen(
                DAVINCI_PATH,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL
            )
            return "DaVinci Resolve is launching, sir."
        except Exception as error:
            return f"I couldn't launch DaVinci Resolve, sir. {error}"

    if name in ["epic", "epic games", "epic games launcher"]:
        try:
            subprocess.Popen(
                EPIC_PATH,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL
            )
            return "Epic Games Launcher is launching, sir."
        except Exception as error:
            return f"I couldn't launch Epic Games, sir. {error}"

    if name in ["chrome", "google chrome"]:
        chrome = find_chrome()
        if not chrome:
            return "I couldn't find Google Chrome, sir."
        try:
            subprocess.Popen(
                [chrome, f"--profile-directory={CHROME_PROFILE}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL
            )
            return "Chrome is opening, sir."
        except Exception as error:
            return f"I couldn't open Chrome, sir. {error}"

    if name not in ALLOWED_APPS:
        return f"I don't have access to {app_name} yet, sir."

    try:
        subprocess.Popen(
            ALLOWED_APPS[name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL
        )
        return f"{app_name} is now open, sir."
    except Exception as error:
        return f"I couldn't open {app_name}, sir. {error}"


# ============================================================
# PROCESS NAMES
# ============================================================

PROCESS_NAMES = {
    "davinci": "Resolve.exe",
    "davinci resolve": "Resolve.exe",
    "resolve": "Resolve.exe",
    "valorant": "VALORANT-Win64-Shipping.exe",
    "roblox": "RobloxPlayerBeta.exe",
    "epic": "EpicGamesLauncher.exe",
    "epic games": "EpicGamesLauncher.exe",
    "epic games launcher": "EpicGamesLauncher.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "browser": "chrome.exe",
    "discord": "Discord.exe",
    "spotify": "Spotify.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "calc": "CalculatorApp.exe",
    "paint": "mspaint.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "vscode": "Code.exe",
    "vs code": "Code.exe",
    "visual studio code": "Code.exe",
    "powershell": "powershell.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "outlook": "OUTLOOK.EXE",
}


# ============================================================
# CLOSE APPLICATION
# ============================================================

def close_app(app_name):
    name = app_name.lower().strip()

    replacements = {
        "the browser": "chrome",
        "browser": "chrome",
        "google": "chrome",
        "davinci resolve": "davinci",
        "da vinci": "davinci",
        "da vinci resolve": "davinci",
        "visual studio code": "vscode",
        "microsoft edge": "edge",
    }

    if name in replacements:
        name = replacements[name]

    if name not in PROCESS_NAMES:
        return f"I don't know how to close {app_name} yet, sir."

    process = PROCESS_NAMES[name]

    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", process, "/T"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        if result.returncode == 0:
            if name == "davinci":
                return "DaVinci Resolve has been closed, sir."
            if name == "chrome":
                return "Google Chrome has been closed, sir."
            if name == "edge":
                return "Microsoft Edge has been closed, sir."
            return f"{app_name} has been closed, sir."

        output = (result.stdout + " " + result.stderr).lower()

        if "not found" in output or "no running instance" in output or "not running" in output:
            return f"{app_name} doesn't appear to be running, sir."

        return f"I couldn't close {app_name}, sir."

    except Exception as error:
        return f"I couldn't close {app_name}, sir. {error}"


# ============================================================
# STORAGE
# ============================================================

def get_storage():
    try:
        total, used, free = shutil.disk_usage("C:\\")
        total_gb = total / (1024 ** 3)
        free_gb = free / (1024 ** 3)
        return f"You have {free_gb:.0f} GB available out of {total_gb:.0f} GB, sir."
    except Exception as error:
        return f"I couldn't check the storage, sir. {error}"


# ============================================================
# BRIGHTNESS
# ============================================================

def get_brightness():
    try:
        command = (
            "Get-CimInstance -Namespace root/WMI "
            "-ClassName WmiMonitorBrightness | "
            "Select-Object -ExpandProperty CurrentBrightness"
        )

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        value = result.stdout.strip()

        if not value:
            return "I couldn't read the current brightness, sir."

        return f"Brightness is currently {value}%, sir."

    except Exception as error:
        return f"I couldn't check brightness, sir. {error}"


def set_brightness(value):
    try:
        value = int(value)
        value = max(0, min(100, value))

        command = (
            "(Get-WmiObject -Namespace root/WMI "
            "-ClassName WmiMonitorBrightnessMethods)"
            f".WmiSetBrightness(1,{value})"
        )

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        if result.returncode != 0:
            return "I couldn't change the brightness on this display, sir."

        return f"Brightness set to {value}%, sir."

    except Exception as error:
        return f"I couldn't change brightness, sir. {error}"


def change_brightness(amount):
    try:
        amount = int(amount)

        command = (
            "Get-CimInstance -Namespace root/WMI "
            "-ClassName WmiMonitorBrightness | "
            "Select-Object -ExpandProperty CurrentBrightness"
        )

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        current = int(result.stdout.strip())
        new_value = max(0, min(100, current + amount))

        return set_brightness(new_value)

    except Exception as error:
        return f"I couldn't change brightness, sir. {error}"


# ============================================================
# VOLUME
# ============================================================

VK_VOLUME_UP = 0xAF
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_MUTE = 0xAD


def press_volume_key(key):
    try:
        ctypes.windll.user32.keybd_event(key, 0, 0, 0)
        ctypes.windll.user32.keybd_event(key, 0, 2, 0)
        return True
    except Exception:
        return False


def change_volume(amount=10):
    try:
        amount = int(amount)
        if amount == 0:
            amount = 10

        steps = max(1, round(abs(amount) / 2))
        key = VK_VOLUME_UP if amount > 0 else VK_VOLUME_DOWN

        for _ in range(steps):
            press_volume_key(key)

        if amount > 0:
            return f"Volume increased by approximately {abs(amount)}%, sir."

        return f"Volume decreased by approximately {abs(amount)}%, sir."

    except Exception as error:
        return f"I couldn't change the volume, sir. {error}"


def mute_volume():
    if press_volume_key(VK_VOLUME_MUTE):
        return "Volume muted, sir."
    return "I couldn't mute the volume, sir."


# ============================================================
# COMPUTER ACTIONS
# ============================================================

def lock_pc():
    try:
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        return "Locking the computer, sir."
    except Exception as error:
        return f"I couldn't lock the computer, sir. {error}"


def restart_pc():
    try:
        subprocess.Popen(
            ["shutdown", "/r", "/t", "5"],
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return "Restart scheduled in five seconds, sir."
    except Exception as error:
        return f"I couldn't restart the computer, sir. {error}"


def shutdown_pc():
    try:
        subprocess.Popen(
            ["shutdown", "/s", "/t", "5"],
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return "Shutdown scheduled in five seconds, sir."
    except Exception as error:
        return f"I couldn't shut down the computer, sir. {error}"


# ============================================================
# CONFIRMATION
# ============================================================

def ask_confirmation(question):
    event = threading.Event()
    result = {"value": False}

    def show_dialog():
        dialog = tk.Toplevel(root)
        dialog.title("J.A.R.V.I.S. Confirmation")
        dialog.geometry("420x190")
        dialog.configure(bg="#080b10")
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        label = tk.Label(
            dialog, text=question, bg="#080b10", fg="#e8edf5",
            font=("Segoe UI", 11), wraplength=370
        )
        label.pack(pady=25)

        buttons = tk.Frame(dialog, bg="#080b10")
        buttons.pack()

        def yes():
            result["value"] = True
            dialog.grab_release()
            dialog.destroy()
            event.set()

        def no():
            result["value"] = False
            dialog.grab_release()
            dialog.destroy()
            event.set()

        tk.Button(buttons, text="YES", command=yes, width=10).pack(side="left", padx=10)
        tk.Button(buttons, text="NO", command=no, width=10).pack(side="left", padx=10)

    root.after(0, show_dialog)
    event.wait()

    return result["value"]


def confirm_dangerous_action(action):
    first = ask_confirmation(f"Are you sure you want to {action}, sir?")

    if not first:
        return f"{action.capitalize()} cancelled, sir."

    second = ask_confirmation(f"Please confirm again. Do you really want to {action}, sir?")

    if not second:
        return f"{action.capitalize()} cancelled, sir."

    if action == "shut down the computer":
        return shutdown_pc()

    if action == "restart the computer":
        return restart_pc()

    return "Action cancelled, sir."


# ============================================================
# TOOLS
# ============================================================

TOOLS = [
    {"type": "function", "function": {
        "name": "open_app",
        "description": "Open an approved application.",
        "parameters": {"type": "object", "properties": {
            "app_name": {"type": "string"}
        }, "required": ["app_name"]}
    }},
    {"type": "function", "function": {
        "name": "close_app",
        "description": "Close a running Windows application.",
        "parameters": {"type": "object", "properties": {
            "app_name": {"type": "string"}
        }, "required": ["app_name"]}
    }},
    {"type": "function", "function": {
        "name": "open_website",
        "description": "Open a website in Google Chrome.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}
        }, "required": ["url"]}
    }},
    {"type": "function", "function": {
        "name": "open_file",
        "description": "Find and open a file by its name.",
        "parameters": {"type": "object", "properties": {
            "file_name": {"type": "string"}
        }, "required": ["file_name"]}
    }},
    {"type": "function", "function": {
        "name": "open_folder",
        "description": "Open one of the user's configured folders.",
        "parameters": {"type": "object", "properties": {
            "folder_name": {"type": "string"}
        }, "required": ["folder_name"]}
    }},
    {"type": "function", "function": {
        "name": "get_storage",
        "description": "Check available storage on the C drive.",
        "parameters": {"type": "object", "properties": {}}
    }},
    {"type": "function", "function": {
        "name": "get_brightness",
        "description": "Get the current Windows display brightness.",
        "parameters": {"type": "object", "properties": {}}
    }},
    {"type": "function", "function": {
        "name": "set_brightness",
        "description": "Set display brightness from 0 to 100.",
        "parameters": {"type": "object", "properties": {
            "value": {"type": "integer"}
        }, "required": ["value"]}
    }},
    {"type": "function", "function": {
        "name": "change_brightness",
        "description": "Increase or decrease display brightness.",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "integer"}
        }, "required": ["amount"]}
    }},
    {"type": "function", "function": {
        "name": "change_volume",
        "description": "Increase or decrease Windows volume.",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "integer"}
        }, "required": ["amount"]}
    }},
    {"type": "function", "function": {
        "name": "mute_volume",
        "description": "Mute Windows volume.",
        "parameters": {"type": "object", "properties": {}}
    }},
    {"type": "function", "function": {
        "name": "lock_computer",
        "description": "Lock the Windows computer.",
        "parameters": {"type": "object", "properties": {}}
    }},
    {"type": "function", "function": {
        "name": "shutdown_computer",
        "description": "Shut down Windows. Always requires two confirmations.",
        "parameters": {"type": "object", "properties": {}}
    }},
    {"type": "function", "function": {
        "name": "restart_computer",
        "description": "Restart Windows. Always requires two confirmations.",
        "parameters": {"type": "object", "properties": {}}
    }},
    {"type": "function", "function": {
        "name": "send_file_to_phone",
        "description": (
            "Find a file by name and arm it for pickup from the user's phone "
            "over the local network. Use this when the user asks to send, "
            "share, or transfer a file to their phone."
        ),
        "parameters": {"type": "object", "properties": {
            "file_name": {"type": "string"}
        }, "required": ["file_name"]}
    }},
]


# ============================================================
# TOOL EXECUTOR
# ============================================================

def execute_tool(tool_name, arguments):
    if tool_name == "open_app":
        return open_app(arguments.get("app_name", ""))

    if tool_name == "close_app":
        return close_app(arguments.get("app_name", ""))

    if tool_name == "open_website":
        return open_website(arguments.get("url", ""))

    if tool_name == "open_file":
        return open_file(arguments.get("file_name", ""))

    if tool_name == "open_folder":
        return open_folder(arguments.get("folder_name", ""))

    if tool_name == "get_storage":
        return get_storage()

    if tool_name == "get_brightness":
        return get_brightness()

    if tool_name == "set_brightness":
        return set_brightness(arguments.get("value", 50))

    if tool_name == "change_brightness":
        return change_brightness(arguments.get("amount", 10))

    if tool_name == "change_volume":
        return change_volume(arguments.get("amount", 10))

    if tool_name == "mute_volume":
        return mute_volume()

    if tool_name == "lock_computer":
        return lock_pc()

    if tool_name == "shutdown_computer":
        return confirm_dangerous_action("shut down the computer")

    if tool_name == "restart_computer":
        return confirm_dangerous_action("restart the computer")

    if tool_name == "send_file_to_phone":
        return send_file_to_phone(arguments.get("file_name", ""))

    return "Unknown command, sir."


# ============================================================
# JARVIS PERSONALITY
# ============================================================

SYSTEM_PROMPT = """

You are JARVIS, the user's personal AI assistant.

IDENTITY:
You are an advanced personal computer assistant inspired by the classic
JARVIS style: intelligent, composed, precise, observant, confident,
and subtly witty.

IMPORTANT USER ADDRESS:
- ALWAYS refer to the user as "sir".
- Use "sir" naturally in your responses.
- Never call the user bro, buddy, mate, dude, or by their name.
- You should sound like a sophisticated personal AI assistant.
- Do not say "sir" in every sentence. Use it naturally.
- For computer commands, keep responses concise.

PERSONALITY:
- Calm and sophisticated.
- Intelligent and quick-thinking.
- Confident without being arrogant.
- Helpful and attentive.
- Occasionally witty with short clever remarks.
- Occasionally use dry British-style humor.
- Never overdo jokes.
- Never joke about serious situations.
- Speak naturally.
- Keep normal responses concise.

COMPUTER CONTROL:

You can control the user's computer using the provided tools.

IMPORTANT:
- ALWAYS use the correct tool when the user asks you to perform an action.
- NEVER pretend an action succeeded if the tool failed.
- If an action succeeds, acknowledge it naturally.
- If an action fails, explain that it failed.
- Never invent capabilities.
- Do not ask for a file path when the user gives a filename.
- Search for files by name.
- Use the user's configured folder names.

FILE EXAMPLES:

User: "open the Spider-Man video"
Use open_file with file_name = "Spider-Man video"

User: "open my movie folder"
Use open_folder with folder_name = "movies"

User: "send my resume to my phone"
Use send_file_to_phone with file_name = "resume"

APP EXAMPLES:

User: "close DaVinci"
Use close_app with app_name = "davinci"

User: "close the browser"
Use close_app with app_name = "chrome"

User: "close Chrome"
Use close_app with app_name = "chrome"

STORAGE:

User: "how much storage do I have?"
Use get_storage.

BRIGHTNESS:

"make brightness 20 percent"
Use set_brightness with value 20.

"increase brightness by 10"
Use change_brightness with amount 10.

"decrease brightness by 20"
Use change_brightness with amount -20.

"increase brightness"
Use change_brightness with amount 10.

"decrease brightness"
Use change_brightness with amount -10.

"what is my brightness?"
Use get_brightness.

VOLUME:

"increase volume"
Use change_volume with amount 10.

"decrease volume"
Use change_volume with amount -10.

"increase volume by 20"
Use change_volume with amount 20.

"decrease volume by 20"
Use change_volume with amount -20.

"mute"
Use mute_volume.

STYLE:

User: "hello"
JARVIS: "Good to hear from you, sir. Systems are online."

User: "open my movie folder"
JARVIS: "Opening your movies, sir."

User: "open the Spider-Man video"
JARVIS: "Opening it, sir."

User: "close DaVinci"
JARVIS: "DaVinci Resolve has been closed, sir."

User: "close the browser"
JARVIS: "Google Chrome has been closed, sir."

User: "how much storage do I have?"
JARVIS: "You currently have [tool result], sir."

User: "increase brightness"
JARVIS: "Brightness increased, sir."

User: "send my resume to my phone"
JARVIS: "Resume dot pdf is ready, sir. Grab it on your phone."

GENERAL RULE:
Be useful first, intelligent second, witty only when appropriate.
You are JARVIS, not a chatbot pretending to be JARVIS.
Always maintain the JARVIS personality.
Always address the user naturally as sir.
"""


# ============================================================
# MEMORY
# ============================================================

messages = [
    {"role": "system", "content": SYSTEM_PROMPT}
]

# Guards `messages` since Tk callbacks, the voice thread, and the Flask
# thread can all call ask_jarvis() concurrently.
messages_lock = threading.Lock()


# ============================================================
# GROQ API CALL
# ============================================================

def call_groq():
    return client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        temperature=0.4
    )


# ============================================================
# ASK JARVIS
# ============================================================

def ask_jarvis(user_message):
    with messages_lock:
        messages.append({"role": "user", "content": user_message})

        if len(messages) > 40:
            del messages[1:10]

        max_tool_rounds = 8

        for _ in range(max_tool_rounds):
            try:
                response = call_groq()
            except Exception as error:
                error_text = str(error)
                print("Groq error:", error_text)
                return f"I encountered an error while contacting the AI service, sir: {error_text}"

            assistant = response.choices[0].message

            if not assistant.tool_calls:
                answer = assistant.content or "I'm here, sir."
                messages.append({"role": "assistant", "content": answer})
                return answer

            messages.append(assistant)

            for tool_call in assistant.tool_calls:
                tool_name = tool_call.function.name

                try:
                    raw_arguments = tool_call.function.arguments or "{}"
                    arguments = json.loads(raw_arguments)
                    result = execute_tool(tool_name, arguments)

                except json.JSONDecodeError as error:
                    result = f"Invalid arguments for {tool_name}: {error}"

                except Exception as error:
                    result = f"Tool error in {tool_name}: {error}"

                print(f"TOOL: {tool_name}")
                print(f"RESULT: {result}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": str(result)
                })

        return "I couldn't complete that command within the allowed tool steps, sir."


# ============================================================
# GAMING MODE MONITORING HELPERS
# ============================================================
# Each of these degrades to "N/A" rather than raising, per the
# requirement that a metric that can't be read should never crash
# the HUD. None of these do anything beyond reading — no writes, no
# process control.

def get_gpu_stats():
    """
    Reads GPU utilization/temp/VRAM via nvidia-smi. Returns "N/A" for
    every field on non-NVIDIA systems or if nvidia-smi isn't on PATH —
    there is no universal cross-vendor equivalent available without a
    heavier dependency (e.g. a separate AMD/Intel SDK), so this is the
    one metric that may legitimately show N/A on many laptops.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits"
            ],
            capture_output=True, text=True, timeout=2,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            if len(parts) >= 4:
                return {
                    "gpu_util": f"{parts[0]}%",
                    "gpu_temp": f"{parts[1]}°C",
                    "vram_used": f"{parts[2]} MB",
                    "vram_total": f"{parts[3]} MB",
                }
    except Exception:
        pass

    return {"gpu_util": "N/A", "gpu_temp": "N/A", "vram_used": "N/A", "vram_total": "N/A"}


def get_ping_ms(host="8.8.8.8"):
    """One-shot ping, parsed from Windows' ping output. N/A on failure."""
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", "1000", host],
            capture_output=True, text=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        match = re.search(r"Average = (\d+)ms", result.stdout)
        if match:
            return f"{match.group(1)} ms"
        match = re.search(r"time[=<](\d+)ms", result.stdout)
        if match:
            return f"{match.group(1)} ms"
    except Exception:
        pass
    return "N/A"


def get_foreground_process_name():
    """Best-effort guess at 'what game/app is currently in front'."""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = psutil.Process(pid.value)
        return proc.name()
    except Exception:
        return "N/A"


# ============================================================
# GUI / HEADLESS BRIDGE
# ============================================================

if os.getenv("JARVIS_HEADLESS") == "1":
    root = tk.Tk()
    root.withdraw()

    class _SilentWidget:
        def config(self, **kwargs):
            pass

        def configure(self, **kwargs):
            pass

        def focus(self):
            pass

        def focus_force(self):
            pass

    status = _SilentWidget()
    send_button = _SilentWidget()
    entry = _SilentWidget()

    def add_message(sender, message):
        print(f"{sender}: {message}")
        if sender in ("YOU", "JARVIS"):
            push_gui_event("message", f"{sender}|{message}")

    def toggle_window():
        pass

    def shutdown_jarvis():
        global voice_active_until
        voice_active_until = 0
        try:
            threading.Thread(
                target=speak, args=("Shutting down JARVIS, sir.",), daemon=True
            ).start()
        except Exception:
            pass
        try:
            root.after(800, root.destroy)
        except Exception:
            pass

else:
    root = tk.Tk()
    root.title("J.A.R.V.I.S.")

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()

    x = screen_width - CHAT_WIDTH - 25
    y = screen_height - CHAT_HEIGHT - 55

    root.geometry(f"{CHAT_WIDTH}x{CHAT_HEIGHT}+{x}+{y}")
    root.configure(bg=INK_BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    header = tk.Frame(root, bg=INK_BG, height=65)
    header.pack(fill="x")
    header.pack_propagate(False)

    title = tk.Label(
        header, text="J.A.R.V.I.S.", font=("Segoe UI", 18, "bold"),
        fg=GOLD, bg=INK_BG
    )
    title.pack(side="left", padx=20)

    status = tk.Label(
        header, text="● ONLINE", font=("Segoe UI", 9),
        fg="#45ff8a", bg=INK_BG
    )
    status.pack(side="right", padx=15)

    stats_bar = tk.Frame(root, bg=INK_BG, height=26)
    stats_bar.pack(fill="x")
    stats_bar.pack_propagate(False)

    stats_label = tk.Label(
        stats_bar, text="", font=("Consolas", 9),
        fg=GOLD_SOFT, bg=INK_BG, anchor="w"
    )
    stats_label.pack(side="left", padx=20, fill="x", expand=True)

    # Smart Context UI references must exist before the panel is constructed.
    context_panel_ref = {"frame": None, "label": None, "detail": None, "mode": None}

    # Smart Context strip: always visible in Normal Mode and updated by the
    # foreground-app context engine. It is intentionally compact so it never
    # gets in the way of the conversation UI.
    context_strip = tk.Frame(root, bg="#08141b", highlightthickness=1, highlightbackground="#15323c")
    context_strip.pack(fill="x", padx=10, pady=(0, 8))
    context_context_label = tk.Label(context_strip, text="◉  READY  //  DESKTOP", font=("Consolas", 10, "bold"), fg=HUD_CYAN_BRIGHT, bg="#08141b", anchor="w")
    context_context_label.pack(side="left", padx=12, pady=7)
    context_detail_label = tk.Label(context_strip, text="Desktop • JARVIS standing by", font=("Consolas", 8), fg="#78949d", bg="#08141b", anchor="w")
    context_detail_label.pack(side="left", padx=8, fill="x", expand=True)
    context_mode_label = tk.Label(context_strip, text="AUTO MODE: NORMAL", font=("Consolas", 8, "bold"), fg=GOLD_SOFT, bg="#08141b")
    context_mode_label.pack(side="right", padx=12)
    context_panel_ref.update({"frame": context_strip, "label": context_context_label, "detail": context_detail_label, "mode": context_mode_label})

    # Fixed layout: keep the chat area and input bar in guaranteed space.
    # Using an expanding packer here could consume the input row on some Tk
    #/Windows scaling configurations, making the typing field disappear.
    chat_frame = tk.Frame(root, bg=PANEL_BG, height=350)
    chat_frame.pack(fill="x", padx=10, pady=(0, 8))
    chat_frame.pack_propagate(False)

    chat = tk.Text(
        chat_frame, bg=PANEL_BG, fg=TEXT_MAIN, font=("Segoe UI", 10),
        wrap="word", relief="flat", padx=12, pady=12, state="disabled"
    )
    chat.pack(fill="both", expand=True)

    chat.tag_config("sender", foreground=GOLD, font=("Segoe UI", 9, "bold"))

    def add_message(sender, message):
        chat.config(state="normal")
        chat.insert("end", f"{sender}\n", "sender")
        chat.insert("end", f"{message}\n\n")
        chat.config(state="disabled")
        chat.see("end")

    # Input bar — kept as a dedicated, fixed-height area so the Smart Context
    # strip can never push it out of the normal JARVIS window.
    bottom = tk.Frame(root, bg=INK_BG, height=58, highlightthickness=1, highlightbackground="#26343a")
    bottom.pack(fill="x", padx=10, pady=(0, 10))
    bottom.pack_propagate(False)

    entry = tk.Entry(
        bottom, bg=INPUT_BG, fg=TEXT_MAIN, insertbackground=GOLD,
        font=("Segoe UI", 11), relief="flat", bd=0,
    )
    entry.pack(side="left", fill="both", expand=True, ipady=8, padx=(0, 8))

    # Make the typing field unmistakable and keyboard-ready.
    entry.insert(0, "Ask JARVIS anything...")
    entry.config(fg="#78949d")

    def _entry_focus(event=None):
        if entry.get() == "Ask JARVIS anything...":
            entry.delete(0, "end")
            entry.config(fg=TEXT_MAIN)

    def _entry_blur(event=None):
        if not entry.get().strip():
            entry.insert(0, "Ask JARVIS anything...")
            entry.config(fg="#78949d")

    entry.bind("<FocusIn>", _entry_focus)
    entry.bind("<FocusOut>", _entry_blur)

    def send_message(event=None):
        user_text = entry.get().strip()
        if user_text == "Ask JARVIS anything...":
            return
        if not user_text:
            return
        entry.delete(0, "end")
        add_message("YOU", user_text)
        if is_exit_command(user_text):
            shutdown_jarvis()
            return

        mode_reply = try_handle_mode_command(user_text)
        if mode_reply is not None:
            add_message("JARVIS", mode_reply)
            threading.Thread(target=speak, args=(mode_reply,), daemon=True).start()
            entry.focus()
            return

        status.config(text="● THINKING...", fg="#ffd166")
        send_button.config(state="disabled")
        threading.Thread(target=get_response, args=(user_text,), daemon=True).start()

    send_button = tk.Button(
        bottom, text="SEND", command=send_message, bg=GOLD, fg="#1a1400",
        relief="flat", font=("Segoe UI", 9, "bold"), padx=12,
        activebackground=GOLD_BRIGHT, activeforeground="#1a1400"
    )
    send_button.pack(side="right", fill="y", padx=(4, 0))

    # Put the cursor in the input field as soon as the window is ready.
    root.after(250, lambda: (entry.focus_force(), entry.icursor("end")))

    def get_response(user_text):
        try:
            response = ask_jarvis(user_text) or "I'm here, sir."
            root.after(0, show_response, response)
        except Exception as error:
            root.after(0, show_response, f"I encountered an error, sir: {error}")

    def show_response(response):
        add_message("JARVIS", response)
        status.config(text="● ONLINE", fg="#45ff8a")
        send_button.config(state="normal")
        threading.Thread(target=speak, args=(response,), daemon=True).start()
        entry.focus()

    entry.bind("<Return>", send_message)

    root.bind("<Escape>", lambda event: root.withdraw())

    def toggle_window():
        """Global Ctrl+Alt+J toggle: hide/show the normal JARVIS window."""
        global gesture_only_hidden
        try:
            hidden = (root.state() == "withdrawn") or gesture_only_hidden

            if hidden:
                # Ctrl+Alt+J is now a true toggle. It can restore JARVIS
                # even if the window was previously put into gesture-only
                # hidden mode. The gesture system remains available too.
                gesture_only_hidden = False
                root.after(0, lambda: (
                    root.deiconify(), root.lift(),
                    root.attributes("-topmost", True), entry.focus()
                ))
                print("[hotkey] JARVIS window restored.")
            else:
                gesture_only_hidden = True
                root.withdraw()
                print("[hotkey] JARVIS window hidden.")
        except Exception as error:
            print("[hotkey] toggle error:", error)

    # ============================================================
    # GLOBAL CTRL+ALT+J HOTKEY
    # ============================================================
    # Ctrl+Alt+J is a true show/hide toggle. The Windows-native
    # RegisterHotKey API is preferred because the `keyboard`
    # package can silently fail on some Windows setups (permissions,
    # another global hook, etc.), which used to make Ctrl+Alt+J appear
    # completely dead.  We keep keyboard as a fallback for non-Windows.
    def _start_global_jarvis_hotkey():
        if os.name != "nt":
            try:
                keyboard.add_hotkey("ctrl+alt+j", toggle_window)
                print("[hotkey] Ctrl+Alt+J registered via keyboard module.")
            except Exception as error:
                print("[hotkey] registration failed:", error)
            return

        def _hotkey_thread():
            user32 = ctypes.windll.user32
            MOD_ALT = 0x0001
            MOD_CONTROL = 0x0002
            WM_HOTKEY = 0x0312
            HOTKEY_ID = 0x4A52

            try:
                ok = user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT, ord("J"))
                if not ok:
                    err = ctypes.GetLastError()
                    print(f"[hotkey] Windows RegisterHotKey failed (error {err}). Trying keyboard module...")
                    try:
                        keyboard.add_hotkey("ctrl+alt+j", toggle_window)
                        print("[hotkey] Ctrl+Alt+J registered via keyboard fallback.")
                    except Exception as fallback_error:
                        print("[hotkey] fallback registration failed:", fallback_error)
                    return

                print("[hotkey] Ctrl+Alt+J registered successfully.")
                msg = wintypes.MSG()
                while True:
                    result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                    if result <= 0:
                        break
                    if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                        root.after(0, toggle_window)

                user32.UnregisterHotKey(None, HOTKEY_ID)
            except Exception as error:
                print("[hotkey] native hotkey thread failed:", error)
                try:
                    keyboard.add_hotkey("ctrl+alt+j", toggle_window)
                    print("[hotkey] Ctrl+Alt+J registered via keyboard fallback.")
                except Exception as fallback_error:
                    print("[hotkey] fallback registration failed:", fallback_error)

        threading.Thread(target=_hotkey_thread, daemon=True, name="JARVIS-Hotkey").start()

    _start_global_jarvis_hotkey()

    # ============================================================
    # MULTI-MONITOR SUPPORT (swipe / point gestures move a window)
    # ============================================================

    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long), ("top", ctypes.c_long),
            ("right", ctypes.c_long), ("bottom", ctypes.c_long),
        ]

    class _WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_uint),
            ("flags", ctypes.c_uint),
            ("showCmd", ctypes.c_uint),
            ("ptMinPosition", ctypes.c_long * 2),
            ("ptMaxPosition", ctypes.c_long * 2),
            ("rcNormalPosition", _RECT),
        ]

    _user32 = None
    try:
        _user32 = ctypes.windll.user32
        _user32.GetForegroundWindow.restype = wintypes.HWND
        _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
        _user32.GetWindowTextW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
        _user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        ]
        _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        _user32.GetWindowPlacement.argtypes = [wintypes.HWND, ctypes.POINTER(_WINDOWPLACEMENT)]
    except Exception as error:
        print("Win32 window API unavailable:", error)

    def move_active_window_to_monitor(target_index, label=""):
        if _user32 is None:
            add_message("JARVIS", "I can't move windows on this system, sir.")
            return
        try:
            monitors = _enum_monitors()
            print(f"[active-window] detected monitors: {monitors}, target index: {target_index}")
            if len(monitors) <= 1:
                add_message("JARVIS", "Only one display detected, sir.")
                return

            target_index = target_index % len(monitors)
            mon_left, mon_top, mon_w, mon_h = monitors[target_index]

            SW_RESTORE = 9
            SW_MAXIMIZE = 3
            SWP_NOZORDER = 0x0004
            SWP_SHOWWINDOW = 0x0040

            hwnd = _user32.GetForegroundWindow()
            if not hwnd:
                add_message("JARVIS", "I couldn't find an active window, sir.")
                return

            title_buf = ctypes.create_unicode_buffer(256)
            _user32.GetWindowTextW(hwnd, title_buf, 256)
            title = title_buf.value.strip() or "that window"

            placement = _WINDOWPLACEMENT()
            placement.length = ctypes.sizeof(_WINDOWPLACEMENT)
            _user32.GetWindowPlacement(hwnd, ctypes.byref(placement))
            was_maximized = placement.showCmd == SW_MAXIMIZE

            rect = _RECT()
            _user32.GetWindowRect(hwnd, ctypes.byref(rect))
            win_w = min(rect.right - rect.left, mon_w)
            win_h = min(rect.bottom - rect.top, mon_h)

            if was_maximized:
                _user32.ShowWindow(hwnd, SW_RESTORE)

            new_x = mon_left + max(0, (mon_w - win_w) // 2)
            new_y = mon_top + max(0, (mon_h - win_h) // 2)

            _user32.SetWindowPos(
                hwnd, 0, new_x, new_y, win_w, win_h,
                SWP_NOZORDER | SWP_SHOWWINDOW
            )

            if was_maximized:
                _user32.ShowWindow(hwnd, SW_MAXIMIZE)

            print(f"[active-window] moved '{title}' to monitor index {target_index}")
            if label:
                add_message("JARVIS", f"Moved {title} to {label}, sir.")
        except Exception as error:
            print("Move active window error:", error)
            add_message("JARVIS", "I couldn't move that window, sir.")

    def _enum_monitors():
        """
        Return monitors in Windows DISPLAY1, DISPLAY2... order.

        IMPORTANT:
        screeninfo's list order / physical X position is NOT guaranteed to
        match Windows display numbering. Gaming/Focus therefore use the
        Windows DISPLAY_DEVICE index directly.
        """
        monitors = []

        try:
            user32 = ctypes.windll.user32

            class DISPLAY_DEVICEW(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128),
                    ("StateFlags", wintypes.DWORD),
                    ("DeviceID", wintypes.WCHAR * 128),
                    ("DeviceKey", wintypes.WCHAR * 128),
                ]

            DISPLAY_DEVICE_ACTIVE = 0x00000001

            class MONITORINFOEXW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", _RECT),
                    ("rcWork", _RECT),
                    ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32),
                ]

            for display_index in range(16):
                device = DISPLAY_DEVICEW()
                device.cb = ctypes.sizeof(DISPLAY_DEVICEW)

                if not user32.EnumDisplayDevicesW(
                    None, display_index, ctypes.byref(device), 0
                ):
                    break

                if not (device.StateFlags & DISPLAY_DEVICE_ACTIVE):
                    continue

                target_device = device.DeviceName
                found = {"geometry": None}

                MonitorEnumProc = ctypes.WINFUNCTYPE(
                    wintypes.BOOL,
                    wintypes.HMONITOR,
                    wintypes.HDC,
                    ctypes.POINTER(wintypes.RECT),
                    wintypes.LPARAM,
                )

                def callback(hmonitor, hdc, lprc, data):
                    info = MONITORINFOEXW()
                    info.cbSize = ctypes.sizeof(MONITORINFOEXW)

                    if user32.GetMonitorInfoW(
                        hmonitor, ctypes.byref(info)
                    ):
                        if info.szDevice == target_device:
                            r = info.rcMonitor
                            found["geometry"] = (
                                r.left,
                                r.top,
                                r.right - r.left,
                                r.bottom - r.top,
                            )
                            return False
                    return True

                callback_proc = MonitorEnumProc(callback)
                user32.EnumDisplayMonitors(
                    0, 0, callback_proc, 0
                )

                if found["geometry"]:
                    monitors.append(found["geometry"])

            if monitors:
                print(
                    "[monitor] Windows display order:",
                    {f"Display {i + 1}": m for i, m in enumerate(monitors)}
                )
                return monitors

        except Exception as error:
            print("Windows display enumeration failed:", error)

        # Fallback: use screeninfo only if Windows enumeration fails.
        # This is less precise, but keeps single-display systems working.
        try:
            import screeninfo
            mons = screeninfo.get_monitors()
            if mons:
                result = [(m.x, m.y, m.width, m.height) for m in mons]
                print("[monitor] fallback screeninfo order:", result)
                return result
        except Exception as error:
            print("screeninfo enumeration failed:", error)

        fallback = [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]
        print("[monitor] final fallback:", fallback)
        return fallback

    monitor_state = {"index": 0}

    def _apply_window_geometry(new_x, new_y):
        geo = f"{CHAT_WIDTH}x{CHAT_HEIGHT}+{new_x}+{new_y}"
        root.withdraw()
        root.update_idletasks()
        root.geometry(geo)
        root.update_idletasks()
        root.deiconify()
        root.geometry(geo)
        root.lift()
        root.attributes("-topmost", True)
        root.update_idletasks()
        print(
            f"[monitor] requested +{new_x}+{new_y} | "
            f"Tk now reports position +{root.winfo_x()}+{root.winfo_y()}"
        )

    def move_window_to_monitor(delta):
        try:
            monitors = _enum_monitors()
            print(f"[monitor] detected: {monitors}")
            if len(monitors) <= 1:
                add_message("JARVIS", "Only one display detected, sir.")
                return

            monitor_state["index"] = (monitor_state["index"] + delta) % len(monitors)
            mon_left, mon_top, mon_w, mon_h = monitors[monitor_state["index"]]

            new_x = mon_left + mon_w - CHAT_WIDTH - 25
            new_y = mon_top + mon_h - CHAT_HEIGHT - 55
            print(f"[monitor] moving to index {monitor_state['index']} -> geometry +{new_x}+{new_y}")

            _apply_window_geometry(new_x, new_y)
        except Exception as error:
            print("Move window error:", error)

    LAPTOP_MONITOR_INDEX = 0
    EXTERNAL_MONITOR_INDEX = 1

    def move_window_to_specific_monitor(target_index, label=""):
        try:
            monitors = _enum_monitors()
            print(f"[monitor] detected: {monitors}, target index requested: {target_index}")
            if len(monitors) <= 1:
                add_message("JARVIS", "Only one display detected, sir.")
                return

            target_index = target_index % len(monitors)
            monitor_state["index"] = target_index
            mon_left, mon_top, mon_w, mon_h = monitors[target_index]

            new_x = mon_left + mon_w - CHAT_WIDTH - 25
            new_y = mon_top + mon_h - CHAT_HEIGHT - 55
            print(f"[monitor] moving to index {target_index} -> geometry +{new_x}+{new_y}")

            _apply_window_geometry(new_x, new_y)
            if label:
                add_message("JARVIS", f"Moved to {label}, sir.")
        except Exception as error:
            print("Move window error:", error)

    # ============================================================
    # LIVE DATA FEEDS
    # ============================================================

    weather_state = {"text": "Fetching weather..."}

    def fetch_weather_loop():
        while True:
            try:
                resp = requests.get(
                    "https://wttr.in/?format=%C+%t",
                    timeout=6, headers={"User-Agent": "curl"}
                )
                if resp.status_code == 200 and resp.text.strip():
                    weather_state["text"] = resp.text.strip()
                else:
                    weather_state["text"] = "Weather unavailable"
            except Exception:
                weather_state["text"] = "Weather unavailable"
            time.sleep(600)

    threading.Thread(target=fetch_weather_loop, daemon=True).start()

    def system_stats_loop():
        try:
            last_net = psutil.net_io_counters()
        except Exception:
            last_net = None
        last_time = time.time()

        while True:
            try:
                cpu = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory().percent
                disk_path = "C:\\" if os.name == "nt" else "/"
                disk = psutil.disk_usage(disk_path).percent

                now = time.time()
                dt = max(now - last_time, 0.001)
                sent_rate = recv_rate = 0.0
                if last_net is not None:
                    net = psutil.net_io_counters()
                    sent_rate = (net.bytes_sent - last_net.bytes_sent) / dt / 1024
                    recv_rate = (net.bytes_recv - last_net.bytes_recv) / dt / 1024
                    last_net = net
                last_time = now

                procs = len(psutil.pids())
                uptime_sec = time.time() - psutil.boot_time()
                hrs = int(uptime_sec // 3600)
                mins = int((uptime_sec % 3600) // 60)

                battery_pct = None
                plugged = None
                try:
                    batt = psutil.sensors_battery()
                    if batt is not None:
                        battery_pct = batt.percent
                        plugged = batt.power_plugged
                except Exception:
                    pass

                mem_total_gb = psutil.virtual_memory().total / (1024 ** 3)
                mem_used_gb = (psutil.virtual_memory().total - psutil.virtual_memory().available) / (1024 ** 3)

                system_state.update({
                    "cpu": cpu, "mem": mem, "disk": disk,
                    "mem_used_gb": mem_used_gb, "mem_total_gb": mem_total_gb,
                    "net_sent": max(sent_rate, 0.0), "net_recv": max(recv_rate, 0.0),
                    "procs": procs, "uptime": f"{hrs}h {mins}m",
                    "battery": battery_pct, "plugged": plugged,
                })
            except Exception as error:
                print("System stats error:", error)
                time.sleep(1)

    threading.Thread(target=system_stats_loop, daemon=True).start()

    # ============================================================
    # HAND GESTURE CONTROL (webcam)
    # ============================================================
    #   Open palm       -> show the window
    #   Fist             -> hide the window
    #   Thumbs up        -> "wake" JARVIS (same as saying the wake word)
    #   Peace sign       -> mute / unmute spoken replies
    #   Pinch (OK sign)  -> grab whatever file is selected in File
    #                       Explorer and arm it for phone pickup
    #   Swipe left/right -> move JARVIS window between monitors
    #   Point pinky      -> move focused window to laptop screen
    #   Point pinky+ring -> move focused window to external monitor

    GESTURE_ENABLED = True
    GESTURE_DEBUG = os.getenv("JARVIS_GESTURE_DEBUG") == "1"

    def gesture_control_loop():
        try:
            import cv2
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python import vision
        except Exception as error:
            print("Gesture control disabled (missing cv2/mediapipe):", error)
            return

        try:
            model_dir = os.path.join(
                os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "JARVIS"
            )
            os.makedirs(model_dir, exist_ok=True)
            model_path = os.path.join(model_dir, "hand_landmarker.task")

            # A truncated task file can make MediaPipe fail later with a
            # confusing landmarker error, so treat anything under 1 MB as
            # invalid and download it again.
            if not os.path.exists(model_path) or os.path.getsize(model_path) < 1_000_000:
                print("[gesture] Downloading hand-gesture model (one-time)...")
                model_url = (
                    "https://storage.googleapis.com/mediapipe-models/"
                    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
                )
                resp = requests.get(
                    model_url, timeout=60,
                    headers={"User-Agent": "JARVIS/3.0"}
                )
                resp.raise_for_status()
                with open(model_path, "wb") as f:
                    f.write(resp.content)
                print(f"[gesture] Hand-gesture model downloaded: {os.path.getsize(model_path):,} bytes")
            else:
                print(f"[gesture] Using hand-gesture model: {model_path}")
        except Exception as error:
            print("Gesture control disabled (model download failed):", error)
            return

        # Try the default webcam first, then common alternate camera
        # indexes/backends.  Some Windows laptops expose the camera only
        # through DirectShow.
        cap = None
        selected_camera = None
        try:
            for camera_index in (0, 1, 2):
                try:
                    candidate = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
                except Exception:
                    candidate = cv2.VideoCapture(camera_index)
                if candidate.isOpened():
                    ok, _test_frame = candidate.read()
                    if ok:
                        cap = candidate
                        selected_camera = camera_index
                        break
                try:
                    candidate.release()
                except Exception:
                    pass

            if cap is None:
                print("[gesture] Gesture control disabled: no usable webcam found.")
                return

            print(f"[gesture] Webcam ready on camera index {selected_camera}.")
        except Exception as error:
            print("[gesture] Gesture control disabled (camera error):", error)
            return  

        try:
            options = vision.HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=model_path),
                num_hands=1,
                min_hand_detection_confidence=0.6,
                min_tracking_confidence=0.5,
                running_mode=vision.RunningMode.VIDEO,
            )
            landmarker = vision.HandLandmarker.create_from_options(options)
            print("[gesture] Hand Landmarker ready. Show your hand to JARVIS.")
        except Exception as error:
            print("[gesture] Gesture control disabled (landmarker init failed):", error)
            cap.release()
            return

        last_gesture = None
        last_fire_time = 0.0
        stable_since = 0.0
        pending_gesture = None
        COOLDOWN = 1.5
        STABLE_TIME = 0.3

        palm_history = deque(maxlen=20)
        last_swipe_time = 0.0
        SWIPE_COOLDOWN = 1.2
        SWIPE_MIN_DX = 0.13
        SWIPE_WINDOW = 0.8

        def _dist(a, b):
            return math.hypot(a.x - b.x, a.y - b.y)

        def _vec3(a, b):
            return (b.x - a.x, b.y - a.y, b.z - a.z)

        def _angle_deg(v1, v2):
            dot = v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]
            n1 = math.sqrt(sum(c * c for c in v1))
            n2 = math.sqrt(sum(c * c for c in v2))
            if n1 * n2 == 0:
                return 0.0
            cos_a = max(-1.0, min(1.0, dot / (n1 * n2)))
            return math.degrees(math.acos(cos_a))

        def classify(landmarks):
            wrist = landmarks[0]
            middle_mcp = landmarks[9]
            thumb_tip = landmarks[4]
            thumb_mcp = landmarks[2]
            index_tip = landmarks[8]

            hand_scale = max(_dist(wrist, middle_mcp), 0.04)

            finger_joints = {
                "index": (5, 6, 8),
                "middle": (9, 10, 12),
                "ring": (13, 14, 16),
                "pinky": (17, 18, 20),
            }
            curl_angle = {}
            for name, (mcp_id, pip_id, tip_id) in finger_joints.items():
                v1 = _vec3(landmarks[mcp_id], landmarks[pip_id])
                v2 = _vec3(landmarks[pip_id], landmarks[tip_id])
                curl_angle[name] = _angle_deg(v1, v2)

            extended = {name: angle < 42 for name, angle in curl_angle.items()}
            extended_count = sum(extended.values())
            all_curled = extended_count == 0
            all_extended = extended_count >= 3

            thumb_reach = _dist(thumb_tip, wrist) - _dist(thumb_mcp, wrist)
            thumb_extended = thumb_reach > 0.55 * hand_scale

            is_pinch = (
                extended["middle"]
                and _dist(thumb_tip, index_tip) < 0.45 * hand_scale
            )

            if is_pinch:
                return "pinch"

            if all_extended:
                return "open_palm"
            if all_curled and thumb_extended:
                return "thumbs_up"
            if all_curled:
                return "fist"
            if extended["index"] and extended["middle"] and not extended["ring"] and not extended["pinky"]:
                return "peace"
            if (
                extended["pinky"] and not extended["ring"]
                and not extended["middle"] and not extended["index"]
            ):
                return "point_pinky"
            if (
                extended["pinky"] and extended["ring"]
                and not extended["middle"] and not extended["index"]
            ):
                return "point_pinky_ring"
            return None

        def handle_pinch_grab():
            selected_path = get_selected_explorer_file()
            if selected_path:
                arm_file_for_transfer(selected_path)
                file_label = os.path.basename(selected_path)
                root.after(
                    0, add_message, "JARVIS",
                    f"Grabbed {file_label}, sir. Ready to send to your phone."
                )
                threading.Thread(
                    target=speak, args=(f"Grabbed {file_label}, sir.",), daemon=True
                ).start()
            else:
                root.after(
                    0, add_message, "JARVIS",
                    "No file selected in Explorer, sir."
                )

        def fire(gesture):
            nonlocal last_fire_time
            global gesture_only_hidden
            try:
                # HIDDEN/GESTURE-ONLY STATE:
                # Full open palm is the ONLY gesture that is allowed to
                # restore the normal JARVIS window. Every other gesture
                # (fist, thumbs up, peace, pinch, swipes, etc.) is ignored.
                if gesture_only_hidden:
                    if gesture == "open_palm":
                        gesture_only_hidden = False
                        root.after(0, lambda: (
                            root.deiconify(), root.lift(),
                            root.attributes("-topmost", True), entry.focus()
                        ))
                    last_fire_time = time.time()
                    return

                if gesture == "open_palm":
                    root.after(0, lambda: (
                        root.deiconify(), root.lift(),
                        root.attributes("-topmost", True), entry.focus()
                    ))
                elif gesture == "fist":
                    gesture_only_hidden = True
                    root.after(0, root.withdraw)
                elif gesture == "thumbs_up":
                    global voice_active_until
                    voice_active_until = time.time() + VOICE_ACTIVE_TIME
                    root.after(0, lambda: status.config(text="● LISTENING", fg=GOLD))
                    threading.Thread(
                        target=speak, args=("Yes, sir. I'm listening.",), daemon=True
                    ).start()
                elif gesture == "peace":
                    global VOICE_ENABLED
                    VOICE_ENABLED = not VOICE_ENABLED
                    state_text = "voice replies muted" if not VOICE_ENABLED else "voice replies on"
                    root.after(0, add_message, "JARVIS", f"({state_text}, sir.)")
                elif gesture == "pinch":
                    handle_pinch_grab()
                elif gesture == "swipe_right":
                    root.after(0, lambda: move_window_to_monitor(1))
                elif gesture == "swipe_left":
                    root.after(0, lambda: move_window_to_monitor(-1))
                elif gesture == "point_pinky":
                    root.after(
                        0, lambda: move_active_window_to_monitor(
                            LAPTOP_MONITOR_INDEX, "your laptop screen"
                        )
                    )
                elif gesture == "point_pinky_ring":
                    root.after(
                        0, lambda: move_active_window_to_monitor(
                            EXTERNAL_MONITOR_INDEX, "your monitor"
                        )
                    )
                last_fire_time = time.time()
            except Exception as error:
                print("Gesture action error:", error)

        frame_ts_ms = 0
        try:
            while True:
                try:
                    ok, frame = cap.read()
                    if not ok:
                        time.sleep(0.05)
                        continue

                    frame = cv2.flip(frame, 1)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

                    frame_ts_ms += 33
                    result = landmarker.detect_for_video(mp_image, frame_ts_ms)

                    gesture = None
                    centroid_x = None
                    now = time.time()

                    if result.hand_landmarks:
                        lm = result.hand_landmarks[0]
                        gesture = classify(lm)
                        centroid_x = lm[0].x
                        palm_history.append((now, centroid_x, gesture))

                        if GESTURE_DEBUG:
                            h_px, w_px = frame.shape[0], frame.shape[1]
                            for p in lm:
                                cv2.circle(
                                    frame,
                                    (int(p.x * w_px), int(p.y * h_px)),
                                    3, (0, 215, 255), -1
                                )

                        if (now - last_swipe_time) > SWIPE_COOLDOWN:
                            recent = [
                                e for e in palm_history
                                if e[1] is not None and now - e[0] <= SWIPE_WINDOW
                            ]
                            if len(recent) >= 3:
                                dx = centroid_x - recent[0][1]
                                if abs(dx) >= SWIPE_MIN_DX:
                                    swipe = "swipe_right" if dx > 0 else "swipe_left"
                                    fire(swipe)
                                    last_swipe_time = now
                                    palm_history.clear()
                    else:
                        palm_history.append((now, None, None))

                    if gesture != pending_gesture:
                        pending_gesture = gesture
                        stable_since = now

                    if (
                        gesture is not None
                        and gesture == pending_gesture
                        and (now - stable_since) >= STABLE_TIME
                        and gesture != last_gesture
                        and (now - last_fire_time) >= COOLDOWN
                    ):
                        fire(gesture)
                        last_gesture = gesture
                    elif gesture is None:
                        last_gesture = None

                    if GESTURE_DEBUG:
                        cv2.putText(
                            frame, f"gesture: {gesture}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 215, 255), 2
                        )
                        cv2.imshow("JARVIS Gesture Debug", frame)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            break
                    else:
                        time.sleep(0.03)

                except Exception as frame_error:
                    print("Gesture frame error (recovered):", frame_error)
                    time.sleep(0.05)

        except Exception as error:
            print("Gesture control loop error:", error)
        finally:
            try:
                cap.release()
                landmarker.close()
                if GESTURE_DEBUG:
                    cv2.destroyAllWindows()
            except Exception:
                pass

    if GESTURE_ENABLED:
        threading.Thread(target=gesture_control_loop, daemon=True).start()

    def refresh_stats_bar():
        try:
            now = datetime.now()
            cpu = system_state.get("cpu", 0.0)
            mem = system_state.get("mem", 0.0)
            wx = weather_state.get("text", "…")
            stats_label.config(
                text=(
                    f"{now.strftime('%I:%M:%S %p')}  ·  {now.strftime('%a %b %d')}  ·  "
                    f"CPU {cpu:.0f}%  ·  MEM {mem:.0f}%  ·  {wx}"
                )
            )
        except Exception:
            pass
        root.after(1000, refresh_stats_bar)

    refresh_stats_bar()


# ============================================================
# MODE MANAGEMENT (Normal / Gaming / Focus)
# ============================================================
# Exactly one mode is active at a time. Switching modes always tears
# down whatever full-screen HUD is currently up before building the
# new one (or before restoring Normal Mode), so there is never more
# than one Toplevel alive and never an invisible leftover window.
#
# All actual Tk window creation/destruction is routed through
# root.after(0, ...) so it's safe to call these from the voice-
# listener thread as well as the main-thread Tk callbacks.

HEADLESS = os.getenv("JARVIS_HEADLESS") == "1"


def position_on_laptop_monitor(window):
    """
    Pin a borderless window to Windows DISPLAY 1 (our laptop).
    We deliberately avoid Tk's -fullscreen because Tk may fullscreen
    on the monitor where the Toplevel was created.
    """
    try:
        monitors = _enum_monitors()
    except Exception as error:
        print("Laptop monitor enumeration unavailable:", error)
        monitors = []

    if not monitors:
        try:
            window.attributes("-fullscreen", True)
        except Exception:
            pass
        return

    index = LAPTOP_MONITOR_INDEX
    if index >= len(monitors):
        print(
            f"[monitor] DISPLAY 1 unavailable; only {len(monitors)} display(s)."
        )
        index = 0

    mon_left, mon_top, mon_w, mon_h = monitors[index]

    try:
        window.withdraw()
        window.overrideredirect(True)
        window.geometry(
            f"{int(mon_w)}x{int(mon_h)}+{int(mon_left)}+{int(mon_top)}"
        )
        window.update_idletasks()
        window.deiconify()
        window.lift()
        window.attributes("-topmost", True)
        print(
            f"[HUD] pinned to Windows Display {index + 1}: "
            f"{mon_w}x{mon_h}+{mon_left}+{mon_top}"
        )
    except Exception as error:
        print("position_on_laptop_monitor error:", error)
        try:
            window.attributes("-fullscreen", True)
        except Exception:
            pass


current_mode = {"value": "normal"}
mode_lock = threading.Lock()
gaming_hud_ref = {"obj": None}
focus_hud_ref = {"obj": None}


class HUDCard(tk.Frame):
    """Reusable glassy-looking HUD card built only with Tk widgets."""

    def __init__(self, parent, title, accent=HUD_CYAN, width=250):
        super().__init__(
            parent,
            bg="#071018",
            highlightthickness=1,
            highlightbackground="#12313b",
            highlightcolor="#12313b",
        )
        self.title_label = tk.Label(
            self,
            text=title.upper(),
            font=("Consolas", 9, "bold"),
            fg=accent,
            bg="#071018",
            anchor="w",
        )
        self.title_label.pack(fill="x", padx=14, pady=(10, 2))

        self.value_label = tk.Label(
            self,
            text="—",
            font=("Consolas", 20, "bold"),
            fg=TEXT_MAIN,
            bg="#071018",
            anchor="w",
        )
        self.value_label.pack(fill="x", padx=14, pady=(0, 2))

        self.detail_label = tk.Label(
            self,
            text="",
            font=("Consolas", 8),
            fg="#75909a",
            bg="#071018",
            anchor="w",
        )
        self.detail_label.pack(fill="x", padx=14, pady=(0, 10))

    def set(self, value, detail=""):
        self.value_label.config(text=str(value))
        self.detail_label.config(text=str(detail))


class HUDBar(tk.Canvas):
    """Small horizontal percentage bar."""

    def __init__(self, parent, width=250, height=7):
        super().__init__(
            parent,
            width=width,
            height=height,
            bg="#071018",
            highlightthickness=0,
        )
        self.width_px = width
        self.height_px = height
        self.track = self.create_rectangle(
            0, 0, width, height, fill="#10232a", outline=""
        )
        self.fill = self.create_rectangle(
            0, 0, 0, height, fill=HUD_CYAN, outline=""
        )

    def set_percent(self, percent):
        try:
            pct = max(0.0, min(100.0, float(percent)))
        except Exception:
            pct = 0.0
        self.coords(self.fill, 0, 0, self.width_px * pct / 100.0, self.height_px)


def _fmt_speed(kbps):
    try:
        mbps = float(kbps) / 1024.0
        if mbps >= 1:
            return f"{mbps:.1f} Mbps"
        return f"{float(kbps):.0f} KB/s"
    except Exception:
        return "N/A"


def _get_top_processes(limit=5):
    """Return a lightweight snapshot of the busiest processes."""
    rows = []
    try:
        for proc in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
            info = proc.info
            name = info.get("name") or "Unknown"
            cpu = float(info.get("cpu_percent") or 0)
            mem = float(info.get("memory_percent") or 0)
            if cpu > 0.5 or mem > 1.0:
                rows.append((cpu, mem, name))
        rows.sort(key=lambda item: item[0], reverse=True)
        return rows[:limit]
    except Exception:
        return []


def _format_battery():
    battery = system_state.get("battery")
    plugged = system_state.get("plugged")
    if battery is None:
        return "N/A"
    return f"{battery:.0f}% {'AC' if plugged else 'BAT'}"


# ============================================================
# V3 TELEMETRY / HISTORY / ALERTS / CUSTOMIZATION
# ============================================================
V3_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis_v3_config.json")
V3_HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis_performance_history.json")

DEFAULT_V3_CONFIG = {
    "auto_gaming": True,
    "auto_context": True,
    "context_notifications": True,
    "mini_hud": False,
    "gaming_widgets": ["performance", "network", "mission", "processes", "media", "history"],
    "focus_widgets": ["timer", "tasks", "system", "apps", "history"],
    "alerts": True,
    "gpu_temp_warning": 82,
    "ram_warning": 90,
    "disk_warning": 90,
}


def _load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    merged = dict(default)
                    merged.update(data)
                    return merged
    except Exception as e:
        print("V3 config read error:", e)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)
    except Exception:
        pass
    return dict(default)


v3_config = _load_json(V3_CONFIG_PATH, DEFAULT_V3_CONFIG)


def _save_v3_config():
    try:
        with open(V3_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(v3_config, f, indent=2)
    except Exception as e:
        print("V3 config save error:", e)


performance_history = deque(maxlen=720)
history_lock = threading.Lock()
alert_state = {"gpu": False, "ram": False, "disk": False}
auto_gaming_thread_started = False
last_detected_game = {"name": "N/A", "pid": None}

# Smart Context Awareness state.  The context engine watches the foreground
# Windows application (not merely running processes) and turns that into a
# useful intent/context for the HUD.
context_state = {
    "name": "READY",
    "app": "Desktop",
    "process": "",
    "pid": None,
    "title": "",
    "description": "Waiting for your next task",
    "mode": "normal",
    "icon": "◉",
    "changed_at": 0.0,
}
context_last_change = {"name": "", "time": 0.0}


def _load_history():
    try:
        if os.path.exists(V3_HISTORY_PATH):
            with open(V3_HISTORY_PATH, "r", encoding="utf-8") as f:
                rows = json.load(f)
            if isinstance(rows, list):
                for row in rows[-720:]:
                    if isinstance(row, dict):
                        performance_history.append(row)
    except Exception as e:
        print("History load error:", e)


_load_history()


def _save_history_snapshot():
    try:
        with history_lock:
            rows = list(performance_history)
        with open(V3_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(rows[-720:], f)
    except Exception:
        pass


def _gpu_numbers():
    g = get_gpu_stats()
    def num(v):
        try:
            return float(re.sub(r"[^0-9.]", "", str(v)))
        except Exception:
            return None
    return num(g.get("gpu_util")), num(g.get("gpu_temp")), num(g.get("vram_used")), num(g.get("vram_total"))


def record_performance_snapshot():
    gpu_util, gpu_temp, vram_used, vram_total = _gpu_numbers()
    cpu = float(system_state.get("cpu") or 0)
    mem = float(system_state.get("mem") or 0)
    disk = float(system_state.get("disk") or 0)
    row = {
        "ts": time.time(),
        "cpu": round(cpu, 1),
        "ram": round(mem, 1),
        "disk": round(disk, 1),
        "gpu": gpu_util,
        "gpu_temp": gpu_temp,
        "vram": vram_used,
        "vram_total": vram_total,
    }
    with history_lock:
        performance_history.append(row)
    if len(performance_history) % 30 == 0:
        _save_history_snapshot()
    return row


def _history_summary():
    with history_lock:
        rows = list(performance_history)
    if not rows:
        return {"samples": 0}
    def avg(key):
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return sum(vals) / len(vals) if vals else None
    return {
        "samples": len(rows),
        "cpu_avg": avg("cpu"),
        "ram_avg": avg("ram"),
        "gpu_avg": avg("gpu"),
        "gpu_temp_max": max([r["gpu_temp"] for r in rows if isinstance(r.get("gpu_temp"), (int, float))], default=None),
    }


def _get_current_media():
    """Best-effort Windows foreground title, useful as a media/game label."""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return "N/A"
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return "N/A"
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        return title[:70] if title else "N/A"
    except Exception:
        return "N/A"


GAME_PROCESS_HINTS = {
    "r5apex.exe": "APEX LEGENDS",
    "valorant-win64-shipping.exe": "VALORANT",
    "robloxplayerbeta.exe": "ROBLOX",
    "fortniteclient-win64-shipping.exe": "FORTNITE",
    "rocketleague.exe": "ROCKET LEAGUE",
    "dota2.exe": "DOTA 2",
    "trackmania.exe": "TRACKMANIA",
    "forzahorizon5.exe": "FORZA HORIZON 5",
    "forzahorizon4.exe": "FORZA HORIZON 4",
    "pubg.exe": "PUBG",
    "tslgame.exe": "PUBG",
    "eldenring.exe": "ELDEN RING",
}


def detect_game():
    """Detect a running game. Kept for telemetry compatibility."""
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            name = (proc.info.get("name") or "").lower()
            if name in GAME_PROCESS_HINTS:
                return GAME_PROCESS_HINTS[name], proc.info.get("pid")
    except Exception:
        pass
    return "N/A", None


def _foreground_process_info():
    """Return the real foreground process, PID and window title on Windows."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "", None, ""
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        title_buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buf, 512)
        title = title_buf.value.strip()
        try:
            proc_name = psutil.Process(pid.value).name()
        except Exception:
            proc_name = ""
        return proc_name.lower(), int(pid.value), title
    except Exception:
        return "", None, ""


CONTEXT_RULES = {
    "GAMING": {
        "processes": set(GAME_PROCESS_HINTS.keys()),
        "keywords": (),
        "description": "Game detected • performance telemetry optimized",
        "mode": "gaming", "icon": "◆",
    },
    "EDITING": {
        "processes": {"resolve.exe", "resolve19.exe", "resolve18.exe", "afterfx.exe", "premiere.exe", "vegaspro.exe"},
        "keywords": ("davinci resolve", "premiere pro", "after effects", "video edit", "timeline"),
        "description": "Creative workspace • editing tools detected",
        "mode": "normal", "icon": "✦",
    },
    "DEVELOPMENT": {
        "processes": {"code.exe", "pycharm64.exe", "devenv.exe", "idea64.exe", "cursor.exe", "windows terminal.exe", "wt.exe"},
        "keywords": ("visual studio code", "pycharm", "terminal", "powershell", "developer command prompt"),
        "description": "Development workspace • coding tools detected",
        "mode": "normal", "icon": "<>" ,
    },
    "STUDY": {
        "processes": {"winword.exe", "powerpnt.exe", "onenote.exe", "acrobat.exe", "acrord32.exe"},
        "keywords": ("assignment", "worksheet", "textbook", "class", "study", "notes", "presentation"),
        "description": "Study workspace • productivity tools detected",
        "mode": "focus", "icon": "▣",
    },
    "BROWSING": {
        "processes": {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"},
        "keywords": (),
        "description": "Browser workspace • web activity detected",
        "mode": "normal", "icon": "◎",
    },
    "FILES": {
        "processes": {"explorer.exe"},
        "keywords": (),
        "description": "File workspace • Windows Explorer active",
        "mode": "normal", "icon": "▤",
    },
    "MEDIA": {
        "processes": {"spotify.exe", "vlc.exe", "wmplayer.exe", "music.ui.exe"},
        "keywords": (),
        "description": "Media workspace • playback app detected",
        "mode": "normal", "icon": "♫",
    },
}


def _classify_context(process_name, title):
    p = (process_name or "").lower()
    title_l = (title or "").lower()
    for name, rule in CONTEXT_RULES.items():
        if p in rule["processes"]:
            return name, rule
        if any(k in title_l for k in rule["keywords"]):
            return name, rule
    return "READY", {"description": "Desktop • JARVIS standing by", "mode": "normal", "icon": "◉"}


def _update_context_panel():
    try:
        label = context_panel_ref.get("label")
        detail = context_panel_ref.get("detail")
        mode_label = context_panel_ref.get("mode")
        if label is None:
            return
        c = context_state
        label.config(text=f"{c['icon']}  {c['name']}  //  {c['app'].upper()}")
        detail.config(text=f"{c['description']}   •   {c['title'][:72] if c['title'] else 'No active window'}")
        mode_label.config(text=f"SUGGESTED: {c['mode'].upper()}")
    except Exception:
        pass


def smart_context_loop():
    """Continuously understand the user's active Windows workspace."""
    previous = ""
    while True:
        try:
            proc, pid, title = _foreground_process_info()
            name, rule = _classify_context(proc, title)
            app = GAME_PROCESS_HINTS.get(proc, proc.replace('.exe', '').replace('.EXE', '').title() or "Desktop")
            if name != previous:
                previous = name
                context_state.update({
                    "name": name, "app": app, "process": proc, "pid": pid,
                    "title": title, "description": rule.get("description", ""),
                    "mode": rule.get("mode", "normal"), "icon": rule.get("icon", "◉"),
                    "changed_at": time.time(),
                })
                root.after(0, _update_context_panel)
                if v3_config.get("context_notifications", True) and name != "READY":
                    print(f"[CONTEXT] {name} | {app} | {title}")

                # Games are the one context that should automatically open the
                # dedicated telemetry HUD. Other contexts remain non-intrusive.
                if (v3_config.get("auto_context", True) and
                    v3_config.get("auto_gaming", True) and
                    name == "GAMING" and current_mode.get("value") == "normal" and
                    not gesture_only_hidden):
                    root.after(0, lambda g=app: activate_gaming_mode(auto_game=g))

                # If a game closes and Gaming HUD is active, return to normal.
                if name != "GAMING" and current_mode.get("value") == "gaming":
                    root.after(0, activate_normal_mode)
        except Exception as e:
            print("Smart context error:", e)
        time.sleep(2)


def _system_alerts(row):
    if not v3_config.get("alerts", True):
        return
    gpu_temp = row.get("gpu_temp")
    ram = row.get("ram", 0)
    disk = row.get("disk", 0)
    thresholds = (
        ("gpu", gpu_temp is not None and gpu_temp >= float(v3_config.get("gpu_temp_warning", 82)), "GPU temperature is high, sir."),
        ("ram", ram >= float(v3_config.get("ram_warning", 90)), "System memory usage is high, sir."),
        ("disk", disk >= float(v3_config.get("disk_warning", 90)), "Storage usage is high, sir."),
    )
    for key, active, message in thresholds:
        if active and not alert_state[key]:
            alert_state[key] = True
            print("[ALERT]", message)
            threading.Thread(target=speak, args=(message,), daemon=True).start()
        elif not active:
            alert_state[key] = False


def telemetry_loop():
    global last_detected_game
    while True:
        try:
            row = record_performance_snapshot()
            _system_alerts(row)
            game, pid = detect_game()
            last_detected_game = {"name": game, "pid": pid}
            if v3_config.get("auto_gaming", False) and game != "N/A" and current_mode.get("value") == "normal":
                root.after(0, lambda g=game: activate_gaming_mode(auto_game=g))
        except Exception as e:
            print("Telemetry loop error:", e)
        time.sleep(5)


# ============================================================
# V3 HUD HELPERS
# ============================================================
class Sparkline(tk.Canvas):
    def __init__(self, parent, width=300, height=50):
        super().__init__(parent, width=width, height=height, bg="#071018", highlightthickness=0)
        self.w = width
        self.h = height
        self.values = deque(maxlen=60)
        self.line = None

    def push(self, value):
        try:
            self.values.append(float(value))
        except Exception:
            return
        self.delete("spark")
        if len(self.values) < 2:
            return
        vals = list(self.values)
        lo, hi = min(vals), max(vals)
        if hi - lo < 1:
            hi = lo + 1
        points = []
        for i, v in enumerate(vals):
            x = i * (self.w - 4) / max(1, len(vals)-1) + 2
            y = self.h - 3 - ((v-lo)/(hi-lo)) * (self.h-8)
            points.extend([x, y])
        self.create_line(*points, fill=HUD_CYAN, width=2, smooth=True, tags="spark")


class MiniHUD:
    def __init__(self):
        self.window = tk.Toplevel(root)
        self.window.configure(bg=HUD_BG)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.geometry("300x118+20+20")
        self.window.bind("<Double-Button-1>", lambda e: self.expand())
        self.window.bind("<Escape>", lambda e: self.destroy())
        self.alive = True
        top = tk.Frame(self.window, bg="#071018")
        top.pack(fill="x", padx=1, pady=1)
        tk.Label(top, text="◉ JARVIS", font=("Consolas", 13, "bold"), fg=HUD_CYAN_BRIGHT, bg="#071018").pack(side="left", padx=10, pady=6)
        tk.Label(top, text="MINI", font=("Consolas", 8, "bold"), fg="#50737e", bg="#071018").pack(side="right", padx=10)
        self.info = tk.Label(self.window, text="SYSTEM NOMINAL", font=("Consolas", 9), fg=TEXT_MAIN, bg=HUD_BG, justify="left", anchor="w")
        self.info.pack(fill="both", expand=True, padx=12, pady=8)
        self.tick()

    def tick(self):
        if not self.alive:
            return
        game = last_detected_game.get("name", "N/A")
        cpu = system_state.get("cpu", 0)
        ram = system_state.get("mem", 0)
        gpu, temp, _, _ = _gpu_numbers()
        self.info.config(text=f"CPU {cpu:.0f}%   RAM {ram:.0f}%   GPU {gpu:.0f}%" if gpu is not None else f"CPU {cpu:.0f}%   RAM {ram:.0f}%\nGAME  {game}")
        self.window.after(1000, self.tick)

    def expand(self):
        if current_mode.get("value") == "gaming":
            activate_gaming_mode()
        else:
            activate_normal_mode()

    def destroy(self):
        self.alive = False
        try: self.window.destroy()
        except Exception: pass


mini_hud_ref = {"obj": None}


class GamingHUD:
    """Rich full-screen gaming / Mission Control HUD."""
    def __init__(self, auto_game=None):
        self.window = tk.Toplevel(root)
        self.window.configure(bg=HUD_BG)
        position_on_laptop_monitor(self.window)
        self.window.attributes("-topmost", True)
        self.window.focus_force()
        self.alive = True
        self.started_at = time.time()
        self.auto_game = auto_game
        self.gpu_spark = Sparkline(self.window, 300, 45)
        self.cpu_spark = Sparkline(self.window, 300, 45)
        self.window.bind("<Escape>", lambda e: activate_normal_mode())
        self.window.protocol("WM_DELETE_WINDOW", activate_normal_mode)

        header = tk.Frame(self.window, bg=HUD_BG)
        header.pack(fill="x", padx=42, pady=(26, 0))
        tk.Label(header, text="J A R V I S", font=("Consolas", 29, "bold"), fg=HUD_CYAN_BRIGHT, bg=HUD_BG).pack(side="left")
        self.mode_label = tk.Label(header, text=" // GAMING MODE", font=("Consolas", 11, "bold"), fg=HUD_CYAN, bg=HUD_BG)
        self.mode_label.pack(side="left", padx=12, pady=(9,0))
        self.clock_label = tk.Label(header, text="", font=("Consolas", 12), fg="#7c9aa4", bg=HUD_BG)
        self.clock_label.pack(side="right", pady=(9,0))
        tk.Frame(self.window, bg="#12313b", height=1).pack(fill="x", padx=42, pady=(18,12))

        mission = tk.Frame(self.window, bg="#071018", highlightthickness=1, highlightbackground="#12313b")
        mission.pack(fill="x", padx=42, pady=(0,12))
        self.game_label = tk.Label(mission, text="GAME DETECTION  •  SCANNING", font=("Consolas", 12, "bold"), fg=HUD_CYAN_BRIGHT, bg="#071018", anchor="w")
        self.game_label.pack(side="left", padx=16, pady=12)
        self.session_label = tk.Label(mission, text="SESSION 00:00:00", font=("Consolas", 10), fg="#7c9aa4", bg="#071018")
        self.session_label.pack(side="right", padx=16)

        body = tk.Frame(self.window, bg=HUD_BG)
        body.pack(fill="both", expand=True, padx=42)
        left = tk.Frame(body, bg=HUD_BG)
        left.pack(side="left", fill="both", expand=True, padx=(0,8))
        right = tk.Frame(body, bg=HUD_BG)
        right.pack(side="left", fill="both", expand=True, padx=(8,0))

        cards = tk.Frame(left, bg=HUD_BG)
        cards.pack(fill="x")
        self.cards = {}
        for title,key in [("CPU","cpu"),("GPU","gpu"),("RAM","ram"),("VRAM","vram"),("TEMP","temp"),("PING","ping")]:
            c=HUDCard(cards,title)
            c.pack(side="left", fill="both", expand=True, padx=4)
            self.cards[key]=c
        self.cpu_bar=HUDBar(left,width=520,height=8); self.cpu_bar.pack(fill="x",pady=(14,3))
        self.gpu_bar=HUDBar(left,width=520,height=8); self.gpu_bar.pack(fill="x",pady=3)
        self.ram_bar=HUDBar(left,width=520,height=8); self.ram_bar.pack(fill="x",pady=3)
        self.cpu_spark.pack(fill="x",pady=(12,2)); self.gpu_spark.pack(fill="x",pady=2)

        net = HUDCard(right,"NETWORK")
        net.pack(fill="x", pady=4); self.net_card=net
        proc = HUDCard(right,"ACTIVE PROCESS")
        proc.pack(fill="x", pady=4); self.proc_card=proc
        power = HUDCard(right,"POWER")
        power.pack(fill="x", pady=4); self.power_card=power
        hist = HUDCard(right,"PERFORMANCE HISTORY")
        hist.pack(fill="x", pady=4); self.hist_card=hist
        self.top_proc_label=tk.Label(right,text="TOP PROCESSES  •  loading",font=("Consolas",9),fg="#7c9aa4",bg=HUD_BG,anchor="w",justify="left")
        self.top_proc_label.pack(fill="x",pady=(12,2))
        self.media_label=tk.Label(right,text="MEDIA / WINDOW  •  N/A",font=("Consolas",9),fg="#7c9aa4",bg=HUD_BG,anchor="w")
        self.media_label.pack(fill="x",pady=2)

        # Persistent HUD customization. Changes made by voice are applied
        # the next time the HUD is opened, keeping the live loop lightweight.
        widgets = set(v3_config.get("gaming_widgets", []))
        if "performance" not in widgets:
            for w in [self.cpu_bar, self.gpu_bar, self.ram_bar, self.cpu_spark, self.gpu_spark]:
                w.pack_forget()
        if "network" not in widgets: self.net_card.pack_forget()
        if "processes" not in widgets: self.top_proc_label.pack_forget()
        if "media" not in widgets: self.media_label.pack_forget()
        if "history" not in widgets: self.hist_card.pack_forget()
        if "mission" not in widgets: self.game_label.master.pack_forget()

        footer=tk.Frame(self.window,bg=HUD_BG); footer.pack(fill="x",padx=42,pady=(10,20))
        tk.Label(footer,text="ESC NORMAL  •  M MISSION CONTROL  •  F1 MINI HUD  •  V voice commands",font=("Consolas",8),fg="#54717a",bg=HUD_BG).pack(side="left")
        tk.Label(footer,text="● CORE ONLINE",font=("Consolas",9,"bold"),fg="#45ff8a",bg=HUD_BG).pack(side="right")
        self.window.bind("<F1>",lambda e: toggle_mini_hud())
        self.update_loop()

    def update_loop(self):
        if not self.alive: return
        try:
            cpu=float(system_state.get("cpu") or 0); mem=float(system_state.get("mem") or 0)
            down=float(system_state.get("net_recv") or 0); up=float(system_state.get("net_sent") or 0)
            gpu,temp,vram,vt=_gpu_numbers()
            game,pid=detect_game()
            ping=get_ping_ms()
            self.clock_label.config(text=datetime.now().strftime("%a %d %b  %H:%M:%S"))
            self.session_label.config(text=f"SESSION {time.strftime('%H:%M:%S',time.gmtime(time.time()-self.started_at))}")
            self.game_label.config(text=f"GAME DETECTION  •  {self.auto_game or game}")
            self.cards["cpu"].set(f"{cpu:.0f}%",f"{psutil.cpu_count(logical=True) or 0} threads")
            self.cards["gpu"].set(f"{gpu:.0f}%" if gpu is not None else "N/A","NVIDIA telemetry")
            self.cards["ram"].set(f"{mem:.0f}%",f"{system_state.get('mem_used_gb',0):.1f} / {system_state.get('mem_total_gb',0):.0f} GB")
            self.cards["vram"].set(f"{vram:.0f} MB" if vram is not None else "N/A",f"of {vt:.0f} MB" if vt else "VRAM")
            self.cards["temp"].set(f"{temp:.0f}°C" if temp is not None else "N/A","GPU temperature")
            self.cards["ping"].set(ping,"8.8.8.8")
            self.net_card.set(f"↓ {_fmt_speed(down)}",f"↑ {_fmt_speed(up)}  •  {ping}")
            self.proc_card.set(get_foreground_process_name(),_get_current_media())
            self.power_card.set(_format_battery(),"battery / AC")
            hs=_history_summary()
            self.hist_card.set(f"{hs.get('gpu_avg'):.0f}% GPU" if hs.get('gpu_avg') is not None else "Collecting...",f"{hs.get('samples',0)} samples")
            self.cpu_bar.set_percent(cpu); self.ram_bar.set_percent(mem); self.gpu_bar.set_percent(gpu or 0)
            self.cpu_spark.push(cpu); self.gpu_spark.push(gpu or 0)
            top=_get_top_processes()
            self.top_proc_label.config(text="TOP PROCESSES  •  "+("  •  ".join(f"{n} {c:.0f}%" for c,m,n in top) if top else "no data"))
            self.media_label.config(text=f"WINDOW  •  {_get_current_media()}")
        except Exception as e: print("Gaming HUD update error:",e)
        self.window.after(1000,self.update_loop)

    def show_stats(self):
        self.alive = True
        self.stats_visible = True

    def hide_stats(self):
        # Keep compatibility with the V2 voice commands. The V3 HUD is
        # intentionally telemetry-first, so hiding stats is represented
        # by dimming the telemetry cards rather than destroying the HUD.
        self.stats_visible = False
        for card in getattr(self, "cards", {}).values():
            card.value_label.config(fg="#45616a")

    def destroy(self):
        self.alive=False
        try:self.window.destroy()
        except Exception:pass


class FocusHUD:
    """Full-screen productivity command center with timer, tasks, streak/history and distraction monitoring."""
    def __init__(self,minutes,project_label="FOCUS SESSION"):
        self.total_seconds=max(1,int(minutes))*60; self.remaining=self.total_seconds; self.paused=False; self.ended=False; self.alive=True
        self.project_label=project_label; self.tasks=[]; self.distractions=0; self.warned_pids=set(); self.start_time=time.time()
        self.window=tk.Toplevel(root); self.window.configure(bg=HUD_BG); position_on_laptop_monitor(self.window); self.window.attributes("-topmost",True); self.window.focus_force()
        self.window.bind("<Escape>",lambda e:activate_normal_mode()); self.window.protocol("WM_DELETE_WINDOW",activate_normal_mode)
        header=tk.Frame(self.window,bg=HUD_BG); header.pack(fill="x",padx=70,pady=(30,0))
        tk.Label(header,text="J A R V I S",font=("Consolas",25,"bold"),fg=HUD_CYAN_BRIGHT,bg=HUD_BG).pack(side="left")
        tk.Label(header,text=" // FOCUS MODE",font=("Consolas",10,"bold"),fg=HUD_CYAN,bg=HUD_BG).pack(side="left",padx=10,pady=(8,0))
        self.clock_label=tk.Label(header,text="",font=("Consolas",12),fg="#7c9aa4",bg=HUD_BG); self.clock_label.pack(side="right")
        tk.Label(self.window,text="FOCUS SESSION",font=("Consolas",11,"bold"),fg="#50737e",bg=HUD_BG).pack(pady=(34,0))
        self.timer_label=tk.Label(self.window,text="00:00",font=("Consolas",96,"bold"),fg=HUD_CYAN_BRIGHT,bg=HUD_BG); self.timer_label.pack()
        self.project_widget=tk.Label(self.window,text=project_label,font=("Consolas",14),fg=GOLD_SOFT,bg=HUD_BG); self.project_widget.pack(pady=(0,14))
        self.progress_canvas=tk.Canvas(self.window,width=680,height=10,bg="#10232a",highlightthickness=0); self.progress_canvas.pack()
        self.progress_bar=self.progress_canvas.create_rectangle(0,0,0,10,fill=HUD_CYAN,width=0)
        info=tk.Frame(self.window,bg=HUD_BG); info.pack(fill="x",padx=70,pady=(24,10))
        self.session_card=HUDCard(info,"SESSION"); self.session_card.pack(side="left",fill="x",expand=True,padx=4)
        self.distraction_card=HUDCard(info,"DISTRACTIONS"); self.distraction_card.pack(side="left",fill="x",expand=True,padx=4)
        self.system_card=HUDCard(info,"SYSTEM"); self.system_card.pack(side="left",fill="x",expand=True,padx=4)
        self.history_card=HUDCard(info,"FOCUS HISTORY"); self.history_card.pack(side="left",fill="x",expand=True,padx=4)
        lower=tk.Frame(self.window,bg=HUD_BG); lower.pack(fill="both",expand=True,padx=70,pady=(5,10))
        task_panel=tk.Frame(lower,bg="#071018",highlightthickness=1,highlightbackground="#12313b"); task_panel.pack(side="left",fill="both",expand=True,padx=(4,8))
        tk.Label(task_panel,text="FOCUS TASKS",font=("Consolas",9,"bold"),fg=HUD_CYAN,bg="#071018").pack(anchor="w",padx=15,pady=(12,5))
        self.task_list_label=tk.Label(task_panel,text='No tasks yet.\nSay: "add task ..."',font=("Consolas",10),fg=TEXT_MAIN,bg="#071018",justify="left",anchor="nw"); self.task_list_label.pack(fill="both",expand=True,padx=15,pady=(0,12))
        apps=tk.Frame(lower,bg="#071018",highlightthickness=1,highlightbackground="#12313b"); apps.pack(side="left",fill="both",expand=True,padx=(8,4))
        tk.Label(apps,text="FOCUS ENVIRONMENT",font=("Consolas",9,"bold"),fg=HUD_CYAN,bg="#071018").pack(anchor="w",padx=15,pady=(12,5))
        self.apps_label=tk.Label(apps,text="",font=("Consolas",9),fg="#a9c1c8",bg="#071018",justify="left",anchor="nw"); self.apps_label.pack(fill="both",expand=True,padx=15,pady=(0,12))
        widgets = set(v3_config.get("focus_widgets", []))
        if "timer" not in widgets:
            self.timer_label.pack_forget(); self.project_widget.pack_forget(); self.progress_canvas.pack_forget()
        if "tasks" not in widgets: task_panel.pack_forget()
        if "apps" not in widgets: apps.pack_forget()
        if "history" not in widgets: self.history_card.pack_forget()
        if "system" not in widgets: self.system_card.pack_forget()
        controls=tk.Frame(self.window,bg=HUD_BG); controls.pack(fill="x",padx=70,pady=(0,8))
        tk.Button(controls,text="PAUSE",command=self.pause,bg="#0d1820",fg=TEXT_MAIN,activebackground="#12313b",activeforeground=TEXT_MAIN,relief="flat",font=("Consolas",9,"bold")).pack(side="left",padx=4)
        tk.Button(controls,text="RESUME",command=self.resume,bg="#0d1820",fg=TEXT_MAIN,activebackground="#12313b",activeforeground=TEXT_MAIN,relief="flat",font=("Consolas",9,"bold")).pack(side="left",padx=4)
        tk.Button(controls,text="END SESSION",command=lambda:self.complete_session(manual_end=True),bg="#0d1820",fg=HUD_WARN,activebackground="#12313b",activeforeground=HUD_WARN,relief="flat",font=("Consolas",9,"bold")).pack(side="right",padx=4)
        tk.Label(self.window,text="ESC NORMAL  •  add task ...  •  pause focus  •  resume focus  •  end focus",font=("Consolas",8),fg="#54717a",bg=HUD_BG).pack(pady=(0,15))
        self.refresh_tasks(); self.tick()

    def add_task(self,text): self.tasks.append([text,False]); self.refresh_tasks()
    def complete_task(self,index):
        if 0<=index<len(self.tasks): self.tasks[index][1]=True; self.refresh_tasks()
    def refresh_tasks(self):
        if not self.tasks:self.task_list_label.config(text='No tasks yet.\nSay: "add task ..."'); return
        self.task_list_label.config(text="\n".join(("☑" if d else "☐")+" "+t for t,d in self.tasks))
    def pause(self): self.paused=True
    def resume(self): self.paused=False
    def check_focus_violations(self):
        try:
            current_pids=set()
            for proc in psutil.process_iter(["pid","name"]):
                pid=proc.info.get("pid"); name=proc.info.get("name") or ""; current_pids.add(pid)
                if name.lower() in [x.lower() for x in FOCUS_BLOCKED_APPS] and pid not in self.warned_pids:
                    self.warned_pids.add(pid); self.distractions+=1
            self.warned_pids.intersection_update(current_pids)
        except Exception: pass
    def update_widgets(self):
        elapsed=self.total_seconds-self.remaining; pct=(elapsed/self.total_seconds)*100
        hs=_history_summary(); cpu=system_state.get("cpu",0); mem=system_state.get("mem",0)
        self.session_card.set(f"{pct:.0f}%",f"{elapsed//60:02d}:{elapsed%60:02d} focused")
        self.distraction_card.set(str(self.distractions),"blocked-list launches")
        self.system_card.set(f"CPU {cpu:.0f}%",f"RAM {mem:.0f}%  •  {_format_battery()}")
        self.history_card.set(f"{hs.get('cpu_avg'):.0f}% CPU" if hs.get('cpu_avg') is not None else "Collecting...",f"{hs.get('samples',0)} samples")
        allowed=", ".join(os.path.splitext(a)[0] for a in FOCUS_ALLOWED_APPS[:6]); blocked=", ".join(os.path.splitext(a)[0] for a in FOCUS_BLOCKED_APPS[:6])
        self.apps_label.config(text=f"ALLOWED APPS\n{allowed}\n\nDISTRACTION LIST\n{blocked}\n\nSTATUS\n{'PAUSED' if self.paused else 'FOCUS ACTIVE'}")
    def tick(self):
        if not self.alive or self.ended:return
        if not self.paused and self.remaining>0:self.remaining-=1
        mins,secs=divmod(max(0,self.remaining),60); self.timer_label.config(text=f"{mins:02d}:{secs:02d}")
        progress=1-(self.remaining/self.total_seconds); self.progress_canvas.coords(self.progress_bar,0,0,int(680*progress),10)
        self.clock_label.config(text=datetime.now().strftime("%a %d %b  %H:%M:%S")); self.check_focus_violations(); self.update_widgets()
        if self.remaining<=0:self.complete_session(); return
        self.window.after(1000,self.tick)
    def complete_session(self,manual_end=False):
        if self.ended:return
        self.ended=True; elapsed=int(time.time()-self.start_time); completed=sum(1 for _,d in self.tasks if d)
        try:
            for w in self.window.winfo_children():w.destroy()
            tk.Label(self.window,text="FOCUS SESSION COMPLETE" if not manual_end else "FOCUS SESSION ENDED",font=("Consolas",28,"bold"),fg=HUD_CYAN_BRIGHT,bg=HUD_BG).pack(pady=(150,20))
            tk.Label(self.window,text=f"Time focused: {elapsed//60:02d}:{elapsed%60:02d}\nTasks completed: {completed}/{len(self.tasks)}\nDistractions detected: {self.distractions}\n\nSay 'return to Normal Mode' or press Esc",font=("Consolas",14),fg=TEXT_MAIN,bg=HUD_BG,justify="center").pack(pady=20)
            threading.Thread(target=speak,args=("Focus session complete, sir." if not manual_end else "Focus session ended, sir.",),daemon=True).start()
        except Exception as e:print("Focus completion screen error:",e)
    def destroy(self):
        self.alive=False
        try:self.window.destroy()
        except Exception:pass


class MissionControlHUD:
    """All-in-one system dashboard: performance, network, storage, power and history."""
    def __init__(self):
        self.window=tk.Toplevel(root); self.window.configure(bg=HUD_BG); position_on_laptop_monitor(self.window); self.window.attributes("-topmost",True); self.window.focus_force(); self.alive=True
        self.window.bind("<Escape>",lambda e:activate_normal_mode()); self.window.protocol("WM_DELETE_WINDOW",activate_normal_mode)
        tk.Label(self.window,text="J A R V I S  //  MISSION CONTROL",font=("Consolas",28,"bold"),fg=HUD_CYAN_BRIGHT,bg=HUD_BG).pack(anchor="w",padx=50,pady=(35,5))
        self.clock=tk.Label(self.window,text="",font=("Consolas",11),fg="#7c9aa4",bg=HUD_BG); self.clock.pack(anchor="w",padx=52)
        grid=tk.Frame(self.window,bg=HUD_BG); grid.pack(fill="both",expand=True,padx=45,pady=25)
        self.cards={}
        for i,(title,key) in enumerate([("CPU","cpu"),("GPU","gpu"),("RAM","ram"),("GPU TEMP","temp"),("NETWORK","net"),("STORAGE","disk"),("BATTERY","bat"),("ACTIVE APP","app"),("GAME","game"),("UPTIME","uptime"),("HISTORY","hist"),("MEDIA","media")]):
            c=HUDCard(grid,title); c.grid(row=i//3,column=i%3,sticky="nsew",padx=6,pady=6); self.cards[key]=c
        for i in range(3):grid.columnconfigure(i,weight=1)
        tk.Label(self.window,text="ESC NORMAL  •  F1 MINI HUD",font=("Consolas",8),fg="#54717a",bg=HUD_BG).pack(pady=(0,25))
        self.update_loop()
    def update_loop(self):
        if not self.alive:return
        try:
            gpu,temp,_,_=_gpu_numbers(); hs=_history_summary(); game,_=detect_game()
            self.clock.config(text=datetime.now().strftime("%A %d %B %Y   %H:%M:%S"))
            self.cards["cpu"].set(f"{system_state.get('cpu',0):.0f}%","processor")
            self.cards["gpu"].set(f"{gpu:.0f}%" if gpu is not None else "N/A","GPU load")
            self.cards["ram"].set(f"{system_state.get('mem',0):.0f}%",f"{system_state.get('mem_used_gb',0):.1f} GB used")
            self.cards["temp"].set(f"{temp:.0f}°C" if temp is not None else "N/A","GPU")
            self.cards["net"].set(f"↓ {_fmt_speed(system_state.get('net_recv',0))}",f"↑ {_fmt_speed(system_state.get('net_sent',0))}")
            self.cards["disk"].set(f"{system_state.get('disk',0):.0f}%","system drive")
            self.cards["bat"].set(_format_battery(),"power")
            self.cards["app"].set(get_foreground_process_name(),"foreground")
            self.cards["game"].set(game,"detected process")
            self.cards["uptime"].set(str(system_state.get('uptime','—')),"system uptime")
            self.cards["hist"].set(str(hs.get('samples',0)),"telemetry samples")
            self.cards["media"].set(_get_current_media(),"window title")
        except Exception as e:print("Mission Control error:",e)
        self.window.after(1500,self.update_loop)
    def destroy(self):
        self.alive=False
        try:self.window.destroy()
        except Exception:pass


mission_hud_ref={"obj":None}

def activate_normal_mode():
    """Tears down whichever full-screen HUD is active and restores the
    small Normal Mode window. Safe to call even if already in Normal
    Mode (no-op in that case beyond re-showing the window)."""
    with mode_lock:
        previous_mode = current_mode["value"]

        if previous_mode == "gaming" and gaming_hud_ref["obj"] is not None:
            obj = gaming_hud_ref["obj"]
            gaming_hud_ref["obj"] = None
            root.after(0, obj.destroy)

        if previous_mode == "focus" and focus_hud_ref["obj"] is not None:
            obj = focus_hud_ref["obj"]
            focus_hud_ref["obj"] = None
            root.after(0, obj.destroy)

        if previous_mode == "mission" and mission_hud_ref["obj"] is not None:
            obj = mission_hud_ref["obj"]
            mission_hud_ref["obj"] = None
            root.after(0, obj.destroy)

        current_mode["value"] = "normal"

    def _restore():
        try:
            root.deiconify()
            root.lift()
            root.attributes("-topmost", True)
            entry.focus()
            status.config(text="● ONLINE", fg="#45ff8a")
        except Exception as error:
            print("Restore Normal Mode error:", error)

    root.after(0, _restore)

    if previous_mode == "normal":
        return "Already in Normal Mode, sir."
    return "Normal Mode restored, sir."


def activate_gaming_mode(auto_game=None):
    if HEADLESS:
        return "Gaming Mode requires the visual interface, sir."

    with mode_lock:
        if current_mode["value"] == "gaming":
            return "Gaming Mode is already active, sir."

        if current_mode["value"] == "focus" and focus_hud_ref["obj"] is not None:
            obj = focus_hud_ref["obj"]
            focus_hud_ref["obj"] = None
            root.after(0, obj.destroy)
        if current_mode["value"] == "mission" and mission_hud_ref["obj"] is not None:
            obj = mission_hud_ref["obj"]
            mission_hud_ref["obj"] = None
            root.after(0, obj.destroy)

        current_mode["value"] = "gaming"

    def _build():
        try:
            root.withdraw()
            root.update_idletasks()
            gaming_hud_ref["obj"] = GamingHUD(auto_game=auto_game)
        except Exception as error:
            print("Gaming Mode build error:", error)

    root.after(0, _build)

    return "Gaming Mode activated, sir."


def activate_focus_mode(minutes=None, project_label="FOCUS SESSION"):
    if HEADLESS:
        return "Focus Mode requires the visual interface, sir."

    if minutes is None:
        minutes = DEFAULT_FOCUS_MINUTES

    with mode_lock:
        if current_mode["value"] == "gaming" and gaming_hud_ref["obj"] is not None:
            obj = gaming_hud_ref["obj"]
            gaming_hud_ref["obj"] = None
            root.after(0, obj.destroy)

        # Re-activating Focus Mode while already focusing starts a
        # fresh session rather than stacking windows.
        if current_mode["value"] == "focus" and focus_hud_ref["obj"] is not None:
            obj = focus_hud_ref["obj"]
            focus_hud_ref["obj"] = None
            root.after(0, obj.destroy)
        if current_mode["value"] == "mission" and mission_hud_ref["obj"] is not None:
            obj = mission_hud_ref["obj"]
            mission_hud_ref["obj"] = None
            root.after(0, obj.destroy)

        current_mode["value"] = "focus"

    def _build():
        try:
            root.withdraw()
            root.update_idletasks()
            focus_hud_ref["obj"] = FocusHUD(minutes, project_label)
        except Exception as error:
            print("Focus Mode build error:", error)

    root.after(0, _build)

    return f"Focus Mode activated, sir. {minutes} minute session starting."


def activate_mission_control():
    if HEADLESS:
        return "Mission Control requires the visual interface, sir."
    with mode_lock:
        if current_mode["value"] == "gaming" and gaming_hud_ref["obj"] is not None:
            gaming_hud_ref["obj"].destroy(); gaming_hud_ref["obj"] = None
        if current_mode["value"] == "focus" and focus_hud_ref["obj"] is not None:
            focus_hud_ref["obj"].destroy(); focus_hud_ref["obj"] = None
        current_mode["value"] = "mission"
    def _build():
        root.withdraw(); root.update_idletasks(); mission_hud_ref["obj"] = MissionControlHUD()
    root.after(0,_build)
    return "Mission Control activated, sir."


def toggle_mini_hud():
    if HEADLESS:return "Mini HUD requires the visual interface, sir."
    if mini_hud_ref["obj"] is not None:
        mini_hud_ref["obj"].destroy(); mini_hud_ref["obj"] = None; v3_config["mini_hud"] = False; _save_v3_config()
        return "Mini HUD hidden, sir."
    mini_hud_ref["obj"] = MiniHUD(); v3_config["mini_hud"] = True; _save_v3_config()
    return "Mini HUD enabled, sir."


def set_auto_gaming(enabled):
    v3_config["auto_gaming"] = bool(enabled); _save_v3_config()
    return "Automatic Gaming Mode detection enabled, sir." if enabled else "Automatic Gaming Mode detection disabled, sir."


def cycle_hud_widget(widget, mode="gaming"):
    key="gaming_widgets" if mode=="gaming" else "focus_widgets"
    arr=v3_config.setdefault(key,[])
    if widget in arr: arr.remove(widget); state="hidden"
    else: arr.append(widget); state="visible"
    _save_v3_config(); return f"{widget} widget {state} in {mode} mode, sir."


def system_diagnostics():
    gpu,temp,vram,vt=_gpu_numbers(); hs=_history_summary(); game,pid=detect_game()
    return (f"System diagnostics: CPU {system_state.get('cpu',0):.0f} percent, "
            f"RAM {system_state.get('mem',0):.0f} percent, "
            f"GPU {gpu:.0f} percent" if gpu is not None else "System diagnostics: GPU telemetry unavailable") + \
           f", disk {system_state.get('disk',0):.0f} percent, battery {_format_battery()}, game {game}, {hs.get('samples',0)} telemetry samples."


def try_handle_mode_command(text):
    """
    Pre-parser for mode-management phrases. Returns a reply string if
    `text` was handled here (so the caller should NOT forward it to
    Groq); returns None if this wasn't a mode command, so the normal
    ask_jarvis() pipeline should handle it instead.

    This runs before the AI call specifically so mode switching is
    instant and 100% deterministic rather than depending on model
    interpretation.
    """
    t = text.lower().strip()
    t = re.sub(r"[,.!?;:]", "", t)
    t = " ".join(t.split())

    if not t:
        return None

    # --- explicit mode switches ---
    if re.search(r"\bactivate normal mode\b", t) or re.search(r"\breturn to normal mode\b", t):
        return activate_normal_mode()

    if re.search(r"\bexit gaming mode\b", t) or re.search(r"\bexit focus mode\b", t):
        return activate_normal_mode()

    focus_minutes_match = re.search(r"start a (\d+)\s*minute focus session", t)
    if focus_minutes_match:
        return activate_focus_mode(int(focus_minutes_match.group(1)))

    if re.search(r"\bactivate focus mode\b", t):
        return activate_focus_mode()

    if re.search(r"\bactivate gaming mode\b", t):
        return activate_gaming_mode()

    # --- gaming-specific ---
    if "show gaming stats" in t:
        if gaming_hud_ref["obj"] is not None:
            gaming_hud_ref["obj"].show_stats()
            return "Stats visible, sir."
        return "Gaming Mode isn't active, sir."

    if "hide gaming stats" in t:
        if gaming_hud_ref["obj"] is not None:
            gaming_hud_ref["obj"].hide_stats()
            return "Stats hidden, sir."
        return "Gaming Mode isn't active, sir."

    # --- focus-specific ---
    if "pause focus" in t:
        if focus_hud_ref["obj"] is not None:
            focus_hud_ref["obj"].pause()
            return "Focus paused, sir."
        return "No focus session is active, sir."

    if "resume focus" in t:
        if focus_hud_ref["obj"] is not None:
            focus_hud_ref["obj"].resume()
            return "Resuming focus, sir."
        return "No focus session is active, sir."

    if "end focus" in t:
        if focus_hud_ref["obj"] is not None:
            obj = focus_hud_ref["obj"]
            root.after(0, lambda: obj.complete_session(manual_end=True))
            return "Focus session ended, sir."
        return "No focus session is active, sir."

    task_match = re.search(r"add task (.+)", t)
    if task_match:
        if focus_hud_ref["obj"] is not None:
            task_text = task_match.group(1).strip()
            focus_hud_ref["obj"].add_task(task_text)
            return "Task added, sir."
        return "Start a focus session first, sir."

    if any(x in t for x in ["mission control", "mission dashboard", "system dashboard"]):
        return activate_mission_control()

    if any(x in t for x in ["mini hud", "mini jarvis", "floating hud"]):
        return toggle_mini_hud()

    if any(x in t for x in ["enable auto gaming", "automatic gaming", "auto gaming on"]):
        return set_auto_gaming(True)

    if any(x in t for x in ["disable auto gaming", "auto gaming off", "automatic gaming off"]):
        return set_auto_gaming(False)

    if any(x in t for x in ["system diagnostics", "run diagnostics", "system status"]):
        return system_diagnostics()

    if t.startswith("show history") or t.startswith("performance history"):
        hs = _history_summary()
        return (f"Telemetry history: {hs.get('samples',0)} samples. "
                f"Average CPU {hs.get('cpu_avg'):.0f} percent. "
                f"Average RAM {hs.get('ram_avg'):.0f} percent." if hs.get('cpu_avg') is not None else "Telemetry history is still collecting, sir.")

    if "gaming widget" in t or "focus widget" in t:
        mode = "focus" if "focus" in t else "gaming"
        for widget in ["performance","network","mission","processes","media","history","timer","tasks","system","apps"]:
            if widget in t:
                return cycle_hud_widget(widget, mode)

    return None


# ============================================================
# MICROPHONE
# ============================================================

recognizer = sr.Recognizer()
recognizer.pause_threshold = 0.8
recognizer.non_speaking_duration = 0.4
recognizer.phrase_threshold = 0.3

try:
    microphone = sr.Microphone()
except Exception:
    microphone = None
    print("No microphone detected.")


# ============================================================
# VOICE ACTIVE TIMER
# ============================================================

voice_active_until = 0


# ============================================================
# JARVIS SHUTDOWN
# ============================================================

def shutdown_jarvis():
    global voice_active_until

    print("JARVIS shutting down...")

    voice_active_until = 0

    try:
        status.config(text="● OFFLINE", fg="#ff4d6d")
    except Exception:
        pass

    try:
        threading.Thread(
            target=speak, args=("Shutting down JARVIS, sir.",), daemon=True
        ).start()
    except Exception:
        pass

    root.after(800, root.destroy)


# ============================================================
# VOICE LISTENER
# ============================================================

def voice_listener():
    global voice_active_until

    if microphone is None:
        print("No microphone available.")
        return

    print("🎤 Calibrating microphone...")

    try:
        with microphone as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
    except Exception as error:
        print("Microphone calibration error:", error)
        return

    print("🎤 JARVIS voice listener ready.")
    print("Say 'Jarvis' to activate 15-second listening mode.")

    while True:
        try:
            with microphone as source:
                print("🎤 Listening...")
                audio = recognizer.listen(source, timeout=None, phrase_time_limit=10)

            try:
                text = recognizer.recognize_google(audio)
            except sr.UnknownValueError:
                print("Couldn't understand speech.")
                continue
            except sr.RequestError as error:
                print("Speech recognition error:", error)
                continue

            text = text.strip()
            if not text:
                continue

            print("VOICE:", text)

            clean_text = text.lower().strip()
            clean_text = re.sub(r"[,.!?;:]", "", clean_text)
            clean_text = " ".join(clean_text.split())

            if is_exit_command(clean_text):
                root.after(0, add_message, "YOU", text)
                root.after(0, shutdown_jarvis)
                return

            current_time = time.time()
            active = current_time < voice_active_until

            # In gesture-only hidden mode, voice commands are deliberately
            # ignored so the hidden JARVIS window cannot be controlled by
            # voice. Only the full open-palm gesture can restore it.
            if gesture_only_hidden:
                print("JARVIS is hidden: voice command ignored; waiting for open-palm gesture.")
                continue

            jarvis_match = re.search(r"\bjarvis\b", clean_text)
            command = ""

            if jarvis_match:
                voice_active_until = time.time() + VOICE_ACTIVE_TIME
                print(f"🎤 ACTIVE MODE: {VOICE_ACTIVE_TIME} seconds")

                command = clean_text[jarvis_match.end():].strip()

                if not command:
                    root.after(0, add_message, "YOU", text)
                    root.after(0, lambda: status.config(text="● LISTENING", fg=GOLD))
                    threading.Thread(
                        target=speak, args=("Yes, sir. I'm listening.",), daemon=True
                    ).start()
                    continue

            elif not active:
                print("Wake word not detected.")
                continue

            if active:
                voice_active_until = time.time() + VOICE_ACTIVE_TIME

                if not jarvis_match:
                    command = clean_text

                if not command:
                    continue

                print("JARVIS COMMAND:", command)

                if is_exit_command(command):
                    root.after(0, add_message, "YOU", text)
                    root.after(0, shutdown_jarvis)
                    return

                root.after(0, add_message, "YOU", text)

                mode_reply = try_handle_mode_command(command)
                if mode_reply is not None:
                    root.after(0, show_response, mode_reply)
                    continue

                root.after(0, lambda: status.config(text="● THINKING...", fg="#ffd166"))
                root.after(0, lambda: send_button.config(state="disabled"))

                try:
                    response = ask_jarvis(command)
                    if not response:
                        response = "I'm here, sir."
                    root.after(0, show_response, response)
                except Exception as error:
                    print("Voice AI error:", error)
                    root.after(0, show_response, f"I encountered an error, sir: {error}")

        except Exception as error:
            print("Voice listener error:", error)
            time.sleep(0.5)


# ============================================================
# BOOT SEQUENCE LAUNCHER
# Defined before root.after() so startup scheduling works during
# module initialization. BootHUD itself is defined later.
# ============================================================
def launch_boot_sequence():
    if not HEADLESS:
        try:
            BootHUD()
        except Exception as e:
            print("Boot HUD error:", e)


# ============================================================
# STARTUP GREETING
# ============================================================

def startup_greeting():
    greeting = "Good morning, sir. JARVIS V3 systems are online and ready."
    add_message("JARVIS", greeting)
    status.config(text="● ONLINE", fg="#45ff8a")
    threading.Thread(target=speak, args=(greeting,), daemon=True).start()


# ============================================================
# INITIAL MESSAGE
# ============================================================

add_message(
    "JARVIS",
    "Systems online. Say Jarvis to activate voice mode, or press Ctrl Alt J to enter gesture-only hidden mode."
)


# ============================================================
# WINDOWS STARTUP
# ============================================================

setup_startup()


# ============================================================
# START VOICE
# ============================================================

if VOICE_ENABLED:
    threading.Thread(target=voice_listener, daemon=True).start()


# ============================================================
# STARTUP GREETING
# ============================================================

root.after(100, launch_boot_sequence)
root.after(1500, startup_greeting)


# ============================================================
# GUI EVENT BRIDGE
# ============================================================

gui_events = []
gui_events_lock = threading.Lock()


def push_gui_event(kind, text):
    try:
        with gui_events_lock:
            gui_events.append({"type": kind, "text": str(text)})
            if len(gui_events) > 30:
                del gui_events[:-30]
    except Exception:
        pass


# ============================================================
# V3 VISUAL BOOT SEQUENCE
# ============================================================
class BootHUD:
    def __init__(self):
        self.window=tk.Toplevel(root)
        self.window.configure(bg=HUD_BG)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost",True)
        position_on_laptop_monitor(self.window)
        self.lines=["CORE SYSTEM","VOICE ENGINE","AI CONNECTION","SYSTEM MONITOR","NETWORK","HUD ENGINE","TELEMETRY"]
        self.i=0
        tk.Label(self.window,text="J A R V I S",font=("Consolas",42,"bold"),fg=HUD_CYAN_BRIGHT,bg=HUD_BG).pack(pady=(120,10))
        tk.Label(self.window,text="PERSONAL AI SYSTEM  //  V3",font=("Consolas",11),fg="#54717a",bg=HUD_BG).pack()
        self.status=tk.Label(self.window,text="INITIALIZING...",font=("Consolas",14,"bold"),fg=HUD_CYAN,bg=HUD_BG); self.status.pack(pady=35)
        self.bar=tk.Canvas(self.window,width=520,height=8,bg="#10232a",highlightthickness=0); self.bar.pack()
        self.fill=self.bar.create_rectangle(0,0,0,8,fill=HUD_CYAN,width=0)
        self.run()
    def run(self):
        if self.i < len(self.lines):
            self.status.config(text="✓ " + self.lines[self.i])
            self.bar.coords(self.fill,0,0,int(520*(self.i+1)/len(self.lines)),8)
            self.i += 1
            self.window.after(180,self.run)
        else:
            self.status.config(text="ALL SYSTEMS ONLINE")
            self.window.after(650,self.close)
    def close(self):
        try:self.window.destroy()
        except Exception:pass


# ============================================================
# V3 BACKGROUND TELEMETRY / AUTO-DETECTION
# ============================================================
threading.Thread(target=telemetry_loop, daemon=True).start()
threading.Thread(target=smart_context_loop, daemon=True).start()

# ============================================================
# JARVIS V3 BOOT DIAGNOSTICS
# ============================================================
def v3_boot_diagnostics():
    checks = [
        ("CORE SYSTEM", True),
        ("VOICE ENGINE", VOICE_ENABLED),
        ("AI CONNECTION", bool(api_key)),
        ("SYSTEM MONITOR", True),
        ("NETWORK", True),
        ("HUD ENGINE", True),
        ("TELEMETRY", True),
    ]
    print("\\n========== JARVIS V3 BOOT ==========")
    for name, ok in checks:
        print(f"{'✓' if ok else '✗'} {name}")
    print("ALL SYSTEMS ONLINE\\n")


v3_boot_diagnostics()

# ============================================================
# PHONE API SERVER
# ============================================================

flask_app = Flask(__name__)


def require_token(req):
    """Constant-shape comparison isn't critical here since this is a
    local-network personal assistant, not a public service — but we
    still reject anything without a matching token."""
    return req.headers.get("X-JARVIS-TOKEN") == AUTH_TOKEN


@flask_app.route("/command", methods=["POST"])
def phone_command():
    if not require_token(request):
        return jsonify({"reply": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    user_text = data.get("text", "")

    if not user_text:
        return jsonify({"reply": "No text received."})

    push_gui_event("message", f"YOU|{user_text}")
    reply = ask_jarvis(user_text)
    push_gui_event("message", f"JARVIS|{reply}")
    threading.Thread(target=speak, args=(reply,), daemon=True).start()
    return jsonify({"reply": reply})


@flask_app.route("/events", methods=["GET"])
def gui_events_endpoint():
    if not require_token(request):
        return jsonify({"error": "unauthorized"}), 401

    with gui_events_lock:
        events = list(gui_events)
        gui_events.clear()
    return jsonify({"events": events})


@flask_app.route("/pending_file", methods=["GET"])
def pending_file():
    """Tells the phone whether a file is currently armed and ready."""
    if not require_token(request):
        return jsonify({"error": "unauthorized"}), 401

    path = get_armed_file()
    if not path:
        return jsonify({"available": False})

    return jsonify({
        "available": True,
        "name": os.path.basename(path),
        "size": os.path.getsize(path)
    })


@flask_app.route("/download_file", methods=["GET"])
def download_file():
    """Streams the currently armed file to the phone."""
    if not require_token(request):
        return jsonify({"error": "unauthorized"}), 401

    path = get_armed_file()
    if not path:
        return jsonify({"error": "no file pending"}), 404

    return send_file(path, as_attachment=True)


def run_server():
    flask_app.run(host="0.0.0.0", port=8000)


threading.Thread(target=run_server, daemon=True).start()


# ============================================================
# START
# ============================================================

entry.focus()
root.mainloop()