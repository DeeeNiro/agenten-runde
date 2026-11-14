"""Registriert die Agenten-Runde-Hooks in ~/.claude/settings.json (mit Backup).

Dieser PC (mit Widget):      python install.py
Anderer PC (Windows/Mac):    python3 install.py --server http://<IP>:47811 --token <SCHLUESSEL>
Entfernen:                   python install.py --uninstall
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]


def arg(name):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return None


# --- remote config (other PCs)
server, token = arg("--server"), arg("--token")
if server or token:
    if not (server and token):
        sys.exit("Bitte --server UND --token angeben.")
    cfg_p = os.path.join(HERE, "config.json")
    with open(cfg_p, "w", encoding="utf-8") as f:
        json.dump({"server": server.rstrip("/"), "token": token}, f, indent=2)
    print("Fern-Widget eingetragen:", server)

# --- hooks in settings.json
p = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
os.makedirs(os.path.dirname(p), exist_ok=True)
if os.path.exists(p):
    shutil.copy(p, p + ".bak-huddle")
    with open(p, encoding="utf-8") as f:
        s = json.load(f)
else:
    s = {}
py = sys.executable.replace("\\", "/")
hook = os.path.join(HERE, "hook.py").replace("\\", "/")
cmd = f'"{py}" "{hook}"'
hooks = s.setdefault("hooks", {})
events = [("SessionStart", None, 10), ("UserPromptSubmit", None, 10), ("PreToolUse", "*", 600),
          ("PostToolUse", "*", 10), ("PermissionRequest", "*", 600), ("Notification", None, 10),
          ("Stop", None, 10), ("SessionEnd", None, 10)]
for ev, matcher, timeout in events:
    lst = hooks.setdefault(ev, [])
    lst[:] = [x for x in lst if "huddle/hook.py" not in json.dumps(x)]
    if "--uninstall" not in args:
        e = {"hooks": [{"type": "command", "command": cmd, "timeout": timeout}]}
        if matcher:
            e["matcher"] = matcher
        lst.append(e)
    if not lst:
        del hooks[ev]
if not hooks:
    del s["hooks"]
with open(p, "w", encoding="utf-8") as f:
    json.dump(s, f, indent=2, ensure_ascii=False)
print("Hooks entfernt." if "--uninstall" in args else "Hooks installiert.",
      "Backup:", p + ".bak-huddle" if os.path.exists(p + ".bak-huddle") else "-")
