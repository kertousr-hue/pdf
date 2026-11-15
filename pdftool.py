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

    sp = sub.add_parser("chiffrer", help="protéger par mot de passe (AES-256)")
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
    except (ValueError, OSError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
