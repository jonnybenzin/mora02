#!/usr/bin/env python3
"""
Mora02 Changelog Builder
========================
Pipeline:
  Phase 1: Parse + Filter (kein LLM)
  Phase 2: Zusammenfassen (Qwen3-14B)
  Phase 3: Prüfen (Magistral Small)
  Phase 4: Re-Summarize FAIL/UNCERTAIN (Qwen3-14B)
  Phase 5: Matching + Changelog generieren

Usage:
    python3 build-changelog.py                  # Nur Phase 1
    python3 build-changelog.py --phase 1-5      # Einzelne Phase
    python3 build-changelog.py --overnight      # Alles mit auto Model-Switch
    python3 build-changelog.py --dry-run        # Preview
    python3 build-changelog.py --reset          # State löschen
"""
import argparse, json, os, re, subprocess, sys, time, requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# === CONFIG ===
BASE = Path("/opt/mora02/knowledge/changelog")
CHATGPT_JSON = BASE / "chats/chatgpt_backup/conversations.json"
CLAUDE_DIR = BASE / "chats/claude-conversations-2026-02-09"
PERPLEXITY_DIR = BASE / "chats/perplexity"
COMPOSE_DIR = BASE / "compose-snapshots"
DIFFS_DIR = BASE / "diffs"
PARSED = BASE / "parsed"
SUMMARIES = BASE / "summaries"
REVIEWS = BASE / "reviews"
OUTPUT = BASE / "mora02-changelog.md"
STATEF = BASE / ".state.json"
DOCKER_DIR = Path("/opt/mora02/docker")
LLM = "http://localhost:8080/v1/chat/completions"
LLM_TIMEOUT = 120

KEYWORDS = [
    "mora02","mora 02","docker","compose","container","dify","baserow",
    "activepieces","comfyui","comfy ui","nginx","weaviate","ollama",
    "searxng","postiz","penpot","excalidraw","wireguard","vpn",
    "qwen","llama","llm","vram","gpu","rtx","cuda","nvidia",
    "ubuntu","linux","borg","backup","synology","creative factory",
    "knowledge-api","script-runner","workflow","automation","webhook",
    "social media","linkedin","content strateg","fine-tun","finetuning",
    "self-host","lokal","open source","api key","prompt","agent","chatflow",
    "image generat","text-to-image","img2img","mixpost","mattermost",
    "loki","promtail","grafana","logging",
    "8080","8085","8089","8090","8091","8092","8094","8095","8097",
    "8100","8101","8102","8188","/opt/mora02","mora02-net",
    "ssd","hardware","mainboard","netzteil","ryzen",
    "librechat","libre chat","libre-chat",
    "logitech","fehlermeldung","error log",
    "systemanweisung","system prompt","system-report",
    "dual boot","windows",
    "borgbackup","borg backup",
    "mein setup","mein system","mein stack",
    "port","localhost","healthcheck",
]

# === STATE ===
def load_state():
    if STATEF.exists():
        with open(STATEF) as f: return json.load(f)
    return {"p2":[],"p3":[]}

def save_state(s):
    with open(STATEF,"w") as f: json.dump(s,f,indent=2)

# === MODEL SWITCH ===
def switch_model(profile, timeout=90):
    print(f"\n{'='*60}\n  MODELL → {profile}\n{'='*60}")
    for p in ["qwen3-14b","qwen3-8b","magistral"]:
        subprocess.run(["docker","compose","--profile",p,"stop"],cwd=DOCKER_DIR,capture_output=True)
        subprocess.run(["docker","compose","--profile",p,"rm","-f"],cwd=DOCKER_DIR,capture_output=True)
    time.sleep(3)
    r = subprocess.run(["docker","compose","--profile",profile,"up","-d"],cwd=DOCKER_DIR,capture_output=True,text=True)
    if r.returncode != 0:
        print(f"  FEHLER: {r.stderr}"); return False
    print("  Health Check...",end="",flush=True)
    for i in range(timeout):
        try:
            if requests.get("http://localhost:8080/health",timeout=3).ok:
                print(f" OK ({i+1}s)"); return True
        except: pass
        time.sleep(1)
        if i%10==9: print(".",end="",flush=True)
    print(f" TIMEOUT!"); return False

# === LLM ===
def llm_call(sys_p, usr_p, temp=0.3):
    try:
        r = requests.post(LLM,json={"messages":[{"role":"system","content":sys_p},{"role":"user","content":usr_p}],"temperature":temp,"max_tokens":2048},timeout=LLM_TIMEOUT)
        if r.ok:
            c = r.json()["choices"][0]["message"]["content"]
            return re.sub(r'<think>.*?</think>','',c,flags=re.DOTALL).strip()
        print(f"  LLM {r.status_code}"); return None
    except requests.exceptions.Timeout:
        print("  LLM Timeout"); return None
    except Exception as e:
        print(f"  LLM: {e}"); return None

# === PHASE 1: PARSE ===
def parse_chatgpt():
    if not CHATGPT_JSON.exists(): return []
    with open(CHATGPT_JSON,"r",encoding="utf-8") as f: convs = json.load(f)
    chats = []
    for conv in convs:
        title = conv.get("title","Untitled")
        ct = conv.get("create_time",0)
        mapping = conv.get("mapping",{})
        root = next((nid for nid,n in mapping.items() if n.get("parent") is None), None)
        if not root: continue
        msgs, cur = [], root
        while cur:
            node = mapping.get(cur,{})
            msg = node.get("message")
            if msg:
                ct2 = msg.get("content",{}).get("content_type","")
                role = msg.get("author",{}).get("role","")
                if ct2=="text" and role in ("user","assistant"):
                    parts = msg.get("content",{}).get("parts",[])
                    txt = "\n".join(str(p) for p in parts if isinstance(p,str) and p.strip())
                    if txt: msgs.append({"role":role,"text":txt})
            children = node.get("children",[])
            cur = children[0] if children else None
        if len(msgs)>=2:
            try: dt=datetime.fromtimestamp(ct); ds=dt.strftime("%Y-%m-%d"); ts=dt.strftime("%H:%M")
            except: ds=ts="unknown"
            chats.append({"source":"chatgpt","title":title,"date":ds,"time":ts,"timestamp":ct,"messages":msgs,"message_count":len(msgs)})
    return chats

def parse_claude():
    if not CLAUDE_DIR.exists(): return []
    chats = []
    for mf in sorted(CLAUDE_DIR.glob("*.md")):
        content = mf.read_text(encoding="utf-8")
        tm = re.search(r"^# (.+)$",content,re.MULTILINE)
        title = tm.group(1) if tm else mf.stem
        cm = re.search(r"\*\*Created:\*\*\s*(.+)",content)
        mm = re.search(r"\*\*Model:\*\*\s*(.+)",content)
        ds,ts,stamp = "unknown","unknown",0
        if cm:
            for fmt in ["%d.%m.%Y, %H:%M:%S","%m/%d/%Y, %H:%M:%S","%Y-%m-%d, %H:%M:%S"]:
                try:
                    dt=datetime.strptime(cm.group(1).strip(),fmt)
                    ds=dt.strftime("%Y-%m-%d"); ts=dt.strftime("%H:%M"); stamp=dt.timestamp(); break
                except: continue
        msgs = []
        for block in re.split(r"\n---\n",content):
            block=block.strip()
            if block.startswith("**You**:"):
                txt=re.sub(r"^\*\*You\*\*:\s*","",block)
                txt=re.sub(r"\n\*[\d.,:\s]+\*\s*$","",txt)
                if txt.strip(): msgs.append({"role":"user","text":txt.strip()})
            elif block.startswith("**Claude**:"):
                txt=re.sub(r"^\*\*Claude\*\*:\s*","",block)
                txt=re.sub(r"\n\*[\d.,:\s]+\*\s*$","",txt)
                if txt.strip(): msgs.append({"role":"assistant","text":txt.strip()})
        if len(msgs)>=2:
            chats.append({"source":"claude","title":title,"date":ds,"time":ts,"timestamp":stamp,"messages":msgs,"message_count":len(msgs),"model":mm.group(1).strip() if mm else "?","filename":mf.name})
    return chats

def parse_perplexity():
    if not PERPLEXITY_DIR.exists(): return []
    chats = []
    for mf in sorted(PERPLEXITY_DIR.glob("*.md")):
        if mf.name.startswith("_"): continue
        content = mf.read_text(encoding="utf-8")
        tm = re.search(r"^# (.+)$",content,re.MULTILINE)
        title = (tm.group(1) if tm else mf.stem)[:100]
        ds,ts,stamp = "unknown","unknown",0
        # Erst **Created:** suchen (vom inject-script)
        cm = re.search(r"\*\*Created:\*\*\s*(.+)",content,re.IGNORECASE)
        if cm:
            raw = cm.group(1).strip()
            for fmt in ["%d.%m.%Y, %H:%M:%S","%d.%m.%Y"]:
                try:
                    dt=datetime.strptime(raw,fmt)
                    ds=dt.strftime("%Y-%m-%d"); ts=dt.strftime("%H:%M"); stamp=dt.timestamp(); break
                except: continue
        # Fallback: mtime
        if ds == "unknown":
            try:
                mt=mf.stat().st_mtime; dt=datetime.fromtimestamp(mt)
                ds=dt.strftime("%Y-%m-%d"); ts=dt.strftime("%H:%M"); stamp=mt
            except: pass
        msgs = []
        if tm:
            q = tm.group(1)
            a = content[tm.end():]
            a = re.sub(r'<img[^>]+/?>','',a)
            a = re.sub(r'\[\^\w+\]','',a).strip()
            if q and a: msgs=[{"role":"user","text":q},{"role":"assistant","text":a}]
        if len(msgs)>=2:
            chats.append({"source":"perplexity","title":title,"date":ds,"time":ts,"timestamp":stamp,"messages":msgs,"message_count":len(msgs),"filename":mf.name})
    return chats

def is_relevant(chat):
    s = chat["title"].lower()+" "+" ".join(m["text"].lower()[:500] for m in chat["messages"][:4])
    score = sum(1 for kw in KEYWORDS if kw.lower() in s)
    # ChatGPT/Perplexity: fast alles Mora02, Threshold 1
    # Claude: auch Nicht-Mora02-Chats, Threshold 2
    threshold = 2 if chat.get("source") == "claude" else 1
    return score >= threshold

def run_phase1(dry_run=False):
    print(f"\n{'='*60}\n  PHASE 1: Parse + Filter\n{'='*60}")
    PARSED.mkdir(parents=True,exist_ok=True)
    print("\n[1a] Parsen...")
    gpt=parse_chatgpt(); print(f"  ChatGPT:    {len(gpt)}")
    cld=parse_claude(); print(f"  Claude:     {len(cld)}")
    ppl=parse_perplexity(); print(f"  Perplexity: {len(ppl)}")
    all_c = gpt+cld+ppl
    print(f"\n  GESAMT: {len(all_c)}")
    print("\n[1b] Filtern...")
    rel = [c for c in all_c if is_relevant(c)]
    irr = [c for c in all_c if not is_relevant(c)]
    print(f"  ✅ Relevant:   {len(rel)}")
    print(f"  ❌ Irrelevant: {len(irr)}")
    if irr:
        print("\n  Aussortiert:")
        for c in irr: print(f"    [{c['source']:10}] {c['date']} | {c['title'][:60]}")
    rel.sort(key=lambda c: c.get("timestamp",0))
    if not dry_run:
        for chat in rel:
            tot,trimmed=0,[]
            for m in chat["messages"]:
                if tot+len(m["text"])>8000:
                    trimmed.append({"role":m["role"],"text":m["text"][:max(500,8000-tot)]+"\n[...]"}); break
                trimmed.append(m); tot+=len(m["text"])
            chat["messages_trimmed"]=trimmed
        with open(PARSED/"relevant_chats.json","w",encoding="utf-8") as f:
            json.dump(rel,f,ensure_ascii=False,indent=2,default=str)
        # ChatGPT → Markdown
        md=PARSED/"chatgpt_markdown"; md.mkdir(exist_ok=True)
        for c in rel:
            if c["source"]=="chatgpt":
                safe=re.sub(r'[^\w\-]','_',c["title"])[:50]
                with open(md/f"{c['date']}_{safe}.md","w",encoding="utf-8") as f:
                    f.write(f"# {c['title']}\n\n**Source:** ChatGPT\n**Date:** {c['date']} {c['time']}\n\n---\n\n")
                    for m in c["messages"]:
                        r2="**You**" if m["role"]=="user" else "**Assistant**"
                        f.write(f"{r2}:\n\n{m['text']}\n\n---\n\n")
        print(f"\n  Gespeichert: {PARSED}/relevant_chats.json")
    return rel

# === PHASE 2: SUMMARIZE (Qwen3-14B) ===
SUM_SYS = """Du bist ein technischer Dokumentar für "Mora02" – eine selbstgehostete AI Creative Factory.

Fasse den Chat-Verlauf als zusammenhängenden Fließtext zusammen (1-2 Absätze, 100-200 Wörter).

Enthalten soll:
- Ziel/Ausgangssituation
- Was besprochen, ausprobiert, entschieden wurde
- Konkrete Änderungen (Pfade, Container, Configs)
- Was anders lief als geplant und warum
- Ergebnis / Stand danach

Regeln: Dritte Person. Technisch präzise (Container-Namen, Pfade, Ports exakt). Keine Füllwörter. Bei reiner Planung ohne Änderungen das sagen.

Bewerte ZUSÄTZLICH die Emotionalität des USER (nicht des Assistants) an drei Stellen:
- Anfang des Chats (erste 2-3 User-Nachrichten)
- Mitte des Chats
- Ende des Chats (letzte 2-3 User-Nachrichten)

Skala: 1=vollkommen sachlich 2=überwiegend sachlich 3=normal 4=emotional/frustriert/begeistert 5=sehr emotional

Antworte EXAKT in diesem Format:
SUMMARY: [Dein Fließtext hier]
EMOTION_START: [1-5]
EMOTION_MID: [1-5]
EMOTION_END: [1-5]"""

def run_phase2(dry_run=False):
    print(f"\n{'='*60}\n  PHASE 2: Zusammenfassen (Qwen3-14B)\n{'='*60}")
    SUMMARIES.mkdir(parents=True,exist_ok=True)
    cf=PARSED/"relevant_chats.json"
    if not cf.exists(): print("  Erst --phase 1"); return
    with open(cf,"r",encoding="utf-8") as f: chats=json.load(f)
    state=load_state(); done=set(state.get("p2",[]));
    pending=[(f"{c['source']}_{c['date']}_{c['title'][:30]}",c) for c in chats if f"{c['source']}_{c['date']}_{c['title'][:30]}" not in done]
    print(f"\n  Gesamt: {len(chats)}, erledigt: {len(done)}, ausstehend: {len(pending)}")
    if dry_run:
        for cid,c in pending[:10]: print(f"    [{c['source']}] {c['date']} - {c['title'][:60]}"); return
    try: requests.get("http://localhost:8080/health",timeout=5).raise_for_status()
    except: print("  LLM nicht erreichbar!"); return
    ok,fail=0,0
    for i,(cid,chat) in enumerate(pending):
        sid=re.sub(r'[^\w\-]','_',cid)
        print(f"\n  [{i+1}/{len(pending)}] {chat['source']} | {chat['date']} | {chat['title'][:50]}")
        msgs=chat.get("messages_trimmed",chat["messages"])
        txt="".join(f"\n{'USER' if m['role']=='user' else 'ASSISTANT'}:\n{m['text']}\n" for m in msgs)
        result=llm_call(SUM_SYS,f"Titel: {chat['title']}\nDatum: {chat['date']}\nQuelle: {chat['source']}\n\n{txt}")
        if result:
            # Parse summary and emotion scores
            summary_text = result
            emotion = {"start":3,"mid":3,"end":3}
            sm = re.search(r'SUMMARY:\s*(.+?)(?=\nEMOTION_START:)',result,re.DOTALL)
            if sm: summary_text = sm.group(1).strip()
            for key,tag in [("start","EMOTION_START"),("mid","EMOTION_MID"),("end","EMOTION_END")]:
                em = re.search(rf'{tag}:\s*([1-5])',result)
                if em: emotion[key] = int(em.group(1))
            d={"chat_id":cid,"source":chat["source"],"title":chat["title"],"date":chat["date"],"time":chat.get("time",""),"timestamp":chat.get("timestamp",0),"summary":summary_text,"emotion":emotion,"message_count":chat.get("message_count",0),"by":"qwen3-14b","at":datetime.now().isoformat()}
            with open(SUMMARIES/f"{sid}.json","w",encoding="utf-8") as f: json.dump(d,f,ensure_ascii=False,indent=2)
            state.setdefault("p2",[]).append(cid); save_state(state); ok+=1
            print(f"    ✅ {len(result)} Zeichen")
        else: fail+=1; print("    ❌")
    print(f"\n  Phase 2: {ok} OK, {fail} FAIL")

# === PHASE 3: REVIEW (Magistral) ===
REV_SYS = """Du bist Qualitätsprüfer für technische Dokumentation.

Du bekommst Original-Chat und Zusammenfassung. Prüfe:
1. FAKTEN: Stimmen Container-Namen, Pfade, Ports, Entscheidungen?
2. VOLLSTÄNDIGKEIT: Wurde Wichtiges weggelassen?
3. HALLUZINATION: Wurde etwas behauptet das NICHT im Original steht?

Antworte EXAKT so:
VERDICT: PASS|FAIL|UNCERTAIN
ISSUES: [Probleme oder "keine"]
MISSING: [Was fehlt oder "nichts"]
HALLUCINATED: [Was erfunden oder "nichts"]"""

def run_phase3(dry_run=False):
    print(f"\n{'='*60}\n  PHASE 3: Prüfen (Magistral)\n{'='*60}")
    REVIEWS.mkdir(parents=True,exist_ok=True)
    sfiles=list(SUMMARIES.glob("*.json"))
    if not sfiles: print("  Keine Summaries. Erst --phase 2"); return
    with open(PARSED/"relevant_chats.json","r",encoding="utf-8") as f: chats=json.load(f)
    cmap={f"{c['source']}_{c['date']}_{c['title'][:30]}":c for c in chats}
    state=load_state(); done=set(state.get("p3",[]));
    pending=[s for s in sfiles if s.stem not in done]
    print(f"\n  Summaries: {len(sfiles)}, geprüft: {len(done)}, ausstehend: {len(pending)}")
    if dry_run:
        for s in pending[:10]: print(f"    {s.stem[:60]}"); return
    try: requests.get("http://localhost:8080/health",timeout=5).raise_for_status()
    except: print("  LLM nicht erreichbar!"); return
    stats={"PASS":0,"FAIL":0,"UNCERTAIN":0}
    for i,sf in enumerate(pending):
        with open(sf,"r",encoding="utf-8") as f: sd=json.load(f)
        chat=cmap.get(sd["chat_id"])
        print(f"\n  [{i+1}/{len(pending)}] {sd['source']} | {sd['date']} | {sd['title'][:50]}")
        if not chat: print("    ⚠️ Original fehlt"); continue
        msgs=chat.get("messages_trimmed",chat["messages"])
        orig="".join(f"\n{'USER' if m['role']=='user' else 'ASSISTANT'}:\n{m['text'][:1000]}\n" for m in msgs[:10])
        result=llm_call(REV_SYS,f"ORIGINAL:\n{orig}\n\nZUSAMMENFASSUNG:\n{sd['summary']}",temp=0.1)
        if result:
            v="UNCERTAIN"
            vm=re.search(r'VERDICT:\s*(PASS|FAIL|UNCERTAIN)',result,re.I)
            if vm: v=vm.group(1).upper()
            im=re.search(r'ISSUES:\s*(.+?)(?:\n|$)',result)
            mm2=re.search(r'MISSING:\s*(.+?)(?:\n|$)',result)
            hm=re.search(r'HALLUCINATED:\s*(.+?)(?:\n|$)',result)
            rv={"chat_id":sd["chat_id"],"verdict":v,"issues":im.group(1).strip() if im else "","missing":mm2.group(1).strip() if mm2 else "","hallucinated":hm.group(1).strip() if hm else "","raw":result,"by":"magistral","at":datetime.now().isoformat()}
            with open(REVIEWS/f"{sf.stem}.json","w",encoding="utf-8") as f: json.dump(rv,f,ensure_ascii=False,indent=2)
            state.setdefault("p3",[]).append(sf.stem); save_state(state)
            stats[v]+=1
            sym={"PASS":"✅","FAIL":"❌","UNCERTAIN":"⚠️"}[v]
            print(f"    {sym} {v}")
        else: print("    ❌ Review failed")
    print(f"\n  Phase 3: {stats['PASS']} PASS, {stats['FAIL']} FAIL, {stats['UNCERTAIN']} UNCERTAIN")

# === PHASE 4: RE-SUMMARIZE ===
RESUM_SYS = """Du bist technischer Dokumentar für "Mora02". Eine Zusammenfassung wurde bemängelt.

Du bekommst Original-Chat, alte Zusammenfassung und Feedback. Schreibe eine VERBESSERTE Version (1-2 Absätze, 100-200 Wörter).

Behebe alle Probleme, füge Fehlendes hinzu, entferne Erfundenes. Dritte Person, präzise. NUR Fließtext."""

def run_phase4(dry_run=False):
    print(f"\n{'='*60}\n  PHASE 4: Re-Summarize\n{'='*60}")
    redo=[]
    for rf in REVIEWS.glob("*.json"):
        with open(rf) as f: rv=json.load(f)
        if rv["verdict"] in ("FAIL","UNCERTAIN"): redo.append((rf.stem,rv))
    print(f"\n  FAIL/UNCERTAIN: {len(redo)}")
    if not redo: print("  Alles PASS!"); return
    with open(PARSED/"relevant_chats.json","r",encoding="utf-8") as f: chats=json.load(f)
    cmap={f"{c['source']}_{c['date']}_{c['title'][:30]}":c for c in chats}
    if dry_run:
        for stem,rv in redo: print(f"    {rv['verdict']}: {stem[:60]}"); return
    ok=0
    for i,(stem,rv) in enumerate(redo):
        sf=SUMMARIES/f"{stem}.json"
        if not sf.exists(): continue
        with open(sf) as f: sd=json.load(f)
        chat=cmap.get(rv["chat_id"])
        print(f"\n  [{i+1}/{len(redo)}] {rv['chat_id'][:60]}")
        if not chat: continue
        msgs=chat.get("messages_trimmed",chat["messages"])
        orig="".join(f"\n{'USER' if m['role']=='user' else 'ASSISTANT'}:\n{m['text'][:1000]}\n" for m in msgs[:10])
        prompt=f"ORIGINAL:\n{orig}\n\nALTE ZUSAMMENFASSUNG:\n{sd['summary']}\n\nFEEDBACK:\n{rv['verdict']}: {rv['issues']}\nFehlend: {rv['missing']}\nErfunden: {rv['hallucinated']}"
        result=llm_call(RESUM_SYS,prompt)
        if result:
            sd["summary_v1"]=sd["summary"]; sd["summary"]=result; sd["re_summarized"]=True
            with open(sf,"w",encoding="utf-8") as f: json.dump(sd,f,ensure_ascii=False,indent=2)
            ok+=1; print(f"    ✅ {len(result)} Zeichen")
        else: print("    ❌")
    print(f"\n  Phase 4: {ok}/{len(redo)} neu")

# === PHASE 5: CHANGELOG ===
def run_phase5(dry_run=False):
    print(f"\n{'='*60}\n  PHASE 5: Changelog generieren\n{'='*60}")
    sums=[]
    for sf in sorted(SUMMARIES.glob("*.json")):
        with open(sf) as f: sums.append(json.load(f))
    # Compose diffs
    changes=[]
    if COMPOSE_DIR.exists():
        snaps=sorted(COMPOSE_DIR.glob("*.yml"))
        for i,snap in enumerate(snaps):
            content=snap.read_text(encoding="utf-8")
            try: dt=datetime.strptime(snap.stem,"%Y-%m-%d_%H-%M")
            except: continue
            containers=re.findall(r'container_name:\s*(\S+)',content)
            added,removed=[],[]
            if i>0:
                df=DIFFS_DIR/f"{snaps[i-1].stem}__to__{snap.stem}.diff"
                if df.exists():
                    for line in df.read_text(encoding="utf-8").split("\n"):
                        m=re.search(r'container_name:\s*(\S+)',line)
                        if m:
                            if line.startswith("+") and not line.startswith("+++"): added.append(m.group(1))
                            elif line.startswith("-") and not line.startswith("---"): removed.append(m.group(1))
            changes.append({"timestamp":dt,"date":dt.strftime("%Y-%m-%d"),"time":dt.strftime("%H:%M"),"containers":containers,"count":len(containers),"added":added,"removed":removed,"initial":i==0})
    print(f"\n  Summaries: {len(sums)}, Compose: {len(changes)}")
    if dry_run: return
    entries,matched=[],set()
    # Docker-relevante Keywords für Chat-Compose-Matching
    DOCKER_KW = ["docker","compose","container","port","volume","service","stack",
                 "deploy","image","nginx","dify","baserow","activepieces","comfyui",
                 "ollama","weaviate","searxng","postiz","penpot","excalidraw",
                 "librechat","mattermost","mixpost","llama-server","chroma",
                 "borg","script-runner","knowledge-api","mora02-net"]
    def is_docker_related(summary_text):
        t = summary_text.lower()
        return sum(1 for kw in DOCKER_KW if kw in t) >= 2

    # Compose + Chat matching (nur Docker-relevante Chats)
    prev_count = 0
    for ch in changes:
        cdt=ch["timestamp"]
        match=[]
        for s in sums:
            try:
                sd=datetime.strptime(s["date"],"%Y-%m-%d")
                if abs((sd-cdt).days)<=1 and is_docker_related(s.get("summary","")):
                    match.append(s); matched.add(s["chat_id"])
            except: continue
        if ch["initial"]: title=f"Initialer Stack ({ch['count']} Container)"
        else:
            p=[]
            if ch["added"]: p.append(f"+ {', '.join(ch['added'])}")
            if ch["removed"]: p.append(f"- {', '.join(ch['removed'])}")
            title="; ".join(p) if p else f"Config-Änderung ({ch['count']} Container)"
        entries.append({"date":ch["date"],"time":ch["time"],"ts":ch["timestamp"],"type":"COMPOSE","title":title,"compose":ch,"chats":match,"prev_count":prev_count})
        prev_count=ch["count"]
    # Unmatched chats
    for s in sums:
        if s["chat_id"] not in matched:
            t=s["summary"].lower()
            if any(k in t for k in ["entscheidung","entschieden","strategie"]): et="DECISION"
            elif any(k in t for k in ["debug","fehler","fix","error"]): et="DEBUG"
            elif any(k in t for k in ["design","tabelle","schema"]): et="DESIGN"
            elif any(k in t for k in ["config","prompt","einstellung"]): et="CONFIG"
            elif any(k in t for k in ["content","linkedin","social"]): et="CONTENT"
            else: et="OTHER"
            try: ts2=datetime.strptime(s["date"],"%Y-%m-%d")
            except: ts2=datetime.min
            entries.append({"date":s["date"],"time":s.get("time",""),"ts":ts2,"type":et,"title":s["title"],"compose":None,"chats":[s]})
    entries.sort(key=lambda e:e.get("ts",datetime.min))
    print(f"\n  {len(entries)} Einträge, schreibe Changelog...")
    with open(OUTPUT,"w",encoding="utf-8") as f:
        f.write(f"# Mora02 Projektchronik\n\n**Generiert:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"**Zeitraum:** {entries[0]['date'] if entries else '?'} bis {entries[-1]['date'] if entries else '?'}\n")
        f.write(f"**Einträge:** {len(entries)}\n**Quellen:** Borg Compose-Diffs, ChatGPT, Claude.ai, Perplexity\n\n")
        types={}
        for e in entries: types[e["type"]]=types.get(e["type"],0)+1
        f.write("## Übersicht\n\n| Typ | Anzahl |\n|-----|--------|\n")
        for t,c in sorted(types.items()): f.write(f"| {t} | {c} |\n")
        f.write("\n---\n\n")
        cmon=""
        for entry in entries:
            mon=entry["date"][:7]
            if mon!=cmon:
                cmon=mon
                try: mn=datetime.strptime(mon,"%Y-%m").strftime("%B %Y")
                except: mn=mon
                f.write(f"\n## {mn}\n\n")
            f.write(f"### {entry['date']} – {entry['title'][:80]} [{entry['type']}]\n\n")
            if entry["compose"]:
                ci=entry["compose"]
                f.write("```\n")
                f.write(f"🐳 DOCKER COMPOSE ÄNDERUNG\n")
                pc = entry.get("prev_count",0)
                if pc: f.write(f"   Container: {pc} → {ci['count']}\n")
                else: f.write(f"   Container: {ci['count']}\n")
                if ci["added"]: f.write(f"   ✅ Neu:     {', '.join(ci['added'])}\n")
                if ci["removed"]: f.write(f"   ❌ Entfernt: {', '.join(ci['removed'])}\n")
                f.write("```\n\n")
            if entry["chats"]:
                for cs in entry["chats"]:
                    # Emotion indicator
                    emo = cs.get("emotion",{})
                    if emo:
                        es,em2,ee = emo.get("start",3),emo.get("mid",3),emo.get("end",3)
                        bar = lambda v: "▁▂▃▅█"[v-1] if 1<=v<=5 else "▃"
                        f.write(f"📊 Emotion: {bar(es)}{bar(em2)}{bar(ee)} ({es}→{em2}→{ee})\n\n")
                    f.write(f"{cs['summary']}\n\n*Quelle: {cs['source']} – {cs['title'][:60]}*\n\n")
            else:
                f.write("*Keine Chat-Dokumentation gefunden.*\n\n")
            f.write("---\n\n")
    print(f"\n  ✅ {OUTPUT} ({OUTPUT.stat().st_size/1024:.1f} KB)")

# === OVERNIGHT ===
def run_overnight():
    print(f"\n{'='*60}\n  OVERNIGHT MODE – {datetime.now().strftime('%Y-%m-%d %H:%M')}\n{'='*60}")
    t0=time.time()
    run_phase1()
    if not switch_model("qwen3-14b"): return
    run_phase2()
    if not switch_model("magistral"): return
    run_phase3()
    if not switch_model("qwen3-14b"): return
    run_phase4()
    run_phase5()
    print(f"\n{'='*60}\n  FERTIG! {(time.time()-t0)/60:.1f} Min\n  {OUTPUT}\n{'='*60}")
    switch_model("qwen3-14b")

# === MAIN ===
def main():
    ap=argparse.ArgumentParser(description="Mora02 Changelog Builder")
    ap.add_argument("--phase",type=int,choices=[1,2,3,4,5])
    ap.add_argument("--overnight",action="store_true")
    ap.add_argument("--dry-run",action="store_true")
    ap.add_argument("--reset",action="store_true")
    args=ap.parse_args()
    for d in [PARSED,SUMMARIES,REVIEWS]: d.mkdir(parents=True,exist_ok=True)
    # Migrate old data
    old=Path("/opt/mora02/knowledge/changelog")
    if old.exists():
        for item in ["compose-snapshots","diffs","changes-overview.txt"]:
            src,dst=old/item,BASE/item
            if src.exists() and not dst.exists(): print(f"  Move {src}→{dst}"); os.rename(str(src),str(dst))
    if args.reset: STATEF.unlink(missing_ok=True); print("Reset."); return
    if args.overnight: run_overnight()
    elif args.phase: {1:run_phase1,2:run_phase2,3:run_phase3,4:run_phase4,5:run_phase5}[args.phase](args.dry_run)
    else: run_phase1(args.dry_run); print("\n  Nächster Schritt: python3 build-changelog.py --overnight")

if __name__=="__main__": main()
