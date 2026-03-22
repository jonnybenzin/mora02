#!/usr/bin/env python3
"""
Mora02 Knowledge API - Extended v4.0
Wrapper für SYNC, Perplexity Search, Claude Vision, Session Summaries

Endpoints:
  POST /sync         - Knowledge Base aktualisieren + Dify Upload
  GET  /status       - Letzten Sync-Status abrufen
  GET  /health       - Health Check
  GET  /docs         - Dokumentenliste
  POST /perplexity   - Web-Suche via Perplexity
  POST /vision       - Bildanalyse via Claude
  POST /ask-claude   - Text-Anfrage via Claude
  POST /session-done - Session Summary generieren
  POST /export-sessions - Sessions zu Knowledge Base exportieren
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import subprocess
import os
import requests as http_requests
from datetime import datetime
import glob

app = Flask(__name__)
CORS(app)

# =============================================================================
# CONFIGURATION
# =============================================================================

STATUS_FILE = "/opt/mora02/volumes/knowledge-sync-status.txt"
SYNC_SCRIPT = "/opt/mora02/scripts/system/update-knowledge-base.sh"
KNOWLEDGE_DIR = "/opt/mora02/volumes/knowledge-base"
KNOWLEDGE_LATEST = "/opt/mora02/volumes/knowledge-base/mora02-knowledge-latest.md"

# Session Summary Scripts
SESSION_SUMMARY_SCRIPT = "/opt/mora02/scripts/system/generate-session-summary.py"
SESSION_EXPORT_SCRIPT = "/opt/mora02/scripts/system/export-sessions-to-knowledge.py"

# Database config for session scripts (uses host.docker.internal to reach host's exposed port)
DB_HOST = os.getenv("POSTGRES_HOST", "postgres-dify-new")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")

# API Keys
PERPLEXITY_KEY = "***PERPLEXITY_API_KEY_OLD_REVOKED***"
CLAUDE_KEY = "***ANTHROPIC_API_KEY_OLD_REVOKED***"

# Dify Knowledge Base Configuration
DIFY_API_URL = "http://dify-api-new:5001/v1"
DIFY_DATASET_KEY = "dataset-NN4tYOsMTZAhidfVpgPLS2Rb"
DIFY_DATASET_ID = "231ed0da-47a6-4a39-b05f-0eb2ad4b5d54"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def read_status():
    """Liest den aktuellen Sync-Status."""
    try:
        with open(STATUS_FILE, 'r') as f:
            lines = f.readlines()
            status = {}
            for line in lines:
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    status[key] = value
            return status
    except FileNotFoundError:
        return {"LAST_SYNC": "never", "LAST_SYNC_READABLE": "Never synchronized"}


def get_dify_documents():
    """Holt alle Dokumente aus der Dify Knowledge Base."""
    try:
        response = http_requests.get(
            f"{DIFY_API_URL}/datasets/{DIFY_DATASET_ID}/documents",
            headers={"Authorization": f"Bearer {DIFY_DATASET_KEY}"},
            timeout=10
        )
        if response.status_code == 200:
            return response.json().get('data', [])
        return []
    except Exception as e:
        print(f"Error getting Dify documents: {e}")
        return []


def delete_dify_document(document_id):
    """Löscht ein Dokument aus der Dify Knowledge Base."""
    try:
        response = http_requests.delete(
            f"{DIFY_API_URL}/datasets/{DIFY_DATASET_ID}/documents/{document_id}",
            headers={"Authorization": f"Bearer {DIFY_DATASET_KEY}"},
            timeout=10
        )
        return response.status_code == 200 or response.status_code == 204
    except Exception as e:
        print(f"Error deleting Dify document: {e}")
        return False


def upload_to_dify(filepath):
    """
    Lädt ein neues Dokument in die Dify Knowledge Base hoch.
    Verwendet create_by_file Endpoint.
    """
    try:
        filename = os.path.basename(filepath)
        
        with open(filepath, 'rb') as f:
            files = {
                'file': (filename, f, 'text/markdown')
            }
            import json
            data = {
                'data': json.dumps({
                    'indexing_technique': 'high_quality',
                    'process_rule': {'mode': 'automatic'}
                })
            }
            
            response = http_requests.post(
                f"{DIFY_API_URL}/datasets/{DIFY_DATASET_ID}/document/create_by_file",
                headers={"Authorization": f"Bearer {DIFY_DATASET_KEY}"},
                files=files,
                data=data,
                timeout=60
            )
        
        if response.status_code == 200 or response.status_code == 201:
            result = response.json()
            return {
                "success": True,
                "document": result.get('document', {}),
                "batch": result.get('batch', '')
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}",
                "details": response.text[:500]
            }
    except Exception as e:
        return {"success": False, "error": str(e)}


def sync_to_dify():
    """
    Synchronisiert die lokale Knowledge Base mit Dify:
    1. Löscht alle alten mora02-knowledge-*.md Dokumente
    2. Lädt das neueste Dokument hoch
    """
    results = {
        "deleted": [],
        "uploaded": None,
        "errors": []
    }
    
    existing_docs = get_dify_documents()
    for doc in existing_docs:
        doc_name = doc.get('name', '')
        doc_id = doc.get('id', '')
        if doc_name.startswith('mora02-knowledge') and doc_id:
            if delete_dify_document(doc_id):
                results["deleted"].append(doc_name)
            else:
                results["errors"].append(f"Failed to delete: {doc_name}")
    
    if os.path.isfile(KNOWLEDGE_LATEST):
        actual_file = os.path.realpath(KNOWLEDGE_LATEST)
        upload_result = upload_to_dify(actual_file)
        
        if upload_result["success"]:
            results["uploaded"] = {
                "file": os.path.basename(actual_file),
                "document_id": upload_result.get("document", {}).get("id", ""),
                "batch": upload_result.get("batch", "")
            }
        else:
            results["errors"].append(f"Upload failed: {upload_result.get('error', 'Unknown')}")
    else:
        results["errors"].append(f"Knowledge file not found: {KNOWLEDGE_LATEST}")
    
    return results


def run_python_script(script_path, args=None, env_extras=None):
    """
    Führt ein Python-Script aus mit optionalen Argumenten und Umgebungsvariablen.
    """
    if not os.path.isfile(script_path):
        return {
            "success": False,
            "error": f"Script not found: {script_path}"
        }
    
    cmd = ["python3", script_path]
    if args:
        cmd.extend(args)
    
    # Environment mit DB-Konfiguration
    env = os.environ.copy()
    env["POSTGRES_HOST"] = DB_HOST
    env["POSTGRES_PORT"] = DB_PORT
    env["POSTGRES_DB"] = "dify"
    env["POSTGRES_USER"] = "dify"
    env["POSTGRES_PASSWORD"] = "dify_secure_password"
    
    if env_extras:
        env.update(env_extras)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )
        
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Script timeout (>120s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# =============================================================================
# CORE ENDPOINTS
# =============================================================================

@app.route('/health', methods=['GET'])
def health():
    """Health Check Endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "mora02-knowledge-api",
        "version": "4.0",
        "endpoints": ["/sync", "/status", "/docs", "/perplexity", "/vision", "/ask-claude", "/session-done", "/export-sessions"],
        "dify_dataset": DIFY_DATASET_ID,
        "timestamp": datetime.now().isoformat()
    })


@app.route('/status', methods=['GET'])
def status():
    """Gibt den aktuellen Sync-Status zurück."""
    sync_status = read_status()
    return jsonify({
        "last_sync": sync_status.get("LAST_SYNC_READABLE", "unknown"),
        "last_sync_iso": sync_status.get("LAST_SYNC", "never"),
        "docs_count": sync_status.get("DOCS_COUNT", "0"),
        "container_count": sync_status.get("CONTAINER_COUNT", "0"),
        "output_file": sync_status.get("OUTPUT_FILE", ""),
        "dify_dataset_id": DIFY_DATASET_ID
    })


@app.route('/sync', methods=['POST'])
def sync():
    """
    Führt das Knowledge-Update durch:
    1. Lokales Script ausführen (generiert neue .md Datei)
    2. Alte Dokumente in Dify löschen
    3. Neues Dokument in Dify hochladen
    """
    script_result = None
    dify_result = None
    
    try:
        if not os.path.isfile(SYNC_SCRIPT):
            return jsonify({
                "status": "error",
                "message": f"Sync script not found: {SYNC_SCRIPT}"
            }), 500
        
        result = subprocess.run(
            ['/bin/bash', SYNC_SCRIPT],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            return jsonify({
                "status": "error",
                "phase": "local_sync",
                "message": "Sync script failed",
                "returncode": result.returncode,
                "stderr": result.stderr[-500:] if result.stderr else "",
                "stdout": result.stdout[-500:] if result.stdout else ""
            }), 500
        
        script_result = {
            "success": True,
            "output": result.stdout[-500:] if result.stdout else ""
        }
        
        dify_result = sync_to_dify()
        sync_status = read_status()
        has_errors = len(dify_result.get("errors", [])) > 0
        
        return jsonify({
            "status": "ok" if not has_errors else "partial",
            "message": "Knowledge Base updated" + (" (with warnings)" if has_errors else ""),
            "timestamp": datetime.now().isoformat(),
            "local_sync": {
                "docs_count": sync_status.get("DOCS_COUNT", "0"),
                "container_count": sync_status.get("CONTAINER_COUNT", "0"),
                "output_file": sync_status.get("OUTPUT_FILE", "")
            },
            "dify_sync": {
                "deleted_documents": dify_result.get("deleted", []),
                "uploaded_document": dify_result.get("uploaded"),
                "errors": dify_result.get("errors", [])
            }
        })
            
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "phase": "local_sync", "message": "Sync script timeout (>60s)"}), 504
    except Exception as e:
        return jsonify({
            "status": "error", 
            "message": str(e),
            "script_result": script_result,
            "dify_result": dify_result
        }), 500


@app.route('/docs', methods=['GET'])
def list_docs():
    """Listet verfügbare Knowledge-Dokumente auf."""
    docs_dir = "/opt/mora02/knowledge/handbook"
    try:
        files = []
        for f in os.listdir(docs_dir):
            if f.endswith('.md'):
                filepath = os.path.join(docs_dir, f)
                stat = os.stat(filepath)
                files.append({
                    "name": f,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        files.sort(key=lambda x: x['modified'], reverse=True)
        return jsonify({"count": len(files), "docs": files[:20]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# SESSION SUMMARY ENDPOINTS
# =============================================================================

@app.route('/session-done', methods=['POST'])
def session_done():
    """
    Generates a session summary for a specific conversation.
    
    Input JSON:
      {"conversation_id": "uuid-of-conversation"}
    
    Or without conversation_id to process all unprocessed conversations.
    """
    try:
        data = request.get_json(silent=True) or {}
        conversation_id = data.get('conversation_id', '')
        
        # Build arguments
        args = []
        if conversation_id:
            args.extend(['-c', conversation_id])
        
        # Run the script
        result = run_python_script(SESSION_SUMMARY_SCRIPT, args)
        
        if result["success"]:
            # Parse output for summary info
            stdout = result.get("stdout", "")
            
            return jsonify({
                "status": "ok",
                "message": "Session summary generated",
                "conversation_id": conversation_id or "all unprocessed",
                "output": stdout[-1000:] if stdout else "",
                "timestamp": datetime.now().isoformat()
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to generate session summary",
                "error": result.get("error", ""),
                "stderr": result.get("stderr", "")[-500:],
                "stdout": result.get("stdout", "")[-500:]
            }), 500
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/export-sessions', methods=['POST'])
def export_sessions():
    """
    Exports session summaries to a Knowledge Base document.
    
    Input JSON (optional):
      {"last": 30}      - Number of recent sessions (default: 30)
      {"since": "2026-01-01"}  - Export since date
      {"all": true}     - Export all sessions
    """
    try:
        data = request.get_json(silent=True) or {}
        
        # Build arguments
        args = []
        if data.get('all'):
            args.append('--all')
        elif data.get('since'):
            args.extend(['--since', data['since']])
        elif data.get('last'):
            args.extend(['--last', str(data['last'])])
        
        # Run the script
        result = run_python_script(SESSION_EXPORT_SCRIPT, args)
        
        if result["success"]:
            output_file = "/opt/mora02/volumes/knowledge-base/mora02-sessions-knowledge.md"
            file_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
            
            return jsonify({
                "status": "ok",
                "message": "Sessions exported to Knowledge Base",
                "output_file": output_file,
                "file_size": file_size,
                "output": result.get("stdout", "")[-500:],
                "timestamp": datetime.now().isoformat()
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to export sessions",
                "error": result.get("error", ""),
                "stderr": result.get("stderr", "")[-500:]
            }), 500
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# PERPLEXITY SEARCH WRAPPER
# =============================================================================

@app.route('/perplexity', methods=['POST'])
def perplexity_search():
    """
    Perplexity Search Wrapper.
    
    Input JSON:
      {"query": "Your search query"}
    
    Or query parameter:
      POST /perplexity?q=Your+search+query
    """
    try:
        data = request.get_json(silent=True) or {}
        query = data.get('query') or request.args.get('q', '')
        
        if not query:
            return jsonify({
                "status": "error",
                "message": "Parameter 'query' required",
                "usage": "POST /perplexity with JSON {'query': '...'} or ?q=..."
            }), 400
        
        response = http_requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {PERPLEXITY_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "sonar",
                "messages": [{"role": "user", "content": query}]
            },
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            answer = ""
            if 'choices' in result and len(result['choices']) > 0:
                answer = result['choices'][0].get('message', {}).get('content', '')
            
            return jsonify({
                "status": "ok",
                "query": query,
                "answer": answer,
                "citations": result.get('citations', []),
                "model": result.get('model', 'sonar'),
                "raw_response": result
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Perplexity API error: {response.status_code}",
                "details": response.text[:500]
            }), response.status_code
            
    except http_requests.Timeout:
        return jsonify({"status": "error", "message": "Perplexity timeout (>30s)"}), 504
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# CLAUDE VISION WRAPPER
# =============================================================================

@app.route('/vision', methods=['POST'])
def vision_analyze():
    """
    Claude Vision Wrapper for image analysis.
    
    Input JSON:
      {
        "image": "base64-encoded-image-data",
        "prompt": "Optional: Specific question about the image",
        "media_type": "Optional: image/png, image/jpeg, etc."
      }
    
    Or for URL-based images:
      {
        "image_url": "https://example.com/image.png",
        "prompt": "Optional: Specific question"
      }
    """
    try:
        data = request.get_json(silent=True) or {}
        
        image_base64 = data.get('image', '')
        image_url = data.get('image_url', '')
        prompt = data.get('prompt', 'Describe this image in detail. If it is a screenshot with an error, explain the problem and possible solutions.')
        media_type = data.get('media_type', 'image/png')
        
        if not image_base64 and not image_url:
            return jsonify({
                "status": "error",
                "message": "Parameter 'image' (base64) or 'image_url' required",
                "usage": "POST /vision with JSON {'image': 'base64...'} or {'image_url': 'https://...'}"
            }), 400
        
        if image_base64:
            image_content = {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_base64
                }
            }
        else:
            image_content = {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": image_url
                }
            }
        
        response = http_requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1024,
                "messages": [{
                    "role": "user",
                    "content": [
                        image_content,
                        {"type": "text", "text": prompt}
                    ]
                }]
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            answer = ""
            if 'content' in result and len(result['content']) > 0:
                answer = result['content'][0].get('text', '')
            
            return jsonify({
                "status": "ok",
                "prompt": prompt,
                "analysis": answer,
                "model": result.get('model', 'claude-sonnet-4-20250514'),
                "usage": result.get('usage', {})
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Claude API error: {response.status_code}",
                "details": response.text[:500]
            }), response.status_code
            
    except http_requests.Timeout:
        return jsonify({"status": "error", "message": "Claude Vision timeout (>60s)"}), 504
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# CLAUDE TEXT WRAPPER (Ask Claude)
# =============================================================================

@app.route('/ask-claude', methods=['POST'])
def ask_claude():
    """
    Claude Text Wrapper for content questions.
    
    Input JSON:
      {
        "prompt": "The question or request",
        "context": "Optional: Additional context (e.g., text to review)"
      }
    """
    try:
        data = request.get_json(silent=True) or {}
        
        prompt = data.get('prompt', '')
        context = data.get('context', '')
        
        if not prompt:
            return jsonify({
                "status": "error",
                "message": "Parameter 'prompt' required"
            }), 400
        
        if context:
            full_prompt = f"Context:\n{context}\n\nQuestion:\n{prompt}"
        else:
            full_prompt = prompt
        
        response = http_requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "system": """You are reviewing my LinkedIn content. My positioning:
- "AI systems for creatives — the right way"
- Local, open source, portable, independent — no Big Tech dependency
- I'm actually building it (not just talking about AI)

Content pillars: Building in Public (60%), Critical Perspectives on AI hype (20%), Personal/Philosophical (20%)

My voice: Direct, opinionated, self-ironic (especially about my own successes). I write like I talk. I show enthusiasm for nerdy details. I admit when I don't know something.

Red flags to catch:
- Humble-bragging ("I'm just a simple...")
- Credential-leading ("After 25 years...")
- Dramatic fragments ("AI. It changes everything.")
- Corporate buzzwords (leverage, synergy, ecosystem)
- Hashtags (not allowed)
- Emojis (avoid)
- Any mention of my employer or team
- Engagement bait ("Agree?" "Thoughts?")

Be direct and concise. No bullet points. Write like a colleague giving honest feedback.""",
                "messages": [{
                    "role": "user",
                    "content": full_prompt
                }]
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            answer = ""
            if 'content' in result and len(result['content']) > 0:
                answer = result['content'][0].get('text', '')
            
            return jsonify({
                "status": "ok",
                "prompt": prompt,
                "answer": answer,
                "model": result.get('model', 'claude-sonnet-4-20250514'),
                "usage": result.get('usage', {})
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"Claude API error: {response.status_code}",
                "details": response.text[:500]
            }), response.status_code
            
    except http_requests.Timeout:
        return jsonify({"status": "error", "message": "Claude timeout (>60s)"}), 504
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    print("=" * 50)
    print("Mora02 Knowledge API - Extended v4.0")
    print("=" * 50)
    print(f"Status File: {STATUS_FILE}")
    print(f"Sync Script: {SYNC_SCRIPT}")
    print(f"Session Summary Script: {SESSION_SUMMARY_SCRIPT}")
    print(f"Session Export Script: {SESSION_EXPORT_SCRIPT}")
    print(f"DB Host: {DB_HOST}:{DB_PORT}")
    print(f"Dify Dataset: {DIFY_DATASET_ID}")
    print("Endpoints:")
    print("  POST /sync           - Knowledge Base Update + Dify Upload")
    print("  GET  /status         - Sync Status")
    print("  GET  /health         - Health Check")
    print("  GET  /docs           - Document List")
    print("  POST /perplexity     - Web Search (Perplexity)")
    print("  POST /vision         - Image Analysis (Claude)")
    print("  POST /ask-claude     - Text Query (Claude)")
    print("  POST /session-done   - Generate Session Summary")
    print("  POST /export-sessions - Export Sessions to KB")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=8095, debug=False)
