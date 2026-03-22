# setup-personas

Erstellt die `bot_personas` Tabelle in Baserow und fügt 7 Starter-Personas ein.
Erweitert `bot_sessions` um persona_name, persona_id, models_used.
Updated `config.py` mit der neuen Table ID.

## Nutzung
```bash
bash /opt/mora02/scripts/setup-personas/setup-personas.sh
```

## Was es tut
1. Erstellt `bot_personas` Tabelle (Database 113)
2. Fügt Felder ein: name, icon, description, prompt, briefing_target, sort_order, active, usage_count
3. Fügt 7 Personas ein: Strategist, Reviewer, Brainstormer, Ghost Writer, Debugger, Coder, Buddy
4. Erweitert `bot_sessions` um 3 Felder
5. Updated `config.py` automatisch

## Einmalig ausführen
Nur 1x nötig. Danach Personas in Baserow verwalten.
