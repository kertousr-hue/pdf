"""Crée l'icône du programme (pdf_editeur.ico) : une feuille rouge « PDF » avec un crayon.

Le fichier .ico contient plusieurs tailles, chacune enregistrée en PNG (format accepté par
Windows depuis Vista).
"""

import os
import struct

import pymupdf

ICI = os.path.dirname(os.path.abspath(__file__))
TAILLES = [16, 24, 32, 48, 64, 128, 256]


def dessiner(taille):
    d = pymupdf.open()
    p = d.new_page(width=256, height=256)
    s = p.new_shape()
    # feuille avec coin replié
    s.draw_polyline([(46, 16), (170, 16), (214, 60), (214, 240), (46, 240), (46, 16)])
    s.finish(color=None, fill=(0.85, 0.16, 0.14), closePath=True)
    s.draw_polyline([(170, 16), (170, 60), (214, 60)])
    s.finish(color=None, fill=(0.98, 0.72, 0.70), closePath=True)
    # bandeau « PDF »
    s.draw_rect(pymupdf.Rect(46, 150, 214, 206))
    s.finish(color=None, fill=(0.65, 0.08, 0.07))
    s.commit()
    if taille >= 32:
        p.insert_text((62, 196), "PDF", fontname="hebo", fontsize=50, color=(1, 1, 1))
    else:
        p.insert_text((58, 200), "PDF", fontname="hebo", fontsize=58, color=(1, 1, 1))
    # crayon
    c = p.new_shape()
    c.draw_polyline([(150, 88), (226, 12), (246, 32), (170, 108), (142, 116), (150, 88)])
    c.finish(color=(1, 1, 1), fill=(0.10, 0.45, 0.91), width=6, closePath=True)
    c.commit()
    zoom = taille / 256
    return p.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True).tobytes("png")


def creer_ico(chemin):
    images = [dessiner(t) for t in TAILLES]
    entete = struct.pack("<HHH", 0, 1, len(images))
    position = 6 + 16 * len(images)
    repertoire, donnees = b"", b""
    for t, png in zip(TAILLES, images):
        cote = 0 if t >= 256 else t  # 0 signifie 256 dans le format ICO
        repertoire += struct.pack("<BBBBHHII", cote, cote, 0, 0, 1, 32, len(png), position)
        donnees += png
        position += len(png)
    with open(chemin, "wb") as f:
        f.write(entete + repertoire + donnees)
    with open(os.path.join(ICI, "pdf_editeur.png"), "wb") as f:
        f.write(images[-1])


if __name__ == "__main__":
    creer_ico(os.path.join(ICI, "pdf_editeur.ico"))
    print("Icône créée :", os.path.join(ICI, "pdf_editeur.ico"))
