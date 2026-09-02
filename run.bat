@echo off
chcp 65001 >nul
title VSub Studio
cd /d "%~dp0"
uv run python run.py %*
