"""Agenten-Runde - floating overview of all running Claude Code sessions.

Receives events from hook.py on http://127.0.0.1:47811 and shows one card per
session: progress (todos), current activity, last terminal command, and lets
you answer permission prompts and AskUserQuestion questions inline.

Windows: a Tkinter window. macOS (and anything else): the same cards as a
small web page served on http://127.0.0.1:47811/ - shown in a native floating
window (panel.swift, built by install.py) or, without it, in the browser.
"""
import ctypes
import hmac
import json
import os
import select
import subprocess
import secrets
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 47811
HERE = os.path.dirname(os.path.abspath(__file__))
HOST = socket.gethostname()
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

try:
    import tkinter as tk
except ImportError:   # no Tk: the web interface is used instead
    tk = None


def load_ui():
    """"tk" (Windows default) or "web" (default elsewhere; Apple's built-in Tk
    is unreliable). config.json may force one with {"ui": "tk"} / {"ui": "web"}."""
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            ui = json.load(f).get("ui")
    except Exception:
        ui = None
    if ui not in ("tk", "web"):
        ui = "tk" if IS_WIN else "web"
    return ui if tk is not None else "web"


UI = load_ui()
UI_TOKEN = secrets.token_urlsafe(18)   # the web page must send this back


def load_token():
    """Shared secret other PCs must send (config.json next to this file)."""
    p = os.path.join(HERE, "config.json")
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(24)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    return cfg["token"]


TOKEN = load_token()

# Names the user gave to sessions (session id -> name); survive widget restarts.
NAMES_FILE = os.path.join(HERE, "names.json")


def load_names():
    try:
        with open(NAMES_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_names():
    try:
        while len(NAMES) > 300:          # oldest first
            NAMES.pop(next(iter(NAMES)))
        with open(NAMES_FILE, "w", encoding="utf-8") as f:
            json.dump(NAMES, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


NAMES = load_names()

# ---------------------------------------------------------------- colors
BG = "#121312"
CARD = "#1e1f1e"
CARD_HI = "#262826"
BORDER = "#2c2e2c"
TXT = "#f2f2f2"
SUB = "#9a9b9a"
DIM = "#6b6c6b"
ACC = "#d4f046"
BAR_BG = "#3a3b3a"
RED = "#f26b6b"
MASCOTS = ["#4f7cf7", "#f472a8", "#f59e42", "#8b6cf5", "#2fc4b2", "#ef5b5b", "#e9c46a"]

F_TITLE = ("Segoe UI Semibold", 10)
F_SUB = ("Segoe UI", 9)
F_SMALL = ("Segoe UI Semibold", 8)
F_MONO = ("Consolas", 8)
F_HEAD = ("Segoe UI Semibold", 10)


# ---------------------------------------------------------------- state
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.sessions = {}      # id -> dict
        self.order = []
        self.version = 0
        self.waiters = {}       # rid -> (Event, holder)
        self.muted = False
        self.color_i = 0
        self.carry = {}         # cwd -> (name, time): keeps a name across /clear

    def bump(self):
        self.version += 1

    def get(self, sid, cwd=""):
        s = self.sessions.get(sid)
        if s is None:
            name = NAMES.get(sid)
            s = dict(id=sid, cwd=cwd,
                     title=name or os.path.basename(cwd.rstrip("\\/")) or "Session",
                     named=bool(name), custom=bool(name),
                     activity="Gestartet", status="running", todos=[],
                     tasks={}, term=None, pending=None, pids=[], answered={},
                     color=MASCOTS[self.color_i % len(MASCOTS)], updated=time.time())
            self.color_i += 1
            self.sessions[sid] = s
            self.order.append(sid)
        if cwd and not s["cwd"]:
            s["cwd"] = cwd
        s["updated"] = time.time()
        return s

    def remove(self, sid):
        self.sessions.pop(sid, None)
        if sid in self.order:
            self.order.remove(sid)


ST = State()


def rename(sid, name):
    """Give a session its own name. An empty name switches back to the
    automatic title."""
    name = " ".join(str(name).split())[:60]
    with ST.lock:
        s = ST.sessions.get(sid)
        if s is None:
            return
        NAMES.pop(sid, None)
        if name:
            s["title"], s["named"], s["custom"] = name, True, True
            NAMES[sid] = name
        else:
            s["title"] = os.path.basename(s["cwd"].rstrip("\\/")) or "Session"
            s["named"] = s["custom"] = False
        save_names()
        ST.bump()


def beep():
    if ST.muted:
        return
    try:
        if IS_MAC:
            subprocess.Popen(["/usr/bin/afplay", "/System/Library/Sounds/Tink.aiff"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return
        import winsound
        threading.Thread(target=winsound.MessageBeep, args=(0x40,), daemon=True).start()
    except Exception:
        pass


def short(text, n):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def base(p):
    return os.path.basename(str(p).rstrip("\\/")) if p else ""


def describe_tool(name, inp):
    inp = inp or {}
    if name == "Bash":
        return short(inp.get("description") or inp.get("command", ""), 48)
    if name in ("Read", "NotebookRead"):
        return "Liest " + base(inp.get("file_path", ""))
    if name in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        return "Bearbeitet " + base(inp.get("file_path") or inp.get("notebook_path", ""))
    if name in ("Grep", "Glob"):
        return "Sucht " + short(inp.get("pattern", ""), 30)
    if name in ("WebFetch", "WebSearch"):
        return "Recherchiert im Web"
    if name in ("Task", "Agent"):
        return "Unteragent: " + short(inp.get("description", ""), 36)
    if name == "PowerShell":
        return short(inp.get("description") or inp.get("command", ""), 48)
    if name.startswith("mcp__"):
        return "Nutzt " + name.split("__")[-1]
    return "Nutzt " + name


def apply_tasks(s, name, inp, resp):
    """Support both TodoWrite and the newer TaskCreate/TaskUpdate tools."""
    if name == "TodoWrite":
        s["todos"] = [dict(content=t.get("content", ""), status=t.get("status", "pending"),
                           active=t.get("activeForm") or t.get("content", ""))
                      for t in inp.get("todos", [])]
        s["tasks"] = {}
        return
    if name == "TaskCreate":
        tid = None
        if isinstance(resp, dict):
            tid = resp.get("taskId") or resp.get("id") or (resp.get("task") or {}).get("id")
        tid = str(tid or len(s["tasks"]) + 1)
        s["tasks"][tid] = dict(content=inp.get("subject", ""), status="pending",
                               active=inp.get("activeForm") or inp.get("subject", ""))
    elif name == "TaskUpdate":
        t = s["tasks"].get(str(inp.get("taskId", "")))
        if t:
            if inp.get("status") == "deleted":
                s["tasks"].pop(str(inp.get("taskId")))
            else:
                t["status"] = inp.get("status", t["status"])
                t["content"] = inp.get("subject", t["content"])
                t["active"] = inp.get("activeForm", t["active"])
    else:
        return
    s["todos"] = list(s["tasks"].values())


def mark_host(s, d):
    host = d.get("_host")
    if host and host != HOST:
        s["remote"] = host


def release_pending(s, d):
    """The same question is also open in the terminal. Once the session moves
    on (answered there), drop it from the widget. Caller holds ST.lock."""
    p = s.get("pending")
    if not p:
        return
    ev = d.get("hook_event_name", "")
    if ev in ("Stop", "UserPromptSubmit") or (
            ev == "PostToolUse" and d.get("tool_name", "") == p.get("tool")):
        w = ST.waiters.get(p["rid"])
        if w and "decision" not in w[1]:
            w[1]["decision"] = {"kind": "terminal"}
            w[0].set()


def gone(conn):
    """True once the hook process on the other end of the socket has exited."""
    if conn is None:
        return False
    try:
        r, _, _ = select.select([conn], [], [], 0)
        return bool(r) and conn.recv(1, socket.MSG_PEEK) == b""
    except (OSError, ValueError):
        return True


def want_window(d):
    """After a widget restart the terminal window of a running session is
    unknown ('Zum Terminal' would do nothing): ask its hook to send it again."""
    if "_hwnd" in d or "_term" in d or d.get("_host") not in (None, HOST):
        return {}
    with ST.lock:
        s = ST.sessions.get(d.get("session_id") or "?")
        known = s is None or s.get("hwnd") or "termwin" in s
        return {} if known else {"want_window": True}


def handle_event(d):
    ev = d.get("hook_event_name", "")
    sid = d.get("session_id") or "?"
    with ST.lock:
        if ev == "SessionEnd":
            old = ST.sessions.get(sid)
            if old and old.get("custom") and d.get("reason") == "clear":
                ST.carry[old["cwd"]] = (old["title"], time.time())
            ST.remove(sid)
            ST.bump()
            return
        s = ST.get(sid, d.get("cwd", ""))
        if ev == "SessionStart" and d.get("source") == "clear" and not s.get("custom"):
            # /clear starts a new session id in the same terminal: keep its name.
            name, t = ST.carry.pop(s["cwd"], ("", 0))
            if name and time.time() - t < 60:
                s["title"], s["named"], s["custom"] = name, True, True
                NAMES[sid] = name
                save_names()
        mark_host(s, d)
        release_pending(s, d)
        if d.get("_pids"):
            s["pids"] = d["_pids"]
        if d.get("_hwnd"):
            s["hwnd"] = d["_hwnd"]
        if isinstance(d.get("_term"), dict):   # macOS: terminal app + tty
            s["termwin"] = d["_term"]
        if ev == "SessionStart":
            s["activity"] = "Bereit"
            s["status"] = "idle"
        elif ev == "UserPromptSubmit":
            p = d.get("prompt", "")
            if not s["named"] and p.strip() and not p.strip().startswith("/"):
                s["title"] = f"{base(s['cwd']) or 'Session'} · {short(p, 26)}"
                s["named"] = True
            s["activity"] = "Denkt nach…"
            s["status"] = "running"
        elif ev == "PreToolUse":
            name = d.get("tool_name", "")
            if name not in ("TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"):
                s["activity"] = describe_tool(name, d.get("tool_input"))
            if s["status"] != "permission":
                s["status"] = "running"
        elif ev == "PostToolUse":
            name = d.get("tool_name", "")
            inp = d.get("tool_input") or {}
            resp = d.get("tool_response")
            apply_tasks(s, name, inp, resp)
            if name in ("Bash", "PowerShell"):
                out = ""
                if isinstance(resp, dict):
                    out = (resp.get("stdout") or "") + (resp.get("stderr") or "")
                elif isinstance(resp, str):
                    out = resp
                lines = [l for l in out.strip().splitlines() if l.strip()]
                s["term"] = dict(cmd=inp.get("command", ""), out=lines[-3:])
            if s["status"] in ("permission", "waiting"):
                s["status"] = "running"
        elif ev == "Notification":
            nt = d.get("notification_type", "")
            msg = d.get("message", "")
            if s["pending"] is None:
                if nt == "permission_prompt" or "permission" in msg.lower():
                    s["status"] = "permission"
                    s["activity"] = "braucht Erlaubnis (im Terminal)"
                else:
                    s["status"] = "waiting"
                    s["activity"] = "wartet auf dich"
                beep()
        elif ev == "Stop":
            s["status"] = "done"
            s["activity"] = "Fertig"
            beep()
        ST.bump()


def handle_ask(d, conn=None):
    """Blocking: permission request or AskUserQuestion. Returns hook JSON output.

    Claude Code shows its own dialog in the terminal while this waits, so the
    user can answer in either place; whichever comes first wins.
    """
    ev = d.get("hook_event_name", "")
    sid = d.get("session_id") or "?"
    name = d.get("tool_name", "")
    inp = d.get("tool_input") or {}
    tuid = d.get("tool_use_id", "")
    is_q = name == "AskUserQuestion"

    with ST.lock:
        s = ST.get(sid, d.get("cwd", ""))
        mark_host(s, d)
        # AskUserQuestion already answered in PreToolUse -> pass answers on.
        if is_q and ev == "PermissionRequest" and tuid and tuid in s["answered"]:
            return {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                           "decision": {"behavior": "allow",
                                                        "updatedInput": s["answered"][tuid]}}}
        rid = uuid.uuid4().hex
        evt = threading.Event()
        holder = {}
        ST.waiters[rid] = (evt, holder)
        prev = s["status"]
        s["pending"] = dict(rid=rid, kind="question" if is_q else "permission",
                            tool=name, input=inp)
        s["status"] = "question" if is_q else "permission"
        ST.bump()
    beep()

    end = time.time() + 570
    while not evt.wait(0.5) and time.time() < end:
        if gone(conn):  # answered in the terminal: Claude Code stopped the hook
            break

    with ST.lock:
        ST.waiters.pop(rid, None)
        s = ST.sessions.get(sid)
        dec = holder.get("decision")
        if s is not None:
            s["pending"] = None
            if dec is None or dec.get("kind") == "terminal":
                s["status"] = prev if prev != "permission" else "running"
            ST.bump()

    if not dec or dec.get("kind") == "terminal":
        return {}
    if dec["kind"] == "allow":
        s_act = "Erlaubt ✓"
        out = {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                      "decision": {"behavior": "allow"}}}
    elif dec["kind"] == "deny":
        s_act = "Abgelehnt"
        out = {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                      "decision": {"behavior": "deny",
                                                   "message": "Vom Nutzer in der Agenten-Runde abgelehnt."}}}
    else:  # answer
        upd = dict(inp)
        upd["answers"] = dec["answers"]
        first = next(iter(dec["answers"].values()), "")
        s_act = f'Antwort: "{short(first, 28)}"'
        with ST.lock:
            if s is not None and tuid:
                s["answered"][tuid] = upd
        if ev == "PreToolUse":
            out = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                          "permissionDecision": "allow",
                                          "permissionDecisionReason": "In der Agenten-Runde beantwortet",
                                          "updatedInput": upd}}
        else:
            out = {"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                          "decision": {"behavior": "allow", "updatedInput": upd}}}
    with ST.lock:
        if s is not None:
            s["activity"] = s_act
            s["flash"] = time.time()
            s["status"] = "running"
            ST.bump()
    return out


def resolve(rid, decision):
    with ST.lock:
        w = ST.waiters.get(rid)
    if w:
        w[1]["decision"] = decision
        w[0].set()


def dismiss(sid):
    """Remove a card; a question still open there goes back to the terminal."""
    with ST.lock:
        p = ST.sessions.get(sid, {}).get("pending")
        ST.remove(sid)
        ST.bump()
    if p:
        resolve(p["rid"], {"kind": "terminal"})


# ---------------------------------------------------------------- web interface
def ui_state():
    """Everything the web page needs to draw the cards."""
    with ST.lock:
        out = []
        for i in ST.order:
            s = ST.sessions.get(i)
            if s is None:
                continue
            sub, col = sub_for(s)
            p = s.get("pending")
            out.append(dict(
                id=s["id"], title=s["title"], custom=bool(s.get("custom")),
                color=s["color"], status=s["status"], sub=sub, acc=col == ACC,
                todos=s["todos"], term=s.get("term"), remote=s.get("remote") or "",
                pending=p and dict(rid=p["rid"], kind=p["kind"], tool=p["tool"],
                                   input=p["input"])))
        return {"sessions": out, "muted": ST.muted}


def ui_log(msg):
    """Script errors of the web page, for troubleshooting."""
    try:
        p = os.path.join(HERE, "ui-errors.log")
        if not os.path.exists(p) or os.path.getsize(p) < 100_000:
            with open(p, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg)[:2000] + "\n")
    except OSError:
        pass


def ui_action(d):
    """A click in the web page."""
    a = d.get("action")
    sid = str(d.get("sid") or "")
    if a == "decide":
        dec = d.get("decision") or {}
        kind = dec.get("kind")
        if kind in ("allow", "deny", "terminal"):
            resolve(str(d.get("rid")), {"kind": kind})
        elif kind == "answer" and isinstance(dec.get("answers"), dict):
            resolve(str(d.get("rid")), {"kind": "answer", "answers": {
                str(k): str(v) for k, v in dec["answers"].items()}})
    elif a == "rename":
        rename(sid, d.get("name") or "")
    elif a == "dismiss":
        dismiss(sid)
    elif a == "mute":
        with ST.lock:
            ST.muted = not ST.muted
            ST.bump()
    elif a in ("focus", "vscode"):
        with ST.lock:
            s = ST.sessions.get(sid)
            s = dict(s) if s else None
        if s and not s.get("remote"):
            if a == "vscode":
                open_vscode(s)
            elif not toggle_terminal(s) and d.get("fallback"):
                open_vscode(s)
    elif a == "log":
        ui_log(d.get("msg"))
    return {}


def same(a, b):
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def deny(self, code=403):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def local_page(self):
        """The web interface is for this computer only: local caller and a local
        Host header (keeps other websites and other machines out)."""
        host = (self.headers.get("Host") or "").lower()
        return (self.client_address[0] in ("127.0.0.1", "::1")
                and host in (f"127.0.0.1:{PORT}", f"localhost:{PORT}"))

    def ui_allowed(self):
        return self.local_page() and same(self.headers.get("X-Huddle-UI", ""), UI_TOKEN)

    def send_body(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """/  and /state: the web interface (this computer only).

        /setup?token=...  ->  a small Python script that installs the hook on
        another PC and points it at this widget:  curl -s "<url>" | python3"""
        from urllib.parse import urlparse, parse_qs
        import base64
        u = urlparse(self.path)
        if u.path == "/":
            if not self.local_page():
                return self.deny()
            try:
                with open(os.path.join(HERE, "ui.html"), encoding="utf-8") as f:
                    page = f.read()
            except OSError:
                return self.deny(404)
            return self.send_body(page.replace("__UI_TOKEN__", UI_TOKEN).encode("utf-8"),
                                  "text/html; charset=utf-8")
        if u.path == "/state":
            if not self.ui_allowed():
                return self.deny()
            return self.send_body(json.dumps(ui_state()).encode("utf-8"), "application/json")
        tok = (parse_qs(u.query).get("token") or [""])[0]
        if u.path != "/setup" or not hmac.compare_digest(tok, TOKEN):
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        files = {}
        for name in ("hook.py", "install.py"):
            with open(os.path.join(HERE, name), "rb") as f:
                files[name] = base64.b64encode(f.read()).decode("ascii")
        server = "http://" + (self.headers.get("Host") or f"{self.server.server_address[0]}:{PORT}")
        script = (
            "import base64, os, subprocess, sys\n"
            f"FILES = {files!r}\n"
            "d = os.path.join(os.path.expanduser('~'), '.claude', 'huddle')\n"
            "os.makedirs(d, exist_ok=True)\n"
            "for name, b in FILES.items():\n"
            "    with open(os.path.join(d, name), 'wb') as f:\n"
            "        f.write(base64.b64decode(b))\n"
            f"sys.exit(subprocess.call([sys.executable, os.path.join(d, 'install.py'), "
            f"'--server', {server!r}, '--token', {TOKEN!r}]))\n"
        )
        body = script.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/x-python; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/ui" and not self.ui_allowed():
            return self.deny()
        ip = self.client_address[0]
        if ip not in ("127.0.0.1", "::1") and not hmac.compare_digest(
                self.headers.get("X-Huddle-Token", ""), TOKEN):
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n > 5_000_000:
            self.send_response(413)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            d = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            d = {}
        out = {}
        try:
            if self.path == "/ask":
                out = handle_ask(d, self.connection)
            elif self.path == "/ui":
                out = ui_action(d)
            else:
                handle_event(d)
                out = want_window(d)
        except Exception:
            out = {}
        body = json.dumps(out).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------- window focus
if IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]


    def _pid_name(pid):
        """Executable name of a PID (lowercase), '' if unknown."""
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(520)
            n = wintypes.DWORD(520)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                return os.path.basename(buf.value).lower()
            return ""
        finally:
            k32.CloseHandle(h)


    user32.GetForegroundWindow.restype = wintypes.HWND
    LAST_FG = [0]   # last foreground window that is not the widget itself


    def track_foreground():
        """Called every tick: remember which foreign window was active last.
        (When the widget is clicked it becomes the foreground window itself.)"""
        h = user32.GetForegroundWindow()
        if not h:
            return
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value != os.getpid():
            LAST_FG[0] = h


    def toggle_terminal(s):
        """'Zum Terminal': bring it to the front - or minimize it if it already was."""
        hwnd = session_hwnd(s)
        if hwnd and LAST_FG[0] == hwnd and not user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 6)          # SW_MINIMIZE
            LAST_FG[0] = 0
            return True
        return focus_session(s)


    def session_hwnd(s):
        with ST.lock:  # use the freshest data (hwnd may have arrived later)
            s = dict(ST.sessions.get(s["id"], s))
        hwnd = s.get("hwnd") or 0
        return hwnd if (hwnd and user32.IsWindow(hwnd)) else 0


    def focus_session(s):
        with ST.lock:  # use the freshest data (hwnd may have arrived later)
            s = dict(ST.sessions.get(s["id"], s))
        hwnd = s.get("hwnd") or 0
        if not (hwnd and user32.IsWindow(hwnd)):
            # Fallback: window of a process in the hook's ancestor chain.
            # explorer.exe is excluded, otherwise a random Explorer window wins.
            pids = [p for p in (s.get("pids") or []) if _pid_name(p) != "explorer.exe"]
            found = []

            def cb(h, _):
                if user32.IsWindowVisible(h) and user32.GetWindowTextLengthW(h) > 0:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                    if pid.value in pids:
                        found.append((pids.index(pid.value), h))
                return True

            user32.EnumWindows(WNDENUMPROC(cb), 0)
            if not found:
                return False
            hwnd = sorted(found)[0][1]
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        user32.keybd_event(0x12, 0, 0, 0)       # Alt tap lets us steal focus
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(hwnd)
        return True


    def open_vscode(s):
        if s.get("cwd"):
            subprocess.Popen(f'code "{s["cwd"]}"', shell=True, creationflags=0x08000000)

elif IS_MAC:
    # A session is found by the terminal's tty (Terminal, iTerm2); other apps
    # (VS Code, ...) are simply brought to the front.
    TAB_SCRIPTS = {
        "Terminal": """on run argv
  tell application "Terminal"
    repeat with w in windows
      repeat with t in tabs of w
        if tty of t is (item 1 of argv) then
          set selected of t to true
          if miniaturized of w then set miniaturized of w to false
          set index of w to 1
          activate
          return "ok"
        end if
      end repeat
    end repeat
  end tell
  return "no"
end run""",
        "iTerm": """on run argv
  tell application "iTerm2"
    repeat with w in windows
      repeat with t in tabs of w
        repeat with ss in sessions of t
          if tty of ss is (item 1 of argv) then
            select w
            select t
            select ss
            activate
            return "ok"
          end if
        end repeat
      end repeat
    end repeat
  end tell
  return "no"
end run""",
    }

    def _focus(app, tty):
        script = TAB_SCRIPTS.get(os.path.basename(app)[:-4])
        if script and tty:
            try:
                r = subprocess.run(["/usr/bin/osascript", "-", tty], input=script,
                                   capture_output=True, text=True, timeout=60)
                if r.returncode == 0 and r.stdout.strip() == "ok":
                    return
            except Exception:
                pass
        subprocess.call(["/usr/bin/open", "-a", app])

    def track_foreground():
        pass

    def focus_session(s):
        with ST.lock:  # use the freshest data (the window may have arrived later)
            s = dict(ST.sessions.get(s["id"], s))
        t = s.get("termwin") or {}
        app = t.get("app") or ""
        if not (app.endswith(".app") and os.path.isdir(app)):
            return False
        threading.Thread(target=_focus, args=(app, t.get("tty") or ""), daemon=True).start()
        return True

    toggle_terminal = focus_session

    def open_vscode(s):
        cwd = s.get("cwd")
        if not (cwd and os.path.isdir(cwd)):
            return

        def run():  # without VS Code: show the folder in the Finder
            if subprocess.call(["/usr/bin/open", "-a", "Visual Studio Code", cwd],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL):
                subprocess.call(["/usr/bin/open", cwd])
        threading.Thread(target=run, daemon=True).start()

else:
    def track_foreground():
        pass

    def focus_session(s):
        return False

    toggle_terminal = focus_session

    def open_vscode(s):
        cwd = s.get("cwd")
        if cwd and os.path.isdir(cwd):
            try:
                subprocess.Popen(["code", cwd])
            except OSError:
                pass


# ---------------------------------------------------------------- UI helpers
def btn(parent, text, cmd, primary=False, bg=None):
    b = tk.Label(parent, text=text, font=F_SMALL, padx=10, pady=3, cursor="hand2",
                 bg=ACC if primary else (bg or "#333533"), fg="#111" if primary else TXT)
    b.bind("<Button-1>", lambda e: cmd())
    return b


def icon(parent, text, cmd, bg, fg=SUB, font=("Segoe UI Symbol", 9)):
    l = tk.Label(parent, text=text, font=font, bg=bg, fg=fg, cursor="hand2", padx=3)
    l.bind("<Button-1>", lambda e: (cmd(), "break")[1])
    l.bind("<Enter>", lambda e: l.config(fg=TXT))
    l.bind("<Leave>", lambda e: l.config(fg=fg))
    return l


def rrect(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def mascot(parent, color, bg, mood="normal"):
    c = tk.Canvas(parent, width=34, height=44, bg=bg, highlightthickness=0)
    c.create_oval(6, 37, 28, 43, fill="#0c0c0c", outline="")
    rrect(c, 7, 4, 27, 36, 6, fill=color, outline="")
    if mood == "done":
        c.create_arc(10, 12, 16, 18, start=0, extent=180, style="arc", outline="#111", width=2)
        c.create_arc(18, 12, 24, 18, start=0, extent=180, style="arc", outline="#111", width=2)
    else:
        c.create_rectangle(11, 13, 14, 17, fill="#111", outline="")
        c.create_rectangle(20, 13, 23, 17, fill="#111", outline="")
    if mood == "ask":
        c.create_oval(14, 22, 20, 28, outline="#111", width=2)
    else:
        c.create_line(13, 25, 21, 25, fill="#111", width=2)
    return c


def bar(parent, frac, bg, width=200):
    c = tk.Canvas(parent, width=width, height=4, bg=bg, highlightthickness=0)
    c.create_rectangle(0, 0, width, 4, fill=BAR_BG, outline="")
    c._hud_width = width
    c._hud_fill = c.create_rectangle(0, 0, 0, 4, fill=ACC, outline="")
    c._hud_frac = None
    set_bar(c, frac)
    return c


def set_bar(c, frac):
    if c._hud_frac == frac:
        return
    c._hud_frac = frac
    w = max(4, int(c._hud_width * frac)) if frac > 0 else 0
    c.coords(c._hud_fill, 0, 0, w, 4)
    c.itemconfigure(c._hud_fill, state="normal" if w else "hidden")


def setw(w, **kw):
    """Configure a widget only with values that actually changed (no redraw otherwise)."""
    last = getattr(w, "_hud", None)
    if last is None:
        last = w._hud = {}
    ch = {k: v for k, v in kw.items() if last.get(k) != v}
    if ch:
        w.config(**ch)
        last.update(ch)


def todo_style(st):
    sym, fg, font = {"completed": ("✓", DIM, F_SUB),
                     "in_progress": ("◐", TXT, ("Segoe UI Semibold", 9))}.get(
        st, ("○", SUB, F_SUB))
    return sym, (ACC if st == "in_progress" else fg), fg, font


def sub_for(s):
    pend = s.get("pending")
    if pend:
        return ("stellt eine Frage" if pend["kind"] == "question"
                else "braucht Erlaubnis"), ACC
    if s["status"] == "done":
        return "Fertig ✓", ACC
    if s["status"] in ("waiting", "permission") or time.time() - s.get("flash", 0) < 6:
        return s["activity"], ACC
    return s["activity"], SUB


# ---------------------------------------------------------------- app
class App:
    W = 330

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Agenten-Runde")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.97)
        self.root.configure(bg=BORDER)
        self.expanded = set()
        self.collapsed = False
        self.choices = {}       # rid -> {question: set(labels)}
        self.last_key = None
        self.refs = {}          # sid -> widgets that get updated in place
        self.editing = None     # sid whose name is being edited
        self.edit_var = tk.StringVar()
        self.edit_entry = None
        self.edit_fresh = False
        self.outer = tk.Frame(self.root, bg=BG)
        self.outer.pack(fill="both", expand=True, padx=1, pady=1)
        self.root.minsize(self.W, 0)
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"+{sw - self.W - 24}+24")
        self._drag = None
        self.tick()

    # --- dragging
    def start_drag(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def do_drag(self, e):
        if self._drag:
            self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def tick(self):
        try:
            track_foreground()
            self.render()
        finally:
            self.root.after(250, self.tick)

    def force(self):
        self.last_key = None

    # --- rendering
    def layout_key(self, sessions):
        """Everything that changes the widget *structure*. Text-only changes are
        excluded and get applied in place (no rebuild -> no flicker)."""
        parts = [self.collapsed, ST.muted, self.editing]
        for s in sessions:
            pend = s.get("pending")
            hi = pend is not None or s["status"] in ("waiting", "permission")
            todos = s["todos"]
            exp = s["id"] in self.expanded
            term = s.get("term")
            ch = None
            if pend and pend["kind"] == "question":
                ch = sorted((q, sorted(v)) for q, v in self.choices.get(pend["rid"], {}).items())
            parts.append((s["id"], s["title"], s["color"], hi, s["status"] == "done",
                          pend["rid"] if pend else None, exp, len(todos),
                          any(t["status"] == "in_progress" for t in todos),
                          bool(term), len(term["out"]) if (exp and term) else 0, repr(ch)))
        return tuple(parts)

    def render(self):
        with ST.lock:
            sessions = [dict(ST.sessions[i]) for i in ST.order if i in ST.sessions]
        if self.editing and (self.collapsed
                             or all(s["id"] != self.editing for s in sessions)):
            self.editing = None
        key = self.layout_key(sessions)
        if key == self.last_key:
            self.update_dynamic(sessions)
            return
        self.last_key = key
        self.refs = {}
        # Keep typing in the name field across a rebuild - but never pull the
        # keyboard away from another window.
        try:
            refocus = self.edit_fresh or self.root.focus_displayof() is not None
        except Exception:
            refocus = self.edit_fresh
        self.edit_entry = None
        # Build the new content off-screen, then swap in one go.
        new = tk.Frame(self.root, bg=BG)
        self.build(new, sessions)
        old, self.outer = self.outer, new
        new.pack(fill="both", expand=True, padx=1, pady=1)
        old.destroy()
        e = self.edit_entry
        if e is not None and refocus:
            e.focus_force()
            if self.edit_fresh:
                e.select_range(0, "end")
            e.icursor("end")
        self.edit_fresh = False

    def update_dynamic(self, sessions):
        for s in sessions:
            r = self.refs.get(s["id"])
            if not r:
                continue
            text, fg = sub_for(s)
            setw(r["sub"], text=short(text, 40), fg=fg)
            todos = s["todos"]
            if todos and "count" in r:
                done = sum(1 for t in todos if t["status"] == "completed")
                cur = next((t for t in todos if t["status"] == "in_progress"), None)
                setw(r["count"], text=f"{done}/{len(todos)}")
                if r.get("cur") is not None and cur:
                    setw(r["cur"], text=" " + short(cur["active"], 30))
                set_bar(r["bar"], done / len(todos))
            for (sym_l, txt_l), t in zip(r.get("rows", []), todos):
                sym, symfg, fg, font = todo_style(t["status"])
                setw(sym_l, text=sym, fg=symfg)
                setw(txt_l, text=short(t["content"], 42), fg=fg, font=font)
            term = s.get("term")
            if term and r.get("term_cmd") is not None:
                setw(r["term_cmd"], text="$ " + short(term["cmd"], 52))
                for l, line in zip(r["term_lines"], term["out"]):
                    setw(l, text=short(line, 56))

    def build(self, outer, sessions):
        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", padx=10, pady=(8, 6))
        dot = tk.Label(head, text="●", fg=ACC, bg=BG, font=("Segoe UI", 8))
        dot.pack(side="left")
        t = tk.Label(head, text=" Agenten-Runde", fg=TXT, bg=BG, font=F_HEAD)
        t.pack(side="left")
        tk.Label(head, text=f" {len(sessions)}", fg=DIM, bg=BG, font=F_HEAD).pack(side="left")
        for w in (head, dot, t):
            w.bind("<ButtonPress-1>", self.start_drag)
            w.bind("<B1-Motion>", self.do_drag)
        icon(head, "×", self.root.destroy, BG, font=("Segoe UI", 11)).pack(side="right")
        icon(head, "▾" if self.collapsed else "▴", self.toggle_collapse, BG).pack(side="right")
        icon(head, "🔇" if ST.muted else "🔊", self.toggle_mute, BG).pack(side="right")

        if self.collapsed:
            return
        if not sessions:
            tk.Label(outer, text="Keine laufenden Sessions", fg=DIM, bg=BG,
                     font=F_SUB).pack(padx=10, pady=(0, 12))
            return
        body = tk.Frame(outer, bg=BG)
        body.pack(fill="x", padx=8, pady=(0, 8))
        for s in sessions:
            self.card(body, s)

    def card(self, parent, s):
        pend = s.get("pending")
        hi = pend is not None or s["status"] in ("waiting", "permission")
        wrap = tk.Frame(parent, bg=ACC if hi else BG)
        wrap.pack(fill="x", pady=3)
        bgc = CARD_HI if hi else CARD
        c = tk.Frame(wrap, bg=bgc)
        c.pack(fill="x", padx=1 if hi else 0, pady=1 if hi else 0)

        top = tk.Frame(c, bg=bgc)
        top.pack(fill="x", padx=8, pady=6)
        mood = "done" if s["status"] == "done" else ("ask" if hi else "normal")
        mascot(top, s["color"], bgc, mood).pack(side="left", padx=(0, 8))

        right = tk.Frame(top, bg=bgc)
        right.pack(side="right", fill="y")
        if not s.get("remote"):
            icon(right, "⧉", lambda: toggle_terminal(s) or open_vscode(s), bgc).pack()
        icon(right, "×", lambda: self.dismiss(s), bgc, font=("Segoe UI", 11)).pack()

        mid = tk.Frame(top, bg=bgc)
        mid.pack(side="left", fill="x", expand=True)
        trow = tk.Frame(mid, bg=bgc)
        trow.pack(fill="x")
        if self.editing == s["id"]:
            icon(trow, "✓", self.commit_edit, bgc, fg=ACC).pack(side="right")
            e = tk.Entry(trow, textvariable=self.edit_var, font=F_TITLE, fg=TXT,
                         bg="#151615", insertbackground=TXT, relief="flat",
                         highlightthickness=1, highlightbackground=ACC,
                         highlightcolor=ACC)
            e.pack(side="left", fill="x", expand=True)
            e.bind("<Return>", lambda ev: self.commit_edit())
            e.bind("<Escape>", lambda ev: self.cancel_edit())
            e.bind("<Button-1>", lambda ev: None)   # clicking it must not fold the card
            self.edit_entry = e
        else:
            icon(trow, "✎", lambda: self.start_edit(s), bgc, fg=DIM).pack(side="right")
            tk.Label(trow, text=short((f"{s['remote']} › " if s.get("remote") else "")
                                      + s["title"], 34),
                     font=F_TITLE, fg=TXT, bg=bgc, anchor="w").pack(
                side="left", fill="x", expand=True)

        r = self.refs[s["id"]] = {}
        sub, subfg = sub_for(s)
        r["sub"] = tk.Label(mid, text=short(sub, 40), font=F_SUB, fg=subfg, bg=bgc, anchor="w")
        r["sub"].pack(fill="x")

        todos = s["todos"]
        if todos:
            done = sum(1 for t in todos if t["status"] == "completed")
            cur = next((t for t in todos if t["status"] == "in_progress"), None)
            row = tk.Frame(mid, bg=bgc)
            row.pack(fill="x")
            r["count"] = tk.Label(row, text=f"{done}/{len(todos)}", font=F_SMALL, fg=ACC, bg=bgc)
            r["count"].pack(side="left")
            if cur:
                r["cur"] = tk.Label(row, text=" " + short(cur["active"], 30), font=F_SMALL,
                                    fg=SUB, bg=bgc)
                r["cur"].pack(side="left")
            r["bar"] = bar(mid, done / len(todos), bgc)
            r["bar"].pack(anchor="w", pady=(3, 0))

        if pend and pend["kind"] == "permission":
            self.permission_box(c, s, pend, bgc)
        elif pend and pend["kind"] == "question":
            self.question_box(c, s, pend, bgc)
        elif s["id"] in self.expanded:
            self.details(c, s, bgc)

        # Whole card toggles open/closed - except widgets with their own click
        # action (buttons, icons, answer options).
        def bind_all(w):
            if not w.bind("<Button-1>"):
                w.bind("<Button-1>", lambda e, sid=s["id"]: self.toggle(sid))
                try:
                    w.configure(cursor="hand2")
                except tk.TclError:
                    pass
            for ch in w.winfo_children():
                bind_all(ch)
        bind_all(wrap)

    def details(self, c, s, bgc):
        box = tk.Frame(c, bg=bgc)
        box.pack(fill="x", padx=12, pady=(0, 8))
        refs = self.refs.setdefault(s["id"], {})
        refs["rows"] = []
        for t in s["todos"]:
            sym, symfg, fg, font = todo_style(t["status"])
            r = tk.Frame(box, bg=bgc)
            r.pack(fill="x")
            l1 = tk.Label(r, text=sym, fg=symfg, bg=bgc, font=("Segoe UI Symbol", 9), width=2)
            l1.pack(side="left")
            l2 = tk.Label(r, text=short(t["content"], 42), fg=fg, bg=bgc, font=font, anchor="w")
            l2.pack(side="left", fill="x")
            refs["rows"].append((l1, l2))
        if s.get("term"):
            term = tk.Frame(box, bg="#151615")
            term.pack(fill="x", pady=(6, 0))
            tk.Label(term, text="▣ Terminal", fg=ACC, bg="#151615", font=F_SMALL,
                     anchor="w").pack(fill="x", padx=6, pady=(4, 0))
            refs["term_cmd"] = tk.Label(term, text="$ " + short(s["term"]["cmd"], 52), fg=ACC,
                                        bg="#151615", font=F_MONO, anchor="w")
            refs["term_cmd"].pack(fill="x", padx=6)
            refs["term_lines"] = []
            for line in s["term"]["out"]:
                l = tk.Label(term, text=short(line, 56), fg=SUB, bg="#151615", font=F_MONO,
                             anchor="w")
                l.pack(fill="x", padx=6)
                refs["term_lines"].append(l)
            tk.Frame(term, bg="#151615", height=4).pack()
        if not s["todos"] and not s.get("term"):
            tk.Label(box, text="Noch keine Details", fg=DIM, bg=bgc, font=F_SUB,
                     anchor="w").pack(fill="x")
        b = tk.Frame(box, bg=bgc)
        b.pack(fill="x", pady=(6, 0))
        if s.get("remote"):
            tk.Label(b, text=f"läuft auf {s['remote']}", fg=DIM, bg=bgc,
                     font=F_SUB).pack(side="left")
        else:
            btn(b, "Zum Terminal", lambda: toggle_terminal(s), bg="#333533").pack(side="left")
            btn(b, "In VS Code", lambda: open_vscode(s)).pack(side="left", padx=6)

    def permission_box(self, c, s, pend, bgc):
        box = tk.Frame(c, bg=bgc)
        box.pack(fill="x", padx=10, pady=(0, 8))
        inp = pend["input"] or {}
        if pend["tool"] in ("Bash", "PowerShell"):
            what = f'{pend["tool"]}: {inp.get("command", "")}'
        elif "file_path" in inp:
            what = f'{pend["tool"]}: {inp["file_path"]}'
        elif "url" in inp:
            what = f'{pend["tool"]}: {inp["url"]}'
        else:
            what = f'{pend["tool"]}: {short(json.dumps(inp, ensure_ascii=False), 120)}'
        tk.Label(box, text=short(what, 220), fg=TXT, bg="#151615", font=F_MONO, anchor="w",
                 justify="left", wraplength=280, padx=6, pady=5).pack(fill="x")
        b = tk.Frame(box, bg=bgc)
        b.pack(fill="x", pady=(6, 0))
        rid = pend["rid"]
        btn(b, "Erlauben", lambda: self.decide(rid, {"kind": "allow"}), primary=True).pack(side="left")
        btn(b, "Ablehnen", lambda: self.decide(rid, {"kind": "deny"})).pack(side="left", padx=6)
        btn(b, "Am PC" if s.get("remote") else "Im Terminal",
            lambda: (self.decide(rid, {"kind": "terminal"}),
                     None if s.get("remote") else self.root.after(400, lambda: focus_session(s)))
            ).pack(side="left")

    def question_box(self, c, s, pend, bgc):
        box = tk.Frame(c, bg=bgc)
        box.pack(fill="x", padx=10, pady=(0, 8))
        rid = pend["rid"]
        qs = (pend["input"] or {}).get("questions", [])
        sel = self.choices.setdefault(rid, {})
        for q in qs:
            qt = q.get("question", "")
            chosen = sel.setdefault(qt, set())
            if q.get("header"):
                tk.Label(box, text=" " + q["header"].upper() + " ", bg=ACC, fg="#111",
                         font=("Segoe UI Semibold", 7)).pack(anchor="w", pady=(4, 2))
            tk.Label(box, text=qt, fg=TXT, bg=bgc, font=F_TITLE, anchor="w", justify="left",
                     wraplength=290).pack(fill="x")
            for o in q.get("options", []):
                lab = o.get("label", "")
                on = lab in chosen
                row = tk.Frame(box, bg="#2c2e2c" if on else "#1a1b1a", cursor="hand2")
                row.pack(fill="x", pady=1)
                mark = ("☑" if on else "☐") if q.get("multiSelect") else ("◉" if on else "○")
                l1 = tk.Label(row, text=f"{mark}  {lab}", fg=ACC if on else TXT, bg=row["bg"],
                              font=F_SUB, anchor="w", padx=6, pady=2)
                l1.pack(fill="x")
                widgets = [row, l1]
                if o.get("description"):
                    l2 = tk.Label(row, text=short(o["description"], 70), fg=DIM, bg=row["bg"],
                                  font=("Segoe UI", 8), anchor="w", padx=22)
                    l2.pack(fill="x")
                    widgets.append(l2)
                for w in widgets:
                    w.bind("<Button-1>", lambda e, qt=qt, lab=lab, m=q.get("multiSelect"):
                           self.pick(rid, qt, lab, m))
        b = tk.Frame(box, bg=bgc)
        b.pack(fill="x", pady=(6, 0))
        ready = all(sel.get(q.get("question", "")) for q in qs) and qs
        btn(b, "Senden", lambda: self.send_answers(rid, qs), primary=bool(ready)).pack(side="left")
        btn(b, "Am PC" if s.get("remote") else "Im Terminal",
            lambda: (self.decide(rid, {"kind": "terminal"}),
                     None if s.get("remote") else self.root.after(400, lambda: focus_session(s)))
            ).pack(side="left", padx=6)

    # --- actions
    def start_edit(self, s):
        self.editing = s["id"]
        self.edit_var.set(s["title"] if s.get("custom") else "")
        self.edit_fresh = True
        self.force()

    def commit_edit(self):
        sid, self.editing = self.editing, None
        if sid:
            rename(sid, self.edit_var.get())
        self.force()

    def cancel_edit(self):
        self.editing = None
        self.force()

    def toggle(self, sid):
        self.expanded.symmetric_difference_update({sid})
        self.force()

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        self.force()

    def toggle_mute(self):
        ST.muted = not ST.muted
        self.force()

    def dismiss(self, s):
        with ST.lock:
            p = ST.sessions.get(s["id"], {}).get("pending")
            ST.remove(s["id"])
            ST.bump()
        if p:
            resolve(p["rid"], {"kind": "terminal"})

    def decide(self, rid, decision):
        resolve(rid, decision)
        self.choices.pop(rid, None)

    def pick(self, rid, qt, lab, multi):
        chosen = self.choices.setdefault(rid, {}).setdefault(qt, set())
        if multi:
            chosen.symmetric_difference_update({lab})
        else:
            chosen.clear()
            chosen.add(lab)
        self.force()

    def send_answers(self, rid, qs):
        sel = self.choices.get(rid, {})
        if not all(sel.get(q.get("question", "")) for q in qs):
            return
        answers = {q["question"]: ", ".join(sorted(sel[q["question"]])) for q in qs}
        self.decide(rid, {"kind": "answer", "answers": answers})


def main():
    try:
        # Windows: never share the port. Elsewhere SO_REUSEADDR still refuses a
        # second widget, but lets a restart bind right after the old one ended.
        ThreadingHTTPServer.allow_reuse_address = not IS_WIN
        # Local only by default. To let other PCs in, add "listen": "0.0.0.0"
        # to config.json (they must send the token).
        try:
            with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
                listen = json.load(f).get("listen") or "127.0.0.1"
        except Exception:
            listen = "127.0.0.1"
        srv = ThreadingHTTPServer((listen, PORT), Handler)
    except OSError:
        return  # already running
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if UI == "web":
        return run_web()
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    App().root.mainloop()


def run_web():
    """Show the web interface: in the native floating window on macOS (closing
    it ends the widget, like the X on Windows), otherwise in the browser."""
    url = f"http://127.0.0.1:{PORT}/"
    panel = os.path.join(HERE, "AgentenRunde")
    if IS_MAC and os.access(panel, os.X_OK):
        t = time.time()
        try:
            rc = subprocess.call([panel, url], stdin=subprocess.DEVNULL)
            if rc == 0 or time.time() - t > 5:   # closed (not: failed to start)
                return
        except OSError:
            pass
    try:
        if IS_MAC:
            subprocess.call(["/usr/bin/open", url])
        else:
            import webbrowser
            webbrowser.open(url)
    except Exception:
        pass
    threading.Event().wait()   # keep serving until the process is stopped


if __name__ == "__main__":
    main()
