#!/usr/bin/env python3
"""PDF Éditeur — lire, modifier et enregistrer des PDF (interface optimisée pour Windows).

Lancement :  python pdf_editeur.py [fichier.pdf]
             (ou double-clic sur « PDF Editeur.pyw » sous Windows)
"""

import json
import os
import sys
import tempfile
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

import pymupdf

import pdftool
import polices

WINDOWS = sys.platform == "win32"
CTRL = "Command" if sys.platform == "darwin" else "Control"

# Glisser-déposer (facultatif : pip install tkinterdnd2)
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    Base = TkinterDnD.Tk
except Exception:  # pragma: no cover
    DND_FILES, Base = None, tk.Tk

# Netteté sur les écrans haute résolution de Windows
if WINDOWS:
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PDFEditeur.App")
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

ZOOMS = ["50 %", "75 %", "100 %", "125 %", "150 %", "200 %", "300 %", "400 %", "Largeur", "Page entière"]
POLICES_STANDARD = ["Helvetica", "Times", "Courier"]
MAX_HISTORIQUE_OCTETS = 400 * 1024 * 1024
BLEU = "#1a73e8"


FOND_RUBAN = "#f9f9f9"


def _police_icones():
    """Police d'icônes de Windows 10/11 (Segoe Fluent Icons ou Segoe MDL2 Assets)."""
    if not WINDOWS:
        return None
    try:
        r = tk.Tk()
        r.withdraw()
        familles = set(tkfont.families(r))
        r.destroy()
    except Exception:
        return None
    for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if f in familles:
            return f
    return None


POLICE_ICONES = _police_icones()
# (glyphe Segoe MDL2/Fluent, symbole de secours)
_ICONES = {
    "ouvrir": ("\ue838", "📂"), "enregistrer": ("\ue74e", "💾"), "imprimer": ("\ue749", "⎙"),
    "annuler": ("\ue7a7", "↶"), "refaire": ("\ue7a6", "↷"), "selection": ("\ue8b3", "↖"),
    "edition": ("\ue70f", "✎"), "texte": ("\ue8d2", "T"), "image": ("\ue91b", "▣"),
    "signature": ("\uee56", "✍"), "surligner": ("\ue7e6", "▌"), "commentaire": ("\ue90a", "✉"),
    "rechercher": ("\ue721", "⌕"), "pivoter": ("\ue7ad", "⟳"), "page": ("\ue7c3", "✚"),
    "supprimer": ("\ue74d", "✖"),
}
ICONES = {k: (v[0] if POLICE_ICONES else v[1]) for k, v in _ICONES.items()}


class BoutonRuban(tk.Frame):
    """Bouton plat façon Windows 11 : icône au-dessus, texte en dessous."""

    def __init__(self, parent, icone, texte, commande, police_icone, police_texte):
        super().__init__(parent, bg=FOND_RUBAN, padx=7, pady=2, highlightthickness=1,
                         highlightbackground=FOND_RUBAN, cursor="hand2")
        self.commande, self.actif, self.choisi = commande, True, False
        self.l_icone = tk.Label(self, text=icone, font=police_icone, bg=FOND_RUBAN, fg="#1f1f1f")
        self.l_icone.pack()
        self.l_texte = tk.Label(self, text=texte, font=police_texte, bg=FOND_RUBAN, fg="#1f1f1f")
        self.l_texte.pack()
        for w in (self, self.l_icone, self.l_texte):
            w.bind("<Enter>", lambda e: self._fond("#e5f1fb", "#cce4f7"))
            w.bind("<Leave>", lambda e: self._etat())
            w.bind("<ButtonRelease-1>", self._clic)

    def _fond(self, fond, bord):
        if not self.actif:
            return
        for w in (self, self.l_icone, self.l_texte):
            w.configure(bg=fond)
        self.configure(highlightbackground=bord)

    def _etat(self):
        if self.choisi:
            self._fond("#cce4f7", "#99c9ef")
        else:
            self._fond(FOND_RUBAN, FOND_RUBAN)

    def _clic(self, e):
        if self.actif and 0 <= e.x_root - self.winfo_rootx() <= self.winfo_width() \
                and 0 <= e.y_root - self.winfo_rooty() <= self.winfo_height():
            self.commande()

    def selectionner(self, oui):
        self.choisi = oui
        self._etat()

    def activer(self, oui):
        self.actif = True
        self._etat()
        self.actif = oui
        couleur = "#1f1f1f" if oui else "#a0a0a0"
        self.l_icone.configure(fg=couleur)
        self.l_texte.configure(fg=couleur)
        self.configure(cursor="hand2" if oui else "arrow")


# --------------------------------------------------------------------------- #
# Boîtes de dialogue
# --------------------------------------------------------------------------- #

class Formulaire(simpledialog.Dialog):
    """champs : (clé, libellé, défaut, type) ; type : texte, nombre, motdepasse, couleur, ("choix", [...])"""

    def __init__(self, parent, titre, champs, aide=None):
        self.champs, self.aide, self.resultat, self.vars = champs, aide, None, {}
        super().__init__(parent, titre)

    def body(self, cadre):
        cadre.configure(padding=6) if isinstance(cadre, ttk.Frame) else None
        ligne, premier = 0, None
        if self.aide:
            ttk.Label(cadre, text=self.aide, wraplength=360, foreground="#555").grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
            ligne = 1
        for cle, libelle, defaut, typ in self.champs:
            ttk.Label(cadre, text=libelle).grid(row=ligne, column=0, sticky="w", padx=(0, 10), pady=4)
            var = tk.StringVar(value="" if defaut is None else str(defaut))
            self.vars[cle] = (var, typ)
            if isinstance(typ, tuple):
                w = ttk.Combobox(cadre, textvariable=var, values=typ[1], state="readonly", width=30)
            elif typ == "couleur":
                w = ttk.Frame(cadre)
                apercu = tk.Label(w, width=3, bg=var.get(), relief="solid", bd=1)
                apercu.pack(side="left")

                def choisir(v=var, a=apercu):
                    c = colorchooser.askcolor(v.get(), parent=self)[1]
                    if c:
                        v.set(c)
                        a.config(bg=c)
                ttk.Button(w, text="Choisir…", command=choisir).pack(side="left", padx=6)
            else:
                w = ttk.Entry(cadre, textvariable=var, width=34, show="•" if typ == "motdepasse" else "")
            w.grid(row=ligne, column=1, sticky="we", pady=4)
            premier = premier or w
            ligne += 1
        return premier

    def validate(self):
        res = {}
        for cle, (var, typ) in self.vars.items():
            v = var.get()
            if typ == "nombre":
                try:
                    v = float(v.replace(",", "."))
                except ValueError:
                    messagebox.showerror("Valeur invalide", f"« {v} » n'est pas un nombre.", parent=self)
                    return False
            res[cle] = v
        self.resultat = res
        return True


class PadSignature(simpledialog.Dialog):
    """Dessiner une signature à la souris. self.traits = [[(x, y), ...], ...] entre 0 et 1."""

    L, H = 520, 200

    def body(self, cadre):
        ttk.Label(cadre, text="Signez avec la souris dans le cadre :").pack(anchor="w")
        self.c = tk.Canvas(cadre, width=self.L, height=self.H, bg="white", highlightthickness=1,
                           highlightbackground="#999", cursor="pencil")
        self.c.pack(pady=6)
        self.c.create_line(20, self.H - 40, self.L - 20, self.H - 40, fill="#ddd", dash=(4, 3))
        ttk.Button(cadre, text="Effacer", command=self._effacer).pack(anchor="e")
        self.traits, self.trait = [], None
        self.c.bind("<ButtonPress-1>", lambda e: self._debut(e))
        self.c.bind("<B1-Motion>", lambda e: self._suite(e))
        self.resultat = None
        return self.c

    def _effacer(self):
        self.c.delete("trait")
        self.traits = []

    def _debut(self, e):
        self.trait = [(e.x, e.y)]
        self.traits.append(self.trait)

    def _suite(self, e):
        x0, y0 = self.trait[-1]
        self.c.create_line(x0, y0, e.x, e.y, width=2.5, fill="#0b2a6b", capstyle="round", tags="trait")
        self.trait.append((e.x, e.y))

    def validate(self):
        traits = [t for t in self.traits if len(t) > 1]
        if not traits:
            messagebox.showinfo("Signature", "Dessinez d'abord votre signature.", parent=self)
            return False
        xs = [x for t in traits for x, _ in t]
        ys = [y for t in traits for _, y in t]
        x0, y0, l, h = min(xs), min(ys), max(max(xs) - min(xs), 1), max(max(ys) - min(ys), 1)
        self.resultat = {"traits": [[((x - x0) / l, (y - y0) / h) for x, y in t] for t in traits],
                         "ratio": l / h}
        return True


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #

class Editeur(Base):
    def __init__(self, fichier=None):
        super().__init__()
        self.title("PDF Éditeur")
        self.dpi = self.winfo_fpixels("1i")
        self.echelle_ui = self.dpi / 96
        largeur, hauteur = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{int(largeur * 0.8)}x{int(hauteur * 0.82)}+{int(largeur * 0.1)}+{int(hauteur * 0.05)}")
        self.minsize(int(900 * self.echelle_ui), int(560 * self.echelle_ui))

        self.config_chemin = os.path.join(polices.dossier_app(), "config.json")
        self.reglages = {"recents": [], "telecharger": True, "installer_windows": True, "zoom": "Largeur"}
        try:
            with open(self.config_chemin, encoding="utf-8") as f:
                self.reglages.update(json.load(f))
        except Exception:
            pass
        pdftool.TELECHARGER_POLICES = self.reglages["telecharger"]

        # État du document
        self.doc = None
        self.chemin = None
        self.modifie = False
        self.page_idx = 0
        self.zoom = 1.0
        self.mode_zoom = self.reglages.get("zoom", "Largeur")
        self.historique, self.retablir = [], []
        self.image = None
        self.vignettes = []
        self.vignettes_a_rendre = []
        self.mots, self.spans = [], []
        self.selection = []
        self.resultats_recherche = []
        self.index_resultat = -1
        self.glisser = None
        self.edition = None
        self.image_a_placer = None
        self.signature = None
        self.outil = tk.StringVar(value="selection")

        self._style()
        self._icone()
        self._menus()
        self._ruban()
        self._barre_format()
        self._corps()
        self._accueil()
        self._raccourcis()
        self.protocol("WM_DELETE_WINDOW", self.quitter)
        if DND_FILES:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._deposer)

        self.statut("Chargement de la liste des polices…")
        polices.INDEX.charger(en_arriere_plan=True, rappel=lambda i: self.after(0, self._polices_pretes))
        self._maj_etat()
        if fichier:
            self.after(100, lambda: self.ouvrir(fichier))

    # ================================================================ UI ==

    def _style(self):
        style = ttk.Style(self)
        if WINDOWS and "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        famille = "Segoe UI" if WINDOWS else "TkDefaultFont"
        defaut = tkfont.nametofont("TkDefaultFont")
        if WINDOWS:
            defaut.configure(family="Segoe UI", size=9)
            tkfont.nametofont("TkTextFont").configure(family="Segoe UI", size=9)
            tkfont.nametofont("TkMenuFont").configure(family="Segoe UI", size=9)
        taille = defaut.cget("size")
        self.police_icone = (POLICE_ICONES, 16) if POLICE_ICONES else (famille, 15)
        self.police_ruban = (famille, taille)
        style.configure("Outil.Toolbutton", font=(famille, taille), padding=(8, 3), anchor="center", justify="center")
        style.configure("Outil.TButton", font=(famille, taille), padding=(8, 3), justify="center")
        style.configure("Accent.TButton", font=(famille, taille, "bold"))
        style.configure("Grand.TButton", font=(famille, 12), padding=(22, 10))
        style.configure("Lien.TLabel", foreground=BLEU, font=(famille, 10, "underline"))
        style.configure("Accueil.TFrame", background="#f3f3f3")
        style.configure("Accueil.TLabel", background="#f3f3f3")
        style.configure("Titre.TLabel", background="#f3f3f3", font=(famille, 20, "bold"))
        style.configure("Statut.TLabel", padding=(8, 3))
        style.configure("Alerte.TLabel", padding=(8, 3), foreground="#b25e00", font=(famille, taille, "underline"))

    def _icone(self):
        """Petite icône (document rouge « PDF ») dessinée avec PyMuPDF."""
        try:
            d = pymupdf.open()
            p = d.new_page(width=64, height=64)
            p.draw_rect(pymupdf.Rect(10, 2, 54, 62), color=(0.75, 0.1, 0.1), fill=(0.85, 0.15, 0.15), width=0)
            p.insert_text((14, 40), "PDF", fontname="hebo", fontsize=16, color=(1, 1, 1))
            self._ico = tk.PhotoImage(data=p.get_pixmap(alpha=True).tobytes("png"))
            self.iconphoto(True, self._ico)
        except Exception:
            pass

    def _menus(self):
        barre = tk.Menu(self)
        m = tk.Menu(barre, tearoff=False)
        m.add_command(label="Ouvrir…", accelerator="Ctrl+O", command=self.demander_ouvrir)
        self.menu_recents = tk.Menu(m, tearoff=False, postcommand=self._remplir_recents)
        m.add_cascade(label="Fichiers récents", menu=self.menu_recents)
        m.add_separator()
        m.add_command(label="Enregistrer", accelerator="Ctrl+S", command=self.enregistrer)
        m.add_command(label="Enregistrer sous…", accelerator="Ctrl+Maj+S", command=self.enregistrer_sous)
        m.add_command(label="Enregistrer avec mot de passe…", command=self.chiffrer)
        m.add_separator()
        m.add_command(label="Ajouter un PDF à la fin (fusionner)…", command=self.fusionner)
        m.add_command(label="Exporter des pages en PDF…", command=self.exporter_pages)
        m.add_command(label="Exporter en images (PNG)…", command=self.exporter_images)
        m.add_command(label="Exporter le texte…", command=self.exporter_texte)
        m.add_separator()
        m.add_command(label="Imprimer…", accelerator="Ctrl+P", command=self.imprimer)
        m.add_command(label="Propriétés…", command=self.metadonnees)
        m.add_separator()
        m.add_command(label="Fermer le document", accelerator="Ctrl+W", command=self.fermer)
        m.add_command(label="Quitter", command=self.quitter)
        barre.add_cascade(label="Fichier", menu=m)

        m = tk.Menu(barre, tearoff=False)
        m.add_command(label="Annuler", accelerator="Ctrl+Z", command=self.annuler)
        m.add_command(label="Rétablir", accelerator="Ctrl+Y", command=self.refaire)
        m.add_separator()
        m.add_command(label="Modifier le texte", accelerator="Ctrl+E", command=lambda: self.outil.set("edition"))
        m.add_command(label="Ajouter du texte", accelerator="Ctrl+T", command=lambda: self.outil.set("texte"))
        m.add_command(label="Ajouter une image…", command=self.choisir_image)
        m.add_command(label="Signer…", command=self.choisir_signature)
        m.add_command(label="Surligner", command=lambda: self.outil.set("surligner"))
        m.add_command(label="Ajouter un commentaire", command=lambda: self.outil.set("commentaire"))
        m.add_command(label="Effacer une zone (caviarder)", command=lambda: self.outil.set("caviarder"))
        m.add_separator()
        m.add_command(label="Rechercher et remplacer", accelerator="Ctrl+F", command=self.afficher_recherche)
        m.add_command(label="Filigrane…", command=self.filigrane)
        m.add_command(label="Numéroter les pages…", command=self.numeroter)
        barre.add_cascade(label="Édition", menu=m)

        m = tk.Menu(barre, tearoff=False)
        m.add_command(label="Pivoter à droite", accelerator="Ctrl+R", command=lambda: self.pivoter(90))
        m.add_command(label="Pivoter à gauche", command=lambda: self.pivoter(-90))
        m.add_command(label="Pivoter toutes les pages", command=lambda: self.pivoter(90, toutes=True))
        m.add_separator()
        m.add_command(label="Insérer une page blanche", command=self.inserer_page_blanche)
        m.add_command(label="Insérer des pages d'un PDF…", command=self.inserer_pdf)
        m.add_command(label="Supprimer la page", command=self.supprimer_page)
        m.add_command(label="Monter la page", command=lambda: self.deplacer_page(self.page_idx, self.page_idx - 1))
        m.add_command(label="Descendre la page", command=lambda: self.deplacer_page(self.page_idx, self.page_idx + 1))
        barre.add_cascade(label="Pages", menu=m)

        m = tk.Menu(barre, tearoff=False)
        m.add_command(label="Polices du document…", command=self.fenetre_polices_document)
        m.add_command(label="Gérer les polices…", command=self.fenetre_gestion_polices)
        m.add_separator()
        m.add_command(label="Informations sur le document", command=self.informations)
        barre.add_cascade(label="Outils", menu=m)

        m = tk.Menu(barre, tearoff=False)
        m.add_command(label="Aide rapide", accelerator="F1", command=self.aide)
        barre.add_cascade(label="Aide", menu=m)
        self.config(menu=barre)

    def _ruban(self):
        r = tk.Frame(self, bg=FOND_RUBAN, padx=4, pady=3)
        r.pack(side="top", fill="x")
        tk.Frame(self, bg="#e0e0e0", height=1).pack(side="top", fill="x")
        self.ruban = r
        self.boutons_outils = {}

        def bouton(cle_icone, texte, cmd, valeur_outil=None):
            b = BoutonRuban(r, ICONES[cle_icone], texte, cmd, self.police_icone, self.police_ruban)
            b.pack(side="left", padx=1)
            if valeur_outil:
                self.boutons_outils[valeur_outil] = b
            return b

        def sep():
            tk.Frame(r, bg="#d0d0d0", width=1).pack(side="left", fill="y", padx=5, pady=4)

        bouton("ouvrir", "Ouvrir", self.demander_ouvrir)
        self.btn_enregistrer = bouton("enregistrer", "Enregistrer", self.enregistrer)
        bouton("imprimer", "Imprimer", self.imprimer)
        sep()
        self.btn_annuler = bouton("annuler", "Annuler", self.annuler)
        self.btn_refaire = bouton("refaire", "Rétablir", self.refaire)
        sep()
        for cle, texte, valeur in [("selection", "Sélection", "selection"), ("edition", "Modifier", "edition"),
                                   ("texte", "Texte", "texte")]:
            bouton(cle, texte, lambda v=valeur: self.outil.set(v), valeur)
        bouton("image", "Image", self.choisir_image, "image")
        bouton("signature", "Signer", self.choisir_signature, "signature")
        bouton("surligner", "Surligner", lambda: self.outil.set("surligner"), "surligner")
        bouton("commentaire", "Note", lambda: self.outil.set("commentaire"), "commentaire")
        sep()
        bouton("rechercher", "Rechercher", self.afficher_recherche)
        sep()
        bouton("pivoter", "Pivoter", lambda: self.pivoter(90))
        bouton("page", "Insérer page", self.inserer_page_blanche)
        bouton("supprimer", "Suppr. page", self.supprimer_page)
        self.outil.trace_add("write", lambda *_: self._changement_outil())
        self._marquer_outil()

    def _marquer_outil(self):
        for valeur, b in self.boutons_outils.items():
            b.selectionner(valeur == self.outil.get())

    def _barre_format(self):
        """Barre de mise en forme du texte (visible avec les outils de texte)."""
        b = ttk.Frame(self, padding=(8, 3))
        self.barre_format = b
        ttk.Label(b, text="Police :").pack(side="left")
        self.var_police = tk.StringVar(value="Arial" if WINDOWS else "Helvetica")
        self.combo_police = ttk.Combobox(b, textvariable=self.var_police, width=28, values=POLICES_STANDARD)
        self.combo_police.pack(side="left", padx=(4, 10))
        self.combo_police.bind("<KeyRelease>", self._filtrer_polices)
        self.combo_police.bind("<<ComboboxSelected>>", lambda e: self._format_change())
        ttk.Label(b, text="Taille :").pack(side="left")
        self.var_taille = tk.StringVar(value="12")
        s = ttk.Combobox(b, textvariable=self.var_taille, width=5,
                         values=[6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 72])
        s.pack(side="left", padx=(4, 10))
        s.bind("<<ComboboxSelected>>", lambda e: self._format_change())
        s.bind("<KeyRelease>", lambda e: self._format_change())
        self.var_gras, self.var_italique = tk.BooleanVar(), tk.BooleanVar()
        fam = "Segoe UI" if WINDOWS else "TkDefaultFont"
        for texte, var, police, marge in [("G", self.var_gras, (fam, 10, "bold"), 0),
                                          ("I", self.var_italique, (fam, 10, "italic"), 10)]:
            tk.Checkbutton(b, text=texte, variable=var, indicatoron=False, width=3, font=police,
                           relief="flat", overrelief="groove", offrelief="flat", selectcolor="#cce4f7",
                           command=self._format_change).pack(side="left", padx=(2, marge))
        ttk.Label(b, text="Couleur :").pack(side="left")
        self.couleur = "#000000"
        self.btn_couleur = tk.Button(b, width=3, bg=self.couleur, relief="solid", bd=1, command=self._choisir_couleur)
        self.btn_couleur.pack(side="left", padx=(4, 12))
        self.var_decaler = tk.BooleanVar(value=True)
        ttk.Checkbutton(b, text="Décaler la suite de la ligne", variable=self.var_decaler).pack(side="left")
        self.lbl_police_origine = ttk.Label(b, text="", foreground="#555")
        self.lbl_police_origine.pack(side="left", padx=12)

    def _corps(self):
        self.statut_barre = ttk.Frame(self, relief="groove")
        self.statut_barre.pack(side="bottom", fill="x")
        self.lbl_statut = ttk.Label(self.statut_barre, text="", style="Statut.TLabel", anchor="w")
        self.lbl_statut.pack(side="left", fill="x", expand=True)
        self.lbl_alerte_polices = ttk.Label(self.statut_barre, text="", style="Alerte.TLabel", cursor="hand2")
        self.lbl_alerte_polices.pack(side="left")
        self.lbl_alerte_polices.bind("<Button-1>", lambda e: self.fenetre_polices_document())
        ttk.Button(self.statut_barre, text="◀", width=3, command=lambda: self.aller_page(self.page_idx - 1)).pack(side="left")
        self.var_page = tk.StringVar()
        e = ttk.Entry(self.statut_barre, textvariable=self.var_page, width=5, justify="center")
        e.pack(side="left")
        e.bind("<Return>", self._saisie_page)
        self.lbl_total = ttk.Label(self.statut_barre, text="/ 0", width=6)
        self.lbl_total.pack(side="left", padx=3)
        ttk.Button(self.statut_barre, text="▶", width=3, command=lambda: self.aller_page(self.page_idx + 1)).pack(side="left")
        ttk.Separator(self.statut_barre, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(self.statut_barre, text="−", width=3, command=lambda: self.changer_zoom(-1)).pack(side="left")
        self.var_zoom = tk.StringVar(value=self.mode_zoom)
        cz = ttk.Combobox(self.statut_barre, textvariable=self.var_zoom, values=ZOOMS, width=11, state="readonly")
        cz.pack(side="left", padx=2)
        cz.bind("<<ComboboxSelected>>", lambda e: self._choix_zoom())
        ttk.Button(self.statut_barre, text="+", width=3, command=lambda: self.changer_zoom(1)).pack(side="left", padx=(0, 6))

        self.panneaux = ttk.PanedWindow(self, orient="horizontal")
        self.panneaux.pack(fill="both", expand=True)

        # Miniatures
        g = ttk.Frame(self.panneaux)
        ttk.Label(g, text="  Pages", font=("Segoe UI" if WINDOWS else "TkDefaultFont", 10, "bold")).pack(anchor="w", pady=3)
        self.c_vignettes = tk.Canvas(g, width=int(170 * self.echelle_ui), bg="#e8e8e8", highlightthickness=0)
        sv = ttk.Scrollbar(g, orient="vertical", command=self.c_vignettes.yview)
        self.c_vignettes.configure(yscrollcommand=sv.set)
        self.c_vignettes.pack(side="left", fill="both", expand=True)
        sv.pack(side="right", fill="y")
        self.c_vignettes.bind("<ButtonPress-1>", self._vignette_clic)
        self.c_vignettes.bind("<ButtonRelease-1>", self._vignette_relache)
        self.c_vignettes.bind("<Button-3>", self._vignette_menu)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.c_vignettes.bind(seq, lambda e: self.c_vignettes.yview_scroll(
                -2 if (e.num == 4 or getattr(e, "delta", 0) > 0) else 2, "units"))
        self.panneaux.add(g, weight=0)

        # Page
        zone = ttk.Frame(self.panneaux)
        self.zone_page = zone
        self.canvas = tk.Canvas(zone, bg="#525659", highlightthickness=0)
        sy = ttk.Scrollbar(zone, orient="vertical", command=self.canvas.yview)
        sx = ttk.Scrollbar(zone, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        zone.rowconfigure(0, weight=1)
        zone.columnconfigure(0, weight=1)
        self.panneaux.add(zone, weight=1)
        self.canvas.bind("<ButtonPress-1>", self._souris_bas)
        self.canvas.bind("<B1-Motion>", self._souris_glisse)
        self.canvas.bind("<ButtonRelease-1>", self._souris_haut)
        self.canvas.bind("<Double-Button-1>", self._double_clic)
        self.canvas.bind("<Motion>", self._survol)
        self.canvas.bind("<Configure>", lambda e: self._redimension())
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>", "<Shift-MouseWheel>"):
            self.canvas.bind(seq, self._molette)

        # Panneau Rechercher / Remplacer (masqué au départ)
        self.panneau_recherche = self._construire_recherche()

    def _construire_recherche(self):
        f = ttk.Frame(self.panneaux, padding=10, width=int(300 * self.echelle_ui))
        entete = ttk.Frame(f)
        entete.pack(fill="x")
        ttk.Label(entete, text="Rechercher et remplacer", font=("Segoe UI" if WINDOWS else "TkDefaultFont", 11, "bold")).pack(side="left")
        ttk.Button(entete, text="✕", width=3, command=self.masquer_recherche).pack(side="right")
        ttk.Label(f, text="Rechercher :").pack(anchor="w", pady=(10, 0))
        self.var_cherche = tk.StringVar()
        self.entree_cherche = ttk.Entry(f, textvariable=self.var_cherche)
        self.entree_cherche.pack(fill="x")
        self.entree_cherche.bind("<Return>", lambda e: self.rechercher())
        p = ttk.Frame(f)
        p.pack(fill="x", pady=4)
        ttk.Button(p, text="Rechercher", command=self.rechercher).pack(side="left", fill="x", expand=True)
        ttk.Button(p, text="▲", width=3, command=lambda: self.resultat_suivant(-1)).pack(side="left", padx=(4, 0))
        ttk.Button(p, text="▼", width=3, command=lambda: self.resultat_suivant(1)).pack(side="left")
        self.lbl_resultats = ttk.Label(f, text="", foreground="#555")
        self.lbl_resultats.pack(anchor="w")
        ttk.Label(f, text="Remplacer par :").pack(anchor="w", pady=(10, 0))
        self.var_remplace = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.var_remplace)
        e.pack(fill="x")
        e.bind("<Return>", lambda ev: self.remplacer_tout())
        self.var_respecter_casse = tk.BooleanVar(value=True)
        self.var_portee = tk.StringVar(value="document")
        ttk.Checkbutton(f, text="Respecter majuscules / minuscules",
                        variable=self.var_respecter_casse).pack(anchor="w", pady=(6, 0))
        ttk.Radiobutton(f, text="Tout le document", variable=self.var_portee, value="document").pack(anchor="w")
        ttk.Radiobutton(f, text="Page actuelle", variable=self.var_portee, value="page").pack(anchor="w")
        ttk.Button(f, text="Remplacer tout", command=self.remplacer_tout).pack(fill="x", pady=(10, 0))
        ttk.Label(f, text="Le texte remplacé garde la police, la taille et la couleur d'origine. "
                  "La suite de la ligne est décalée si besoin.", wraplength=int(270 * self.echelle_ui),
                  foreground="#666").pack(anchor="w", pady=(10, 0))
        return f

    def _accueil(self):
        a = ttk.Frame(self.zone_page, style="Accueil.TFrame", padding=40)
        self.accueil = a
        ttk.Label(a, text="PDF Éditeur", style="Titre.TLabel").pack(pady=(30, 6))
        ttk.Label(a, text="Ouvrez un PDF pour le lire, le modifier et l'enregistrer.",
                  style="Accueil.TLabel").pack()
        ttk.Button(a, text="📂  Ouvrir un fichier PDF…", style="Grand.TButton",
                   command=self.demander_ouvrir).pack(pady=24)
        if DND_FILES:
            ttk.Label(a, text="ou glissez-déposez un fichier PDF dans cette fenêtre",
                      style="Accueil.TLabel", foreground="#666").pack()
        self.cadre_recents = ttk.Frame(a, style="Accueil.TFrame")
        self.cadre_recents.pack(pady=(30, 0))
        self._maj_accueil()

    def _maj_accueil(self):
        for w in self.cadre_recents.winfo_children():
            w.destroy()
        recents = [r for r in self.reglages["recents"] if os.path.isfile(r)][:8]
        if recents:
            ttk.Label(self.cadre_recents, text="Fichiers récents", style="Accueil.TLabel",
                      font=("Segoe UI" if WINDOWS else "TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(0, 6))
        for r in recents:
            l = ttk.Label(self.cadre_recents, text=f"📄  {os.path.basename(r)}", style="Lien.TLabel", cursor="hand2")
            l.configure(background="#f3f3f3")
            l.pack(anchor="w", pady=1)
            l.bind("<Button-1>", lambda e, c=r: self.ouvrir(c))
            ttk.Label(self.cadre_recents, text="     " + os.path.dirname(r), style="Accueil.TLabel",
                      foreground="#888").pack(anchor="w")
        if self.doc is None:
            self.accueil.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _raccourcis(self):
        c = CTRL
        for touche, action in [
            ("o", self.demander_ouvrir), ("s", self.enregistrer), ("S", self.enregistrer_sous),
            ("p", self.imprimer), ("z", self.annuler), ("y", self.refaire), ("Z", self.refaire),
            ("f", self.afficher_recherche), ("h", self.afficher_recherche), ("r", lambda: self.pivoter(90)),
            ("e", lambda: self.outil.set("edition")), ("t", lambda: self.outil.set("texte")),
            ("w", self.fermer), ("plus", lambda: self.changer_zoom(1)), ("equal", lambda: self.changer_zoom(1)),
            ("minus", lambda: self.changer_zoom(-1)), ("0", lambda: self._choix_zoom("Largeur")),
        ]:
            self.bind(f"<{c}-{touche}>", lambda e, a=action: self._raccourci(e, a))
        self.bind("<Prior>", lambda e: self._raccourci(e, lambda: self.aller_page(self.page_idx - 1)))
        self.bind("<Next>", lambda e: self._raccourci(e, lambda: self.aller_page(self.page_idx + 1)))
        self.bind("<Escape>", lambda e: self._echap())
        self.bind("<F1>", lambda e: self.aide())

    def _raccourci(self, e, action):
        # Page préc./suiv. restent aux zones de saisie
        if isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Combobox)) and e.keysym in ("Prior", "Next"):
            return
        action()
        return "break"

    # ============================================================ Statut ==

    def statut(self, texte):
        self.lbl_statut.config(text=texte)

    def _polices_pretes(self):
        familles = polices.INDEX.familles()
        self.combo_police.configure(values=familles + POLICES_STANDARD)
        self._toutes_polices = familles + POLICES_STANDARD
        if self.var_police.get() not in self._toutes_polices:
            self.var_police.set("Helvetica")
        self.statut(f"{len(familles)} familles de polices disponibles.")
        if self.doc:
            self._verifier_polices()

    def _filtrer_polices(self, e):
        if e.keysym in ("Return", "Down", "Up"):
            return
        t = self.var_police.get().lower()
        toutes = getattr(self, "_toutes_polices", POLICES_STANDARD)
        self.combo_police.configure(values=[f for f in toutes if t in f.lower()] or toutes)

    def _verifier_polices(self):
        if not polices.INDEX.pret.is_set() or not self.doc:
            return
        etats = polices.etat_polices_document(self.doc)
        manquantes = [e for e in etats if e[3] in ("manquante", "equivalente")]
        self.lbl_alerte_polices.config(
            text=f"⚠ {len(manquantes)} police(s) à installer" if manquantes else "")

    def _maj_etat(self):
        nom = os.path.basename(self.chemin) if self.chemin else None
        self.title((("● " if self.modifie else "") + nom + " — PDF Éditeur") if nom else "PDF Éditeur")
        n = self.doc.page_count if self.doc else 0
        self.var_page.set(str(self.page_idx + 1) if n else "")
        self.lbl_total.config(text=f"/ {n}")
        self.btn_annuler.activer(bool(self.historique))
        self.btn_refaire.activer(bool(self.retablir))
        self.btn_enregistrer.activer(bool(self.doc))

    # ========================================================== Fichiers ==

    def demander_ouvrir(self):
        if not self._confirmer_abandon():
            return
        initial = os.path.dirname(self.reglages["recents"][0]) if self.reglages["recents"] else None
        chemin = filedialog.askopenfilename(title="Ouvrir un PDF", initialdir=initial,
                                            filetypes=[("Documents PDF", "*.pdf"), ("Tous les fichiers", "*.*")])
        if chemin:
            self.ouvrir(chemin)

    def _deposer(self, e):
        fichiers = [f for f in self.tk.splitlist(e.data) if f.lower().endswith(".pdf")]
        if not fichiers:
            images = [f for f in self.tk.splitlist(e.data)
                      if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff"))]
            if images and self.doc:
                self.image_a_placer = images[0]
                self.outil.set("image")
            return
        if self.doc:
            rep = messagebox.askyesnocancel(
                "Fichier déposé", "Ajouter ce(s) PDF à la fin du document actuel ?\n\n"
                "Oui : fusionner    Non : ouvrir à la place")
            if rep is None:
                return
            if rep:
                return self.fusionner(fichiers)
            if not self._confirmer_abandon():
                return
        self.ouvrir(fichiers[0])

    def ouvrir(self, chemin):
        self._fermer_edition(valider=True)
        try:
            with open(chemin, "rb") as f:
                donnees = f.read()
            doc = pymupdf.open(stream=donnees, filetype="pdf")
        except Exception as e:
            messagebox.showerror("Ouverture impossible", f"{chemin}\n\n{e}")
            return
        if doc.needs_pass:
            while True:
                mdp = simpledialog.askstring("Document protégé", f"{os.path.basename(chemin)} est protégé.\n"
                                             "Mot de passe :", show="•", parent=self)
                if mdp is None:
                    return
                if doc.authenticate(mdp):
                    break
                messagebox.showerror("Mot de passe", "Mot de passe incorrect.")
            doc = pymupdf.open(stream=doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE), filetype="pdf")
            messagebox.showinfo("Document protégé", "Le document est déverrouillé pour être modifié.\n"
                                "Utilisez « Fichier › Enregistrer avec mot de passe » pour le protéger à nouveau.")
        self.doc, self.chemin = doc, os.path.abspath(chemin)
        self.historique.clear()
        self.retablir.clear()
        self.modifie = False
        self.page_idx = 0
        self.resultats_recherche = []
        recents = [self.chemin] + [r for r in self.reglages["recents"] if r != self.chemin]
        self.reglages["recents"] = recents[:12]
        self._sauver_reglages()
        self.accueil.place_forget()
        self.statut(f"{os.path.basename(chemin)} : {doc.page_count} page(s).")
        self.update_idletasks()
        self._appliquer_mode_zoom()
        self._construire_vignettes()
        self._verifier_polices()

    def fermer(self):
        if not self.doc or not self._confirmer_abandon():
            return
        self._fermer_edition(valider=False)
        self.doc, self.chemin, self.modifie = None, None, False
        self.historique.clear()
        self.retablir.clear()
        self.canvas.delete("all")
        self.c_vignettes.delete("all")
        self.image = None
        self.lbl_alerte_polices.config(text="")
        self._maj_accueil()
        self._maj_etat()

    def enregistrer(self):
        if not self.doc:
            return False
        self._fermer_edition(valider=True)
        if not self.chemin:
            return self.enregistrer_sous()
        return self._ecrire(self.chemin)

    def enregistrer_sous(self):
        if not self.doc:
            return False
        self._fermer_edition(valider=True)
        base = os.path.splitext(os.path.basename(self.chemin or "document.pdf"))[0]
        chemin = filedialog.asksaveasfilename(
            title="Enregistrer sous", defaultextension=".pdf", initialfile=base + ".pdf",
            initialdir=os.path.dirname(self.chemin) if self.chemin else None,
            filetypes=[("Document PDF", "*.pdf")])
        if not chemin:
            return False
        if self._ecrire(chemin):
            self.chemin = os.path.abspath(chemin)
            self.reglages["recents"] = [self.chemin] + [r for r in self.reglages["recents"] if r != self.chemin]
            self._sauver_reglages()
            self._maj_etat()
            return True
        return False

    def _ecrire(self, chemin, **options):
        try:
            donnees = self.doc.tobytes(garbage=3, deflate=True, **options)
            temporaire = chemin + ".tmp"
            with open(temporaire, "wb") as f:
                f.write(donnees)
            os.replace(temporaire, chemin)
        except PermissionError:
            messagebox.showerror("Enregistrement impossible",
                                 f"Le fichier est peut-être ouvert dans un autre programme :\n{chemin}\n\n"
                                 "Fermez-le ou utilisez « Enregistrer sous ».")
            return False
        except Exception as e:
            messagebox.showerror("Enregistrement impossible", str(e))
            return False
        if not options:
            self.modifie = False
        self.statut(f"Enregistré : {chemin}")
        self._maj_etat()
        return True

    def chiffrer(self):
        if not self._doc_requis():
            return
        r = Formulaire(self, "Enregistrer avec mot de passe", [
            ("mdp", "Mot de passe :", "", "motdepasse"), ("mdp2", "Confirmer :", "", "motdepasse")],
            aide="Le fichier sera chiffré (AES-256). Il faudra ce mot de passe pour l'ouvrir.").resultat
        if not r:
            return
        if not r["mdp"] or r["mdp"] != r["mdp2"]:
            return messagebox.showerror("Mot de passe", "Les mots de passe sont vides ou différents.")
        chemin = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile="document_protege.pdf",
                                              filetypes=[("Document PDF", "*.pdf")])
        if chemin:
            self._ecrire(chemin, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=r["mdp"], owner_pw=r["mdp"])

    def fusionner(self, chemins=None):
        if not self._doc_requis():
            return
        chemins = chemins or filedialog.askopenfilenames(title="PDF à ajouter à la fin",
                                                         filetypes=[("Documents PDF", "*.pdf")])
        if not chemins:
            return
        self._avant_modif()
        for c in chemins:
            try:
                with pymupdf.open(c) as autre:
                    self.doc.insert_pdf(autre)
                self.statut(f"Ajouté : {os.path.basename(c)}")
            except Exception as e:
                messagebox.showerror("Fusion", f"Impossible d'ajouter {c} :\n{e}")
        self._apres_modif(structure=True)

    def exporter_pages(self):
        if not self._doc_requis():
            return
        spec = simpledialog.askstring("Exporter des pages", f"Pages à exporter (ex. 1,3-5) — "
                                      f"le document en a {self.doc.page_count} :",
                                      initialvalue=str(self.page_idx + 1), parent=self)
        if not spec:
            return
        try:
            pages = pdftool.parse_pages(spec, self.doc.page_count)
        except ValueError as e:
            return messagebox.showerror("Pages", str(e))
        chemin = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile="extrait.pdf",
                                              filetypes=[("Document PDF", "*.pdf")])
        if chemin:
            nouveau = pymupdf.open()
            for i in pages:
                nouveau.insert_pdf(self.doc, from_page=i, to_page=i)
            nouveau.save(chemin, garbage=3, deflate=True)
            self.statut(f"{len(pages)} page(s) exportée(s) : {chemin}")

    def exporter_images(self):
        if not self._doc_requis():
            return
        dossier = filedialog.askdirectory(title="Dossier où enregistrer les images")
        if not dossier:
            return
        base = os.path.splitext(os.path.basename(self.chemin or "page"))[0]
        self.config(cursor="watch")
        self.update()
        for i, page in enumerate(self.doc):
            page.get_pixmap(dpi=150).save(os.path.join(dossier, f"{base}_page{i + 1:03d}.png"))
        self.config(cursor="")
        self.statut(f"{self.doc.page_count} image(s) enregistrée(s) dans {dossier}")

    def exporter_texte(self):
        if not self._doc_requis():
            return
        chemin = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="texte.txt",
                                              filetypes=[("Texte", "*.txt")])
        if chemin:
            with open(chemin, "w", encoding="utf-8") as f:
                for i, page in enumerate(self.doc):
                    f.write(f"===== Page {i + 1} =====\n{page.get_text()}\n")
            self.statut(f"Texte exporté : {chemin}")

    def imprimer(self):
        if not self._doc_requis():
            return
        self._fermer_edition(valider=True)
        chemin = os.path.join(tempfile.gettempdir(), "PDF_Editeur_impression.pdf")
        self.doc.save(chemin, garbage=3, deflate=True)
        if WINDOWS:
            try:
                os.startfile(chemin, "print")
                self.statut("Document envoyé à l'imprimante par défaut.")
            except OSError:
                os.startfile(chemin)
                self.statut("Utilisez la commande Imprimer du lecteur PDF qui vient de s'ouvrir.")
        else:
            messagebox.showinfo("Imprimer", f"Une copie a été enregistrée ici pour l'imprimer :\n{chemin}")

    def metadonnees(self):
        if not self._doc_requis():
            return
        m = self.doc.metadata or {}
        r = Formulaire(self, "Propriétés du document", [
            ("title", "Titre :", m.get("title", ""), "texte"),
            ("author", "Auteur :", m.get("author", ""), "texte"),
            ("subject", "Sujet :", m.get("subject", ""), "texte"),
            ("keywords", "Mots-clés :", m.get("keywords", ""), "texte")]).resultat
        if r:
            self._avant_modif()
            m.update(r)
            self.doc.set_metadata(m)
            self._apres_modif()
            self.statut("Propriétés mises à jour.")

    def quitter(self):
        if self._confirmer_abandon():
            self._sauver_reglages()
            self.destroy()

    def _confirmer_abandon(self):
        self._fermer_edition(valider=True)
        if self.doc and self.modifie:
            rep = messagebox.askyesnocancel("Modifications non enregistrées",
                                            f"Enregistrer les modifications de « {os.path.basename(self.chemin or 'document')} » ?")
            if rep is None:
                return False
            if rep:
                return bool(self.enregistrer())
        return True

    def _sauver_reglages(self):
        try:
            with open(self.config_chemin, "w", encoding="utf-8") as f:
                json.dump(self.reglages, f, indent=1)
        except OSError:
            pass

    def _remplir_recents(self):
        self.menu_recents.delete(0, "end")
        for r in [r for r in self.reglages["recents"] if os.path.isfile(r)][:10]:
            self.menu_recents.add_command(label=r, command=lambda c=r: self._confirmer_abandon() and self.ouvrir(c))

    # ===================================================== Modifications ==

    def _doc_requis(self):
        if not self.doc:
            messagebox.showinfo("Aucun document", "Ouvrez d'abord un fichier PDF.")
            return False
        return True

    def _avant_modif(self):
        self.historique.append((self.doc.tobytes(), self.page_idx))
        self.retablir.clear()
        while len(self.historique) > 1 and sum(len(h[0]) for h in self.historique) > MAX_HISTORIQUE_OCTETS:
            self.historique.pop(0)

    def _apres_modif(self, structure=False, pages=None):
        self.modifie = True
        self.page_idx = max(0, min(self.page_idx, self.doc.page_count - 1))
        self.afficher()
        if structure:
            self._construire_vignettes()
        else:
            self._invalider_vignettes(pages if pages is not None else [self.page_idx])

    def annuler(self):
        self._fermer_edition(valider=False)
        if not self.historique:
            return
        self.retablir.append((self.doc.tobytes(), self.page_idx))
        donnees, self.page_idx = self.historique.pop()
        self.doc = pymupdf.open(stream=donnees, filetype="pdf")
        self.modifie = True
        self.statut("Modification annulée.")
        self.afficher()
        self._construire_vignettes()

    def refaire(self):
        self._fermer_edition(valider=False)
        if not self.retablir:
            return
        self.historique.append((self.doc.tobytes(), self.page_idx))
        donnees, self.page_idx = self.retablir.pop()
        self.doc = pymupdf.open(stream=donnees, filetype="pdf")
        self.modifie = True
        self.statut("Modification rétablie.")
        self.afficher()
        self._construire_vignettes()

    def pivoter(self, angle, toutes=False, idx=None):
        if not self._doc_requis():
            return
        self._fermer_edition(valider=True)
        self._avant_modif()
        pages = range(self.doc.page_count) if toutes else [self.page_idx if idx is None else idx]
        for i in pages:
            p = self.doc[i]
            p.set_rotation((p.rotation + angle) % 360)
        self._apres_modif(pages=list(pages))
        if self.mode_zoom in ("Largeur", "Page entière"):
            self._appliquer_mode_zoom()

    def supprimer_page(self, idx=None):
        if not self._doc_requis():
            return
        idx = self.page_idx if idx is None else idx
        if self.doc.page_count == 1:
            return messagebox.showinfo("Supprimer", "Impossible de supprimer la seule page du document.")
        if messagebox.askyesno("Supprimer la page", f"Supprimer la page {idx + 1} ?"):
            self._fermer_edition(valider=False)
            self._avant_modif()
            self.doc.delete_page(idx)
            self._apres_modif(structure=True)
            self.statut(f"Page {idx + 1} supprimée.")

    def deplacer_page(self, de, vers):
        if not self.doc or de == vers or not (0 <= vers < self.doc.page_count):
            return
        self._fermer_edition(valider=True)
        self._avant_modif()
        # move_page(a, b) : place la page a avant la page b (-1 = à la fin)
        if vers > de:
            self.doc.move_page(de, vers + 1 if vers + 1 < self.doc.page_count else -1)
        else:
            self.doc.move_page(de, vers)
        self.page_idx = vers
        self._apres_modif(structure=True)

    def inserer_page_blanche(self, apres=None):
        if not self._doc_requis():
            return
        apres = self.page_idx if apres is None else apres
        r = self.doc[apres].rect
        self._avant_modif()
        self.doc.new_page(apres + 1, width=r.width, height=r.height)
        self.page_idx = apres + 1
        self._apres_modif(structure=True)

    def inserer_pdf(self, apres=None):
        if not self._doc_requis():
            return
        apres = self.page_idx if apres is None else apres
        chemin = filedialog.askopenfilename(title="PDF à insérer", filetypes=[("Documents PDF", "*.pdf")])
        if not chemin:
            return
        self._avant_modif()
        with pymupdf.open(chemin) as autre:
            self.doc.insert_pdf(autre, start_at=apres + 1)
        self.page_idx = apres + 1
        self._apres_modif(structure=True)

    def filigrane(self):
        if not self._doc_requis():
            return
        r = Formulaire(self, "Filigrane", [
            ("texte", "Texte :", "CONFIDENTIEL", "texte"), ("taille", "Taille :", 60, "nombre"),
            ("opacite", "Opacité (0 à 1) :", 0.3, "nombre"), ("couleur", "Couleur :", "#999999", "couleur"),
            ("portee", "Pages :", "Toutes", ("choix", ["Toutes", "Page actuelle"]))]).resultat
        if not r or not r["texte"]:
            return
        self._avant_modif()
        couleur = _hex_vers_rgb(r["couleur"])
        pages = range(self.doc.page_count) if r["portee"] == "Toutes" else [self.page_idx]
        for i in pages:
            page = self.doc[i]
            rect = page.rect * page.derotation_matrix
            rect.normalize()
            centre = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
            largeur = pymupdf.get_text_length(r["texte"], fontname="hebo", fontsize=r["taille"])
            page.insert_text(centre + (-largeur / 2, r["taille"] / 3), r["texte"], fontname="hebo",
                             fontsize=r["taille"], color=couleur, fill_opacity=max(0, min(1, r["opacite"])),
                             morph=(centre, pymupdf.Matrix(45 + page.rotation)))
        self._apres_modif(pages=list(pages))

    def numeroter(self):
        if not self._doc_requis():
            return
        r = Formulaire(self, "Numéroter les pages", [
            ("format", "Format :", "{n} / {total}", "texte"), ("taille", "Taille :", 10, "nombre"),
            ("position", "Position :", "En bas au centre",
             ("choix", ["En bas au centre", "En bas à droite", "En haut à droite"]))],
            aide="{n} = numéro de la page, {total} = nombre de pages.").resultat
        if not r:
            return
        self._avant_modif()
        total = self.doc.page_count
        for i, page in enumerate(self.doc):
            texte = r["format"].replace("{n}", str(i + 1)).replace("{total}", str(total))
            l = pymupdf.get_text_length(texte, fontname="helv", fontsize=r["taille"])
            rect = page.rect * page.derotation_matrix
            rect.normalize()
            # positions dans le repère de la page telle qu'affichée
            vue = page.rect
            if r["position"] == "En bas au centre":
                p = pymupdf.Point(vue.width / 2 - l / 2, vue.height - 25)
            elif r["position"] == "En bas à droite":
                p = pymupdf.Point(vue.width - 40 - l, vue.height - 25)
            else:
                p = pymupdf.Point(vue.width - 40 - l, 30)
            page.insert_text(p * page.derotation_matrix, texte, fontname="helv", fontsize=r["taille"],
                             color=(0.2, 0.2, 0.2), rotate=page.rotation)
        self._apres_modif(pages=list(range(total)))

    # ===================================================== Affichage page ==

    @property
    def facteur(self):
        return self.zoom * self.dpi / 72

    def afficher(self):
        self._maj_etat()
        self.canvas.delete("all")
        if not self.doc:
            return
        page = self.doc[self.page_idx]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(self.facteur, self.facteur), alpha=False, annots=True)
        self.image = tk.PhotoImage(data=pix.tobytes("ppm"))
        self.canvas.create_rectangle(3, 3, pix.width + 3, pix.height + 3, fill="#2b2d2f", outline="", tags="page")
        self.canvas.create_image(0, 0, image=self.image, anchor="nw", tags=("page", "fond"))
        self.mots = page.get_text("words")
        self.spans = [s for b in page.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]
                      if s["text"].strip()]
        self.selection = []
        self._placer()
        self._dessiner_resultats()
        if self.outil.get() == "edition":
            self._dessiner_contours()
        self._selection_vignette()

    def _placer(self):
        if not self.image:
            return
        w, h = self.image.width(), self.image.height()
        cw = self.canvas.winfo_width()
        self.decalage = (max(24, (cw - w) // 2), 24)
        bbox = self.canvas.bbox("fond")
        if bbox:
            self.canvas.move("all", self.decalage[0] - bbox[0], self.decalage[1] - bbox[1])
        self.canvas.configure(scrollregion=(0, 0, max(cw, w + 48), h + 48))

    def _redimension(self):
        if self.edition:  # ne pas interrompre une modification en cours
            return
        if self.doc and self.mode_zoom in ("Largeur", "Page entière"):
            if getattr(self, "_redim_prevu", None):
                self.after_cancel(self._redim_prevu)
            self._redim_prevu = self.after(150, self._appliquer_mode_zoom)
        else:
            self._placer()

    def _vers_canvas(self, rect):
        page = self.doc[self.page_idx]
        r = pymupdf.Rect(rect) * page.rotation_matrix * self.facteur
        r.normalize()
        dx, dy = self.decalage
        return r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy

    def _vers_page(self, x, y):
        """Coordonnées écran (événement) -> coordonnées de la page non pivotée."""
        page = self.doc[self.page_idx]
        dx, dy = self.decalage
        p = pymupdf.Point((self.canvas.canvasx(x) - dx) / self.facteur, (self.canvas.canvasy(y) - dy) / self.facteur)
        return p * page.derotation_matrix

    def _dessiner_contours(self):
        self.canvas.delete("contour")
        for s in self.spans:
            x0, y0, x1, y1 = self._vers_canvas(s["bbox"])
            self.canvas.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1, outline="#8ab4f8", dash=(3, 2),
                                         tags="contour")

    def aller_page(self, idx, haut=True):
        if self.doc and 0 <= idx < self.doc.page_count and idx != self.page_idx:
            self._fermer_edition(valider=True)
            self.page_idx = idx
            self.afficher()
            self.canvas.yview_moveto(0 if haut else 1)

    def _saisie_page(self, _):
        try:
            self.aller_page(int(self.var_page.get()) - 1)
        except ValueError:
            pass
        self._maj_etat()

    def _choix_zoom(self, valeur=None):
        self.mode_zoom = valeur or self.var_zoom.get()
        self.reglages["zoom"] = self.mode_zoom if self.mode_zoom in ("Largeur", "Page entière") else "Largeur"
        self._appliquer_mode_zoom()

    def _appliquer_mode_zoom(self):
        if not self.doc:
            return
        ancien = self.zoom
        r = self.doc[self.page_idx].rect
        cw, ch = self.canvas.winfo_width() - 60, self.canvas.winfo_height() - 50
        base = self.dpi / 72
        if self.mode_zoom == "Largeur":
            self.zoom = max(0.2, cw / (r.width * base))
        elif self.mode_zoom == "Page entière":
            self.zoom = max(0.2, min(cw / (r.width * base), ch / (r.height * base)))
        else:
            self.zoom = int(self.mode_zoom.split()[0]) / 100
        self.var_zoom.set(self.mode_zoom if not self.mode_zoom[0].isdigit() else f"{round(self.zoom * 100)} %")
        if self.image and abs(ancien - self.zoom) < 0.005:
            self._placer()
            return
        self._fermer_edition(valider=True)
        self.afficher()

    def changer_zoom(self, sens):
        if not self.doc:
            return
        paliers = [int(z.split()[0]) / 100 for z in ZOOMS if z[0].isdigit()]
        proches = [z for z in paliers if (z > self.zoom + 0.01 if sens > 0 else z < self.zoom - 0.01)]
        if proches:
            self.mode_zoom = f"{round((min(proches) if sens > 0 else max(proches)) * 100)} %"
            self._appliquer_mode_zoom()

    def _molette(self, e):
        bas = not (e.num == 4 or getattr(e, "delta", 0) > 0)
        if e.state & 0x4:  # Ctrl + molette : zoom
            self.changer_zoom(-1 if bas else 1)
            return "break"
        if e.state & 0x1:  # Maj + molette : défilement horizontal
            self.canvas.xview_scroll(3 if bas else -3, "units")
            return "break"
        haut_vue, bas_vue = self.canvas.yview()
        if bas and bas_vue >= 0.999:
            self.aller_page(self.page_idx + 1, haut=True)
        elif not bas and haut_vue <= 0.001:
            self.aller_page(self.page_idx - 1, haut=False)
        else:
            self.canvas.yview_scroll(3 if bas else -3, "units")
        return "break"

    # ========================================================= Miniatures ==

    def _construire_vignettes(self):
        c = self.c_vignettes
        c.delete("all")
        if not self.doc:
            return
        largeur = int(120 * self.echelle_ui)
        x0 = (int(c.cget("width")) - largeur) // 2
        y = 12
        self.vignettes = []
        for i, page in enumerate(self.doc):
            r = page.rect
            h = int(largeur * r.height / r.width)
            c.create_rectangle(x0, y, x0 + largeur, y + h, fill="white", outline="#bbb", tags=(f"v{i}", "vignette"))
            c.create_text(x0 + largeur // 2, y + h + 10, text=str(i + 1), fill="#333", tags=f"n{i}")
            self.vignettes.append({"y0": y, "y1": y + h, "x0": x0, "l": largeur, "image": None})
            y += h + 30
        c.configure(scrollregion=(0, 0, int(c.cget("width")), y))
        self.vignettes_a_rendre = list(range(self.doc.page_count))
        self._selection_vignette()
        self.after(10, self._rendre_vignettes)

    def _invalider_vignettes(self, pages):
        for i in pages:
            if i not in self.vignettes_a_rendre and i < len(self.vignettes):
                self.vignettes_a_rendre.insert(0, i)
        self.after(10, self._rendre_vignettes)

    def _rendre_vignettes(self):
        if not self.doc:
            return
        for _ in range(4):
            if not self.vignettes_a_rendre:
                return
            i = self.vignettes_a_rendre.pop(0)
            if i >= self.doc.page_count or i >= len(self.vignettes):
                continue
            v = self.vignettes[i]
            page = self.doc[i]
            f = v["l"] / page.rect.width
            pix = page.get_pixmap(matrix=pymupdf.Matrix(f, f), alpha=False)
            v["image"] = tk.PhotoImage(data=pix.tobytes("ppm"))
            self.c_vignettes.delete(f"img{i}")
            self.c_vignettes.create_image(v["x0"], v["y0"], image=v["image"], anchor="nw", tags=(f"img{i}", "vignette"))
        self.after(5, self._rendre_vignettes)

    def _selection_vignette(self):
        c = self.c_vignettes
        c.delete("sel")
        if not self.doc or self.page_idx >= len(self.vignettes):
            return
        v = self.vignettes[self.page_idx]
        c.create_rectangle(v["x0"] - 4, v["y0"] - 4, v["x0"] + v["l"] + 4, v["y1"] + 4, outline=BLEU, width=3,
                           tags="sel")
        haut, bas = c.yview()
        total = float(c.cget("scrollregion").split()[3] or 1)
        if not (haut * total <= v["y0"] and v["y1"] <= bas * total):
            c.yview_moveto(max(0, (v["y0"] - 20) / total))

    def _vignette_a(self, y):
        y = self.c_vignettes.canvasy(y)
        for i, v in enumerate(self.vignettes):
            if v["y0"] - 15 <= y <= v["y1"] + 15:
                return i
        return None

    def _vignette_clic(self, e):
        self._glisser_vignette = self._vignette_a(e.y)
        if self._glisser_vignette is not None:
            self.aller_page(self._glisser_vignette)

    def _vignette_relache(self, e):
        de, vers = getattr(self, "_glisser_vignette", None), self._vignette_a(e.y)
        if de is not None and vers is not None and de != vers:
            self.deplacer_page(de, vers)
            self.statut(f"Page {de + 1} déplacée en position {vers + 1}.")

    def _vignette_menu(self, e):
        i = self._vignette_a(e.y)
        if i is None:
            return
        self.aller_page(i)
        m = tk.Menu(self, tearoff=False)
        m.add_command(label="Pivoter à droite", command=lambda: self.pivoter(90, idx=i))
        m.add_command(label="Pivoter à gauche", command=lambda: self.pivoter(-90, idx=i))
        m.add_separator()
        m.add_command(label="Insérer une page blanche après", command=lambda: self.inserer_page_blanche(i))
        m.add_command(label="Insérer un PDF après…", command=lambda: self.inserer_pdf(i))
        m.add_command(label="Monter", command=lambda: self.deplacer_page(i, i - 1))
        m.add_command(label="Descendre", command=lambda: self.deplacer_page(i, i + 1))
        m.add_separator()
        m.add_command(label="Supprimer la page", command=lambda: self.supprimer_page(i))
        m.tk_popup(e.x_root, e.y_root)

    # ============================================================= Outils ==

    def _changement_outil(self):
        self._fermer_edition(valider=True)
        self._marquer_outil()
        o = self.outil.get()
        curseurs = {"selection": "xterm", "edition": "xterm", "texte": "crosshair", "image": "crosshair",
                    "signature": "crosshair", "surligner": "xterm", "commentaire": "crosshair",
                    "caviarder": "crosshair"}
        self.canvas.config(cursor=curseurs.get(o, ""))
        if o in ("edition", "texte"):
            self.barre_format.pack(side="top", fill="x", after=self.ruban)
        else:
            self.barre_format.pack_forget()
        self.canvas.delete("contour")
        if o == "edition" and self.doc:
            self._dessiner_contours()
        aides = {
            "selection": "Cliquez sur un mot pour voir sa police. Double-cliquez pour le modifier.",
            "edition": "Cliquez sur un texte pour le modifier. Entrée pour valider, Échap pour annuler.",
            "texte": "Cliquez sur la page à l'endroit où écrire.",
            "image": "Tracez un rectangle sur la page pour placer l'image.",
            "signature": "Tracez un rectangle sur la page pour placer la signature.",
            "surligner": "Glissez sur le texte à surligner.",
            "commentaire": "Cliquez sur la page pour ajouter un commentaire.",
            "caviarder": "Tracez un rectangle : tout son contenu sera définitivement effacé.",
        }
        self.statut(aides.get(o, ""))

    def _echap(self):
        if self.edition:
            self._fermer_edition(valider=False)
        else:
            self.outil.set("selection")
            self.selection = []
            self.canvas.delete("selection")

    def _survol(self, e):
        if not self.doc or self.outil.get() != "edition":
            return
        p = self._vers_page(e.x, e.y)
        sur_texte = any(pymupdf.Rect(s["bbox"]).contains(p) for s in self.spans)
        self.canvas.config(cursor="xterm" if sur_texte else "arrow")

    def _souris_bas(self, e):
        if not self.doc:
            return
        o = self.outil.get()
        p = self._vers_page(e.x, e.y)
        self.glisser = (e.x, e.y)
        if o == "edition":
            span = self._span_a(p)
            if self.edition and span is self.edition.get("span"):
                return
            self._fermer_edition(valider=True)
            if span:
                self._ouvrir_edition(span)
        elif o == "texte":
            if self.edition:
                self._fermer_edition(valider=True)
            else:
                self._ouvrir_ajout(p)
        elif o == "commentaire":
            self._commentaire(p)
        elif o in ("selection", "surligner"):
            self._selectionner(p, p)

    def _souris_glisse(self, e):
        if not self.doc or not self.glisser:
            return
        o = self.outil.get()
        if o in ("selection", "surligner"):
            self._selectionner(self._vers_page(*self.glisser), self._vers_page(e.x, e.y))
        elif o in ("image", "signature", "caviarder"):
            self.canvas.delete("cadre")
            x0, y0 = self.canvas.canvasx(self.glisser[0]), self.canvas.canvasy(self.glisser[1])
            x1, y1 = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
            couleur = "#d93025" if o == "caviarder" else BLEU
            self.canvas.create_rectangle(x0, y0, x1, y1, outline=couleur, dash=(4, 3), width=2, tags="cadre",
                                         fill="#000000" if o == "caviarder" else "", stipple="gray25" if o == "caviarder" else "")

    def _souris_haut(self, e):
        if not self.doc or not self.glisser:
            return
        o = self.outil.get()
        debut, self.glisser = self.glisser, None
        if o == "selection" and self.selection:
            self._infos_selection()
        elif o == "surligner" and self.selection:
            self._surligner()
        elif o in ("image", "signature", "caviarder"):
            self.canvas.delete("cadre")
            if abs(e.x - debut[0]) < 8 or abs(e.y - debut[1]) < 8:
                return self.statut("Tracez un rectangle plus grand (cliquez et faites glisser).")
            {"image": self._placer_image, "signature": self._placer_signature,
             "caviarder": self._caviarder}[o](debut, (e.x, e.y))

    def _double_clic(self, e):
        if self.doc and self.outil.get() == "selection":
            span = self._span_a(self._vers_page(e.x, e.y))
            if span:
                self.outil.set("edition")
                self._ouvrir_edition(self._span_a(self._vers_page(e.x, e.y)))

    def _span_a(self, p):
        for s in self.spans:
            if pymupdf.Rect(s["bbox"]).contains(p):
                return s
        proches = [s for s in self.spans if (pymupdf.Rect(s["bbox"]) + (-3, -3, 3, 3)).contains(p)]
        return proches[0] if proches else None

    def _selectionner(self, a, b):
        zone = pymupdf.Rect(a, b)
        zone.normalize()
        if zone.is_empty:
            zone = pymupdf.Rect(a.x - 0.5, a.y - 0.5, a.x + 0.5, a.y + 0.5)
        self.selection = [m for m in self.mots if pymupdf.Rect(m[:4]).intersects(zone)]
        self.canvas.delete("selection")
        for m in self.selection:
            x0, y0, x1, y1 = self._vers_canvas(m[:4])
            self.canvas.create_rectangle(x0, y0, x1, y1, outline=BLEU, width=2, tags="selection")

    def _infos_selection(self):
        mots = sorted(self.selection, key=lambda m: (m[5], m[6], m[7]))
        texte = " ".join(m[4] for m in mots)
        r = pymupdf.Rect(mots[0][:4])
        span = max(self.spans, key=lambda s: (pymupdf.Rect(s["bbox"]) & r).get_area(), default=None)
        if span:
            gras, ita = pdftool.style_span(span)
            style = " ".join(x for x, ok in (("gras", gras), ("italique", ita)) if ok) or "normal"
            self.statut(f"« {texte[:60]} »   —   Police : {span['font']}   Taille : {span['size']:.1f} pt   "
                        f"Style : {style}   Couleur : {pdftool.couleur_hex(span['color'])}")
        self.var_cherche.set(texte)
        self.clipboard_clear()
        self.clipboard_append(texte)

    # ----------------------------------------------------- Édition texte --

    def _famille_affichee(self, nom_pdf, gras, ita):
        nom = polices.sans_prefixe(nom_pdf).split("-")[0].split(",")[0]
        for std in POLICES_STANDARD:
            if nom.lower() == std.lower():
                return std
        entree, exacte = polices.INDEX.chercher(nom_pdf, gras, ita) if polices.INDEX.pret.is_set() else (None, False)
        return entree["famille"] if entree and exacte else nom

    def _police_tk(self, famille, taille_pt, gras, ita):
        px = max(6, round(taille_pt * self.facteur))
        return tkfont.Font(family=famille, size=-px, weight="bold" if gras else "normal",
                           slant="italic" if ita else "roman")

    def _ouvrir_edition(self, span):
        gras, ita = pdftool.style_span(span)
        famille = self._famille_affichee(span["font"], gras, ita)
        couleur = pdftool.couleur_hex(span["color"])
        self.var_police.set(famille)
        self.var_taille.set(f"{span['size']:g}" if span["size"] == int(span["size"]) else f"{span['size']:.1f}")
        self.var_gras.set(gras)
        self.var_italique.set(ita)
        self._regler_couleur(couleur)
        self.lbl_police_origine.config(text=f"Police d'origine : {span['font']}")
        texte = span["text"]
        x0, y0, x1, y1 = self._vers_canvas(span["bbox"])
        masque = self.canvas.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1, fill="white", outline="", tags="edition")
        e = tk.Entry(self.canvas, relief="solid", bd=1, highlightthickness=1, highlightcolor=BLEU,
                     font=self._police_tk(famille, span["size"], gras, ita), fg=couleur)
        e.insert(0, texte)
        largeur = max(x1 - x0 + 60, 160)
        fen = self.canvas.create_window(x0 - 3, y0 - 3, anchor="nw", window=e, width=largeur, tags="edition")
        e.focus_set()
        e.icursor("end")
        e.bind("<Return>", lambda ev: (self._fermer_edition(valider=True), "break")[1])
        e.bind("<Escape>", lambda ev: (self._fermer_edition(valider=False), "break")[1])
        self.edition = {"type": "modif", "span": span, "entree": e, "items": (masque, fen), "texte": texte,
                        "style": self._style_courant()}

    def _ouvrir_ajout(self, p):
        famille = self.var_police.get()
        taille = self._taille()
        x, y = self._vers_canvas(pymupdf.Rect(p, p))[:2]
        e = tk.Entry(self.canvas, relief="solid", bd=1, highlightthickness=1, highlightcolor=BLEU,
                     font=self._police_tk(famille, taille, self.var_gras.get(), self.var_italique.get()),
                     fg=self.couleur)
        fen = self.canvas.create_window(x, y, anchor="nw", window=e, width=300, tags="edition")
        e.focus_set()
        e.bind("<Return>", lambda ev: (self._fermer_edition(valider=True), "break")[1])
        e.bind("<Escape>", lambda ev: (self._fermer_edition(valider=False), "break")[1])
        self.edition = {"type": "ajout", "point": p, "entree": e, "items": (fen,)}
        self.lbl_police_origine.config(text="")

    def _style_courant(self):
        return (self.var_police.get(), self._taille(), self.var_gras.get(), self.var_italique.get(), self.couleur)

    def _taille(self):
        try:
            return max(1.0, float(self.var_taille.get().replace(",", ".")))
        except ValueError:
            return 12.0

    def _format_change(self):
        if self.edition:
            f = self._police_tk(self.var_police.get(), self._taille(), self.var_gras.get(), self.var_italique.get())
            self.edition["entree"].configure(font=f, fg=self.couleur)

    def _choisir_couleur(self):
        c = colorchooser.askcolor(self.couleur, parent=self, title="Couleur du texte")[1]
        if c:
            self._regler_couleur(c)
            self._format_change()

    def _regler_couleur(self, c):
        self.couleur = c
        self.btn_couleur.configure(bg=c, activebackground=c)

    def _style_pdf(self, avec_police=True):
        """Mise en forme choisie dans la barre -> dict pour pdftool."""
        famille, taille, gras, ita, couleur = self._style_courant()
        style = {"taille": taille, "couleur": _hex_vers_rgb(couleur)}
        if avec_police:
            if famille in POLICES_STANDARD:
                style["base14"] = pdftool.BASE14[famille][(1 if gras else 0) + (2 if ita else 0)]
            else:
                entree = polices.INDEX.variante(famille, 700 if gras else 400, ita)
                if entree:
                    style["entree"] = entree
                else:
                    style["base14"] = pdftool.BASE14[pdftool._famille_base14(famille)][(1 if gras else 0) + (2 if ita else 0)]
        return style

    def _fermer_edition(self, valider=True):
        ed, self.edition = self.edition, None
        if not ed:
            return
        texte = ed["entree"].get()
        for item in ed["items"]:
            self.canvas.delete(item)
        ed["entree"].destroy()
        if not valider or not self.doc:
            return
        page = self.doc[self.page_idx]
        if ed["type"] == "ajout":
            if not texte.strip():
                return
            style = self._style_pdf()
            self._avant_modif()
            police_tk = self._police_tk(self.var_police.get(), self._taille(), self.var_gras.get(), self.var_italique.get())
            ascent = police_tk.metrics("ascent") / self.facteur
            # ligne de base sous le point cliqué, dans le sens de lecture de la page
            decal = pymupdf.Point(0, ascent) * pymupdf.Matrix(-page.rotation)
            pdftool.inserer_texte(page, ed["point"] + decal, texte, entree=style.get("entree"),
                                  base14=style.get("base14", "helv"), taille=style["taille"], couleur=style["couleur"])
            self._apres_modif()
            self.statut(f"Texte ajouté : « {texte} »")
            return
        # Modification d'un texte existant
        style_change = self._style_courant() != ed["style"]
        if texte == ed["texte"] and not style_change:
            return
        actuel = self._style_courant()
        police_changee = actuel[0] != ed["style"][0] or actuel[2:4] != ed["style"][2:4]
        style = self._style_pdf(avec_police=police_changee) if style_change else None
        self._avant_modif()
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            res = pdftool.modifier_texte(page, pymupdf.Rect(ed["span"]["bbox"]), texte, style=style,
                                         decaler=self.var_decaler.get())
        except Exception as ex:
            self.historique.pop()
            messagebox.showerror("Modification impossible", str(ex))
            return
        finally:
            self.config(cursor="")
        self._apres_modif()
        if res:
            msg = f"Texte modifié — police : {res['police']}"
            if res["deborde"]:
                msg += "  ⚠ le texte est plus long et peut chevaucher la suite"
            self.statut(msg)
            if "plus proche" in res["police"]:
                self._proposer_police(ed["span"]["font"])

    def _proposer_police(self, nom=None):
        quoi = f"La police « {polices.sans_prefixe(nom)} »" if nom else "La police d'origine"
        if messagebox.askyesno(
                "Police introuvable",
                f"{quoi} n'est pas installée : une police proche a été utilisée.\n\n"
                "Voulez-vous ajouter le fichier de cette police (.ttf / .otf) ?\n"
                "Ensuite, annulez (Ctrl+Z) et refaites la modification."):
            self.ajouter_fichiers_police()

    # ---------------------------------------------------- Autres outils --

    def _rect_page(self, a, b):
        p0, p1 = self._vers_page(*a), self._vers_page(*b)
        r = pymupdf.Rect(p0, p1)
        r.normalize()
        return r

    def choisir_image(self):
        if not self._doc_requis():
            return
        chemin = filedialog.askopenfilename(title="Choisir une image", filetypes=[
            ("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff"), ("Tous les fichiers", "*.*")])
        if chemin:
            self.image_a_placer = chemin
            self.outil.set("image")

    def _placer_image(self, a, b):
        if not self.image_a_placer:
            return self.choisir_image()
        self._avant_modif()
        page = self.doc[self.page_idx]
        try:
            page.insert_image(self._rect_page(a, b), filename=self.image_a_placer, keep_proportion=True,
                              rotate=page.rotation)
        except Exception as e:
            self.historique.pop()
            return messagebox.showerror("Image", f"Impossible d'insérer l'image :\n{e}")
        self._apres_modif()
        self.outil.set("selection")
        self.statut("Image ajoutée.")

    def choisir_signature(self):
        if not self._doc_requis():
            return
        r = PadSignature(self, "Signer le document").resultat
        if r:
            self.signature = r
            self.outil.set("signature")

    def _placer_signature(self, a, b):
        if not self.signature:
            return self.choisir_signature()
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        # garder les proportions de la signature dans le rectangle tracé
        l, h = x1 - x0, y1 - y0
        ratio = self.signature["ratio"]
        if l / h > ratio:
            x0 += (l - h * ratio) / 2
            l = h * ratio
        else:
            y0 += (h - l / ratio) / 2
            h = l / ratio
        self._avant_modif()
        page = self.doc[self.page_idx]
        forme = page.new_shape()
        for trait in self.signature["traits"]:
            points = [self._vers_page(x0 + u * l, y0 + v * h) for u, v in trait]
            forme.draw_polyline(points)
        forme.finish(color=(0.04, 0.16, 0.42), width=max(0.8, h / self.facteur / 40), closePath=False,
                     lineCap=1, lineJoin=1)
        forme.commit()
        self._apres_modif()
        self.outil.set("selection")
        self.statut("Signature ajoutée.")

    def _surligner(self):
        page = self.doc[self.page_idx]
        lignes = {}
        for m in self.selection:
            lignes.setdefault((m[5], m[6]), []).append(pymupdf.Rect(m[:4]))
        rects = []
        for rs in lignes.values():
            r = rs[0]
            for x in rs[1:]:
                r |= x
            rects.append(r)
        self._avant_modif()
        a = page.add_highlight_annot(rects)
        a.update()
        self._apres_modif()
        self.statut("Texte surligné.")

    def _commentaire(self, p):
        texte = simpledialog.askstring("Commentaire", "Texte du commentaire :", parent=self)
        if not texte:
            return
        self._avant_modif()
        a = self.doc[self.page_idx].add_text_annot(p, texte, icon="Comment")
        a.update()
        self._apres_modif()

    def _caviarder(self, a, b):
        if not messagebox.askyesno("Effacer la zone", "Tout le contenu de cette zone (texte, images, dessins) "
                                   "sera définitivement effacé. Continuer ?"):
            return
        self._avant_modif()
        page = self.doc[self.page_idx]
        page.add_redact_annot(self._rect_page(a, b), fill=(1, 1, 1))
        page.apply_redactions()
        self._apres_modif()
        self.statut("Zone effacée.")

    # ================================================ Rechercher/remplacer ==

    def afficher_recherche(self):
        if str(self.panneau_recherche) not in self.panneaux.panes():
            self.panneaux.add(self.panneau_recherche, weight=0)
        if self.selection and not self.var_cherche.get():
            self.var_cherche.set(" ".join(m[4] for m in self.selection))
        self.entree_cherche.focus_set()
        self.entree_cherche.select_range(0, "end")

    def masquer_recherche(self):
        if str(self.panneau_recherche) in self.panneaux.panes():
            self.panneaux.forget(self.panneau_recherche)
        self.resultats_recherche = []
        self.canvas.delete("resultat")

    def _occurrences(self, page, texte):
        rects = page.search_for(texte)
        if self.var_respecter_casse.get():
            rects = [r for r in rects if page.get_text("text", clip=r).strip() == texte]
        return rects

    def rechercher(self):
        if not self._doc_requis() or not self.var_cherche.get():
            return
        texte = self.var_cherche.get()
        pages = [self.page_idx] if self.var_portee.get() == "page" else range(self.doc.page_count)
        self.resultats_recherche = [(i, r) for i in pages for r in self._occurrences(self.doc[i], texte)]
        n = len(self.resultats_recherche)
        self.lbl_resultats.config(text=f"{n} résultat(s)" if n else "Aucun résultat")
        self.index_resultat = -1
        if n:
            self.resultat_suivant(1)
        else:
            self.canvas.delete("resultat")

    def resultat_suivant(self, sens):
        if not self.resultats_recherche:
            return self.rechercher()
        self.index_resultat = (self.index_resultat + sens) % len(self.resultats_recherche)
        i, _r = self.resultats_recherche[self.index_resultat]
        if i != self.page_idx:
            self.aller_page(i)
        self._dessiner_resultats()
        self.lbl_resultats.config(text=f"Résultat {self.index_resultat + 1} sur {len(self.resultats_recherche)}")

    def _dessiner_resultats(self):
        self.canvas.delete("resultat")
        for k, (i, r) in enumerate(self.resultats_recherche):
            if i == self.page_idx:
                x0, y0, x1, y1 = self._vers_canvas(r)
                actif = k == self.index_resultat
                self.canvas.create_rectangle(x0 - 2, y0 - 2, x1 + 2, y1 + 2, outline="#ff8c00",
                                             width=3 if actif else 1.5, tags="resultat")
                if actif:
                    h = float(self.canvas.cget("scrollregion").split()[3] or 1)
                    haut, bas = self.canvas.yview()
                    if not (haut * h < y0 < bas * h):
                        self.canvas.yview_moveto(max(0, (y0 - 120) / h))

    def remplacer_tout(self):
        if not self._doc_requis():
            return
        ancien, nouveau = self.var_cherche.get(), self.var_remplace.get()
        if not ancien:
            return messagebox.showinfo("Remplacer", "Indiquez le texte à rechercher.")
        pages = [self.page_idx] if self.var_portee.get() == "page" else list(range(self.doc.page_count))
        self._avant_modif()
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            res = pdftool.remplacer_texte(self.doc, ancien, nouveau, pages,
                                          ignorer_casse=not self.var_respecter_casse.get(),
                                          decaler=self.var_decaler.get())
        except Exception as e:
            self.historique.pop()
            return messagebox.showerror("Remplacer", str(e))
        finally:
            self.config(cursor="")
        if not res:
            self.historique.pop()
            self.lbl_resultats.config(text="Aucun résultat")
            return
        self.resultats_recherche = []
        self._apres_modif(pages=sorted({r["page"] - 1 for r in res}))
        polices_utilisees = sorted({r["police"] for r in res})
        self.lbl_resultats.config(text=f"{len(res)} remplacement(s)")
        self.statut(f"{len(res)} remplacement(s) — police : " + " ; ".join(polices_utilisees))
        if any("plus proche" in p for p in polices_utilisees):
            self._proposer_police()

    # ============================================================ Polices ==

    def _fenetre(self, titre, l, h):
        """Fenêtre secondaire centrée sur la fenêtre principale."""
        f = tk.Toplevel(self)
        f.title(titre)
        l, h = int(l * self.echelle_ui), int(h * self.echelle_ui)
        x = self.winfo_rootx() + (self.winfo_width() - l) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 3
        f.geometry(f"{l}x{h}+{max(0, x)}+{max(0, y)}")
        return f

    def fenetre_polices_document(self):
        if not self._doc_requis():
            return
        if not polices.INDEX.pret.is_set():
            return messagebox.showinfo("Polices", "La liste des polices est en cours de chargement…")
        f = self._fenetre("Polices du document", 760, 420)
        f.transient(self)
        ttk.Label(f, text="Polices utilisées dans ce document et leur disponibilité sur cet ordinateur.",
                  padding=10).pack(anchor="w")
        arbre = ttk.Treeview(f, columns=("police", "integree", "etat"), show="headings")
        for col, titre, l in [("police", "Police", 260), ("integree", "Dans le PDF", 140), ("etat", "Sur l'ordinateur", 320)]:
            arbre.heading(col, text=titre)
            arbre.column(col, width=int(l * self.echelle_ui))
        arbre.pack(fill="both", expand=True, padx=10)
        arbre.tag_configure("ok", foreground="#1f7a1f")
        arbre.tag_configure("ko", foreground="#b00020")
        arbre.tag_configure("moyen", foreground="#b25e00")

        def remplir():
            arbre.delete(*arbre.get_children())
            self._etats = polices.etat_polices_document(self.doc)
            for nom, integree, partielle, etat, detail, _x, _e in self._etats:
                dans = "non intégrée" if not integree else ("intégrée (partielle)" if partielle else "intégrée (complète)")
                texte, tag = {"installee": (f"✔ installée ({detail})", "ok"),
                              "standard": ("✔ police standard PDF", "ok"),
                              "equivalente": (f"≈ remplacée par {detail}", "moyen"),
                              "manquante": ("✖ manquante", "ko")}[etat]
                arbre.insert("", "end", values=(nom, dans, texte), tags=(tag,))
            self._verifier_polices()

        remplir()
        b = ttk.Frame(f, padding=10)
        b.pack(fill="x")
        prog = ttk.Label(b, text="")
        prog.pack(side="left")
        ttk.Button(b, text="Fermer", command=f.destroy).pack(side="right")
        ttk.Button(b, text="Ajouter un fichier de police…",
                   command=lambda: (self.ajouter_fichiers_police(), remplir())).pack(side="right", padx=6)
        bouton = ttk.Button(b, text="⬇ Installer les polices manquantes", style="Accent.TButton")
        bouton.pack(side="right")

        def installer():
            a_faire = [e for e in self._etats if e[3] in ("manquante", "equivalente")]
            if not a_faire:
                return prog.config(text="Toutes les polices sont déjà disponibles.")
            bouton.state(["disabled"])
            # Les polices complètes intégrées au PDF sont extraites (fil principal : accès au document)
            extraites = {}
            for nom, integree, partielle, _etat, _d, xref, ext in a_faire:
                if integree and not partielle and ext in ("ttf", "otf"):
                    try:
                        extraites[nom] = (self.doc.extract_font(xref)[3], ext)
                    except Exception:
                        pass

            def travail():
                ok, ko = [], []
                for nom, *_r in a_faire:
                    self.after(0, lambda n=nom: prog.config(text=f"Installation de {n}…"))
                    chemin = None
                    if nom in extraites:
                        donnees, ext = extraites[nom]
                        chemin, _ = polices.ajouter_octets(f"{nom}.{ext}", donnees)
                    else:
                        e = polices.INDEX.telecharger_google(nom, delai=15)
                        chemin = e and e["chemin"]
                    if chemin:
                        ok.append(nom)
                        if self.reglages["installer_windows"]:
                            try:
                                polices.installer_dans_windows(chemin)
                            except Exception:
                                pass
                    else:
                        ko.append(nom)
                self.after(0, lambda: fin(ok, ko))

            def fin(ok, ko):
                bouton.state(["!disabled"])
                remplir()
                self._polices_pretes()
                msg = f"{len(ok)} police(s) installée(s)."
                if ko:
                    msg += f"  Introuvables gratuitement : {', '.join(ko[:4])}{'…' if len(ko) > 4 else ''}"
                    msg += " — ajoutez leur fichier avec le bouton ci-contre."
                prog.config(text=msg)

            threading.Thread(target=travail, daemon=True).start()

        bouton.configure(command=installer)

    def fenetre_gestion_polices(self):
        f = self._fenetre("Gérer les polices", 640, 600)
        f.transient(self)
        polices.INDEX.attendre()
        familles = polices.INDEX.familles()
        haut = ttk.Frame(f, padding=10)
        haut.pack(fill="x")
        lbl = ttk.Label(haut, text=f"{len(familles)} familles de polices disponibles")
        lbl.pack(anchor="w")
        var_filtre = tk.StringVar()
        e = ttk.Entry(haut, textvariable=var_filtre)
        e.pack(fill="x", pady=(6, 0))
        liste = tk.Listbox(f, activestyle="none", font=("Segoe UI" if WINDOWS else "TkDefaultFont", 10))
        liste.pack(fill="both", expand=True, padx=10)

        def filtrer(*_):
            liste.delete(0, "end")
            t = var_filtre.get().lower()
            for fam in polices.INDEX.familles():
                if t in fam.lower():
                    liste.insert("end", fam)
        var_filtre.trace_add("write", filtrer)
        filtrer()

        b = ttk.Frame(f, padding=10)
        b.pack(fill="x")
        var_tele = tk.BooleanVar(value=self.reglages["telecharger"])
        var_win = tk.BooleanVar(value=self.reglages["installer_windows"])

        def maj_reglages():
            self.reglages["telecharger"] = pdftool.TELECHARGER_POLICES = var_tele.get()
            self.reglages["installer_windows"] = var_win.get()
            self._sauver_reglages()
        ttk.Checkbutton(b, text="Télécharger automatiquement les polices manquantes (Google Fonts)",
                        variable=var_tele, command=maj_reglages).pack(anchor="w")
        if WINDOWS:
            ttk.Checkbutton(b, text="Installer aussi les polices ajoutées dans Windows (Word, etc.)",
                            variable=var_win, command=maj_reglages).pack(anchor="w")
        boutons = ttk.Frame(b)
        boutons.pack(fill="x", pady=(10, 0))

        def apres():
            filtrer()
            lbl.config(text=f"{len(polices.INDEX.familles())} familles de polices disponibles")
            self._polices_pretes()

        ttk.Button(boutons, text="Ajouter des fichiers…",
                   command=lambda: (self.ajouter_fichiers_police(), apres())).pack(side="left")
        ttk.Button(boutons, text="Télécharger (Google Fonts)…",
                   command=lambda: (self.telecharger_police(), apres())).pack(side="left", padx=6)
        ttk.Button(boutons, text="Ouvrir le dossier", command=lambda: _ouvrir_dossier(polices.dossier_polices_perso())).pack(side="left")
        ttk.Button(boutons, text="Fermer", command=f.destroy).pack(side="right")

    def ajouter_fichiers_police(self):
        chemins = filedialog.askopenfilenames(title="Fichiers de police", filetypes=[
            ("Polices", "*.ttf *.otf *.ttc *.TTF *.OTF *.TTC"), ("Tous les fichiers", "*.*")])
        if not chemins:
            return
        ajoutees = polices.INDEX.ajouter_fichiers(chemins)
        if self.reglages["installer_windows"]:
            for c in {e["chemin"] for e in ajoutees}:
                try:
                    polices.installer_dans_windows(c)
                except Exception:
                    pass
        self._polices_pretes()
        self.statut(f"{len(ajoutees)} police(s) ajoutée(s).")

    def telecharger_police(self):
        nom = simpledialog.askstring("Google Fonts", "Nom de la police à télécharger (ex. Roboto, Open Sans, "
                                     "Montserrat Bold) :", parent=self)
        if not nom:
            return
        mots = nom.strip().split()
        style = ""
        if len(mots) > 1 and any(m.lower() in mots[-1].lower() for m, _ in polices.POIDS + [("italic", 0)]):
            style = mots.pop()
        self.config(cursor="watch")
        self.update()
        e = polices.INDEX.telecharger_google("".join(mots) + ("-" + style if style else ""), delai=15)
        self.config(cursor="")
        if e:
            if self.reglages["installer_windows"]:
                try:
                    polices.installer_dans_windows(e["chemin"])
                except Exception:
                    pass
            self._polices_pretes()
            messagebox.showinfo("Google Fonts", f"Police installée : {e['complet']}")
        else:
            messagebox.showwarning("Google Fonts", f"« {nom} » est introuvable sur Google Fonts\n"
                                   "(ou pas de connexion Internet).")

    # ============================================================== Divers ==

    def informations(self):
        if not self._doc_requis():
            return
        m = self.doc.metadata or {}
        r = self.doc[self.page_idx].rect
        lignes = [f"Fichier : {self.chemin}", f"Pages : {self.doc.page_count}",
                  f"Format de la page {self.page_idx + 1} : {r.width / 72 * 25.4:.0f} × {r.height / 72 * 25.4:.0f} mm"]
        for cle, nom in [("title", "Titre"), ("author", "Auteur"), ("subject", "Sujet"),
                         ("creator", "Créé avec"), ("producer", "Producteur")]:
            if m.get(cle):
                lignes.append(f"{nom} : {m[cle]}")
        messagebox.showinfo("Informations", "\n".join(lignes))

    def aide(self):
        messagebox.showinfo("Aide rapide", "\n".join([
            "• Ouvrir : bouton Ouvrir, Ctrl+O, ou glisser-déposer un PDF.",
            "• Modifier un texte : outil « Modifier le texte » (Ctrl+E), cliquez sur le texte, "
            "tapez, puis Entrée. Échap annule.",
            "  Double-cliquer sur un texte avec l'outil Sélection fonctionne aussi.",
            "• Changer la police, la taille, le gras, l'italique ou la couleur : barre de mise en forme.",
            "• Ajouter du texte : outil « Ajouter du texte » (Ctrl+T), cliquez sur la page.",
            "• Image / Signer : tracez un rectangle sur la page.",
            "• Pages : clic droit sur une miniature, ou glissez une miniature pour déplacer la page.",
            "• Rechercher / remplacer : Ctrl+F.",
            "• Annuler : Ctrl+Z — Rétablir : Ctrl+Y.",
            "• Enregistrer : Ctrl+S — Enregistrer sous : Ctrl+Maj+S.",
            "• Polices manquantes : Outils › Polices du document › Installer.",
        ]))


# --------------------------------------------------------------------------- #

def _hex_vers_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _ouvrir_dossier(chemin):
    if WINDOWS:
        os.startfile(chemin)
    elif sys.platform == "darwin":
        os.system(f'open "{chemin}"')
    else:
        os.system(f'xdg-open "{chemin}" &')


def main():
    app = Editeur(sys.argv[1] if len(sys.argv) > 1 else None)
    app.mainloop()


if __name__ == "__main__":
    main()
