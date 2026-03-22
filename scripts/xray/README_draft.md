# mora02-xray.py — System-Durchleuchtung für Mora02
Scannt das gesamte Mora02-System und erstellt ein vollständiges Bild der Infrastruktur, der Konfiguration und der potenziellen Sicherheitsrisiken. Das Tool wird verwendet, um Systeme zu auditieren, Abhängigkeiten zu visualisieren und sensible Daten zu identifizieren.

## Quick Start
```bash
python3 mora02-xray.py --base-dir /opt/mora02 --output-dir /opt/mora02/knowledge/x-ray
```
Dieser Befehl scannt das Mora02-System unter `/opt/mora02` und speichert das Ergebnis im Ordner `/opt/mora02/knowledge/x-ray`. Das Ergebnis umfasst eine Dependency-Map, ein Secrets-Audit, ein Service-Inventar, ein Mermaid-Diagramm und ein interaktives HTML-Dashboard.

## What It Does
Das Tool scannt das gesamte Mora02-System und identifiziert:
- **Abhängigkeiten**: Welche Dateien von anderen Dateien referenziert werden (z. B. Pfad-Referenzen in Code).
- **Sensible Daten**: API-Schlüssel, Tokens, Passwörter, Datenbank-URLs und andere geheimen Informationen.
- **Docker-Infrastruktur**: Services, Ports, Volumes, Umgebungsvariablen und Abhängigkeiten zwischen Containern.
- **Baserow-Tabellen**: Identifiziert Tabellen, Felder, und potenziell sensible Daten in Baserow.
- **Activepieces-Flows**: Scannen von Flows und Verbindungen in Activepieces.
- **DB-Hygiene**: Prüft ob Datenbanken existieren, deren Services nicht mehr laufen.

## Parameters
Die folgenden Parameter können über die Kommandozeile gesetzt werden:

| Parameter | Default | Beschreibung |
|---------|---------|-------------|
| `--base-dir` | `/opt/mora02` | Basisverzeichnis des Mora02-Systems |
| `--output-dir` | `/opt/mora02/knowledge/x-ray` | Zielverzeichnis für die Ausgabe |
| `--no-baserow` | `False` | Baserow-Scan deaktivieren |
| `--no-activepieces` | `False` | Activepieces-Scan deaktivieren |
| `--no-dify` | `False` | Dify-Scan deaktivieren |
| `--no-db-hygiene` | `False` | DB-Hygiene-Check deaktivieren |

## Practical Examples
### 1. Standard-Scan
```bash
python3 mora02-xray.py
```
Erstellt ein vollständiges Audit des Systems unter `/opt/mora02` und speichert es im Standard-Ausgabeverzeichnis.

### 2. Ausgabe in einem anderen Verzeichnis
```bash
python3 mora02-xray.py --base-dir /opt/mora02 --output-dir /home/user/xray
```
Nützlich, wenn der Benutzer keine Schreibrechte im Standard-Ausgabeverzeichnis hat.

### 3. Deaktivieren von Baserow-Scan
```bash
python3 mora02-xray.py --no-baserow
```
Wenn Baserow nicht installiert ist oder der Scan nicht gewünscht ist.

### 4. Nur Secrets-Scan durchführen
```bash
python3 mora02-xray.py --no-docker --no-baserow --no-activepieces --no-dify --no-db-hygiene
```
Nützlich, wenn nur die Identifizierung von sensiblen Daten benötigt wird.

## How It Works
Das Tool arbeitet in mehreren Schichten:
1. **Docker Compose-Scan**: Liest `docker-compose.yml`-Dateien und extrahiert Services, Ports, Volumes und Umgebungsvariablen.
2. **.env-Dateien**: Scannen von `.env`, `.env.*`, und anderen Konfigurationsdateien nach sensiblen Daten.
3. **Dateisystem-Scan**: Durchsucht das gesamte System nach Pfad-Referenzen, URLs und sensiblen Daten.
4. **Baserow-Scan**: Verbindet sich mit der Baserow-API und extrahiert Tabellen, Felder und potenziell sensible Daten.
5. **Activepieces-Scan**: Verbindet sich mit der Activepieces-DB und extrahiert Flows und Verbindungen.
6. **DB-Hygiene-Check**: Prüft ob Datenbanken existieren, deren Services nicht mehr laufen.

## Directory Structure
```
/opt/mora02/knowledge/x-ray/
├── x-ray-raw.json              # Rohdaten des Scans
├── x-ray-mermaid.mmd           # Mermaid-Diagramm
├── x-ray-dashboard.html        # Interaktives HTML-Dashboard
├── x-ray-secrets.csv           # Liste der gefundenen Secrets
├── x-ray-dependencies.json     # Dependency-Map
├── x-ray-services.json         # Service-Inventar
├── x-ray-baserow.json          # Baserow-Tabellen
├── x-ray-activepieces.json     # Activepieces-Flows
├── x-ray-dify.json             # Dify-Agents
└── x-ray-errors.txt            # Fehlermeldungen
```

## Dependencies
- **Python-Bibliotheken**: `requests`, `pyyaml`
- **System-Tools**: `docker`, `psql`, `sqlite3`

## Configuration
Die folgenden Variablen können in der Datei `mora02-xray.py` geändert werden:
- `BASE_DIR`: Zeile 30
- `SECRET_PATTERNS`: Zeilen 42–76
- `SKIP_DIRS`: Zeilen 84–95
- `SCAN_EXTENSIONS`: Zeile 100
- `DEPENDENCY_NOISE_PATHS`: Zeile 120–130

## Troubleshooting
### 1. Fehler beim Lesen von `.env`-Dateien
**Problem**: Fehlermeldung wie `Error reading /opt/mora02/docker/.env: [Errno 2] No such file or directory`
**Lösung**: Stellen Sie sicher, dass die Datei `/opt/mora02/docker/.env` existiert und lesbar ist.

### 2. Baserow-Token nicht gefunden
**Problem**: Meldung `Kein Baserow-Token gefunden`
**Lösung**: Legen Sie den Token in `/opt/mora02/config/baserow-token.txt` ab.

### 3. Fehler beim Scannen von Baserow
**Problem**: Fehlermeldung `Baserow scan failed: ...`
**Lösung**: Stellen Sie sicher, dass der Baserow-Container läuft und die URL korrekt ist.

### 4. Fehler beim Scannen von Activepieces
**Problem**: Fehlermeldung `Activepieces SQLite: ...`
**Lösung**: Stellen Sie sicher, dass der Activepieces-Container läuft und die Datei `/opt/mora02/docker/activepieces/.activepieces/database.sqlite` existiert.

## Shell Script Collections
### backup/
- `backup-xray.sh`: Erstellt eine Sicherungskopie der X-Ray-Dateien.
- `backup-secrets.sh`: Erstellt eine Sicherungskopie der Secrets-Dateien.

**Zweck**: Sicherungskopien der X-Ray- und Secrets-Dateien erstellen, um Datenverlust zu vermeiden.

### docker/
- `docker-restart.sh`: Neustart aller Docker-Container.
- `docker-clean.sh`: Löscht temporäre Docker-Dateien.

**Zweck**: Verwaltung der Docker-Infrastruktur.

### system/
- `system-repair.sh`: Prüft und repariert System-Dateien.
- `system-check.sh`: Führt umfassende System-Checks durch.

**Zweck**: Wartung und Prüfung des Systems.