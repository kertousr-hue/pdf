#!/usr/bin/env python3
"""PDF Éditeur — version application web.

Lancement :
    python app_web.py              -> ouvre l'éditeur dans le navigateur (cet ordinateur seulement)
    python app_web.py --reseau     -> accessible depuis un téléphone ou une tablette sur le même Wi-Fi
                                      (protégé par un code d'accès affiché au démarrage)

Le serveur garde les documents ouverts en mémoire et applique les modifications avec le même
moteur que l'application de bureau (pdftool, polices, scan, conversion, scanner).
"""

import argparse
import io
import os
import secrets
import socket
import sys
import tempfile
import threading
import time
import uuid

import pymupdf
from flask import Flask, abort, jsonify, make_response, request, send_file, send_from_directory

import conversion
import pdftool
import polices
import scan
import scanner

ICI = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ICI, "web")
POLICES_STANDARD = ["Helvetica", "Times", "Courier"]
PWA = sys.platform == "emscripten"  # moteur exécuté dans le navigateur (application installable)
MAX_HISTORIQUE_OCTETS = 300 * 1024 * 1024
DUREE_SESSION = 4 * 3600
TAILLE_MAX_ENVOI = 200 * 1024 * 1024

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = TAILLE_MAX_ENVOI
VERROU = threading.RLock()  # PyMuPDF n'est pas prévu pour plusieurs fils en même temps
SESSIONS = {}
CODE_ACCES = None  # défini avec --reseau
LIEN_RESEAU = None  # adresse à ouvrir sur le téléphone (avec le code)


# --------------------------------------------------------------------------- #
# Sessions (documents ouverts)
# --------------------------------------------------------------------------- #

class Session:
    def __init__(self, doc, nom):
        self.doc, self.nom = doc, nom
        self.historique, self.retablir = [], []
        self.version = 0
        self.vu = time.time()

    def avant(self):
        self.historique.append(self.doc.tobytes())
        self.retablir.clear()
        while len(self.historique) > 1 and sum(map(len, self.historique)) > MAX_HISTORIQUE_OCTETS:
            self.historique.pop(0)

    def apres(self):
        self.version += 1

    def recharger(self, donnees):
        self.doc = pymupdf.open(stream=donnees, filetype="pdf")
        self.version += 1


def _session(ident):
    s = SESSIONS.get(ident)
    if not s:
        abort(404, "Document introuvable (fermé ou expiré). Rouvrez le fichier.")
    s.vu = time.time()
    return s


def _nettoyer():
    while True:
        time.sleep(600)
        with VERROU:
            for k in [k for k, s in SESSIONS.items() if time.time() - s.vu > DUREE_SESSION]:
                del SESSIONS[k]


def _nouvelle_session(doc, nom):
    ident = uuid.uuid4().hex
    SESSIONS[ident] = Session(doc, nom)
    return ident


def _infos_doc(ident):
    s = SESSIONS[ident]
    pages = [{"l": p.rect.width, "h": p.rect.height} for p in s.doc]
    return {"id": ident, "nom": s.nom, "pages": pages, "version": s.version,
            "annuler": bool(s.historique), "retablir": bool(s.retablir),
            "scannees": scan.pages_a_reconnaitre(s.doc),
            "formulaire": any(p.first_widget for p in s.doc)}


# --------------------------------------------------------------------------- #
# Sécurité : accès local, ou code d'accès en mode réseau
# --------------------------------------------------------------------------- #

def _est_local():
    return request.remote_addr in ("127.0.0.1", "::1")


@app.before_request
def _controle_acces():
    if CODE_ACCES is None or _est_local():
        return None
    code = request.args.get("code") or request.cookies.get("code_pdf")
    if not code or not secrets.compare_digest(code, CODE_ACCES):
        return make_response("Code d'accès manquant ou incorrect. Utilisez le lien affiché par le serveur.", 403)
    return None


@app.after_request
def _cookie_et_entetes(r):
    if CODE_ACCES and request.args.get("code") == CODE_ACCES:
        r.set_cookie("code_pdf", CODE_ACCES, httponly=True, samesite="Strict", max_age=30 * 24 * 3600)
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "no-referrer"
    return r


@app.errorhandler(Exception)
def _erreur(e):
    code = getattr(e, "code", 500)
    message = getattr(e, "description", None) or str(e)
    if code == 500:
        app.logger.exception(e)
    return jsonify({"erreur": message}), code if isinstance(code, int) else 500


# --------------------------------------------------------------------------- #
# Conversions de coordonnées (le navigateur voit la page telle qu'affichée)
# --------------------------------------------------------------------------- #

def _vers_ecran(page, rect):
    r = pymupdf.Rect(rect) * page.rotation_matrix
    r.normalize()
    return [round(v, 2) for v in r]


def _vers_page(page, rect):
    r = pymupdf.Rect(rect) * page.derotation_matrix
    r.normalize()
    return r


def _point_page(page, x, y):
    return pymupdf.Point(x, y) * page.derotation_matrix


def _hex(h):
    h = (h or "#000000").lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _style(d):
    """Mise en forme envoyée par le navigateur -> style pour pdftool."""
    if not d:
        return None
    style = {}
    if d.get("taille"):
        style["taille"] = float(d["taille"])
    if d.get("couleur"):
        style["couleur"] = _hex(d["couleur"])
    if d.get("police"):
        famille, gras, ita = d["police"], bool(d.get("gras")), bool(d.get("italique"))
        variante = (1 if gras else 0) + (2 if ita else 0)
        if famille in POLICES_STANDARD:
            style["base14"] = pdftool.BASE14[famille][variante]
        else:
            entree = polices.INDEX.variante(famille, 700 if gras else 400, ita)
            if entree:
                style["entree"] = entree
            else:
                style["base14"] = pdftool.BASE14[pdftool._famille_base14(famille)][variante]
    return style or None


def _famille_affichee(nom_pdf, gras, ita):
    nom = polices.sans_prefixe(nom_pdf).split("-")[0].split(",")[0]
    for std in POLICES_STANDARD:
        if nom.lower() == std.lower():
            return std
    entree, exacte = polices.INDEX.chercher(nom_pdf, gras, ita) if polices.INDEX.pret.is_set() else (None, False)
    return entree["famille"] if entree and exacte else nom


# --------------------------------------------------------------------------- #
# Pages statiques
# --------------------------------------------------------------------------- #

@app.get("/")
def accueil():
    return send_from_directory(WEB, "index.html")


@app.get("/web/<path:nom>")
def fichiers_web(nom):
    return send_from_directory(WEB, nom)


@app.get("/api/config")
def config():
    return jsonify({"local": _est_local() and not PWA, "scanner": _est_local() and not PWA, "pwa": PWA,
                    "reseau": bool(LIEN_RESEAU) and _est_local(),
                    "langues": {"Français": "fra", "Anglais": "eng"} if PWA else scan.LANGUES, "polices_pretes": polices.INDEX.pret.is_set()})


@app.get("/api/polices")
def liste_polices():
    return jsonify(polices.INDEX.familles() + POLICES_STANDARD)


# --------------------------------------------------------------------------- #
# Ouvrir, télécharger, fermer
# --------------------------------------------------------------------------- #

@app.post("/api/ouvrir")
def ouvrir():
    fichiers = request.files.getlist("fichiers")
    if not fichiers:
        abort(400, "Aucun fichier reçu.")
    mdp = request.form.get("mot_de_passe")
    with tempfile.TemporaryDirectory() as tmp:
        chemins = []
        for f in fichiers:
            nom = os.path.basename(f.filename or "document.pdf")
            if not conversion.type_fichier(nom):
                abort(400, f"Type de fichier non pris en charge : {nom}")
            c = os.path.join(tmp, f"{len(chemins):03d}_{nom}")
            f.save(c)
            chemins.append(c)
        genres = {conversion.type_fichier(c) for c in chemins}
        nom = os.path.splitext(os.path.basename(fichiers[0].filename or "document"))[0]
        with VERROU:
            if genres == {"image"}:
                doc = scanner.pages_vers_pdf(chemins, mode="Couleur", redresser=True, largeur_papier=595)
                doc = pymupdf.open(stream=doc.tobytes(garbage=3, deflate=True), filetype="pdf")
            elif len(chemins) == 1 and "word" in genres:
                doc = pymupdf.open(stream=conversion.word_vers_pdf(chemins[0]), filetype="pdf")
            else:
                doc = pymupdf.open()
                for c in chemins:
                    g = conversion.type_fichier(c)
                    if g == "pdf":
                        autre = pymupdf.open(c)
                        if autre.needs_pass:
                            if not mdp:
                                return jsonify({"mot_de_passe_requis": True, "nom": os.path.basename(c)[4:]})
                            if not autre.authenticate(mdp):
                                return jsonify({"mot_de_passe_requis": True, "erreur": "Mot de passe incorrect."})
                            autre = pymupdf.open(stream=autre.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE),
                                                 filetype="pdf")
                    elif g == "word":
                        autre = pymupdf.open(stream=conversion.word_vers_pdf(c), filetype="pdf")
                    else:
                        autre = scanner.pages_vers_pdf([c], largeur_papier=595)
                    if len(chemins) == 1:
                        doc = pymupdf.open(stream=autre.tobytes(), filetype="pdf")
                    else:
                        doc.insert_pdf(autre)
            ident = _nouvelle_session(doc, nom)
            return jsonify(_infos_doc(ident))


@app.get("/api/doc/<ident>")
def infos(ident):
    with VERROU:
        _session(ident)
        return jsonify(_infos_doc(ident))


@app.route("/api/doc/<ident>/telecharger", methods=["GET", "POST"])
def telecharger(ident):
    with VERROU:
        s = _session(ident)
        # le mot de passe arrive dans le corps de la requête (jamais dans l'adresse, qui est journalisée)
        mdp = (request.get_json(silent=True) or {}).get("mdp") if request.method == "POST" else None
        options = {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "user_pw": mdp, "owner_pw": mdp} if mdp else {}
        donnees = s.doc.tobytes(garbage=3, deflate=True, **options)
    return send_file(io.BytesIO(donnees), mimetype="application/pdf", as_attachment=True,
                     download_name=(s.nom or "document") + (" (protégé)" if mdp else "") + ".pdf")


@app.get("/api/doc/<ident>/word")
def exporter_word(ident):
    with VERROU:
        s = _session(ident)
        donnees = s.doc.tobytes(garbage=3, deflate=True)
    with tempfile.TemporaryDirectory() as tmp:
        src, dest = os.path.join(tmp, "doc.pdf"), os.path.join(tmp, "doc.docx")
        with open(src, "wb") as f:
            f.write(donnees)
        with VERROU:
            conversion.pdf_vers_word(src, dest)
        with open(dest, "rb") as f:
            docx = f.read()
    return send_file(io.BytesIO(docx), as_attachment=True, download_name=(s.nom or "document") + ".docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/api/doc/<ident>/texte.txt")
def exporter_texte(ident):
    with VERROU:
        s = _session(ident)
        texte = "".join(f"===== Page {i + 1} =====\n{p.get_text()}\n" for i, p in enumerate(s.doc))
    return send_file(io.BytesIO(texte.encode("utf-8")), mimetype="text/plain; charset=utf-8",
                     as_attachment=True, download_name=(s.nom or "document") + ".txt")


@app.delete("/api/doc/<ident>")
def fermer(ident):
    with VERROU:
        SESSIONS.pop(ident, None)
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
# Affichage
# --------------------------------------------------------------------------- #

@app.get("/api/doc/<ident>/page/<int:n>.png")
def image_page(ident, n):
    echelle = max(0.05, min(6.0, float(request.args.get("e", 1.5))))
    with VERROU:
        s = _session(ident)
        if not 0 <= n < s.doc.page_count:
            abort(404)
        pix = s.doc[n].get_pixmap(matrix=pymupdf.Matrix(echelle, echelle), alpha=False, annots=True)
        donnees = pix.tobytes("png")
    r = make_response(donnees)
    r.headers["Content-Type"] = "image/png"
    r.headers["Cache-Control"] = "private, max-age=3600"  # l'URL change à chaque version
    return r


@app.get("/api/doc/<ident>/page/<int:n>/contenu")
def contenu_page(ident, n):
    """Textes modifiables, mots (sélection), champs de formulaire d'une page."""
    with VERROU:
        s = _session(ident)
        page = s.doc[n]
        spans = []
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                for sp in l["spans"]:
                    if not sp["text"].strip() or sp.get("alpha", 255) == 0:
                        continue
                    gras, ita = pdftool.style_span(sp)
                    spans.append({"texte": sp["text"], "bbox": _vers_ecran(page, sp["bbox"]), "police": sp["font"],
                                  "famille": _famille_affichee(sp["font"], gras, ita), "taille": round(sp["size"], 2),
                                  "couleur": pdftool.couleur_hex(sp["color"]), "gras": gras, "italique": ita,
                                  "scan": False})
        for l in scan.lignes_scannees(page):
            spans.append({"texte": l["text"], "bbox": _vers_ecran(page, l["bbox"]), "police": "Texte scanné",
                          "taille": round(l["size"], 2), "scan": True})
        mots = [[*_vers_ecran(page, m[:4]), m[4]] for m in page.get_text("words")]
        champs = []
        for w in page.widgets():
            champs.append({"xref": w.xref, "type": w.field_type_string, "nom": w.field_name,
                           "valeur": w.field_value, "bbox": _vers_ecran(page, w.rect),
                           "choix": [c[1] if isinstance(c, (list, tuple)) else c for c in (w.choice_values or [])],
                           "multiligne": bool(w.field_flags & pymupdf.PDF_TX_FIELD_IS_MULTILINE),
                           "taille": w.text_fontsize or 0})
        return jsonify({"spans": spans, "mots": mots, "champs": champs, "rotation": page.rotation,
                        "scannee": scan.est_scannee(page)})


@app.post("/api/doc/<ident>/analyse")
def analyse_scan(ident):
    """Police, taille et couleurs estimées d'une ligne de texte scanné."""
    d = request.get_json()
    with VERROU:
        page = _session(ident).doc[int(d["page"])]
        rect = _vers_page(page, d["bbox"])
        base = scan.ligne_de_base(page, rect) or rect.y1
        texte = page.get_text("text", clip=rect).strip() or d.get("texte", "")
        g = scan.deviner_police(page, rect, texte, base)
        fond, encre = scan.couleurs(page, rect)
    fam = g["entree"]["famille"] if g["entree"] else {"helv": "Helvetica", "hebo": "Helvetica", "tiro": "Times",
                                                      "tibo": "Times", "cour": "Courier", "cobo": "Courier"}.get(
        g["base14"], "Helvetica")
    hexa = lambda c: "#%02x%02x%02x" % tuple(round(v * 255) for v in c)
    return jsonify({"famille": fam, "libelle": g["libelle"], "taille": round(g["taille"], 1), "gras": g["gras"],
                    "couleur": hexa(encre), "fond": hexa(fond)})


# --------------------------------------------------------------------------- #
# Modifications
# --------------------------------------------------------------------------- #

def _modif(ident, action, pages_touchees=None):
    """Applique `action(session)` avec annulation possible ; renvoie l'état du document."""
    with VERROU:
        s = _session(ident)
        s.avant()
        try:
            resultat = action(s)
        except Exception:
            s.doc = pymupdf.open(stream=s.historique.pop(), filetype="pdf")
            raise
        if resultat is False:  # rien n'a changé
            s.historique.pop()
            resultat = None
        else:
            s.apres()
        infos = _infos_doc(ident)
        infos["resultat"] = resultat
        return jsonify(infos)


@app.post("/api/doc/<ident>/modifier_texte")
def modifier_texte(ident):
    d = request.get_json()

    def action(s):
        page = s.doc[int(d["page"])]
        style = _style(d.get("style"))  # texte scanné sans style : la police est identifiée sur l'image
        res = pdftool.modifier_texte(page, _vers_page(page, d["bbox"]), d["texte"], style=style,
                                     decaler=d.get("decaler", True))
        return res or False
    return _modif(ident, action)


@app.post("/api/doc/<ident>/ajouter_texte")
def ajouter_texte(ident):
    d = request.get_json()

    def action(s):
        page = s.doc[int(d["page"])]
        style = _style(d.get("style")) or {}
        taille = style.get("taille", 12)
        texte = d["texte"].replace("\r", "")
        if not texte.strip():
            return False
        # le navigateur envoie le coin haut-gauche ; la ligne de base est ~0,8 × taille plus bas
        p = _point_page(page, d["x"], d["y"] + taille * 0.8)
        pdftool.inserer_texte(page, p, texte, entree=style.get("entree"), base14=style.get("base14", "helv"),
                              taille=taille, couleur=style.get("couleur", (0, 0, 0)))
        return True
    return _modif(ident, action)


@app.post("/api/doc/<ident>/remplacer")
def remplacer(ident):
    d = request.get_json()

    def action(s):
        pages = [int(d["page"])] if d.get("page") is not None else None
        res = pdftool.remplacer_texte(s.doc, d["ancien"], d.get("nouveau", ""), pages,
                                      ignorer_casse=not d.get("casse", True), decaler=d.get("decaler", True))
        return res or False
    return _modif(ident, action)


@app.post("/api/doc/<ident>/rechercher")
def rechercher(ident):
    d = request.get_json()
    texte, casse = d.get("texte", ""), d.get("casse", True)
    resultats = []
    with VERROU:
        for i, page in enumerate(_session(ident).doc):
            for r in page.search_for(texte) if texte else []:
                if casse and page.get_text("text", clip=r).strip() != texte:
                    continue
                resultats.append({"page": i, "bbox": _vers_ecran(page, r)})
    return jsonify(resultats)


@app.post("/api/doc/<ident>/annuler")
def annuler(ident):
    with VERROU:
        s = _session(ident)
        if s.historique:
            s.retablir.append(s.doc.tobytes())
            s.recharger(s.historique.pop())
        return jsonify(_infos_doc(ident))


@app.post("/api/doc/<ident>/retablir")
def retablir(ident):
    with VERROU:
        s = _session(ident)
        if s.retablir:
            s.historique.append(s.doc.tobytes())
            s.recharger(s.retablir.pop())
        return jsonify(_infos_doc(ident))


@app.post("/api/doc/<ident>/pages")
def pages(ident):
    d = request.get_json()
    a, n = d["action"], int(d.get("page", 0))

    def action(s):
        doc = s.doc
        if a == "pivoter":
            p = doc[n]
            p.set_rotation((p.rotation + int(d.get("angle", 90))) % 360)
        elif a == "pivoter_tout":
            for p in doc:
                p.set_rotation((p.rotation + 90) % 360)
        elif a == "supprimer":
            if doc.page_count == 1:
                abort(400, "Impossible de supprimer la seule page du document.")
            doc.delete_page(n)
        elif a == "deplacer":
            vers = int(d["vers"])
            if vers == n or not 0 <= vers < doc.page_count:
                return False
            # move_page(a, b) place la page a avant la page b (-1 = à la fin)
            if vers > n:
                doc.move_page(n, vers + 1 if vers + 1 < doc.page_count else -1)
            else:
                doc.move_page(n, vers)
        elif a == "blanche":
            r = doc[n].rect
            doc.new_page(n + 1, width=r.width, height=r.height)
        return True
    return _modif(ident, action)


@app.post("/api/doc/<ident>/fusionner")
def fusionner(ident):
    fichiers = request.files.getlist("fichiers")
    apres = request.form.get("apres")

    def action(s):
        position = int(apres) + 1 if apres not in (None, "") else None
        with tempfile.TemporaryDirectory() as tmp:
            for i, f in enumerate(fichiers):
                c = os.path.join(tmp, f"{i}_{os.path.basename(f.filename or 'a.pdf')}")
                f.save(c)
                g = conversion.type_fichier(c)
                if g == "pdf":
                    autre = pymupdf.open(c)
                elif g == "word":
                    autre = pymupdf.open(stream=conversion.word_vers_pdf(c), filetype="pdf")
                elif g == "image":
                    autre = scanner.pages_vers_pdf([c], largeur_papier=595)
                else:
                    abort(400, f"Type de fichier non pris en charge : {f.filename}")
                if position is not None:
                    s.doc.insert_pdf(autre, start_at=position)
                    position += autre.page_count
                else:
                    s.doc.insert_pdf(autre)
        return True
    return _modif(ident, action)


@app.post("/api/doc/<ident>/image")
def image(ident):
    f = request.files.get("image")
    n, bbox = int(request.form["page"]), [float(v) for v in request.form["bbox"].split(",")]
    donnees = f.read()

    def action(s):
        page = s.doc[n]
        page.insert_image(_vers_page(page, bbox), stream=donnees, keep_proportion=True, rotate=page.rotation)
        return True
    return _modif(ident, action)


@app.post("/api/doc/<ident>/signature")
def signature(ident):
    d = request.get_json()

    def action(s):
        page = s.doc[int(d["page"])]
        x0, y0, x1, y1 = d["bbox"]
        l, h = x1 - x0, y1 - y0
        ratio = d.get("ratio", 3)
        if l / max(h, 1) > ratio:
            x0 += (l - h * ratio) / 2
            l = h * ratio
        else:
            y0 += (h - l / ratio) / 2
            h = l / ratio
        forme = page.new_shape()
        for trait in d["traits"]:
            forme.draw_polyline([_point_page(page, x0 + u * l, y0 + v * h) for u, v in trait])
        forme.finish(color=(0.04, 0.16, 0.42), width=max(0.8, h / 40), closePath=False, lineCap=1, lineJoin=1)
        forme.commit()
        return True
    return _modif(ident, action)


@app.post("/api/doc/<ident>/annotation")
def annotation(ident):
    d = request.get_json()

    def action(s):
        page = s.doc[int(d["page"])]
        if d["type"] == "surligner":
            a = page.add_highlight_annot([_vers_page(page, r) for r in d["rects"]])
        elif d["type"] == "note":
            a = page.add_text_annot(_point_page(page, d["x"], d["y"]), d["texte"], icon="Comment")
        elif d["type"] == "caviarder":
            page.add_redact_annot(_vers_page(page, d["bbox"]), fill=(1, 1, 1))
            page.apply_redactions()
            return True
        else:
            abort(400)
        a.update()
        return True
    return _modif(ident, action)


@app.post("/api/doc/<ident>/champ")
def champ(ident):
    d = request.get_json()

    def action(s):
        page = s.doc[int(d["page"])]
        for w in page.widgets():
            if w.xref == int(d["xref"]):
                t = w.field_type
                if t == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                    w.field_value = (w.on_state() or True) if d.get("valeur") else "Off"
                elif t == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                    w.field_value = w.on_state() or True
                else:
                    if (w.field_value or "") == d.get("valeur", ""):
                        return False
                    w.field_value = d.get("valeur", "")
                w.update()
                return True
        abort(404, "Champ introuvable.")
    return _modif(ident, action)


@app.post("/api/doc/<ident>/creer_champ")
def creer_champ(ident):
    d = request.get_json()

    def action(s):
        page = s.doc[int(d["page"])]
        w = pymupdf.Widget()
        w.rect = _vers_page(page, d["bbox"])
        w.field_name = d.get("nom") or f"champ{sum(len(list(p.widgets())) for p in s.doc) + 1}"
        types = {"texte": pymupdf.PDF_WIDGET_TYPE_TEXT, "multiligne": pymupdf.PDF_WIDGET_TYPE_TEXT,
                 "case": pymupdf.PDF_WIDGET_TYPE_CHECKBOX, "liste": pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
                 "signature": pymupdf.PDF_WIDGET_TYPE_SIGNATURE}
        w.field_type = types.get(d.get("type"), pymupdf.PDF_WIDGET_TYPE_TEXT)
        if d.get("type") == "multiligne":
            w.field_flags = pymupdf.PDF_TX_FIELD_IS_MULTILINE
        if w.field_type == pymupdf.PDF_WIDGET_TYPE_TEXT:
            w.text_fontsize = 0
        if w.field_type == pymupdf.PDF_WIDGET_TYPE_COMBOBOX:
            choix = [c.strip() for c in (d.get("choix") or "").split(";") if c.strip()] or ["Choix 1", "Choix 2"]
            w.choice_values, w.field_value = choix, choix[0]
        w.border_color, w.border_width = (0.6, 0.6, 0.6), 0.5
        page.add_widget(w)
        return True
    return _modif(ident, action)


@app.post("/api/doc/<ident>/outil")
def outil(ident):
    """Filigrane, numéros de page, propriétés, aplatir."""
    d = request.get_json()
    quoi = d["quoi"]

    def action(s):
        doc = s.doc
        if quoi == "filigrane":
            couleur = _hex(d.get("couleur", "#999999"))
            taille = float(d.get("taille", 60))
            for page in doc:
                rect = page.rect * page.derotation_matrix
                rect.normalize()
                centre = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
                l = pymupdf.get_text_length(d["texte"], fontname="hebo", fontsize=taille)
                page.insert_text(centre + (-l / 2, taille / 3), d["texte"], fontname="hebo", fontsize=taille,
                                 color=couleur, fill_opacity=max(0, min(1, float(d.get("opacite", 0.3)))),
                                 morph=(centre, pymupdf.Matrix(45 + page.rotation)))
        elif quoi == "numeroter":
            total = doc.page_count
            for i, page in enumerate(doc):
                texte = d.get("format", "{n} / {total}").replace("{n}", str(i + 1)).replace("{total}", str(total))
                t = float(d.get("taille", 10))
                l = pymupdf.get_text_length(texte, fontname="helv", fontsize=t)
                vue = page.rect
                p = pymupdf.Point(vue.width / 2 - l / 2, vue.height - 25)
                page.insert_text(p * page.derotation_matrix, texte, fontname="helv", fontsize=t,
                                 color=(0.2, 0.2, 0.2), rotate=page.rotation)
        elif quoi == "proprietes":
            m = doc.metadata or {}
            m.update({k: d.get(k, "") for k in ("title", "author", "subject", "keywords")})
            doc.set_metadata(m)
            s.nom = d.get("nom") or s.nom
        elif quoi == "aplatir":
            doc.bake()
        else:
            abort(400)
        return True
    return _modif(ident, action)


@app.get("/api/doc/<ident>/proprietes")
def proprietes(ident):
    with VERROU:
        s = _session(ident)
        return jsonify({**(s.doc.metadata or {}), "nom": s.nom})


@app.get("/api/doc/<ident>/polices")
def polices_document(ident):
    with VERROU:
        etats = polices.etat_polices_document(_session(ident).doc)
    return jsonify([{"nom": e[0], "integree": e[1], "partielle": e[2], "etat": e[3], "detail": e[4]} for e in etats])


@app.post("/api/doc/<ident>/installer_polices")
def installer_polices(ident):
    with VERROU:
        s = _session(ident)
        etats = polices.etat_polices_document(s.doc)
        extraites = {}
        for nom, integree, partielle, etat, _d, xref, ext in etats:
            if etat in ("manquante", "equivalente") and integree and not partielle and ext in ("ttf", "otf"):
                extraites[nom] = (s.doc.extract_font(xref)[3], ext)
    ok, ko = [], []
    for nom, _i, _p, etat, *_r in etats:
        if etat not in ("manquante", "equivalente"):
            continue
        if nom in extraites:
            polices.ajouter_octets(f"{nom}.{extraites[nom][1]}", extraites[nom][0])
            ok.append(nom)
        elif polices.INDEX.telecharger_google(nom, delai=15):
            ok.append(nom)
        else:
            ko.append(nom)
    return jsonify({"installees": ok, "introuvables": ko})


# --------------------------------------------------------------------------- #
# OCR et numérisation
# --------------------------------------------------------------------------- #

@app.post("/api/doc/<ident>/ocr")
def ocr(ident):
    d = request.get_json() or {}
    langues = [l for l in d.get("langues", ["fra", "eng"]) if l in scan.LANGUES.values()] or ["fra", "eng"]
    scan.telecharger_langues(langues)  # une seule fois (fichiers gardés ensuite)

    def action(s):
        pages_ = [i for i, p in enumerate(s.doc) if not scan.a_couche_texte_invisible(p)] if d.get("toutes") \
            else scan.pages_a_reconnaitre(s.doc)
        if not pages_:
            return False
        return {"mots": sum(scan.reconnaitre_page(s.doc[i], langues) for i in pages_), "pages": len(pages_)}
    return _modif(ident, action)


@app.get("/api/reseau")
def reseau():
    """Lien et QR code pour ouvrir l'éditeur sur le téléphone (seulement depuis cet ordinateur)."""
    if not _est_local() or not LIEN_RESEAU:
        abort(404)
    svg = None
    try:
        import qrcode
        import qrcode.image.svg
        tampon = io.BytesIO()
        qrcode.make(LIEN_RESEAU, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2).save(tampon)
        svg = tampon.getvalue().decode("utf-8")
    except Exception:
        pass
    return jsonify({"lien": LIEN_RESEAU, "qr": svg})


@app.post("/api/arreter")
def arreter():
    """Arrête le serveur (seulement depuis l'ordinateur où il tourne)."""
    if not _est_local():
        abort(403, "Le serveur ne peut être arrêté que depuis l'ordinateur où il tourne.")
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return jsonify({"ok": True})


@app.post("/api/doc/<ident>/ocr_mots")
def ocr_mots(ident):
    """Mots reconnus dans le navigateur (Tesseract.js), posés de façon invisible sur la page.
    Corps : {"pages": [{"page": n, "mots": [{"texte", "bbox": [x0, y0, x1, y1], "base": y, "taille": t}]}]}
    en points, dans le sens d'affichage de la page."""
    d = request.get_json()

    def action(s):
        total, pages_ = 0, 0
        for entree in d.get("pages", []):
            page = s.doc[int(entree["page"])]
            mots = []
            for m in entree.get("mots", []):
                r = _vers_page(page, m["bbox"])
                base = _point_page(page, m["bbox"][0], m["base"])
                y_base = base.y if page.rotation in (0, 180) else r.y1
                mots.append({"text": m["texte"], "bbox": tuple(r), "origin": (r.x0, y_base),
                             "size": float(m["taille"])})
            n = scan.inserer_mots(page, mots)
            total += n
            pages_ += 1 if n else 0
        return {"mots": total, "pages": pages_} if total else False
    return _modif(ident, action)


@app.get("/api/scanners")
def scanners():
    if not _est_local():
        abort(403, "La numérisation n'est possible que sur l'ordinateur où tourne le serveur.")
    return jsonify([{"id": i, "nom": n} for i, n in scanner.lister_scanners()])


@app.post("/api/numeriser")
def numeriser():
    if not _est_local():
        abort(403, "La numérisation n'est possible que sur l'ordinateur où tourne le serveur.")
    d = request.get_json()
    with tempfile.TemporaryDirectory() as tmp:
        images = scanner.numeriser(tmp, d.get("appareil"), int(d.get("dpi", 300)), d.get("mode", "Couleur"),
                                   bool(d.get("chargeur")), bool(d.get("fenetre")))
        if not images:
            abort(400, "Aucune page numérisée.")
        with VERROU:
            nouveau = scanner.pages_vers_pdf(images, int(d.get("dpi", 300)), d.get("mode", "Couleur"),
                                             redresser=d.get("redresser", True))
            if d.get("doc"):
                s = _session(d["doc"])
                s.avant()
                s.doc.insert_pdf(nouveau)
                s.apres()
                return jsonify(_infos_doc(d["doc"]))
            ident = _nouvelle_session(pymupdf.open(stream=nouveau.tobytes(garbage=3, deflate=True), filetype="pdf"),
                                      "Numérisation " + time.strftime("%Y-%m-%d %H-%M"))
            return jsonify(_infos_doc(ident))


# --------------------------------------------------------------------------- #

def _ip_locale():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as so:
            so.connect(("10.255.255.255", 1))
            return so.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _port_occupe(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as so:
        return so.connect_ex(("127.0.0.1", port)) == 0


def main():
    import webbrowser
    global CODE_ACCES, LIEN_RESEAU
    ap = argparse.ArgumentParser(description="PDF Éditeur — application web")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--reseau", action="store_true",
                    help="accessible depuis les autres appareils du réseau (téléphone…), avec un code d'accès")
    ap.add_argument("--sans-navigateur", action="store_true", help="ne pas ouvrir le navigateur")
    args = ap.parse_args()

    if _port_occupe(args.port):  # déjà ouvert : on montre simplement l'éditeur existant
        webbrowser.open(f"http://127.0.0.1:{args.port}/")
        return 0
    polices.INDEX.charger(en_arriere_plan=True)
    threading.Thread(target=_nettoyer, daemon=True).start()
    hote = "0.0.0.0" if args.reseau else "127.0.0.1"
    adresse = f"http://127.0.0.1:{args.port}/"
    print("PDF Éditeur (web) démarré.")
    print(f"  Sur cet ordinateur : {adresse}")
    if args.reseau:
        CODE_ACCES = secrets.token_urlsafe(8)
        LIEN_RESEAU = f"http://{_ip_locale()}:{args.port}/?code={CODE_ACCES}"
        print(f"  Depuis un téléphone ou une tablette (même Wi-Fi) : {LIEN_RESEAU}")
        print("  (le code protège l'accès : ne partagez ce lien qu'avec vos appareils)")
    print("Laissez cette fenêtre ouverte. Pour arrêter : Ctrl+C.")
    if not args.sans_navigateur:
        threading.Timer(1.0, lambda: webbrowser.open(adresse)).start()
    app.run(host=hote, port=args.port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    sys.exit(main())
