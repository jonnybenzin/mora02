#!/usr/bin/env python3
"""
Mora02 Session Summary Generator

Liest Dify Conversations aus der Postgres DB,
fasst sie mit Qwen3-14B zusammen,
speichert strukturiert in session_summaries Tabelle.

Usage:
    python3 generate-session-summary.py                    # Alle unverarbeiteten Conversations
    python3 generate-session-summary.py --conversation-id UUID  # Spezifische Conversation
    python3 generate-session-summary.py --since 2026-02-05      # Seit Datum
    python3 generate-session-summary.py --last 24h              # Letzte 24 Stunden
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from uuid import UUID

import psycopg2
import psycopg2.extras
import requests

# =============================================================================
# CONFIGURATION
# =============================================================================

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": os.getenv("POSTGRES_PORT", "5433"),
    "database": os.getenv("POSTGRES_DB", "dify"),
    "user": os.getenv("POSTGRES_USER", "dify"),
    "password": os.getenv("POSTGRES_PASSWORD", "dify_secure_password")
}

LLM_URL = os.getenv("LLM_URL", "http://localhost:8080/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3-14b")

MIN_MESSAGES = 2  # Mindestanzahl Messages für eine "echte" Session

# =============================================================================
# SUMMARY PROMPT
# =============================================================================

SUMMARY_PROMPT = """You are a technical documentarian. Summarize the following bot conversation.

CONVERSATION:
{conversation}

Create a structured summary in the following JSON format. Reply ONLY with valid JSON, no other text:

{{
  "context": "One-liner describing what the session was about",
  "what_we_did": [
    {{"action": "What was done", "detail": "Important details"}}
  ],
  "decisions": [
    {{"decision": "What decision was made", "reason": "Why this was decided"}}
  ],
  "files_changed": [
    {{"path": "/path/to/file", "change": "created/modified/deleted"}}
  ],
  "open_questions": ["Open question 1", "Open question 2"],
  "next_steps": ["Next step 1", "Next step 2"]
}}

Rules:
- Only include what was actually discussed/done
- Be technically precise, no filler words
- Copy paths and commands exactly
- For decisions ALWAYS include the "why"
- Use empty arrays [] if nothing relevant
"""

# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_db_connection():
    """Erstellt Datenbankverbindung."""
    return psycopg2.connect(**DB_CONFIG)

def get_unprocessed_conversations(conn, since=None, min_messages=MIN_MESSAGES):
    """Holt Conversations die noch nicht zusammengefasst wurden."""
    query = """
        SELECT c.id, c.app_id, c.name, c.created_at, c.updated_at,
               COUNT(m.id) as message_count
        FROM conversations c
        LEFT JOIN messages m ON m.conversation_id = c.id
        LEFT JOIN session_summaries ss ON ss.conversation_id = c.id
        WHERE ss.id IS NULL
          AND c.is_deleted = false
    """
    params = []
    
    if since:
        query += " AND c.created_at >= %s"
        params.append(since)
    
    query += """
        GROUP BY c.id
        HAVING COUNT(m.id) >= %s
        ORDER BY c.created_at DESC
    """
    params.append(min_messages)
    
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(query, params)
        return cur.fetchall()

def get_conversation_by_id(conn, conversation_id):
    """Holt spezifische Conversation."""
    query = """
        SELECT c.id, c.app_id, c.name, c.created_at, c.updated_at,
               COUNT(m.id) as message_count
        FROM conversations c
        LEFT JOIN messages m ON m.conversation_id = c.id
        WHERE c.id = %s
        GROUP BY c.id
    """
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(query, (conversation_id,))
        return cur.fetchone()

def get_conversation_messages(conn, conversation_id):
    """Holt alle Messages einer Conversation."""
    query = """
        SELECT query, answer, created_at
        FROM messages
        WHERE conversation_id = %s
        ORDER BY created_at ASC
    """
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(query, (conversation_id,))
        return cur.fetchall()

def save_session_summary(conn, conversation_id, app_id, session_date, summary_data, raw_summary):
    """Speichert Zusammenfassung in DB."""
    query = """
        INSERT INTO session_summaries 
        (conversation_id, app_id, session_date, context, what_we_did, decisions, 
         files_changed, open_questions, next_steps, raw_summary)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(query, (
            conversation_id,
            app_id,
            session_date,
            summary_data.get("context", ""),
            json.dumps(summary_data.get("what_we_did", [])),
            json.dumps(summary_data.get("decisions", [])),
            json.dumps(summary_data.get("files_changed", [])),
            summary_data.get("open_questions", []),
            summary_data.get("next_steps", []),
            raw_summary
        ))
        conn.commit()
        return cur.fetchone()[0]

def is_already_processed(conn, conversation_id):
    """Prüft ob Conversation bereits verarbeitet wurde."""
    query = "SELECT id FROM session_summaries WHERE conversation_id = %s"
    with conn.cursor() as cur:
        cur.execute(query, (conversation_id,))
        return cur.fetchone() is not None

# =============================================================================
# LLM FUNCTIONS
# =============================================================================

def format_conversation_for_llm(messages):
    """Formatiert Messages für LLM Prompt."""
    formatted = []
    for msg in messages:
        timestamp = msg['created_at'].strftime("%H:%M")
        formatted.append(f"[{timestamp}] USER: {msg['query']}")
        formatted.append(f"[{timestamp}] BOT: {msg['answer'][:2000]}...")  # Truncate lange Antworten
    return "\n\n".join(formatted)

def call_llm(prompt):
    """Ruft lokales LLM auf."""
    try:
        response = requests.post(
            LLM_URL,
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": "Du antwortest nur mit validem JSON. Kein anderer Text."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 2000
            },
            timeout=120
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        print(f"  ❌ LLM Error: {e}")
        return None

def parse_llm_response(response_text):
    """Parsed LLM JSON Response."""
    if not response_text:
        return None
    
    # Versuche JSON zu extrahieren (LLM gibt manchmal Markdown zurück)
    text = response_text.strip()
    
    # Entferne mögliche Markdown Code-Blöcke
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        print(f"  ⚠ JSON Parse Error: {e}")
        print(f"  Raw response: {text[:500]}...")
        return None

# =============================================================================
# MAIN LOGIC
# =============================================================================

def summarize_conversation(conn, conversation):
    """Fasst eine Conversation zusammen und speichert sie."""
    conv_id = conversation['id']
    
    print(f"\n→ Processing: {conv_id}")
    print(f"  Name: {conversation['name']}")
    print(f"  Messages: {conversation['message_count']}")
    
    # Bereits verarbeitet?
    if is_already_processed(conn, conv_id):
        print(f"  ⏭ Already processed, skipping")
        return None
    
    # Messages holen
    messages = get_conversation_messages(conn, conv_id)
    if len(messages) < MIN_MESSAGES:
        print(f"  ⏭ Too few messages ({len(messages)}), skipping")
        return None
    
    # Für LLM formatieren
    conversation_text = format_conversation_for_llm(messages)
    prompt = SUMMARY_PROMPT.format(conversation=conversation_text)
    
    # LLM aufrufen
    print(f"  🤖 Asking LLM...")
    raw_response = call_llm(prompt)
    
    if not raw_response:
        print(f"  ❌ No LLM response")
        return None
    
    # JSON parsen
    summary_data = parse_llm_response(raw_response)
    
    if not summary_data:
        # Fallback: Speichere raw response
        summary_data = {
            "context": conversation['name'] or "Unknown session",
            "what_we_did": [],
            "decisions": [],
            "files_changed": [],
            "open_questions": [],
            "next_steps": []
        }
        print(f"  ⚠ JSON parse failed, saving fallback")
    
    # In DB speichern
    session_date = conversation['created_at'].date()
    summary_id = save_session_summary(
        conn, conv_id, conversation['app_id'], 
        session_date, summary_data, raw_response
    )
    
    print(f"  ✅ Gespeichert: {summary_id}")
    print(f"     Context: {summary_data.get('context', 'N/A')[:60]}...")
    
    return summary_id

def main():
    parser = argparse.ArgumentParser(description="Generate session summaries from Dify conversations")
    parser.add_argument("--conversation-id", "-c", help="Specific conversation UUID")
    parser.add_argument("--since", "-s", help="Process conversations since date (YYYY-MM-DD)")
    parser.add_argument("--last", "-l", help="Process conversations from last period (e.g., 24h, 7d)")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Show what would be processed")
    args = parser.parse_args()
    
    print("=" * 60)
    print("Mora02 Session Summary Generator")
    print("=" * 60)
    
    # Zeitfilter berechnen
    since = None
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d")
    elif args.last:
        if args.last.endswith("h"):
            hours = int(args.last[:-1])
            since = datetime.now() - timedelta(hours=hours)
        elif args.last.endswith("d"):
            days = int(args.last[:-1])
            since = datetime.now() - timedelta(days=days)
    
    if since:
        print(f"Filter: Seit {since}")
    
    conn = get_db_connection()
    
    try:
        if args.conversation_id:
            # Spezifische Conversation
            conv = get_conversation_by_id(conn, args.conversation_id)
            if conv:
                conversations = [conv]
            else:
                print(f"❌ Conversation nicht gefunden: {args.conversation_id}")
                return 1
        else:
            # Alle unverarbeiteten
            conversations = get_unprocessed_conversations(conn, since)
        
        print(f"\nGefunden: {len(conversations)} Conversation(s)")
        
        if args.dry_run:
            print("\n[DRY RUN] Würde verarbeiten:")
            for conv in conversations:
                print(f"  - {conv['id']} ({conv['message_count']} msgs): {conv['name']}")
            return 0
        
        # Verarbeiten
        processed = 0
        for conv in conversations:
            result = summarize_conversation(conn, conv)
            if result:
                processed += 1
        
        print(f"\n{'=' * 60}")
        print(f"✅ Fertig: {processed}/{len(conversations)} verarbeitet")
        print("=" * 60)
        
    finally:
        conn.close()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
