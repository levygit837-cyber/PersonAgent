#!/bin/bash
# Run this script to completely reset Windsurf while keeping skills

echo "=== Backing up skills ==="
mkdir -p ~/windsurf-backup-$(date +%Y%m%d)
cp -r ~/.windsurf/skills ~/windsurf-backup-$(date +%Y%m%d)/
cp -r ~/.windsurf/extensions ~/windsurf-backup-$(date +%Y%m%d)/ 2>/dev/null || true
cp -r ~/.windsurf/plans ~/windsurf-backup-$(date +%Y%m%d)/ 2>/dev/null || true

echo "=== Resetting Windsurf user settings ==="
rm -f ~/.config/Windsurf/User/settings.json
rm -f ~/.config/Windsurf/User/keybindings.json
rm -rf ~/.config/Windsurf/User/snippets

echo "=== Clearing corrupted caches ==="
rm -rf ~/.config/Windsurf/CachedData/*
rm -rf ~/.config/Windsurf/CachedConfigurations/*
rm -rf ~/.config/Windsurf/Cache/*
rm -rf ~/.config/Windsurf/GPUCache
rm -rf ~/.config/Windsurf/Code\ Cache
rm -rf ~/.config/Windsurf/Crashpad/*
rm -rf ~/.config/Windsurf/logs/*

echo "=== Resetting window state ==="
rm -f ~/.config/Windsurf/Preferences
rm -f ~/.config/Windsurf/User/globalStorage/state.vscdb
rm -f ~/.config/Windsurf/User/globalStorage/storage.json

echo "=== Done! ==="
echo "Skills backed up to: ~/windsurf-backup-$(date +%Y%m%d)/"
echo "Now launch Windsurf with: windsurf --disable-gpu"
