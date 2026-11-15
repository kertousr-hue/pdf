"""Conversions : Word / images -> PDF, et PDF -> Word.

- Word (.docx, .doc, .rtf, .odt) -> PDF : avec Microsoft Word s'il est installé (Windows),
  sinon avec LibreOffice (gratuit).
- Images (.jpg, .png, .tif…) -> PDF : une page par image.
- PDF -> Word (.docx) : avec le module pdf2docx (mise en page conservée au mieux).
"""

import glob
import os
import shutil
import subprocess
import sys
import tempfile

import pymupdf

EXT_WORD = (".docx", ".doc", ".rtf", ".odt", ".txt")
EXT_IMAGES = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")
WINDOWS = sys.platform == "win32"


def type_fichier(chemin):
    ext = os.path.splitext(chemin)[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext in EXT_WORD:
        return "word"
    if ext in EXT_IMAGES:
        return "image"
    return None


# --------------------------------------------------------------------------- #
# Images -> PDF
# --------------------------------------------------------------------------- #

def images_vers_pdf(chemins):
    """Renvoie un document PDF (en mémoire) avec une page par image."""
    doc = pymupdf.open()
    for c in chemins:
        with pymupdf.open(c) as img:
            pdf = pymupdf.open("pdf", img.convert_to_pdf())
            doc.insert_pdf(pdf)
    return doc


# --------------------------------------------------------------------------- #
# Word -> PDF
# --------------------------------------------------------------------------- #

def _soffice():
    for nom in ("soffice", "libreoffice"):
        trouve = shutil.which(nom)
        if trouve:
            return trouve
    candidats = [r"C:\Program Files\LibreOffice\program\soffice.exe",
                 r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                 "/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    return next((c for c in candidats if os.path.isfile(c)), None)


def _word_windows(source, dest):
    """Conversion avec Microsoft Word (PowerShell + COM, sans module supplémentaire)."""
    script = (
        "$ErrorActionPreference='Stop';"
        "$w=New-Object -ComObject Word.Application; $w.Visible=$false; $w.DisplayAlerts=0;"
        f"try {{ $d=$w.Documents.Open('{source}', $false, $true);"
        f" $d.SaveAs([ref]'{dest}', [ref]17); $d.Close($false) }} finally {{ $w.Quit() }}"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   check=True, capture_output=True, timeout=180,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def word_vers_pdf(chemin):
    """Convertit un document Word (ou .odt, .rtf, .txt) en PDF. Renvoie les octets du PDF."""
    source = os.path.abspath(chemin)
    if "'" in source and WINDOWS:
        raise ValueError("Le nom du fichier contient une apostrophe : renommez-le puis réessayez.")
    with tempfile.TemporaryDirectory() as tmp:
        dest = os.path.join(tmp, os.path.splitext(os.path.basename(source))[0] + ".pdf")
        erreurs = []
        if WINDOWS and not source.lower().endswith(".odt"):
            try:
                _word_windows(source, dest)
            except Exception as e:
                erreurs.append(f"Microsoft Word : {e}")
        if not os.path.isfile(dest):
            soffice = _soffice()
            if soffice:
                try:
                    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, source],
                                   check=True, capture_output=True, timeout=180,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    produits = glob.glob(os.path.join(tmp, "*.pdf"))
                    if produits:
                        dest = produits[0]
                except Exception as e:
                    erreurs.append(f"LibreOffice : {e}")
        if not os.path.isfile(dest):
            raise RuntimeError(
                "Impossible de convertir ce document en PDF.\n\n"
                "Il faut Microsoft Word ou LibreOffice (gratuit : https://fr.libreoffice.org) "
                "installé sur l'ordinateur." + ("\n\n" + "\n".join(erreurs) if erreurs else ""))
        with open(dest, "rb") as f:
            return f.read()


# --------------------------------------------------------------------------- #
# PDF -> Word
# --------------------------------------------------------------------------- #

def pdf_vers_word(chemin_pdf, chemin_docx, pages=None, rappel=None):
    """Convertit un PDF en document Word modifiable (.docx)."""
    try:
        from pdf2docx import Converter
    except ImportError:
        raise RuntimeError("Le module pdf2docx n'est pas installé.\n"
                           "Relancez installer.bat (ou : pip install pdf2docx).")
    import logging
    logging.getLogger().setLevel(logging.ERROR)
    cv = Converter(chemin_pdf)
    try:
        cv.convert(chemin_docx, pages=pages)
    finally:
        cv.close()
