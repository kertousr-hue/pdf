#!/usr/bin/env python3
"""pdftool - lire et modifier des fichiers PDF en ligne de commande.

Exemples :
    python pdftool.py info document.pdf
    python pdftool.py texte document.pdf --pages 1-3
    python pdftool.py fusionner sortie.pdf a.pdf b.pdf
    python pdftool.py extraire document.pdf sortie.pdf --pages 2,4-6
    python pdftool.py supprimer document.pdf sortie.pdf --pages 3
    python pdftool.py pivoter document.pdf sortie.pdf --angle 90 --pages 1
    python pdftool.py ajouter-texte document.pdf sortie.pdf --texte "Bonjour" --x 100 --y 700 --pages 1
    python pdftool.py filigrane document.pdf sortie.pdf --texte "CONFIDENTIEL"
    python pdftool.py metadonnees document.pdf sortie.pdf --titre "Mon titre" --auteur "Moi"
    python pdftool.py chiffrer document.pdf sortie.pdf --mot-de-passe secret
    python pdftool.py dechiffrer protege.pdf sortie.pdf --mot-de-passe secret
"""

import argparse
import io
import os
import sys

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import Color
from reportlab.pdfgen import canvas


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #

def parse_pages(spec, total):
    """Convertit "1,3-5" en liste d'indices (base 0). None => toutes les pages."""
    if not spec:
        return list(range(total))
    indices = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            debut, fin = part.split("-", 1)
            debut = int(debut) if debut else 1
            fin = int(fin) if fin else total
        else:
            debut = fin = int(part)
        if debut < 1 or fin > total or debut > fin:
            raise ValueError(f"Plage de pages invalide : '{part}' (le document a {total} pages)")
        indices.extend(range(debut - 1, fin))
    return indices


def ouvrir(chemin, mot_de_passe=None):
    reader = PdfReader(chemin)
    if reader.is_encrypted:
        if not mot_de_passe or not reader.decrypt(mot_de_passe):
            raise ValueError(f"'{chemin}' est protégé : mot de passe manquant ou incorrect")
    return reader


def enregistrer(writer, chemin):
    with open(chemin, "wb") as f:
        writer.write(f)
    print(f"Fichier enregistré : {chemin}")


def calque_texte(largeur, hauteur, dessiner):
    """Crée une page PDF transparente de la taille donnée et y dessine via `dessiner(canvas)`."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(largeur, hauteur))
    dessiner(c)
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


# --------------------------------------------------------------------------- #
# Commandes de lecture
# --------------------------------------------------------------------------- #

def cmd_info(args):
    reader = ouvrir(args.fichier, args.mot_de_passe)
    meta = reader.metadata or {}
    print(f"Fichier      : {args.fichier}")
    print(f"Pages        : {len(reader.pages)}")
    print(f"Chiffré      : {'oui' if reader.is_encrypted else 'non'}")
    for cle, nom in [("/Title", "Titre"), ("/Author", "Auteur"), ("/Subject", "Sujet"),
                     ("/Creator", "Créateur"), ("/Producer", "Producteur")]:
        if meta.get(cle):
            print(f"{nom:<13}: {meta.get(cle)}")
    if reader.pages:
        box = reader.pages[0].mediabox
        print(f"Taille p.1   : {float(box.width):.0f} x {float(box.height):.0f} pt")


def cmd_texte(args):
    reader = ouvrir(args.fichier, args.mot_de_passe)
    morceaux = []
    for i in parse_pages(args.pages, len(reader.pages)):
        texte = reader.pages[i].extract_text() or ""
        morceaux.append(f"===== Page {i + 1} =====\n{texte}")
    resultat = "\n\n".join(morceaux)
    if args.sortie:
        with open(args.sortie, "w", encoding="utf-8") as f:
            f.write(resultat)
        print(f"Texte enregistré : {args.sortie}")
    else:
        print(resultat)


# --------------------------------------------------------------------------- #
# Commandes de modification
# --------------------------------------------------------------------------- #

def cmd_fusionner(args):
    writer = PdfWriter()
    for chemin in args.fichiers:
        for page in ouvrir(chemin).pages:
            writer.add_page(page)
    enregistrer(writer, args.sortie)


def cmd_extraire(args):
    reader = ouvrir(args.fichier, args.mot_de_passe)
    writer = PdfWriter()
    for i in parse_pages(args.pages, len(reader.pages)):
        writer.add_page(reader.pages[i])
    enregistrer(writer, args.sortie)


def cmd_supprimer(args):
    reader = ouvrir(args.fichier, args.mot_de_passe)
    a_supprimer = set(parse_pages(args.pages, len(reader.pages)))
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i not in a_supprimer:
            writer.add_page(page)
    if not writer.pages:
        raise ValueError("Impossible de supprimer toutes les pages")
    enregistrer(writer, args.sortie)


def cmd_pivoter(args):
    if args.angle % 90 != 0:
        raise ValueError("L'angle doit être un multiple de 90")
    reader = ouvrir(args.fichier, args.mot_de_passe)
    cibles = set(parse_pages(args.pages, len(reader.pages)))
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i in cibles:
            page.rotate(args.angle)
        writer.add_page(page)
    enregistrer(writer, args.sortie)


def cmd_ajouter_texte(args):
    reader = ouvrir(args.fichier, args.mot_de_passe)
    cibles = set(parse_pages(args.pages, len(reader.pages)))
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i in cibles:
            box = page.mediabox
            largeur, hauteur = float(box.width), float(box.height)

            def dessiner(c):
                c.setFont("Helvetica", args.taille)
                c.setFillColorRGB(*args.couleur)
                for n, ligne in enumerate(args.texte.split("\\n")):
                    c.drawString(args.x, args.y - n * args.taille * 1.2, ligne)

            page.merge_page(calque_texte(largeur, hauteur, dessiner))
        writer.add_page(page)
    enregistrer(writer, args.sortie)


def cmd_filigrane(args):
    reader = ouvrir(args.fichier, args.mot_de_passe)
    cibles = set(parse_pages(args.pages, len(reader.pages)))
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i in cibles:
            box = page.mediabox
            largeur, hauteur = float(box.width), float(box.height)

            def dessiner(c):
                c.saveState()
                c.setFillColor(Color(0.6, 0.6, 0.6, alpha=args.opacite))
                c.setFont("Helvetica-Bold", args.taille)
                c.translate(largeur / 2, hauteur / 2)
                c.rotate(45)
                c.drawCentredString(0, 0, args.texte)
                c.restoreState()

            page.merge_page(calque_texte(largeur, hauteur, dessiner))
        writer.add_page(page)
    enregistrer(writer, args.sortie)


def cmd_metadonnees(args):
    reader = ouvrir(args.fichier, args.mot_de_passe)
    writer = PdfWriter(clone_from=reader)
    nouvelles = {}
    if args.titre is not None:
        nouvelles["/Title"] = args.titre
    if args.auteur is not None:
        nouvelles["/Author"] = args.auteur
    if args.sujet is not None:
        nouvelles["/Subject"] = args.sujet
    if not nouvelles:
        raise ValueError("Indiquez au moins --titre, --auteur ou --sujet")
    writer.add_metadata(nouvelles)
    enregistrer(writer, args.sortie)


# --------------------------------------------------------------------------- #
# Polices et remplacement de texte (PyMuPDF)
# --------------------------------------------------------------------------- #

def ouvrir_fitz(chemin, mot_de_passe=None):
    import pymupdf
    doc = pymupdf.open(chemin)
    if doc.needs_pass and not doc.authenticate(mot_de_passe or ""):
        raise ValueError(f"'{chemin}' est protégé : mot de passe manquant ou incorrect")
    return doc


def nom_lisible(basefont):
    """'ABCDEF+Arial-BoldMT' -> 'Arial-BoldMT' (retire le préfixe de sous-ensemble)."""
    if len(basefont) > 7 and basefont[6] == "+":
        return basefont[7:]
    return basefont


def style_span(span):
    flags, nom = span["flags"], span["font"].lower()
    gras = bool(flags & 16) or "bold" in nom or "black" in nom or "heavy" in nom
    italique = bool(flags & 2) or "italic" in nom or "oblique" in nom
    return gras, italique


def couleur_hex(entier):
    return f"#{entier:06x}"


def cmd_polices(args):
    doc = ouvrir_fitz(args.fichier, args.mot_de_passe)
    pages = parse_pages(args.pages, doc.page_count)

    # 1) Polices déclarées dans le fichier
    vues = {}
    for i in pages:
        for _xref, ext, typ, basefont, _nom, _enc, *_ in doc[i].get_fonts(full=True):
            entree = vues.setdefault((basefont, typ, ext), {"nom": basefont, "type": typ, "ext": ext, "pages": []})
            entree["pages"].append(i + 1)

    print(f"Polices utilisées ({len(vues)}) :")
    for e in sorted(vues.values(), key=lambda e: e["nom"]):
        integree = "non intégrée" if e["ext"] == "n/a" else f"intégrée ({e['ext']})"
        sous_ens = ", sous-ensemble" if nom_lisible(e["nom"]) != e["nom"] else ""
        pages_txt = ",".join(map(str, sorted(set(e["pages"]))))
        print(f"  - {nom_lisible(e['nom']):<32} {e['type']:<10} {integree}{sous_ens}  pages {pages_txt}")

    # 2) Détail : police utilisée pour chaque morceau de texte
    if args.detail or args.chercher:
        print()
        for i in pages:
            for bloc in doc[i].get_text("dict")["blocks"]:
                for ligne in bloc.get("lines", []):
                    for span in ligne["spans"]:
                        txt = span["text"].strip()
                        if not txt or (args.chercher and args.chercher not in span["text"]):
                            continue
                        gras, ita = style_span(span)
                        style = " ".join(s for s, ok in (("gras", gras), ("italique", ita)) if ok) or "normal"
                        print(f"  p.{i + 1}  {span['font']:<28} {span['size']:5.1f} pt  "
                              f"{style:<15} {couleur_hex(span['color'])}  « {txt[:60]} »")


# Télécharger automatiquement depuis Google Fonts les polices introuvables sur l'ordinateur
TELECHARGER_POLICES = True

BASE14 = {
    "Helvetica": ("helv", "hebo", "heit", "hebi"),
    "Times": ("tiro", "tibo", "tiit", "tibi"),
    "Courier": ("cour", "cobo", "coit", "cobi"),
}
NOMS_BASE14 = {
    "Helvetica": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "Times": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "Courier": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
}


def _famille_base14(nom, flags=0):
    nom = nom.lower()
    if flags & 8 or any(k in nom for k in ("courier", "mono", "consol")):
        return "Courier"
    if (flags & 4 or any(k in nom for k in ("times", "serif", "roman", "georgia", "garamond", "cambria"))) \
            and "sans" not in nom:
        return "Times"
    return "Helvetica"


def _charger_police(page, cache, cle, contenu, texte):
    """Vérifie qu'une police (octets) contient tous les caractères de `texte` ; la garde en cache."""
    import pymupdf
    if cle not in cache:
        try:
            police = pymupdf.Font(fontbuffer=contenu)
            cache[cle] = police
            cache.setdefault("_contenus", {})[cle] = contenu
        except Exception:
            cache[cle] = None
    police = cache[cle]
    if police is None or not all(c.isspace() or police.has_glyph(ord(c)) for c in texte):
        return None
    return cle


def _cle_entree(entree):
    import hashlib
    return "F" + hashlib.md5(f"{entree['chemin']}|{entree['index']}".encode()).hexdigest()[:10]


def police_installee(page, cache, entree, texte):
    """Prépare une police de l'index (polices.INDEX) pour écrire `texte`. Renvoie le nom interne ou None."""
    import polices
    try:
        return _charger_police(page, cache, _cle_entree(entree), polices.INDEX.contenu(entree), texte)
    except Exception:
        return None


def police_de_remplacement(page, span, texte, cache, fichier_police=None):
    """Choisit la police pour écrire `texte` à la place de `span`, dans cet ordre :

    1. le fichier de police fourni par l'utilisateur ;
    2. la police intégrée au PDF, si elle contient tous les caractères ;
    3. la police standard PDF du même nom (Helvetica, Times, Courier) ;
    4. la même police installée sur l'ordinateur ;
    5. la même police téléchargée depuis Google Fonts (si TELECHARGER_POLICES) ;
    6. une police équivalente installée (ex. Liberation Sans pour Arial) ;
    7. la police standard la plus proche.
    Renvoie (nom_interne, description, exacte).
    """
    import polices
    doc = page.parent
    nom = span["font"]
    gras, ita = style_span(span)

    if fichier_police:
        with open(fichier_police, "rb") as f:
            cle = _charger_police(page, cache, "utilisateur", f.read(), texte)
        if cle:
            return cle, f"{os.path.basename(fichier_police)} (fournie)", True

    for xref, ext, _typ, basefont, *_ in page.get_fonts(full=True):
        if nom_lisible(basefont) == nom and ext not in ("n/a", ""):
            try:
                cle = _charger_police(page, cache, f"orig{xref}", doc.extract_font(xref)[3], texte)
            except Exception:
                cle = None
            if cle:
                return cle, f"{nom} (police d'origine intégrée)", True
            break

    famille14 = _famille_base14(nom, span["flags"])
    variante = (1 if gras else 0) + (2 if ita else 0)
    if NOMS_BASE14[famille14][variante] == nom:
        return BASE14[famille14][variante], f"{nom} (police standard d'origine)", True

    entree, exacte = polices.INDEX.chercher(nom, gras, ita)
    if entree and exacte:
        cle = police_installee(page, cache, entree, texte)
        if cle:
            return cle, f"{entree['complet']} (installée)", True

    if TELECHARGER_POLICES:
        tele = polices.INDEX.telecharger_google(nom, gras, ita)
        if tele:
            cle = police_installee(page, cache, tele, texte)
            if cle:
                meme = polices.normaliser(tele["famille"]) == polices.analyser_nom(nom)[0]
                return cle, f"{tele['complet']} (téléchargée de Google Fonts)", meme
            entree, exacte = polices.INDEX.chercher(nom, gras, ita)

    if entree:
        cle = police_installee(page, cache, entree, texte)
        if cle:
            return cle, f"{entree['complet']} (équivalente à {nom})", False

    nom14 = NOMS_BASE14[famille14][variante]
    return BASE14[famille14][variante], (f"{nom14} (la plus proche de {nom}, introuvable sur l'ordinateur ; "
                                         "ajoutez-la ou utilisez --fichier-police)"), False


def _spans_avec_caracteres(page):
    return [s for b in page.get_text("rawdict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]


def _suite_de_ligne(spans, rect, ligne_base):
    """Caractères situés après `rect` sur la même ligne, regroupés par span : [(span, texte, chars)].

    On s'arrête à un grand espace (changement de colonne, cellule de tableau…)."""
    caracteres = []
    for s in spans:
        if abs(s["origin"][1] - ligne_base) > 1:
            continue
        for c in s["chars"]:
            if (c["bbox"][0] + c["bbox"][2]) / 2 > rect.x1:
                caracteres.append((c, s))
    caracteres.sort(key=lambda cs: cs[0]["origin"][0])
    morceaux, fin_prec = [], rect.x1
    for c, s in caracteres:
        if c["bbox"][0] - fin_prec > 3 * s["size"]:
            break
        fin_prec = max(fin_prec, c["bbox"][2])
        if morceaux and morceaux[-1][0] is s:
            morceaux[-1][1].append(c)
        else:
            morceaux.append((s, [c]))
    return [(s, "".join(c["c"] for c in cs), cs) for s, cs in morceaux]


def _zone_effacement(rect):
    """Rétrécit verticalement la zone : sinon les lettres des lignes voisines serrées sont effacées."""
    import pymupdf
    h = rect.height
    return pymupdf.Rect(rect.x0, rect.y0 + h * 0.3, rect.x1, rect.y1 - h * 0.3)


def _remplacer_occurrence(page, rect, nouveau, taille=None, ajuster=False, fichier_police=None,
                          decaler=True, cache=None, style=None):
    """Remplace le texte situé dans `rect` par `nouveau`.

    style (facultatif) : {"entree": police de l'index, "base14": nom interne standard,
                          "taille": float, "couleur": (r, g, b)} pour imposer la mise en forme."""
    import pymupdf
    cache = {} if cache is None else cache
    style = style or {}
    spans = _spans_avec_caracteres(page)
    span = max(spans, key=lambda s: (pymupdf.Rect(s["bbox"]) & rect).get_area(), default=None)
    if span is None:
        return None
    base = span["origin"][1]

    fontname = None
    if style.get("entree"):
        fontname = police_installee(page, cache, style["entree"], nouveau)
        desc = f"{style['entree']['complet']} (choisie)"
        if not fontname:
            desc = f"{style['entree']['complet']} ne contient pas tous les caractères"
    elif style.get("base14"):
        fontname, desc = style["base14"], "police standard (choisie)"
    if not fontname:
        fontname, desc, _ = police_de_remplacement(page, span, nouveau, cache, fichier_police)
    t = style.get("taille") or taille or span["size"]
    couleur = style.get("couleur") or pymupdf.sRGB_to_pdf(span["color"])
    police = cache.get(fontname) or pymupdf.Font(fontname)
    largeur = police.text_length(nouveau, fontsize=t) if nouveau else 0

    # Suite de la ligne à décaler : seulement si on peut la réécrire dans sa police exacte
    suite, raison = [], None
    if decaler and abs(largeur - rect.width) > 0.5:
        suite = _suite_de_ligne(spans, rect, base)
        for i, (s, texte, cs) in enumerate(suite):
            nom, _d, exacte = police_de_remplacement(page, s, texte, cache)
            if not exacte:
                raison = f"police {s['font']} indisponible"
                suite = []
                break
            suite[i] = (s, texte, cs, nom)

    if ajuster and not suite and largeur > rect.width:
        t *= rect.width / largeur
        largeur = rect.width

    page.add_redact_annot(_zone_effacement(rect), fill=False)
    for _s, _t, cs, _n in suite:
        zone = pymupdf.Rect(cs[0]["bbox"])
        for c in cs[1:]:
            zone |= c["bbox"]
        page.add_redact_annot(_zone_effacement(zone), fill=False)
    # Efface uniquement le texte (pas les images ni les dessins)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)

    # Les polices sont ajoutées après l'effacement (qui retire les ressources inutilisées)
    for nom in {fontname, *(n for *_r, n in suite)}:
        contenu = cache.get("_contenus", {}).get(nom)
        if contenu:
            page.insert_font(fontname=nom, fontbuffer=contenu)
    if nouveau:
        page.insert_text((rect.x0, base), nouveau, fontname=fontname, fontsize=t, color=couleur)
    decalage = rect.x0 + largeur - rect.x1
    for s, texte, cs, nom in suite:
        page.insert_text((cs[0]["origin"][0] + decalage, s["origin"][1]), texte, fontname=nom,
                         fontsize=s["size"], color=pymupdf.sRGB_to_pdf(s["color"]))
    deborde = not suite and largeur > rect.width + 1 and bool(_suite_de_ligne(spans, rect, base))
    return {"police": desc, "taille": t, "decale": bool(suite), "deborde": deborde, "raison": raison}


def modifier_texte(page, rect, nouveau, style=None, decaler=True):
    """Remplace le texte d'une zone précise (utilisé par l'éditeur graphique)."""
    return _remplacer_occurrence(page, rect, nouveau, decaler=decaler, style=style)


def inserer_texte(page, point, texte, entree=None, base14="helv", taille=12, couleur=(0, 0, 0)):
    """Écrit du texte (plusieurs lignes possibles) avec une police de l'index ou une police standard."""
    cache = {}
    nom = police_installee(page, cache, entree, texte) if entree else None
    if nom:
        page.insert_font(fontname=nom, fontbuffer=cache["_contenus"][nom])
    else:
        nom = base14
    for i, ligne in enumerate(texte.split("\n")):
        page.insert_text((point.x, point.y + i * taille * 1.25), ligne, fontname=nom, fontsize=taille,
                         color=couleur, rotate=page.rotation)
    return nom


def remplacer_texte(doc, ancien, nouveau, pages=None, taille=None, ajuster=False,
                    ignorer_casse=False, fichier_police=None, decaler=True):
    """Remplace `ancien` par `nouveau` dans un document PyMuPDF ouvert (modifié sur place).

    `pages` : liste d'indices (base 0), None = toutes.
    `decaler` : décale la suite de la ligne pour qu'elle ne soit pas chevauchée (ou qu'il ne
    reste pas de trou), si la police d'origine de cette suite est disponible.
    Renvoie une liste de dicts {page, police, taille, decale, deborde, raison}.
    """
    resultats = []
    for i in (range(doc.page_count) if pages is None else pages):
        page = doc[i]
        rects = page.search_for(ancien)
        # search_for ignore la casse : on vérifie la correspondance exacte
        if not ignorer_casse:
            rects = [r for r in rects if page.get_text("text", clip=r).strip() == ancien]
        cache = {}
        # De droite à gauche et de bas en haut : un remplacement ne déplace pas les suivants
        for rect in sorted(rects, key=lambda r: (-r.y1, -r.x0)):
            res = _remplacer_occurrence(page, rect, nouveau, taille, ajuster, fichier_police, decaler, cache)
            if res:
                res["page"] = i + 1
                resultats.append(res)
    return resultats


def cmd_remplacer(args):
    global TELECHARGER_POLICES
    TELECHARGER_POLICES = not args.hors_ligne
    doc = ouvrir_fitz(args.fichier, args.mot_de_passe)
    pages = parse_pages(args.pages, doc.page_count)
    resultats = remplacer_texte(doc, args.ancien, args.nouveau, pages, args.taille, args.ajuster,
                                args.ignorer_casse, args.fichier_police, not args.sans_decaler)
    for r in resultats:
        print(f"  p.{r['page']} : « {args.ancien} » -> « {args.nouveau} »  "
              f"police : {r['police']}, {r['taille']:.1f} pt")
        if r["decale"]:
            print("        suite de la ligne décalée")
        if r["deborde"]:
            print("        attention : le nouveau texte est plus long et peut chevaucher la suite"
                  + (f" ({r['raison']}, suite non décalée)" if r["raison"] else "")
                  + " — option --ajuster pour réduire la taille")
    if not resultats:
        raise ValueError(f"Texte « {args.ancien} » introuvable")
    doc.save(args.sortie, garbage=3, deflate=True)
    print(f"{len(resultats)} remplacement(s). Fichier enregistré : {args.sortie}")


def cmd_chiffrer(args):
    reader = ouvrir(args.fichier)
    writer = PdfWriter(clone_from=reader)
    writer.encrypt(user_password=args.mot_de_passe, algorithm="AES-256")
    enregistrer(writer, args.sortie)


def cmd_dechiffrer(args):
    reader = ouvrir(args.fichier, args.mot_de_passe)
    writer = PdfWriter(clone_from=reader)
    enregistrer(writer, args.sortie)


# --------------------------------------------------------------------------- #
# Interface en ligne de commande
# --------------------------------------------------------------------------- #

def couleur(valeur):
    """Accepte '#RRGGBB' et renvoie un tuple (r, g, b) entre 0 et 1."""
    v = valeur.lstrip("#")
    if len(v) != 6:
        raise argparse.ArgumentTypeError("Couleur attendue au format #RRGGBB")
    return tuple(int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))


def construire_parser():
    p = argparse.ArgumentParser(
        prog="pdftool",
        description="Lire et modifier des fichiers PDF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Les pages se notent à partir de 1, ex. : --pages 1,3-5",
    )
    sub = p.add_subparsers(dest="commande", required=True, metavar="COMMANDE")

    def entree_sortie(sp, sortie=True):
        sp.add_argument("fichier", help="PDF source")
        if sortie:
            sp.add_argument("sortie", help="PDF de sortie")
        sp.add_argument("--mot-de-passe", help="mot de passe si le PDF est protégé")

    sp = sub.add_parser("info", help="afficher les informations du PDF")
    entree_sortie(sp, sortie=False)
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("texte", help="extraire le texte")
    entree_sortie(sp, sortie=False)
    sp.add_argument("--pages", help="pages à lire (défaut : toutes)")
    sp.add_argument("-o", "--sortie", help="enregistrer le texte dans un fichier .txt")
    sp.set_defaults(func=cmd_texte)

    sp = sub.add_parser("fusionner", help="fusionner plusieurs PDF")
    sp.add_argument("sortie", help="PDF de sortie")
    sp.add_argument("fichiers", nargs="+", help="PDF à fusionner, dans l'ordre")
    sp.set_defaults(func=cmd_fusionner)

    sp = sub.add_parser("extraire", help="garder seulement certaines pages")
    entree_sortie(sp)
    sp.add_argument("--pages", required=True)
    sp.set_defaults(func=cmd_extraire)

    sp = sub.add_parser("supprimer", help="supprimer des pages")
    entree_sortie(sp)
    sp.add_argument("--pages", required=True)
    sp.set_defaults(func=cmd_supprimer)

    sp = sub.add_parser("pivoter", help="faire pivoter des pages")
    entree_sortie(sp)
    sp.add_argument("--angle", type=int, default=90, help="90, 180, 270... (défaut : 90)")
    sp.add_argument("--pages", help="défaut : toutes")
    sp.set_defaults(func=cmd_pivoter)

    sp = sub.add_parser("ajouter-texte", help="écrire du texte sur des pages")
    entree_sortie(sp)
    sp.add_argument("--texte", required=True, help="texte (\\n pour un retour à la ligne)")
    sp.add_argument("--x", type=float, default=72, help="position horizontale en points (défaut : 72)")
    sp.add_argument("--y", type=float, default=72, help="position verticale depuis le bas (défaut : 72)")
    sp.add_argument("--taille", type=float, default=12, help="taille de police (défaut : 12)")
    sp.add_argument("--couleur", type=couleur, default=(0, 0, 0), help="#RRGGBB (défaut : noir)")
    sp.add_argument("--pages", help="défaut : toutes")
    sp.set_defaults(func=cmd_ajouter_texte)

    sp = sub.add_parser("filigrane", help="ajouter un filigrane diagonal")
    entree_sortie(sp)
    sp.add_argument("--texte", required=True)
    sp.add_argument("--taille", type=float, default=60)
    sp.add_argument("--opacite", type=float, default=0.3, help="entre 0 et 1 (défaut : 0.3)")
    sp.add_argument("--pages", help="défaut : toutes")
    sp.set_defaults(func=cmd_filigrane)

    sp = sub.add_parser("metadonnees", help="modifier titre / auteur / sujet")
    entree_sortie(sp)
    sp.add_argument("--titre")
    sp.add_argument("--auteur")
    sp.add_argument("--sujet")
    sp.set_defaults(func=cmd_metadonnees)

    sp = sub.add_parser("polices", help="identifier les polices d'écriture")
    entree_sortie(sp, sortie=False)
    sp.add_argument("--pages", help="défaut : toutes")
    sp.add_argument("--detail", action="store_true",
                    help="afficher la police, la taille et la couleur de chaque morceau de texte")
    sp.add_argument("--chercher", help="afficher seulement la police du texte contenant ce mot")
    sp.set_defaults(func=cmd_polices)

    sp = sub.add_parser("remplacer", help="remplacer un texte existant par un autre")
    entree_sortie(sp)
    sp.add_argument("--ancien", required=True, help="texte à remplacer")
    sp.add_argument("--nouveau", required=True, help="nouveau texte")
    sp.add_argument("--pages", help="défaut : toutes")
    sp.add_argument("--taille", type=float, help="forcer la taille (défaut : celle d'origine)")
    sp.add_argument("--ajuster", action="store_true",
                    help="réduire la taille si le nouveau texte est plus long que l'ancien")
    sp.add_argument("--hors-ligne", action="store_true",
                    help="ne pas télécharger les polices manquantes depuis Google Fonts")
    sp.add_argument("--sans-decaler", action="store_true",
                    help="ne pas décaler la suite de la ligne quand la longueur change")
    sp.add_argument("--fichier-police", help="fichier .ttf/.otf à utiliser pour le nouveau texte")
    sp.add_argument("--ignorer-casse", action="store_true", help="ne pas distinguer majuscules/minuscules")
    sp.set_defaults(func=cmd_remplacer)

    sp = sub.add_parser("chiffrer",help="protéger par mot de passe (AES-256)")
    sp.add_argument("fichier")
    sp.add_argument("sortie")
    sp.add_argument("--mot-de-passe", required=True)
    sp.set_defaults(func=cmd_chiffrer)

    sp = sub.add_parser("dechiffrer", help="retirer le mot de passe")
    sp.add_argument("fichier")
    sp.add_argument("sortie")
    sp.add_argument("--mot-de-passe", required=True)
    sp.set_defaults(func=cmd_dechiffrer)

    return p


def main(argv=None):
    args = construire_parser().parse_args(argv)
    try:
        args.func(args)
    except FileNotFoundError as e:
        print(f"Erreur : fichier introuvable : {e.filename}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
