"""Point d'entrée du programme installé (PDF Editeur.exe).

    PDF Editeur.exe [fichier.pdf]     éditeur de bureau
    PDF Editeur.exe --web             éditeur dans le navigateur
    PDF Editeur.exe --web --reseau    éditeur dans le navigateur, utilisable depuis le téléphone
    PDF Editeur.exe --verifier        vérifie que tout fonctionne (utilisé à la construction)
"""

import os
import sys

VERSION = "1.0.0"


def _sorties():
    """Un programme sans console n'a pas de sortie : on écrit dans un journal."""
    if sys.stdout is None or sys.stderr is None:
        import polices
        journal = open(os.path.join(polices.dossier_app(), "journal.txt"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or journal
        sys.stderr = sys.stderr or journal


def verifier():
    """Contrôle rapide de tous les modules (sans fenêtre). Code de sortie 0 si tout va bien."""
    import pymupdf

    import app_web  # noqa: F401  (Flask, interface web)
    import conversion  # noqa: F401
    import pdftool
    import polices
    import scan
    import scanner
    erreurs = []

    def etape(nom, fn):
        try:
            fn()
            print(f"OK      {nom}")
        except Exception as e:  # noqa: BLE001
            erreurs.append(nom)
            print(f"ÉCHEC   {nom} : {e!r}")

    def edition():
        d = pymupdf.open()
        p = d.new_page()
        p.insert_text((72, 100), "Bonjour Paul", fontname="helv", fontsize=12)
        assert pdftool.remplacer_texte(d, "Paul", "Marie")
        assert "Marie" in d[0].get_text()

    def ocr():
        d = pymupdf.open()
        p = d.new_page()
        p.insert_text((72, 100), "Reconnaissance de texte", fontname="helv", fontsize=20)
        image = pymupdf.open()
        q = image.new_page()
        q.insert_image(q.rect, pixmap=p.get_pixmap(dpi=200))
        assert scan.est_scannee(q)
        scan.reconnaitre_page(q, ["fra"])
        assert "texte" in q.get_text()

    def word():
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            d = pymupdf.open()
            d.new_page().insert_text((72, 100), "Export Word", fontname="helv")
            d.save(os.path.join(t, "a.pdf"))
            conversion.pdf_vers_word(os.path.join(t, "a.pdf"), os.path.join(t, "a.docx"))
            assert os.path.getsize(os.path.join(t, "a.docx")) > 1000

    def interface():
        import tkinter
        import tkinterdnd2
        assert tkinterdnd2.TkinterDnD
        tkinter.Tcl()

    def interface_web():
        client = app_web.app.test_client()
        assert client.get("/").status_code == 200
        assert client.get("/web/app.js").status_code == 200

    etape("édition du texte", edition)
    etape("polices installées", lambda: polices.INDEX.charger() or len(polices.INDEX.entrees) > 0 or None)
    etape("reconnaissance de texte (OCR)", ocr)
    etape("export Word", word)
    etape("redressement des scans", lambda: scanner.angle_inclinaison(pymupdf.open().new_page().get_pixmap()))
    etape("interface de bureau", interface)
    etape("interface web", interface_web)
    print("Tout fonctionne." if not erreurs else f"{len(erreurs)} problème(s).")
    return 1 if erreurs else 0


def main():
    args = sys.argv[1:]
    if "--version" in args:
        print(VERSION)
        return 0
    if "--verifier" in args:
        sortie = args[args.index("--verifier") + 1] if len(args) > args.index("--verifier") + 1 else None
        if sortie:  # le programme sans console écrit son rapport dans un fichier
            sys.stdout = sys.stderr = open(sortie, "w", encoding="utf-8", buffering=1)
        return verifier()
    _sorties()
    if "--web" in args:
        args.remove("--web")
        sys.argv = [sys.argv[0]] + args
        import app_web
        return app_web.main()
    sys.argv = [sys.argv[0]] + [a for a in args if not a.startswith("-")]
    import pdf_editeur
    return pdf_editeur.main()


if __name__ == "__main__":
    sys.exit(main() or 0)
