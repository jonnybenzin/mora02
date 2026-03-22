#!/usr/bin/env python3
"""
Mora02 LLM Benchmark Suite
Testet verschiedene Modelle über Dify API

Usage:
  python llm-benchmark.py run [--models model1,model2]
  python llm-benchmark.py eval <results.json>
  python llm-benchmark.py report <results.json>
"""

import requests
import json
import time
import re
import os
import sys
from datetime import datetime
from pathlib import Path

# ============================================================================
# KONFIGURATION
# ============================================================================

DIFY_API_BASE = "http://mora02.local:8191/v1"  # Dify 1.x API

# Benchmark Agent API Keys (alle verwenden denselben Agent, nur Modell wird in Dify gewechselt)
# WICHTIG: Vor dem Test das Modell im Dify UI wechseln!
BENCHMARK_AGENT_KEY = "app-YIH65bgn4j2UV8BrILm3vTd3"  # Hier deinen benchmark_agent Key eintragen

# Ergebnis-Verzeichnis
RESULTS_DIR = Path("/opt/mora02/knowledge/benchmarks")

# Verfügbare Modelle (für Dokumentation)
MODELS = {
    "qwen3-14b": {"type": "local", "profile": "qwen3-14b", "vram": "~10 GB"},
    "qwen3-8b": {"type": "local", "profile": "qwen3-8b", "vram": "~6 GB"},
    "qwen25-7b": {"type": "local", "profile": "qwen25-7b", "vram": "~5 GB"},
    "qwen25-coder": {"type": "local", "profile": "qwen25-coder", "vram": "~10 GB"},
    "nous-hermes": {"type": "local", "profile": "nous-hermes", "vram": "~5 GB"},
    "magistral": {"type": "local", "profile": "magistral", "vram": "~16 GB"},
    "claude-sonnet": {"type": "cloud", "provider": "anthropic"},
    "claude-haiku": {"type": "cloud", "provider": "anthropic"},
    "mistral-large": {"type": "cloud", "provider": "mistral"},
}

# ============================================================================
# TEST DEFINITIONEN
# ============================================================================

TESTS = [
    # === Kategorie 1: Tool Calling ===
    {
        "id": "T1",
        "name": "Tool Call Simple",
        "category": "tool_calling",
        "prompt": "Frage Perplexity: Was ist die Hauptstadt von Frankreich?",
        "checks": [
            {"type": "contains", "text": "Paris", "weight": 1.0},
        ],
        "max_score": 1.0,
        "manual_eval": False,
    },
    {
        "id": "T2",
        "name": "Tool Call Multi-Step",
        "category": "tool_calling",
        "prompt": "Recherchiere via Perplexity aktuelle Entwicklungen im Bereich lokale KI-Modelle. Erstelle dann basierend auf den Ergebnissen einen Draft für einen LinkedIn Post.",
        "checks": [
            {"type": "min_length", "chars": 200, "weight": 1.0},
        ],
        "max_score": 1.0,
        "manual_eval": False,
    },
    {
        "id": "T3",
        "name": "Output ungekürzt Perplexity",
        "category": "tool_calling",
        "prompt": """Frage Perplexity: Was sind die wichtigsten Unterschiede zwischen den aktuellen Open Source LLMs Llama 3, Mistral und Qwen3?

WICHTIG: Gib die VOLLSTÄNDIGE Antwort von Perplexity wieder. 
Kürze NICHTS. Behalte alle Details und Quellenangaben.""",
        "checks": [
            {"type": "min_length", "chars": 500, "weight": 1.0},
            {"type": "contains_any", "texts": ["Quelle", "Source", "http", "laut", "according", "["], "weight": 0.5},
        ],
        "max_score": 1.5,
        "manual_eval": False,
    },
    {
        "id": "T4",
        "name": "Output ungekürzt Claude",
        "category": "tool_calling",
        "prompt": """Frage Claude: Erkläre die Architektur von Transformer-Modellen mit allen wichtigen Komponenten (Attention, Feed-Forward, Normalization, etc.)

WICHTIG: Gib Claudes VOLLSTÄNDIGE Antwort wieder.
Kürze NICHTS. Fasse NICHT zusammen.""",
        "checks": [
            {"type": "min_length", "chars": 400, "weight": 1.0},
            {"type": "not_contains_any", "texts": ["zusammengefasst", "kurz gesagt", "im Wesentlichen"], "weight": 0.5},
        ],
        "max_score": 1.5,
        "manual_eval": False,
    },
    
    # === Kategorie 2: Structured Output ===
    {
        "id": "T5",
        "name": "JSON Output",
        "category": "structured_output",
        "prompt": """Erstelle 3 LinkedIn Post Ideen zum Thema "KI im Kreativbereich".

Antworte NUR mit einem JSON Array. Keine Erklärung, kein Markdown.
Jedes Element muss diese Keys haben: title, hook, cta

Beispiel-Format:
[{"title": "...", "hook": "...", "cta": "..."}]""",
        "checks": [
            {"type": "valid_json", "weight": 1.0},
            {"type": "json_array_min_length", "min": 3, "weight": 0.5},
            {"type": "json_keys_in_each", "keys": ["title", "hook", "cta"], "weight": 1.0},
        ],
        "max_score": 2.5,
        "manual_eval": False,
    },
    {
        "id": "T6",
        "name": "Code Generation",
        "category": "structured_output",
        "prompt": """Schreibe eine Python Funktion fibonacci(n) die die n-te Fibonacci-Zahl zurückgibt.

Anforderungen:
- fibonacci(0) = 0
- fibonacci(1) = 1  
- fibonacci(10) = 55

Nur Code, keine Erklärung.""",
        "checks": [
            {"type": "contains", "text": "def fibonacci", "weight": 0.5},
            {"type": "code_executes", "weight": 1.0},
            {"type": "code_test", "call": "fibonacci(10)", "expect": 55, "weight": 1.0},
        ],
        "max_score": 2.5,
        "manual_eval": False,
    },
    
    # === Kategorie 3: Korrektur Deutsch ===
    {
        "id": "T7",
        "name": "Rechtschreibung DE",
        "category": "korrektur_de",
        "prompt": """Finde alle Rechtschreibfehler in diesem Text und liste sie auf:

"Letztes Wochende habe ich mein erstes lokkales KI-Modell instaliert. 
Die Konfiguration war komplizierter als gedacht, aber nach einigen 
Stunden lief ales wie geplant. Besonders die Geschwindkeit hat mich überzeugt."

Format: Liste jeden Fehler mit Korrektur auf.""",
        "checks": [
            {"type": "contains", "text": "Wochenende", "weight": 0.2},
            {"type": "contains", "text": "lokales", "weight": 0.2},
            {"type": "contains", "text": "installiert", "weight": 0.2},
            {"type": "contains", "text": "alles", "weight": 0.2},
            {"type": "contains", "text": "Geschwindigkeit", "weight": 0.2},
        ],
        "max_score": 1.0,
        "manual_eval": False,
    },
    {
        "id": "T8",
        "name": "Grammatik DE",
        "category": "korrektur_de",
        "prompt": """Finde alle Grammatikfehler in diesem Text und erkläre sie:

"Das neue Modell waren deutlich schneller als das alte. Ich habe gestern 
den Workflow getestet und es haben super funktioniert. Die Ergebnisse, 
dass ich bekommen habe, war sehr gut. Mein Team und ich ist begeistert 
von die Möglichkeiten."

Format: Liste jeden Fehler mit Erklärung und Korrektur.""",
        "checks": [
            {"type": "contains_any", "texts": ["war deutlich", "war schneller"], "weight": 0.2},
            {"type": "contains_any", "texts": ["hat super", "hat funktioniert"], "weight": 0.2},
            {"type": "contains_any", "texts": ["die ich", "Ergebnisse, die"], "weight": 0.2},
            {"type": "contains", "text": "waren sehr gut", "weight": 0.2},
            {"type": "contains_any", "texts": ["sind begeistert", "Team und ich sind"], "weight": 0.2},
        ],
        "max_score": 1.0,
        "manual_eval": False,
    },
    
    # === Kategorie 4: Korrektur Englisch ===
    {
        "id": "T9",
        "name": "Rechtschreibung EN",
        "category": "korrektur_en",
        "prompt": """Find all spelling errors in this text and list them:

"Last weekend I finaly managed to setup my local AI enviroment. 
The configuraton took longer then expected, but the performace is impressive."

Format: List each error with correction.""",
        "checks": [
            {"type": "contains", "text": "finally", "weight": 0.2},
            {"type": "contains", "text": "environment", "weight": 0.2},
            {"type": "contains", "text": "configuration", "weight": 0.2},
            {"type": "contains_any", "texts": ["than expected", "than I"], "weight": 0.2},
            {"type": "contains", "text": "performance", "weight": 0.2},
        ],
        "max_score": 1.0,
        "manual_eval": False,
    },
    {
        "id": "T10",
        "name": "Grammatik EN",
        "category": "korrektur_en",
        "prompt": """Find all grammar errors in this text and explain them:

"The model work very fast and the results is impressive. Me and my colleague 
was testing it yesterday. The informations we got was very helpful for our project."

Format: List each error with explanation and correction.""",
        "checks": [
            {"type": "contains", "text": "works", "weight": 0.2},
            {"type": "contains_any", "texts": ["results are", "are impressive"], "weight": 0.2},
            {"type": "contains_any", "texts": ["My colleague and I", "colleague and I were"], "weight": 0.2},
            {"type": "contains", "text": "information", "weight": 0.2},
            {"type": "contains_any", "texts": ["were testing", "were helpful", "was helpful"], "weight": 0.2},
        ],
        "max_score": 1.0,
        "manual_eval": False,
    },
    
    # === Kategorie 5: System Prompt Adherence ===
    {
        "id": "T11",
        "name": "System Prompt Länge",
        "category": "system_prompt",
        "system_prompt": "Du bist ein hilfreicher Assistent. WICHTIGE REGEL: Antworte IMMER in maximal 2 Sätzen. Nicht mehr.",
        "prompt": "Erkläre mir die Vorteile von Docker für die Softwareentwicklung.",
        "checks": [
            {"type": "max_sentences", "max": 2, "weight": 1.0},
        ],
        "max_score": 1.0,
        "manual_eval": False,
    },
    {
        "id": "T12",
        "name": "System Prompt Format",
        "category": "system_prompt",
        "system_prompt": "Du bist ein hilfreicher Assistent. WICHTIGE REGEL: Antworte IMMER in Bullet Points. Niemals Fließtext. Jede Antwort muss mindestens 3 Bullet Points haben.",
        "prompt": "Was sind die wichtigsten Dinge, die ich beim Backup meiner Daten beachten sollte?",
        "checks": [
            {"type": "contains_any", "texts": ["- ", "• ", "* ", "1.", "2.", "3."], "weight": 0.5},
            {"type": "min_bullet_points", "min": 3, "weight": 0.5},
        ],
        "max_score": 1.0,
        "manual_eval": False,
    },
    {
        "id": "T13",
        "name": "System Prompt Verboten",
        "category": "system_prompt",
        "system_prompt": "Du bist ein hilfreicher Assistent. WICHTIGE REGEL: Benutze NIEMALS die Wörter 'allerdings', 'jedoch', 'grundsätzlich'. Finde immer Alternativen.",
        "prompt": "Was sind die Vor- und Nachteile von lokalen KI-Modellen im Vergleich zu Cloud-APIs?",
        "checks": [
            {"type": "not_contains", "text": "allerdings", "weight": 0.34},
            {"type": "not_contains", "text": "jedoch", "weight": 0.33},
            {"type": "not_contains", "text": "grundsätzlich", "weight": 0.33},
        ],
        "max_score": 1.0,
        "manual_eval": False,
    },
    
    # === Kategorie 6: Text-Optimierung (Manuell) ===
    {
        "id": "T14",
        "name": "Stichpunkte zu Post DE",
        "category": "text_optimierung",
        "prompt": """Schreibe einen LinkedIn Post aus diesen Stichpunkten:

FAKTEN:
- Erster lokaler Video-Gen Test auf Mora02
- Prompt: "Hund tanzt Salsa"
- Ergebnis: Kein Hund zu sehen, nur wild wirbelndes abstraktes Etwas
- Mit viel Fantasie konnte man einen tanzenden Hund erahnen
- ComfyUI Workflow, SD 1.5 (2022er Modell)
- Workflow verloren wegen Volume Mapping Fehler nach Reboot

EMOTIONALE RICHTUNG:
Selbstironie: "Das ist gleichzeitig ein Erfolg und ein Desaster". 
Der Leser soll lachen und denken "KI-Realität vs. KI-Erwartung".
Unterschwellig stolz dass überhaupt was rauskam.
Pointe: Das abstrakte Chaos IST irgendwie Kunst.

VORGABEN:
- 120-150 Wörter
- Starker Hook (keine Frage, kein Clickbait)
- Endet mit Einladung zur Diskussion""",
        "checks": [],
        "max_score": 0,
        "manual_eval": True,
        "manual_criteria": [
            {"name": "hook", "description": "Starker Hook ohne Clickbait?"},
            {"name": "ton", "description": "Trifft den selbstironischen Ton?"},
            {"name": "emotion", "description": "Kommt die 'Erfolg und Desaster' Stimmung rüber?"},
            {"name": "laenge", "description": "120-150 Wörter eingehalten?"},
            {"name": "lesbarkeit", "description": "Flüssig aus Stichpunkten gebaut?"},
        ],
    },
    {
        "id": "T15",
        "name": "Stichpunkte zu Post EN",
        "category": "text_optimierung",
        "prompt": """Write a LinkedIn post from these bullet points:

FACTS:
- 16 hours building local AI setup vs $20/month cloud APIs
- Mass of Docker containers, RTX 5090
- Finally works
- But: spent more time debugging than actually creating
- Plot twist: love the process more than the result

EMOTIONAL DIRECTION:
Self-deprecating humor about the sunken cost fallacy meeting genuine passion.
Reader should think "this is absurd but I totally get it".
Subtle message: The journey of building something yourself has value beyond ROI.

REQUIREMENTS:
- 120-150 words
- Strong hook (no question, no clickbait)
- Ends with genuine discussion invite (not "comment if you agree")""",
        "checks": [],
        "max_score": 0,
        "manual_eval": True,
        "manual_criteria": [
            {"name": "hook", "description": "Strong hook without clickbait?"},
            {"name": "ton", "description": "Hits the self-deprecating tone?"},
            {"name": "emotion", "description": "Conveys 'absurd but passionate' vibe?"},
            {"name": "laenge", "description": "120-150 words respected?"},
            {"name": "lesbarkeit", "description": "Flows naturally from bullet points?"},
        ],
    },
    
    # === Kategorie 7: Reasoning / Debug (Auto) ===
    {
        "id": "T16",
        "name": "Workflow Debug",
        "category": "reasoning",
        "prompt": """Mein Activepieces Workflow für Image Generation funktioniert nicht mehr.

**Symptom:** 
Der Flow startet, step_1 (build_and_send) läuft durch mit prompt_id, 
aber bei step_3 (comfyui_history) bekomme ich "Connection refused". 
Danach schlägt step_4 (baserow_entry) mit 404 fehl.

**Hinweise:** 
- ComfyUI läuft normalerweise auf Port 8188
- Activepieces verwendet {{step_X['key']}} Syntax mit eckigen Klammern
- Baserow API benötigt einen Host-Header

**Relevante Code-Teile:**

step_1 (build_and_send) - macht HTTP POST:
```javascript
const response = await fetch('http://comfyui:8189/prompt', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(workflow)
});
```

step_3 (comfyui_history) - HTTP GET:
```
URL: http://comfyui:8189/history/{{step_1['prompt_id']}}
```

step_6 (extract_filename) - Input Mapping:
```javascript
input: {
  "history": "{{step_3.body}}",
  "prompt_id": "{{step_1['prompt_id']}}"
}
```

step_4 (baserow_entry) - HTTP POST:
```
URL: {{step_5['create_url']}}
Headers: {
  "Authorization": "Token xxx",
  "Content-Type": "application/json"
}
```

**Aufgabe:** Finde die 3 Fehler im Code und erkläre kurz wie man sie behebt.""",
        "checks": [
            {"type": "contains", "text": "8188", "weight": 1.0},
            {"type": "contains_any", "texts": ["step_3['body']", "['body']", '["body"]', "eckigen Klammern", "bracket"], "weight": 1.0},
            {"type": "contains_any", "texts": ["Host", "host-header", "Host-Header"], "weight": 1.0},
        ],
        "max_score": 3.0,
        "manual_eval": False,
    },
    {
        "id": "T17",
        "name": "Strategisches Feedback",
        "category": "reasoning",
        "prompt": """Ich möchte diesen LinkedIn Post veröffentlichen. Gib mir strategisches Feedback.

Meine Positionierung: "AI systems for creatives – the right way"
Zielgruppe: Tech-affine Kreative, Freelancer, kleine Agenturen

**Post:**
"First fully locally, CUDA GPU supported video generation on mora02. "Dog dancing 
salsa" was the prompt. I admit, not exactly best practice prompting for text to video. 
But it worked. I built the workflow in ComfyUI, checkpoint sd_v1-5.safetensors 
(an elderly 2022 model). Sadly I don't have the workflow anymore – it was before I 
learned that ComfyUI workflows have to be saved actively, and I think there was 
something wrong with volume mapping so all data disappeared after reboot."

**Fragen:**
- Ist der Hook stark genug?
- Passt der Ton zu meiner Positionierung?
- Was fehlt? Was würdest du ändern?
- Wie könnte ich mehr Engagement erzeugen?
- Welches Bild/Video sollte ich dazu posten?""",
        "checks": [],
        "max_score": 0,
        "manual_eval": True,
        "manual_criteria": [
            {"name": "tiefe", "description": "Geht das Feedback in die Tiefe oder bleibt es oberflächlich?"},
            {"name": "konkret_actionable", "description": "Sind die Vorschläge konkret und umsetzbar?"},
            {"name": "nicht_mechanisch", "description": "Wirkt es durchdacht oder wie eine Checkliste abgehakt?"},
            {"name": "zielgruppen_fit", "description": "Berücksichtigt es meine Positionierung und Zielgruppe?"},
        ],
    },
    
    # === Kategorie 8: Kreativ (Manuell - kombiniert) ===
    {
        "id": "T18",
        "name": "Kreativer Post + Bild + Prompt",
        "category": "kreativ",
        "prompt": """Erstelle einen kompletten LinkedIn Content-Vorschlag:

**TEIL 1 - POST:**
Schreibe einen LinkedIn Post zu diesem Thema:
"Warum ich lieber 16 Stunden in mein eigenes AI-Setup investiere statt $20/Monat für Cloud-APIs zu zahlen"

Vorgaben:
- Zielgruppe: Tech-affine Kreative, Freelancer, kleine Agenturen
- Ton: Selbstironisch, authentisch, nicht belehrend
- Länge: 150-200 Wörter
- Starker Hook in den ersten 2 Zeilen
- Soll zum Kommentieren einladen

**TEIL 2 - BILDKONZEPT:**
Beschreibe ein passendes Bild für diesen Post:
- Hauptmotiv
- Stil (Foto, Illustration, Abstract)
- Stimmung/Atmosphäre
- Dominante Farben
- Was NICHT im Bild sein soll

**TEIL 3 - STABLE DIFFUSION PROMPT:**
Schreibe den Prompt für ComfyUI/Stable Diffusion:
- Positive Prompt
- Negative Prompt
- Empfohlene Einstellungen (Steps, CFG, Sampler, Checkpoint)""",
        "checks": [],
        "max_score": 0,
        "manual_eval": True,
        "manual_criteria": [
            {"name": "post_hook", "description": "Sind die ersten 2 Zeilen attention-grabbing?"},
            {"name": "post_originalitaet", "description": "Ist der Post originell oder generisch?"},
            {"name": "post_ton", "description": "Passt der Ton (selbstironisch, authentisch)?"},
            {"name": "bild_passt", "description": "Unterstützt das Bildkonzept die Message?"},
            {"name": "bild_konkret", "description": "Ist die Bildbeschreibung konkret genug?"},
            {"name": "prompt_funktioniert", "description": "Würde der SD-Prompt funktionieren?"},
        ],
    },
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def call_dify(api_key: str, prompt: str, system_prompt: str = None) -> dict:
    """Sendet Prompt an Dify Agent, gibt Response zurück (streaming mode)"""
    start_time = time.time()
    
    try:
        payload = {
            "inputs": {},
            "query": prompt,
            "response_mode": "streaming",
            "user": "benchmark",
        }
        
        # System prompt als Input wenn vorhanden
        if system_prompt:
            payload["inputs"]["system_prompt"] = system_prompt
        
        response = requests.post(
            f"{DIFY_API_BASE}/chat-messages",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=180,
            stream=True,
        )
        response.raise_for_status()
        
        # Parse SSE stream
        full_answer = ""
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data_str = line[6:]  # Remove 'data: ' prefix
                    if data_str.strip() == '[DONE]':
                        break
                    try:
                        data = json.loads(data_str)
                        event = data.get("event", "")
                        
                        if event == "agent_message" or event == "message":
                            full_answer += data.get("answer", "")
                        elif event == "message_end":
                            # Final message - could contain full answer
                            pass
                        elif event == "error":
                            return {
                                "success": False,
                                "error": data.get("message", "Unknown error"),
                                "time": time.time() - start_time,
                            }
                    except json.JSONDecodeError:
                        continue
        
        return {
            "success": True,
            "answer": full_answer,
            "metadata": {},
            "time": time.time() - start_time,
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Timeout (180s)",
            "time": time.time() - start_time,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "time": time.time() - start_time,
        }


def extract_json(text: str):
    """Versucht JSON aus Text zu extrahieren"""
    # Direkt parsen
    try:
        return json.loads(text)
    except:
        pass
    
    # JSON in Code-Block suchen
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if match:
        try:
            return json.loads(match.group(1))
        except:
            pass
    
    # Array suchen
    match = re.search(r'\[[\s\S]*\]', text)
    if match:
        try:
            return json.loads(match.group(0))
        except:
            pass
    
    return None


def extract_code(text: str) -> str:
    """Extrahiert Python Code aus Text"""
    match = re.search(r'```(?:python)?\s*([\s\S]*?)\s*```', text)
    if match:
        return match.group(1)
    return text


def count_sentences(text: str) -> int:
    """Zählt Sätze in Text"""
    # Einfache Heuristik: Punkte, Ausrufezeichen, Fragezeichen
    sentences = re.split(r'[.!?]+', text)
    return len([s for s in sentences if s.strip()])


def count_bullet_points(text: str) -> int:
    """Zählt Bullet Points in Text"""
    patterns = [r'^[\s]*[-•*]', r'^[\s]*\d+\.']
    count = 0
    for line in text.split('\n'):
        for pattern in patterns:
            if re.match(pattern, line):
                count += 1
                break
    return count


def run_checks(response: dict, checks: list) -> tuple:
    """Führt alle Checks durch, gibt (score, details) zurück"""
    if not response.get("success"):
        return 0.0, [{"check": "api_call", "passed": False, "error": response.get("error")}]
    
    answer = response.get("answer", "")
    score = 0.0
    details = []
    
    for check in checks:
        check_type = check["type"]
        weight = check.get("weight", 1.0)
        passed = False
        info = ""
        
        if check_type == "contains":
            text = check["text"].lower()
            passed = text in answer.lower()
            info = f"'{check['text']}' {'gefunden' if passed else 'nicht gefunden'}"
            
        elif check_type == "contains_any":
            texts = [t.lower() for t in check["texts"]]
            passed = any(t in answer.lower() for t in texts)
            info = f"Einer von {check['texts']}"
            
        elif check_type == "not_contains":
            text = check["text"].lower()
            passed = text not in answer.lower()
            info = f"'{check['text']}' {'nicht enthalten ✓' if passed else 'enthalten ✗'}"
            
        elif check_type == "not_contains_any":
            texts = [t.lower() for t in check["texts"]]
            passed = not any(t in answer.lower() for t in texts)
            info = f"Keiner von {check['texts']}"
            
        elif check_type == "min_length":
            length = len(answer)
            passed = length >= check["chars"]
            info = f"{length} Zeichen (min: {check['chars']})"
            
        elif check_type == "valid_json":
            data = extract_json(answer)
            passed = data is not None
            info = "Valides JSON" if passed else "Kein valides JSON"
            
        elif check_type == "json_array_min_length":
            data = extract_json(answer)
            if isinstance(data, list):
                passed = len(data) >= check["min"]
                info = f"Array mit {len(data)} Elementen (min: {check['min']})"
            else:
                info = "Kein Array"
                
        elif check_type == "json_keys_in_each":
            data = extract_json(answer)
            if isinstance(data, list) and len(data) > 0:
                keys = check["keys"]
                passed = all(all(k in item for k in keys) for item in data if isinstance(item, dict))
                info = f"Keys {keys} in allen Elementen: {passed}"
            else:
                info = "Kein Array oder leer"
                
        elif check_type == "code_executes":
            code = extract_code(answer)
            try:
                exec(code, {"__builtins__": __builtins__})
                passed = True
                info = "Code läuft"
            except Exception as e:
                info = f"Code-Fehler: {str(e)[:50]}"
                
        elif check_type == "code_test":
            code = extract_code(answer)
            try:
                local_vars = {}
                exec(code, {"__builtins__": __builtins__}, local_vars)
                result = eval(check["call"], {"__builtins__": __builtins__}, local_vars)
                passed = result == check["expect"]
                info = f"{check['call']} = {result} (erwartet: {check['expect']})"
            except Exception as e:
                info = f"Test-Fehler: {str(e)[:50]}"
                
        elif check_type == "max_sentences":
            count = count_sentences(answer)
            passed = count <= check["max"]
            info = f"{count} Sätze (max: {check['max']})"
            
        elif check_type == "min_bullet_points":
            count = count_bullet_points(answer)
            passed = count >= check["min"]
            info = f"{count} Bullet Points (min: {check['min']})"
        
        if passed:
            score += weight
            
        details.append({
            "check": check_type,
            "passed": passed,
            "weight": weight,
            "info": info,
        })
    
    return score, details


# ============================================================================
# BENCHMARK RUNNER
# ============================================================================

def run_benchmark(model_name: str, api_key: str) -> dict:
    """Führt Benchmark für ein Modell durch"""
    
    print(f"\n{'='*60}")
    print(f"BENCHMARK: {model_name.upper()}")
    print(f"{'='*60}\n")
    
    results = {
        "model": model_name,
        "timestamp": datetime.now().isoformat(),
        "tests": {},
        "auto_score": 0,
        "auto_max": 0,
        "manual_pending": [],
        "total_time": 0,
    }
    
    for test in TESTS:
        test_id = test["id"]
        print(f"  [{test_id}] {test['name']}...", end=" ", flush=True)
        
        # System Prompt wenn vorhanden
        system_prompt = test.get("system_prompt")
        
        # API Call
        response = call_dify(api_key, test["prompt"], system_prompt)
        results["total_time"] += response.get("time", 0)
        
        if test["manual_eval"]:
            # Manuell - nur speichern
            results["tests"][test_id] = {
                "name": test["name"],
                "category": test["category"],
                "prompt": test["prompt"][:200] + "..." if len(test["prompt"]) > 200 else test["prompt"],
                "response": response,
                "manual_eval": True,
                "manual_criteria": test.get("manual_criteria", []),
                "scores": {},
            }
            results["manual_pending"].append(test_id)
            print(f"⏳ (manuell) [{response.get('time', 0):.1f}s]")
        else:
            # Automatisch
            score, details = run_checks(response, test["checks"])
            results["tests"][test_id] = {
                "name": test["name"],
                "category": test["category"],
                "response": response,
                "auto_score": score,
                "max_score": test["max_score"],
                "details": details,
            }
            results["auto_score"] += score
            results["auto_max"] += test["max_score"]
            
            status = "✅" if score == test["max_score"] else "⚠️" if score > 0 else "❌"
            print(f"{status} {score:.1f}/{test['max_score']:.1f} [{response.get('time', 0):.1f}s]")
    
    # Zusammenfassung
    pct = (results["auto_score"] / results["auto_max"] * 100) if results["auto_max"] > 0 else 0
    print(f"\n  Auto-Score: {results['auto_score']:.1f}/{results['auto_max']:.1f} ({pct:.0f}%)")
    print(f"  Zeit: {results['total_time']:.1f}s")
    print(f"  Manuell ausstehend: {len(results['manual_pending'])} Tests")
    
    return results


def run_all_benchmarks(api_key: str, models_to_test: list = None):
    """Führt Benchmark für alle/ausgewählte Modelle durch"""
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    
    all_results = {
        "timestamp": timestamp,
        "models": {},
    }
    
    if models_to_test is None:
        models_to_test = list(MODELS.keys())
    
    print(f"\n{'#'*60}")
    print(f"# MORA02 LLM BENCHMARK - {timestamp}")
    print(f"# Modelle: {', '.join(models_to_test)}")
    print(f"# Tests: {len(TESTS)} ({len([t for t in TESTS if not t['manual_eval']])} auto, {len([t for t in TESTS if t['manual_eval']])} manuell)")
    print(f"{'#'*60}")
    
    for model in models_to_test:
        print(f"\n⚠️  WICHTIG: Wechsle jetzt in Dify das Modell zu '{model}'")
        print(f"   Für lokale Modelle auch Docker Profile wechseln:")
        print(f"   docker stop llama-server && docker rm llama-server")
        print(f"   docker compose --profile {MODELS.get(model, {}).get('profile', model)} up -d")
        input(f"\n   Drücke ENTER wenn bereit...")
        
        results = run_benchmark(model, api_key)
        all_results["models"][model] = results
        
        # Pause zwischen Modellen
        print("\n   Pause 5 Sekunden...")
        time.sleep(5)
    
    # Ergebnisse speichern
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_file = RESULTS_DIR / f"{timestamp}_benchmark.json"
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n{'='*60}")
    print(f"ERGEBNISSE GESPEICHERT: {output_file}")
    print(f"{'='*60}")
    
    return all_results, output_file


# ============================================================================
# MANUELLE BEWERTUNG
# ============================================================================

def manual_eval(results_file: str):
    """Interaktive manuelle Bewertung - BLIND (Modellnamen verborgen, zufällige Reihenfolge)"""
    import random
    
    with open(results_file, "r", encoding="utf-8") as f:
        results = json.load(f)
    
    models = list(results["models"].keys())
    
    # Finde Tests die manuell bewertet werden müssen
    manual_tests = [t for t in TESTS if t["manual_eval"]]
    
    print(f"\n{'='*60}")
    print("MANUELLE BEWERTUNG (BLIND)")
    print(f"{'='*60}")
    print(f"\nAnzahl Modelle: {len(models)}")
    print(f"Anzahl Tests: {len(manual_tests)}")
    print("\nBewertungsskala: 1=Unbrauchbar, 2=Schwach, 3=OK, 4=Gut, 5=Sehr gut")
    print("\n⚠️  Die Antworten werden in ZUFÄLLIGER Reihenfolge als")
    print("   'Antwort A', 'Antwort B', etc. angezeigt.")
    print("   Die Zuordnung wird am Ende aufgelöst.")
    print("-"*60)
    
    # Mapping für Auflösung am Ende
    all_mappings = {}
    
    for test in manual_tests:
        test_id = test["id"]
        
        print(f"\n{'='*60}")
        print(f"TEST {test_id}: {test['name']}")
        print(f"Kategorie: {test['category']}")
        print(f"{'='*60}")
        
        # Prompt zeigen
        print(f"\nPROMPT:\n{'-'*40}")
        print(test["prompt"][:800] + "..." if len(test["prompt"]) > 800 else test["prompt"])
        print(f"{'-'*40}")
        
        # Kriterien zeigen
        print(f"\nKRITERIEN:")
        for c in test.get("manual_criteria", []):
            print(f"  - {c['name']}: {c['description']}")
        
        # Modelle zufällig mischen
        shuffled_models = models.copy()
        random.shuffle(shuffled_models)
        
        # Mapping speichern (A=model1, B=model2, etc.)
        labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        mapping = {labels[i]: m for i, m in enumerate(shuffled_models)}
        all_mappings[test_id] = mapping
        
        # Alle Modell-Antworten zeigen (ohne Namen!)
        print(f"\n{'='*60}")
        print("ANTWORTEN:")
        print(f"{'='*60}")
        
        for i, model in enumerate(shuffled_models):
            label = labels[i]
            model_data = results["models"][model]["tests"].get(test_id, {})
            response = model_data.get("response", {})
            answer = response.get("answer", "KEINE ANTWORT")
            
            print(f"\n--- ANTWORT {label} ---")
            # Erhöhtes Limit: 2500 Zeichen
            print(answer[:2500] + "..." if len(answer) > 2500 else answer)
            print(f"[Zeit: {response.get('time', 0):.1f}s]")
        
        # Bewertungen eingeben
        print(f"\n{'='*60}")
        print("BEWERTUNGEN EINGEBEN:")
        print(f"{'='*60}")
        
        for i, model in enumerate(shuffled_models):
            label = labels[i]
            print(f"\nANTWORT {label}:")
            model_data = results["models"][model]["tests"].get(test_id, {})
            
            scores = {}
            for c in test.get("manual_criteria", []):
                while True:
                    try:
                        score = input(f"  {c['name']} [1-5]: ").strip()
                        if score == "":
                            score = 3  # Default
                        else:
                            score = int(score)
                        if 1 <= score <= 5:
                            scores[c["name"]] = score
                            break
                    except ValueError:
                        pass
                    print("    Bitte Zahl 1-5 eingeben (oder ENTER für 3)")
            
            # Optionale Notiz
            note = input(f"  Notiz (optional): ").strip()
            if note:
                scores["_note"] = note
            
            # Durchschnitt berechnen
            numeric_scores = [v for k, v in scores.items() if k != "_note"]
            avg = sum(numeric_scores) / len(numeric_scores) if numeric_scores else 0
            scores["_average"] = round(avg, 2)
            
            # Speichern (mit echtem Modellnamen)
            model_data["scores"] = scores
            print(f"  → Durchschnitt: {avg:.2f}/5")
    
    # Auflösung anzeigen
    print(f"\n{'='*60}")
    print("AUFLÖSUNG: WELCHES MODELL WAR WAS?")
    print(f"{'='*60}")
    
    for test_id, mapping in all_mappings.items():
        print(f"\n{test_id}:")
        for label, model in mapping.items():
            test_data = results["models"][model]["tests"].get(test_id, {})
            avg = test_data.get("scores", {}).get("_average", "?")
            print(f"  Antwort {label} = {model} (Score: {avg})")
    
    # Ergebnisse speichern
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n{'='*60}")
    print(f"BEWERTUNGEN GESPEICHERT: {results_file}")
    print(f"{'='*60}")


# ============================================================================
# REPORT GENERATOR
# ============================================================================

def generate_report(results_file: str):
    """Generiert Markdown Report"""
    
    with open(results_file, "r", encoding="utf-8") as f:
        results = json.load(f)
    
    timestamp = results["timestamp"]
    models = list(results["models"].keys())
    
    report = f"""# LLM Benchmark Report

**Datum:** {timestamp}
**Modelle:** {', '.join(models)}
**Tests:** {len(TESTS)} ({len([t for t in TESTS if not t['manual_eval']])} automatisch, {len([t for t in TESTS if t['manual_eval']])} manuell)

---

## Zusammenfassung

| Modell | Auto-Score | Manuell Ø | Zeit | VRAM |
|--------|------------|-----------|------|------|
"""
    
    for model in models:
        data = results["models"][model]
        auto = data.get("auto_score", 0)
        auto_max = data.get("auto_max", 1)
        auto_pct = (auto / auto_max * 100) if auto_max > 0 else 0
        
        # Manuelle Scores
        manual_avgs = []
        for test_id, test_data in data.get("tests", {}).items():
            if test_data.get("manual_eval") and "scores" in test_data:
                avg = test_data["scores"].get("_average", 0)
                if avg > 0:
                    manual_avgs.append(avg)
        manual_avg = sum(manual_avgs) / len(manual_avgs) if manual_avgs else 0
        
        time_s = data.get("total_time", 0)
        vram = MODELS.get(model, {}).get("vram", "?")
        
        report += f"| {model} | {auto:.1f}/{auto_max:.1f} ({auto_pct:.0f}%) | {manual_avg:.1f}/5 | {time_s:.0f}s | {vram} |\n"
    
    # Detail-Ergebnisse: Automatische Tests
    report += """
---

## Automatische Tests (Detail)

"""
    
    for test in TESTS:
        if test["manual_eval"]:
            continue
            
        test_id = test["id"]
        report += f"### {test_id}: {test['name']}\n\n"
        report += f"**Kategorie:** {test['category']}\n\n"
        report += "| Modell | Score | Details |\n"
        report += "|--------|-------|--------|\n"
        
        for model in models:
            test_data = results["models"][model]["tests"].get(test_id, {})
            score = test_data.get("auto_score", 0)
            max_score = test_data.get("max_score", 0)
            details = test_data.get("details", [])
            
            details_str = ", ".join([f"{d['check']}: {'✓' if d['passed'] else '✗'}" for d in details[:3]])
            report += f"| {model} | {score:.1f}/{max_score:.1f} | {details_str} |\n"
        
        report += "\n"
    
    # Detail-Ergebnisse: Manuelle Tests
    report += """
---

## Manuelle Tests (Detail)

"""
    
    for test in TESTS:
        if not test["manual_eval"]:
            continue
            
        test_id = test["id"]
        report += f"### {test_id}: {test['name']}\n\n"
        report += f"**Kategorie:** {test['category']}\n\n"
        
        criteria_names = [c["name"] for c in test.get("manual_criteria", [])]
        header = "| Modell | " + " | ".join(criteria_names) + " | Ø |\n"
        separator = "|--------|" + "|".join(["------" for _ in criteria_names]) + "|---|\n"
        
        report += header
        report += separator
        
        for model in models:
            test_data = results["models"][model]["tests"].get(test_id, {})
            scores = test_data.get("scores", {})
            
            row = f"| {model} |"
            for c in criteria_names:
                s = scores.get(c, "-")
                row += f" {s} |"
            avg = scores.get("_average", "-")
            row += f" {avg} |\n"
            report += row
        
        report += "\n"
    
    # Stärken/Schwächen
    report += """
---

## Stärken & Schwächen

"""
    
    for model in models:
        data = results["models"][model]
        report += f"### {model}\n\n"
        
        strengths = []
        weaknesses = []
        
        for test_id, test_data in data.get("tests", {}).items():
            if test_data.get("manual_eval"):
                avg = test_data.get("scores", {}).get("_average", 0)
                if avg >= 4:
                    strengths.append(f"{test_id} ({avg:.1f}/5)")
                elif avg > 0 and avg < 3:
                    weaknesses.append(f"{test_id} ({avg:.1f}/5)")
            else:
                score = test_data.get("auto_score", 0)
                max_score = test_data.get("max_score", 1)
                pct = score / max_score if max_score > 0 else 0
                if pct >= 0.9:
                    strengths.append(f"{test_id} ({score:.1f}/{max_score:.1f})")
                elif pct < 0.5:
                    weaknesses.append(f"{test_id} ({score:.1f}/{max_score:.1f})")
        
        if strengths:
            report += f"**Stärken:** {', '.join(strengths)}\n\n"
        if weaknesses:
            report += f"**Schwächen:** {', '.join(weaknesses)}\n\n"
        
        report += "\n"
    
    # Report speichern
    report_file = results_file.replace(".json", ".md")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"Report generiert: {report_file}")
    return report_file


# ============================================================================
# CLI
# ============================================================================

def print_usage():
    print("""
Mora02 LLM Benchmark Suite

Usage:
  python llm-benchmark.py run [--models model1,model2,...]
  python llm-benchmark.py eval <results.json>
  python llm-benchmark.py report <results.json>
  python llm-benchmark.py list

Commands:
  run      Benchmark durchführen
  eval     Manuelle Bewertung der Ergebnisse
  report   Markdown Report generieren
  list     Verfügbare Modelle anzeigen

Options:
  --models  Komma-separierte Liste der zu testenden Modelle
            Default: alle Modelle

Examples:
  python llm-benchmark.py run --models qwen3-14b,magistral
  python llm-benchmark.py eval /opt/mora02/knowledge/benchmarks/20260203_1430_benchmark.json
  python llm-benchmark.py report /opt/mora02/knowledge/benchmarks/20260203_1430_benchmark.json
""")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "run":
        # API Key prüfen
        if BENCHMARK_AGENT_KEY == "app-XXXXXXXXXX":
            print("FEHLER: Bitte BENCHMARK_AGENT_KEY im Script setzen!")
            print("Öffne das Script und ersetze 'app-XXXXXXXXXX' mit deinem API Key.")
            sys.exit(1)
        
        # Modelle parsen
        models = None
        for arg in sys.argv[2:]:
            if arg.startswith("--models="):
                models = arg.split("=")[1].split(",")
            elif arg.startswith("--models"):
                idx = sys.argv.index(arg)
                if idx + 1 < len(sys.argv):
                    models = sys.argv[idx + 1].split(",")
        
        run_all_benchmarks(BENCHMARK_AGENT_KEY, models)
        
    elif cmd == "eval":
        if len(sys.argv) < 3:
            print("FEHLER: Bitte Results-Datei angeben")
            print("Beispiel: python llm-benchmark.py eval results.json")
            sys.exit(1)
        manual_eval(sys.argv[2])
        
    elif cmd == "report":
        if len(sys.argv) < 3:
            print("FEHLER: Bitte Results-Datei angeben")
            print("Beispiel: python llm-benchmark.py report results.json")
            sys.exit(1)
        generate_report(sys.argv[2])
        
    elif cmd == "list":
        print("\nVerfügbare Modelle:")
        print("-" * 50)
        for name, info in MODELS.items():
            print(f"  {name:<20} {info.get('type', '?'):<8} {info.get('vram', '')}")
        print()
        
    else:
        print(f"Unbekannter Befehl: {cmd}")
        print_usage()
        sys.exit(1)
