#!/bin/bash
VRAM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
if [ "$VRAM" -lt 5000 ]; then
    echo "$(date): GPU VRAM low ($VRAM MiB), reloading nvidia_uvm..."
    sudo rmmod nvidia_uvm
    sudo modprobe nvidia_uvm
    docker restart llama-server
    sleep 30
    echo "$(date): Fixed. VRAM now $(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) MiB"
fi
