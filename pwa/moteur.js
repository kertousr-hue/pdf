/* PDF Éditeur (PWA) — moteur exécuté dans un Web Worker.
 *
 * Python (Pyodide) fait tourner le même serveur que la version de bureau (app_web.py, Flask),
 * sans réseau : chaque requête de l'interface est passée directement au « client de test » Flask.
 * Les fichiers de l'utilisateur ne quittent donc jamais l'appareil.
 */
"use strict";

importScripts("pyodide/pyodide.js");

const DOSSIER_APP = "/home/pyodide/app";
const DOSSIER_DONNEES = "/home/pyodide/.local/share"; // réglages, polices ajoutées (gardés entre deux visites)
let pyodide = null;
let traiter = null;
let synchroPrevue = null;

function progression(etape, pourcent) { postMessage({ type: "progression", etape, pourcent }); }

async function demarrer() {
  progression("Chargement de Python…", 5);
  pyodide = await loadPyodide({ indexURL: new URL("pyodide/", location.href).href });

  progression("Chargement du moteur PDF…", 35);
  await pyodide.loadPackage(new URL("roues/pymupdf-1.28.2-cp313-abi3-pyemscripten_2025_0_wasm32.whl", location.href).href);

  progression("Installation des modules…", 70);
  const archive = await (await fetch("python.zip")).arrayBuffer();
  pyodide.FS.mkdirTree(DOSSIER_APP);
  pyodide.unpackArchive(archive, "zip", { extractDir: DOSSIER_APP });

  progression("Préparation des polices…", 80);
  pyodide.FS.mkdirTree(DOSSIER_APP + "/polices");
  const polices = await (await fetch("polices/liste.json")).json();
  await Promise.all(polices.map(async (nom) => {
    const octets = new Uint8Array(await (await fetch("polices/" + nom)).arrayBuffer());
    pyodide.FS.writeFile(`${DOSSIER_APP}/polices/${nom}`, octets);
  }));

  // dossier de données gardé dans le navigateur (IndexedDB)
  pyodide.FS.mkdirTree(DOSSIER_DONNEES);
  try {
    pyodide.FS.mount(pyodide.FS.filesystems.IDBFS, {}, DOSSIER_DONNEES);
    await new Promise((ok) => pyodide.FS.syncfs(true, () => ok()));
  } catch (_) { /* stockage indisponible (navigation privée) : on continue sans */ }

  progression("Démarrage…", 92);
  traiter = pyodide.runPython(`
import sys
sys.path.insert(0, "${DOSSIER_APP}")
import os
os.environ.setdefault("XDG_DATA_HOME", "${DOSSIER_DONNEES}")
import app_web, polices
polices.INDEX.charger()          # pas de fil d'exécution dans le navigateur : chargement direct
client = app_web.app.test_client()

def traiter(methode, url, type_contenu, corps):
    donnees = bytes(corps.to_py()) if hasattr(corps, "to_py") else None
    type_contenu = type_contenu if isinstance(type_contenu, str) and type_contenu else None
    r = client.open(url, method=methode, data=donnees, content_type=type_contenu)
    return [r.status_code, r.headers.get("Content-Type", ""), r.headers.get("Content-Disposition", ""),
            r.get_data()]
traiter
`);
  progression("Prêt", 100);
}

function synchroniser() {
  clearTimeout(synchroPrevue);
  synchroPrevue = setTimeout(() => { try { pyodide.FS.syncfs(false, () => {}); } catch (_) { /* rien */ } }, 1500);
}

const pret = demarrer().then(
  () => postMessage({ type: "pret" }),
  (e) => postMessage({ type: "erreur_demarrage", message: String(e && e.message || e) }),
);

onmessage = async (e) => {
  const m = e.data;
  if (m.type !== "requete") return;
  await pret;
  try {
    // « undefined » devient None en Python (« null » ne le devient pas)
    const corps = m.corps ? new Uint8Array(m.corps) : undefined;
    const r = traiter(m.methode, m.url, m.typeContenu || undefined, corps);
    const [statut, type, disposition, donnees] = r.toJs();
    r.destroy();
    const octets = donnees.slice ? donnees.slice() : new Uint8Array(donnees);
    postMessage({ type: "reponse", id: m.id, statut, entetes: { "Content-Type": type, "Content-Disposition": disposition },
                  corps: octets.buffer }, [octets.buffer]);
    if (m.methode !== "GET") synchroniser();
  } catch (err) {
    const message = JSON.stringify({ erreur: String(err && err.message || err).split("\n").slice(-3).join(" ") });
    postMessage({ type: "reponse", id: m.id, statut: 500, entetes: { "Content-Type": "application/json" },
                  corps: new TextEncoder().encode(message).buffer });
  }
};
