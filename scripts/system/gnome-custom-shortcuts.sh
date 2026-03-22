#!/bin/bash
dbus-send --print-reply --dest=org.gnome.Shell /org/gnome/Shell org.gnome.Shell.ShowOSD 2>/dev/null || gnome-control-center keyboard

