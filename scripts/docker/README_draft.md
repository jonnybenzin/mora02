# Mora02 Docker Management Scripts — Shell scripts for managing Mora02 Docker containers

These scripts provide a consistent interface for managing Mora02's Docker containers, including starting, stopping, restarting, and checking the status of services. They are designed to be used in a development or production environment running on Ubuntu 24.04 with Docker Compose.

## Quick Start

To start all Mora02 Docker containers:

```bash
sudo /opt/mora02/docker/docker-up.sh
```

To stop all containers:

```bash
sudo /opt/mora02/docker/docker-down.sh
```

To restart containers:

```bash
sudo /opt/mora02/docker/docker-restart.sh
```

To check the status of containers:

```bash
sudo /opt/mora02/docker/docker-status.sh
```

## What It Does

These scripts interact with Docker Compose to manage the lifecycle of Mora02's services. They provide a consistent user interface with terminal output, status checks, and confirmation prompts. Each script opens a new GNOME Terminal window to display progress and results.

## Parameters

These scripts do not accept external parameters. All behavior is hard-coded in the script files.

## Practical Examples

1. **Starting services after a reboot**  
   Use `docker-up.sh` to ensure all Mora02 services are running after a system restart.

2. **Checking service status**  
   Use `docker-status.sh` to verify that all containers are running and to see disk usage statistics.

3. **Graceful shutdown**  
   Use `docker-down.sh` to stop all containers before maintenance or updates.

4. **Restarting services**  
   Use `docker-restart.sh` to restart containers after configuration changes or to recover from a failure.

## How It Works

Each script executes Docker Compose commands in a new terminal window. The scripts change directory to `/opt/mora02/docker` before executing commands. They use `docker compose down` to stop containers, `docker compose up -d` to start them in detached mode, and `docker compose ps` to display the current status.

## Directory Structure

```
/opt/mora02/
├── docker/
│   ├── docker-down.sh
│   ├── docker-restart.sh
│   ├── docker-status.sh
│   └── docker-up.sh
```

- `/opt/mora02/docker/`: Contains all Docker management scripts and the `docker-compose.yml` file (not shown here).

## Dependencies

- Docker and Docker Compose must be installed and running.
- GNOME Terminal must be available for script output.
- Script must be executed with `sudo` to manage Docker services.

## Configuration

No configuration is required in these scripts. All behavior is defined within the script files. If changes are needed, they must be made directly in the script files.

## Troubleshooting

1. **Permission denied when running scripts**  
   Ensure the scripts are executed with `sudo` to gain the necessary permissions for Docker commands.

2. **Terminal not opening**  
   Check if GNOME Terminal is installed and available in the system path.

3. **No output from scripts**  
   Ensure that the terminal window is not closed immediately after script execution. The scripts wait for user input before closing.

4. **Container status not updating**  
   Ensure that Docker Compose is correctly configured and that the `docker-compose.yml` file is in the correct location.

## Shell Script Collections

### backup/

- `backup-docker.sh`: Backs up Docker volumes and configurations for disaster recovery.

### docker/

- `docker-down.sh`: Stops all Mora02 Docker containers.
- `docker-restart.sh`: Stops and restarts all Mora02 Docker containers.
- `docker-status.sh`: Displays the current status of Docker containers and system information.
- `docker-up.sh`: Starts all Mora02 Docker containers.

### system/

- `system-check.sh`: Runs a system health check including disk usage, memory, and CPU.
- `system-reboot.sh`: Safely reboots the system after confirming with the user.