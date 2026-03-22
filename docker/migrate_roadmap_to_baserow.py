#!/usr/bin/env python3
"""
Mora02 Roadmap → Baserow Migration Script
==========================================
Ausführen auf mora02:
    python3 migrate_roadmap_to_baserow.py          # Normal
    python3 migrate_roadmap_to_baserow.py --clean   # Erst aufräumen, dann neu
"""

import requests
import json
import sys
import getpass

# === KONFIGURATION ===
BASEROW_URL = "http://mora02.local:8085"
DATABASE_TOKEN = "***BASEROW_TOKEN_OLD_REVOKED***"
TABLE_ID = 569

ROW_HEADERS = {
    "Authorization": f"Token {DATABASE_TOKEN}",
    "Content-Type": "application/json"
}

JWT_TOKEN = None
JWT_HEADERS = None


def get_jwt_token():
    global JWT_TOKEN, JWT_HEADERS
    email = input("Baserow Email: ")
    password = getpass.getpass("Baserow Passwort: ")
    r = requests.post(f"{BASEROW_URL}/api/user/token-auth/", json={
        "email": email, "password": password
    })
    if r.status_code != 200:
        print(f"❌ Login fehlgeschlagen: {r.status_code}")
        sys.exit(1)
    JWT_TOKEN = r.json()["access_token"]
    JWT_HEADERS = {
        "Authorization": f"JWT {JWT_TOKEN}",
        "Content-Type": "application/json"
    }
    print("✅ JWT Token erhalten\n")


def clean_table():
    print("\n=== CLEAN: TABELLE LEEREN ===\n")

    # Rows löschen
    print("  Rows löschen...")
    total_deleted = 0
    while True:
        r = requests.get(
            f"{BASEROW_URL}/api/database/rows/table/{TABLE_ID}/?page=1&size=200",
            headers=JWT_HEADERS
        )
        if r.status_code != 200:
            break
        rows = r.json().get("results", [])
        if not rows:
            break
        row_ids = [row["id"] for row in rows]
        dr = requests.post(
            f"{BASEROW_URL}/api/database/rows/table/{TABLE_ID}/batch-delete/",
            headers=JWT_HEADERS, json={"items": row_ids}
        )
        if dr.status_code in (200, 204):
            total_deleted += len(row_ids)
            print(f"    ✅ {len(row_ids)} Rows gelöscht (gesamt: {total_deleted})")
        else:
            # Fallback: einzeln
            for rid in row_ids:
                requests.delete(
                    f"{BASEROW_URL}/api/database/rows/table/{TABLE_ID}/{rid}/",
                    headers=JWT_HEADERS
                )
                total_deleted += 1
            break
    print(f"  → {total_deleted} Rows gelöscht")

    # Fields löschen
    print("\n  Fields löschen...")
    r = requests.get(f"{BASEROW_URL}/api/database/fields/table/{TABLE_ID}/", headers=JWT_HEADERS)
    if r.status_code != 200:
        return
    deleted = 0
    for field in r.json():
        if field.get("primary", False):
            print(f"    ⏭  {field['name']} (primary)")
            continue
        dr = requests.delete(f"{BASEROW_URL}/api/database/fields/{field['id']}/", headers=JWT_HEADERS)
        if dr.status_code in (200, 204):
            deleted += 1
            print(f"    ✅ {field['name']} gelöscht")
        else:
            print(f"    ❌ {field['name']}: {dr.status_code}")
    print(f"  → {deleted} Fields gelöscht\n")


FIELDS_TO_CREATE = [
    {"name": "ap_id", "type": "text"},
    {"name": "title", "type": "text"},
    {"name": "phase", "type": "single_select", "select_options": [
        {"value": "phase_1", "color": "blue"}, {"value": "phase_2", "color": "light-blue"},
        {"value": "phase_3", "color": "cyan"}, {"value": "phase_4", "color": "green"},
        {"value": "phase_5", "color": "light-green"}, {"value": "phase_6", "color": "yellow"},
        {"value": "unplanned", "color": "light-gray"},
    ]},
    {"name": "category", "type": "single_select", "select_options": [
        {"value": "ap", "color": "blue"}, {"value": "tool", "color": "green"},
        {"value": "workflow", "color": "orange"}, {"value": "feature", "color": "purple"},
        {"value": "infra", "color": "red"}, {"value": "idea", "color": "light-gray"},
    ]},
    {"name": "status", "type": "single_select", "select_options": [
        {"value": "backlog", "color": "light-gray"}, {"value": "planned", "color": "blue"},
        {"value": "in_progress", "color": "yellow"}, {"value": "done", "color": "green"},
        {"value": "discarded", "color": "red"},
    ]},
    {"name": "priority", "type": "single_select", "select_options": [
        {"value": "p1", "color": "red"}, {"value": "p2", "color": "orange"},
        {"value": "p3", "color": "light-gray"}, {"value": "idea", "color": "light-blue"},
    ]},
    {"name": "goal", "type": "long_text"},
    {"name": "plan", "type": "long_text"},
    {"name": "result", "type": "long_text"},
    {"name": "issues_solutions", "type": "long_text"},
    {"name": "links", "type": "long_text"},
    {"name": "ports_paths", "type": "long_text"},
    {"name": "doc_path", "type": "text"},
    {"name": "tags", "type": "multiple_select", "select_options": [
        {"value": "docker", "color": "blue"}, {"value": "dify", "color": "purple"},
        {"value": "baserow", "color": "green"}, {"value": "activepieces", "color": "orange"},
        {"value": "comfyui", "color": "red"}, {"value": "llm", "color": "cyan"},
        {"value": "nginx", "color": "light-green"}, {"value": "vpn", "color": "dark-blue"},
        {"value": "backup", "color": "dark-gray"}, {"value": "social_media", "color": "light-orange"},
        {"value": "vision", "color": "light-blue"}, {"value": "scripts", "color": "yellow"},
        {"value": "penpot", "color": "light-purple"}, {"value": "excalidraw", "color": "light-red"},
    ]},
    {"name": "hours_planned", "type": "number", "number_decimal_places": 1},
    {"name": "hours_actual", "type": "number", "number_decimal_places": 1},
    {"name": "created_at", "type": "date", "date_format": "ISO", "date_include_time": False},
    {"name": "completed_at", "type": "date", "date_format": "ISO", "date_include_time": False},
]


def create_fields():
    print("=== FELDER ANLEGEN ===\n")
    resp = requests.get(f"{BASEROW_URL}/api/database/fields/table/{TABLE_ID}/", headers=JWT_HEADERS)
    resp.raise_for_status()
    existing = {f["name"] for f in resp.json()}
    for field_def in FIELDS_TO_CREATE:
        name = field_def["name"]
        if name in existing:
            print(f"  ⏭  {name} existiert bereits")
            continue
        r = requests.post(
            f"{BASEROW_URL}/api/database/fields/table/{TABLE_ID}/",
            headers=JWT_HEADERS, json=field_def
        )
        if r.status_code in (200, 201):
            print(f"  ✅ {name} ({field_def['type']})")
        else:
            print(f"  ❌ {name}: {r.status_code} - {r.text[:200]}")


def get_select_option_map():
    resp = requests.get(f"{BASEROW_URL}/api/database/fields/table/{TABLE_ID}/", headers=JWT_HEADERS)
    resp.raise_for_status()
    m = {}
    for f in resp.json():
        if f["type"] in ("single_select", "multiple_select"):
            m[f["name"]] = {o["value"]: o["id"] for o in f.get("select_options", [])}
    return m


ITEMS = [
    # Phase 1
    {"ap_id": "AP1", "title": "Stack aufräumen & stabilisieren", "phase": "phase_1", "category": "ap", "status": "done", "priority": "p1", "goal": "Docker-Stack bereinigen, alte Container entfernen, stabile Basis schaffen", "result": "Stack aufgeräumt und stabilisiert", "hours_actual": 2, "completed_at": "2025-12-03", "tags": ["docker"], "doc_path": "/opt/mora02/knowledge/archive/202512031205_ap1-cleanup-complete.md"},
    {"ap_id": "AP2", "title": "Dify Multi-Agenten-Plattform", "phase": "phase_1", "category": "ap", "status": "done", "priority": "p1", "goal": "Dify als zentrale AI-Plattform mit Multi-Agent-Setup einrichten", "result": "Dify läuft mit Multi-Agenten-Setup", "hours_actual": 3, "completed_at": "2025-12-05", "tags": ["dify", "llm"], "doc_path": "/opt/mora02/knowledge/archive/202512051130_ap2-dify-multimodel-complete.md"},
    {"ap_id": "AP3", "title": "Baserow Projektzentrum", "phase": "phase_1", "category": "ap", "status": "done", "priority": "p1", "goal": "Baserow als zentrale Projektverwaltung einrichten", "result": "Baserow konfiguriert mit Tabellenstruktur", "hours_actual": 2, "completed_at": "2025-12-09", "tags": ["baserow"]},
    {"ap_id": "AP4", "title": "Activepieces Integration", "phase": "phase_1", "category": "ap", "status": "done", "priority": "p1", "goal": "Activepieces als Workflow-Automation-Engine integrieren", "result": "Activepieces läuft und verbindet Baserow, Dify, ComfyUI", "hours_actual": 3, "completed_at": "2025-12-12", "tags": ["activepieces"], "doc_path": "/opt/mora02/knowledge/archive/202512121704_ap4-activepieces-integration-complete.md"},
    {"ap_id": "AP5", "title": "Asset-Workflow + Reviews", "phase": "phase_1", "category": "ap", "status": "done", "priority": "p1", "goal": "Kompletter Asset-Lifecycle: Erstellung → Review → Finalisierung", "result": "Asset-Workflow mit Review-Loop und Versionierung produktiv", "hours_actual": 7, "completed_at": "2025-12-24", "tags": ["baserow", "activepieces", "dify"], "doc_path": "/opt/mora02/knowledge/archive/2512241640_ap53-asset-workflow-implementation_1_.md"},

    # Phase 2
    {"ap_id": "AP6", "title": "LLM-Modell-Optimierung (Qwen3-14B)", "phase": "phase_2", "category": "ap", "status": "done", "priority": "p1", "goal": "Von 3 LLMs auf ein optimiertes Modell konsolidieren, VRAM freigeben", "result": "Qwen3-14B als Single-LLM (15.5GB VRAM), 17GB frei für ComfyUI", "issues_solutions": "Benchmark nötig. Lösung: Systematischer Vergleich, Qwen3-14B gewann.", "hours_actual": 3, "completed_at": "2025-12-27", "tags": ["llm", "docker"], "ports_paths": "Port 8080 (llama-qwen3), 15.5GB VRAM"},
    {"ap_id": "AP7", "title": "Vision-Integration (Claude API)", "phase": "phase_2", "category": "ap", "status": "done", "priority": "p1", "goal": "Bild-Analyse via Claude Vision API in Dify integrieren", "result": "Claude Vision API funktioniert für Bild-Review und Asset-Tagging", "issues_solutions": "Subject-Swap zu komplex. Lösung: Auf ControlNet verschoben (W-003).", "hours_actual": 4, "completed_at": "2025-12-26", "tags": ["vision", "dify"]},

    # Phase 3
    {"ap_id": "AP8", "title": "ComfyUI API Integration", "phase": "phase_3", "category": "ap", "status": "done", "priority": "p1", "goal": "ComfyUI programmatisch via API ansprechen", "result": "ComfyUI API funktioniert, Workflows via HTTP aufrufbar", "hours_actual": 4, "completed_at": "2025-12-27", "tags": ["comfyui"], "ports_paths": "Port 8188"},
    {"ap_id": "AP8.5", "title": "History API (Skalierbar)", "phase": "phase_3", "category": "ap", "status": "done", "priority": "p1", "goal": "Skalierbare History-API für ComfyUI-Generierungen", "result": "History API läuft", "hours_actual": 2, "completed_at": "2025-12-28", "tags": ["comfyui"]},
    {"ap_id": "AP8.7", "title": "Image Review Loop", "phase": "phase_3", "category": "ap", "status": "done", "priority": "p1", "goal": "Review-Workflow für generierte Bilder", "result": "Image Review Loop produktiv: ComfyUI → WIP → Review → Final", "hours_actual": 5, "completed_at": "2025-12-29", "tags": ["comfyui", "baserow", "nginx"], "doc_path": "/opt/mora02/knowledge/archive/2512291450_ap87-image-review-loop-dokumentation.md", "ports_paths": "nginx 8092: /wip/ und /final/"},

    # Phase 4
    {"ap_id": "AP9", "title": "Tools-Stack (Mixpost, Penpot, Excalidraw)", "phase": "phase_4", "category": "ap", "status": "done", "priority": "p1", "goal": "Kreativ-Tools als Docker-Container", "result": "Penpot (8101), Excalidraw (8102), Mixpost (8100). postgres-tools Cluster.", "hours_actual": 5, "completed_at": "2025-12-31", "tags": ["docker", "penpot", "excalidraw"], "ports_paths": "Penpot 8101, Excalidraw 8102, Mixpost 8100"},
    {"ap_id": "AP10", "title": "System Bot Embedding Fix", "phase": "phase_4", "category": "ap", "status": "done", "priority": "p1", "goal": "Embedding-Probleme im System-Bot beheben", "result": "Ollama Embeddings funktionieren stabil", "hours_actual": 3, "completed_at": "2026-01-23", "tags": ["llm", "dify"], "ports_paths": "Ollama 11434", "doc_path": "/opt/mora02/knowledge/archive/2026-01-23_system-bot-embedding-fix.md"},
    {"ap_id": "AP11", "title": "VPN + mora02.local URLs", "phase": "phase_4", "category": "ap", "status": "done", "priority": "p1", "goal": "WireGuard VPN + lokale DNS für Remote-Zugriff", "result": "WireGuard (51820), 4 Peers, alle Services via mora02.local", "hours_actual": 4, "completed_at": "2026-01-21", "tags": ["vpn"], "ports_paths": "WireGuard 51820, mora02.local → 192.168.178.133"},

    # Phase 5
    {"ap_id": "AP12", "title": "Script-Bot System", "phase": "phase_5", "category": "ap", "status": "done", "priority": "p1", "goal": "HTTP-basierter Script-Runner für Gifer, Typer, Clipper", "result": "Script-Runner (8097): Gifer, Typer, Clipper. Web-UI. Baserow (568).", "hours_actual": 6, "completed_at": "2026-01-24", "tags": ["scripts", "docker", "nginx"], "ports_paths": "script-runner 8097, nginx /script-bot-assets/"},
    {"ap_id": "AP13", "title": "LinkedIn Publishing (DIY)", "phase": "phase_5", "category": "ap", "status": "done", "priority": "p1", "goal": "Direktes LinkedIn-Publishing ohne Postiz/Mixpost", "result": "LinkedIn API via Activepieces. SM_content (557). 6 Dify Tools. Scheduled Publishing.", "issues_solutions": "Postiz/Mixpost scheiterten an LinkedIn OAuth. Lösung: API direkt.", "hours_actual": 8, "completed_at": "2026-01-24", "tags": ["social_media", "activepieces", "dify", "baserow"], "links": "SM_content ID 557\nFlow: idea → draft → review → approved → published", "ports_paths": "nginx /socialmedia/"},
    {"ap_id": "AP14", "title": "Penpot Font Fix", "phase": "phase_5", "category": "ap", "status": "done", "priority": "p2", "goal": "JetBrains Mono in Penpot, Google Fonts deaktivieren", "result": "JetBrains Mono in allen Penpot-Containern.", "completed_at": "2026-01-22", "tags": ["penpot"], "doc_path": "/opt/mora02/knowledge/archive/2501222045_penpot-font-fix.md"},
    {"ap_id": "AP15", "title": "Merkle Präsentation", "phase": "phase_5", "category": "ap", "status": "done", "priority": "p1", "goal": "Creative Factory Konzept bei Arbeitgeber präsentieren", "result": "Konzept präsentiert. Azure Deployment genehmigt. Budget + Team in Aussicht.", "completed_at": "2026-01-22"},

    # Phase 6 (geplant)
    {"ap_id": "AP16", "title": "Social Media Bot Testing", "phase": "phase_6", "category": "ap", "status": "planned", "priority": "p1", "goal": "Kompletten SM-Workflow End-to-End testen", "plan": "Testfälle: Idee/Draft erstellen, Status ändern, Scheduled Publishing, LinkedIn-Post, Email-Reminder.", "hours_planned": 3, "tags": ["social_media", "dify", "activepieces"]},
    {"ap_id": "AP17", "title": "Consolidated Logging", "phase": "phase_6", "category": "ap", "status": "planned", "priority": "p2", "goal": "Zentrales Logging für Monitoring + AI-Training-Daten", "plan": "Loki + Promtail + Grafana. knowledge-api /log/*. JSONL-Schema.", "hours_planned": 4, "tags": ["docker", "scripts"], "ports_paths": "Geplant: Loki 3100, Grafana 3200"},
    {"ap_id": "AP18", "title": "Mobile & Messaging", "phase": "phase_6", "category": "ap", "status": "planned", "priority": "p3", "goal": "Bots unterwegs nutzen (iPhone)", "plan": "Option A: WireGuard + Browser. Option B: Mattermost (Port 8103).", "hours_planned": 5, "tags": ["vpn"], "ports_paths": "Mattermost geplant: 8103"},
    {"ap_id": "AP19", "title": "Landing Page / Dashboard", "phase": "phase_6", "category": "ap", "status": "planned", "priority": "p3", "goal": "Zentrale Übersicht: Status, Links, Stats, Health", "plan": "HTML/JS oder React. knowledge-api /status. nginx.", "hours_planned": 5, "tags": ["nginx", "scripts"]},
    {"ap_id": "AP20", "title": "ComfyUI Advanced Workflows", "phase": "phase_6", "category": "ap", "status": "planned", "priority": "p3", "goal": "Image + Text → Video Pipeline", "plan": "AnimateDiff, SVD, Lipsync. Modelle ~20-50 GB. 17 GB VRAM.", "hours_planned": 10, "tags": ["comfyui"]},

    # Backlog: Workflows
    {"ap_id": "W-001", "title": "Bilderkennung + Baserow Output", "phase": "unplanned", "category": "workflow", "status": "backlog", "priority": "p2", "goal": "Vision API → Beschreibung → Baserow. Asset-Tagging.", "plan": "Claude Vision (AP7). Upload → Vision → Parse → Baserow.", "tags": ["vision", "baserow"], "created_at": "2025-12-28"},
    {"ap_id": "W-002", "title": "Foto → Sketch Conversion", "phase": "unplanned", "category": "workflow", "status": "backlog", "priority": "p2", "goal": "ControlNet Canny Edge für Storyboards", "plan": "Canny/Scribble Preprocessor. Einfach.", "tags": ["comfyui"], "created_at": "2025-12-28"},
    {"ap_id": "W-003", "title": "Image-to-Image Replacement", "phase": "unplanned", "category": "workflow", "status": "backlog", "priority": "p3", "goal": "Subject-Swap. ControlNet + Inpainting.", "plan": "SEHR KOMPLEX. SAM, IP-Adapter, Inpainting.", "tags": ["comfyui"], "created_at": "2025-12-28"},
    {"ap_id": "W-004", "title": "High-End Fotos Juggernaut v6", "phase": "unplanned", "category": "workflow", "status": "backlog", "priority": "p2", "goal": "Fotorealistische Marketing/Produkt/Portrait Bilder", "plan": "Juggernaut XL v6 (~6GB). DPM++ 2M Karras. 4x-UltraSharp.", "tags": ["comfyui"], "created_at": "2025-12-28"},
    {"ap_id": "W-005", "title": "Moodboard → Style Replication", "phase": "unplanned", "category": "workflow", "status": "backlog", "priority": "p2", "goal": "Multi-Image → Style-Analyse → Brand-consistent Output", "plan": "IP-Adapter SDXL. Multi-Image Mode. 3-8 Referenzbilder.", "tags": ["comfyui"], "created_at": "2025-12-28"},

    # Backlog: Tools
    {"ap_id": "T-004", "title": "Matomo/Plausible (Analytics)", "phase": "unplanned", "category": "tool", "status": "backlog", "priority": "p3", "goal": "Privacy-first Analytics", "tags": ["docker"], "created_at": "2025-12-05"},
    {"ap_id": "T-005", "title": "Metabase (Dashboards/BI)", "phase": "unplanned", "category": "tool", "status": "backlog", "priority": "p2", "goal": "Daten aus Baserow visualisieren", "tags": ["docker", "baserow"], "created_at": "2025-12-05"},
    {"ap_id": "T-006", "title": "Mautic (Marketing Automation)", "phase": "unplanned", "category": "tool", "status": "backlog", "priority": "p2", "goal": "Open-source HubSpot: Newsletter, Drip Campaigns", "tags": ["docker"], "created_at": "2025-12-05"},
    {"ap_id": "T-007", "title": "Listmonk (Newsletter)", "phase": "unplanned", "category": "tool", "status": "backlog", "priority": "p3", "goal": "Leichtgewichtige Newsletter-Lösung", "tags": ["docker"], "created_at": "2025-12-05"},
    {"ap_id": "T-008", "title": "Grav / Hugo (Website)", "phase": "unplanned", "category": "tool", "status": "backlog", "priority": "p3", "goal": "CMS oder Static Site Generator", "tags": ["docker", "nginx"], "created_at": "2025-12-08"},
    {"ap_id": "T-009", "title": "PrestaShop (E-Commerce)", "phase": "unplanned", "category": "tool", "status": "backlog", "priority": "p3", "goal": "Self-hosted Shopify-Alternative", "tags": ["docker"], "created_at": "2025-12-08"},
    {"ap_id": "T-010", "title": "Easy!Appointments (Buchung)", "phase": "unplanned", "category": "tool", "status": "backlog", "priority": "p3", "goal": "Terminbuchung, Calendar Sync", "tags": ["docker"], "created_at": "2025-12-08"},
    {"ap_id": "T-012", "title": "Excalidraw Custom Build", "phase": "unplanned", "category": "tool", "status": "backlog", "priority": "p2", "goal": "Lokale Excalidraw mit eigenem Collab-Server", "plan": "Custom Docker Build (REACT_APP_WS_SERVER_URL Build-Time).", "issues_solutions": "React ENV nur Build-Time. Workaround: Externer Collab-Server.", "tags": ["excalidraw", "docker"], "created_at": "2025-12-31"},
    {"ap_id": "T-013", "title": "Flow-Portabilität", "phase": "unplanned", "category": "tool", "status": "backlog", "priority": "p2", "goal": "Activepieces Flows als Shell/Python (Vendor Lock-in)", "plan": "JSON analysieren. Top 3 als Script.", "issues_solutions": "AP-Update → DB-Inkompatibilität (Incident 06.01). Borg half.", "tags": ["activepieces", "scripts"], "created_at": "2026-01-06"},

    # Backlog: Features
    {"ap_id": "F-001", "title": "Systemassistent mit Bash-Zugriff", "phase": "unplanned", "category": "feature", "status": "backlog", "priority": "p2", "goal": "Read-Only Docker Exec", "tags": ["docker", "dify"], "created_at": "2025-12-05"},
    {"ap_id": "F-002", "title": "Auto Systemdaten-Aktualisierung", "phase": "unplanned", "category": "feature", "status": "backlog", "priority": "p2", "goal": "RAG-Refresh der Mora02-Docs", "tags": ["dify", "activepieces"], "created_at": "2025-12-05"},
    {"ap_id": "F-003", "title": "Dify-Baserow-Integration", "phase": "unplanned", "category": "feature", "status": "backlog", "priority": "p2", "goal": "Projektdaten direkt in Dify-Agents", "tags": ["dify", "baserow"], "created_at": "2025-12-05"},
    {"ap_id": "F-004", "title": "Social Media API-Aggregation", "phase": "unplanned", "category": "feature", "status": "backlog", "priority": "p2", "goal": "Performance-Tracking (Likes, Shares)", "tags": ["social_media", "baserow"], "created_at": "2025-12-05"},
    {"ap_id": "F-005", "title": "Conversational Agent Interface", "phase": "unplanned", "category": "feature", "status": "backlog", "priority": "p2", "goal": "Chat ersetzt Activepieces Forms", "tags": ["dify"], "created_at": "2025-12-29"},

    # Backlog: Infra
    {"ap_id": "I-001", "title": "Training-Lab (PyTorch)", "phase": "unplanned", "category": "infra", "status": "backlog", "priority": "p3", "goal": "Fine-Tuning Container", "tags": ["llm", "docker"], "created_at": "2025-12-01"},
    {"ap_id": "I-002", "title": "Blue/Green Deployment", "phase": "unplanned", "category": "infra", "status": "backlog", "priority": "p3", "goal": "Zero-Downtime Updates", "tags": ["docker"], "created_at": "2025-12-01"},
    {"ap_id": "I-004", "title": "SSO (Authentik)", "phase": "unplanned", "category": "infra", "status": "backlog", "priority": "p3", "goal": "Zentrales Login, ab 5-10 User", "tags": ["docker"], "created_at": "2025-12-01"},
    {"ap_id": "I-005", "title": "Image-Management & Updates", "phase": "unplanned", "category": "infra", "status": "backlog", "priority": "p1", "goal": "Diun, Version-Pinning", "tags": ["docker", "backup"], "created_at": "2026-01-06"},

    # Ideen
    {"ap_id": "IDEA-001", "title": "ControlNet Bild-Kontrolle", "phase": "unplanned", "category": "idea", "status": "backlog", "priority": "idea", "goal": "Für W-003 (aus AP7)", "tags": ["comfyui"], "created_at": "2025-12-28"},
    {"ap_id": "IDEA-002", "title": "Video-Generation (Hunyuan)", "phase": "unplanned", "category": "idea", "status": "backlog", "priority": "idea", "goal": "Viel VRAM nötig", "tags": ["comfyui", "llm"], "created_at": "2025-12-28"},
    {"ap_id": "IDEA-003", "title": "Lokale Vision-Modelle", "phase": "unplanned", "category": "idea", "status": "backlog", "priority": "idea", "goal": "Alternative zu Claude Vision API", "tags": ["vision", "llm"], "created_at": "2025-12-28"},
    {"ap_id": "IDEA-004", "title": "Externe Collaborators", "phase": "unplanned", "category": "idea", "status": "backlog", "priority": "idea", "goal": "Guest Access in Baserow", "tags": ["baserow"], "created_at": "2025-12-28"},

    # Archiv
    {"ap_id": "T-001", "title": "Affine (Kollaboration)", "phase": "unplanned", "category": "tool", "status": "discarded", "priority": "p3", "result": "Self-Hosted Image nicht verfügbar", "tags": ["docker"], "created_at": "2025-12-31"},
]


def build_row(item, option_map):
    row = {}
    for key, value in item.items():
        if key in ("phase", "category", "status", "priority"):
            if key in option_map and value in option_map[key]:
                row[key] = option_map[key][value]
        elif key == "tags":
            if "tags" in option_map:
                row["tags"] = [option_map["tags"][t] for t in value if t in option_map["tags"]]
        else:
            row[key] = value
    return row


def insert_rows(option_map):
    print(f"\n=== {len(ITEMS)} ITEMS EINFÜGEN ===\n")
    ok, err = 0, 0
    for item in ITEMS:
        row = build_row(item, option_map)
        r = requests.post(
            f"{BASEROW_URL}/api/database/rows/table/{TABLE_ID}/?user_field_names=true",
            headers=ROW_HEADERS, json=row
        )
        if r.status_code in (200, 201):
            print(f"  ✅ {item['ap_id']}: {item['title']}")
            ok += 1
        else:
            print(f"  ❌ {item['ap_id']}: {r.status_code} - {r.text[:300]}")
            err += 1
    print(f"\n=== ERGEBNIS: {ok} OK, {err} Fehler ===")


def main():
    clean = "--clean" in sys.argv
    print("=" * 60)
    print("  Mora02 Roadmap → Baserow Migration")
    print(f"  Mode: {'CLEAN + Import' if clean else 'Import'}")
    print("=" * 60)
    print(f"\n  Ziel: {BASEROW_URL} / Table {TABLE_ID}")
    print(f"  Items: {len(ITEMS)}\n")

    get_jwt_token()

    try:
        r = requests.get(f"{BASEROW_URL}/api/database/fields/table/{TABLE_ID}/", headers=JWT_HEADERS)
        r.raise_for_status()
        print(f"  Verbindung: ✅\n")
    except Exception as e:
        print(f"  ❌ Verbindung fehlgeschlagen: {e}")
        sys.exit(1)

    if clean:
        confirm = input("  ⚠ CLEAN: Alle Rows + Fields werden gelöscht. Weiter? (yes/no): ")
        if confirm.lower() != "yes":
            print("  Abbruch.")
            sys.exit(0)
        clean_table()

    create_fields()
    option_map = get_select_option_map()
    insert_rows(option_map)

    print("\n" + "=" * 60)
    print("  FERTIG!")
    print(f"  → {BASEROW_URL}/database/112/table/{TABLE_ID}/")
    print("  → Views anlegen: Kanban (status), Filter (phase, priority)")
    print("=" * 60)


if __name__ == "__main__":
    main()
