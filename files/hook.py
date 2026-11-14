"""Agent Huddle hook: forwards Claude Code hook events to the Huddle widget.

Local mode (default, Windows and macOS): talks to the widget on this computer
and auto-starts it on SessionStart / UserPromptSubmit.

Remote mode (any OS): if config.json next to this file names a "server"
(e.g. {"server": "http://100.101.102.103:47811", "token": "..."}), events go to
the widget on that PC instead, so other computers show up in the same list.
Silent no-op whenever the widget can't be reached - Claude keeps working.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

PORT = 47811
HERE = os.path.dirname(os.path.abspath(__file__))
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def load_config():
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


CFG = load_config()
REMOTE = (CFG.get("server") or "").rstrip("/")
BASE = REMOTE or f"http://127.0.0.1:{PORT}"
DOWN_FILE = os.path.join(HERE, ".remote_down")
BACKOFF = 30  # seconds to skip an unreachable remote widget (keeps Claude fast)


def post(path, data, timeout):
    headers = {"Content-Type": "application/json"}
    if REMOTE:
        headers["X-Huddle-Token"] = CFG.get("token", "")
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode("utf-8"),
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body else {}


def remote_down():
    try:
        return time.time() - os.path.getmtime(DOWN_FILE) < BACKOFF
    except OSError:
        return False


def mark_down():
    try:
        with open(DOWN_FILE, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


# ------------------------------------------------------------ Windows only
def ancestors():
    """PIDs of this process' ancestor chain (used to find the terminal window)."""
    if not IS_WIN:
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class PE(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
        k32 = ctypes.windll.kernel32
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snap = k32.CreateToolhelp32Snapshot(2, 0)
        pe = PE()
        pe.dwSize = ctypes.sizeof(PE)
        parent = {}
        ok = k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            parent[pe.th32ProcessID] = pe.th32ParentProcessID
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
        k32.CloseHandle(snap)
        chain, pid = [], os.getpid()
        for _ in range(20):
            pid = parent.get(pid)
            if not pid or pid in chain:
                break
            chain.append(pid)
        return chain
    except Exception:
        return []


def terminal_hwnd(pids):
    """Top-level window that hosts Claude's console.

    In Windows Terminal the console window is an invisible ConPTY pseudo
    window owned by the WindowsTerminal.exe window, which is NOT in our
    process chain. So we attach to an ancestor's console and walk up to the
    root owner (works for Windows Terminal and classic conhost).
    """
    if not IS_WIN:
        return 0
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32
        k32.GetConsoleWindow.restype = ctypes.c_void_p
        u32.GetAncestor.restype = ctypes.c_void_p
        u32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        for pid in pids:
            k32.FreeConsole()
            if not k32.AttachConsole(pid):
                continue
            h = k32.GetConsoleWindow()
            k32.FreeConsole()
            if h:
                root = u32.GetAncestor(h, 3)  # GA_ROOTOWNER
                return int(root or h)
    except Exception:
        pass
    return 0


# ------------------------------------------------------------ macOS only
def mac_terminal():
    """(ancestor PIDs, {"app": bundle path, "tty": device}) of this session.

    The widget uses them to bring the right terminal window to the front.
    """
    try:
        out = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,tty=,comm="],
                             capture_output=True, text=True, timeout=3).stdout
        table = {}
        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit():
                table[int(parts[0])] = (int(parts[1]), parts[2], parts[3])
        chain, pid, app, tty = [], os.getpid(), "", ""
        for _ in range(30):
            pid = table.get(pid, (0, "", ""))[0]
            if pid <= 1 or pid in chain or pid not in table:
                break
            chain.append(pid)
            _, t, comm = table[pid]
            if not tty and t not in ("??", "-", ""):
                tty = "/dev/" + t
            i = comm.find(".app/")
            if not app and i > 0:
                app = comm[:i + 4]
        return chain, {"app": app, "tty": tty}
    except Exception:
        return [], {"app": "", "tty": ""}


def add_window(data):
    """Tell the widget which terminal window this session lives in."""
    if IS_WIN:
        data["_pids"] = ancestors()
        data["_hwnd"] = terminal_hwnd(data["_pids"])
    elif IS_MAC:
        data["_pids"], data["_term"] = mac_terminal()


def start_widget():
    if not IS_WIN:
        env = dict(os.environ, TK_SILENCE_DEPRECATION="1")
        subprocess.Popen([sys.executable, os.path.join(HERE, "huddle.pyw")],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True,
                         close_fds=True, env=env, cwd=HERE)
        return
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    args = [pyw, os.path.join(HERE, "huddle.pyw")]
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    try:  # break out of the hook's job object so the widget survives
        subprocess.Popen(args, creationflags=flags | 0x01000000, close_fds=True)
    except OSError:
        subprocess.Popen(args, creationflags=flags, close_fds=True)


# ------------------------------------------------------------ main
def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")
    except Exception:
        return
    ev = data.get("hook_event_name", "")
    data["_host"] = socket.gethostname()
    if ev in ("SessionStart", "UserPromptSubmit") and not REMOTE:
        add_window(data)

    if REMOTE and remote_down():
        return  # widget recently unreachable: answer in the terminal as usual

    # Only PermissionRequest blocks: Claude Code shows its own dialog in the
    # terminal at the same time, so a question can be answered in either place.
    blocking = ev == "PermissionRequest"

    try:
        if blocking:
            out = post("/ask", data, timeout=590)
            if out:
                sys.stdout.write(json.dumps(out))
        else:
            r = post("/event", data, timeout=2)
            if (r.get("want_window") and not REMOTE
                    and "_hwnd" not in data and "_term" not in data):
                win = {"hook_event_name": "_Window", "_host": data["_host"],
                       "session_id": data.get("session_id"), "cwd": data.get("cwd", "")}
                add_window(win)  # widget was restarted and lost our window
                if "_hwnd" in win or "_term" in win:
                    post("/event", win, timeout=2)
    except (urllib.error.URLError, ConnectionError, OSError):
        if REMOTE:
            if not blocking:  # an unanswered question timing out is not "down"
                mark_down()
        elif ev in ("SessionStart", "UserPromptSubmit"):
            try:
                start_widget()
                for _ in range(30):
                    time.sleep(0.15)
                    try:
                        post("/event", data, timeout=2)
                        break
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass


if __name__ == "__main__":
    main()
