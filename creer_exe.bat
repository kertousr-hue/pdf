@echo off
chcp 65001 >nul
title Creation de PDF Editeur.exe
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set PY=py) else (set PY=python)
%PY% -m pip install -r requirements.txt pyinstaller
%PY% -m PyInstaller --noconfirm --windowed --onefile --name "PDF Editeur" ^
  --collect-all pymupdf --collect-all tkinterdnd2 --collect-submodules fontTools ^
  pdf_editeur.py
echo.
echo  Le programme est dans le dossier "dist" : dist\PDF Editeur.exe
echo  Il fonctionne sans Python : copiez-le ou vous voulez.
echo  Pour ouvrir vos PDF avec : clic droit sur un PDF, Ouvrir avec, Choisir une autre application.
pause
