@echo off
chcp 65001 >nul
title Installation de PDF Editeur
cd /d "%~dp0"
echo.
echo  Installation de PDF Editeur
echo  ===========================
echo.
where py >nul 2>nul
if %errorlevel%==0 (set PY=py) else (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo  Python n'est pas installe.
  echo  Installez-le depuis https://www.python.org/downloads/
  echo  en cochant "Add python.exe to PATH", puis relancez ce fichier.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo  Erreur pendant l'installation des modules.
  pause
  exit /b 1
)
echo.
echo  Creation du raccourci sur le Bureau...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\PDF Editeur.lnk'); $s.TargetPath='%~dp0PDF Editeur.pyw'; $s.WorkingDirectory='%~dp0'; $s.Save(); $s=$w.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\PDF Editeur (web).lnk'); $s.TargetPath='%~dp0PDF Editeur Web.pyw'; $s.WorkingDirectory='%~dp0'; $s.Save()"
echo.
echo  Termine ! Lancez "PDF Editeur" depuis le Bureau
echo  (ou double-cliquez sur "PDF Editeur.pyw" dans ce dossier).
echo.
pause
