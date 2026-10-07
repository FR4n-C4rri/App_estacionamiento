@echo off
chcp 65001 >nul
title Camara de estacionamiento
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo No encontre Python. Instalalo desde https://www.python.org/downloads/
  echo ^(tilda "Add python.exe to PATH" durante la instalacion^) y volve a abrir este archivo.
  pause
  exit /b 1
)

if not exist camara.ini (
  echo Falta el archivo camara.ini en esta carpeta.
  echo Pediselo a quien administra el sistema ^(se descarga desde el modo admin^).
  pause
  exit /b 1
)

py -c "import cv2" >nul 2>nul
if errorlevel 1 (
  echo Instalando OpenCV ^(solo la primera vez^)...
  py -m pip install --quiet opencv-python
)

py cliente_camara.py
pause
