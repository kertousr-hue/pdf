# Construit l'installateur Windows de PDF Éditeur :
#   1. installe les modules Python nécessaires ;
#   2. fabrique le programme (dist\PDF Editeur\PDF Editeur.exe) avec PyInstaller ;
#   3. vérifie qu'il fonctionne (PDF Editeur.exe --verifier) ;
#   4. crée dist\PDF-Editeur-Installation-<version>.exe avec Inno Setup 6.
# Utilisé par GitHub Actions et par creer_installateur.bat.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Executer($commande) {
    & $commande[0] $commande[1..($commande.Length - 1)]
    if ($LASTEXITCODE -ne 0) { throw "Échec : $($commande -join ' ')" }
}

Write-Host "== Modules Python"
Executer @("python", "-m", "pip", "install", "--upgrade", "pip")
Executer @("python", "-m", "pip", "install", "-r", "requirements.txt", "pyinstaller")
$version = (python -c "import lanceur; print(lanceur.VERSION)").Trim()
Write-Host "Version : $version"

Write-Host "== Icône et langues de la reconnaissance de texte"
Executer @("python", "installateur\creer_icone.py")
New-Item -ItemType Directory -Force "installateur\tessdata" | Out-Null
foreach ($langue in @("fra", "eng")) {
    $dest = "installateur\tessdata\$langue.traineddata"
    if (-not (Test-Path $dest)) {
        Invoke-WebRequest "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/$langue.traineddata" -OutFile $dest
    }
}

Write-Host "== Programme (PyInstaller)"
Executer @("python", "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
    "--name", "PDF Editeur", "--icon", "installateur\pdf_editeur.ico",
    "--add-data", "web;web", "--add-data", "installateur\tessdata;tessdata",
    "--collect-binaries", "pymupdf", "--collect-submodules", "pymupdf",
    "--exclude-module", "pymupdf.layout", "--exclude-module", "onnxruntime",
    "--collect-all", "tkinterdnd2", "--collect-all", "pdf2docx",
    "--collect-submodules", "fontTools", "--hidden-import", "qrcode.image.svg",
    "lanceur.py")
# parties de PyMuPDF inutiles ici (analyse de mise en page, fichiers de développement) : ~50 Mo
foreach ($inutile in @("dist\PDF Editeur\_internal\pymupdf\layout", "dist\PDF Editeur\_internal\pymupdf\mupdf-devel")) {
    if (Test-Path $inutile) { Remove-Item -Recurse -Force $inutile }
}

Write-Host "== Vérification du programme construit"
$rapport = Join-Path (Get-Location) "verification.txt"
$p = Start-Process -FilePath "dist\PDF Editeur\PDF Editeur.exe" -ArgumentList "--verifier", "`"$rapport`"" -Wait -PassThru
Get-Content $rapport
if ($p.ExitCode -ne 0) { throw "La vérification du programme a échoué (code $($p.ExitCode))." }

Write-Host "== Installateur (Inno Setup)"
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($c in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                     "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $c) { $iscc = $c; break }
    }
}
if (-not $iscc) { throw "Inno Setup 6 n'est pas installé. Téléchargez-le sur https://jrsoftware.org/isdl.php puis relancez." }
Executer @($iscc, "/DAppVersion=$version", "installateur\pdf_editeur.iss")

$fichier = Get-ChildItem "dist\PDF-Editeur-Installation-*.exe" | Select-Object -First 1
Write-Host ""
Write-Host "Installateur créé : $($fichier.FullName) ($([math]::Round($fichier.Length / 1MB)) Mo)"
