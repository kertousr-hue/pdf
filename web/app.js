/* PDF Éditeur — interface web.
 * Le serveur (app_web.py) fait tout le travail sur le PDF ; cette page affiche les pages
 * (images rendues par le serveur) et envoie les modifications. Les coordonnées échangées sont
 * en points PDF, dans le sens d'affichage de la page.
 */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const PT_EN_PX = 96 / 72;
const STANDARD = ["Helvetica", "Times", "Courier"];

const etat = {
  doc: null,            // infos du document (id, pages, version…)
  page: 0,
  zoom: localStorage.getItem("zoom") || "largeur",
  echelle: 1,           // pixels CSS par point
  outil: "selection",
  contenu: null,        // textes, mots, champs de la page affichée
  edition: null,        // saisie en cours sur la page
  resultats: [], iRes: -1,
  config: {},
  modifie: false,
  imageAPlacer: null,
  signature: null,
  glisser: null,
};

// --------------------------------------------------------------------------
// Utilitaires
// --------------------------------------------------------------------------

function statut(t) { $("#statut").textContent = t; }

function attente(texte) {
  if (texte === false) { $("#attente").hidden = true; return; }
  $("#attente-texte").textContent = texte || "Patientez…";
  $("#attente").hidden = false;
}

async function api(url, options = {}, texteAttente = null) {
  if (texteAttente) attente(texteAttente);
  try {
    const o = { ...options };
    if (o.json !== undefined) {
      o.method = o.method || "POST";
      o.headers = { "Content-Type": "application/json" };
      o.body = JSON.stringify(o.json);
      delete o.json;
    }
    const r = await fetch(url, o);
    const type = r.headers.get("Content-Type") || "";
    const donnees = type.includes("json") ? await r.json() : await r.blob();
    if (!r.ok) throw new Error((donnees && donnees.erreur) || `Erreur ${r.status}`);
    return donnees;
  } finally {
    if (texteAttente) attente(false);
  }
}

async function essayer(fn) {
  try { return await fn(); }
  catch (e) { attente(false); await alerte("Erreur", e.message || String(e)); }
}

function urlDoc(chemin = "") { return `/api/doc/${etat.doc.id}${chemin}`; }

function telechargerBlob(blob, nom) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = nom;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
}

function echapper(t) { const d = document.createElement("div"); d.textContent = t; return d.innerHTML; }

// --------------------------------------------------------------------------
// Boîtes de dialogue
// --------------------------------------------------------------------------

/** champs : [{cle, libelle, type: texte|nombre|motdepasse|couleur|choix|case|info, valeur, choix}] */
function formulaire(titre, champs, { aide = "", ok = "OK", annuler = "Annuler" } = {}) {
  return new Promise((resolve) => {
    const dlg = $("#dlg"), f = $("#dlg-form");
    let html = `<h2>${echapper(titre)}</h2>`;
    if (aide) html += `<p class="discret">${aide}</p>`;
    for (const c of champs) {
      const id = `dlg-${c.cle}`;
      if (c.type === "info") { html += `<div>${c.html}</div>`; continue; }
      if (c.type === "case") {
        html += `<label class="case"><input type="checkbox" id="${id}" ${c.valeur ? "checked" : ""}> ${echapper(c.libelle)}</label>`;
        continue;
      }
      let entree;
      if (c.type === "choix") {
        entree = `<select id="${id}">${c.choix.map(([v, l]) => `<option value="${echapper(String(v))}" ${String(v) === String(c.valeur) ? "selected" : ""}>${echapper(l)}</option>`).join("")}</select>`;
      } else {
        const t = { nombre: "number", motdepasse: "password", couleur: "color" }[c.type] || "text";
        entree = `<input id="${id}" type="${t}" step="any" value="${echapper(String(c.valeur ?? ""))}">`;
      }
      html += `<label class="champ-dlg"><span>${echapper(c.libelle)}</span>${entree}</label>`;
    }
    html += `<div class="actions">${annuler ? `<button value="annuler">${annuler}</button>` : ""}<button value="ok" class="principal">${ok}</button></div>`;
    f.innerHTML = html;
    dlg.onclose = () => {
      if (dlg.returnValue !== "ok") return resolve(null);
      const res = {};
      for (const c of champs) {
        const el = $(`#dlg-${c.cle}`);
        if (!el) continue;
        res[c.cle] = c.type === "case" ? el.checked : c.type === "nombre" ? parseFloat(el.value) : el.value;
      }
      resolve(res);
    };
    dlg.returnValue = "";
    dlg.showModal();
    const premier = f.querySelector("input, select");
    if (premier) premier.focus();
  });
}

const alerte = (titre, texte) => formulaire(titre, [{ type: "info", html: echapper(texte).replace(/\n/g, "<br>") }], { annuler: "" });
async function confirmer(titre, texte, ok = "Oui", annuler = "Non") {
  return (await formulaire(titre, [{ type: "info", html: echapper(texte).replace(/\n/g, "<br>") }], { ok, annuler })) !== null;
}

// --------------------------------------------------------------------------
// Ouvrir, télécharger
// --------------------------------------------------------------------------

async function envoyerFichiers(fichiers, motDePasse = null) {
  const fd = new FormData();
  for (const f of fichiers) fd.append("fichiers", f, f.name);
  if (motDePasse) fd.append("mot_de_passe", motDePasse);
  const infos = await api("/api/ouvrir", { method: "POST", body: fd },
    [...fichiers].some((f) => !/\.pdf$/i.test(f.name)) ? "Conversion en PDF…" : "Ouverture…");
  if (infos.mot_de_passe_requis) {
    const r = await formulaire("Document protégé", [{ cle: "mdp", libelle: "Mot de passe", type: "motdepasse" }],
      { aide: infos.erreur || `${echapper(infos.nom || "Ce document")} est protégé par un mot de passe.` });
    if (r) return envoyerFichiers(fichiers, r.mdp);
    return null;
  }
  return infos;
}

async function ouvrirFichiers(fichiers) {
  if (!fichiers || !fichiers.length) return;
  if (!(await confirmerAbandon())) return;
  await essayer(async () => {
    const infos = await envoyerFichiers(fichiers);
    if (!infos) return;
    if (etat.doc) fetch(urlDoc(), { method: "DELETE" });
    etat.doc = null;
    etat.page = 0;
    etat.modifie = [...fichiers].some((f) => !/\.pdf$/i.test(f.name));
    nouveauDocument(infos);
    statut(`${infos.nom} : ${infos.pages.length} page(s).`);
    // photo d'un document : lecture du texte directement
    if ([...fichiers].every((f) => f.type.startsWith("image/")) && infos.scannees.length) await lancerOcr(false);
  });
}

async function telecharger(motDePasse = null) {
  if (!etat.doc) return;
  fermerEdition(true);
  await essayer(async () => {
    const blob = await api(urlDoc("/telecharger"), { json: motDePasse ? { mdp: motDePasse } : {} }, "Préparation du fichier…");
    telechargerBlob(blob, `${etat.doc.nom || "document"}${motDePasse ? " (protégé)" : ""}.pdf`);
    if (!motDePasse) etat.modifie = false;
    statut("Fichier téléchargé.");
  });
}

async function confirmerAbandon() {
  if (!etat.doc || !etat.modifie) return true;
  return confirmer("Modifications non téléchargées", "Le document a été modifié et n'a pas été téléchargé.\nContinuer quand même ?", "Continuer", "Annuler");
}

// --------------------------------------------------------------------------
// Document et affichage
// --------------------------------------------------------------------------

function nouveauDocument(infos) {
  etat.doc = infos;
  etat.page = Math.min(etat.page, infos.pages.length - 1);
  etat.resultats = [];
  $("#accueil").hidden = true;
  $("#feuille").hidden = false;
  document.title = `${infos.nom} — PDF Éditeur`;
  construireVignettes();
  majEtat();
  afficherPage();
}

function majDocument(infos, pagesTouchees = null) {
  const structure = !etat.doc || infos.pages.length !== etat.doc.pages.length;
  etat.doc = infos;
  etat.modifie = true;
  etat.page = Math.min(etat.page, infos.pages.length - 1);
  if (structure || pagesTouchees === "toutes") construireVignettes();
  else majVignettes(pagesTouchees ?? [etat.page]);
  majEtat();
  return afficherPage();
}

function majEtat() {
  const d = etat.doc;
  $("#b-annuler").disabled = !d || !d.annuler;
  $("#b-retablir").disabled = !d || !d.retablir;
  $$("[data-doc], .outil[data-outil]").forEach((b) => (b.disabled = !d));
  $("#p-total").textContent = `/ ${d ? d.pages.length : 0}`;
  $("#p-num").value = d ? etat.page + 1 : "";
  $$(".outil[data-outil]").forEach((b) => b.classList.toggle("choisi", b.dataset.outil === etat.outil));
  majBandeau();
}

function majBandeau() {
  const d = etat.doc, b = $("#bandeau");
  if (d && d.scannees.length && !etat.bandeauFerme) {
    $("#bandeau-texte").textContent = "Ce document est scanné : son texte est une image. Lancez la reconnaissance de texte pour pouvoir le modifier, le rechercher et le copier.";
    $("#bandeau-bouton").textContent = "Reconnaître le texte (OCR)";
    $("#bandeau-bouton").onclick = () => lancerOcr(true);
    b.hidden = false;
  } else if (d && d.formulaire && etat.outil !== "formulaire" && !etat.bandeauFerme) {
    $("#bandeau-texte").textContent = "Ce document contient un formulaire à remplir.";
    $("#bandeau-bouton").textContent = "Remplir le formulaire";
    $("#bandeau-bouton").onclick = () => { etat.bandeauFerme = true; choisirOutil("formulaire"); };
    b.hidden = false;
  } else b.hidden = true;
}

function calculerEchelle() {
  const p = etat.doc.pages[etat.page], vue = $("#vue");
  const largeur = vue.clientWidth - 48, hauteur = vue.clientHeight - 48;
  if (etat.zoom === "largeur") return Math.max(0.2, largeur / p.l);
  if (etat.zoom === "page") return Math.max(0.2, Math.min(largeur / p.l, hauteur / p.h));
  return parseFloat(etat.zoom) * PT_EN_PX;
}

async function afficherPage() {
  if (!etat.doc) return;
  fermerEdition(true);
  const p = etat.doc.pages[etat.page];
  etat.echelle = calculerEchelle();
  const f = $("#feuille");
  f.style.width = `${p.l * etat.echelle}px`;
  f.style.height = `${p.h * etat.echelle}px`;
  const resolution = etat.echelle * (window.devicePixelRatio || 1);
  const img = $("#image-page");
  img.src = urlDoc(`/page/${etat.page}.png?e=${resolution.toFixed(3)}&v=${etat.doc.version}`);
  $("#p-num").value = etat.page + 1;
  $$(".vignette").forEach((v, i) => v.classList.toggle("active", i === etat.page));
  const v = $$(".vignette")[etat.page];
  if (v) v.scrollIntoView({ block: "nearest" });
  $("#calque").innerHTML = "";
  etat.contenu = null;
  const page = etat.page, version = etat.doc.version;
  try {
    const c = await api(urlDoc(`/page/${page}/contenu`));
    if (page !== etat.page || version !== etat.doc.version) return;
    etat.contenu = c;
    dessinerCalque();
  } catch (e) { statut(e.message); }
}

function px(v) { return `${v * etat.echelle}px`; }

function placer(el, b) {
  el.style.left = px(b[0]); el.style.top = px(b[1]);
  el.style.width = px(b[2] - b[0]); el.style.height = px(b[3] - b[1]);
  return el;
}

function dessinerCalque() {
  const calque = $("#calque");
  calque.querySelectorAll(".boite, .champ, .resultat, .mot-sel").forEach((e) => e.remove());
  calque.className = { edition: "edition", texte: "texte", image: "dessin", signature: "dessin", caviarder: "dessin", champ: "dessin" }[etat.outil] || "";
  const c = etat.contenu;
  if (!c) return;
  if (etat.outil === "edition") {
    for (const s of c.spans) calque.appendChild(placer(Object.assign(document.createElement("div"), { className: "boite" }), s.bbox));
  }
  if (etat.outil === "formulaire" || etat.outil === "selection" || etat.outil === "champ") {
    for (const ch of c.champs) {
      const d = placer(document.createElement("div"), ch.bbox);
      d.className = "champ";
      d.title = ch.nom;
      if (etat.outil === "selection") d.style.background = "transparent", d.style.borderColor = "transparent";
      d.addEventListener("pointerdown", (e) => { e.stopPropagation(); e.preventDefault(); remplirChamp(ch); });
      calque.appendChild(d);
    }
  }
  etat.resultats.forEach((r, i) => {
    if (r.page !== etat.page) return;
    const d = placer(document.createElement("div"), r.bbox);
    d.className = "resultat" + (i === etat.iRes ? " actif" : "");
    calque.appendChild(d);
  });
}

function allerPage(n) {
  if (!etat.doc || n < 0 || n >= etat.doc.pages.length || n === etat.page) return;
  etat.page = n;
  afficherPage();
  $("#vue").scrollTop = 0;
}

// --------------------------------------------------------------------------
// Miniatures
// --------------------------------------------------------------------------

function urlVignette(i) {
  const p = etat.doc.pages[i];
  return urlDoc(`/page/${i}.png?e=${((120 / p.l) * (window.devicePixelRatio || 1)).toFixed(3)}&v=${etat.doc.version}`);
}

function construireVignettes() {
  const z = $("#vignettes");
  z.innerHTML = "";
  etat.doc.pages.forEach((p, i) => {
    const v = document.createElement("div");
    v.className = "vignette" + (i === etat.page ? " active" : "");
    v.draggable = true;
    v.innerHTML = `<img loading="lazy" alt="Page ${i + 1}" style="aspect-ratio:${p.l}/${p.h}" src="${urlVignette(i)}"><div class="num">${i + 1}</div>`;
    v.addEventListener("click", () => allerPage(i));
    v.addEventListener("contextmenu", (e) => { e.preventDefault(); allerPage(i); menuPage(e.clientX, e.clientY, i); });
    v.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/x-page", String(i)); });
    v.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("text/x-page")) { e.preventDefault(); v.classList.add("cible"); } });
    v.addEventListener("dragleave", () => v.classList.remove("cible"));
    v.addEventListener("drop", (e) => {
      v.classList.remove("cible");
      const de = parseInt(e.dataTransfer.getData("text/x-page"), 10);
      if (!Number.isNaN(de) && de !== i) { e.preventDefault(); e.stopPropagation(); actionPages("deplacer", de, { vers: i }); }
    });
    z.appendChild(v);
  });
}

function majVignettes(pages) {
  const vs = $$(".vignette img");
  for (const i of pages) if (vs[i]) vs[i].src = urlVignette(i);
}

function menuPage(x, y, i) {
  const m = $("#menu-contexte");
  m.innerHTML = "";
  const elements = [
    ["Pivoter à droite", () => actionPages("pivoter", i, { angle: 90 })],
    ["Pivoter à gauche", () => actionPages("pivoter", i, { angle: -90 })],
    ["Insérer une page blanche après", () => actionPages("blanche", i)],
    ["Insérer un fichier après…", () => { etat.fusionApres = i; $("#f-fusion").click(); }],
    ["Monter", () => actionPages("deplacer", i, { vers: i - 1 })],
    ["Descendre", () => actionPages("deplacer", i, { vers: i + 1 })],
    ["Supprimer la page", () => supprimerPage(i)],
  ];
  for (const [t, f] of elements) {
    const b = document.createElement("button");
    b.textContent = t;
    b.onclick = () => { m.hidden = true; f(); };
    m.appendChild(b);
  }
  m.style.left = `${Math.min(x, innerWidth - 270)}px`;
  m.style.top = `${Math.min(y, innerHeight - 300)}px`;
  m.hidden = false;
}

async function actionPages(action, page, extra = {}) {
  await essayer(async () => {
    const infos = await api(urlDoc("/pages"), { json: { action, page, ...extra } });
    if (action === "deplacer") etat.page = extra.vers;
    if (action === "blanche") etat.page = page + 1;
    majDocument(infos, action === "pivoter" ? [page] : "toutes");
  });
}

async function supprimerPage(i = etat.page) {
  if (!etat.doc) return;
  if (await confirmer("Supprimer la page", `Supprimer la page ${i + 1} ?`)) actionPages("supprimer", i);
}

// --------------------------------------------------------------------------
// Outils et souris
// --------------------------------------------------------------------------

const AIDES = {
  selection: "Cliquez sur un mot pour voir sa police. Double-cliquez sur un texte pour le modifier.",
  edition: "Cliquez sur un texte pour le modifier. Entrée pour valider, Échap pour annuler.",
  texte: "Cliquez sur la page à l'endroit où écrire.",
  image: "Tracez un rectangle sur la page pour placer l'image.",
  signature: "Tracez un rectangle sur la page pour placer la signature.",
  surligner: "Glissez sur le texte à surligner.",
  note: "Cliquez sur la page pour ajouter une note.",
  formulaire: "Cliquez sur un champ pour le remplir. Tab passe au champ suivant.",
  caviarder: "Tracez un rectangle : tout son contenu sera définitivement effacé.",
  champ: "Tracez un rectangle pour créer un champ de formulaire.",
};

function choisirOutil(o) {
  fermerEdition(true);
  etat.outil = o;
  $("#format").hidden = !(o === "edition" || o === "texte");
  majEtat();
  dessinerCalque();
  statut(AIDES[o] || "");
}

function pointPt(e) {
  const r = $("#calque").getBoundingClientRect();
  return [(e.clientX - r.left) / etat.echelle, (e.clientY - r.top) / etat.echelle];
}

function dans(b, x, y, marge = 0) { return x >= b[0] - marge && x <= b[2] + marge && y >= b[1] - marge && y <= b[3] + marge; }

function spanA(x, y) {
  const c = etat.contenu;
  if (!c) return null;
  return c.spans.find((s) => dans(s.bbox, x, y)) || c.spans.find((s) => dans(s.bbox, x, y, 3)) || null;
}

function motsDans(a, b) {
  const x0 = Math.min(a[0], b[0]), x1 = Math.max(a[0], b[0]), y0 = Math.min(a[1], b[1]), y1 = Math.max(a[1], b[1]);
  return (etat.contenu?.mots || []).filter((m) => m[0] <= x1 && m[2] >= x0 && m[1] <= y1 && m[3] >= y0);
}

function montrerSelection(mots) {
  $$("#calque .mot-sel").forEach((e) => e.remove());
  for (const m of mots) $("#calque").appendChild(Object.assign(placer(document.createElement("div"), m), { className: "mot-sel" }));
}

function cadre(a, b, danger = false) {
  let d = $("#calque .cadre");
  if (!d) { d = document.createElement("div"); $("#calque").appendChild(d); }
  d.className = "cadre" + (danger ? " danger" : "");
  placer(d, [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])]);
}

const calque = $("#calque");
calque.addEventListener("pointerdown", (e) => {
  if (!etat.doc || e.button !== 0 || e.target.closest(".saisie")) return;
  e.preventDefault(); // sinon le navigateur retire le focus de la zone de saisie qu'on va ouvrir
  const [x, y] = pointPt(e);
  const o = etat.outil;
  if (etat.edition) { fermerEdition(true); if (o === "texte") return; }
  if (o === "edition") {
    const s = spanA(x, y);
    if (s) ouvrirEdition(s);
    else if (etat.contenu?.scannee) proposerOcr();
    return;
  }
  if (o === "texte") return ouvrirAjout(x, y);
  if (o === "note") return ajouterNote(x, y);
  etat.glisser = [x, y];
  calque.setPointerCapture(e.pointerId);
  if (o === "selection" || o === "surligner") montrerSelection(motsDans([x, y], [x, y]));
});

calque.addEventListener("pointermove", (e) => {
  if (!etat.glisser) return;
  const p = pointPt(e), o = etat.outil;
  if (o === "selection" || o === "surligner") montrerSelection(motsDans(etat.glisser, p));
  else if (["image", "signature", "caviarder", "champ"].includes(o)) cadre(etat.glisser, p, o === "caviarder");
});

calque.addEventListener("pointerup", (e) => {
  if (!etat.glisser) return;
  const a = etat.glisser, b = pointPt(e), o = etat.outil;
  etat.glisser = null;
  $("#calque .cadre")?.remove();
  if (o === "selection") return infosSelection(motsDans(a, b));
  if (o === "surligner") return surligner(motsDans(a, b));
  if (["image", "signature", "caviarder", "champ"].includes(o)) {
    const r = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
    if ((r[2] - r[0]) * etat.echelle < 8 || (r[3] - r[1]) * etat.echelle < 8) return statut("Tracez un rectangle plus grand (cliquez et faites glisser).");
    ({ image: placerImage, signature: placerSignature, caviarder, champ: creerChamp })[o](r);
  }
});

calque.addEventListener("dblclick", (e) => {
  if (etat.outil !== "selection") return;
  const [x, y] = pointPt(e);
  const s = spanA(x, y);
  if (s) { choisirOutil("edition"); ouvrirEdition(spanA(x, y)); }
});

function infosSelection(mots) {
  if (!mots.length) { montrerSelection([]); return; }
  const texte = mots.map((m) => m[4]).join(" ");
  const m = mots[0];
  const s = etat.contenu.spans.find((s) => dans(s.bbox, (m[0] + m[2]) / 2, (m[1] + m[3]) / 2));
  $("#r-cherche").value = texte;
  if (!s) return statut(`« ${texte} »`);
  if (s.scan) return statut(`« ${texte} » — texte scanné (Modifier pour identifier sa police)`);
  const style = [s.gras && "gras", s.italique && "italique"].filter(Boolean).join(" ") || "normal";
  statut(`« ${texte.slice(0, 60)} » — Police : ${s.police}   Taille : ${s.taille} pt   Style : ${style}   Couleur : ${s.couleur}`);
}

// --------------------------------------------------------------------------
// Modification du texte sur la page
// --------------------------------------------------------------------------

function formatCourant() {
  return {
    police: $("#f-police").value.trim() || "Helvetica",
    taille: parseFloat($("#f-taille").value) || 12,
    gras: $("#f-gras").classList.contains("actif"),
    italique: $("#f-italique").classList.contains("actif"),
    couleur: $("#f-couleur").value,
  };
}

function reglerFormat(f) {
  $("#f-police").value = f.police;
  $("#f-taille").value = Math.round(f.taille * 10) / 10;
  $("#f-gras").classList.toggle("actif", !!f.gras);
  $("#f-italique").classList.toggle("actif", !!f.italique);
  $("#f-couleur").value = f.couleur || "#000000";
}

function styleSaisie(el, f) {
  el.style.fontFamily = `"${f.police}", ${/times|serif|roman|georgia|garamond|cambria/i.test(f.police) && !/sans/i.test(f.police) ? "serif" : /courier|mono/i.test(f.police) ? "monospace" : "sans-serif"}`;
  el.style.fontSize = `${f.taille * etat.echelle}px`;
  el.style.fontWeight = f.gras ? "bold" : "normal";
  el.style.fontStyle = f.italique ? "italic" : "normal";
  el.style.color = f.couleur;
}

function memeFormat(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

async function ouvrirEdition(s) {
  let format, fond = "#ffffff";
  if (s.scan) {
    statut("Analyse du texte scanné (police, taille, couleurs)…");
    let g;
    try { g = await api(urlDoc("/analyse"), { json: { page: etat.page, bbox: s.bbox, texte: s.texte } }); }
    catch (e) { return statut(e.message); }
    format = { police: g.famille, taille: g.taille, gras: g.gras, italique: false, couleur: g.couleur };
    fond = g.fond;
    $("#f-origine").textContent = `Texte scanné — police estimée : ${g.libelle}`;
    statut(AIDES.edition);
  } else {
    format = { police: s.famille, taille: s.taille, gras: s.gras, italique: s.italique, couleur: s.couleur };
    $("#f-origine").textContent = `Police d'origine : ${s.police}`;
  }
  reglerFormat(format);
  const el = document.createElement("input");
  el.className = "saisie";
  el.value = s.texte;
  placer(el, s.bbox);
  el.style.width = `${Math.max((s.bbox[2] - s.bbox[0]) * etat.echelle + 60, 160)}px`;
  el.style.background = fond;
  styleSaisie(el, format);
  $("#calque").appendChild(el);
  el.focus();
  el.setSelectionRange(el.value.length, el.value.length);
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); fermerEdition(true); }
    if (e.key === "Escape") { e.preventDefault(); fermerEdition(false); }
  });
  etat.edition = { type: "modif", span: s, el, texte: s.texte, format: formatCourant() };
}

function ouvrirAjout(x, y) {
  const f = formatCourant();
  const el = document.createElement("input");
  el.className = "saisie";
  el.placeholder = "Votre texte";
  el.style.left = px(x); el.style.top = px(y);
  el.style.width = "300px";
  styleSaisie(el, f);
  $("#calque").appendChild(el);
  el.focus();
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); fermerEdition(true); }
    if (e.key === "Escape") { e.preventDefault(); fermerEdition(false); }
  });
  $("#f-origine").textContent = "";
  etat.edition = { type: "ajout", x, y, el };
}

function fermerEdition(valider) {
  const ed = etat.edition;
  if (!ed) return;
  etat.edition = null;
  const valeur = ed.el.value;
  ed.el.remove();
  if (!valider) return;
  if (ed.type === "champ") return ed.valider(valeur);
  if (ed.type === "ajout") {
    if (!valeur.trim()) return;
    essayer(async () => {
      const infos = await api(urlDoc("/ajouter_texte"), { json: { page: etat.page, x: ed.x, y: ed.y, texte: valeur, style: formatCourant() } });
      majDocument(infos);
      statut(`Texte ajouté : « ${valeur} »`);
    });
    return;
  }
  const f = formatCourant(), s = ed.span;
  const formatChange = !memeFormat(f, ed.format);
  if (valeur === ed.texte && !formatChange) return;
  let style = null;
  if (s.scan) style = f; // police estimée (ou choisie) : toujours transmise
  else if (formatChange) {
    style = {};
    if (f.police !== ed.format.police || f.gras !== ed.format.gras || f.italique !== ed.format.italique)
      Object.assign(style, { police: f.police, gras: f.gras, italique: f.italique });
    if (f.taille !== ed.format.taille) style.taille = f.taille;
    if (f.couleur !== ed.format.couleur) style.couleur = f.couleur;
  }
  essayer(async () => {
    const infos = await api(urlDoc("/modifier_texte"), {
      json: { page: etat.page, bbox: s.bbox, texte: valeur, style, scan: s.scan, decaler: $("#f-decaler").checked },
    }, "Modification…");
    majDocument(infos);
    const r = infos.resultat;
    if (r) statut(`Texte modifié — police : ${r.police}${r.deborde ? "  ⚠ plus long : peut chevaucher la suite" : ""}`);
    if (r && /plus proche/.test(r.police)) proposerPolices();
  });
}

function changementFormat() {
  const ed = etat.edition;
  if (ed && ed.type !== "champ") styleSaisie(ed.el, formatCourant());
}
["#f-police", "#f-taille", "#f-couleur"].forEach((s) => $(s).addEventListener("input", changementFormat));
["#f-gras", "#f-italique"].forEach((s) => $(s).addEventListener("pointerdown", (e) => {
  e.preventDefault(); // garder la saisie active
  $(s).classList.toggle("actif");
  changementFormat();
}));

// --------------------------------------------------------------------------
// Autres outils
// --------------------------------------------------------------------------

async function ajouterNote(x, y) {
  const r = await formulaire("Ajouter une note", [{ cle: "texte", libelle: "Texte de la note", type: "texte" }]);
  if (!r || !r.texte) return;
  await essayer(async () => majDocument(await api(urlDoc("/annotation"), { json: { type: "note", page: etat.page, x, y, texte: r.texte } })));
}

async function surligner(mots) {
  montrerSelection([]);
  if (!mots.length) return;
  // un rectangle par ligne
  const lignes = [];
  for (const m of mots) {
    const l = lignes.find((l) => Math.abs((l[1] + l[3]) / 2 - (m[1] + m[3]) / 2) < (m[3] - m[1]) / 2);
    if (l) { l[0] = Math.min(l[0], m[0]); l[1] = Math.min(l[1], m[1]); l[2] = Math.max(l[2], m[2]); l[3] = Math.max(l[3], m[3]); }
    else lignes.push(m.slice(0, 4));
  }
  await essayer(async () => majDocument(await api(urlDoc("/annotation"), { json: { type: "surligner", page: etat.page, rects: lignes } })));
}

async function caviarder(r) {
  if (!(await confirmer("Effacer la zone", "Tout le contenu de cette zone (texte, images, dessins) sera définitivement effacé. Continuer ?"))) return;
  await essayer(async () => majDocument(await api(urlDoc("/annotation"), { json: { type: "caviarder", page: etat.page, bbox: r } })));
}

async function placerImage(r) {
  if (!etat.imageAPlacer) return $("#f-image").click();
  const fd = new FormData();
  fd.append("image", etat.imageAPlacer);
  fd.append("page", etat.page);
  fd.append("bbox", r.join(","));
  await essayer(async () => {
    majDocument(await api(urlDoc("/image"), { method: "POST", body: fd }, "Ajout de l'image…"));
    choisirOutil("selection");
    statut("Image ajoutée.");
  });
}

// signature dessinée
const pad = $("#pad"), ctx = pad.getContext("2d");
let traits = [], trait = null;
function padPoint(e) { const r = pad.getBoundingClientRect(); return [(e.clientX - r.left) * pad.width / r.width, (e.clientY - r.top) * pad.height / r.height]; }
pad.addEventListener("pointerdown", (e) => { pad.setPointerCapture(e.pointerId); trait = [padPoint(e)]; traits.push(trait); });
pad.addEventListener("pointermove", (e) => {
  if (!trait) return;
  const p = padPoint(e), q = trait[trait.length - 1];
  ctx.beginPath(); ctx.moveTo(q[0], q[1]); ctx.lineTo(p[0], p[1]); ctx.stroke();
  trait.push(p);
});
pad.addEventListener("pointerup", () => (trait = null));
function effacerPad() {
  ctx.clearRect(0, 0, pad.width, pad.height);
  ctx.strokeStyle = "#ddd"; ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.moveTo(20, 160); ctx.lineTo(500, 160); ctx.stroke();
  ctx.setLineDash([]); ctx.strokeStyle = "#0b2a6b"; ctx.lineWidth = 2.5; ctx.lineCap = "round";
  traits = [];
}
$("#pad-effacer").addEventListener("click", effacerPad);

function demanderSignature() {
  return new Promise((resolve) => {
    const dlg = $("#dlg-signature");
    effacerPad();
    dlg.onclose = () => {
      const ts = traits.filter((t) => t.length > 1);
      if (dlg.returnValue !== "ok" || !ts.length) return resolve(null);
      const xs = ts.flat().map((p) => p[0]), ys = ts.flat().map((p) => p[1]);
      const x0 = Math.min(...xs), y0 = Math.min(...ys);
      const l = Math.max(Math.max(...xs) - x0, 1), h = Math.max(Math.max(...ys) - y0, 1);
      resolve({ traits: ts.map((t) => t.map(([x, y]) => [(x - x0) / l, (y - y0) / h])), ratio: l / h });
    };
    dlg.returnValue = "";
    dlg.showModal();
  });
}

async function placerSignature(r) {
  if (!etat.signature) return;
  await essayer(async () => {
    majDocument(await api(urlDoc("/signature"), { json: { page: etat.page, bbox: r, ...etat.signature } }));
    choisirOutil("selection");
    statut("Signature ajoutée.");
  });
}

// --------------------------------------------------------------------------
// Formulaires
// --------------------------------------------------------------------------

async function envoyerChamp(ch, valeur) {
  await essayer(async () => {
    const infos = await api(urlDoc("/champ"), { json: { page: etat.page, xref: ch.xref, valeur } });
    await majDocument(infos); // attendre la page à jour (pour passer au champ suivant)
  });
}

async function remplirChamp(ch) {
  fermerEdition(true);
  const off = (v) => v === "Off" || v === "" || v === false || v === null || v === "False";
  if (ch.type === "CheckBox") return envoyerChamp(ch, off(ch.valeur));
  if (ch.type === "RadioButton") return envoyerChamp(ch, true);
  if (ch.type === "Signature") {
    const sig = await demanderSignature();
    if (sig) { etat.signature = sig; await placerSignature(ch.bbox); }
    return;
  }
  if (ch.type === "ComboBox" || ch.type === "ListBox") {
    const sel = document.createElement("select");
    sel.className = "saisie";
    sel.innerHTML = ch.choix.map((c) => `<option ${c === ch.valeur ? "selected" : ""}>${echapper(c)}</option>`).join("");
    placer(sel, ch.bbox);
    $("#calque").appendChild(sel);
    sel.focus();
    if (sel.showPicker) try { sel.showPicker(); } catch (_) { /* navigateur sans showPicker */ }
    const fin = () => { if (sel.isConnected) { sel.remove(); etat.edition = null; if (sel.value !== ch.valeur) envoyerChamp(ch, sel.value); } };
    sel.addEventListener("change", fin);
    sel.addEventListener("blur", fin);
    etat.edition = { type: "champ", el: sel, valider: () => {} };
    return;
  }
  // texte
  const el = document.createElement(ch.multiligne ? "textarea" : "input");
  el.className = "saisie";
  el.value = ch.valeur || "";
  placer(el, ch.bbox);
  el.style.fontSize = `${(ch.taille || Math.max(8, Math.min(14, (ch.bbox[3] - ch.bbox[1]) * 0.65))) * etat.echelle}px`;
  el.style.fontFamily = "Arial, Helvetica, sans-serif";
  $("#calque").appendChild(el);
  el.focus();
  const valider = async (valeur, sens = 0) => {
    if (valeur !== (ch.valeur || "")) await envoyerChamp(ch, valeur);
    if (sens) {
      // champ de texte suivant / précédent
      const textes = (etat.contenu?.champs || []).filter((c) => c.type === "Text")
        .sort((a, b) => Math.round(a.bbox[1]) - Math.round(b.bbox[1]) || a.bbox[0] - b.bbox[0]);
      const i = textes.findIndex((c) => c.xref === ch.xref);
      const suivant = textes[i + sens];
      if (suivant) remplirChamp(suivant);
    }
  };
  el.addEventListener("keydown", (e) => {
    if (e.key === "Tab") { e.preventDefault(); etat.edition = null; const v = el.value; el.remove(); valider(v, e.shiftKey ? -1 : 1); }
    else if (e.key === "Enter" && !ch.multiligne) { e.preventDefault(); fermerEdition(true); }
    else if (e.key === "Escape") { e.preventDefault(); fermerEdition(false); }
  });
  etat.edition = { type: "champ", el, valider: (v) => valider(v) };
}

async function creerChamp(r) {
  const res = await formulaire("Créer un champ", [
    { cle: "type", libelle: "Type", type: "choix", valeur: "texte", choix: [["texte", "Texte"], ["multiligne", "Texte sur plusieurs lignes"], ["case", "Case à cocher"], ["liste", "Liste déroulante"], ["signature", "Signature"]] },
    { cle: "nom", libelle: "Nom du champ", type: "texte", valeur: "" },
    { cle: "choix", libelle: "Choix de la liste (séparés par ;)", type: "texte", valeur: "" },
  ]);
  if (!res) return;
  await essayer(async () => {
    majDocument(await api(urlDoc("/creer_champ"), { json: { page: etat.page, bbox: r, ...res } }));
    statut("Champ créé. Outil Formulaire pour le remplir.");
  });
}

// --------------------------------------------------------------------------
// Rechercher et remplacer
// --------------------------------------------------------------------------

async function rechercher() {
  const texte = $("#r-cherche").value;
  if (!etat.doc || !texte) return;
  await essayer(async () => {
    let res = await api(urlDoc("/rechercher"), { json: { texte, casse: $("#r-casse").checked } });
    if ($("#r-page").checked) res = res.filter((r) => r.page === etat.page);
    etat.resultats = res;
    etat.iRes = -1;
    $("#r-resultats").textContent = res.length ? `${res.length} résultat(s)` : "Aucun résultat";
    if (res.length) resultatSuivant(1); else dessinerCalque();
  });
}

function resultatSuivant(sens) {
  const n = etat.resultats.length;
  if (!n) return rechercher();
  etat.iRes = (etat.iRes + sens + n) % n;
  const r = etat.resultats[etat.iRes];
  $("#r-resultats").textContent = `Résultat ${etat.iRes + 1} sur ${n}`;
  if (r.page !== etat.page) { etat.page = r.page; afficherPage().then(() => defilerVers(r)); }
  else { dessinerCalque(); defilerVers(r); }
}

function defilerVers(r) {
  const vue = $("#vue"), y = r.bbox[1] * etat.echelle + $("#feuille").offsetTop;
  if (y < vue.scrollTop || y > vue.scrollTop + vue.clientHeight - 40) vue.scrollTop = y - 120;
}

async function remplacerTout() {
  const ancien = $("#r-cherche").value;
  if (!ancien) return alerte("Remplacer", "Indiquez le texte à rechercher.");
  await essayer(async () => {
    const infos = await api(urlDoc("/remplacer"), {
      json: { ancien, nouveau: $("#r-remplace").value, casse: $("#r-casse").checked,
              page: $("#r-page").checked ? etat.page : null, decaler: true },
    }, "Remplacement…");
    const res = infos.resultat;
    if (!res) { $("#r-resultats").textContent = "Aucun résultat"; return; }
    etat.resultats = [];
    majDocument(infos, [...new Set(res.map((r) => r.page - 1))]);
    $("#r-resultats").textContent = `${res.length} remplacement(s)`;
    statut(`${res.length} remplacement(s) — police : ${[...new Set(res.map((r) => r.police))].join(" ; ")}`);
  });
}

// --------------------------------------------------------------------------
// OCR, numérisation, polices
// --------------------------------------------------------------------------

function proposerOcr() {
  confirmer("Page scannée", "Cette page est une image scannée : son texte doit d'abord être reconnu (OCR) pour être modifié.\nLancer la reconnaissance maintenant ?")
    .then((ok) => ok && lancerOcr(false));
}

async function lancerOcr(choisir) {
  let langues = JSON.parse(localStorage.getItem("langues") || '["fra","eng"]'), toutes = false;
  if (choisir || !etat.doc.scannees.length) {
    const champs = Object.entries(etat.config.langues || { Français: "fra", Anglais: "eng" })
      .map(([nom, code]) => ({ cle: code, libelle: nom, type: "case", valeur: langues.includes(code) }));
    champs.push({ cle: "_toutes", libelle: "Reconnaître aussi les pages qui contiennent déjà du texte", type: "case", valeur: !etat.doc.scannees.length });
    const r = await formulaire("Reconnaissance du texte (OCR)", champs, { aide: "Langues du document :", ok: "Lancer" });
    if (!r) return;
    toutes = r._toutes;
    langues = Object.keys(r).filter((k) => k !== "_toutes" && r[k]);
    if (!langues.length) return alerte("Langues", "Choisissez au moins une langue.");
    localStorage.setItem("langues", JSON.stringify(langues));
  }
  await essayer(async () => {
    const infos = await api(urlDoc("/ocr"), { json: { langues, toutes } },
      "Lecture du texte de la page… (la première fois, les fichiers de langue sont téléchargés)");
    majDocument(infos, "toutes");
    const r = infos.resultat;
    if (r) choisirOutil("edition");
    statut(r ? `Texte reconnu : ${r.mots} mots sur ${r.pages} page(s). Cliquez sur un texte pour le modifier.` : "Aucune page à reconnaître.");
  });
}

async function numeriser() {
  if (!etat.config.scanner) return alerte("Numériser", "La numérisation n'est possible que sur l'ordinateur où tourne PDF Éditeur.\nSur un téléphone, utilisez « Photographier un document ».");
  let appareils = [];
  try { appareils = await api("/api/scanners", {}, "Recherche des scanners…"); } catch (e) { /* liste vide */ }
  const reg = JSON.parse(localStorage.getItem("numerisation") || "{}");
  const r = await formulaire("Numériser un document", [
    { cle: "appareil", libelle: "Scanner", type: "choix", valeur: reg.appareil, choix: appareils.length ? appareils.map((a) => [a.id, a.nom]) : [["", "(scanner par défaut)"]] },
    { cle: "dpi", libelle: "Qualité", type: "choix", valeur: reg.dpi || 300, choix: [[150, "150 ppp (brouillon)"], [200, "200 ppp"], [300, "300 ppp (conseillé)"], [400, "400 ppp"], [600, "600 ppp (très fin)"]] },
    { cle: "mode", libelle: "Couleurs", type: "choix", valeur: reg.mode || "Couleur", choix: [["Couleur", "Couleur"], ["Niveaux de gris", "Niveaux de gris"], ["Noir et blanc", "Noir et blanc"]] },
    { cle: "source", libelle: "Source", type: "choix", valeur: reg.source || "vitre", choix: [["vitre", "Vitre (page par page)"], ["chargeur", "Chargeur (plusieurs pages)"]] },
    { cle: "ocr", libelle: "Reconnaître le texte pour pouvoir le modifier", type: "case", valeur: reg.ocr !== false },
    { cle: "redresser", libelle: "Redresser les pages scannées de travers", type: "case", valeur: reg.redresser !== false },
    { cle: "fenetre", libelle: "Utiliser la fenêtre du scanner de Windows (aperçu, cadrage)", type: "case", valeur: !!reg.fenetre },
  ], { ok: "Numériser", aide: "Posez la feuille bien droite, face à numériser contre la vitre." });
  if (!r) return;
  localStorage.setItem("numerisation", JSON.stringify(r));
  const requete = { appareil: r.appareil || null, dpi: parseInt(r.dpi, 10), mode: r.mode, chargeur: r.source === "chargeur", fenetre: r.fenetre, redresser: r.redresser };
  await essayer(async () => {
    let infos = await api("/api/numeriser", { json: requete }, "Numérisation en cours…");
    let premier = true;
    while (!requete.chargeur && await confirmer("Numériser", `${infos.pages.length} page(s) numérisée(s).\nNumériser une autre page ? (posez la feuille suivante sur la vitre)`)) {
      if (premier) { nouveauDocument(infos); premier = false; }
      infos = await api("/api/numeriser", { json: { ...requete, doc: infos.id } }, "Numérisation en cours…");
    }
    etat.page = 0;
    nouveauDocument(infos);
    etat.modifie = true;
    statut(`${infos.pages.length} page(s) numérisée(s).`);
    if (r.ocr) await lancerOcr(false);
  });
}

async function proposerPolices() {
  if (await confirmer("Police introuvable", "La police d'origine n'est pas installée : une police proche a été utilisée.\nVoir les polices du document et installer celles qui manquent ?")) fenetrePolices();
}

async function fenetrePolices() {
  await essayer(async () => {
    const liste = await api(urlDoc("/polices"));
    const etats = { installee: ["✔ installée", "ok"], standard: ["✔ police standard PDF", "ok"], equivalente: ["≈ remplacée", "moyen"], manquante: ["✖ manquante", "ko"] };
    const lignes = liste.map((p) => `<tr><td>${echapper(p.nom)}</td><td>${p.integree ? (p.partielle ? "intégrée (partielle)" : "intégrée") : "non intégrée"}</td><td class="${etats[p.etat][1]}">${etats[p.etat][0]} ${echapper(p.detail || "")}</td></tr>`).join("");
    const manquantes = liste.filter((p) => p.etat === "manquante" || p.etat === "equivalente").length;
    const r = await formulaire("Polices du document", [{ type: "info", html: `<table><tr><th>Police</th><th>Dans le PDF</th><th>Disponible</th></tr>${lignes}</table>` }],
      { ok: manquantes ? "Installer les polices manquantes" : "Fermer", annuler: manquantes ? "Fermer" : "" });
    if (r && manquantes) {
      const res = await api(urlDoc("/installer_polices"), { method: "POST" }, "Téléchargement des polices (Google Fonts)…");
      await alerte("Polices", `${res.installees.length} police(s) installée(s).` + (res.introuvables.length ? `\nIntrouvables gratuitement : ${res.introuvables.join(", ")}` : ""));
      chargerPolices();
    }
  });
}

async function chargerPolices() {
  try {
    const liste = await api("/api/polices");
    $("#liste-polices").innerHTML = liste.map((p) => `<option value="${echapper(p)}">`).join("");
  } catch (_) { /* pas grave */ }
}

// --------------------------------------------------------------------------
// Actions des menus
// --------------------------------------------------------------------------

const ACTIONS = {
  ouvrir: () => $("#f-ouvrir").click(),
  photo: () => $("#f-photo").click(),
  numeriser,
  telecharger: () => telecharger(),
  "telecharger-mdp": async () => {
    const r = await formulaire("Télécharger avec mot de passe", [
      { cle: "a", libelle: "Mot de passe", type: "motdepasse" }, { cle: "b", libelle: "Confirmer", type: "motdepasse" }],
    { aide: "Le fichier sera chiffré (AES-256) : il faudra ce mot de passe pour l'ouvrir." });
    if (!r) return;
    if (!r.a || r.a !== r.b) return alerte("Mot de passe", "Les mots de passe sont vides ou différents.");
    telecharger(r.a);
  },
  word: () => essayer(async () => telechargerBlob(await api(urlDoc("/word"), {}, "Conversion en Word…"), `${etat.doc.nom}.docx`)),
  "texte-txt": () => essayer(async () => telechargerBlob(await api(urlDoc("/texte.txt")), `${etat.doc.nom}.txt`)),
  fusionner: () => { etat.fusionApres = null; $("#f-fusion").click(); },
  proprietes: async () => {
    const m = await api(urlDoc("/proprietes"));
    const r = await formulaire("Propriétés du document", [
      { cle: "nom", libelle: "Nom du fichier", type: "texte", valeur: m.nom },
      { cle: "title", libelle: "Titre", type: "texte", valeur: m.title || "" },
      { cle: "author", libelle: "Auteur", type: "texte", valeur: m.author || "" },
      { cle: "subject", libelle: "Sujet", type: "texte", valeur: m.subject || "" },
      { cle: "keywords", libelle: "Mots-clés", type: "texte", valeur: m.keywords || "" }]);
    if (r) essayer(async () => { majDocument(await api(urlDoc("/outil"), { json: { quoi: "proprietes", ...r } })); document.title = `${etat.doc.nom} — PDF Éditeur`; });
  },
  fermer: async () => {
    if (!etat.doc || !(await confirmerAbandon())) return;
    fetch(urlDoc(), { method: "DELETE" });
    etat.doc = null; etat.modifie = false;
    $("#feuille").hidden = true; $("#vignettes").innerHTML = ""; $("#accueil").hidden = false; $("#bandeau").hidden = true;
    document.title = "PDF Éditeur";
    majEtat();
  },
  arreter: async () => {
    if (!(await confirmerAbandon())) return;
    if (!(await confirmer("Quitter", "Arrêter PDF Éditeur ? Les documents ouverts seront fermés.", "Quitter", "Annuler"))) return;
    etat.modifie = false;
    try { await api("/api/arreter", { method: "POST" }); } catch (_) { /* déjà arrêté */ }
    document.body.innerHTML = '<p style="margin:40px;font-size:18px">PDF Éditeur est arrêté. Vous pouvez fermer cet onglet.</p>';
  },
  annuler: () => etat.doc && essayer(async () => { fermerEdition(false); majDocument(await api(urlDoc("/annuler"), { method: "POST" }), "toutes"); }),
  retablir: () => etat.doc && essayer(async () => { fermerEdition(false); majDocument(await api(urlDoc("/retablir"), { method: "POST" }), "toutes"); }),
  image: () => $("#f-image").click(),
  signer: async () => { const s = await demanderSignature(); if (s) { etat.signature = s; choisirOutil("signature"); } },
  rechercher: () => { $("#panneau").hidden = false; $("#r-cherche").focus(); $("#r-cherche").select(); },
  pivoter: () => actionPages("pivoter", etat.page, { angle: 90 }),
  "pivoter-tout": () => actionPages("pivoter_tout", etat.page),
  "supprimer-page": () => supprimerPage(),
  "page-blanche": () => actionPages("blanche", etat.page),
  ocr: () => lancerOcr(true),
  polices: fenetrePolices,
  filigrane: async () => {
    const r = await formulaire("Filigrane", [
      { cle: "texte", libelle: "Texte", type: "texte", valeur: "CONFIDENTIEL" }, { cle: "taille", libelle: "Taille", type: "nombre", valeur: 60 },
      { cle: "opacite", libelle: "Opacité (0 à 1)", type: "nombre", valeur: 0.3 }, { cle: "couleur", libelle: "Couleur", type: "couleur", valeur: "#999999" }]);
    if (r && r.texte) essayer(async () => majDocument(await api(urlDoc("/outil"), { json: { quoi: "filigrane", ...r } }), "toutes"));
  },
  numeroter: async () => {
    const r = await formulaire("Numéroter les pages", [
      { cle: "format", libelle: "Format", type: "texte", valeur: "{n} / {total}" }, { cle: "taille", libelle: "Taille", type: "nombre", valeur: 10 }],
    { aide: "{n} = numéro de la page, {total} = nombre de pages. Les numéros sont placés en bas au centre." });
    if (r) essayer(async () => majDocument(await api(urlDoc("/outil"), { json: { quoi: "numeroter", ...r } }), "toutes"));
  },
  aplatir: async () => {
    if (await confirmer("Aplatir", "Les champs de formulaire et les annotations deviendront du contenu fixe (plus modifiables). Continuer ?"))
      essayer(async () => majDocument(await api(urlDoc("/outil"), { json: { quoi: "aplatir" } }), "toutes"));
  },
  aide: () => alerte("Aide", [
    "• Ouvrir : bouton Ouvrir, ou glisser-déposer un PDF, un document Word ou une image.",
    "• Sur téléphone : « Photographier un document » ; le texte est reconnu automatiquement.",
    "• Modifier un texte : outil Modifier, cliquez sur le texte, tapez, puis Entrée (Échap annule).",
    "• Police, taille, gras, italique, couleur : barre de mise en forme.",
    "• Document scanné : bouton « Reconnaître le texte (OCR) » dans le bandeau jaune.",
    "• Formulaire : outil Formulaire, cliquez sur un champ (Tab = champ suivant).",
    "• Pages : glissez une miniature pour la déplacer ; clic droit pour plus d'actions.",
    "• Annuler : Ctrl+Z — Rétablir : Ctrl+Y — Télécharger : Ctrl+S — Rechercher : Ctrl+F.",
  ].join("\n")),
};

function fermerMenus() { $$(".menu").forEach((m) => (m.hidden = true)); }

document.addEventListener("click", (e) => {
  const menu = e.target.closest("[data-menu]");
  if (menu) {
    const m = $(`#menu-${menu.dataset.menu}`), ouvert = !m.hidden;
    fermerMenus();
    m.hidden = ouvert;
    return;
  }
  const b = e.target.closest("[data-action], [data-outil]");
  if (!e.target.closest(".menu") || b) fermerMenus();
  if (!b || b.disabled || b.closest("#calque")) return;
  if (b.dataset.outil) {
    if (!etat.doc) return;
    return choisirOutil(b.dataset.outil);
  }
  const action = ACTIONS[b.dataset.action];
  if (action && (etat.doc || ["ouvrir", "photo", "numeriser", "aide", "arreter"].includes(b.dataset.action))) action();
});

// fichiers choisis
$("#f-ouvrir").addEventListener("change", (e) => { ouvrirFichiers([...e.target.files]); e.target.value = ""; });
$("#f-photo").addEventListener("change", (e) => { ouvrirFichiers([...e.target.files]); e.target.value = ""; });
$("#f-image").addEventListener("change", (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  etat.imageAPlacer = f;
  choisirOutil("image");
});
$("#f-fusion").addEventListener("change", async (e) => {
  const fichiers = [...e.target.files];
  e.target.value = "";
  if (!fichiers.length) return;
  const fd = new FormData();
  fichiers.forEach((f) => fd.append("fichiers", f, f.name));
  if (etat.fusionApres !== null && etat.fusionApres !== undefined) fd.append("apres", etat.fusionApres);
  await essayer(async () => majDocument(await api(urlDoc("/fusionner"), { method: "POST", body: fd }, "Ajout des pages…"), "toutes"));
});

// glisser-déposer de fichiers
let compteurGlisser = 0;
const fichiersGlisses = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
window.addEventListener("dragenter", (e) => { if (fichiersGlisses(e)) { compteurGlisser++; $("#glisser").hidden = false; } });
window.addEventListener("dragleave", (e) => { if (fichiersGlisses(e) && --compteurGlisser <= 0) { compteurGlisser = 0; $("#glisser").hidden = true; } });
window.addEventListener("dragover", (e) => { if (fichiersGlisses(e)) e.preventDefault(); });
window.addEventListener("drop", async (e) => {
  if (!fichiersGlisses(e)) return;
  e.preventDefault();
  compteurGlisser = 0;
  $("#glisser").hidden = true;
  const fichiers = [...e.dataTransfer.files];
  if (!fichiers.length) return;
  if (etat.doc) {
    const images = fichiers.every((f) => f.type.startsWith("image/"));
    const r = await formulaire("Fichier déposé", [{ cle: "quoi", libelle: "Que faire ?", type: "choix", valeur: images ? "image" : "fusion",
      choix: [["fusion", "Ajouter à la fin du document"], ["ouvrir", "Ouvrir à la place"], ...(images ? [["image", "Placer l'image sur la page"]] : [])] }]);
    if (!r) return;
    if (r.quoi === "image") { etat.imageAPlacer = fichiers[0]; return choisirOutil("image"); }
    if (r.quoi === "fusion") {
      const fd = new FormData();
      fichiers.forEach((f) => fd.append("fichiers", f, f.name));
      return essayer(async () => majDocument(await api(urlDoc("/fusionner"), { method: "POST", body: fd }, "Ajout des pages…"), "toutes"));
    }
  }
  ouvrirFichiers(fichiers);
});

// panneau de recherche
$("#r-chercher").addEventListener("click", rechercher);
$("#r-cherche").addEventListener("keydown", (e) => { if (e.key === "Enter") rechercher(); });
$("#r-prec").addEventListener("click", () => resultatSuivant(-1));
$("#r-suiv").addEventListener("click", () => resultatSuivant(1));
$("#r-remplacer").addEventListener("click", remplacerTout);
$("#panneau-fermer").addEventListener("click", () => { $("#panneau").hidden = true; etat.resultats = []; dessinerCalque(); });
$("#bandeau-fermer").addEventListener("click", () => { etat.bandeauFerme = true; $("#bandeau").hidden = true; });

// navigation et zoom
$("#p-prec").addEventListener("click", () => allerPage(etat.page - 1));
$("#p-suiv").addEventListener("click", () => allerPage(etat.page + 1));
$("#p-num").addEventListener("change", (e) => { allerPage(parseInt(e.target.value, 10) - 1); majEtat(); });
$("#zoom").value = etat.zoom;
$("#zoom").addEventListener("change", (e) => { etat.zoom = e.target.value; localStorage.setItem("zoom", etat.zoom); afficherPage(); });
let attenteRedim;
window.addEventListener("resize", () => {
  clearTimeout(attenteRedim);
  if (etat.doc && !etat.edition && (etat.zoom === "largeur" || etat.zoom === "page")) attenteRedim = setTimeout(afficherPage, 200);
});
$("#vue").addEventListener("wheel", (e) => {
  if (e.ctrlKey) {
    e.preventDefault();
    const niveaux = [0.5, 0.75, 1, 1.25, 1.5, 2, 3];
    const actuel = etat.echelle / PT_EN_PX;
    const z = e.deltaY < 0 ? niveaux.find((n) => n > actuel + 0.01) : [...niveaux].reverse().find((n) => n < actuel - 0.01);
    if (z) { etat.zoom = String(z); $("#zoom").value = etat.zoom; afficherPage(); }
    return;
  }
  const vue = $("#vue");
  if (e.deltaY > 0 && vue.scrollTop + vue.clientHeight >= vue.scrollHeight - 2 && etat.doc && etat.page < etat.doc.pages.length - 1) {
    e.preventDefault(); allerPage(etat.page + 1);
  } else if (e.deltaY < 0 && vue.scrollTop <= 0 && etat.page > 0) {
    e.preventDefault(); etat.page--; afficherPage().then(() => (vue.scrollTop = vue.scrollHeight));
  }
}, { passive: false });

// raccourcis clavier
document.addEventListener("keydown", (e) => {
  const saisie = e.target.closest("input, textarea, select, dialog");
  const ctrl = e.ctrlKey || e.metaKey;
  if (e.key === "Escape") { fermerMenus(); $("#menu-contexte").hidden = true; if (!saisie && etat.outil !== "selection") choisirOutil("selection"); }
  if (!ctrl) {
    if (!saisie && e.key === "PageDown") allerPage(etat.page + 1);
    if (!saisie && e.key === "PageUp") allerPage(etat.page - 1);
    return;
  }
  const k = e.key.toLowerCase();
  const correspondance = { o: "ouvrir", s: "telecharger", f: "rechercher", h: "rechercher" };
  if (!saisie && (k === "z" || k === "y")) { e.preventDefault(); return ACTIONS[k === "z" && !e.shiftKey ? "annuler" : "retablir"](); }
  if (k === "e" && etat.doc) { e.preventDefault(); return choisirOutil("edition"); }
  if (correspondance[k] && (etat.doc || k === "o")) { e.preventDefault(); ACTIONS[correspondance[k]](); }
});

window.addEventListener("beforeunload", (e) => { if (etat.doc && etat.modifie) { e.preventDefault(); e.returnValue = ""; } });

// démarrage
(async function demarrer() {
  try { etat.config = await api("/api/config"); } catch (_) { etat.config = {}; }
  if (!etat.config.scanner) $$("[data-local]").forEach((b) => (b.hidden = true));
  if (!matchMedia("(pointer: coarse)").matches) $$('[data-action="photo"]').forEach((b) => b.textContent.startsWith("Photo") && (b.textContent = "Ouvrir une photo…"));
  document.documentElement.style.setProperty("--haut-accueil", `${$("#ruban").offsetHeight}px`);
  chargerPolices();
  setTimeout(chargerPolices, 8000); // la liste complète peut être prête un peu plus tard
  majEtat();
})();
