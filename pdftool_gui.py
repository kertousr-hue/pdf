#!/usr/bin/env python3
"""Interface graphique de pdftool : lire et modifier des PDF.

Lancement :  python pdftool_gui.py [fichier.pdf]
"""

import os
import sys
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

import pymupdf

import pdftool

ZOOMS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0]
POLICES_STANDARD = {
    "Helvetica": "helv", "Helvetica gras": "hebo", "Helvetica italique": "heit",
    "Times": "tiro", "Times gras": "tibo", "Times italique": "tiit",
    "Courier": "cour", "Courier gras": "cobo",
}
MAX_ANNULATIONS = 30


# --------------------------------------------------------------------------- #
# Boîte de dialogue générique (formulaire)
# --------------------------------------------------------------------------- #

class Formulaire(simpledialog.Dialog):
    """champs : liste de (clé, libellé, valeur_défaut, type)
    type : "texte", "nombre", "motdepasse", "couleur", ("choix", [options])"""

    def __init__(self, parent, titre, champs, aide=None):
        self.champs, self.aide, self.resultat, self.vars = champs, aide, None, {}
        super().__init__(parent, titre)

    def body(self, cadre):
        ligne = 0
        if self.aide:
            ttk.Label(cadre, text=self.aide, wraplength=340, foreground="#555").grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
            ligne = 1
        premier = None
        for cle, libelle, defaut, typ in self.champs:
            ttk.Label(cadre, text=libelle).grid(row=ligne, column=0, sticky="w", padx=(0, 8), pady=3)
            var = tk.StringVar(value="" if defaut is None else str(defaut))
            self.vars[cle] = (var, typ)
            if isinstance(typ, tuple) and typ[0] == "choix":
                w = ttk.Combobox(cadre, textvariable=var, values=typ[1], state="readonly", width=28)
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
                w = ttk.Entry(cadre, textvariable=var, width=32, show="•" if typ == "motdepasse" else "")
            w.grid(row=ligne, column=1, sticky="we", pady=3)
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


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #

class Application(tk.Tk):
    def __init__(self, fichier=None):
        super().__init__()
        self.title("PDF Tool")
        self.geometry("1200x820")
        self.minsize(800, 500)

        self.doc = None
        self.chemin = None
        self.modifie = False
        self.page_idx = 0
        self.zoom = 1.25
        self.annulations = []
        self.image = None          # référence à la PhotoImage affichée
        self.mots = []             # mots de la page courante
        self.selection = []        # mots sélectionnés
        self.surlignes = []        # rectangles de recherche
        self.depart_glisser = None
        self.mode = tk.StringVar(value="selection")

        self._style()
        self._menus()
        self._barre_outils()
        self._corps()
        self._raccourcis()
        self.protocol("WM_DELETE_WINDOW", self.quitter)
        self._maj_etat()

        if fichier:
            self.after(50, lambda: self.ouvrir(fichier))

    # ------------------------------------------------------------------ UI --

    def _style(self):
        style = ttk.Style(self)
        if "clam" in style.theme_names() and sys.platform.startswith("linux"):
            style.theme_use("clam")
        style.configure("Titre.TLabel", font=("TkDefaultFont", 10, "bold"))
        style.configure("Valeur.TLabel", foreground="#1a4d8f")
        style.configure("Accent.TButton", font=("TkDefaultFont", 10, "bold"))

    def _menus(self):
        barre = tk.Menu(self)
        m = tk.Menu(barre, tearoff=False)
        m.add_command(label="Ouvrir…", accelerator="Ctrl+O", command=self.demander_ouvrir)
        m.add_command(label="Enregistrer", accelerator="Ctrl+S", command=self.enregistrer)
        m.add_command(label="Enregistrer sous…", accelerator="Ctrl+Maj+S", command=self.enregistrer_sous)
        m.add_separator()
        m.add_command(label="Ajouter un PDF à la fin (fusionner)…", command=self.fusionner)
        m.add_command(label="Exporter des pages…", command=self.exporter_pages)
        m.add_command(label="Exporter le texte…", command=self.exporter_texte)
        m.add_command(label="Enregistrer avec mot de passe…", command=self.chiffrer)
        m.add_separator()
        m.add_command(label="Quitter", command=self.quitter)
        barre.add_cascade(label="Fichier", menu=m)

        m = tk.Menu(barre, tearoff=False)
        m.add_command(label="Annuler", accelerator="Ctrl+Z", command=self.annuler)
        m.add_separator()
        m.add_command(label="Remplacer un texte", accelerator="Ctrl+F", command=self.focus_recherche)
        m.add_command(label="Ajouter du texte (cliquer sur la page)", command=lambda: self.mode.set("ajout"))
        m.add_command(label="Filigrane…", command=self.filigrane)
        m.add_command(label="Propriétés (titre, auteur…)…", command=self.metadonnees)
        barre.add_cascade(label="Édition", menu=m)

        m = tk.Menu(barre, tearoff=False)
        m.add_command(label="Pivoter la page à droite", accelerator="Ctrl+R", command=lambda: self.pivoter(90))
        m.add_command(label="Pivoter la page à gauche", command=lambda: self.pivoter(-90))
        m.add_command(label="Pivoter toutes les pages à droite", command=lambda: self.pivoter(90, toutes=True))
        m.add_separator()
        m.add_command(label="Supprimer la page", command=self.supprimer_page)
        m.add_command(label="Déplacer la page avant", command=lambda: self.deplacer_page(-1))
        m.add_command(label="Déplacer la page après", command=lambda: self.deplacer_page(1))
        barre.add_cascade(label="Pages", menu=m)

        m = tk.Menu(barre, tearoff=False)
        m.add_command(label="Polices du document…", command=self.fenetre_polices)
        m.add_command(label="Informations…", command=self.informations)
        barre.add_cascade(label="Outils", menu=m)
        self.config(menu=barre)

    def _barre_outils(self):
        b = ttk.Frame(self, padding=(6, 4))
        b.pack(side="top", fill="x")

        def bouton(texte, cmd, **kw):
            w = ttk.Button(b, text=texte, command=cmd, **kw)
            w.pack(side="left", padx=2)
            return w

        bouton("📂 Ouvrir", self.demander_ouvrir)
        self.btn_enreg = bouton("💾 Enregistrer", self.enregistrer)
        self.btn_annuler = bouton("↶ Annuler", self.annuler)
        ttk.Separator(b, orient="vertical").pack(side="left", fill="y", padx=8)

        bouton("◀", lambda: self.aller_page(self.page_idx - 1), width=3)
        self.var_page = tk.StringVar(value="")
        e = ttk.Entry(b, textvariable=self.var_page, width=5, justify="center")
        e.pack(side="left")
        e.bind("<Return>", self._saisie_page)
        self.lbl_total = ttk.Label(b, text="/ 0")
        self.lbl_total.pack(side="left", padx=(3, 3))
        bouton("▶", lambda: self.aller_page(self.page_idx + 1), width=3)
        ttk.Separator(b, orient="vertical").pack(side="left", fill="y", padx=8)

        bouton("−", lambda: self.changer_zoom(-1), width=3)
        self.lbl_zoom = ttk.Label(b, text="125 %", width=6, anchor="center")
        self.lbl_zoom.pack(side="left")
        bouton("+", lambda: self.changer_zoom(1), width=3)
        bouton("Largeur", self.zoom_largeur)
        ttk.Separator(b, orient="vertical").pack(side="left", fill="y", padx=8)

        bouton("⟳", lambda: self.pivoter(90), width=3)
        ttk.Radiobutton(b, text="Sélectionner le texte", variable=self.mode, value="selection",
                        command=self._changement_mode).pack(side="left", padx=(8, 2))
        ttk.Radiobutton(b, text="Ajouter du texte", variable=self.mode, value="ajout",
                        command=self._changement_mode).pack(side="left", padx=2)
        self.mode.trace_add("write", lambda *_: self._changement_mode())

    def _corps(self):
        panneaux = ttk.PanedWindow(self, orient="horizontal")
        panneaux.pack(fill="both", expand=True)

        # Zone d'affichage de la page
        zone = ttk.Frame(panneaux)
        self.canvas = tk.Canvas(zone, bg="#6b6f75", highlightthickness=0, cursor="xterm")
        sy = ttk.Scrollbar(zone, orient="vertical", command=self.canvas.yview)
        sx = ttk.Scrollbar(zone, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        zone.rowconfigure(0, weight=1)
        zone.columnconfigure(0, weight=1)
        panneaux.add(zone, weight=1)

        self.canvas.bind("<ButtonPress-1>", self._clic)
        self.canvas.bind("<B1-Motion>", self._glisser)
        self.canvas.bind("<ButtonRelease-1>", self._relacher)
        self.canvas.bind("<Configure>", lambda e: self._centrer())
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind(seq, self._molette)

        # Panneau latéral
        cote = ttk.Frame(panneaux, padding=8, width=340)
        panneaux.add(cote, weight=0)

        # -- Police du texte sélectionné
        f = ttk.LabelFrame(cote, text=" Texte sélectionné ", padding=8)
        f.pack(fill="x")
        self.info = {}
        for cle, lib in [("texte", "Texte"), ("police", "Police"), ("taille", "Taille"),
                         ("style", "Style"), ("couleur", "Couleur"), ("integree", "Intégrée")]:
            ligne = ttk.Frame(f)
            ligne.pack(fill="x", pady=1)
            ttk.Label(ligne, text=lib + " :", width=9).pack(side="left")
            if cle == "couleur":
                self.apercu_couleur = tk.Label(ligne, width=2, bg="#ffffff", relief="solid", bd=1)
                self.apercu_couleur.pack(side="left", padx=(0, 4))
            lbl = ttk.Label(ligne, text="—", style="Valeur.TLabel", wraplength=230)
            lbl.pack(side="left", fill="x")
            self.info[cle] = lbl
        ttk.Label(f, text="Cliquez sur un mot, ou glissez pour en sélectionner plusieurs.",
                  foreground="#777", wraplength=300).pack(fill="x", pady=(6, 0))

        # -- Remplacement
        f = ttk.LabelFrame(cote, text=" Remplacer un texte ", padding=8)
        f.pack(fill="x", pady=(10, 0))
        ttk.Label(f, text="Texte actuel :").pack(anchor="w")
        self.var_ancien = tk.StringVar()
        self.entree_ancien = ttk.Entry(f, textvariable=self.var_ancien)
        self.entree_ancien.pack(fill="x")
        self.entree_ancien.bind("<Return>", lambda e: self.rechercher())
        ttk.Label(f, text="Nouveau texte :").pack(anchor="w", pady=(6, 0))
        self.var_nouveau = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.var_nouveau)
        e.pack(fill="x")
        e.bind("<Return>", lambda ev: self.remplacer())

        self.var_portee = tk.StringVar(value="document")
        p = ttk.Frame(f)
        p.pack(fill="x", pady=(6, 0))
        ttk.Radiobutton(p, text="Tout le document", variable=self.var_portee, value="document").pack(side="left")
        ttk.Radiobutton(p, text="Cette page", variable=self.var_portee, value="page").pack(side="left", padx=8)
        self.var_decaler = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Décaler la suite de la ligne", variable=self.var_decaler).pack(
            anchor="w", pady=(4, 0))
        self.var_ajuster = tk.BooleanVar(value=False)
        self.var_casse = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Réduire la taille si le texte est plus long",
                        variable=self.var_ajuster).pack(anchor="w")
        ttk.Checkbutton(f, text="Ignorer majuscules / minuscules", variable=self.var_casse).pack(anchor="w")

        ttk.Label(f, text="Police (facultatif, .ttf / .otf) :").pack(anchor="w", pady=(6, 0))
        p = ttk.Frame(f)
        p.pack(fill="x")
        self.var_fichier_police = tk.StringVar()
        ttk.Entry(p, textvariable=self.var_fichier_police).pack(side="left", fill="x", expand=True)
        ttk.Button(p, text="…", width=3, command=self._choisir_police).pack(side="left", padx=(4, 0))

        p = ttk.Frame(f)
        p.pack(fill="x", pady=(8, 0))
        ttk.Button(p, text="Rechercher", command=self.rechercher).pack(side="left", expand=True, fill="x")
        ttk.Button(p, text="Remplacer", style="Accent.TButton", command=self.remplacer).pack(
            side="left", expand=True, fill="x", padx=(6, 0))

        # -- Journal
        f = ttk.LabelFrame(cote, text=" Journal ", padding=4)
        f.pack(fill="both", expand=True, pady=(10, 0))
        self.journal = tk.Text(f, height=8, width=40, wrap="word", state="disabled",
                               font=("TkDefaultFont", 9), relief="flat", bg="#f7f7f7")
        self.journal.pack(fill="both", expand=True)
        self.journal.tag_configure("ok", foreground="#1f7a1f")
        self.journal.tag_configure("attention", foreground="#b25e00")
        self.journal.tag_configure("erreur", foreground="#b00020")

        # -- Barre d'état
        self.statut = ttk.Label(self, text="Ouvrez un fichier PDF pour commencer (Ctrl+O).",
                                relief="sunken", anchor="w", padding=(6, 2))
        self.statut.pack(side="bottom", fill="x")

    def _raccourcis(self):
        ctrl = "Command" if sys.platform == "darwin" else "Control"
        self.bind(f"<{ctrl}-o>", lambda e: self.demander_ouvrir())
        self.bind(f"<{ctrl}-s>", lambda e: self.enregistrer())
        self.bind(f"<{ctrl}-S>", lambda e: self.enregistrer_sous())
        self.bind(f"<{ctrl}-z>", lambda e: self.annuler())
        self.bind(f"<{ctrl}-f>", lambda e: self.focus_recherche())
        self.bind(f"<{ctrl}-r>", lambda e: self.pivoter(90))
        self.bind(f"<{ctrl}-plus>", lambda e: self.changer_zoom(1))
        self.bind(f"<{ctrl}-equal>", lambda e: self.changer_zoom(1))
        self.bind(f"<{ctrl}-minus>", lambda e: self.changer_zoom(-1))
        self.bind("<Prior>", lambda e: self.aller_page(self.page_idx - 1))
        self.bind("<Next>", lambda e: self.aller_page(self.page_idx + 1))
        self.bind("<Escape>", lambda e: (self.mode.set("selection"), self._effacer_selection()))

    # ------------------------------------------------------------ Journal --

    def log(self, message, tag=None):
        self.journal.configure(state="normal")
        self.journal.insert("end", message + "\n", tag)
        self.journal.see("end")
        self.journal.configure(state="disabled")
        self.statut.config(text=message.split("\n")[0])

    # ----------------------------------------------------------- Fichiers --

    def demander_ouvrir(self):
        if not self._confirmer_abandon():
            return
        chemin = filedialog.askopenfilename(title="Ouvrir un PDF", filetypes=[("PDF", "*.pdf"), ("Tous", "*.*")])
        if chemin:
            self.ouvrir(chemin)

    def ouvrir(self, chemin):
        try:
            with open(chemin, "rb") as f:
                donnees = f.read()
            doc = pymupdf.open(stream=donnees, filetype="pdf")
        except Exception as e:
            messagebox.showerror("Ouverture impossible", f"{chemin}\n\n{e}")
            return
        if doc.needs_pass:
            while True:
                mdp = simpledialog.askstring("Mot de passe", "Ce PDF est protégé. Mot de passe :",
                                             show="•", parent=self)
                if mdp is None:
                    return
                if doc.authenticate(mdp):
                    break
                messagebox.showerror("Mot de passe", "Mot de passe incorrect.")
            # On travaille sur une copie déchiffrée
            doc = pymupdf.open(stream=doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE), filetype="pdf")
            self.log("PDF déchiffré. Utilisez « Enregistrer avec mot de passe » pour le protéger à nouveau.",
                     "attention")
        self.doc, self.chemin = doc, chemin
        self.annulations.clear()
        self.modifie = False
        self.page_idx = 0
        self.log(f"Ouvert : {os.path.basename(chemin)} ({doc.page_count} pages)", "ok")
        self.zoom_largeur()

    def enregistrer(self):
        if not self.doc:
            return
        if not self.chemin:
            return self.enregistrer_sous()
        self._ecrire(self.chemin)

    def enregistrer_sous(self):
        if not self.doc:
            return
        initial = os.path.splitext(os.path.basename(self.chemin or "document.pdf"))[0] + "_modifie.pdf"
        chemin = filedialog.asksaveasfilename(title="Enregistrer sous", defaultextension=".pdf",
                                              initialfile=initial, filetypes=[("PDF", "*.pdf")])
        if chemin:
            self._ecrire(chemin)
            self.chemin = chemin

    def _ecrire(self, chemin, **options):
        try:
            donnees = self.doc.tobytes(garbage=3, deflate=True, **options)
            with open(chemin, "wb") as f:
                f.write(donnees)
        except Exception as e:
            messagebox.showerror("Enregistrement impossible", str(e))
            return False
        if not options:
            self.modifie = False
        self.log(f"Enregistré : {chemin}", "ok")
        self._maj_etat()
        return True

    def fusionner(self):
        if not self._doc_requis():
            return
        chemins = filedialog.askopenfilenames(title="PDF à ajouter à la fin", filetypes=[("PDF", "*.pdf")])
        if not chemins:
            return
        self._sauvegarde_annulation()
        for c in chemins:
            try:
                with pymupdf.open(c) as autre:
                    self.doc.insert_pdf(autre)
                self.log(f"Ajouté : {os.path.basename(c)}", "ok")
            except Exception as e:
                self.log(f"Impossible d'ajouter {c} : {e}", "erreur")
        self._modification()

    def exporter_pages(self):
        if not self._doc_requis():
            return
        spec = simpledialog.askstring("Exporter des pages",
                                      f"Pages à exporter (ex. 1,3-5) — le document en a {self.doc.page_count} :",
                                      initialvalue=str(self.page_idx + 1), parent=self)
        if not spec:
            return
        try:
            pages = pdftool.parse_pages(spec, self.doc.page_count)
        except ValueError as e:
            return messagebox.showerror("Pages", str(e))
        chemin = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile="extrait.pdf",
                                              filetypes=[("PDF", "*.pdf")])
        if chemin:
            nouveau = pymupdf.open()
            for i in pages:
                nouveau.insert_pdf(self.doc, from_page=i, to_page=i)
            nouveau.save(chemin, garbage=3, deflate=True)
            self.log(f"{len(pages)} page(s) exportée(s) : {chemin}", "ok")

    def exporter_texte(self):
        if not self._doc_requis():
            return
        chemin = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="texte.txt",
                                              filetypes=[("Texte", "*.txt")])
        if chemin:
            with open(chemin, "w", encoding="utf-8") as f:
                for i, page in enumerate(self.doc):
                    f.write(f"===== Page {i + 1} =====\n{page.get_text()}\n")
            self.log(f"Texte exporté : {chemin}", "ok")

    def chiffrer(self):
        if not self._doc_requis():
            return
        r = Formulaire(self, "Protéger par mot de passe", [
            ("mdp", "Mot de passe :", "", "motdepasse"),
            ("mdp2", "Confirmer :", "", "motdepasse")],
            aide="Le fichier sera enregistré chiffré (AES-256).").resultat
        if not r:
            return
        if not r["mdp"] or r["mdp"] != r["mdp2"]:
            return messagebox.showerror("Mot de passe", "Les mots de passe sont vides ou différents.")
        chemin = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile="protege.pdf",
                                              filetypes=[("PDF", "*.pdf")])
        if chemin:
            self._ecrire(chemin, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                         user_pw=r["mdp"], owner_pw=r["mdp"])

    def quitter(self):
        if self._confirmer_abandon():
            self.destroy()

    def _confirmer_abandon(self):
        if self.doc and self.modifie:
            rep = messagebox.askyesnocancel("Modifications non enregistrées",
                                            "Enregistrer les modifications avant de continuer ?")
            if rep is None:
                return False
            if rep:
                self.enregistrer()
                return not self.modifie
        return True

    # ------------------------------------------------------- Modifications --

    def _doc_requis(self):
        if not self.doc:
            messagebox.showinfo("Aucun document", "Ouvrez d'abord un fichier PDF.")
            return False
        return True

    def _sauvegarde_annulation(self):
        self.annulations.append((self.doc.tobytes(), self.page_idx))
        del self.annulations[:-MAX_ANNULATIONS]

    def _modification(self):
        self.modifie = True
        self.page_idx = min(self.page_idx, self.doc.page_count - 1)
        self.afficher()

    def annuler(self):
        if not self.annulations:
            return
        donnees, self.page_idx = self.annulations.pop()
        self.doc = pymupdf.open(stream=donnees, filetype="pdf")
        self.modifie = True
        self.log("Dernière modification annulée.")
        self.afficher()

    def pivoter(self, angle, toutes=False):
        if not self._doc_requis():
            return
        self._sauvegarde_annulation()
        pages = range(self.doc.page_count) if toutes else [self.page_idx]
        for i in pages:
            p = self.doc[i]
            p.set_rotation((p.rotation + angle) % 360)
        self._modification()

    def supprimer_page(self):
        if not self._doc_requis():
            return
        if self.doc.page_count == 1:
            return messagebox.showinfo("Supprimer", "Impossible de supprimer la seule page du document.")
        if messagebox.askyesno("Supprimer", f"Supprimer la page {self.page_idx + 1} ?"):
            self._sauvegarde_annulation()
            self.doc.delete_page(self.page_idx)
            self.log(f"Page {self.page_idx + 1} supprimée.")
            self._modification()

    def deplacer_page(self, sens):
        if not self._doc_requis():
            return
        cible = self.page_idx + sens
        if not 0 <= cible < self.doc.page_count:
            return
        self._sauvegarde_annulation()
        # move_page(a, b) place la page a avant la page b ; b = -1 => à la fin
        if sens < 0:
            self.doc.move_page(self.page_idx, cible)
        else:
            self.doc.move_page(self.page_idx, cible + 1 if cible + 1 < self.doc.page_count else -1)
        self.page_idx = cible
        self._modification()

    def filigrane(self):
        if not self._doc_requis():
            return
        r = Formulaire(self, "Filigrane", [
            ("texte", "Texte :", "CONFIDENTIEL", "texte"),
            ("taille", "Taille :", 60, "nombre"),
            ("opacite", "Opacité (0 à 1) :", 0.3, "nombre"),
            ("couleur", "Couleur :", "#999999", "couleur"),
            ("portee", "Pages :", "Toutes", ("choix", ["Toutes", "Page courante"]))]).resultat
        if not r or not r["texte"]:
            return
        self._sauvegarde_annulation()
        couleur = _hex_vers_rgb(r["couleur"])
        pages = range(self.doc.page_count) if r["portee"] == "Toutes" else [self.page_idx]
        for i in pages:
            page = self.doc[i]
            rect = page.rect * page.derotation_matrix  # rectangle de la page non pivotée
            rect.normalize()
            centre = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
            largeur = pymupdf.get_text_length(r["texte"], fontname="hebo", fontsize=r["taille"])
            origine = centre + (-largeur / 2, r["taille"] / 3)
            angle = 45 + page.rotation
            page.insert_text(origine, r["texte"], fontname="hebo", fontsize=r["taille"], color=couleur,
                             fill_opacity=max(0, min(1, r["opacite"])),
                             morph=(centre, pymupdf.Matrix(angle)))
        self.log(f"Filigrane « {r['texte']} » ajouté.", "ok")
        self._modification()

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
            self._sauvegarde_annulation()
            m.update(r)
            self.doc.set_metadata(m)
            self.log("Propriétés mises à jour.", "ok")
            self._modification()

    def ajouter_texte(self, point_page):
        r = Formulaire(self, "Ajouter du texte", [
            ("texte", "Texte :", "", "texte"),
            ("police", "Police :", "Helvetica", ("choix", list(POLICES_STANDARD))),
            ("taille", "Taille :", 12, "nombre"),
            ("couleur", "Couleur :", "#000000", "couleur")],
            aide="Le texte sera placé à l'endroit cliqué (début de la ligne de base).").resultat
        if not r or not r["texte"]:
            return
        self._sauvegarde_annulation()
        page = self.doc[self.page_idx]
        page.insert_text(point_page, r["texte"], fontname=POLICES_STANDARD[r["police"]],
                         fontsize=r["taille"], color=_hex_vers_rgb(r["couleur"]), rotate=page.rotation)
        self.log(f"Texte ajouté p.{self.page_idx + 1} : « {r['texte']} »", "ok")
        self._modification()

    # -------------------------------------------------------- Remplacement --

    def focus_recherche(self):
        self.entree_ancien.focus_set()
        self.entree_ancien.select_range(0, "end")

    def _choisir_police(self):
        c = filedialog.askopenfilename(title="Fichier de police",
                                       filetypes=[("Polices", "*.ttf *.otf *.TTF *.OTF"), ("Tous", "*.*")])
        if c:
            self.var_fichier_police.set(c)

    def _pages_portee(self):
        return [self.page_idx] if self.var_portee.get() == "page" else list(range(self.doc.page_count))

    def _occurrences(self, page, texte):
        rects = page.search_for(texte)
        if not self.var_casse.get():
            rects = [r for r in rects if page.get_text("text", clip=r).strip() == texte]
        return rects

    def rechercher(self):
        if not self._doc_requis():
            return
        texte = self.var_ancien.get()
        if not texte:
            return
        compte = {i: len(self._occurrences(self.doc[i], texte)) for i in self._pages_portee()}
        total = sum(compte.values())
        if not total:
            self.log(f"« {texte} » introuvable.", "attention")
            self.surlignes = []
            self._dessiner_surlignes()
            return
        pages = [i for i, n in compte.items() if n]
        if self.page_idx not in pages:
            self.aller_page(pages[0])
        self.surlignes = self._occurrences(self.doc[self.page_idx], texte)
        self._dessiner_surlignes()
        self.log(f"« {texte} » : {total} occurrence(s), page(s) " + ", ".join(str(i + 1) for i in pages))

    def remplacer(self):
        if not self._doc_requis():
            return
        ancien, nouveau = self.var_ancien.get(), self.var_nouveau.get()
        if not ancien:
            return messagebox.showinfo("Remplacer", "Indiquez le texte à remplacer "
                                       "(ou cliquez sur un mot dans la page).")
        fichier_police = self.var_fichier_police.get().strip() or None
        if fichier_police and not os.path.isfile(fichier_police):
            return messagebox.showerror("Police", f"Fichier introuvable :\n{fichier_police}")
        self._sauvegarde_annulation()
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            res = pdftool.remplacer_texte(self.doc, ancien, nouveau, self._pages_portee(),
                                          ajuster=self.var_ajuster.get(),
                                          ignorer_casse=self.var_casse.get(),
                                          fichier_police=fichier_police,
                                          decaler=self.var_decaler.get())
        except Exception as e:
            self.annulations.pop()
            self.log(f"Erreur : {e}", "erreur")
            return
        finally:
            self.config(cursor="")
        if not res:
            self.annulations.pop()
            self.log(f"« {ancien} » introuvable : rien n'a été remplacé.", "attention")
            return
        self.log(f"{len(res)} remplacement(s) : « {ancien} » → « {nouveau} »", "ok")
        polices = sorted({(r["police"], round(r["taille"], 1)) for r in res})
        for police, taille in polices:
            tag = "attention" if "plus proche" in police else None
            self.log(f"   police : {police}, {taille} pt", tag)
        if any(r["decale"] for r in res):
            self.log("   suite de la ligne décalée")
        raisons = {r["raison"] for r in res if r["deborde"]}
        if raisons:
            detail = " ; ".join(x for x in raisons if x)
            self.log("   attention : le nouveau texte est plus long et peut chevaucher la suite"
                     + (f" (non décalée : {detail})" if detail else "")
                     + ". Cochez « Réduire la taille ».", "attention")
        self.surlignes = []
        self._modification()

    # ---------------------------------------------------------- Affichage --

    def _maj_etat(self):
        nom = os.path.basename(self.chemin) if self.chemin else "PDF Tool"
        self.title(("• " if self.modifie else "") + nom + (" — PDF Tool" if self.chemin else ""))
        n = self.doc.page_count if self.doc else 0
        self.var_page.set(str(self.page_idx + 1) if n else "")
        self.lbl_total.config(text=f"/ {n}")
        self.lbl_zoom.config(text=f"{round(self.zoom * 100)} %")
        self.btn_annuler.state(["!disabled"] if self.annulations else ["disabled"])
        self.btn_enreg.state(["!disabled"] if self.doc else ["disabled"])

    def afficher(self):
        self._maj_etat()
        self.canvas.delete("all")
        if not self.doc:
            return
        page = self.doc[self.page_idx]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(self.zoom, self.zoom), alpha=False)
        self.image = tk.PhotoImage(data=pix.tobytes("ppm"))
        self.canvas.create_rectangle(4, 4, pix.width + 4, pix.height + 4, fill="#3d4044", outline="",
                                     tags="page")
        self.canvas.create_image(0, 0, image=self.image, anchor="nw", tags="page")
        self.mots = page.get_text("words")
        self.selection = []
        self._centrer()
        self._dessiner_surlignes()

    def _centrer(self):
        if not self.image:
            return
        w, h = self.image.width(), self.image.height()
        cw = self.canvas.winfo_width()
        self.decalage = (max(20, (cw - w) // 2), 20)
        bbox = self.canvas.bbox("page")
        if bbox:
            self.canvas.move("all", self.decalage[0] - bbox[0], self.decalage[1] - bbox[1])
        self.canvas.configure(scrollregion=(0, 0, max(cw, w + 40), h + 40))

    # Conversions de coordonnées : page (non pivotée, points) <-> canvas
    def _vers_canvas(self, rect):
        page = self.doc[self.page_idx]
        r = pymupdf.Rect(rect) * page.rotation_matrix * self.zoom
        r.normalize()
        dx, dy = self.decalage
        return r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy

    def _vers_page(self, x, y):
        page = self.doc[self.page_idx]
        dx, dy = self.decalage
        p = pymupdf.Point((self.canvas.canvasx(x) - dx) / self.zoom, (self.canvas.canvasy(y) - dy) / self.zoom)
        return p * page.derotation_matrix

    def _dessiner_surlignes(self):
        self.canvas.delete("surligne")
        if not self.doc:
            return
        for r in self.surlignes:
            x0, y0, x1, y1 = self._vers_canvas(r)
            self.canvas.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1, outline="#ff8c00", width=2,
                                         tags="surligne")

    def aller_page(self, idx):
        if self.doc and 0 <= idx < self.doc.page_count and idx != self.page_idx:
            self.page_idx = idx
            self.surlignes = []
            self.afficher()
            self.canvas.yview_moveto(0)

    def _saisie_page(self, _):
        try:
            self.aller_page(int(self.var_page.get()) - 1)
        except ValueError:
            pass
        self._maj_etat()

    def changer_zoom(self, sens):
        proches = [z for z in ZOOMS if (z > self.zoom + 0.01 if sens > 0 else z < self.zoom - 0.01)]
        if proches:
            self.zoom = min(proches) if sens > 0 else max(proches)
            self.afficher()

    def zoom_largeur(self):
        if not self.doc:
            return
        self.update_idletasks()
        largeur_page = self.doc[self.page_idx].rect.width
        dispo = max(200, self.canvas.winfo_width() - 60)
        self.zoom = max(0.3, min(4.0, dispo / largeur_page))
        self.afficher()

    def _molette(self, e):
        haut = e.num == 4 or getattr(e, "delta", 0) > 0
        if e.state & 0x4:  # Ctrl + molette = zoom
            self.changer_zoom(1 if haut else -1)
            return
        self.canvas.yview_scroll(-3 if haut else 3, "units")

    # ---------------------------------------------------------- Sélection --

    def _changement_mode(self):
        self.canvas.config(cursor="crosshair" if self.mode.get() == "ajout" else "xterm")
        if self.mode.get() == "ajout":
            self.statut.config(text="Cliquez sur la page à l'endroit où ajouter le texte (Échap pour annuler).")

    def _clic(self, e):
        if not self.doc:
            return
        if self.mode.get() == "ajout":
            self.mode.set("selection")
            self.ajouter_texte(self._vers_page(e.x, e.y))
            return
        self.depart_glisser = (e.x, e.y)
        self._selectionner(self._vers_page(e.x, e.y), self._vers_page(e.x, e.y))

    def _glisser(self, e):
        if self.depart_glisser and self.mode.get() == "selection":
            self._selectionner(self._vers_page(*self.depart_glisser), self._vers_page(e.x, e.y))

    def _relacher(self, _):
        self.depart_glisser = None
        if self.selection:
            self._afficher_police()

    def _selectionner(self, a, b):
        zone = pymupdf.Rect(a, b)
        zone.normalize()
        if zone.is_empty:  # simple clic : mot sous le curseur
            zone = pymupdf.Rect(a.x - 0.5, a.y - 0.5, a.x + 0.5, a.y + 0.5)
        self.selection = [m for m in self.mots if pymupdf.Rect(m[:4]).intersects(zone)]
        self.canvas.delete("selection")
        for m in self.selection:
            x0, y0, x1, y1 = self._vers_canvas(m[:4])
            self.canvas.create_rectangle(x0, y0, x1, y1, outline="#1a73e8", width=2, tags="selection")

    def _effacer_selection(self):
        self.selection = []
        self.canvas.delete("selection")

    def _afficher_police(self):
        mots = sorted(self.selection, key=lambda m: (m[5], m[6], m[7]))  # bloc, ligne, mot
        texte = " ".join(m[4] for m in mots)
        self.var_ancien.set(texte)
        self.var_nouveau.set(texte)

        page = self.doc[self.page_idx]
        r = pymupdf.Rect(mots[0][:4])
        spans = [s for b in page.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
        span = max(spans, key=lambda s: (pymupdf.Rect(s["bbox"]) & r).get_area(), default=None)
        if not span:
            return
        gras, ita = pdftool.style_span(span)
        style = " + ".join(s for s, ok in (("gras", gras), ("italique", ita)) if ok) or "normal"
        integree = "?"
        for _x, ext, typ, base, *_ in page.get_fonts(full=True):
            if pdftool.nom_lisible(base) == span["font"]:
                integree = f"non ({typ})" if ext == "n/a" else f"oui ({ext}" + (
                    ", partielle)" if base != span["font"] else ")")
                break
        couleur = pdftool.couleur_hex(span["color"])
        self.info["texte"].config(text=texte if len(texte) < 80 else texte[:77] + "…")
        self.info["police"].config(text=span["font"])
        self.info["taille"].config(text=f"{span['size']:.1f} pt")
        self.info["style"].config(text=style)
        self.info["couleur"].config(text=couleur)
        self.apercu_couleur.config(bg=couleur)
        self.info["integree"].config(text=integree)
        self.statut.config(text=f"« {texte} » — {span['font']}, {span['size']:.1f} pt, {style}")

    # --------------------------------------------------------- Fenêtres --

    def fenetre_polices(self):
        if not self._doc_requis():
            return
        f = tk.Toplevel(self)
        f.title("Polices du document")
        f.geometry("820x480")
        onglets = ttk.Notebook(f)
        onglets.pack(fill="both", expand=True, padx=8, pady=8)

        cadre = ttk.Frame(onglets)
        onglets.add(cadre, text="Polices")
        arbre = ttk.Treeview(cadre, columns=("nom", "type", "integree", "pages"), show="headings")
        for col, titre, l in [("nom", "Police", 280), ("type", "Type", 90), ("integree", "Intégrée", 160),
                              ("pages", "Pages", 200)]:
            arbre.heading(col, text=titre)
            arbre.column(col, width=l)
        arbre.pack(fill="both", expand=True)
        vues = {}
        for i, page in enumerate(self.doc):
            for _x, ext, typ, base, *_ in page.get_fonts(full=True):
                vues.setdefault((base, typ, ext), set()).add(i + 1)
        for (base, typ, ext), pages in sorted(vues.items()):
            nom = pdftool.nom_lisible(base)
            integ = "non" if ext == "n/a" else f"oui ({ext}" + (", partielle)" if nom != base else ")")
            arbre.insert("", "end", values=(nom, typ, integ, _resumer_pages(pages)))

        cadre = ttk.Frame(onglets)
        onglets.add(cadre, text="Détail par texte")
        arbre = ttk.Treeview(cadre, columns=("page", "police", "taille", "style", "couleur", "texte"),
                             show="headings")
        for col, titre, l in [("page", "Page", 50), ("police", "Police", 200), ("taille", "Taille", 60),
                              ("style", "Style", 90), ("couleur", "Couleur", 80), ("texte", "Texte", 320)]:
            arbre.heading(col, text=titre)
            arbre.column(col, width=l, stretch=col == "texte")
        sb = ttk.Scrollbar(cadre, orient="vertical", command=arbre.yview)
        arbre.configure(yscrollcommand=sb.set)
        arbre.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for i, page in enumerate(self.doc):
            for b in page.get_text("dict")["blocks"]:
                for l in b.get("lines", []):
                    for s in l["spans"]:
                        if s["text"].strip():
                            gras, ita = pdftool.style_span(s)
                            style = " + ".join(x for x, ok in (("gras", gras), ("italique", ita)) if ok) or "normal"
                            arbre.insert("", "end", values=(i + 1, s["font"], f"{s['size']:.1f}", style,
                                                            pdftool.couleur_hex(s["color"]), s["text"].strip()))

    def informations(self):
        if not self._doc_requis():
            return
        m = self.doc.metadata or {}
        r = self.doc[self.page_idx].rect
        lignes = [f"Fichier : {self.chemin}", f"Pages : {self.doc.page_count}",
                  f"Taille de la page {self.page_idx + 1} : {r.width:.0f} × {r.height:.0f} pt "
                  f"({r.width / 72 * 25.4:.0f} × {r.height / 72 * 25.4:.0f} mm)"]
        for cle, nom in [("title", "Titre"), ("author", "Auteur"), ("subject", "Sujet"),
                         ("creator", "Créateur"), ("producer", "Producteur")]:
            if m.get(cle):
                lignes.append(f"{nom} : {m[cle]}")
        messagebox.showinfo("Informations", "\n".join(lignes))


# --------------------------------------------------------------------------- #

def _hex_vers_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _resumer_pages(pages):
    pages = sorted(pages)
    plages, debut = [], pages[0]
    for a, b in zip(pages, pages[1:] + [None]):
        if b != a + 1:
            plages.append(str(debut) if debut == a else f"{debut}-{a}")
            debut = b
    return ", ".join(plages)


def main():
    app = Application(sys.argv[1] if len(sys.argv) > 1 else None)
    app.mainloop()


if __name__ == "__main__":
    main()
