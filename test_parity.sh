#!/usr/bin/env bash
#
# Test parity between expose.sh and expose.py
#
# This script runs both versions on a test gallery and compares the output.
# Usage: ./test_parity.sh [test_directory]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="${1:-$SCRIPT_DIR/test_gallery}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "Test Parity Script"
echo "=================="
echo "Script directory: $SCRIPT_DIR"
echo "Test directory: $TEST_DIR"
echo ""

# Check if test directory exists
if [ ! -d "$TEST_DIR" ]; then
    echo -e "${YELLOW}Warning: Test directory does not exist. Creating sample test gallery...${NC}"
    mkdir -p "$TEST_DIR/01 Gallery One"
    mkdir -p "$TEST_DIR/02 Gallery Two"

    # Create sample images using ImageMagick
    if command -v convert >/dev/null 2>&1; then
        convert -size 640x480 xc:blue "$TEST_DIR/01 Gallery One/01 blue.jpg"
        convert -size 640x480 xc:red "$TEST_DIR/01 Gallery One/02 red.jpg"
        convert -size 640x480 xc:green "$TEST_DIR/02 Gallery Two/01 green.jpg"

        # Create sample text files
        cat > "$TEST_DIR/01 Gallery One/01 blue.txt" << 'EOF'
title: Blue Image
---
This is a **blue** image for testing.
EOF

        cat > "$TEST_DIR/01 Gallery One/02 red.txt" << 'EOF'
title: Red Image
top: 50
left: 30
---
A beautiful red square.
EOF

        echo "Sample test gallery created."
    else
        echo -e "${RED}Error: ImageMagick not found. Cannot create sample images.${NC}"
        exit 1
    fi
fi

# Create temporary directories for output
SHELL_OUTPUT=$(mktemp -d)
PYTHON_OUTPUT=$(mktemp -d)

cleanup() {
    rm -rf "$SHELL_OUTPUT" "$PYTHON_OUTPUT"
}
trap cleanup EXIT

echo "Running shell version..."
cd "$TEST_DIR"
rm -rf _site
bash "$SCRIPT_DIR/expose.sh" -d
cp -r _site/* "$SHELL_OUTPUT/"
rm -rf _site

echo ""
echo "Running Python version..."
rm -rf _site
python3 "$SCRIPT_DIR/expose.py" -d
cp -r _site/* "$PYTHON_OUTPUT/"
rm -rf _site

echo ""
echo "Comparing outputs..."
echo "===================="

# Compare directory structures
echo -n "Directory structure: "
SHELL_DIRS=$(cd "$SHELL_OUTPUT" && find . -type d | sort)
PYTHON_DIRS=$(cd "$PYTHON_OUTPUT" && find . -type d | sort)

if [ "$SHELL_DIRS" = "$PYTHON_DIRS" ]; then
    echo -e "${GREEN}MATCH${NC}"
else
    echo -e "${RED}DIFFER${NC}"
    echo "Shell directories:"
    echo "$SHELL_DIRS"
    echo "Python directories:"
    echo "$PYTHON_DIRS"
fi

# Compare file lists
echo -n "File list: "
SHELL_FILES=$(cd "$SHELL_OUTPUT" && find . -type f | sort)
PYTHON_FILES=$(cd "$PYTHON_OUTPUT" && find . -type f | sort)

if [ "$SHELL_FILES" = "$PYTHON_FILES" ]; then
    echo -e "${GREEN}MATCH${NC}"
else
    echo -e "${RED}DIFFER${NC}"
    echo "Shell files:"
    echo "$SHELL_FILES"
    echo "Python files:"
    echo "$PYTHON_FILES"
fi

# Compare HTML files
echo ""
echo "HTML file comparison:"
for html_file in $(cd "$SHELL_OUTPUT" && find . -name "*.html" | sort); do
    echo -n "  $html_file: "

    if [ ! -f "$PYTHON_OUTPUT/$html_file" ]; then
        echo -e "${RED}MISSING in Python output${NC}"
        continue
    fi

    # Normalize whitespace for comparison
    SHELL_HTML=$(cat "$SHELL_OUTPUT/$html_file" | tr -s '[:space:]' ' ')
    PYTHON_HTML=$(cat "$PYTHON_OUTPUT/$html_file" | tr -s '[:space:]' ' ')

    if [ "$SHELL_HTML" = "$PYTHON_HTML" ]; then
        echo -e "${GREEN}MATCH${NC}"
    else
        echo -e "${YELLOW}DIFFER (checking key content)${NC}"

        # Check key elements
        SHELL_TITLE=$(grep -o '<title>[^<]*</title>' "$SHELL_OUTPUT/$html_file" || echo "")
        PYTHON_TITLE=$(grep -o '<title>[^<]*</title>' "$PYTHON_OUTPUT/$html_file" || echo "")

        if [ "$SHELL_TITLE" = "$PYTHON_TITLE" ]; then
            echo "    - Title: ${GREEN}MATCH${NC}"
        else
            echo "    - Title: ${RED}DIFFER${NC}"
            echo "      Shell: $SHELL_TITLE"
            echo "      Python: $PYTHON_TITLE"
        fi

        # Check slide count
        SHELL_SLIDES=$(grep -c 'class="slide"' "$SHELL_OUTPUT/$html_file" || echo "0")
        PYTHON_SLIDES=$(grep -c 'class="slide"' "$PYTHON_OUTPUT/$html_file" || echo "0")

        if [ "$SHELL_SLIDES" = "$PYTHON_SLIDES" ]; then
            echo "    - Slide count: ${GREEN}MATCH ($SHELL_SLIDES)${NC}"
        else
            echo "    - Slide count: ${RED}DIFFER (Shell: $SHELL_SLIDES, Python: $PYTHON_SLIDES)${NC}"
        fi

        # Check navigation items
        SHELL_NAV=$(grep -c 'class="gallery' "$SHELL_OUTPUT/$html_file" || echo "0")
        PYTHON_NAV=$(grep -c 'class="gallery' "$PYTHON_OUTPUT/$html_file" || echo "0")

        if [ "$SHELL_NAV" = "$PYTHON_NAV" ]; then
            echo "    - Nav items: ${GREEN}MATCH ($SHELL_NAV)${NC}"
        else
            echo "    - Nav items: ${RED}DIFFER (Shell: $SHELL_NAV, Python: $PYTHON_NAV)${NC}"
        fi
    fi
done

# Compare image files
echo ""
echo "Image file comparison:"
for img_file in $(cd "$SHELL_OUTPUT" && find . -name "*.jpg" | sort); do
    echo -n "  $img_file: "

    if [ ! -f "$PYTHON_OUTPUT/$img_file" ]; then
        echo -e "${RED}MISSING in Python output${NC}"
        continue
    fi

    # Compare file sizes (should be similar)
    SHELL_SIZE=$(stat -c %s "$SHELL_OUTPUT/$img_file" 2>/dev/null || stat -f %z "$SHELL_OUTPUT/$img_file")
    PYTHON_SIZE=$(stat -c %s "$PYTHON_OUTPUT/$img_file" 2>/dev/null || stat -f %z "$PYTHON_OUTPUT/$img_file")

    # Allow 5% difference in file size
    DIFF=$((SHELL_SIZE - PYTHON_SIZE))
    DIFF=${DIFF#-}  # Absolute value
    THRESHOLD=$((SHELL_SIZE / 20))

    if [ "$DIFF" -le "$THRESHOLD" ]; then
        echo -e "${GREEN}SIMILAR (Shell: ${SHELL_SIZE}B, Python: ${PYTHON_SIZE}B)${NC}"
    else
        echo -e "${YELLOW}SIZE DIFFERS (Shell: ${SHELL_SIZE}B, Python: ${PYTHON_SIZE}B)${NC}"
    fi
done

echo ""
echo "Comparison complete."
echo ""
echo "Output directories preserved at:"
echo "  Shell: $SHELL_OUTPUT"
echo "  Python: $PYTHON_OUTPUT"

# Don't cleanup so user can inspect
trap - EXIT
echo ""
echo "To clean up: rm -rf $SHELL_OUTPUT $PYTHON_OUTPUT"
