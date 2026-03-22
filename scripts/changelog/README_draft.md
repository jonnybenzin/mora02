# Mora02 Changelog Builder — Automated Documentation Pipeline for AI Creative Factory

A Python script that parses chat logs from multiple sources, summarizes technical discussions, validates summaries, and generates a structured changelog for Mora02, a self-hosted AI Creative Factory. It uses multiple LLMs for different stages of processing and is designed to run on Ubuntu 24.04 with an RTX 5090 GPU.

## Quick Start

To run the full pipeline:
```bash
python3 build-changelog.py --overnight
```

To run a single phase:
```bash
python3 build-changelog.py --phase 2
```

To preview without writing files:
```bash
python3 build-changelog.py --dry-run
```

## What It Does

The script implements a 5-phase pipeline for technical documentation:

1. **Parse + Filter**  
   Extracts chat logs from ChatGPT, Claude, and Perplexity, filtering for content relevant to Mora02 using keyword matching.

2. **Summarize**  
   Uses Qwen3-14B to create technical summaries of chats, including emotional analysis of user messages.

3. **Review**  
   Uses Magistral Small to validate summaries for factual accuracy, completeness, and hallucinations.

4. **Re-Summarize**  
   Re-processes summaries marked as "FAIL" or "UNCERTAIN" in phase 3.

5. **Generate Changelog**  
   Combines Docker Compose diffs with chat summaries to produce a structured changelog in Markdown format.

## Parameters

The script uses the following configuration values:

| Parameter | Value | Description |
|---------|-------|-------------|
| `BASE` | `/opt/mora02/knowledge/changelog` | Root directory for all data |
| `LLM` | `http://localhost:8080/v1/chat/completions` | API endpoint for LLMs |
| `LLM_TIMEOUT` | `120` | Timeout in seconds for LLM calls |
| `KEYWORDS` | List of 100+ keywords | Used for filtering relevant chats |
| `DOCKER_KW` | List of 30+ Docker-related keywords | Used for matching chats to Compose diffs |

## Practical Examples

### 1. Daily Changelog Generation
```bash
python3 build-changelog.py --overnight
```
Runs all phases automatically, switching between LLM profiles as needed. Ideal for nightly documentation updates.

### 2. Manual Summary Validation
```bash
python3 build-changelog.py --phase 3 --dry-run
```
Preview phase 3 without writing files, useful for testing review prompts.

### 3. Re-Summarize Failed Entries
```bash
python3 build-changelog.py --phase 4
```
Re-processes all summaries marked as "FAIL" or "UNCERTAIN" in phase 3.

### 4. Extracting Only Compose Changes
```bash
python3 build-changelog.py --phase 5 --dry-run
```
Generates a changelog preview with only Docker Compose diffs, ignoring chat summaries.

## How It Works

The pipeline processes data in the following order:

1. **Phase 1: Parse + Filter**  
   - Parses JSON chat files from ChatGPT, Markdown files from Claude, and Perplexity  
   - Filters chats using keyword matching (100+ keywords)  
   - Trims long messages and saves relevant chats to `parsed/relevant_chats.json`

2. **Phase 2: Summarize (Qwen3-14B)**  
   - Creates technical summaries of chats (1-2 paragraphs, 100-200 words)  
   - Adds emotional analysis of user messages (1-5 scale)  
   - Saves summaries in `summaries/*.json`

3. **Phase 3: Review (Magistral Small)**  
   - Validates summaries for factual accuracy, completeness, and hallucinations  
   - Saves review results in `reviews/*.json`

4. **Phase 4: Re-Summarize**  
   - Re-processes summaries marked as "FAIL" or "UNCERTAIN" in phase 3  
   - Updates summaries in `summaries/*.json`

5. **Phase 5: Generate Changelog**  
   - Combines Docker Compose diffs with chat summaries  
   - Groups entries by date and type (COMPOSE, DECISION, DEBUG, etc.)  
   - Saves final changelog to `mora02-changelog.md`

## Directory Structure

```
/opt/mora02/knowledge/changelog/
├── chats/
│   ├── chatgpt_backup/
│   ├── claude-conversations-2026-02-09/
│   └── perplexity/
├── compose-snapshots/
├── diffs/
├── parsed/
│   ├── relevant_chats.json
│   └── chatgpt_markdown/
├── summaries/
│   └── *.json
├── reviews/
│   └── *.json
├── .state.json
└── mora02-changelog.md
```

## Dependencies

- Python 3.10+
- `requests`
- `argparse`
- `json`
- `re`
- `datetime`
- `pathlib`
- `subprocess`
- Docker Compose (for model switching)
- Qwen3-14B and Magistral Small LLMs running locally at `http://localhost:8080`

## Configuration

To modify the script, edit the following variables in the code:

- `BASE` (line 23): Root directory for all data  
- `KEYWORDS` (line 44): List of keywords for filtering relevant chats  
- `DOCKER_KW` (line 307): List of Docker-related keywords for matching chats to Compose diffs  
- `LLM` (line 26): API endpoint for LLMs  
- `LLM_TIMEOUT` (line 27): Timeout in seconds for LLM calls

## Troubleshooting

### 1. LLM Not Responding
**Symptom:** Phase 2 or 3 fails with "LLM not reachable"  
**Cause:** Qwen3-14B or Magistral Small is not running locally at `http://localhost:8080`  
**Fix:** Ensure the LLMs are running and accessible at the specified endpoint

### 2. No Chats Found
**Symptom:** Phase 1 reports 0 chats  
**Cause:** No chat files exist in the expected locations  
**Fix:** Verify that ChatGPT, Claude, and Perplexity chat files are present in the correct directories

### 3. Summary Generation Fails
**Symptom:** Phase 2 reports "LLM Timeout"  
**Cause:** Qwen3-14B is not responding or is overloaded  
**Fix:** Check Qwen3-14B status and try again later

### 4. Review Phase Fails
**Symptom:** Phase 3 reports "Review failed"  
**Cause:** Magistral Small is not responding or is overloaded  
**Fix:** Check Magistral Small status and try again later

## Shell Script Collections

### backup/
- `backup-state.sh`: Backs up the `.state.json` file
- `backup-chats.sh`: Backs up all parsed chat data

### docker/
- `switch-model.sh`: Switches between LLM profiles using Docker Compose
- `health-check.sh`: Checks if LLMs are running and accessible

### system/
- `setup-environment.sh`: Installs dependencies and sets up directories
- `cleanup.sh`: Removes temporary files and resets the pipeline state