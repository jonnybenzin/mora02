# Mora02 Session Knowledge Exporter — Export session summaries from Postgres to Markdown for Dify Knowledge Base

This script reads session summaries from a PostgreSQL database and generates a structured Markdown document for use in Dify Knowledge Base. It exists to provide a centralized, machine-readable record of agent sessions that can be used for training, auditing, or documentation purposes. It is used when you need to create a knowledge base from historical session data.

## Quick Start
```bash
python3 export-sessions-to-knowledge.py
```
Exports the last 30 sessions to `/opt/mora02/data/knowledge-base/mora02-sessions-knowledge.md`.

## What It Does
The script:
- Connects to a PostgreSQL database using credentials from environment variables
- Queries the `session_summaries` table with optional filters (last N sessions, since specific date, or all sessions)
- Formats the results into a Markdown document with:
  - Session date and context
  - Actions taken
  - Decisions made with reasons
  - Files changed
  - Open questions
  - Summary statistics for the last 7 days
- Writes the output to a file in the specified output directory

## Parameters
The script accepts the following parameters:

| Parameter | Default | Description |
|---------|---------|-------------|
| `--last` | 30 | Number of recent sessions to export |
| `--since` | None | Export sessions since specific date (YYYY-MM-DD) |
| `--all` | False | Export all sessions |
| `--output` | `/opt/mora02/data/knowledge-base/mora02-sessions-knowledge.md` | Output file path |

## Practical Examples
1. **Daily summary**:
   ```bash
   python3 export-sessions-to-knowledge.py --last 24
   ```
   Used to create a daily knowledge base from the last 24 sessions.

2. **Historical analysis**:
   ```bash
   python3 export-sessions-to-knowledge.py --since 2026-01-01
   ```
   Used to analyze sessions from a specific time period.

3. **Full archive**:
   ```bash
   python3 export-sessions-to-knowledge.py --all
   ```
   Used for complete data export or backup purposes.

## How It Works
1. Establishes a connection to PostgreSQL using environment variables
2. Executes SQL queries to retrieve session data with optional filters
3. Formats the retrieved data into structured Markdown sections
4. Writes the final document to the specified output file
5. Includes summary statistics for the last 7 days

## Directory Structure
```
/opt/mora02/
├── data/
│   └── knowledge-base/
│       └── mora02-sessions-knowledge.md
```
- `data/` contains generated knowledge base files
- `knowledge-base/` stores the exported Markdown document

## Dependencies
- Python 3.10+
- psycopg2 (PostgreSQL adapter)
- Standard library modules: `argparse`, `json`, `os`, `sys`, `datetime`

## Configuration
- Database connection parameters are set in the `DB_CONFIG` dictionary (lines 26-31)
- Output directory is set in `OUTPUT_DIR` (line 24)
- Default output file is set in `OUTPUT_FILE` (line 25)

## Troubleshooting
1. **Database connection errors**:
   - Check if PostgreSQL is running
   - Verify environment variables: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
   - Ensure the `session_summaries` table exists

2. **Empty output file**:
   - Verify that there are sessions in the database matching the filter criteria
   - Check if the `session_summaries` table has data

3. **Permission denied when writing**:
   - Ensure the script has write permissions to `/opt/mora02/data/knowledge-base/`
   - Check if the user running the script has appropriate privileges

4. **Encoding issues**:
   - Ensure the script is run with UTF-8 encoding
   - Verify that the PostgreSQL database uses UTF-8 encoding

---

# Mora02 README Generator — Generates technical documentation for Mora02 scripts

This script reads Mora02 scripts and generates technical documentation using a local LLM. It exists to ensure consistent, high-quality documentation for all Mora02 components. It is used when you need to create or update README files for Mora02 scripts.

## Quick Start
```bash
python3 generate-readmes.py
```
Generates README drafts for all target scripts in `/opt/mora02/scripts/`.

## What It Does
The script:
- Reads scripts from the `/opt/mora02/scripts/` directory
- Sends the code to a local LLM (Qwen3-14B) for documentation generation
- Saves the generated README in each script's directory as `README_draft.md`
- Provides a summary of the generation process

## Parameters
The script uses the following configuration:

| Parameter | Default | Description |
|---------|---------|-------------|
| `LLM_URL` | `http://localhost:8080/v1/chat/completions` | URL of the local LLM service |
| `LLM_MODEL` | `qwen3-14b` | Model to use for documentation generation |
| `SCRIPTS_DIR` | `/opt/mora02/scripts` | Base directory for scripts |

## Practical Examples
1. **Generate documentation for all scripts**:
   ```bash
   python3 generate-readmes.py
   ```
   Used to create or update documentation for all Mora02 components.

2. **Generate documentation for a specific script**:
   ```bash
   python3 generate-readmes.py --target changelog
   ```
   Used to focus on a specific script or directory.

3. **Review and finalize documentation**:
   ```bash
   for d in gifer pexels pixabay; do
       mv /opt/mora02/scripts/$d/README_draft.md /opt/mora02/scripts/$d/README.md
   done
   ```
   Used to finalize documentation after review.

## How It Works
1. Reads scripts from the target directories
2. Sends the code to a local LLM with a detailed prompt for documentation
3. Saves the generated README in each script's directory
4. Provides a summary of the generation process

## Directory Structure
```
/opt/mora02/scripts/
├── gifer/
│   ├── gifer.py
│   └── README_draft.md
├── pexels/
│   ├── pexels.py
│   └── README_draft.md
├── backup/
│   ├── backup.sh
│   └── README_draft.md
└── changelog/
    ├── build-changelog.py
    └── README_draft.md
```
- Each script directory contains the source code and generated README draft

## Dependencies
- Python 3.10+
- `requests` for LLM communication
- `urllib.request` for HTTP requests
- `json` for data serialization
- `os`, `sys`, `pathlib` for file operations

## Configuration
- LLM URL and model are set in `LLM_URL` and `LLM_MODEL` (lines 15-16)
- Script directory is set in `SCRIPTS_DIR` (line 14)
- Target scripts are defined in `TARGETS` (lines 19-28)

## Troubleshooting
1. **LLM connection errors**:
   - Ensure the LLM service is running at the specified URL
   - Check if the LLM model is available
   - Verify network connectivity between the script and LLM service

2. **Empty or incomplete README**:
   - Check if the script is properly formatted
   - Ensure the LLM has enough context to generate documentation
   - Verify that the prompt is correctly configured

3. **Permission denied when writing**:
   - Ensure the script has write permissions to `/opt/mora02/scripts/`
   - Check if the user running the script has appropriate privileges

4. **Generated README is too long**:
   - The script automatically truncates long code samples
   - Review the generated README and manually edit if necessary

---

# Mora02 Session Summary Generator — Summarizes Dify conversations and stores in PostgreSQL

This script reads Dify conversations from PostgreSQL, summarizes them using a local LLM, and stores the structured summary in the database. It exists to create a centralized record of agent sessions that can be used for analysis, auditing, or knowledge base generation. It is used when you need to process and store session data from Dify.

## Quick Start
```bash
python3 generate-session-summary.py
```
Processes all unprocessed conversations and stores summaries in the database.

## What It Does
The script:
- Connects to a PostgreSQL database using credentials from environment variables
- Queries the `conversations` table for unprocessed conversations
- Sends conversation data to a local LLM (Qwen3-14B) for summarization
- Stores the structured summary in the `session_summaries` table
- Includes context, actions taken, decisions made, files changed, open questions, and next steps

## Parameters
The script accepts the following parameters:

| Parameter | Default | Description |
|---------|---------|-------------|
| `--conversation-id` | None | Process a specific conversation by UUID |
| `--since` | None | Process conversations since specific date (YYYY-MM-DD) |
| `--last` | None | Process conversations from last period (e.g., 24h, 7d) |
| `--dry-run` | False | Show what would be processed without actually processing |

## Practical Examples
1. **Process all unprocessed conversations**:
   ```bash
   python3 generate-session-summary.py
   ```
   Used to create summaries for all unprocessed conversations.

2. **Process a specific conversation**:
   ```bash
   python3 generate-session-summary.py --conversation-id 123e4567-e89b-12d3-a456-426614174000
   ```
   Used to process a specific conversation for detailed analysis.

3. **Process conversations from the last 24 hours**:
   ```bash
   python3 generate-session-summary.py --last 24h
   ```
   Used to create summaries for recent conversations.

## How It Works
1. Establishes a connection to PostgreSQL using environment variables
2. Queries the `conversations` table for unprocessed conversations
3. Sends conversation data to a local LLM for summarization
4. Stores the structured summary in the `session_summaries` table
5. Includes context, actions taken, decisions made, files changed, open questions, and next steps

## Directory Structure
```
/opt/mora02/scripts/
├── generate-session-summary.py
├── README_draft.md
```
- The script file and its generated documentation are stored in the scripts directory

## Dependencies
- Python 3.10+
- psycopg2 (PostgreSQL adapter)
- `requests` for LLM communication
- Standard library modules: `argparse`, `json`, `os`, `sys`, `datetime`, `uuid`

## Configuration
- Database connection parameters are set in the `DB_CONFIG` dictionary (lines 26-31)
- LLM URL and model are set in `LLM_URL` and `LLM_MODEL` (lines 44-45)
- Minimum messages threshold is set in `MIN_MESSAGES` (line 33)

## Troubleshooting
1. **Database connection errors**:
   - Check if PostgreSQL is running
   - Verify environment variables: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
   - Ensure the `conversations` and `session_summaries` tables exist

2. **LLM connection errors**:
   - Ensure the LLM service is running at the specified URL
   - Check if the LLM model is available
   - Verify network connectivity between the script and LLM service

3. **Empty or incomplete summaries**:
   - Check if the conversation data is properly formatted
   - Ensure the LLM has enough context to generate summaries
   - Verify that the prompt is correctly configured

4. **Permission denied when writing**:
   - Ensure the script has write permissions to the database
   - Check if the user running the script has appropriate privileges

---

# Shell Script Collections

## backup.sh — Archive old directories
**One-liner**: Archives old directories to a subdirectory named `x_archiv` with a retention policy.

**Purpose**: Maintains a clean directory structure by archiving old folders while keeping the most recent ones.

## directory-info.sh — Document directory structure
**One-liner**: Generates a Markdown document of the directory structure and key files.

**Purpose**: Creates a technical documentation of the file system layout for auditing, onboarding, or reference.

## Other Scripts
- **archive.sh**: Archives old directories with a retention policy
- **directory-info.sh**: Documents the directory structure and key files
- **Other shell scripts**: Additional utilities for system management and maintenance

**Collection Purpose**: Provides a set of shell scripts for system maintenance, backup, and documentation tasks.