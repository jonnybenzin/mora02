# Mora02 Backup Scripts — Automation for Borg Backup Management

This collection of shell scripts provides automated backup listing, execution, and pruning for a Borg backup repository hosted on a Synology NAS. It ensures consistent backup management, alerts on repository bloat, and enforces retention policies. Used in conjunction with a full system backup script (`backup-fullsystem.sh`), these tools help maintain a clean and efficient backup strategy.

## Quick Start

To list all backups in the repository:

```bash
sudo /opt/mora02/scripts/backup-list.sh
```

To run a full system backup:

```bash
sudo /opt/mora02/scripts/backup-run.sh
```

## What It Does

These scripts manage the Borg backup lifecycle:

- `backup-list.sh`: Displays the list of backups and warns if the number exceeds 500.
- `backup-run.sh`: Executes a full system backup and reports success or failure.
- `borg-prune-dryrun.sh`: Simulates pruning of old backups based on retention rules.
- `borg-prune-live.sh`: Applies the same pruning rules to actually delete old backups.

## Parameters

All scripts use the following configuration:

| Parameter | Value | Description |
|---------|-------|-------------|
| `REPO` | `/home/jonnybenzin/synology-backup` | Path to the Borg repository |
| `BORG_PASSPHRASE` | `MaGGan99@` | Encryption passphrase for the repository |
| `keep-within` | `7d` | Retain backups within the last 7 days |
| `keep-daily` | `30` | Retain 1 backup per day for the last 30 days |
| `keep-weekly` | `52` | Retain 1 backup per week for the last 52 weeks |
| `keep-monthly` | `12` | Retain 1 backup per month for the last 12 months |

## Practical Examples

### 1. Listing Backups
Used to check the number of backups in the repository and ensure it's under 500.

### 2. Running a Backup
Executed manually or via cron to ensure the system is backed up regularly.

### 3. Dry Run Pruning
Used to simulate the pruning process before applying it to avoid accidental data loss.

### 4. Live Pruning
Used to clean up the repository after confirming the dry run output.

## How It Works

1. **Backup Listing**: Connects to the Borg repository, lists all archives, and counts them.
2. **Backup Execution**: Invokes a system backup script (`backup-fullsystem.sh`) and reports the result.
3. **Pruning**: Applies retention rules using `borg prune` with either a dry run or live execution.

## Directory Structure

```
/opt/mora02/scripts/
├── backup-list.sh
├── backup-run.sh
├── borg-prune-dryrun.sh
└── borg-prune-live.sh
```

- `backup-list.sh`: Lists backups and checks for repository bloat.
- `backup-run.sh`: Triggers a full system backup.
- `borg-prune-dryrun.sh`: Simulates pruning of old backups.
- `borg-prune-live.sh`: Applies pruning rules to the repository.

## Dependencies

- **Borg Backup** (installed via `apt` or `pip`)
- **sudo** access for repository operations
- **gnome-terminal** for displaying output
- **bash** for script execution

## Configuration

- **Passphrase**: Hardcoded in all scripts (`BORG_PASSPHRASE='MaGGan99@'`)
- **Repository Path**: Hardcoded in `borg-prune-dryrun.sh` and `borg-prune-live.sh` (`REPO="/home/jonnybenzin/synology-backup"`)

## Troubleshooting

### 1. **Permission Denied**
- **Cause**: Missing `sudo` access or incorrect permissions on the repository.
- **Fix**: Ensure the user has `sudo` access and the repository is readable.

### 2. **Backup Fails with "No Such File or Directory"**
- **Cause**: `backup-fullsystem.sh` is missing or not executable.
- **Fix**: Ensure the script exists at `/root/backup-fullsystem.sh` and has proper execute permissions.

### 3. **Pruning Shows No Archives to Prune**
- **Cause**: The retention rules are too strict or the repository is too new.
- **Fix**: Adjust the `keep-*` parameters in the pruning scripts.

### 4. **Passphrase Prompt Not Working**
- **Cause**: The hardcoded `BORG_PASSPHRASE` is incorrect or not exported properly.
- **Fix**: Verify the passphrase in the script and ensure `export BORG_PASSPHRASE` is used before `borg` commands.

---

## Shell Script Collections

### backup/

- **backup-list.sh**: Displays the list of backups and warns if the count exceeds 500.
- **backup-run.sh**: Executes a full system backup and reports success or failure.
- **borg-prune-dryrun.sh**: Simulates pruning of old backups based on retention rules.
- **borg-prune-live.sh**: Applies the same pruning rules to actually delete old backups.

**Purpose**: This collection automates the lifecycle of a Borg backup repository, ensuring backups are run, listed, and pruned efficiently.