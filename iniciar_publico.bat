@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Estacionamiento - servidor publico
cd /d "%~dp0"
py -m scripts.iniciar_publico
pause
