#!/usr/bin/env python3
"""
Mora02 Session Knowledge Exporter

Liest session_summaries aus Postgres und generiert ein
Knowledge Base Dokument für Dify Agents.

Usage:
    python3 export-sessions-to-knowledge.py                # Standard: letzte 30 Sessions
    python3 export-sessions-to-knowledge.py --last 50      # Letzte 50 Sessions
    python3 export-sessions-to-knowledge.py --since 2026-01-01  # Seit Datum
    python3 export-sessions-to-knowledge.py --all          # Alle Sessions
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras

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

OUTPUT_DIR = "/opt/mora02/data/knowledge-base"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "mora02-sessions-knowledge.md")

# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_db_connection():
    """Erstellt Datenbankverbindung."""
    return psycopg2.connect(**DB_CONFIG)

def get_sessions(conn, limit=30, since=None):
    """Holt Sessions aus der Datenbank."""
    query = """
        SELECT 
            ss.id,
            ss.session_date,
            ss.context,
            ss.what_we_did,
            ss.decisions,
            ss.files_changed,
            ss.open_questions,
            ss.next_steps,
            ss.created_at,
            a.name as app_name
        FROM session_summaries ss
        LEFT JOIN apps a ON a.id = ss.app_id
    """
    params = []
    
    if since:
        query += " WHERE ss.session_date >= %s"
        params.append(since)
    
    query += " ORDER BY ss.session_date DESC, ss.created_at DESC"
    
    if limit and not since:
        query += " LIMIT %s"
        params.append(limit)
    
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(query, params)
        return cur.fetchall()

def get_all_decisions(conn, limit=50):
    """Holt alle wichtigen Entscheidungen."""
    query = """
        SELECT 
            ss.session_date,
            ss.context,
            ss.decisions
        FROM session_summaries ss
        WHERE jsonb_array_length(ss.decisions) > 0
        ORDER BY ss.session_date DESC
        LIMIT %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(query, (limit,))
        return cur.fetchall()

def get_recent_activity_summary(conn, days=7):
    """Zusammenfassung der letzten X Tage."""
    since = datetime.now() - timedelta(days=days)
    query = """
        SELECT 
            COUNT(*) as session_count,
            COUNT(DISTINCT session_date) as active_days,
            SUM(jsonb_array_length(what_we_did)) as total_actions,
            SUM(jsonb_array_length(decisions)) as total_decisions
        FROM session_summaries
        WHERE session_date >= %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(query, (since.date(),))
        return cur.fetchone()

# =============================================================================
# EXPORT FUNCTIONS
# =============================================================================

def format_session(session):
    """Formatiert eine Session für Markdown."""
    lines = []
    
    date_str = session['session_date'].strftime("%Y-%m-%d")
    app_name = session['app_name'] or "Unknown Agent"
    context = session['context'] or "No description"
    
    lines.append(f"### {date_str}: {context}")
    lines.append(f"*Agent: {app_name}*")
    lines.append("")
    
    # What was done
    what_we_did = session['what_we_did'] or []
    if what_we_did:
        lines.append("**Actions:**")
        for item in what_we_did:
            action = item.get('action', 'Unknown')
            detail = item.get('detail', '')
            if detail:
                lines.append(f"- {action}: {detail}")
            else:
                lines.append(f"- {action}")
        lines.append("")
    
    # Decisions
    decisions = session['decisions'] or []
    if decisions:
        lines.append("**Decisions:**")
        for item in decisions:
            decision = item.get('decision', 'Unknown')
            reason = item.get('reason', '')
            if reason:
                lines.append(f"- {decision} — *{reason}*")
            else:
                lines.append(f"- {decision}")
        lines.append("")
    
    # Files changed
    files_changed = session['files_changed'] or []
    if files_changed:
        lines.append("**Files:**")
        for item in files_changed:
            path = item.get('path', 'Unknown')
            change = item.get('change', '')
            lines.append(f"- `{path}` ({change})")
        lines.append("")
    
    # Open questions
    open_questions = session['open_questions'] or []
    if open_questions:
        lines.append("**Open:**")
        for q in open_questions:
            lines.append(f"- {q}")
        lines.append("")
    
    return "\n".join(lines)

def format_decisions_summary(decisions_data):
    """Formatiert alle Entscheidungen als Übersicht."""
    lines = []
    lines.append("## Key Decisions (Overview)")
    lines.append("")
    lines.append("| Date | Context | Decision | Reason |")
    lines.append("|------|---------|----------|--------|")
    
    for session in decisions_data:
        date_str = session['session_date'].strftime("%Y-%m-%d")
        context = (session['context'] or "")[:30]
        
        for dec in (session['decisions'] or []):
            decision = (dec.get('decision', ''))[:40]
            reason = (dec.get('reason', ''))[:40]
            lines.append(f"| {date_str} | {context} | {decision} | {reason} |")
    
    lines.append("")
    return "\n".join(lines)

def generate_knowledge_document(sessions, decisions_data, activity_summary):
    """Generiert das komplette Knowledge Base Dokument."""
    lines = []
    
    # Header
    lines.append("# Mora02 Session Knowledge Base")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Sessions:** {len(sessions)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Activity summary
    if activity_summary:
        lines.append("## Last 7 Days")
        lines.append("")
        lines.append(f"- **Sessions:** {activity_summary['session_count'] or 0}")
        lines.append(f"- **Active Days:** {activity_summary['active_days'] or 0}")
        lines.append(f"- **Actions:** {activity_summary['total_actions'] or 0}")
        lines.append(f"- **Decisions:** {activity_summary['total_decisions'] or 0}")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # Decisions overview
    if decisions_data:
        lines.append(format_decisions_summary(decisions_data))
        lines.append("---")
        lines.append("")
    
    # Sessions detail
    lines.append("## Session Details")
    lines.append("")
    
    for session in sessions:
        lines.append(format_session(session))
        lines.append("---")
        lines.append("")
    
    return "\n".join(lines)

# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Export session summaries to Knowledge Base")
    parser.add_argument("--last", "-l", type=int, default=30, help="Number of recent sessions (default: 30)")
    parser.add_argument("--since", "-s", help="Export sessions since date (YYYY-MM-DD)")
    parser.add_argument("--all", "-a", action="store_true", help="Export all sessions")
    parser.add_argument("--output", "-o", help=f"Output file (default: {OUTPUT_FILE})")
    args = parser.parse_args()
    
    output_file = args.output or OUTPUT_FILE
    
    print("=" * 60)
    print("Mora02 Session Knowledge Exporter")
    print("=" * 60)
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    conn = get_db_connection()
    
    try:
        # Sessions holen
        since = None
        limit = args.last
        
        if args.since:
            since = datetime.strptime(args.since, "%Y-%m-%d").date()
            limit = None
        elif args.all:
            limit = None
        
        print(f"→ Lade Sessions...")
        sessions = get_sessions(conn, limit=limit, since=since)
        print(f"  Gefunden: {len(sessions)}")
        
        # Entscheidungen holen
        print(f"→ Lade Entscheidungen...")
        decisions_data = get_all_decisions(conn, limit=50)
        print(f"  Gefunden: {len(decisions_data)} Sessions mit Entscheidungen")
        
        # Aktivitäts-Summary
        print(f"→ Berechne Aktivitäts-Summary...")
        activity_summary = get_recent_activity_summary(conn)
        
        # Dokument generieren
        print(f"→ Generiere Knowledge Base...")
        document = generate_knowledge_document(sessions, decisions_data, activity_summary)
        
        # Schreiben
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(document)
        
        print(f"")
        print("=" * 60)
        print(f"✅ Exportiert: {output_file}")
        print(f"   Sessions: {len(sessions)}")
        print(f"   Größe: {len(document)} Zeichen")
        print("=" * 60)
        print("")
        print("Nächster Schritt:")
        print(f"  Lade '{output_file}' in Dify Knowledge Base hoch")
        print("")
        
    finally:
        conn.close()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
