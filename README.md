# Agenten-Runde

Ein kleines Desktop-Widget für Windows und macOS, das alle laufenden
Claude-Code-Sitzungen als Karten zeigt.

- Fortschritt (Aufgabenliste), aktuelle Tätigkeit und letzter Terminal-Befehl pro Sitzung
- Zeigt an, wenn nach Claudes Antwort noch ein Hintergrundbefehl oder Hintergrund-Agent läuft
- Freigaben und Rückfragen direkt im Widget beantworten (oder wie gewohnt im Terminal)
- Jeder Sitzung einen eigenen Namen geben (Stift-Symbol neben dem Titel)
- Per Klick zum passenden Terminal-Fenster springen (zweiter Klick klappt es wieder ein)
  oder den Ordner in VS Code öffnen
- Sitzungen von anderen Rechnern können in derselben Liste erscheinen

## Installation

Das Repository ist ein Claude-Code-Skill. Den Ordner nach
`~/.claude/skills/agenten-runde` legen und Claude Code bitten:
„Installiere die Agenten-Runde". Claude führt dann die Schritte aus `SKILL.md` aus.

Von Hand geht es auch:

1. Alle Dateien aus `files/` nach `~/.claude/huddle` kopieren
   (Windows: `%USERPROFILE%\.claude\huddle`).
2. In diesem Ordner `python install.py` ausführen (macOS: `python3 install.py`).
   Das trägt die Hooks in `~/.claude/settings.json` ein und legt vorher ein Backup an.
   Unter macOS wird dabei auch das kleine Fenster des Widgets gebaut.
3. Eine neue Claude-Code-Sitzung starten. Das Widget startet automatisch mit.

Entfernen: `python install.py --uninstall`.

## Voraussetzungen

- Claude Code
- **Windows:** Python 3.8 oder neuer mit Tkinter (keine weiteren Pakete nötig)
- **macOS:** das mitgelieferte `python3` (Xcode oder Xcode-Befehlszeilenwerkzeuge).
  Damit wird auch das schwebende Fenster gebaut; ohne die Werkzeuge erscheint das
  Widget stattdessen als Seite im Browser. Tkinter wird unter macOS nicht benutzt.

## Dateien

| Datei | Zweck |
| --- | --- |
| `SKILL.md` | Anleitung für Claude Code: installieren, reparieren, entfernen |
| `files/huddle.pyw` | Das Widget (lokaler Server auf `127.0.0.1:47811`; Windows: Tkinter-Fenster, macOS: Oberfläche als Seite) |
| `files/hook.py` | Leitet Claude-Code-Hook-Ereignisse an das Widget weiter und startet es bei Bedarf |
| `files/install.py` | Trägt die Hooks in `~/.claude/settings.json` ein oder entfernt sie; baut unter macOS das Fenster |
| `files/ui.html` | Die Oberfläche für macOS |
| `files/panel.swift` | Das schwebende Fenster für macOS (wird bei der Installation gebaut) |

Das Widget hört standardmäßig nur auf `127.0.0.1`.
