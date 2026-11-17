"""Numérisation depuis un scanner, puis création d'un PDF prêt à être modifié.

- Windows : pilote WIA (tous les scanners et imprimantes multifonctions reconnus par Windows),
  commandé par PowerShell, sans module supplémentaire.
- Linux : SANE (commande scanimage).
- Chaque page est redressée automatiquement si elle a été scannée de travers, puis
  enregistrée en JPEG (fichier léger) ou en PNG (noir et blanc).
"""

import glob
import os
import shutil
import subprocess
import sys

import pymupdf

WINDOWS = sys.platform == "win32"
FORMAT_PNG = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"
MODES = {"Couleur": 1, "Niveaux de gris": 2, "Noir et blanc": 4}  # WIA : intention de numérisation
MODES_SANE = {"Couleur": "Color", "Niveaux de gris": "Gray", "Noir et blanc": "Lineart"}
SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ErreurScanner(Exception):
    pass


def _powershell(script, delai=600):
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
                       capture_output=True, timeout=delai, creationflags=SANS_FENETRE)
    sortie = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    return r.returncode, sortie


def _ps_chaine(texte):
    return "'" + texte.replace("'", "''") + "'"


# --------------------------------------------------------------------------- #
# Liste des scanners
# --------------------------------------------------------------------------- #

def lister_scanners():
    """[(identifiant, nom)] des scanners branchés."""
    if WINDOWS:
        script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                  "$m=New-Object -ComObject WIA.DeviceManager;"
                  "foreach($d in $m.DeviceInfos){ if($d.Type -eq 1){"
                  " Write-Output ($d.DeviceID + '|' + $d.Properties.Item('Name').Value) } }")
        code, sortie = _powershell(script, 60)
        return [tuple(l.split("|", 1)) for l in sortie.splitlines() if "|" in l]
    if shutil.which("scanimage"):
        r = subprocess.run(["scanimage", "-f", "%d|%v %m%n"], capture_output=True, timeout=60)
        return [tuple(l.split("|", 1)) for l in r.stdout.decode("utf-8", "replace").splitlines() if "|" in l]
    return []


# --------------------------------------------------------------------------- #
# Numérisation
# --------------------------------------------------------------------------- #

def numeriser(dossier, appareil=None, dpi=300, mode="Couleur", chargeur=False, fenetre_windows=False):
    """Numérise une page (vitre) ou toutes les pages du chargeur. Renvoie la liste des images.

    fenetre_windows : utilise la fenêtre de numérisation de Windows (aperçu, cadrage) au lieu
    des réglages du programme."""
    os.makedirs(dossier, exist_ok=True)
    avant = set(glob.glob(os.path.join(dossier, "*")))
    if WINDOWS:
        _numeriser_wia(dossier, appareil, dpi, mode, chargeur, fenetre_windows)
    elif shutil.which("scanimage"):
        _numeriser_sane(dossier, appareil, dpi, mode, chargeur)
    else:
        raise ErreurScanner("Aucun logiciel de numérisation trouvé sur cet ordinateur.")
    images = sorted(set(glob.glob(os.path.join(dossier, "*"))) - avant)
    return [i for i in images if os.path.getsize(i) > 0]


def _numeriser_wia(dossier, appareil, dpi, mode, chargeur, fenetre_windows):
    d = _ps_chaine(dossier)
    if fenetre_windows:
        script = f"""
$ErrorActionPreference='Stop'
$dlg = New-Object -ComObject WIA.CommonDialog
$img = $dlg.ShowAcquireImage(1, {MODES.get(mode, 1)}, 131072, '{FORMAT_PNG}', $false, $true, $false)
if ($img -eq $null) {{ exit 3 }}
$img.SaveFile((Join-Path {d} ('page001.' + $img.FileExtension)))
"""
    else:
        choix = f"$d.DeviceID -eq {_ps_chaine(appareil)}" if appareil else "$true"
        script = f"""
$ErrorActionPreference='Stop'
$m = New-Object -ComObject WIA.DeviceManager
$info = $null
foreach ($d in $m.DeviceInfos) {{ if ($d.Type -eq 1 -and ({choix})) {{ $info = $d; break }} }}
if ($info -eq $null) {{ Write-Output 'AUCUN_SCANNER'; exit 2 }}
$dev = $info.Connect()
function Regler($proprietes, $id, $valeur) {{
  foreach ($p in $proprietes) {{ if ($p.PropertyID -eq $id) {{ try {{ $p.Value = $valeur }} catch {{}} }} }}
}}
$chargeur = ${'true' if chargeur else 'false'}
if ($chargeur) {{ Regler $dev.Properties 3088 1; Regler $dev.Properties 3096 1 }}
$item = $dev.Items.Item(1)
Regler $item.Properties 6146 {MODES.get(mode, 1)}
Regler $item.Properties 6147 {int(dpi)}
Regler $item.Properties 6148 {int(dpi)}
$n = 0
do {{
  try {{ $img = $item.Transfer('{FORMAT_PNG}') }}
  catch {{ if ($n -gt 0) {{ break }} else {{ throw }} }}
  $n++
  $img.SaveFile((Join-Path {d} (('page{{0:D3}}.' -f $n) + $img.FileExtension)))
}} while ($chargeur)
"""
    code, sortie = _powershell(script)
    if code == 3:
        raise ErreurScanner("Numérisation annulée.")
    if "AUCUN_SCANNER" in sortie:
        raise ErreurScanner("Aucun scanner trouvé. Vérifiez qu'il est branché, allumé et installé dans Windows.")
    if code != 0:
        if "0x80210003" in sortie or "0x80210064" in sortie:
            raise ErreurScanner("Le chargeur de documents est vide : mettez les feuilles dans le chargeur.")
        if "0x80210006" in sortie or "0x8021000a" in sortie.lower():
            raise ErreurScanner("Le scanner est occupé ou en veille. Réessayez dans quelques secondes.")
        raise ErreurScanner("La numérisation a échoué.\n\n" + sortie.strip()[-600:])


def _numeriser_sane(dossier, appareil, dpi, mode, chargeur):
    cmd = ["scanimage", "--format=png", f"--resolution={int(dpi)}", f"--mode={MODES_SANE.get(mode, 'Color')}"]
    if appareil:
        cmd += ["-d", appareil]
    if chargeur:
        cmd += ["--source=ADF", f"--batch={os.path.join(dossier, 'page%03d.png')}"]
    else:
        cmd += ["-o", os.path.join(dossier, "page001.png")]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0 and not glob.glob(os.path.join(dossier, "page*.png")):
        raise ErreurScanner("La numérisation a échoué.\n\n" + r.stderr.decode("utf-8", "replace")[-600:])


# --------------------------------------------------------------------------- #
# Redressement et création du PDF
# --------------------------------------------------------------------------- #

def angle_inclinaison(pix):
    """Angle (en degrés) dont la page est penchée, mesuré sur les lignes de texte.
    Renvoie 0 si numpy n'est pas installé ou si la page n'a pas assez de texte."""
    try:
        import numpy as np
    except ImportError:
        return 0.0
    gris = pymupdf.Pixmap(pymupdf.csGRAY, pix) if pix.n != 1 else pix
    a = np.frombuffer(gris.samples, dtype=np.uint8).reshape(gris.height, gris.stride)[:, :gris.width]
    ys, xs = np.nonzero(a < 128)
    if len(xs) < 500:
        return 0.0
    if len(xs) > 60000:  # échantillon : suffisant et rapide
        choix = np.random.default_rng(0).choice(len(xs), 60000, replace=False)
        xs, ys = xs[choix], ys[choix]
    xs = xs - xs.mean()

    def score(deg):
        t = np.radians(deg)
        rangs = np.round(ys * np.cos(t) - xs * np.sin(t)).astype(np.int64)
        h = np.bincount(rangs - rangs.min())
        return float((h.astype(np.float64) ** 2).sum())

    meilleur = max(np.arange(-5, 5.01, 0.25), key=score)
    fin = max(np.arange(meilleur - 0.25, meilleur + 0.26, 0.05), key=score)
    return float(fin)


def pages_vers_pdf(images, dpi=300, mode="Couleur", redresser=True, largeur_papier=None):
    """Crée un PDF (une page par image, à la taille réelle du papier), pages redressées.

    largeur_papier (en points, ex. 595 pour A4) : pour les photos, dont la résolution n'a pas
    de sens, l'image est mise à cette largeur."""
    doc = pymupdf.open()
    for chemin in images:
        pix = pymupdf.Pixmap(chemin)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
        # résolution réelle de l'image si elle est indiquée (certains scanners ignorent celle demandée)
        if largeur_papier:
            resolution = pix.width * 72 / largeur_papier
        else:
            resolution = pix.xres if pix.xres and pix.xres not in (72, 96) else (dpi or 300)
        largeur, hauteur = pix.width * 72 / resolution, pix.height * 72 / resolution
        petite = pymupdf.Pixmap(pix, max(1, pix.width // 4), max(1, pix.height // 4), None) \
            if pix.width > 1200 else pix
        angle = angle_inclinaison(petite) if redresser else 0.0
        noir_blanc = mode == "Noir et blanc"
        donnees = pix.tobytes("png") if noir_blanc else pix.tobytes("jpeg", jpg_quality=85)
        page = doc.new_page(width=largeur, height=hauteur)
        if abs(angle) >= 0.15:
            # redressement : on dessine l'image tournée, puis on la ré-imprime en une image plate
            tmp = pymupdf.open()
            p = tmp.new_page(width=largeur, height=hauteur)
            p.insert_image(p.rect, stream=donnees)
            tour = pymupdf.open()
            q = tour.new_page(width=largeur, height=hauteur)
            q.show_pdf_page(q.rect, tmp, 0, rotate=angle, keep_proportion=False)
            plate = q.get_pixmap(dpi=max(1, round(resolution)), colorspace=pymupdf.csGRAY if noir_blanc else pix.colorspace,
                                 alpha=False)
            donnees = plate.tobytes("png") if noir_blanc else plate.tobytes("jpeg", jpg_quality=85)
        page.insert_image(page.rect, stream=donnees)
    return doc
