@echo off
chcp 65001 >nul
title Creation de l'installateur de PDF Editeur
cd /d "%~dp0"
echo.
echo  Creation de l'installateur de PDF Editeur
echo  Il faut Python 3.12 et Inno Setup 6 (https://jrsoftware.org/isdl.php).
echo  Cela prend plusieurs minutes.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installateur\construire.ps1"
echo.
pause
