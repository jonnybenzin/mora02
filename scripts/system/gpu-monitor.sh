#!/bin/bash
/usr/bin/gnome-terminal --geometry=100x35 -- bash -c '
    echo "═══════════════════════════════════════"
    echo "             GPU MONITOR"
    echo "═══════════════════════════════════════"
    echo
    echo "Beende mit STRG+C."
    echo
    watch -n 1 nvidia-smi
'

