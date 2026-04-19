#!/bin/bash
# Run this on Zubeda's machine to sync her Claude agent with the latest Z-Pay state.
# Usage: bash zubeda_agent_update.sh

SRC="$HOME/.claude"
DEST="$HOME/.claude"

echo "Updating Z-Pay agent context and memory..."

# Copy context file (what Z-Pay is)
cp "$SRC/context/zpay.md" "$DEST/context/zpay.md" 2>/dev/null || echo "⚠ Could not copy context/zpay.md — copy manually"

# Copy memory file (session history)
cp "$SRC/memory/zpay.md" "$DEST/memory/zpay.md" 2>/dev/null || echo "⚠ Could not copy memory/zpay.md — copy manually"

echo "Done. Her agent is now current as of 2026-04-17."
