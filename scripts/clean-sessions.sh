#!/bin/bash
for f in /opt/mora02/knowledge/sessions/claude/raw/*.log; do
    clean="${f%.log}.clean.log"
    if [ ! -f "$clean" ]; then
        ansi2txt < "$f" > "$clean"
        echo "Bereinigt: $clean"
    fi
done
