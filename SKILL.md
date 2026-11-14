---
name: agenten-runde
description: Installiert, repariert oder entfernt die "Agenten-Runde" (huddle) auf diesem Rechner (Windows oder macOS) - ein kleines Desktop-Widget, das alle laufenden Claude-Code-Sitzungen als Karten zeigt und Rückfragen/Freigaben direkt im Widget beantworten lässt. Verwenden bei "installiere die Agenten-Runde", "Agenten-Runde einrichten", "huddle installieren", "Widget startet nicht", "Agenten-Runde entfernen".
---

# Agenten-Runde installieren (Windows und macOS)

Die Agenten-Runde ist ein eigenständiges Widget für diesen Rechner und dieses
Benutzerkonto. Die Dateien liegen im Ordner `files/` neben dieser SKILL.md:

- `huddle.pyw` - das Widget (lokaler Server auf `127.0.0.1:47811`; unter Windows ein Tkinter-Fenster, unter macOS liefert es die Oberfläche als Seite aus)
- `hook.py` - leitet Claude-Code-Hook-Ereignisse an das Widget weiter und startet es bei Bedarf
- `install.py` - trägt die Hooks in `~/.claude/settings.json` ein (legt vorher ein Backup an); baut unter macOS zusätzlich das Fenster
- `ui.html` - die Oberfläche für macOS
- `panel.swift` - das kleine schwebende Fenster für macOS (wird bei der Installation zu `AgentenRunde` gebaut)

Der Nutzer will keine Befehle selbst eingeben. Führe alle Schritte selbst aus und
frage nur dort nach, wo es unten ausdrücklich steht.

Zuerst das Betriebssystem feststellen und dann **nur** den passenden Abschnitt ausführen.

## Windows

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

7. **Rückmeldung.** Siehe unten.

## macOS

Unter macOS braucht das Widget kein Tkinter (das in macOS eingebaute Tk ist
unzuverlässig und stürzt teils sofort ab - nicht verwenden, nicht testen).

1. **Python finden.** `/usr/bin/python3 --version` muss eine Version 3.8+ ausgeben.
   Kommt stattdessen der Hinweis auf fehlende Entwicklerwerkzeuge (xcode-select), ist ein
   anderes `python3` (`command -v python3`, Homebrew, python.org) genauso gut.
   Gibt es gar keines: den Nutzer fragen, ob die Xcode-Befehlszeilenwerkzeuge installiert
   werden dürfen (`xcode-select --install` öffnet den Apple-Dialog; der Nutzer muss ihn
   bestätigen). Bei Nein abbrechen.

2. **Dateien kopieren.** Zielordner `~/.claude/huddle` anlegen und `huddle.pyw`, `hook.py`,
   `install.py`, `ui.html`, `panel.swift` aus `files/` hineinkopieren (vorhandene
   überschreiben). Eine vorhandene `config.json` im Zielordner **nicht** anfassen.

3. **Hooks eintragen und Fenster bauen.** `<python3> ~/.claude/huddle/install.py` ausführen
   (ohne `--server`/`--token`). Das Skript baut zuerst das Fenster (`AgentenRunde`,
   dauert einige Sekunden) und trägt dann die Hooks ein. Meldet es "Fenster konnte nicht
   gebaut werden", funktioniert trotzdem alles - das Widget öffnet sich dann als Seite im
   Browser statt als schwebendes Fenster. Dem Nutzer das sagen; mit installierten
   Xcode-Befehlszeilenwerkzeugen lässt sich `install.py` später einfach erneut ausführen.

4. **Widget starten.** Losgelöst, damit es die Sitzung überlebt:
   `nohup <python3> ~/.claude/huddle/huddle.pyw >/dev/null 2>&1 &`

5. **Prüfen.** Ein Test-POST muss mit HTTP 200 antworten:
   `curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d '{"hook_event_name":"Notification","session_id":"skill-test"}' http://127.0.0.1:47811/event`.
   Danach die Testkarte wieder entfernen (gleicher Aufruf mit `"hook_event_name":"SessionEnd"`).
   Mit `pgrep -fl AgentenRunde` prüfen, dass das Fenster läuft. Anschließend
   `~/.claude/settings.json` lesen und bestätigen, dass die acht Hook-Einträge auf
   `huddle/hook.py` zeigen.

6. **Rückmeldung.** Siehe unten. Zusätzlich erwähnen: Beim ersten Klick auf
   "Zum Terminal" fragt macOS einmalig, ob Python das Terminal steuern darf - mit
   "Erlauben" springt das Widget zum richtigen Tab (Terminal und iTerm2), sonst holt es
   nur die Terminal-App nach vorn.

## Rückmeldung (beide Systeme)

Kurz sagen, dass das Widget läuft, und dass die Hooks erst in neu gestarteten
Claude-Code-Sitzungen greifen. Das Widget startet künftig automatisch mit der ersten
Sitzung. Wird das Fenster geschlossen, erscheint es bei der nächsten Eingabe in einer
Sitzung wieder.

## Fehlerbilder

- **"Python wurde nicht gefunden ..." bei jedem Hook (Windows):** In den Hooks steht ein
  Python-Pfad, den es nicht gibt (oder der Store-Platzhalter). Schritt 1 und 4 wiederholen.
- **Port 47811 belegt / Widget erscheint nicht:** Auf einem Rechner mit mehreren angemeldeten
  Benutzern kann nur ein Benutzer gleichzeitig den Port nutzen. Prüfen, wem der Prozess
  gehört (Windows: `Get-NetTCPConnection -LocalPort 47811`, macOS: `lsof -nP -iTCP:47811 -sTCP:LISTEN`),
  und dem Nutzer das Ergebnis sagen, statt fremde Prozesse zu beenden.
- **macOS: Widget öffnet sich im Browser statt als Fenster:** `AgentenRunde` fehlt im
  Ordner `~/.claude/huddle` (Bau fehlgeschlagen). `install.py` erneut ausführen und die
  gemeldete Ursache beheben.
- **macOS: Karten bleiben leer oder reagieren nicht:** `~/.claude/huddle/ui-errors.log`
  lesen - dort stehen Skriptfehler der Oberfläche.
- **macOS: "Zum Terminal" holt nur die App nach vorn:** Die Freigabe fehlt. Unter
  Systemeinstellungen > Datenschutz & Sicherheit > Automation für Python das Terminal erlauben.
- **Eine Karte zeigt etwas anderes als die Sitzung tut:** In `config.json` im
  huddle-Ordner `"debug": true` ergänzen und das Widget neu starten. Dann schreibt es jedes
  eingehende Ereignis nach `events.log` im selben Ordner. Nach der Fehlersuche wieder entfernen.
- **Rückfragen stehen im Terminal und im Widget:** Gewollt. Man kann an beiden Stellen
  antworten; die erste Antwort gilt, und die Frage verschwindet an der anderen Stelle.

## Entfernen

`<python> <huddle-ordner>/install.py --uninstall`, dann das Widget beenden (Windows: den
`pythonw`-Prozess; macOS: das Fenster schließen oder `pkill -f huddle.pyw`) und - nur wenn
der Nutzer es möchte - den Ordner `~/.claude/huddle` löschen.

## Hinweise

- Das Widget hört nur auf `127.0.0.1`. Nicht auf `0.0.0.0` umstellen und keine
  Firewall-Regeln anlegen, außer der Nutzer verlangt es ausdrücklich.
- Die Oberfläche unter macOS (`http://127.0.0.1:47811/`) ist nur von diesem Rechner aus
  erreichbar und nimmt Klicks nur mit einem Schlüssel an, den das Widget bei jedem Start
  neu vergibt. Diese Prüfungen nicht entfernen.
- Auf einem gemeinsam genutzten Rechner können andere dort angemeldete Benutzer
  Ereignisse an `127.0.0.1:47811` schicken (also falsche Karten erzeugen), aber keine
  Freigaben erteilen - die kommen nur per Klick aus dem Widget.
