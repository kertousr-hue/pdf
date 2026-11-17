@echo off
chcp 65001 >nul
title PDF Editeur - acces depuis le telephone
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set PY=py) else (set PY=python)
echo.
echo  Ouvrez le lien "Depuis un telephone" ci-dessous sur votre telephone ou tablette
echo  (connecte au meme Wi-Fi que cet ordinateur). Laissez cette fenetre ouverte.
echo  Si Windows demande l'autorisation du pare-feu, acceptez pour les reseaux prives.
echo.
%PY% app_web.py --reseau
pause
