---
name: agenten-runde
description: Installiert, repariert oder entfernt die "Agenten-Runde" (huddle) auf diesem Windows-Rechner - ein kleines Desktop-Widget, das alle laufenden Claude-Code-Sitzungen als Karten zeigt und Rückfragen/Freigaben direkt im Widget beantworten lässt. Verwenden bei "installiere die Agenten-Runde", "Agenten-Runde einrichten", "huddle installieren", "Widget startet nicht", "Agenten-Runde entfernen".
---

# Agenten-Runde installieren (Windows)

Die Agenten-Runde ist ein eigenständiges Widget für diesen Rechner und dieses
Benutzerkonto. Es besteht aus drei Dateien im Ordner `files/` neben dieser
SKILL.md:

- `huddle.pyw` - das Widget (Tkinter-Fenster + lokaler Server auf `127.0.0.1:47811`)
- `hook.py` - leitet Claude-Code-Hook-Ereignisse an das Widget weiter und startet es bei Bedarf
- `install.py` - trägt die Hooks in `~/.claude/settings.json` ein (legt vorher ein Backup an)

Der Nutzer will keine Befehle selbst eingeben. Führe alle Schritte selbst aus und
frage nur dort nach, wo es unten ausdrücklich steht.

## Schritte

1. **Echtes Python finden.** Der Eintrag unter `...\WindowsApps\python.exe` ist nur
   der Microsoft-Store-Platzhalter und zählt nicht ("Python wurde nicht gefunden").
   Prüfe der Reihe nach: `py -3 -c "import sys; print(sys.executable)"`,
   `where.exe python` (Treffer in `WindowsApps` ignorieren),
   `%LOCALAPPDATA%\Programs\Python\Python3*\python.exe`, `C:\Program Files\Python3*\python.exe`.
   Benötigt wird Python 3.8+ mit Tkinter: `"<python>" -c "import tkinter"` muss ohne Fehler laufen.

2. **Wenn kein passendes Python da ist:** erst den Nutzer fragen, ob Python auf
   diesem Rechner installiert werden darf (es kann ein Firmenserver sein). Bei Ja
   nur für das eigene Benutzerkonto installieren, ohne Adminrechte, z. B.
   `winget install --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements`.
   Falls winget fehlt: Installer von python.org laden und mit
   `/quiet InstallAllUsers=0 PrependPath=0 Include_tcltk=1` ausführen. Bei Nein abbrechen
   und sagen, dass das Widget ohne Python nicht läuft.

3. **Dateien kopieren.** Zielordner `%USERPROFILE%\.claude\huddle` anlegen und
   `huddle.pyw`, `hook.py`, `install.py` aus `files/` hineinkopieren (vorhandene
   überschreiben). Eine vorhandene `config.json` im Zielordner **nicht** anfassen.
   Keine `config.json` von einem anderen Rechner mitkopieren.

4. **Hooks eintragen.** `"<python>" "%USERPROFILE%\.claude\huddle\install.py"` ausführen,
   und zwar genau mit dem Python aus Schritt 1 (dessen voller Pfad landet in den Hooks).
   Ohne `--server`/`--token` - das Widget läuft hier lokal.

5. **Widget starten.** Mit `pythonw.exe` aus demselben Python-Ordner, losgelöst, z. B. in PowerShell:
   `Start-Process "<ordner>\pythonw.exe" -ArgumentList '"<home>\.claude\huddle\huddle.pyw"'`.

6. **Prüfen.** Ein Test-POST muss mit HTTP 200 antworten:
   `Invoke-WebRequest -UseBasicParsing -Method Post -ContentType application/json -Body '{"hook_event_name":"Notification","session_id":"skill-test"}' http://127.0.0.1:47811/event`.
   Danach die Testkarte wieder entfernen (gleicher Aufruf mit `"hook_event_name":"SessionEnd"`).
   Anschließend `~/.claude/settings.json` lesen und bestätigen, dass die acht Hook-Einträge
   auf `huddle/hook.py` mit dem richtigen Python-Pfad zeigen.

7. **Rückmeldung.** Kurz sagen, dass das Widget läuft, und dass die Hooks erst in neu
   gestarteten Claude-Code-Sitzungen greifen. Das Widget startet künftig automatisch
   mit der ersten Sitzung.

## Fehlerbilder

- **"Python wurde nicht gefunden ..." bei jedem Hook:** In den Hooks steht ein Python-Pfad,
  den es nicht gibt (oder der Store-Platzhalter). Schritt 1 und 4 wiederholen.
- **Port 47811 belegt / Widget erscheint nicht:** Auf einem Server mit mehreren angemeldeten
  Benutzern kann nur ein Benutzer gleichzeitig den Port nutzen. Mit
  `Get-NetTCPConnection -LocalPort 47811` prüfen, wem der Prozess gehört, und dem Nutzer
  das Ergebnis sagen, statt fremde Prozesse zu beenden.
- **Rückfragen stehen im Terminal und im Widget:** Gewollt. Man kann an beiden Stellen
  antworten; die erste Antwort gilt, und die Frage verschwindet an der anderen Stelle.

## Entfernen

`"<python>" "%USERPROFILE%\.claude\huddle\install.py" --uninstall`, dann den
`pythonw`-Prozess des Widgets beenden und - nur wenn der Nutzer es möchte - den Ordner
`%USERPROFILE%\.claude\huddle` löschen.

## Hinweise

- Das Widget hört nur auf `127.0.0.1`. Nicht auf `0.0.0.0` umstellen und keine
  Firewall-Regeln anlegen, außer der Nutzer verlangt es ausdrücklich.
- Auf einem gemeinsam genutzten Server können andere dort angemeldete Benutzer
  Ereignisse an `127.0.0.1:47811` schicken (also falsche Karten erzeugen), aber keine
  Freigaben erteilen - die kommen nur per Klick aus dem Widget.
