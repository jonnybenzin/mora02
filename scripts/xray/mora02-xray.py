#!/usr/bin/env python3
"""
mora02-xray.py — System-Durchleuchtung für Mora02
==================================================
Scannt das gesamte Mora02-System und erstellt:
1. Dependency Map (Pfad → wer referenziert ihn)
2. Secrets Audit (wo stehen Keys/Tokens/Passwörter)
3. Service-Inventar (Container, Ports, Volumes, APIs)
4. Mermaid-Diagramm zur Visualisierung
5. Interaktives HTML-Dashboard

Nutzung:
    python3 mora02-xray.py [--base-dir /opt/mora02] [--output-dir /opt/mora02/knowledge/x-ray]

Erfordert: requests, pyyaml
    pip install requests pyyaml --break-system-packages
"""

import os
import re
import sys
import json
import yaml
import glob
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional

# ============================================================
# KONFIGURATION
# ============================================================

BASE_DIR = "/opt/mora02"
TIMESTAMP = datetime.now().strftime("%y%m%d%H%M")

# Patterns für Secret-Detection
SECRET_PATTERNS = [
    (r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']?([A-Za-z0-9_\-\.]{16,})', "API Key"),
    (r'(?i)(secret|secret[_-]?key)\s*[:=]\s*["\']?([A-Za-z0-9_\-\.]{16,})', "Secret Key"),
    (r'(?i)(token|access[_-]?token|bearer)\s*[:=]\s*["\']?([A-Za-z0-9_\-\.]{16,})', "Token"),
    (r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']?([^\s"\']{4,})', "Password"),
    (r'(?i)(database[_-]?url|db[_-]?url|postgres://|mysql://)\s*[:=]?\s*["\']?([^\s"\']+)', "Database URL"),
    (r'(sk-[A-Za-z0-9]{20,})', "OpenAI/Anthropic Key"),
    (r'(ghp_[A-Za-z0-9]{36,})', "GitHub Token"),
    (r'(xoxb-[A-Za-z0-9\-]+)', "Slack Token"),
    (r'(?i)(private[_-]?key|priv[_-]?key)\s*[:=]\s*["\']?([^\s"\']+)', "Private Key"),
    (r'(?i)(auth[_-]?token|authorization)\s*[:=]\s*["\']?([A-Za-z0-9_\-\.]{16,})', "Auth Token"),
    (r'(?i)(webhook[_-]?url|webhook[_-]?secret)\s*[:=]\s*["\']?([^\s"\']+)', "Webhook"),
    (r'(?i)(encrypt[_-]?key|encryption[_-]?key)\s*[:=]\s*["\']?([A-Za-z0-9_\-\.]{16,})', "Encryption Key"),
]

# Pfad-Referenz-Pattern
PATH_PATTERN = re.compile(r'/opt/mora02[/\w\.\-\(\)]*')
URL_PATTERN = re.compile(r'https?://[^\s"\'<>\)]+')
PORT_PATTERN = re.compile(r'(\d{4,5})(?::(\d{4,5}))?')

# Dateien die gescannt werden
SCAN_EXTENSIONS = {
    '.py', '.sh', '.yml', '.yaml', '.md', '.txt', '.env', '.conf',
    '.json', '.toml', '.cfg', '.ini', '.js', '.ts', '.html', '.xml',
    '.service', '.timer', '.nginx', '.config'
}

# Dateien/Ordner die übersprungen werden
SKIP_DIRS = {
    'node_modules', '__pycache__', '.git', 'venv', '.venv',
    'ai_models',  # Zu groß, keine relevanten Configs
    'fine_tuning', 'weights', 'logs',
    'venv_rag',          # Python venv — nur Library-Code
    'x_archiv',          # Archivierte Altdaten
    'chats',             # Changelog-Chats — massig False Positives
    'i18n',              # Open-WebUI Übersetzungsdateien
    'locales',           # Open-WebUI Übersetzungsdateien
    '_old_docker-compose',  # Alte Compose-Dateien
    'dify-new',             # Dify Quellcode — nicht unser Code
    'x-ray',                # Eigene alte Reports
    'compose-snapshots',    # Changelog Compose-Kopien mit Passwörtern
}

SKIP_FILES = {
    '.pyc', '.pyo', '.so', '.o', '.bin', '.gguf', '.safetensors',
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.wav',
    '.zip', '.tar', '.gz', '.bz2',
}

# Dateien die bei Secret-Detection als False Positive gelten
SECRET_FP_PATHS = [
    '.env.example',           # Template-Dateien (Dify etc.)
    '.env.sample',
    'env.example',
    '/tests/',                # Test-Dateien
    '/integration_tests/',
    'plugin_daemon/cwd/',     # Dify Plugin Templates
    'dify-new/',              # Dify Quellcode — nicht unser Code
    'docker/open-webui/',     # Open-WebUI Quellcode
    'docker/ollama/',         # Ollama Quellcode
    'sdks/',                  # SDK Beispiele
    '_old_docker-compose/',   # Alte Compose-Dateien mit Passwörtern
    'knowledge/x-ray/',     # Eigene alte Reports (enthalten Secrets als Text!)
]

# Pfade die bei Dependency-Zählung als Noise markiert werden
# (knowledge-base, changelogs, alte Compose-Dateien referenzieren ALLES)
DEPENDENCY_NOISE_PATHS = [
    'data/knowledge-base/',
    'data/dify/storage/upload_files/',
    'data/dify-new/storage/upload_files/',
    'docker/open_web_ui/uploads/',
    'docker/open-webui/',
    '_old_docker-compose/',
    'docs/changelog/',
    'knowledge/x-ray/',       # Eigene alte Reports nicht mitzählen
    'knowledge/archive/2602130912_',   # Alte xray-raw.json
]


# ============================================================
# SCANNER KLASSEN
# ============================================================

class Finding:
    """Ein einzelner Fund"""
    def __init__(self, category: str, source_file: str, line_num: int,
                 finding_type: str, value: str, context: str = ""):
        self.category = category  # dependency, secret, service
        self.source_file = source_file
        self.line_num = line_num
        self.finding_type = finding_type
        self.value = value
        self.context = context  # Zeile oder Beschreibung

    def __repr__(self):
        return f"[{self.category}] {self.finding_type}: {self.value} @ {self.source_file}:{self.line_num}"


class XRayScanner:
    """Hauptscanner für Mora02"""

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.findings: List[Finding] = []
        self.docker_services: Dict = {}
        self.volume_mounts: List[Dict] = []
        self.port_mappings: List[Dict] = []
        self.env_vars: Dict[str, Dict] = {}
        self.path_references: Dict[str, List[Dict]] = defaultdict(list)
        self.secrets: List[Dict] = []
        self.baserow_tables: List[Dict] = []
        self.activepieces_flows: List[Dict] = []
        self.dify_agents: List[Dict] = []
        self.errors: List[str] = []

    # --------------------------------------------------------
    # Schicht 1: Docker Compose
    # --------------------------------------------------------
    def scan_docker_compose(self):
        """Parse docker-compose.yml für Services, Volumes, Ports"""
        compose_paths = [
            self.base_dir / "docker" / "docker-compose.yml",
            self.base_dir / "docker-compose.yml",
        ]

        for compose_path in compose_paths:
            if not compose_path.exists():
                continue

            print(f"  📦 Scanning: {compose_path}")
            try:
                with open(compose_path) as f:
                    data = yaml.safe_load(f)
            except Exception as e:
                self.errors.append(f"YAML parse error {compose_path}: {e}")
                continue

            if not data or 'services' not in data:
                continue

            for svc_name, svc_config in data.get('services', {}).items():
                service = {
                    'name': svc_name,
                    'image': svc_config.get('image', 'custom-build'),
                    'ports': [],
                    'volumes': [],
                    'environment': {},
                    'depends_on': svc_config.get('depends_on', []),
                    'networks': svc_config.get('networks', []),
                    'deploy': svc_config.get('deploy', {}),
                }

                # Ports
                for port in svc_config.get('ports', []):
                    port_str = str(port)
                    service['ports'].append(port_str)
                    self.port_mappings.append({
                        'service': svc_name,
                        'mapping': port_str,
                        'source': str(compose_path)
                    })

                # Volumes
                for vol in svc_config.get('volumes', []):
                    vol_str = str(vol)
                    service['volumes'].append(vol_str)
                    self.volume_mounts.append({
                        'service': svc_name,
                        'mount': vol_str,
                        'source': str(compose_path)
                    })
                    # Pfad-Referenz erfassen
                    if vol_str.startswith('/'):
                        host_path = vol_str.split(':')[0]
                        self.path_references[host_path].append({
                            'service': svc_name,
                            'type': 'docker-volume',
                            'source': str(compose_path)
                        })

                # Environment
                env = svc_config.get('environment', {})
                if isinstance(env, list):
                    for item in env:
                        if '=' in str(item):
                            k, v = str(item).split('=', 1)
                            service['environment'][k] = v
                elif isinstance(env, dict):
                    service['environment'] = env

                # Env file
                env_file = svc_config.get('env_file', [])
                if isinstance(env_file, str):
                    env_file = [env_file]
                service['env_files'] = env_file

                self.docker_services[svc_name] = service

    # --------------------------------------------------------
    # Schicht 2: .env und Config Files
    # --------------------------------------------------------
    def scan_env_files(self):
        """Scanne .env und andere Config-Dateien"""
        env_paths = list(self.base_dir.rglob('.env'))
        env_paths += list(self.base_dir.rglob('*.env'))
        env_paths += list(self.base_dir.rglob('.env.*'))

        for env_path in env_paths:
            str_env = str(env_path)
            if any(skip in str_env for skip in SKIP_DIRS):
                continue
            # Überspringe .env.example etc. — Templates, keine echten Secrets
            if any(fp in str_env for fp in SECRET_FP_PATHS):
                continue

            print(f"  🔐 Scanning env: {env_path}")
            try:
                with open(env_path) as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if '=' in line:
                            key, _, value = line.partition('=')
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")

                            self.env_vars[key] = {
                                'value_preview': self._mask_secret(value),
                                'value_length': len(value),
                                'source': str(env_path),
                                'line': line_num,
                                'is_secret': self._looks_like_secret(key, value)
                            }

                            if self._looks_like_secret(key, value):
                                self.secrets.append({
                                    'type': 'env_var',
                                    'key': key,
                                    'value_preview': self._mask_secret(value),
                                    'source': str(env_path),
                                    'line': line_num,
                                    'risk': 'HIGH' if len(value) > 10 else 'MEDIUM'
                                })
            except Exception as e:
                self.errors.append(f"Error reading {env_path}: {e}")

    # --------------------------------------------------------
    # Schicht 3: Dateisystem-Scan
    # --------------------------------------------------------
    def scan_filesystem(self):
        """Scanne alle relevanten Dateien nach Pfaden, URLs und Secrets"""
        print(f"  📂 Scanning filesystem under {self.base_dir}...")
        file_count = 0

        for root, dirs, files in os.walk(self.base_dir):
            # Skip-Dirs entfernen
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

            for fname in files:
                fpath = Path(root) / fname
                suffix = fpath.suffix.lower()

                if suffix in SKIP_FILES:
                    continue
                if suffix not in SCAN_EXTENSIONS and fname not in {'.env', 'Dockerfile', 'Makefile'}:
                    continue

                # Dateigröße-Limit (5MB)
                try:
                    if fpath.stat().st_size > 5_000_000:
                        continue
                except:
                    continue

                file_count += 1
                self._scan_file(fpath)

        print(f"    Scanned {file_count} files")

    def _scan_file(self, fpath: Path):
        """Einzelne Datei scannen"""
        try:
            with open(fpath, 'r', errors='ignore') as f:
                lines = f.readlines()
        except Exception:
            return

        str_path = str(fpath)
        rel_path = str_path.replace(str(self.base_dir) + "/", "")
        is_noise = any(n in rel_path for n in DEPENDENCY_NOISE_PATHS)
        is_fp_source = any(fp in str_path for fp in SECRET_FP_PATHS)

        for line_num, line in enumerate(lines, 1):
            # Pfad-Referenzen (mit Noise-Markierung)
            for match in PATH_PATTERN.finditer(line):
                ref_path = match.group(0)
                self.path_references[ref_path].append({
                    'file': str_path,
                    'line': line_num,
                    'type': 'file-reference',
                    'noise': is_noise,
                    'context': line.strip()[:120]
                })

            # Secret-Detection (mit False-Positive-Filter)
            if not is_fp_source:
                for pattern, secret_type in SECRET_PATTERNS:
                    for match in re.finditer(pattern, line):
                        full_match = match.group(0)
                        # Kommentare ignorieren (außer in echten .env)
                        if line.strip().startswith('#') and '.env' not in str_path:
                            continue
                        # Bekannte Platzhalter/False Positives
                        lower = full_match.lower()
                        if any(x in lower for x in [
                            'example', 'placeholder', 'your_', 'changeme',
                            'xxx', 'todo', 'fixme', '<server', '<jonny',
                            '<freund', 'self.secret', 'request.args',
                        ]):
                            continue
                        # Eigenes Script ignorieren
                        if 'mora02-xray' in str_path:
                            continue

                        self.secrets.append({
                            'type': secret_type,
                            'key': full_match[:50],
                            'value_preview': self._mask_secret(full_match),
                            'source': str_path,
                            'line': line_num,
                            'risk': self._assess_risk(str_path, secret_type),
                            'context': line.strip()[:100]
                        })

            # URL-Referenzen
            for match in URL_PATTERN.finditer(line):
                url = match.group(0)
                if 'localhost' in url or 'mora02' in url or '127.0.0.1' in url:
                    self.path_references[url].append({
                        'file': str_path,
                        'line': line_num,
                        'type': 'url-reference',
                        'noise': is_noise,
                        'context': line.strip()[:120]
                    })

    # --------------------------------------------------------
    # Schicht 4: Baserow API
    # --------------------------------------------------------
    def scan_baserow(self, baserow_url: str = "http://localhost:8085",
                     token: str = None):
        """Scanne Baserow — Token reicht nur für Row-CRUD, nicht für
        /api/applications/ (braucht JWT). Tabellen-Discovery über DB."""
        if not token:
            # Token aus .env laden — flexibel nach BASEROW*TOKEN suchen
            env_path = self.base_dir / "docker" / ".env"
            if env_path.exists():
                try:
                    with open(env_path) as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith('#'):
                                continue
                            upper = line.upper()
                            if 'BASEROW' in upper and 'TOKEN' in upper and '=' in line:
                                token = line.split('=', 1)[1].strip().strip('"').strip("'")
                                break
                except:
                    pass

            # Fallback: separates Token-File
            if not token:
                token_file = self.base_dir / "config" / "baserow-token.txt"
                if token_file.exists():
                    try:
                        token = open(token_file).read().strip()
                    except:
                        pass

        if not token:
            print("  ⚠️  Kein Baserow-Token gefunden")
            print("     Hinweis: Token in /opt/mora02/config/baserow-token.txt ablegen")
            return

        print(f"  📊 Scanning Baserow @ {baserow_url}...")
        headers = {
            "Authorization": f"Token {token}",
            "Host": "mora02.local"
        }

        try:
            import requests

            # Tabellen-Discovery über PostgreSQL (Token kann kein /api/applications/)
            known_tables = []
            try:
                result = subprocess.run(
                    ['docker', 'exec', 'postgres-baserow', 'psql', '-U', 'baserow',
                     '-d', 'baserow', '-t', '-A', '-c',
                     "SELECT dt.id, dt.name, ca.name as db_name "
                     "FROM database_table dt "
                     "JOIN database_database dd ON dt.database_id = dd.application_ptr_id "
                     "JOIN core_application ca ON dd.application_ptr_id = ca.id "
                     "WHERE dt.trashed = false ORDER BY dt.id;"],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0 and result.stdout.strip():
                    for line in result.stdout.strip().split('\n'):
                        parts = line.split('|')
                        if len(parts) >= 2:
                            known_tables.append({
                                'id': int(parts[0]),
                                'name': parts[1],
                                'database': parts[2] if len(parts) > 2 else '?'
                            })
                    print(f"    DB-Discovery: {len(known_tables)} Tabellen")
            except Exception as e:
                self.errors.append(f"Baserow DB lookup failed: {e}")
                # Fallback: bekannte IDs aus Dokumentation
                known_tables = [
                    {'id': 548, 'name': 'assets_wip', 'database': 'mora02'},
                    {'id': 553, 'name': 'assets_final', 'database': 'mora02'},
                    {'id': 554, 'name': 'image_generations_wip', 'database': 'mora02'},
                    {'id': 555, 'name': 'images_final', 'database': 'mora02'},
                    {'id': 557, 'name': 'SM_content', 'database': 'mora02'},
                    {'id': 568, 'name': 'script_bot_assets', 'database': 'mora02'},
                ]
                print(f"    Fallback: {len(known_tables)} bekannte Tabellen")

            for table in known_tables:
                table_info = {
                    'id': table['id'],
                    'name': table['name'],
                    'database': table.get('database', '?'),
                    'fields': [],
                    'path_references': [],
                    'url_references': [],
                    'secret_fields': [],
                    'row_count': 0,
                }

                # Felder lesen (Token-Auth funktioniert für Fields)
                try:
                    fields_resp = requests.get(
                        f"{baserow_url}/api/database/fields/table/{table['id']}/",
                        headers=headers, timeout=10
                    )
                    if fields_resp.status_code == 200:
                        fields = fields_resp.json()
                        for field in fields:
                            table_info['fields'].append({
                                'id': field['id'],
                                'name': field['name'],
                                'type': field['type'],
                            })
                            if any(s in field['name'].lower() for s in
                                   ['key', 'token', 'secret', 'password', 'credential', 'auth']):
                                table_info['secret_fields'].append(field['name'])
                except Exception as e:
                    self.errors.append(f"Baserow fields {table['name']}: {e}")

                # Rows Stichprobe (Token-Auth funktioniert für Rows)
                try:
                    rows_resp = requests.get(
                        f"{baserow_url}/api/database/rows/table/{table['id']}/?size=20",
                        headers=headers, timeout=10
                    )
                    if rows_resp.status_code == 200:
                        data = rows_resp.json()
                        table_info['row_count'] = data.get('count', 0)
                        for row in data.get('results', []):
                            for key, value in row.items():
                                if isinstance(value, str):
                                    for m in PATH_PATTERN.finditer(value):
                                        table_info['path_references'].append({
                                            'field': key, 'row_id': row.get('id'),
                                            'path': m.group(0)
                                        })
                                    for m in URL_PATTERN.finditer(value):
                                        if 'localhost' in m.group(0) or 'mora02' in m.group(0):
                                            table_info['url_references'].append({
                                                'field': key, 'row_id': row.get('id'),
                                                'url': m.group(0)
                                            })
                except Exception as e:
                    self.errors.append(f"Baserow rows {table['name']}: {e}")

                self.baserow_tables.append(table_info)

        except ImportError:
            self.errors.append("requests not available — skipping Baserow")
        except Exception as e:
            self.errors.append(f"Baserow scan failed: {e}")

    # --------------------------------------------------------
    # Schicht 5: Activepieces API
    # --------------------------------------------------------
    def scan_activepieces(self, ap_url: str = "http://localhost:8089"):
        """Scanne Activepieces Flows aus SQLite DB (AP nutzt SQLITE3, nicht Postgres)."""
        print(f"  ⚡ Scanning Activepieces (SQLite)...")

        sqlite_path = self.base_dir / "docker" / "activepieces" / ".activepieces" / "database.sqlite"
        if not sqlite_path.exists():
            self.errors.append(f"Activepieces SQLite nicht gefunden: {sqlite_path}")
            return

        try:
            import sqlite3
            con = sqlite3.connect(str(sqlite_path))
            cur = con.cursor()

            # Alle Flows mit neuester Version
            cur.execute("""
                SELECT f.id, f.status, fv.displayName, fv.trigger
                FROM flow f
                JOIN flow_version fv ON f.id = fv.flowId
                WHERE fv.id IN (
                    SELECT id FROM flow_version fv2
                    WHERE fv2.flowId = f.id
                    ORDER BY fv2.updated DESC LIMIT 1
                )
                GROUP BY f.id
                ORDER BY fv.updated DESC
            """)

            for row in cur.fetchall():
                flow_id, status, name, trigger_json = row
                flow_info = {
                    'id': flow_id,
                    'name': name or flow_id,
                    'status': status or '?',
                    'urls': [], 'paths': [], 'secrets': [],
                    'webhook_url': None,
                }

                # Trigger JSON durchsuchen
                if trigger_json:
                    for m in URL_PATTERN.finditer(trigger_json):
                        u = m.group(0)
                        flow_info['urls'].append(u)
                        if 'webhook' in u.lower():
                            flow_info['webhook_url'] = u
                    for m in PATH_PATTERN.finditer(trigger_json):
                        p = m.group(0)
                        if p not in flow_info['paths']:
                            flow_info['paths'].append(p)
                    for pat, stype in SECRET_PATTERNS:
                        for m in re.finditer(pat, trigger_json):
                            fm = m.group(0)
                            if any(x in fm.lower() for x in ['example', 'placeholder', 'your_']):
                                continue
                            flow_info['secrets'].append({
                                'type': stype, 'preview': self._mask_secret(fm)
                            })

                self.activepieces_flows.append(flow_info)

            # Auch app_connection scannen (dort liegen die Auth-Configs)
            try:
                cur.execute("SELECT name, pieceName FROM app_connection")
                for row in cur.fetchall():
                    conn_name, piece = row
                    # Nicht die Werte lesen (verschlüsselt), aber Existenz melden
                    self.activepieces_flows.append({
                        'id': f'conn_{conn_name}',
                        'name': f'[Connection] {conn_name} ({piece})',
                        'status': 'CONNECTION',
                        'urls': [], 'paths': [], 'secrets': [],
                        'webhook_url': None,
                    })
            except:
                pass  # Tabelle existiert evtl. nicht

            con.close()
            print(f"    Gefunden: {len(self.activepieces_flows)} Flows/Connections")

        except Exception as e:
            self.errors.append(f"Activepieces SQLite: {e}")

    # --------------------------------------------------------
    # Bonus: DB-Hygiene-Check
    # --------------------------------------------------------
    def scan_db_hygiene(self):
        """Prüfe ob Datenbanken existieren deren Services nicht mehr laufen."""
        print(f"  🧹 DB-Hygiene-Check...")
        self.orphaned_dbs = []

        # Laufende Service-Namen
        running_services = set(self.docker_services.keys())

        # postgres-tools: alle DBs auflisten
        try:
            result = subprocess.run(
                ['docker', 'exec', 'postgres-tools', 'psql', '-U', 'postgres',
                 '-t', '-A', '-c',
                 "SELECT datname FROM pg_database WHERE datistemplate = false AND datname != 'postgres';"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                for db_name in result.stdout.strip().split('\n'):
                    db_name = db_name.strip()
                    if not db_name:
                        continue
                    # Prüfe ob ein passender Service läuft
                    has_service = any(db_name.lower() in svc.lower() for svc in running_services)
                    if not has_service:
                        self.orphaned_dbs.append({
                            'database': db_name,
                            'container': 'postgres-tools',
                            'note': 'Kein laufender Service gefunden'
                        })
                        print(f"    ⚠️  Verwaiste DB: {db_name} in postgres-tools")
        except Exception as e:
            self.errors.append(f"DB-Hygiene postgres-tools: {e}")

    # --------------------------------------------------------
    # Schicht 6: Dify
    # --------------------------------------------------------
    def scan_dify(self, dify_data_dir: str = None):
        """Scanne Dify Agents aus DB"""
        print(f"  🤖 Scanning Dify...")

        for container in ['postgres-dify-new', 'postgres-dify']:
            try:
                result = subprocess.run(
                    ['docker', 'exec', container, 'psql', '-U', 'dify',
                     '-d', 'dify', '-t', '-A', '-c',
                     "SELECT id, name, mode FROM apps ORDER BY created_at DESC;"],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0 and result.stdout.strip():
                    for line in result.stdout.strip().split('\n'):
                        parts = line.split('|')
                        if len(parts) >= 2:
                            self.dify_agents.append({
                                'id': parts[0],
                                'name': parts[1],
                                'mode': parts[2] if len(parts) > 2 else '?',
                            })
                    print(f"    via {container}: {len(self.dify_agents)} Agents")

                    # Prompts auf Secrets prüfen
                    result2 = subprocess.run(
                        ['docker', 'exec', container, 'psql', '-U', 'dify',
                         '-d', 'dify', '-t', '-A', '-c',
                         "SELECT a.name, ac.pre_prompt FROM apps a "
                         "JOIN app_model_configs ac ON a.app_model_config_id = ac.id;"],
                        capture_output=True, text=True, timeout=15
                    )
                    if result2.returncode == 0 and result2.stdout.strip():
                        for line in result2.stdout.strip().split('\n'):
                            parts = line.split('|', 1)
                            if len(parts) > 1:
                                for pattern, secret_type in SECRET_PATTERNS:
                                    for m in re.finditer(pattern, parts[1]):
                                        self.secrets.append({
                                            'type': f'dify-{secret_type}',
                                            'key': f"Agent: {parts[0]}",
                                            'value_preview': self._mask_secret(m.group(0)),
                                            'source': f"dify-db/{parts[0]}",
                                            'line': 0, 'risk': 'HIGH'
                                        })
                    break
            except:
                continue

        if not self.dify_agents:
            self.errors.append("Dify DB: Keine Agents gefunden")

    # --------------------------------------------------------
    # Hilfsfunktionen
    # --------------------------------------------------------
    def _mask_secret(self, value: str) -> str:
        """Maskiere Secret-Werte für den Report"""
        if len(value) <= 8:
            return "***"
        return value[:4] + "..." + value[-3:]

    def _looks_like_secret(self, key: str, value: str) -> bool:
        """Heuristik: Sieht dieser Env-Var wie ein Secret aus?"""
        secret_keywords = [
            'key', 'secret', 'token', 'password', 'passwd', 'pwd',
            'auth', 'credential', 'private', 'encrypt', 'api_key',
            'apikey', 'bearer', 'webhook'
        ]
        key_lower = key.lower()
        if any(kw in key_lower for kw in secret_keywords):
            if len(value) > 3 and value not in ('true', 'false', 'yes', 'no', '0', '1'):
                return True
        # Wert sieht nach Token aus
        if len(value) > 30 and re.match(r'^[A-Za-z0-9_\-\.]+$', value):
            return True
        return False

    def _assess_risk(self, source: str, secret_type: str) -> str:
        """Risiko-Bewertung für einen Secret-Fund"""
        if '.env' in source:
            return 'HIGH'
        if 'docker-compose' in source:
            return 'HIGH'
        if secret_type in ('API Key', 'Secret Key', 'Private Key', 'Database URL'):
            return 'HIGH'
        if 'docs/' in source or 'system/' in source:
            return 'MEDIUM'  # Könnte Doku sein
        return 'MEDIUM'

    # --------------------------------------------------------
    # Report-Generierung
    # --------------------------------------------------------
    def generate_markdown_report(self) -> str:
        """Generiere den Hauptreport als Markdown"""
        lines = []
        lines.append(f"# Mora02 X-Ray Report")
        lines.append(f"**Generiert:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"**Base:** {self.base_dir}")
        lines.append("")

        # --- Service Inventar ---
        lines.append("## 1. Service-Inventar")
        lines.append("")
        if self.docker_services:
            lines.append(f"**{len(self.docker_services)} Services gefunden:**")
            lines.append("")
            lines.append("| Service | Image | Ports | Volumes |")
            lines.append("|---------|-------|-------|---------|")
            for name, svc in sorted(self.docker_services.items()):
                ports = ", ".join(svc['ports'][:3]) or "—"
                vols = len(svc['volumes'])
                image = svc['image'][:40]
                lines.append(f"| {name} | {image} | {ports} | {vols} mounts |")
            lines.append("")

        # --- Port Map ---
        lines.append("### Port-Zuordnung")
        lines.append("")
        lines.append("| Port | Service | Mapping |")
        lines.append("|------|---------|---------|")
        for pm in sorted(self.port_mappings, key=lambda x: x['mapping']):
            lines.append(f"| {pm['mapping']} | {pm['service']} | {pm['source'].split('/')[-1]} |")
        lines.append("")

        # --- Volume Map ---
        lines.append("### Volume-Mounts (Pfad-Abhängigkeiten)")
        lines.append("")
        lines.append("| Host-Pfad | Container-Pfad | Service |")
        lines.append("|-----------|----------------|---------|")
        for vm in sorted(self.volume_mounts, key=lambda x: x['mount']):
            parts = vm['mount'].split(':')
            host = parts[0] if len(parts) >= 2 else vm['mount']
            container = parts[1] if len(parts) >= 2 else "—"
            lines.append(f"| `{host}` | `{container}` | {vm['service']} |")
        lines.append("")

        # --- Dependency Map ---
        lines.append("## 2. Dependency Map (bereinigt)")
        lines.append("")
        lines.append("Pfade mit mehreren Referenzen (ohne Knowledge-Base, Changelogs, alte Compose):")
        lines.append("")

        # Sortiert nach Anzahl NICHT-Noise Referenzen
        sorted_refs = sorted(self.path_references.items(),
                            key=lambda x: len([r for r in x[1] if not r.get('noise')]),
                            reverse=True)[:30]
        for path, refs in sorted_refs:
            real_refs = [r for r in refs if not r.get('noise')]
            if len(real_refs) < 2:
                continue
            lines.append(f"### `{path}` ({len(real_refs)} Referenzen)")
            for ref in real_refs[:10]:
                if 'service' in ref:
                    lines.append(f"- Docker Volume: **{ref['service']}**")
                elif 'file' in ref:
                    rel_file = ref['file'].replace(str(self.base_dir) + "/", "")
                    lines.append(f"- `{rel_file}` (Z.{ref.get('line', '?')})")
            if len(real_refs) > 10:
                lines.append(f"- ... und {len(real_refs) - 10} weitere")
            lines.append("")

        # --- Secrets Audit ---
        lines.append("## 3. Secrets Audit")
        lines.append("")
        if self.secrets:
            # Deduplizieren
            seen = set()
            unique_secrets = []
            for s in self.secrets:
                key = f"{s['source']}:{s.get('line', 0)}:{s.get('key', '')}"
                if key not in seen:
                    seen.add(key)
                    unique_secrets.append(s)

            high = [s for s in unique_secrets if s.get('risk') == 'HIGH']
            medium = [s for s in unique_secrets if s.get('risk') == 'MEDIUM']

            lines.append(f"**{len(unique_secrets)} potenzielle Secrets gefunden** "
                        f"({len(high)} HIGH, {len(medium)} MEDIUM)")
            lines.append("")

            if high:
                lines.append("### ⚠️ HIGH Risk")
                lines.append("")
                lines.append("| Typ | Wo | Datei | Zeile |")
                lines.append("|----|-----|------|-------|")
                for s in high:
                    rel_source = s['source'].replace(str(self.base_dir) + "/", "")
                    lines.append(f"| {s['type']} | `{s.get('key', '—')[:30]}` | `{rel_source}` | {s.get('line', '—')} |")
                lines.append("")

            if medium:
                lines.append("### 🔶 MEDIUM Risk")
                lines.append("")
                lines.append("| Typ | Wo | Datei | Zeile |")
                lines.append("|----|-----|------|-------|")
                for s in medium[:20]:
                    rel_source = s['source'].replace(str(self.base_dir) + "/", "")
                    lines.append(f"| {s['type']} | `{s.get('key', '—')[:30]}` | `{rel_source}` | {s.get('line', '—')} |")
                if len(medium) > 20:
                    lines.append(f"| ... | {len(medium) - 20} weitere | | |")
                lines.append("")
        else:
            lines.append("Keine Secrets gefunden (oder Scanner konnte nicht zugreifen).")
            lines.append("")

        # --- Env Vars ---
        lines.append("### Env-Variablen Übersicht")
        lines.append("")
        if self.env_vars:
            lines.append(f"**{len(self.env_vars)} Variablen** in .env-Dateien:")
            lines.append("")
            lines.append("| Variable | Secret? | Quelle |")
            lines.append("|----------|---------|--------|")
            for key, info in sorted(self.env_vars.items()):
                is_secret = "🔐 JA" if info['is_secret'] else "—"
                rel_source = info['source'].replace(str(self.base_dir) + "/", "")
                lines.append(f"| `{key}` | {is_secret} | `{rel_source}` |")
            lines.append("")

        # --- Baserow ---
        lines.append("## 4. Baserow-Tabellen")
        lines.append("")
        if self.baserow_tables:
            for table in self.baserow_tables:
                lines.append(f"### {table['name']} (ID: {table['id']})")
                lines.append(f"Database: {table['database']}")
                lines.append(f"Felder: {len(table['fields'])}")
                if table['secret_fields']:
                    lines.append(f"⚠️ Secret-verdächtige Felder: {', '.join(table['secret_fields'])}")
                if table['path_references']:
                    lines.append(f"Pfad-Referenzen: {len(table['path_references'])}")
                    for ref in table['path_references'][:5]:
                        lines.append(f"  - Feld `{ref['field']}`: `{ref['path']}`")
                if table['url_references']:
                    lines.append(f"URL-Referenzen: {len(table['url_references'])}")
                    for ref in table['url_references'][:5]:
                        lines.append(f"  - Feld `{ref['field']}`: `{ref['url']}`")
                lines.append("")
        else:
            lines.append("Kein Baserow-Zugriff (Token fehlt oder Service nicht erreichbar)")
            lines.append("")

        # --- Activepieces ---
        lines.append("## 5. Activepieces-Flows")
        lines.append("")
        if self.activepieces_flows:
            for flow in self.activepieces_flows:
                lines.append(f"### {flow['name']}")
                lines.append(f"Status: {flow.get('status', '?')}")
                if flow.get('urls'):
                    lines.append(f"URLs: {len(flow['urls'])}")
                    for url in flow['urls'][:5]:
                        lines.append(f"  - `{url[:80]}`")
                if flow.get('paths'):
                    lines.append(f"Pfade: {', '.join(set(flow['paths'][:5]))}")
                if flow.get('secrets'):
                    lines.append(f"⚠️ {len(flow['secrets'])} potenzielle Secrets in Flow-Steps!")
                lines.append("")
        else:
            lines.append("Keine Activepieces-Flows gefunden (Auth oder Verbindung fehlgeschlagen)")
            lines.append("")

        # --- Dify ---
        lines.append("## 6. Dify-Agents")
        lines.append("")
        if self.dify_agents:
            lines.append("| Name | Mode | ID |")
            lines.append("|------|------|-----|")
            for agent in self.dify_agents:
                lines.append(f"| {agent['name']} | {agent['mode']} | {agent['id'][:12]}... |")
            lines.append("")
        else:
            lines.append("Keine Dify-Agents gefunden (DB nicht erreichbar)")
            lines.append("")

        # --- Errors ---
        # --- Orphaned DBs ---
        if hasattr(self, 'orphaned_dbs') and self.orphaned_dbs:
            lines.append("## 7. Verwaiste Datenbanken")
            lines.append("")
            lines.append("Datenbanken in PostgreSQL für die kein laufender Service existiert:")
            lines.append("")
            lines.append("| Datenbank | Container | Status |")
            lines.append("|-----------|-----------|--------|")
            for db in self.orphaned_dbs:
                lines.append(f"| `{db['database']}` | {db['container']} | ⚠️ {db['note']} |")
            lines.append("")
            lines.append("**Empfehlung:** Prüfen ob diese DBs noch gebraucht werden. Wenn nicht, mit `DROP DATABASE` entfernen.")
            lines.append("")

        # --- Errors ---
        if self.errors:
            lines.append("## ⚠️ Scanner-Fehler")
            lines.append("")
            for err in self.errors:
                lines.append(f"- {err}")
            lines.append("")

        return "\n".join(lines)

    # --------------------------------------------------------
    # Mermaid-Diagramm
    # --------------------------------------------------------
    def generate_mermaid(self) -> str:
        """Generiere Mermaid-Diagramm mit Subgraphs und Beschreibungen"""
        lines = []
        lines.append("graph LR")
        lines.append("")
        lines.append("    classDef gpu fill:#ff6b6b,stroke:#c92a2a,color:#fff")
        lines.append("    classDef db fill:#4dabf7,stroke:#1864ab,color:#fff")
        lines.append("    classDef app fill:#69db7c,stroke:#2b8a3e,color:#fff")
        lines.append("    classDef tool fill:#ffd43b,stroke:#e67700,color:#000")
        lines.append("    classDef storage fill:#da77f2,stroke:#7c3aed,color:#fff")
        lines.append("")

        gpu, db, app, tool = [], [], [], []
        for name, svc in self.docker_services.items():
            nc = name.replace('-', '_').replace('.', '_')
            ports = svc['ports'][0] if svc['ports'] else ''
            port_label = f":{ports.split(':')[0]}" if ports else ''
            img = svc['image'].split('/')[-1].split(':')[0][:20]

            if any(x in name.lower() for x in ['comfyui', 'llama', 'ollama']):
                gpu.append((nc, name, port_label, img))
            elif any(x in name.lower() for x in ['postgres', 'redis', 'weaviate']):
                db.append((nc, name, port_label, img))
            elif any(x in name.lower() for x in ['nginx', 'script', 'searxng', 'knowledge', 'pilot']):
                tool.append((nc, name, port_label, img))
            else:
                app.append((nc, name, port_label, img))

        # Subgraphs
        if gpu:
            lines.append("    subgraph GPU [\"🔥 GPU Services\"]")
            for nc, name, port, img in gpu:
                lines.append(f"        {nc}[\"{name}{port}<br/><small>{img}</small>\"]:::gpu")
            lines.append("    end")
            lines.append("")

        if db:
            lines.append("    subgraph DBS [\"💾 Databases\"]")
            for nc, name, port, img in db:
                lines.append(f"        {nc}[(\"{name}\")]:::db")
            lines.append("    end")
            lines.append("")

        if app:
            lines.append("    subgraph APPS [\"🚀 Applications\"]")
            for nc, name, port, img in app:
                lines.append(f"        {nc}[\"{name}{port}<br/><small>{img}</small>\"]:::app")
            lines.append("    end")
            lines.append("")

        if tool:
            lines.append("    subgraph TOOLS [\"🔧 Tools & Infra\"]")
            for nc, name, port, img in tool:
                lines.append(f"        {nc}[\"{name}{port}<br/><small>{img}</small>\"]:::tool")
            lines.append("    end")
            lines.append("")

        # Storage-Pfade
        key_paths = set()
        for vm in self.volume_mounts:
            host_path = vm['mount'].split(':')[0]
            if host_path.startswith('/opt/mora02'):
                parts = host_path.replace('/opt/mora02/', '').split('/')
                short = '/'.join(parts[:2]) if len(parts) > 1 else parts[0]
                key_paths.add(short)

        lines.append("    subgraph STORAGE [\"📁 Storage\"]")
        for kp in sorted(key_paths):
            kp_id = kp.replace('/', '_').replace('.', '_').replace('-', '_').replace('(', '').replace(')', '')
            lines.append(f"        {kp_id}[\"/opt/mora02/{kp}/\"]:::storage")
        lines.append("    end")
        lines.append("")

        # Verbindungen: Service → Storage
        for vm in self.volume_mounts:
            host_path = vm['mount'].split(':')[0]
            svc_name = vm['service'].replace('-', '_').replace('.', '_')
            if host_path.startswith('/opt/mora02'):
                parts = host_path.replace('/opt/mora02/', '').split('/')
                short = '/'.join(parts[:2]) if len(parts) > 1 else parts[0]
                kp_id = short.replace('/', '_').replace('.', '_').replace('-', '_').replace('(', '').replace(')', '')
                lines.append(f"    {svc_name} --> {kp_id}")

        lines.append("")

        # Verbindungen: depends_on
        for name, svc in self.docker_services.items():
            name_clean = name.replace('-', '_').replace('.', '_')
            deps = svc.get('depends_on', [])
            if isinstance(deps, dict):
                deps = list(deps.keys())
            for dep in deps:
                dep_clean = dep.replace('-', '_').replace('.', '_')
                lines.append(f"    {name_clean} -.-> {dep_clean}")

        return "\n".join(lines)

    # --------------------------------------------------------
    # Interaktives HTML
    # --------------------------------------------------------
    def generate_html_dashboard(self) -> str:
        """Generiere interaktives HTML-Dashboard"""
        # Daten für JavaScript vorbereiten
        nodes = []
        edges = []
        node_ids = set()

        # Service-Nodes
        for name, svc in self.docker_services.items():
            node_type = 'gpu' if any(x in name.lower() for x in ['comfyui', 'llama', 'ollama']) \
                else 'db' if any(x in name.lower() for x in ['postgres', 'redis', 'weaviate']) \
                else 'app'
            nodes.append({
                'id': f'svc_{name}',
                'label': name,
                'type': node_type,
                'group': 'service',
                'ports': svc.get('ports', []),
                'volumes': len(svc.get('volumes', [])),
            })
            node_ids.add(f'svc_{name}')

        # Pfad-Nodes
        path_groups = defaultdict(set)
        for vm in self.volume_mounts:
            host_path = vm['mount'].split(':')[0]
            if host_path.startswith('/opt/mora02'):
                parts = host_path.replace('/opt/mora02/', '').split('/')
                short = '/'.join(parts[:2]) if len(parts) > 1 else parts[0]
                path_groups[short].add(vm['service'])

        for path_key, services in path_groups.items():
            pid = f'path_{path_key}'.replace('/', '_').replace('.', '_')
            if pid not in node_ids:
                nodes.append({
                    'id': pid,
                    'label': f'/opt/mora02/{path_key}/',
                    'type': 'storage',
                    'group': 'path',
                    'ref_count': len(services),
                })
                node_ids.add(pid)

            for svc in services:
                edges.append({
                    'from': f'svc_{svc}',
                    'to': pid,
                    'type': 'volume'
                })

        # depends_on Edges
        for name, svc in self.docker_services.items():
            deps = svc.get('depends_on', [])
            if isinstance(deps, dict):
                deps = list(deps.keys())
            for dep in deps:
                if f'svc_{dep}' in node_ids:
                    edges.append({
                        'from': f'svc_{name}',
                        'to': f'svc_{dep}',
                        'type': 'depends_on'
                    })

        # Secrets-Summary für Dashboard
        secrets_summary = defaultdict(int)
        for s in self.secrets:
            secrets_summary[s.get('risk', 'UNKNOWN')] += 1

        dashboard_data = {
            'nodes': nodes,
            'edges': edges,
            'secrets_summary': dict(secrets_summary),
            'total_services': len(self.docker_services),
            'total_volumes': len(self.volume_mounts),
            'total_secrets': len(self.secrets),
            'total_env_vars': len(self.env_vars),
            'baserow_tables': len(self.baserow_tables),
            'activepieces_flows': len(self.activepieces_flows),
            'dify_agents': len(self.dify_agents),
            'errors': self.errors,
        }

        html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Mora02 X-Ray Dashboard</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f0f23; color: #ccc; }}
.header {{ background: #1a1a3e; padding: 20px 30px; border-bottom: 2px solid #333; }}
.header h1 {{ color: #69db7c; font-size: 24px; }}
.header .meta {{ color: #888; margin-top: 5px; font-size: 14px; }}
.stats {{ display: flex; gap: 15px; padding: 20px 30px; flex-wrap: wrap; }}
.stat-card {{ background: #1a1a3e; border-radius: 8px; padding: 15px 20px; min-width: 150px; border: 1px solid #333; }}
.stat-card .value {{ font-size: 28px; font-weight: bold; color: #4dabf7; }}
.stat-card .label {{ font-size: 12px; color: #888; margin-top: 4px; }}
.stat-card.danger .value {{ color: #ff6b6b; }}
.stat-card.warning .value {{ color: #ffd43b; }}
.stat-card.success .value {{ color: #69db7c; }}
.main {{ display: flex; height: calc(100vh - 200px); }}
.graph-container {{ flex: 2; position: relative; }}
canvas {{ width: 100%; height: 100%; }}
.sidebar {{ flex: 1; max-width: 400px; overflow-y: auto; background: #1a1a3e; border-left: 1px solid #333; padding: 15px; }}
.sidebar h3 {{ color: #69db7c; margin-bottom: 10px; }}
.node-info {{ background: #252550; padding: 10px; border-radius: 6px; margin-bottom: 8px; cursor: pointer; border: 1px solid transparent; }}
.node-info:hover {{ border-color: #4dabf7; }}
.node-info .name {{ font-weight: bold; color: #fff; }}
.node-info .detail {{ font-size: 12px; color: #888; margin-top: 3px; }}
.legend {{ padding: 10px 30px; display: flex; gap: 20px; }}
.legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 12px; }}
.legend-dot {{ width: 12px; height: 12px; border-radius: 50%; }}
.filter-bar {{ padding: 10px 30px; }}
.filter-bar button {{ background: #252550; color: #ccc; border: 1px solid #444; padding: 6px 14px; border-radius: 4px; cursor: pointer; margin-right: 5px; }}
.filter-bar button:hover, .filter-bar button.active {{ background: #4dabf7; color: #fff; border-color: #4dabf7; }}
#graph {{ width: 100%; height: 100%; }}
</style>
</head>
<body>
<div class="header">
    <h1>Mora02 X-Ray Dashboard</h1>
    <div class="meta">Generiert: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Base: {self.base_dir}</div>
</div>

<div class="stats">
    <div class="stat-card success">
        <div class="value">{len(self.docker_services)}</div>
        <div class="label">Services</div>
    </div>
    <div class="stat-card">
        <div class="value">{len(self.volume_mounts)}</div>
        <div class="label">Volume Mounts</div>
    </div>
    <div class="stat-card danger">
        <div class="value">{len(self.secrets)}</div>
        <div class="label">Secrets gefunden</div>
    </div>
    <div class="stat-card">
        <div class="value">{len(self.env_vars)}</div>
        <div class="label">Env-Variablen</div>
    </div>
    <div class="stat-card warning">
        <div class="value">{len(self.baserow_tables)}</div>
        <div class="label">Baserow Tabellen</div>
    </div>
    <div class="stat-card">
        <div class="value">{len(self.activepieces_flows)}</div>
        <div class="label">AP Flows</div>
    </div>
    <div class="stat-card">
        <div class="value">{len(self.dify_agents)}</div>
        <div class="label">Dify Agents</div>
    </div>
</div>

<div class="legend">
    <div class="legend-item"><div class="legend-dot" style="background:#ff6b6b"></div> GPU Service</div>
    <div class="legend-item"><div class="legend-dot" style="background:#4dabf7"></div> Database</div>
    <div class="legend-item"><div class="legend-dot" style="background:#69db7c"></div> Application</div>
    <div class="legend-item"><div class="legend-dot" style="background:#da77f2"></div> Storage Path</div>
    <div class="legend-item"><div class="legend-dot" style="background:#ffd43b"></div> Tool/Infra</div>
</div>

<div class="filter-bar">
    <button class="active" onclick="filterNodes('all')">Alle</button>
    <button onclick="filterNodes('service')">Services</button>
    <button onclick="filterNodes('path')">Pfade</button>
    <button onclick="filterNodes('secrets')">Secrets</button>
</div>

<div class="main">
    <div class="graph-container">
        <canvas id="graph"></canvas>
    </div>
    <div class="sidebar" id="sidebar">
        <h3>Details</h3>
        <p style="color:#666">Klicke auf einen Node im Graph</p>
    </div>
</div>

<script>
const DATA = {json.dumps(dashboard_data, indent=2)};

// Simple force-directed graph on Canvas
const canvas = document.getElementById('graph');
const ctx = canvas.getContext('2d');
const sidebar = document.getElementById('sidebar');

let width, height;
function resize() {{
    const rect = canvas.parentElement.getBoundingClientRect();
    width = canvas.width = rect.width * window.devicePixelRatio;
    height = canvas.height = rect.height * window.devicePixelRatio;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = rect.height + 'px';
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
}}
resize();
window.addEventListener('resize', resize);

const colorMap = {{
    gpu: '#ff6b6b', db: '#4dabf7', app: '#69db7c',
    storage: '#da77f2', tool: '#ffd43b'
}};

// Initialize node positions
const graphWidth = width / window.devicePixelRatio;
const graphHeight = height / window.devicePixelRatio;

const nodes = DATA.nodes.map((n, i) => ({{
    ...n,
    x: graphWidth/2 + (Math.random() - 0.5) * graphWidth * 0.6,
    y: graphHeight/2 + (Math.random() - 0.5) * graphHeight * 0.6,
    vx: 0, vy: 0,
    radius: n.group === 'path' ? 8 : 14,
    color: colorMap[n.type] || '#69db7c',
    visible: true
}}));

const edges = DATA.edges.map(e => ({{
    ...e,
    sourceNode: nodes.find(n => n.id === e.from),
    targetNode: nodes.find(n => n.id === e.to)
}})).filter(e => e.sourceNode && e.targetNode);

let selectedNode = null;
let dragNode = null;
let mouseX = 0, mouseY = 0;

// Physics
function simulate() {{
    const k = 0.005;  // spring constant
    const repulsion = 3000;
    const damping = 0.85;
    const centerForce = 0.002;

    // Repulsion between all nodes
    for (let i = 0; i < nodes.length; i++) {{
        if (!nodes[i].visible) continue;
        for (let j = i + 1; j < nodes.length; j++) {{
            if (!nodes[j].visible) continue;
            let dx = nodes[j].x - nodes[i].x;
            let dy = nodes[j].y - nodes[i].y;
            let dist = Math.sqrt(dx*dx + dy*dy) || 1;
            let force = repulsion / (dist * dist);
            let fx = (dx / dist) * force;
            let fy = (dy / dist) * force;
            nodes[i].vx -= fx; nodes[i].vy -= fy;
            nodes[j].vx += fx; nodes[j].vy += fy;
        }}
    }}

    // Spring force on edges
    for (const e of edges) {{
        if (!e.sourceNode.visible || !e.targetNode.visible) continue;
        let dx = e.targetNode.x - e.sourceNode.x;
        let dy = e.targetNode.y - e.sourceNode.y;
        let dist = Math.sqrt(dx*dx + dy*dy) || 1;
        let force = (dist - 120) * k;
        let fx = (dx / dist) * force;
        let fy = (dy / dist) * force;
        e.sourceNode.vx += fx; e.sourceNode.vy += fy;
        e.targetNode.vx -= fx; e.targetNode.vy -= fy;
    }}

    // Center gravity + damping
    for (const n of nodes) {{
        if (!n.visible || n === dragNode) continue;
        n.vx += (graphWidth/2 - n.x) * centerForce;
        n.vy += (graphHeight/2 - n.y) * centerForce;
        n.vx *= damping;
        n.vy *= damping;
        n.x += n.vx;
        n.y += n.vy;
        n.x = Math.max(20, Math.min(graphWidth - 20, n.x));
        n.y = Math.max(20, Math.min(graphHeight - 20, n.y));
    }}
}}

function draw() {{
    ctx.clearRect(0, 0, graphWidth, graphHeight);

    // Edges
    for (const e of edges) {{
        if (!e.sourceNode.visible || !e.targetNode.visible) continue;
        ctx.beginPath();
        ctx.moveTo(e.sourceNode.x, e.sourceNode.y);
        ctx.lineTo(e.targetNode.x, e.targetNode.y);
        ctx.strokeStyle = e.type === 'depends_on' ? 'rgba(255,255,255,0.15)' : 'rgba(218,119,242,0.3)';
        ctx.lineWidth = e.type === 'depends_on' ? 1 : 1.5;
        if (e.type === 'depends_on') ctx.setLineDash([4, 4]);
        else ctx.setLineDash([]);
        ctx.stroke();
        ctx.setLineDash([]);
    }}

    // Nodes
    for (const n of nodes) {{
        if (!n.visible) continue;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
        ctx.fillStyle = n === selectedNode ? '#fff' : n.color;
        ctx.fill();
        if (n === selectedNode) {{
            ctx.strokeStyle = n.color;
            ctx.lineWidth = 3;
            ctx.stroke();
        }}

        // Label
        ctx.font = '10px sans-serif';
        ctx.fillStyle = '#ccc';
        ctx.textAlign = 'center';
        ctx.fillText(n.label.replace('svc_', ''), n.x, n.y + n.radius + 14);
    }}

    simulate();
    requestAnimationFrame(draw);
}}

// Interaction
canvas.addEventListener('mousedown', (e) => {{
    const rect = canvas.getBoundingClientRect();
    mouseX = e.clientX - rect.left;
    mouseY = e.clientY - rect.top;
    for (const n of nodes) {{
        if (!n.visible) continue;
        let dx = n.x - mouseX, dy = n.y - mouseY;
        if (Math.sqrt(dx*dx + dy*dy) < n.radius + 5) {{
            dragNode = n;
            selectedNode = n;
            showNodeDetails(n);
            break;
        }}
    }}
}});

canvas.addEventListener('mousemove', (e) => {{
    if (!dragNode) return;
    const rect = canvas.getBoundingClientRect();
    dragNode.x = e.clientX - rect.left;
    dragNode.y = e.clientY - rect.top;
    dragNode.vx = 0;
    dragNode.vy = 0;
}});

canvas.addEventListener('mouseup', () => {{ dragNode = null; }});

function showNodeDetails(n) {{
    let html = '<h3>' + n.label + '</h3>';
    html += '<div class="node-info"><div class="name">Type</div><div class="detail">' + n.type + ' / ' + n.group + '</div></div>';

    if (n.ports && n.ports.length) {{
        html += '<div class="node-info"><div class="name">Ports</div><div class="detail">' + n.ports.join(', ') + '</div></div>';
    }}

    // Connected nodes
    const connected = edges.filter(e => e.from === n.id || e.to === n.id);
    if (connected.length) {{
        html += '<div class="node-info"><div class="name">Verbindungen (' + connected.length + ')</div>';
        for (const e of connected) {{
            const other = e.from === n.id ? e.to : e.from;
            const otherNode = nodes.find(nn => nn.id === other);
            if (otherNode) {{
                html += '<div class="detail">' + e.type + ' → ' + otherNode.label + '</div>';
            }}
        }}
        html += '</div>';
    }}

    sidebar.innerHTML = html;
}}

function filterNodes(type) {{
    document.querySelectorAll('.filter-bar button').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');

    for (const n of nodes) {{
        if (type === 'all') n.visible = true;
        else if (type === 'service') n.visible = n.group === 'service';
        else if (type === 'path') n.visible = n.group === 'path' || edges.some(e => (e.from === n.id || e.to === n.id) && nodes.find(nn => nn.id === (e.from === n.id ? e.to : e.from))?.group === 'path');
        else if (type === 'secrets') n.visible = false; // TODO
    }}
}}

draw();
</script>
</body>
</html>"""
        return html

    # --------------------------------------------------------
    # Statisches Architektur-Diagramm
    # --------------------------------------------------------
    def generate_architecture_html(self) -> str:
        """Generiere statisches Grid-Layout Architektur-Diagramm"""
        ts = datetime.now().strftime('%Y-%m-%d %H:%M')

        # Services kategorisieren
        gpu, db, app, creative, tool = [], [], [], [], []
        for name, svc in sorted(self.docker_services.items()):
            ports = svc['ports'][0] if svc['ports'] else '—'
            vols = len(svc['volumes'])
            img = svc['image'].split('/')[-1].split(':')[0][:25] if svc['image'] != 'custom-build' else 'custom'

            # Bessere Beschreibungen
            nl = name.lower()
            if name == 'llama-qwen3-14b': desc = 'Primäres LLM · ~15.5GB VRAM'
            elif 'llama' in nl: desc = 'Alt. LLM · llama.cpp'
            elif name == 'comfyui': desc = f'Image Generation · {vols} vols'
            elif name == 'ollama': desc = 'Embedding Models'
            elif 'dify-api' in name: desc = 'AI Agent Platform · v1.11'
            elif 'dify-web' in name: desc = 'Dify Web Frontend'
            elif 'dify-worker' in name and 'beat' in name: desc = 'Scheduled Tasks'
            elif 'dify-worker' in name: desc = 'Async Worker'
            elif name == 'baserow': desc = f'Projektdatenbank · {len(self.baserow_tables)} Tab.'
            elif name == 'activepieces': desc = f'Workflow · {len(self.activepieces_flows)} Flows'
            elif name == 'pilot': desc = 'Image Review UI'
            elif name == 'open-webui': desc = 'Chat Interface'
            elif 'penpot-frontend' in name: desc = 'Design Tool · v2.12'
            elif 'penpot-backend' in name: desc = 'Penpot API'
            elif 'penpot-exporter' in name: desc = 'PDF/SVG Export'
            elif name == 'excalidraw': desc = 'Whiteboard'
            elif 'excalidraw-room' in name: desc = 'Collab Server'
            elif 'nginx' in nl: desc = f'Asset Server · {vols} vols'
            elif 'script-runner' in nl: desc = 'HTTP Script API'
            elif 'knowledge' in nl: desc = 'System Knowledge'
            elif 'searxng' in nl: desc = 'Meta-Suchmaschine'
            elif 'sandbox' in nl: desc = 'Code Execution'
            elif 'ssrf' in nl: desc = 'Squid Proxy'
            elif 'plugin' in nl: desc = 'Dify Plugins'
            elif 'redis' in nl: desc = 'Cache & Queue'
            elif 'weaviate' in nl: desc = 'Vector DB · v1.19'
            elif 'postgres-baserow' in nl: desc = 'Baserow DB'
            elif 'postgres-dify' in nl: desc = 'Dify DB'
            elif 'postgres-tools' in nl:
                orphans = [d['database'] for d in getattr(self, 'orphaned_dbs', [])]
                desc = f'Penpot · ⚠️ {", ".join(orphans)}' if orphans else 'Penpot DB'
            else: desc = f'{img} · {vols} vols'

            entry = {'name': name, 'ports': ports, 'vols': vols, 'image': img, 'desc': desc}

            nl = name.lower()
            if any(x in nl for x in ['llama', 'comfyui', 'ollama']):
                gpu.append(entry)
            elif any(x in nl for x in ['postgres', 'redis', 'weaviate']):
                db.append(entry)
            elif any(x in nl for x in ['penpot', 'excalidraw']):
                creative.append(entry)
            elif any(x in nl for x in ['nginx', 'script', 'searxng', 'knowledge', 'sandbox', 'ssrf', 'plugin-daemon']):
                tool.append(entry)
            else:
                app.append(entry)

        # Storage-Pfade aus Volume Mounts
        storage_paths = {}
        for vm in self.volume_mounts:
            hp = vm['mount'].split(':')[0]
            if hp.startswith('/opt/mora02'):
                parts = hp.replace('/opt/mora02/', '').split('/')
                short = parts[0] if parts else hp
                if short not in storage_paths:
                    storage_paths[short] = set()
                storage_paths[short].add(vm['service'])

        # Connections aus depends_on
        connections = {}
        for name, svc in self.docker_services.items():
            deps = svc.get('depends_on', [])
            if isinstance(deps, dict):
                deps = list(deps.keys())
            if deps:
                connections[name] = {'deps': deps}

        def render_cards(items, css_class):
            html = ''
            for e in items:
                html += f'''<div class="svc {css_class}" data-id="{e['name']}">
          <div class="svc-name">{e['name']}</div>
          <div class="svc-port">{e['ports']}</div>
          <div class="svc-desc">{e['desc']}</div>
        </div>\n'''
            return html

        # AP-Connections aus Flows ableiten
        ap_targets = set()
        for flow in self.activepieces_flows:
            for url in flow.get('urls', []):
                if 'baserow' in url: ap_targets.add('baserow')
                if 'dify-api' in url or 'dify:' in url: ap_targets.add('dify-api-new')
                if 'comfyui' in url: ap_targets.add('comfyui')
        if ap_targets:
            connections.setdefault('activepieces', {})['uses'] = list(ap_targets)

        conns_json = json.dumps(connections, default=str)

        return f'''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Mora02 Architektur — {ts}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600&family=Outfit:wght@300;400;600;700&display=swap');
:root {{
  --bg:#0c0e1a;--card:#151729;--border:#1e2240;--text:#c4c9e2;--dim:#6b7194;--bright:#eef0ff;
  --gpu:#ff5757;--gpu-bg:#2a1520;--db:#4d9fff;--db-bg:#152035;
  --app:#3dd68c;--app-bg:#132a20;--tool:#ffb74d;--tool-bg:#2a2215;
  --stor:#b77dff;--stor-bg:#1f1535;
}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Outfit',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
.header{{padding:24px 36px 16px;border-bottom:1px solid var(--border);display:flex;align-items:baseline;gap:14px}}
.header h1{{font-size:20px;font-weight:700;color:var(--bright);letter-spacing:-.5px}}
.header .sub{{font-size:12px;color:var(--dim);font-family:'JetBrains Mono',monospace}}
.legend{{display:flex;gap:20px;padding:12px 36px;border-bottom:1px solid var(--border);font-size:11px}}
.legend-i{{display:flex;align-items:center;gap:5px}}
.legend-d{{width:9px;height:9px;border-radius:2px}}
.diagram{{padding:24px 36px}}
.cat{{margin-bottom:22px}}
.cat-label{{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:8px;padding-left:2px}}
.cat-label.gpu{{color:var(--gpu)}}.cat-label.db{{color:var(--db)}}.cat-label.app{{color:var(--app)}}
.cat-label.tool{{color:var(--tool)}}.cat-label.stor{{color:var(--stor)}}
.cat-grid{{display:flex;flex-wrap:wrap;gap:7px}}
.svc{{border:1px solid var(--border);border-radius:5px;padding:8px 12px;min-width:140px;max-width:190px;cursor:default;transition:all .12s}}
.svc:hover{{transform:translateY(-2px);z-index:10}}
.svc.gpu{{background:var(--gpu-bg);border-color:rgba(255,87,87,.3)}}.svc.gpu:hover{{border-color:var(--gpu);box-shadow:0 4px 16px rgba(255,87,87,.15)}}
.svc.db{{background:var(--db-bg);border-color:rgba(77,159,255,.3)}}.svc.db:hover{{border-color:var(--db);box-shadow:0 4px 16px rgba(77,159,255,.15)}}
.svc.app{{background:var(--app-bg);border-color:rgba(61,214,140,.3)}}.svc.app:hover{{border-color:var(--app);box-shadow:0 4px 16px rgba(61,214,140,.15)}}
.svc.tool{{background:var(--tool-bg);border-color:rgba(255,183,77,.3)}}.svc.tool:hover{{border-color:var(--tool);box-shadow:0 4px 16px rgba(255,183,77,.15)}}
.svc.stor{{background:var(--stor-bg);border-color:rgba(183,125,255,.3)}}.svc.stor:hover{{border-color:var(--stor);box-shadow:0 4px 16px rgba(183,125,255,.15)}}
.svc-name{{font-size:12px;font-weight:600;color:var(--bright);font-family:'JetBrains Mono',monospace;margin-bottom:3px}}
.svc-port{{font-size:10px;font-family:'JetBrains Mono',monospace;margin-bottom:2px}}
.svc.gpu .svc-port{{color:var(--gpu)}}.svc.db .svc-port{{color:var(--db)}}.svc.app .svc-port{{color:var(--app)}}
.svc.tool .svc-port{{color:var(--tool)}}.svc.stor .svc-port{{color:var(--stor)}}
.svc-desc{{font-size:9px;color:var(--dim);line-height:1.3}}
.flow{{display:flex;align-items:center;gap:10px;padding:4px 0 14px;color:var(--dim);font-size:10px;font-family:'JetBrains Mono',monospace}}
.flow-line{{flex:1;height:1px;background:linear-gradient(90deg,transparent,rgba(100,120,180,.25),transparent)}}
.info{{position:fixed;bottom:16px;right:16px;background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px 16px;max-width:340px;font-size:11px;z-index:100;display:none;box-shadow:0 6px 24px rgba(0,0,0,.4)}}
.info.show{{display:block}}
.info h3{{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--bright);margin-bottom:6px}}
.info .cl{{color:var(--dim);line-height:1.7}}
.info .cl span{{color:var(--text)}}
.svc.dimmed{{opacity:.2}}
</style>
</head>
<body>
<div class="header">
  <h1>Mora02 Architektur</h1>
  <span class="sub">{len(self.docker_services)} Services · {len(self.volume_mounts)} Mounts · {ts}</span>
</div>
<div class="legend">
  <div class="legend-i"><div class="legend-d" style="background:var(--gpu)"></div>GPU/AI</div>
  <div class="legend-i"><div class="legend-d" style="background:var(--app)"></div>Apps</div>
  <div class="legend-i"><div class="legend-d" style="background:var(--tool)"></div>Tools</div>
  <div class="legend-i"><div class="legend-d" style="background:var(--db)"></div>DBs</div>
  <div class="legend-i"><div class="legend-d" style="background:var(--stor)"></div>Storage</div>
</div>
<div class="diagram">

<div class="cat"><div class="cat-label gpu">🔥 GPU &amp; AI Models</div>
<div class="cat-grid">{render_cards(gpu, 'gpu')}</div></div>

<div class="flow"><span>API calls / depends_on</span><div class="flow-line"></div></div>

<div class="cat"><div class="cat-label app">🚀 Anwendungen</div>
<div class="cat-grid">{render_cards(app, 'app')}</div></div>

<div class="flow"><span>volumes</span><div class="flow-line"></div></div>

<div class="cat"><div class="cat-label app">🎨 Creative Suite</div>
<div class="cat-grid">{render_cards(creative, 'app')}</div></div>

<div class="flow"><span>depends_on</span><div class="flow-line"></div></div>

<div class="cat"><div class="cat-label tool">🔧 Tools &amp; Infrastruktur</div>
<div class="cat-grid">{render_cards(tool, 'tool')}</div></div>

<div class="flow"><span>persistent data</span><div class="flow-line"></div></div>

<div class="cat"><div class="cat-label db">💾 Datenbanken</div>
<div class="cat-grid">{render_cards(db, 'db')}</div></div>

<div class="flow"><span>volume mounts → filesystem</span><div class="flow-line"></div></div>

<div class="cat"><div class="cat-label stor">📁 Storage · /opt/mora02/</div>
<div class="cat-grid">
{''.join(f'<div class="svc stor" data-id="{k}"><div class="svc-name">{k}/</div><div class="svc-desc">→ {", ".join(sorted(v)[:4])}{"..." if len(v)>4 else ""}</div></div>' for k, v in sorted(storage_paths.items()))}
</div></div>

</div>

<div class="info" id="info"><h3 id="info-n"></h3><div class="cl" id="info-c"></div></div>

<script>
const CONNS={conns_json};
const cards=document.querySelectorAll('.svc');
const info=document.getElementById('info'),infoN=document.getElementById('info-n'),infoC=document.getElementById('info-c');
cards.forEach(c=>{{
  c.addEventListener('mouseenter',()=>{{
    const id=c.dataset.id,cn=CONNS[id];
    infoN.textContent=id;
    let h='';
    if(cn&&cn.deps) h+='<div>⬇ depends_on: <span>'+cn.deps.join(', ')+'</span></div>';
    if(cn&&cn.uses) h+='<div>→ nutzt: <span>'+cn.uses.join(', ')+'</span></div>';
    // Find who depends on this
    const dependants=Object.entries(CONNS).filter(([k,v])=>(v.deps||[]).includes(id)||(v.uses||[]).includes(id)).map(([k])=>k);
    if(dependants.length) h+='<div>⬆ genutzt von: <span>'+dependants.join(', ')+'</span></div>';
    infoC.innerHTML=h||'<div style="color:var(--dim)">Keine Verbindungen</div>';
    info.classList.add('show');
    const related=new Set([id]);
    if(cn) (cn.deps||[]).forEach(d=>related.add(d));
    dependants.forEach(d=>related.add(d));
    cards.forEach(x=>{{
      if(related.has(x.dataset.id)) x.classList.remove('dimmed');
      else x.classList.add('dimmed');
    }});
  }});
  c.addEventListener('mouseleave',()=>{{
    cards.forEach(x=>x.classList.remove('dimmed'));
    info.classList.remove('show');
  }});
}});
</script>
</body>
</html>'''


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='Mora02 X-Ray System Scanner')
    parser.add_argument('--base-dir', default='/opt/mora02', help='Mora02 Basisverzeichnis')
    parser.add_argument('--output-dir', default=None, help='Output-Verzeichnis für Reports')
    parser.add_argument('--baserow-url', default='http://localhost:8085', help='Baserow URL')
    parser.add_argument('--baserow-token', default=None, help='Baserow API Token')
    parser.add_argument('--activepieces-url', default='http://localhost:8089', help='Activepieces URL')
    parser.add_argument('--skip-apis', action='store_true', help='Nur Dateisystem scannen, keine APIs')
    parser.add_argument('--skip-baserow', action='store_true', help='Baserow-Scan überspringen')
    parser.add_argument('--skip-activepieces', action='store_true', help='Activepieces-Scan überspringen')
    parser.add_argument('--skip-dify', action='store_true', help='Dify-Scan überspringen')
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%y%m%d%H%M")

    if args.output_dir is None:
        args.output_dir = f"{args.base_dir}/knowledge/x-ray/{timestamp}"

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Mora02 X-Ray Scanner v2")
    print("=" * 60)
    print(f"  Base: {args.base_dir}")
    print(f"  Output: {args.output_dir}")
    print("")

    scanner = XRayScanner(args.base_dir)

    # Schicht 1: Docker
    print("📦 Schicht 1: Docker Compose...")
    scanner.scan_docker_compose()
    print(f"   → {len(scanner.docker_services)} Services, {len(scanner.volume_mounts)} Mounts")

    # Schicht 2: Env Files
    print("🔐 Schicht 2: Env & Config Files...")
    scanner.scan_env_files()
    print(f"   → {len(scanner.env_vars)} Variablen")

    # Schicht 3: Filesystem
    print("📂 Schicht 3: Filesystem-Scan...")
    scanner.scan_filesystem()
    print(f"   → {len(scanner.path_references)} unique Pfade, {len(scanner.secrets)} Secrets")

    if not args.skip_apis:
        # Schicht 4: Baserow
        if not args.skip_baserow:
            print("📊 Schicht 4: Baserow...")
            scanner.scan_baserow(args.baserow_url, args.baserow_token)
            print(f"   → {len(scanner.baserow_tables)} Tabellen")

        # Schicht 5: Activepieces
        if not args.skip_activepieces:
            print("⚡ Schicht 5: Activepieces...")
            scanner.scan_activepieces(args.activepieces_url)
            print(f"   → {len(scanner.activepieces_flows)} Flows")

        # Schicht 6: Dify
        if not args.skip_dify:
            print("🤖 Schicht 6: Dify...")
            scanner.scan_dify()
            print(f"   → {len(scanner.dify_agents)} Agents")

        # Bonus: DB-Hygiene
        print("🧹 Schicht 7: DB-Hygiene...")
        scanner.scan_db_hygiene()
        if hasattr(scanner, 'orphaned_dbs') and scanner.orphaned_dbs:
            print(f"   → {len(scanner.orphaned_dbs)} verwaiste DBs")

    # Reports generieren
    print("")
    print("📝 Generiere Reports...")

    # 1. Markdown Report
    md_path = output_dir / "xray-report.md"
    with open(md_path, 'w') as f:
        f.write(scanner.generate_markdown_report())
    print(f"   ✅ {md_path}")

    # 2. Mermaid Diagramm
    mermaid_path = output_dir / "xray-dependencies.mermaid"
    with open(mermaid_path, 'w') as f:
        f.write(scanner.generate_mermaid())
    print(f"   ✅ {mermaid_path}")

    # 3. HTML Dashboard (Force-Directed)
    html_path = output_dir / "xray-dashboard.html"
    with open(html_path, 'w') as f:
        f.write(scanner.generate_html_dashboard())
    print(f"   ✅ {html_path}")

    # 4. Architektur-Diagramm (Statisches Grid)
    arch_path = output_dir / "xray-architektur.html"
    with open(arch_path, 'w') as f:
        f.write(scanner.generate_architecture_html())
    print(f"   ✅ {arch_path}")

    # 5. Raw JSON (für spätere Verarbeitung)
    json_path = output_dir / "xray-raw.json"
    raw_data = {
        'timestamp': datetime.now().isoformat(),
        'base_dir': str(scanner.base_dir),
        'services': scanner.docker_services,
        'volume_mounts': scanner.volume_mounts,
        'port_mappings': scanner.port_mappings,
        'env_vars': {k: {**v, 'value_preview': v['value_preview']} for k, v in scanner.env_vars.items()},
        'secrets_count': len(scanner.secrets),
        'baserow_tables': [{'id': t['id'], 'name': t['name'], 'fields_count': len(t['fields'])} for t in scanner.baserow_tables],
        'activepieces_flows': [{'id': f['id'], 'name': f['name']} for f in scanner.activepieces_flows],
        'dify_agents': scanner.dify_agents,
        'errors': scanner.errors,
    }
    with open(json_path, 'w') as f:
        json.dump(raw_data, f, indent=2, default=str)
    print(f"   ✅ {json_path}")

    print("")
    print("=" * 60)
    print("  ✅ X-Ray komplett!")
    print(f"  {len(scanner.docker_services)} Services | {len(scanner.secrets)} Secrets | {len(scanner.errors)} Errors")
    print(f"  HTML Dashboard: file://{html_path}")
    print("=" * 60)

    if scanner.errors:
        print("")
        print("⚠️  Fehler aufgetreten:")
        for err in scanner.errors:
            print(f"  - {err}")


if __name__ == '__main__':
    main()
