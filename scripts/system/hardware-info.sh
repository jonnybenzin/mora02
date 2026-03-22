#!/bin/bash
# Erstellt detaillierte Hardware- und Treiber-Dokumentation

OUTPUT_FILE="/opt/mora02/knowledge/archive/$(date +%Y%m%d%H%M)_hardware-status.md"

{
    echo "# Mora02 Hardware & Treiber Status"
    echo "Erstellt: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    
    echo "## System-Basis"
    echo "**Hostname:** $(hostname)"
    echo "**OS:** $(lsb_release -d | cut -f2)"
    echo "**Kernel:** $(uname -r)"
    echo "**Uptime:** $(uptime -p)"
    echo ""
    
    echo "## CPU"
    echo '```'
    lscpu | grep -E "Model name|Thread|Core|Socket|MHz"
    echo '```'
    echo ""
    
    echo "## Arbeitsspeicher"
    echo '```'
    free -h
    echo '```'
    echo ""
    
    echo "## GPU & NVIDIA-Treiber"
    echo '```'
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
    nvidia-smi
    echo '```'
    echo ""
    
    echo "## CUDA-Version"
    echo '```'
    nvcc --version 2>/dev/null || echo "nvcc nicht installiert"
    echo '```'
    echo ""
    
    echo "## Docker-Info"
    echo '```'
    docker version --format '{{.Server.Version}}'
    docker info | grep -E "Server Version|Runtime|Runtimes|nvidia"
    echo '```'
    echo ""
    
    echo "## Speicher (Festplatten)"
    echo '```'
    df -h | grep -E "Filesystem|/dev/nvme|/opt/mora02"
    echo '```'
    echo ""
    
    echo "## Netzwerk-Interfaces"
    echo '```'
    ip -br addr
    echo '```'
    echo ""
    
    echo "## Geladene NVIDIA-Kernel-Module"
    echo '```'
    lsmod | grep nvidia
    echo '```'
    echo ""
    
    echo "## PCI-Geräte (GPU)"
    echo '```'
    lspci | grep -i vga
    lspci | grep -i nvidia
    echo '```'
    echo ""
    
    echo "## USB-Geräte"
    echo '```'
    lsusb
    echo '```'

} > "$OUTPUT_FILE"

echo "Hardware-Dokumentation erstellt: $OUTPUT_FILE"
