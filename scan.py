"""Documents scannés : reconnaissance de texte (OCR) et modification du texte d'une image.

- L'OCR utilise le moteur Tesseract intégré à PyMuPDF : il suffit de télécharger une fois les
  fichiers de langue (français, anglais…), rien d'autre à installer.
- Le texte reconnu est ajouté de façon invisible sur l'image, mot par mot, à sa place exacte :
  le PDF devient sélectionnable, cherchable et modifiable, sans perte de qualité.
- Pour modifier un texte scanné : la zone est recouverte de la couleur du papier, puis le
  nouveau texte est écrit dans la couleur de l'encre, avec la police la plus ressemblante.
"""

import os
import urllib.request

import pymupdf

import polices

URL_LANGUE = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/{}.traineddata"
LANGUES = {"Français": "fra", "Anglais": "eng", "Allemand": "deu", "Espagnol": "spa",
           "Italien": "ita", "Portugais": "por", "Néerlandais": "nld", "Arabe": "ara"}
NOM_POLICE_OCR = "OCRTX"

# Familles essayées pour identifier la police d'un texte scanné (si elles sont disponibles)
FAMILLES_CANDIDATES = [
    "Arial", "Times New Roman", "Calibri", "Cambria", "Verdana", "Georgia", "Tahoma", "Segoe UI",
    "Trebuchet MS", "Century Gothic", "Garamond", "Book Antiqua", "Courier New", "Roboto", "Open Sans",
    "Liberation Sans", "Liberation Serif", "Liberation Mono", "Carlito", "Caladea", "Arimo", "Tinos", "Cousine",
    "DejaVu Sans", "DejaVu Serif",
]
STANDARD = [("Helvetica", "helv", "hebo"), ("Times", "tiro", "tibo"), ("Courier", "cour", "cobo")]


# --------------------------------------------------------------------------- #
# Langues de l'OCR
# --------------------------------------------------------------------------- #

def dossier_tessdata():
    d = os.path.join(polices.dossier_app(), "tessdata")
    os.makedirs(d, exist_ok=True)
    return d


def _tessdata_fourni():
    """Fichiers de langue livrés avec le programme installé (dossier « tessdata » à côté)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "tessdata")


def langues_manquantes(codes):
    manquantes = []
    for c in codes:
        dest = os.path.join(dossier_tessdata(), f"{c}.traineddata")
        if os.path.isfile(dest):
            continue
        fourni = os.path.join(_tessdata_fourni(), f"{c}.traineddata")
        if os.path.isfile(fourni):  # langue livrée avec le programme : pas de téléchargement
            import shutil
            shutil.copyfile(fourni, dest)
            continue
        manquantes.append(c)
    return manquantes


def telecharger_langues(codes, rappel=None):
    """Télécharge les fichiers de langue manquants. rappel(code, octets_lus, total)."""
    for code in langues_manquantes(codes):
        dest = os.path.join(dossier_tessdata(), f"{code}.traineddata")
        req = urllib.request.Request(URL_LANGUE.format(code), headers={"User-Agent": "pdf-editeur"})
        with urllib.request.urlopen(req, timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0)
            morceaux, lus = [], 0
            while True:
                bloc = r.read(256 * 1024)
                if not bloc:
                    break
                morceaux.append(bloc)
                lus += len(bloc)
                if rappel:
                    rappel(code, lus, total)
        with open(dest + ".part", "wb") as f:
            f.write(b"".join(morceaux))
        os.replace(dest + ".part", dest)


# --------------------------------------------------------------------------- #
# Détection
# --------------------------------------------------------------------------- #

def a_couche_texte_invisible(page):
    """Vrai si la page porte déjà du texte invisible (OCR fait par ce programme ou un scanner)."""
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                if s.get("alpha", 255) == 0 and s["text"].strip():
                    return True
    return False


def est_scannee(page):
    """Vrai si la page n'est qu'une image (aucun texte) : il faut l'OCR pour la modifier."""
    if page.get_text().strip():
        return False
    surface = abs(page.rect)
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & page.rect
        if abs(r) > 0.4 * surface:
            return True
    return False


def pages_a_reconnaitre(doc):
    return [i for i, p in enumerate(doc) if est_scannee(p)]


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #

def reconnaitre_page(page, langues=("fra", "eng"), dpi=300):
    """OCR d'une page : ajoute le texte reconnu de façon invisible. Renvoie le nombre de mots."""
    manquantes = langues_manquantes(langues)  # copie aussi les langues livrées avec le programme
    if manquantes:
        telecharger_langues(manquantes)
    tp = page.get_textpage_ocr(flags=0, language="+".join(langues), dpi=dpi, full=True,
                               tessdata=dossier_tessdata())
    mots = [{"text": s["text"], "bbox": s["bbox"], "origin": s["origin"], "size": s["size"]}
            for b in page.get_text("dict", textpage=tp)["blocks"] for l in b.get("lines", [])
            for s in l["spans"] if s["text"].strip()]
    return inserer_mots(page, mots)


def inserer_mots(page, mots):
    """Pose de façon invisible des mots reconnus par un OCR (le moteur intégré, ou Tesseract.js
    dans le navigateur). mots : [{"text", "bbox", "origin" (x, y de la ligne de base), "size"}]
    en coordonnées de la page non pivotée. Renvoie le nombre de mots posés."""
    mots = [m for m in mots if m["text"].strip()]
    if not mots:
        return 0
    police = pymupdf.Font("helv")
    page.insert_font(fontname=NOM_POLICE_OCR, fontbuffer=police.buffer)
    # Mots regroupés par ligne : même ligne de base et même taille, pour que le texte se lise
    # (et se recherche) comme une vraie ligne
    mots.sort(key=lambda s: (s["origin"][1], s["bbox"][0]))
    lignes = []
    for s in mots:
        for ligne in lignes:
            if abs(ligne[0]["origin"][1] - s["origin"][1]) < max(2, 0.3 * s["size"]) \
                    and s["bbox"][0] >= ligne[-1]["bbox"][0]:
                ligne.append(s)
                break
        else:
            lignes.append([s])
    n = 0
    for ligne in lignes:
        base = sorted(s["origin"][1] for s in ligne)[len(ligne) // 2]
        taille = max(2.0, sorted(s["size"] for s in ligne)[len(ligne) // 2])
        for s in ligne:
            texte = s["text"].strip()
            r = pymupdf.Rect(s["bbox"])
            naturel = police.text_length(texte, fontsize=taille) or 1
            origine = pymupdf.Point(r.x0, base)
            page.insert_text(origine, texte, fontname=NOM_POLICE_OCR, fontsize=taille, render_mode=3,
                             morph=(origine, pymupdf.Matrix(r.width / naturel, 1)))
            n += 1
    return n


# --------------------------------------------------------------------------- #
# Analyse de l'image : couleurs et police
# --------------------------------------------------------------------------- #

def zone_encre(rect):
    """Zone occupée par l'encre d'un texte de la couche invisible (déjà jambages compris)."""
    h = rect.height
    return pymupdf.Rect(rect.x0 - 0.1 * h, rect.y0 + 0.04 * h, rect.x1 + 0.1 * h, rect.y1 + 0.02 * h)


def _gris(pix):
    """Pixmap -> liste de niveaux de gris."""
    s, n = pix.samples, pix.n
    if n == 1:
        return list(s)
    return [(s[i] * 299 + s[i + 1] * 587 + s[i + 2] * 114) // 1000 for i in range(0, len(s), n)]


def couleurs(page, rect):
    """(couleur du papier, couleur de l'encre) en RVB 0..1, mesurées sur l'image."""
    zone = zone_encre(rect) & page.rect
    pix = page.get_pixmap(clip=zone, dpi=100, colorspace=pymupdf.csRGB, alpha=False)
    s = pix.samples
    px = [(s[i], s[i + 1], s[i + 2]) for i in range(0, len(s), 3)]
    if not px:
        return (1, 1, 1), (0, 0, 0)
    lum = [(r * 299 + g * 587 + b * 114) // 1000 for r, g, b in px]
    ordre = sorted(range(len(px)), key=lambda i: lum[i])
    clairs = [px[i] for i in ordre[len(ordre) // 2:]]
    fond = tuple(sorted(c[k] for c in clairs)[len(clairs) // 2] / 255 for k in range(3))
    seuil = (lum[ordre[len(ordre) // 2]] + lum[ordre[0]]) / 2
    fonces = [px[i] for i in ordre if lum[i] < seuil][: max(1, len(px) // 20)]
    encre = tuple(sum(c[k] for c in fonces) / len(fonces) / 255 for k in range(3)) if fonces else (0, 0, 0)
    return fond, encre


def _encre(pix, seuil=None):
    """Ensemble des pixels d'encre {(x, y)} d'une pixmap en niveaux de gris."""
    gris, l = _gris(pix), pix.width
    if seuil is None:
        ordre = sorted(gris)
        seuil = (ordre[len(ordre) // 2] + ordre[0]) / 2
    return {(i % l, i // l) for i, v in enumerate(gris) if v < seuil}


def _boite(points):
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def _dilater(points):
    return {(x + dx, y + dy) for x, y in points for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))}


def _ressemblance(original, essai):
    """Score entre 0 et 1 : recouvrement exact des encres (au pixel près, après recalage),
    pénalisé si la hauteur des lettres diffère."""
    ox0, oy0, ox1, oy1 = _boite(original)
    cx0, cy0, cx1, cy1 = _boite(essai)
    dx0 = ox0 - cx0
    dy0 = round(((oy0 + oy1) - (cy0 + cy1)) / 2)
    meilleur = 0
    for ddx in (-1, 0, 1):
        for ddy in (-1, 0, 1):
            decale = {(x + dx0 + ddx, y + dy0 + ddy) for x, y in essai}
            meilleur = max(meilleur, len(decale & original) / len(decale | original))
    rapport_h = (oy1 - oy0 + 1) / (cy1 - cy0 + 1)
    return meilleur * (1 - min(0.5, abs(1 - rapport_h) * 1.5))


def etendre_a_l_encre(page, zone):
    """Agrandit la zone pour couvrir toute l'encre du texte : le cadre de l'OCR est approximatif
    (lettres coupées en haut, jambages, bords). On suit l'encre jusqu'au blanc qui sépare
    les lignes (en hauteur) et les mots (en largeur)."""
    h = zone.height
    large = pymupdf.Rect(zone.x0 - 0.5 * h, zone.y0 - 0.45 * h, zone.x1 + 0.5 * h, zone.y1 + 0.45 * h) & page.rect
    dpi = 200
    e = 72 / dpi
    pix = page.get_pixmap(clip=large, dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    encre = _encre(pix)
    if not encre:
        return zone
    g, d = int((zone.x0 - large.x0) / e), int((zone.x1 - large.x0) / e)
    hau, bas = int((zone.y0 - large.y0) / e), int((zone.y1 - large.y0) / e)
    # en hauteur : rangées contenant de l'encre dans la largeur du texte
    rangs = {y for x, y in encre if g <= x <= d}
    while hau - 1 in rangs:
        hau -= 1
    while bas + 1 in rangs:
        bas += 1
    # en largeur : colonnes contenant de l'encre dans la hauteur obtenue
    colonnes = {x for x, y in encre if hau <= y <= bas}
    while g - 1 in colonnes:
        g -= 1
    while d + 1 in colonnes:
        d += 1
    return pymupdf.Rect(large.x0 + g * e - 0.3, large.y0 + hau * e - 0.3,
                        large.x0 + (d + 1) * e + 0.3, large.y0 + (bas + 1) * e + 0.3)


def ligne_de_base(page, rect):
    """Ligne de base mesurée sur l'image : dernière rangée de pixels bien remplie
    (les jambages de p, g, j sont plus fins et ignorés)."""
    zone = zone_encre(rect) & page.rect
    pix = page.get_pixmap(clip=zone, dpi=200, colorspace=pymupdf.csGRAY, alpha=False)
    encre = _encre(pix)
    if len(encre) < 10:
        return None
    rangs = [0] * pix.height
    for _x, y in encre:
        rangs[y] += 1
    seuil = max(rangs) * 0.25
    y = max(i for i, n in enumerate(rangs) if n >= seuil)
    return zone.y0 + (y + 1) * 72 / 200


def _candidats():
    """[(libellé, entrée de l'index ou None, nom interne standard ou None, gras)]."""
    polices.INDEX.attendre()
    res, vues = [], set()
    for fam in FAMILLES_CANDIDATES:
        for gras in (False, True):
            e = polices.INDEX.variante(fam, 700 if gras else 400, False)
            if e and polices.normaliser(e["famille"]) == polices.normaliser(fam) \
                    and (e["chemin"], e["index"]) not in vues and (e["poids"] >= 600) == gras:
                vues.add((e["chemin"], e["index"]))
                res.append((e["complet"], e, None, gras))
    for nom, reg, gras_nom in STANDARD:
        res.append((nom, None, reg, False))
        res.append((nom + " Bold", None, gras_nom, True))
    return res


_cache_fontes = {}


def _fonte(entree, interne):
    cle = (entree["chemin"], entree["index"]) if entree else interne
    if cle not in _cache_fontes:
        _cache_fontes[cle] = pymupdf.Font(fontbuffer=polices.INDEX.contenu(entree)) if entree \
            else pymupdf.Font(interne)
    return _cache_fontes[cle]


def deviner_police(page, rect, texte, ligne_base):
    """Identifie la police la plus ressemblante pour un texte scanné.

    Le même texte est écrit dans chaque police candidate, à la même largeur d'encre, puis
    comparé à l'image (superposition des pixels et hauteur des lettres).
    Renvoie {"libelle", "entree", "base14", "taille", "gras", "score"}.
    """
    texte = " ".join(texte.split())  # un texte lu dans une zone peut contenir des retours à la ligne
    zone = zone_encre(rect) & page.rect
    dpi = 200
    original = _encre(page.get_pixmap(clip=zone, dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False))
    hauteur_ref = rect.height / 1.25  # hauteur du cadre ≈ 1,25 × taille réelle
    meilleur = None
    if len(original) < 10:
        original = None
    else:
        ox0, _oy0, ox1, _oy1 = _boite(original)
    essai_page = pymupdf.open()
    for libelle, entree, interne, gras in (_candidats() if original else []):
        try:
            fonte = _fonte(entree, interne)
            if not all(c.isspace() or fonte.has_glyph(ord(c)) for c in texte):
                continue
            naturel = fonte.text_length(texte, fontsize=1)
            if naturel <= 0:
                continue
            taille = rect.width / naturel
            if not 0.6 * hauteur_ref < taille < 1.8 * hauteur_ref:
                continue

            def rendu(t):
                while essai_page.page_count:
                    essai_page.delete_page(0)
                p = essai_page.new_page(width=page.rect.width, height=page.rect.height)
                if entree:
                    p.insert_font(fontname="C", fontbuffer=polices.INDEX.contenu(entree))
                p.insert_text((rect.x0, ligne_base), texte, fontname="C" if entree else interne, fontsize=t)
                return _encre(p.get_pixmap(clip=zone, dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False), 128)

            essai = rendu(taille)
            if len(essai) < 10:
                continue
            cx0, _y, cx1, _y2 = _boite(essai)
            taille *= (ox1 - ox0 + 1) / (cx1 - cx0 + 1)  # même largeur d'encre que l'original
            essai = rendu(taille)
            if len(essai) < 10:
                continue
            score = _ressemblance(original, essai)
            if not meilleur or score > meilleur["score"]:
                meilleur = {"libelle": libelle, "entree": entree, "base14": interne, "taille": taille,
                            "gras": gras, "score": score}
        except Exception:
            continue
    return meilleur or {"libelle": "Helvetica", "entree": None, "base14": "helv",
                        "taille": hauteur_ref, "gras": False, "score": 0}


# --------------------------------------------------------------------------- #
# Modification d'un texte scanné
# --------------------------------------------------------------------------- #

def remplacer_texte_scanne(page, rect, nouveau, spans, ligne_base, style=None, decaler=True, cache=None):
    """Remplace le texte scanné situé dans `rect` (zone d'une couche OCR invisible).

    Renvoie un dict {police, taille, decale, deborde, raison} comme pdftool._remplacer_occurrence.
    """
    import pdftool
    style = style or {}
    cache = {} if cache is None else cache
    ancien = " ".join(page.get_text("text", clip=rect).split()) or nouveau
    fond, encre = couleurs(page, rect)
    ligne = next((l for l in lignes_scannees(page)
                  if pymupdf.Rect(l["bbox"]).intersects(rect) and abs(l["origin"][1] - ligne_base) < 2), None)
    base_ocr = ligne_base  # ligne de base de la couche invisible (pour retrouver la suite de la ligne)
    mesuree = ligne_de_base(page, pymupdf.Rect(ligne["bbox"]) if ligne else rect)
    if mesuree and abs(mesuree - ligne_base) < rect.height * 0.5:
        ligne_base = mesuree

    # Police : celle imposée, sinon la plus ressemblante (mémorisée par hauteur de ligne)
    g = {}
    if style.get("entree") or style.get("base14"):
        entree, interne = style.get("entree"), style.get("base14")
        desc = (entree["complet"] if entree else interne) + " (choisie)"
        taille = style.get("taille")
    else:
        # identification sur la ligne entière (plus fiable qu'un mot seul)
        ref_rect, ref_texte = (pymupdf.Rect(ligne["bbox"]), ligne["text"]) if ligne else (rect, ancien)
        cle = ("devine", tuple(round(v) for v in ref_rect))
        if cle not in cache:
            cache[cle] = deviner_police(page, ref_rect, ref_texte, ligne_base)
        g = cache[cle]
        entree, interne = g["entree"], g["base14"]
        desc = f"{g['libelle']} (police estimée d'après l'image)"
        taille = None
    fonte = _fonte(entree, interne)
    if not all(c.isspace() or fonte.has_glyph(ord(c)) for c in nouveau):
        entree, interne, fonte = None, "helv", _fonte(None, "helv")
    if not taille:
        taille = g["taille"] if g.get("score") else rect.width / (fonte.text_length(ancien, fontsize=1) or 1)
    couleur = style.get("couleur") or encre
    largeur = fonte.text_length(nouveau, fontsize=taille) if nouveau else 0
    decalage = rect.x0 + largeur - rect.x1

    # Suite de la ligne (image) à décaler
    zone_effacee = etendre_a_l_encre(page, zone_encre(rect))
    suite = pdftool._suite_de_ligne(spans, rect, base_ocr) if decaler and page.rotation == 0 else []
    zone_suite = None
    if suite and abs(decalage) > 0.5:
        xs = [c["bbox"][2] for _s, _t, cs in suite for c in cs]
        zone_suite = zone_encre(pymupdf.Rect(rect.x1, rect.y0, max(xs), rect.y1)) & page.rect
        zone_suite = etendre_a_l_encre(page, zone_suite)
        zone_suite.x0 = max(zone_suite.x0, zone_effacee.x1)
        image_suite = page.get_pixmap(clip=zone_suite, dpi=300, alpha=False)
    else:
        suite = []

    # 1. Retirer le texte invisible (ancien mot + suite)
    page.add_redact_annot(pdftool._zone_effacement(rect), fill=False)
    for _s, _t, cs in suite:
        z = pymupdf.Rect(cs[0]["bbox"])
        for c in cs[1:]:
            z |= c["bbox"]
        page.add_redact_annot(pdftool._zone_effacement(z), fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)

    # 2. Recouvrir l'image de la couleur du papier
    page.draw_rect(zone_effacee, color=None, fill=fond, overlay=True)
    if zone_suite:
        page.draw_rect(zone_suite, color=None, fill=fond, overlay=True)
        page.insert_image(zone_suite + (decalage, 0, decalage, 0), pixmap=image_suite)
        # le texte invisible de la suite suit l'image
        police = pymupdf.Font("helv")
        page.insert_font(fontname=NOM_POLICE_OCR, fontbuffer=police.buffer)
        for s, texte, cs in suite:
            for mot in _mots(cs):
                t = "".join(c["c"] for c in mot).strip()
                if not t:
                    continue
                r = pymupdf.Rect(mot[0]["bbox"])
                for c in mot[1:]:
                    r |= c["bbox"]
                naturel = police.text_length(t, fontsize=s["size"]) or 1
                o = pymupdf.Point(r.x0 + decalage, s["origin"][1])
                page.insert_text(o, t, fontname=NOM_POLICE_OCR, fontsize=s["size"], render_mode=3,
                                 morph=(o, pymupdf.Matrix(r.width / naturel, 1)))

    # 3. Écrire le nouveau texte
    if nouveau:
        if entree:
            nom = pdftool._cle_entree(entree)
            page.insert_font(fontname=nom, fontbuffer=polices.INDEX.contenu(entree))
        else:
            nom = interne
        page.insert_text((rect.x0, ligne_base), nouveau, fontname=nom, fontsize=taille, color=couleur)
    return {"police": desc, "taille": taille, "decale": bool(suite), "raison": None,
            "deborde": not suite and largeur > rect.width + 1 and
            bool(pdftool._suite_de_ligne(spans, rect, base_ocr))}


def _mots(chars):
    mots, courant = [], []
    for c in chars:
        if c["c"].isspace():
            if courant:
                mots.append(courant)
            courant = []
        else:
            courant.append(c)
    if courant:
        mots.append(courant)
    return mots


def lignes_scannees(page):
    """Regroupe les mots invisibles (OCR) en lignes éditables : [{"text", "bbox", "origin", "size"}]."""
    mots = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                if s.get("alpha", 255) == 0 and s["text"].strip():
                    mots.append(s)
    mots.sort(key=lambda s: (round(s["origin"][1]), s["bbox"][0]))
    lignes = []
    for s in mots:
        r = pymupdf.Rect(s["bbox"])
        for ligne in lignes:
            meme_base = abs(ligne["origin"][1] - s["origin"][1]) < max(2, 0.35 * s["size"])
            proche = r.x0 - ligne["bbox"].x1 < 2.5 * s["size"]
            if meme_base and proche and r.x0 >= ligne["bbox"].x0:
                ligne["text"] += ("" if ligne["text"].endswith(" ") else " ") + s["text"].strip()
                ligne["bbox"] |= r
                break
        else:
            lignes.append({"text": s["text"].strip(), "bbox": r, "origin": s["origin"], "size": s["size"],
                           "font": "Texte scanné", "flags": 0, "color": 0, "alpha": 0, "scan": True})
    for ligne in lignes:
        ligne["bbox"] = tuple(ligne["bbox"])
    return lignes
