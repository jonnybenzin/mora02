#!/usr/bin/env python3
"""
AP20: Baserow-Tabellen für Pilot Bot erstellen
"""
import requests, json, time, sys

BASEROW_URL = "http://mora02.local:8085"
EMAIL = "jonnybenzin@gmail.com"
PASSWORD = "MaGGan99@"
DATABASE_ID = 113

def get_jwt():
    resp = requests.post(f"{BASEROW_URL}/api/user/token-auth/",
        headers={"Content-Type": "application/json"},
        json={"email": EMAIL, "password": PASSWORD})
    if resp.status_code == 200:
        print("🔑 JWT ✓")
        return resp.json()["access_token"]
    print(f"✗ Login failed: {resp.status_code}"); sys.exit(1)

def h(jwt):
    return {"Authorization": f"JWT {jwt}", "Content-Type": "application/json"}

def create_field(jwt, tid, name, ftype, **kw):
    resp = requests.post(f"{BASEROW_URL}/api/database/fields/table/{tid}/",
        headers=h(jwt), json={"name": name, "type": ftype, **kw})
    if resp.status_code in [200, 201]:
        print(f"  + {name} ({ftype}) → ID: {resp.json()['id']}")
        return resp.json()
    print(f"  ✗ {name}: {resp.status_code} - {resp.text}"); return None

def delete_default_fields(jwt, tid):
    resp = requests.get(f"{BASEROW_URL}/api/database/fields/table/{tid}/", headers=h(jwt))
    if resp.status_code == 200:
        for f in resp.json():
            if f['name'] in ['Name', 'Notes', 'Active']:
                requests.delete(f"{BASEROW_URL}/api/database/fields/{f['id']}/", headers=h(jwt))
                print(f"  - Deleted default: {f['name']}")

def create_table(jwt, name):
    resp = requests.post(f"{BASEROW_URL}/api/database/tables/database/{DATABASE_ID}/",
        headers=h(jwt), json={"name": name})
    if resp.status_code in [200, 201]:
        t = resp.json()
        print(f"📋 Created '{name}' → Table ID: {t['id']}")
        return t['id']
    print(f"✗ Error: {resp.status_code} - {resp.text}"); return None

def create_row(jwt, tid, data):
    resp = requests.post(f"{BASEROW_URL}/api/database/rows/table/{tid}/?user_field_names=true",
        headers=h(jwt), json=data)
    return resp.json() if resp.status_code in [200, 201] else None

def main():
    print("=" * 50)
    print("AP20: Pilot Bot — Baserow Setup")
    print("=" * 50)

    jwt = get_jwt()

    # Lösche den leeren Default-Table 570
    print("\n🗑️  Deleting empty default table 570...")
    resp = requests.delete(f"{BASEROW_URL}/api/database/tables/570/", headers=h(jwt))
    if resp.status_code in [200, 204]:
        print("  ✓ Deleted")
    else:
        print(f"  ⚠ {resp.status_code} (vielleicht schon gelöscht)")

    time.sleep(0.3)

    # ── bot_sessions ──
    print()
    t1 = create_table(jwt, "bot_sessions")
    if not t1: sys.exit(1)
    time.sleep(0.3)
    delete_default_fields(jwt, t1)
    create_field(jwt, t1, "started_at", "date", date_include_time=True)
    create_field(jwt, t1, "ended_at", "date", date_include_time=True)
    create_field(jwt, t1, "model_used", "text")
    create_field(jwt, t1, "goal", "long_text")
    create_field(jwt, t1, "summary", "long_text")
    create_field(jwt, t1, "decisions", "long_text")
    create_field(jwt, t1, "open_items", "long_text")
    create_field(jwt, t1, "tokens_in", "number", number_decimal_places=0)
    create_field(jwt, t1, "tokens_out", "number", number_decimal_places=0)
    create_field(jwt, t1, "cost_usd", "number", number_decimal_places=4)

    # ── bot_context ──
    print()
    t2 = create_table(jwt, "bot_context")
    if not t2: sys.exit(1)
    time.sleep(0.3)
    delete_default_fields(jwt, t2)
    create_field(jwt, t2, "key", "text")
    create_field(jwt, t2, "value", "long_text")
    create_field(jwt, t2, "updated_at", "date", date_include_time=True)

    # ── Vorbefüllen ──
    print("\n📝 Populating bot_context...")
    for row in [
        {"key": "current_ap", "value": "AP20"},
        {"key": "llm_local", "value": "Qwen3-14B @ 8080"},
        {"key": "vram_free", "value": "17 GB"},
        {"key": "stack_size", "value": "26 Container"},
        {"key": "pilot_version", "value": "0.1.0"},
    ]:
        if create_row(jwt, t2, row):
            print(f"  ✓ {row['key']} = {row['value']}")

    # ── Summary ──
    print("\n" + "=" * 50)
    print("✅ DONE!")
    print(f"  bot_sessions → Table ID: {t1}")
    print(f"  bot_context  → Table ID: {t2}")
    print(f"\n⚠️  Trage in config.py ein:")
    print(f"  baserow_table_sessions: int = {t1}")
    print(f"  baserow_table_context: int = {t2}")
    print("=" * 50)

if __name__ == "__main__":
    main()
