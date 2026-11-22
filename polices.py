"""Gestion des polices : index de toutes les polices installées et téléchargement Google Fonts.

- Indexe les polices de Windows (système et utilisateur), macOS, Linux, du dossier « polices »
  du programme et du dossier de polices personnel du programme.
- Les polices sont reconnues par leur nom interne (ex. « Arial-BoldMT » -> arialbd.ttf).
- L'index est mis en cache : seule la première ouverture est un peu plus longue.
- Une police absente peut être téléchargée gratuitement depuis Google Fonts (plus de 1 500 familles).
"""

import io
import json
import os
import re
import shutil
import sys
import threading
import urllib.parse
import urllib.request

EXTENSIONS = (".ttf", ".otf", ".ttc", ".otc")
VERSION_CACHE = 2

# Mots de style -> graisse (les mots composés d'abord)
POIDS = [("extralight", 200), ("ultralight", 200), ("semibold", 600), ("demibold", 600),
         ("extrabold", 800), ("ultrabold", 800), ("hairline", 100), ("thin", 100), ("light", 300),
         ("medium", 500), ("bold", 700), ("black", 900), ("heavy", 900), ("demi", 600)]
NOMS_POIDS = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium",
              600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black"}

# Polices de remplacement à métriques identiques (mêmes largeurs de caractères)
EQUIVALENTS = {
    "helvetica": ["arial", "liberationsans", "arimo"],
    "arial": ["liberationsans", "arimo", "helvetica"],
    "timesnewroman": ["liberationserif", "tinos", "times"],
    "times": ["timesnewroman", "liberationserif", "tinos"],
    "couriernew": ["liberationmono", "cousine"],
    "courier": ["couriernew", "liberationmono", "cousine"],
    "calibri": ["carlito"],
    "cambria": ["caladea"],
    "arialnarrow": ["liberationsansnarrow"],
}
# Polices standard PDF : inutile de les chercher sur Google Fonts
STANDARD_PDF = {"helvetica", "times", "timesroman", "courier", "symbol", "zapfdingbats"}


# --------------------------------------------------------------------------- #
# Dossiers
# --------------------------------------------------------------------------- #

def dossier_app():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    d = os.path.join(base, "PDF Editeur")
    os.makedirs(d, exist_ok=True)
    return d


def dossier_polices_perso():
    """Polices ajoutées ou téléchargées par le programme (pas besoin d'être administrateur)."""
    d = os.path.join(dossier_app(), "polices")
    os.makedirs(d, exist_ok=True)
    return d


def dossiers_polices():
    ici = os.path.dirname(os.path.abspath(__file__))
    dossiers = [os.path.join(ici, "polices"), dossier_polices_perso()]
    if sys.platform == "win32":
        dossiers += [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")]
    elif sys.platform == "darwin":
        dossiers += ["/Library/Fonts", "/System/Library/Fonts", "/System/Library/Fonts/Supplemental",
                     os.path.expanduser("~/Library/Fonts")]
    else:
        dossiers += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
                     os.path.expanduser("~/.local/share/fonts")]
    return [d for d in dossiers if d and os.path.isdir(d)]


# --------------------------------------------------------------------------- #
# Noms
# --------------------------------------------------------------------------- #

def sans_prefixe(nom):
    """'ABCDEF+Arial-BoldMT' -> 'Arial-BoldMT'."""
    return nom[7:] if len(nom) > 7 and nom[6] == "+" else nom


def normaliser(nom):
    n = "".join(c for c in sans_prefixe(nom).lower() if c.isalnum())
    for suffixe in ("psmt", "mt", "ps"):
        if n.endswith(suffixe) and len(n) > len(suffixe) + 2:
            n = n[: -len(suffixe)]
            break
    return n.replace("regular", "") or n


def analyser_nom(nom, gras=None, italique=None):
    """'Montserrat-SemiBoldItalic' -> ('montserrat', 600, True)."""
    nom = sans_prefixe(nom)
    m = re.match(r"^(.*?)[-,_](.*)$", nom)
    famille, style = (m.group(1), m.group(2)) if m else (nom, "")
    s = style.lower().replace(" ", "")
    poids = next((p for mot, p in POIDS if mot in s), None)
    if poids is None:
        poids = 700 if gras else 400
    ita = italique if italique is not None else ("italic" in s or "oblique" in s or s.endswith("it"))
    if not m:  # ex. « ArialBold »
        low = famille.lower()
        for mot, p in POIDS:
            if low.endswith(mot):
                famille, poids = famille[: -len(mot)], p
                break
    return normaliser(famille), poids, bool(ita or ("italic" in s))


# --------------------------------------------------------------------------- #
# Index
# --------------------------------------------------------------------------- #

def _lire_fichier(chemin):
    from fontTools.ttLib import TTCollection, TTFont
    entrees = []
    ext = os.path.splitext(chemin)[1].lower()
    polices = TTCollection(chemin, lazy=True).fonts if ext in (".ttc", ".otc") else [TTFont(chemin, lazy=True)]
    for index, f in enumerate(polices):
        try:
            nom = f["name"]
            famille = nom.getDebugName(16) or nom.getDebugName(1) or ""
            style = nom.getDebugName(17) or nom.getDebugName(2) or "Regular"
            ps = nom.getDebugName(6) or ""
            complet = nom.getDebugName(4) or f"{famille} {style}"
            poids, ita = 400, "italic" in style.lower() or "oblique" in style.lower()
            if "OS/2" in f:
                os2 = f["OS/2"]
                poids = os2.usWeightClass or 400
                ita = ita or bool(os2.fsSelection & 1)
            if not famille:
                continue
            entrees.append({"chemin": chemin, "index": index, "famille": famille, "style": style,
                            "ps": ps, "complet": complet, "poids": poids, "italique": ita})
        except Exception:
            continue
    return entrees


class IndexPolices:
    def __init__(self):
        self.entrees = []
        self.pret = threading.Event()
        self._contenus = {}
        self._absentes_google = set()
        self._verrou = threading.Lock()

    # -- construction --

    def charger(self, en_arriere_plan=False, rappel=None):
        if en_arriere_plan:
            threading.Thread(target=self._construire, args=(rappel,), daemon=True).start()
        else:
            self._construire(rappel)

    def attendre(self):
        if not self.pret.is_set() and not any(t.name == "polices" for t in threading.enumerate()):
            self._construire()
        self.pret.wait()

    def _chemin_cache(self):
        return os.path.join(dossier_app(), "polices_index.json")

    def _construire(self, rappel=None):
        threading.current_thread().name = "polices"
        try:
            with open(self._chemin_cache(), encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("version") != VERSION_CACHE:
                cache = {}
        except Exception:
            cache = {}
        fichiers = cache.get("fichiers", {})
        nouveau, entrees = {}, []
        for dossier in dossiers_polices():
            for racine, _d, noms in os.walk(dossier):
                for n in noms:
                    if not n.lower().endswith(EXTENSIONS):
                        continue
                    chemin = os.path.join(racine, n)
                    try:
                        st = os.stat(chemin)
                    except OSError:
                        continue
                    signature = [st.st_mtime, st.st_size]
                    connu = fichiers.get(chemin)
                    if connu and connu["sig"] == signature:
                        e = connu["entrees"]
                    else:
                        try:
                            e = _lire_fichier(chemin)
                        except Exception:
                            e = []
                    nouveau[chemin] = {"sig": signature, "entrees": e}
                    entrees.extend(e)
        try:
            with open(self._chemin_cache(), "w", encoding="utf-8") as f:
                json.dump({"version": VERSION_CACHE, "fichiers": nouveau}, f)
        except OSError:
            pass
        with self._verrou:
            self.entrees = entrees
            self._indexer()
        self.pret.set()
        if rappel:
            rappel(self)

    def _indexer(self):
        self.par_nom, self.par_famille = {}, {}
        for e in self.entrees:
            for cle in (e["ps"], e["complet"], e["famille"] + e["style"]):
                if cle:
                    self.par_nom.setdefault(normaliser(cle), e)
            self.par_famille.setdefault(normaliser(e["famille"]), []).append(e)

    def _ajouter(self, entrees):
        with self._verrou:
            self.entrees.extend(entrees)
            self._indexer()

    # -- consultation --

    def familles(self):
        self.attendre()
        return sorted({e["famille"] for e in self.entrees}, key=str.lower)

    def variante(self, famille, poids=400, italique=False):
        """Meilleure police d'une famille pour une graisse et un style donnés."""
        self.attendre()
        candidats = self.par_famille.get(normaliser(famille))
        if not candidats:
            return None
        return min(candidats, key=lambda e: (e["italique"] != italique, abs(e["poids"] - poids)))

    def chercher(self, nom_pdf, gras=None, italique=None):
        """Trouve la police installée correspondant à un nom de police PDF.

        Renvoie (entrée, exacte) ; exacte = même police (et pas une simple équivalente)."""
        self.attendre()
        e = self.par_nom.get(normaliser(nom_pdf))
        if e:
            return e, True
        famille, poids, ita = analyser_nom(nom_pdf, gras, italique)
        for nom_famille, exacte in [(famille, True)] + [(eq, False) for eq in EQUIVALENTS.get(famille, [])]:
            candidats = self.par_famille.get(nom_famille)
            if candidats:
                meilleur = min(candidats, key=lambda c: (c["italique"] != ita, abs(c["poids"] - poids)))
                ok = exacte and meilleur["italique"] == ita and abs(meilleur["poids"] - poids) < 50
                return meilleur, ok
        return None, False

    def contenu(self, entree):
        """Octets du fichier de police (extrait d'une collection .ttc si besoin)."""
        cle = (entree["chemin"], entree["index"])
        if cle not in self._contenus:
            ext = os.path.splitext(entree["chemin"])[1].lower()
            if ext in (".ttc", ".otc"):
                from fontTools.ttLib import TTCollection
                buf = io.BytesIO()
                TTCollection(entree["chemin"]).fonts[entree["index"]].save(buf)
                self._contenus[cle] = buf.getvalue()
            else:
                with open(entree["chemin"], "rb") as f:
                    self._contenus[cle] = f.read()
        return self._contenus[cle]

    def ajouter_fichiers(self, chemins):
        """Copie des fichiers de police dans le dossier du programme et les ajoute à l'index."""
        self.attendre()
        ajoutees = []
        for c in chemins:
            if not c.lower().endswith(EXTENSIONS):
                continue
            dest = os.path.join(dossier_polices_perso(), os.path.basename(c))
            if os.path.abspath(c) != os.path.abspath(dest):
                shutil.copy2(c, dest)
            ajoutees.extend(_lire_fichier(dest))
        self._ajouter(ajoutees)
        return ajoutees

    # -- Google Fonts --

    def telecharger_google(self, nom_pdf, gras=None, italique=None, delai=10):
        """Télécharge depuis Google Fonts la police correspondant au nom PDF. Renvoie l'entrée ou None."""
        self.attendre()
        famille, poids, ita = analyser_nom(nom_pdf, gras, italique)
        candidats = [famille] + EQUIVALENTS.get(famille, [])
        for fam in candidats:
            if fam in STANDARD_PDF or fam in self._absentes_google or len(fam) < 2:
                continue
            try:
                entree = self._telecharger_famille(fam, poids, ita, delai)
            except Exception:
                entree = None
            if entree:
                return entree
            self._absentes_google.add(fam)
        return None

    def _telecharger_famille(self, dossier_famille, poids, italique, delai):
        meta, licence = None, None
        for lic in ("ofl", "apache", "ufl"):
            try:
                meta = _http(f"https://raw.githubusercontent.com/google/fonts/main/{lic}/{dossier_famille}/METADATA.pb",
                             delai).decode("utf-8")
                licence = lic
                break
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
        if not meta:
            return None
        nom_famille = re.search(r'^name:\s*"(.*)"', meta, re.M).group(1)
        blocs = []
        for b in re.findall(r"fonts\s*\{(.*?)\n\}", meta, re.S):
            champ = lambda k: (re.search(rf'{k}:\s*"?([^"\n]*)"?', b) or [None, ""])[1]
            blocs.append({"style": champ("style"), "poids": int(champ("weight") or 400),
                          "fichier": champ("filename"), "ps": champ("post_script_name")})
        if not blocs:
            return None
        bloc = min(blocs, key=lambda b: ((b["style"] == "italic") != italique, abs(b["poids"] - poids)))
        donnees = _http(f"https://raw.githubusercontent.com/google/fonts/main/{licence}/{dossier_famille}/"
                        + urllib.parse.quote(bloc["fichier"]), delai * 3)

        nom_style = NOMS_POIDS.get(round(poids / 100) * 100, "Regular")
        if "[" in bloc["fichier"]:  # police variable : on fige la graisse voulue
            from fontTools.ttLib import TTFont
            from fontTools.varLib import instancer
            f = TTFont(io.BytesIO(donnees))
            limites = {}
            for axe in f["fvar"].axes:
                v = axe.defaultValue
                if axe.axisTag == "wght":
                    v = max(axe.minValue, min(axe.maxValue, poids))
                limites[axe.axisTag] = v
            try:
                f = instancer.instantiateVariableFont(f, limites, updateFontNames=True)
            except Exception:
                f = instancer.instantiateVariableFont(TTFont(io.BytesIO(donnees)), limites)
            if "OS/2" in f and "wght" in limites:
                f["OS/2"].usWeightClass = int(limites["wght"])
            buf = io.BytesIO()
            f.save(buf)
            donnees = buf.getvalue()
            poids_reel = int(limites.get("wght", bloc["poids"]))
        else:
            poids_reel = bloc["poids"]
            nom_style = NOMS_POIDS.get(poids_reel, "Regular")
        if bloc["style"] == "italic":
            nom_style = "Italic" if nom_style == "Regular" else nom_style + "Italic"
        ps = nom_famille.replace(" ", "") + "-" + nom_style
        chemin = os.path.join(dossier_polices_perso(), ps + ".ttf")
        with open(chemin, "wb") as fichier:
            fichier.write(donnees)
        entree = {"chemin": chemin, "index": 0, "famille": nom_famille, "style": nom_style, "ps": ps,
                  "complet": f"{nom_famille} {nom_style}", "poids": poids_reel,
                  "italique": bloc["style"] == "italic", "source": "Google Fonts"}
        self._ajouter([entree])
        return entree


def _http(url, delai):
    if sys.platform == "emscripten":
        # dans le navigateur (PWA) : pas de connexion directe, on passe par une requête du navigateur
        # (synchrone, autorisée dans un Web Worker)
        from js import Uint8Array, XMLHttpRequest
        xhr = XMLHttpRequest.new()
        xhr.open("GET", url, False)
        xhr.responseType = "arraybuffer"
        xhr.send(None)
        if xhr.status != 200:
            raise urllib.error.HTTPError(url, xhr.status or 599, "erreur réseau", None, None)
        return Uint8Array.new(xhr.response).to_py().tobytes()
    req = urllib.request.Request(url, headers={"User-Agent": "pdf-editeur"})
    with urllib.request.urlopen(req, timeout=delai) as r:
        return r.read()


INDEX = IndexPolices()


# --------------------------------------------------------------------------- #
# Installation
# --------------------------------------------------------------------------- #

def installer_dans_windows(chemin):
    """Installe une police pour l'utilisateur Windows courant (sans droits administrateur),
    pour qu'elle soit aussi utilisable dans Word, etc. Renvoie True si c'est fait."""
    if sys.platform != "win32":
        return False
    import ctypes
    import winreg
    dossier = os.path.join(os.environ["LOCALAPPDATA"], "Microsoft", "Windows", "Fonts")
    os.makedirs(dossier, exist_ok=True)
    dest = os.path.join(dossier, os.path.basename(chemin))
    if not os.path.exists(dest):
        shutil.copy2(chemin, dest)
    try:
        nom = _lire_fichier(dest)[0]["complet"]
    except Exception:
        nom = os.path.splitext(os.path.basename(dest))[0]
    genre = "OpenType" if dest.lower().endswith(".otf") else "TrueType"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\Fonts",
                        0, winreg.KEY_SET_VALUE) as cle:
        winreg.SetValueEx(cle, f"{nom} ({genre})", 0, winreg.REG_SZ, dest)
    ctypes.windll.gdi32.AddFontResourceW(dest)
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001D, 0, 0, 0x0002, 1000, None)  # WM_FONTCHANGE
    return True


def ajouter_octets(nom_fichier, donnees):
    """Enregistre une police (octets) dans le dossier du programme et l'ajoute à l'index."""
    chemin = os.path.join(dossier_polices_perso(), nom_fichier)
    with open(chemin, "wb") as f:
        f.write(donnees)
    entrees = _lire_fichier(chemin)
    INDEX._ajouter(entrees)
    return chemin, entrees


def etat_polices_document(doc):
    """Pour chaque police d'un document PyMuPDF : (nom, intégrée, partielle, état, détail, xref, ext).
    état : 'installee', 'equivalente', 'manquante' ou 'standard'."""
    INDEX.attendre()
    vues, res = set(), []
    for page in doc:
        for xref, ext, _typ, base, *_ in page.get_fonts(full=True):
            nom = sans_prefixe(base)
            if nom in vues or not nom:
                continue
            vues.add(nom)
            integree, partielle = ext not in ("n/a", ""), nom != base
            entree, exacte = INDEX.chercher(nom)
            if exacte:
                etat, detail = "installee", entree["complet"]
            elif not integree and analyser_nom(nom)[0] in STANDARD_PDF | {"timesroman", "timesbold"}:
                etat, detail = "standard", "police standard PDF"
            elif entree:
                etat, detail = "equivalente", entree["complet"]
            else:
                etat, detail = "manquante", ""
            res.append((nom, integree, partielle, etat, detail, xref, ext))
    return res
