# Agenten-Runde

Ein kleines Desktop-Widget für Windows, das alle laufenden Claude-Code-Sitzungen
als Karten zeigt.

- Fortschritt (Aufgabenliste), aktuelle Tätigkeit und letzter Terminal-Befehl pro Sitzung
- Freigaben und Rückfragen direkt im Widget beantworten (oder wie gewohnt im Terminal)
- Jeder Sitzung einen eigenen Namen geben (Stift-Symbol neben dem Titel)
- Per Klick zum passenden Terminal-Fenster springen oder den Ordner in VS Code öffnen
- Sitzungen von anderen Rechnern können in derselben Liste erscheinen

## Installation

Das Repository ist ein Claude-Code-Skill. Den Ordner nach
`~/.claude/skills/agenten-runde` legen und Claude Code bitten:
„Installiere die Agenten-Runde". Claude führt dann die Schritte aus `SKILL.md` aus.

Von Hand geht es auch:

1. `files/huddle.pyw`, `files/hook.py` und `files/install.py` nach
   `%USERPROFILE%\.claude\huddle` kopieren.
2. `python install.py` in diesem Ordner ausführen. Das trägt die Hooks in
   `~/.claude/settings.json` ein und legt vorher ein Backup an.
3. Eine neue Claude-Code-Sitzung starten. Das Widget startet automatisch mit.

Entfernen: `python install.py --uninstall`.

## Voraussetzungen

- Windows
- Python 3.8 oder neuer mit Tkinter (keine weiteren Pakete nötig)
- Claude Code

## Dateien

| Datei | Zweck |
| --- | --- |
| `SKILL.md` | Anleitung für Claude Code: installieren, reparieren, entfernen |
| `files/huddle.pyw` | Das Widget (Tkinter-Fenster und lokaler Server auf `127.0.0.1:47811`) |
| `files/hook.py` | Leitet Claude-Code-Hook-Ereignisse an das Widget weiter und startet es bei Bedarf |
| `files/install.py` | Trägt die Hooks in `~/.claude/settings.json` ein oder entfernt sie |

Das Widget hört standardmäßig nur auf `127.0.0.1`.
