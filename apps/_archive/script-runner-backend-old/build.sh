#!/bin/bash
# Build script for Mora02 Script Runner

echo "=== Mora02 Script Runner Build ==="

# Check if fonts exist, if not create placeholder
FONT_DIR="./fonts"
if [ ! -f "$FONT_DIR/JetBrainsMono-ExtraBold.ttf" ]; then
    echo "⚠️  Fonts not found in $FONT_DIR"
    echo "   Downloading JetBrains Mono..."
    
    mkdir -p "$FONT_DIR"
    cd "$FONT_DIR"
    
    # Download JetBrains Mono
    wget -q https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip
    unzip -q JetBrainsMono-2.304.zip
    
    # Copy needed fonts
    cp fonts/ttf/JetBrainsMono-ExtraBold.ttf .
    cp fonts/ttf/JetBrainsMono-ExtraBoldItalic.ttf .
    cp fonts/ttf/JetBrainsMono-ExtraLight.ttf .
    cp fonts/ttf/JetBrainsMono-ExtraLightItalic.ttf .
    
    # Cleanup
    rm -rf fonts/
    rm -f JetBrainsMono-2.304.zip OFL.txt AUTHORS.txt
    
    cd ..
    echo "✓ Fonts downloaded"
fi

echo ""
echo "Building Docker image..."
docker build -t script-runner:latest .

echo ""
echo "✓ Build complete"
echo ""
echo "To add to docker-compose.yml, use the service definition from README"
