/* PDF Éditeur (PWA) — lien entre l'interface (app.js) et le moteur Python (moteur.js).
 * Chargé avant app.js : app.js utilise window.MOTEUR_PWA à la place du serveur.
 */
"use strict";

(function () {
  // ---------------------------------------------------------------- écran de chargement
  const ecran = document.createElement("div");
  ecran.id = "chargement-pwa";
  ecran.innerHTML = `<div class="carte-chargement">
      <img src="icone-192.png" alt="" width="72" height="72">
      <h1>PDF Éditeur</h1>
      <p id="chargement-etape">Démarrage…</p>
      <div class="barre"><div id="chargement-barre"></div></div>
      <p class="discret" id="chargement-note">Le premier lancement télécharge l'application (environ 45 Mo).
      Ensuite, elle s'ouvre en quelques secondes, même sans Internet.</p>
    </div>`;
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(ecran));

  function etape(texte, pourcent) {
    const e = document.getElementById("chargement-etape"), b = document.getElementById("chargement-barre");
    if (e) e.textContent = texte;
    if (b) b.style.width = `${pourcent}%`;
  }

  // ---------------------------------------------------------------- moteur (Web Worker)
  const attentes = new Map();
  let compteur = 0;
  let resoudrePret, rejeterPret, moteur;
  const pret = new Promise((ok, ko) => { resoudrePret = ok; rejeterPret = ko; });

  /** Le service worker doit contrôler la page avant le démarrage du moteur : ainsi les gros
   *  fichiers (Python, PyMuPDF…) sont gardés pour la suite dès leur premier téléchargement. */
  async function attendreServiceWorker() {
    if (!("serviceWorker" in navigator) || location.protocol === "file:") return;
    try {
      await navigator.serviceWorker.register("sw.js");
      if (navigator.serviceWorker.controller) return;
      await Promise.race([
        new Promise((ok) => navigator.serviceWorker.addEventListener("controllerchange", ok, { once: true })),
        new Promise((ok) => setTimeout(ok, 8000)),
      ]);
    } catch (_) { /* sans service worker : l'application marche, mais pas hors ligne */ }
  }

  attendreServiceWorker().then(() => {
    moteur = new Worker("moteur.js");
    moteur.onmessage = recevoir;
  });

  function recevoir(e) {
    const m = e.data;
    if (m.type === "progression") etape(m.etape, m.pourcent);
    else if (m.type === "pret") { ecran.remove(); resoudrePret(); }
    else if (m.type === "erreur_demarrage") {
      etape("Impossible de démarrer l'application : " + m.message, 100);
      document.getElementById("chargement-note").textContent =
        "Vérifiez la connexion Internet (nécessaire au premier lancement), puis rechargez la page.";
      rejeterPret(new Error(m.message));
    } else if (m.type === "reponse") {
      const a = attentes.get(m.id);
      attentes.delete(m.id);
      if (a) a(new Response(m.corps, { status: m.statut, headers: m.entetes }));
    }
  }

  /** Équivalent de fetch() vers le serveur, mais traité par le moteur local. */
  async function requete(url, options = {}) {
    await pret;
    const req = new Request(new URL(url, location.href), options);
    const corps = ["GET", "HEAD"].includes(req.method) ? null : await req.arrayBuffer();
    const u = new URL(req.url);
    return new Promise((ok) => {
      const id = ++compteur;
      attentes.set(id, ok);
      moteur.postMessage({ type: "requete", id, methode: req.method, url: u.pathname.replace(/^.*?\/api\//, "/api/") + u.search,
                           typeContenu: req.headers.get("Content-Type"), corps }, corps ? [corps] : []);
    });
  }

  // ---------------------------------------------------------------- reconnaissance de texte
  let tesseract = null;

  function chargerScript(src) {
    return new Promise((ok, ko) => {
      const s = document.createElement("script");
      s.src = src; s.onload = ok; s.onerror = () => ko(new Error("Chargement impossible : " + src));
      document.head.appendChild(s);
    });
  }

  async function lecteur(langues, suivi) {
    if (!window.Tesseract) await chargerScript("ocr/tesseract.min.js");
    if (tesseract && tesseract.langues === langues.join("+")) return tesseract.w;
    if (tesseract) await tesseract.w.terminate();
    const w = await Tesseract.createWorker(langues, 1, {
      workerPath: new URL("ocr/worker.min.js", location.href).href,
      corePath: new URL("ocr/", location.href).href,
      langPath: new URL("ocr/", location.href).href,
      gzip: false,
      logger: (m) => m.status === "recognizing text" && suivi && suivi(m.progress),
    });
    tesseract = { w, langues: langues.join("+") };
    return w;
  }

  /** Lit le texte des pages scannées et le pose (invisible) sur le PDF. Renvoie l'état du document. */
  async function ocr(idDoc, pages, langues, afficher) {
    const disponibles = ["fra", "eng"];
    langues = langues.filter((l) => disponibles.includes(l));
    if (!langues.length) langues = ["fra"];
    afficher("Préparation de la lecture du texte…");
    const resultats = [];
    for (let k = 0; k < pages.length; k++) {
      const n = pages[k];
      const echelle = 220 / 72; // 220 ppp : bon compromis précision / rapidité sur téléphone
      const w = await lecteur(langues, (p) => afficher(`Lecture de la page ${n + 1} (${k + 1} sur ${pages.length})… ${Math.round(p * 100)} %`));
      afficher(`Lecture de la page ${n + 1} (${k + 1} sur ${pages.length})…`);
      const image = await (await requete(`/api/doc/${idDoc}/page/${n}.png?e=${echelle}&ocr=1`)).blob();
      const { data } = await w.recognize(image, {}, { blocks: true, text: false });
      const mots = [];
      for (const bloc of data.blocks || []) {
        for (const par of bloc.paragraphs || []) {
          for (const ligne of par.lines || []) {
            const b = ligne.baseline || {};
            for (const mot of ligne.words || []) {
              const t = (mot.text || "").trim();
              if (!t || mot.confidence < 20) continue;
              const x0 = mot.bbox.x0, x1 = mot.bbox.x1;
              const cx = (x0 + x1) / 2;
              let base = mot.bbox.y1;
              if (b.has_baseline !== false && b.x1 > b.x0) base = b.y0 + (b.y1 - b.y0) * (cx - b.x0) / (b.x1 - b.x0);
              const haut = Math.min(ligne.bbox.y0, mot.bbox.y0);
              const taille = Math.max(2, 0.9 * (base - haut) / 0.73 / echelle);
              mots.push({ texte: t, bbox: [x0 / echelle, mot.bbox.y0 / echelle, x1 / echelle, mot.bbox.y1 / echelle],
                          base: base / echelle, taille });
            }
          }
        }
      }
      resultats.push({ page: n, mots });
    }
    afficher("Mise en place du texte…");
    const r = await requete(`/api/doc/${idDoc}/ocr_mots`, { method: "POST", headers: { "Content-Type": "application/json" },
                                                          body: JSON.stringify({ pages: resultats }) });
    const infos = await r.json();
    if (!r.ok) throw new Error(infos.erreur || "Erreur de reconnaissance");
    return infos;
  }

  window.MOTEUR_PWA = { requete, ocr, pret };

  // ---------------------------------------------------------------- installation et hors ligne
  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    let dejaControlee = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (!dejaControlee) { dejaControlee = true; return; } // première installation
      const s = document.getElementById("statut");
      if (s) s.textContent = "Une mise à jour de l'application a été installée : elle sera utilisée au prochain lancement.";
    });
  }

  let invitation = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    invitation = e;
    document.querySelectorAll("[data-installer]").forEach((b) => (b.hidden = false));
  });
  window.addEventListener("appinstalled", () => {
    invitation = null;
    document.querySelectorAll("[data-installer]").forEach((b) => (b.hidden = true));
  });

  document.addEventListener("DOMContentLoaded", () => {
    // dans le navigateur : PDF et photos (la conversion de documents Word demande la version Windows)
    const intro = document.querySelector(".carte-accueil > p");
    if (intro) intro.textContent = "Ouvrez un PDF ou une photo de document pour le lire, le modifier et le télécharger. Vos fichiers restent sur cet appareil.";
    const choix = document.getElementById("f-ouvrir");
    if (choix) choix.accept = ".pdf,image/*";
    // bouton « Installer l'application » sur l'accueil et dans le menu Fichier
    const boutons = document.querySelector(".boutons-accueil");
    const menu = document.getElementById("menu-fichier");
    const accueil = Object.assign(document.createElement("button"), { className: "grand", textContent: "Installer l'application" });
    const entree = Object.assign(document.createElement("button"), { textContent: "Installer l'application" });
    for (const b of [accueil, entree]) {
      b.dataset.installer = "";
      b.hidden = true;
      b.addEventListener("click", async () => {
        if (!invitation) return;
        invitation.prompt();
        await invitation.userChoice;
        invitation = null;
        document.querySelectorAll("[data-installer]").forEach((x) => (x.hidden = true));
      });
    }
    if (boutons) boutons.appendChild(accueil);
    if (menu) menu.insertBefore(entree, menu.firstChild);
    // iPhone / iPad : pas d'invitation automatique, on explique comment faire
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) && !navigator.standalone;
    if (ios && boutons) {
      const p = document.createElement("p");
      p.className = "discret";
      p.textContent = "Pour installer l'application : touchez Partager, puis « Sur l'écran d'accueil ».";
      boutons.after(p);
    }
  });
})();
