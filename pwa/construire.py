#!/usr/bin/env python3
"""Assemble la PWA (application installable depuis le navigateur) dans le dossier « site/ ».

    python pwa/construire.py            -> site/ prêt à être mis en ligne (HTTPS obligatoire)
    python pwa/construire.py --servir   -> et le sert sur http://localhost:8080 pour l'essayer

Tout est hébergé avec l'application (aucun service tiers au moment de l'utilisation) :
- Pyodide (Python dans le navigateur), depuis npm ;
- PyMuPDF compilé en WebAssembly et les modules Python purs (Flask…), depuis PyPI ;
- le moteur de PDF Éditeur (app_web.py, pdftool.py, polices.py, scan.py…) ;
- Tesseract.js et les langues française et anglaise pour la reconnaissance de texte ;
- des polices libres aux mêmes dimensions qu'Arial, Times, Courier, Calibri et Cambria.
"""

import argparse
import hashlib
import http.server
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PWA = os.path.join(RACINE, "pwa")
SITE = os.path.join(RACINE, "site")
CACHE = os.path.join(RACINE, "build", "pwa-cache")  # téléchargements gardés entre deux constructions

PYODIDE = "0.29.5"            # Python 3.13, plateforme pyemscripten_2025_0
PYMUPDF = "1.28.2"
TESSERACT_JS = "5.1.1"
TESSERACT_CORE = "5.1.1"
PAQUETS_PURS = ["flask", "werkzeug", "jinja2", "itsdangerous", "click", "blinker", "fonttools"]
MODULES = ["app_web.py", "pdftool.py", "polices.py", "scan.py", "scanner.py", "conversion.py"]
# (famille Google Fonts, graisse, italique) : équivalents libres des polices les plus courantes
POLICES = [("arimo", w, i) for w in (400, 700) for i in (False, True)] + \
          [("tinos", w, i) for w in (400, 700) for i in (False, True)] + \
          [("cousine", 400, False), ("cousine", 700, False),
           ("carlito", 400, False), ("carlito", 700, False), ("carlito", 400, True),
           ("caladea", 400, False), ("caladea", 700, False)]
LANGUES = ["fra", "eng"]


def telecharger(url, nom=None):
    os.makedirs(CACHE, exist_ok=True)
    chemin = os.path.join(CACHE, nom or url.rsplit("/", 1)[-1])
    if not os.path.isfile(chemin):
        print("  téléchargement", url)
        req = urllib.request.Request(url, headers={"User-Agent": "pdf-editeur-construction"})
        with urllib.request.urlopen(req, timeout=300) as r:
            donnees = r.read()
        with open(chemin + ".part", "wb") as f:
            f.write(donnees)
        os.replace(chemin + ".part", chemin)
    return chemin


def npm(paquet, version):
    url = f"https://registry.npmjs.org/{paquet}/-/{paquet.split('/')[-1]}-{version}.tgz"
    return tarfile.open(telecharger(url, f"{paquet.replace('/', '_')}-{version}.tgz"))


def extraire_npm(paquet, version, fichiers, dest):
    os.makedirs(dest, exist_ok=True)
    with npm(paquet, version) as t:
        for f in fichiers:
            membre = t.extractfile(f"package/{f}")
            with open(os.path.join(dest, os.path.basename(f)), "wb") as sortie:
                sortie.write(membre.read())


def roue_pypi(nom, version=None, filtre=None):
    """Télécharge une roue (wheel) depuis PyPI : la plus récente pure Python, ou selon `filtre`."""
    infos = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{nom}/{version + '/' if version else ''}json",
                                             timeout=60))
    for f in infos["urls"]:
        if f["packagetype"] == "bdist_wheel" and (filtre(f["filename"]) if filtre else f["filename"].endswith("-py3-none-any.whl")):
            return telecharger(f["url"])
    raise RuntimeError(f"Aucune roue trouvée pour {nom}")


def sources_markupsafe():
    """MarkupSafe n'a pas de roue pure Python, mais fonctionne sans sa partie compilée."""
    infos = json.load(urllib.request.urlopen("https://pypi.org/pypi/markupsafe/json", timeout=60))
    sdist = next(f for f in infos["urls"] if f["packagetype"] == "sdist")
    fichiers = {}
    with tarfile.open(telecharger(sdist["url"])) as t:
        for m in t.getmembers():
            if "/src/markupsafe/" in m.name and m.name.endswith((".py", ".typed")):
                fichiers["markupsafe/" + m.name.split("/src/markupsafe/")[1]] = t.extractfile(m).read()
    return fichiers


def archive_python():
    """python.zip : modules purs + moteur de PDF Éditeur, décompressés dans le navigateur."""
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        for paquet in PAQUETS_PURS:
            with zipfile.ZipFile(roue_pypi(paquet)) as roue:
                for n in roue.namelist():
                    if not n.endswith((".pyc", "/RECORD")):  # métadonnées gardées (Flask les lit)
                        z.writestr(n, roue.read(n))
        for n, contenu in sources_markupsafe().items():
            z.writestr(n, contenu)
        for m in MODULES:
            z.write(os.path.join(RACINE, m), m)
    return tampon.getvalue()


def polices_libres(dest):
    """Polices libres (Google Fonts) déjà prêtes : une graisse par fichier."""
    sys.path.insert(0, RACINE)
    tmp = tempfile.mkdtemp()
    os.environ["XDG_DATA_HOME"] = os.environ["APPDATA"] = tmp  # dossier de téléchargement isolé
    import polices
    index = polices.IndexPolices()
    index.pret.set()
    index.entrees = []
    index._indexer()
    os.makedirs(dest, exist_ok=True)
    for famille, poids, italique in POLICES:
        cle = f"{famille}-{poids}-{'i' if italique else 'n'}.ttf"
        cache = os.path.join(CACHE, "polices", cle)
        if not os.path.isfile(cache):
            print("  police", famille, poids, "italique" if italique else "")
            e = index._telecharger_famille(famille, poids, italique, 60)
            if not e:
                raise RuntimeError(f"Police introuvable : {famille}")
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            shutil.copyfile(e["chemin"], cache)
        shutil.copyfile(cache, os.path.join(dest, cle))
    with open(os.path.join(dest, "liste.json"), "w") as f:
        json.dump(sorted(n for n in os.listdir(dest) if n.endswith(".ttf")), f)
    shutil.rmtree(tmp, ignore_errors=True)


def icones(dest):
    sys.path.insert(0, os.path.join(RACINE, "installateur"))
    import pymupdf

    import creer_icone
    for taille in (192, 512):
        with open(os.path.join(dest, f"icone-{taille}.png"), "wb") as f:
            f.write(creer_icone.dessiner(taille))
        # icône « maskable » : marge de sécurité pour les formes rondes d'Android
        pix = pymupdf.Pixmap(creer_icone.dessiner(int(taille * 0.72)))
        doc = pymupdf.open()
        page = doc.new_page(width=taille, height=taille)
        page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
        marge = (taille - pix.width) / 2
        page.insert_image(pymupdf.Rect(marge, marge, marge + pix.width, marge + pix.height), pixmap=pix)
        with open(os.path.join(dest, f"icone-maskable-{taille}.png"), "wb") as f:
            f.write(page.get_pixmap(alpha=False).tobytes("png"))


def construire():
    if os.path.isdir(SITE):
        shutil.rmtree(SITE)
    os.makedirs(SITE)
    print("== Interface")
    page = open(os.path.join(RACINE, "web", "index.html"), encoding="utf-8").read()
    page = page.replace('<link rel="stylesheet" href="/web/style.css">',
                        '<link rel="stylesheet" href="style.css">\n<link rel="stylesheet" href="pwa.css">')
    page = page.replace('<script src="/web/app.js"></script>',
                        '<script src="pwa.js"></script>\n<script src="app.js"></script>')
    page = page.replace("<title>PDF Éditeur</title>", """<title>PDF Éditeur</title>
<meta name="theme-color" content="#1a73e8">
<meta name="description" content="Lire, modifier, signer et remplir des PDF, même scannés. Fonctionne hors ligne.">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icone-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">""")
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    for nom in ("app.js", "style.css"):
        shutil.copyfile(os.path.join(RACINE, "web", nom), os.path.join(SITE, nom))
    for nom in ("pwa.js", "moteur.js", "manifest.webmanifest", "pwa.css"):
        shutil.copyfile(os.path.join(PWA, nom), os.path.join(SITE, nom))
    icones(SITE)

    print("== Pyodide", PYODIDE)
    extraire_npm("pyodide", PYODIDE, ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip",
                                      "pyodide-lock.json"], os.path.join(SITE, "pyodide"))
    print("== PyMuPDF", PYMUPDF, "(WebAssembly)")
    roue = roue_pypi("pymupdf", PYMUPDF, lambda n: "pyemscripten_2025_0_wasm32" in n)
    os.makedirs(os.path.join(SITE, "roues"))
    shutil.copyfile(roue, os.path.join(SITE, "roues", os.path.basename(roue)))
    print("== Modules Python et moteur de PDF Éditeur")
    with open(os.path.join(SITE, "python.zip"), "wb") as f:
        f.write(archive_python())
    print("== Polices libres")
    polices_libres(os.path.join(SITE, "polices"))
    print("== Tesseract.js", TESSERACT_JS)
    ocr = os.path.join(SITE, "ocr")
    extraire_npm("tesseract.js", TESSERACT_JS, ["dist/tesseract.min.js", "dist/worker.min.js"], ocr)
    extraire_npm("tesseract.js-core", TESSERACT_CORE,
                 ["tesseract-core-simd-lstm.wasm.js", "tesseract-core-lstm.wasm.js",
                  "tesseract-core-simd-lstm.wasm", "tesseract-core-lstm.wasm"], ocr)
    for langue in LANGUES:
        shutil.copyfile(telecharger(f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/{langue}.traineddata",
                                    f"fast-{langue}.traineddata"),
                        os.path.join(ocr, f"{langue}.traineddata"))

    # Service worker : liste des fichiers à garder pour l'utilisation hors ligne + version
    fichiers, empreinte = [], hashlib.sha256()
    for dossier, _d, noms in os.walk(SITE):
        for n in sorted(noms):
            chemin = os.path.join(dossier, n)
            relatif = os.path.relpath(chemin, SITE).replace(os.sep, "/")
            fichiers.append(relatif)
            with open(chemin, "rb") as f:
                empreinte.update(relatif.encode() + f.read())
    version = empreinte.hexdigest()[:12]
    sw = open(os.path.join(PWA, "sw.js"), encoding="utf-8").read()
    # gardés dès l'installation : la « coquille » de l'application. Les gros fichiers (Python, PyMuPDF,
    # polices, OCR) sont mis en cache au passage, lors de leur premier téléchargement.
    coquille = ["./"] + [f for f in sorted(fichiers) if "/" not in f and not f.endswith((".zip", ".json"))]
    sw = sw.replace("__VERSION__", version).replace("__FICHIERS__", json.dumps(coquille, indent=1))
    with open(os.path.join(SITE, "sw.js"), "w", encoding="utf-8") as f:
        f.write(sw)
    with open(os.path.join(SITE, ".nojekyll"), "w") as f:
        pass
    taille = sum(os.path.getsize(os.path.join(d, n)) for d, _x, ns in os.walk(SITE) for n in ns)
    print(f"\nPWA construite dans {SITE} ({len(fichiers)} fichiers, {taille / 1e6:.0f} Mo, version {version})")


class Gestionnaire(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".wasm": "application/wasm", ".webmanifest": "application/manifest+json",
                      ".js": "text/javascript", ".mjs": "text/javascript"}

    def __init__(self, *a, **k):
        super().__init__(*a, directory=SITE, **k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--servir", action="store_true", help="servir site/ sur http://localhost:8080 après la construction")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    construire()
    if args.servir:
        print(f"Essai : http://localhost:{args.port}/  (Ctrl+C pour arrêter)")
        http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Gestionnaire).serve_forever()


if __name__ == "__main__":
    main()
