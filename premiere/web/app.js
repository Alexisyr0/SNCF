/* Première — calendrier des prix SNCF, aller-retour, suivi, rames Océane */
(function () {
  "use strict";

  const JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
  const JOURS_C = ["Lu", "Ma", "Me", "Je", "Ve", "Sa", "Di"];
  const MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
  const CARTES = ["Carte Avantage Jeune", "Carte Avantage Adulte", "Carte Avantage Senior", "Carte Liberté", ""];
  const app = document.getElementById("app");

  let sb = null;
  const E = { session: null, recherches: [], meilleurs: {}, robot: null, alertes: [], etiquettes: {},
              detail: null, sens: "aller", jourChoisi: null, filtreParis: null, filtreOceane: false, minuteur: null };

  // ---------------------------------------------------------------- utilitaires
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const euros = (v) => v == null ? "–" : (Math.round(v * 100) / 100).toLocaleString("fr-FR", { minimumFractionDigits: v % 1 ? 2 : 0, maximumFractionDigits: 2 }) + " €";
  const dateDe = (iso) => { const [a, m, j] = iso.split("-").map(Number); return new Date(a, m - 1, j); };
  const isoDe = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  const jourSem = (d) => (d.getDay() + 6) % 7;
  const jourFr = (iso) => { const d = dateDe(iso); return JOURS[jourSem(d)] + " " + d.getDate() + " " + MOIS[d.getMonth()]; };
  const Maj = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const MOIS_C = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
  const court = (iso) => { const d = dateDe(iso); return d.getDate() + " " + MOIS_C[d.getMonth()]; };
  const ecart = (a, b) => Math.round((dateDe(b) - dateDe(a)) / 864e5);
  const ilya = (ts) => { const s = (Date.now() - new Date(ts)) / 1000; if (s < 90) return "à l'instant"; if (s < 3600) return "il y a " + Math.round(s / 60) + " min"; if (s < 86400) return "il y a " + Math.round(s / 3600) + " h"; return "il y a " + Math.round(s / 86400) + " j"; };
  const gare = (g) => (g || "").replace(/ - Hall \d+( & \d+)?/g, "").replace(/Paris - /g, "Paris ");
  const go = (h) => { location.hash = h; };

  function cfg() {
    const c = window.PREMIERE_CONFIG || {};
    return { url: c.supabaseUrl || localStorage.getItem("premiere.url") || "", cle: c.supabaseAnonKey || localStorage.getItem("premiere.cle") || "" };
  }

  async function toutLire(requete) {
    const out = [];
    for (let i = 0; ; i += 1000) {
      const { data, error } = await requete().range(i, i + 999);
      if (error) throw error;
      out.push(...data);
      if (data.length < 1000) return out;
    }
  }

  // ---------------------------------------------------------------- démarrage
  async function demarrer() {
    const { url, cle } = cfg();
    if (!url || !cle) return ecranConfig();
    sb = window.supabase.createClient(url, cle, { auth: { persistSession: true, autoRefreshToken: true } });
    const { data } = await sb.auth.getSession();
    E.session = data.session;
    sb.auth.onAuthStateChange((_e, s) => { const avant = !!E.session; E.session = s; if (avant !== !!s) route(); });
    window.addEventListener("hashchange", route);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) route(true); });
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
    route();
  }

  function ecranConfig() {
    app.innerHTML = `<div class="ecran"><form class="carte" id="f-config">
      <div class="logo"><i>1</i>Première</div>
      <p class="sous">Première connexion sur cet appareil : colle l'adresse et la clé publique (« anon ») de ton projet Supabase.
      Tu les trouves dans Supabase › Project Settings › API.</p>
      <div class="champ"><label>URL du projet</label><input name="url" placeholder="https://xxxx.supabase.co" required></div>
      <div class="champ"><label>Clé anon (publique)</label><input name="cle" required></div>
      <button class="btn principal">Continuer</button></form></div>`;
    document.getElementById("f-config").onsubmit = (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      localStorage.setItem("premiere.url", f.get("url").trim());
      localStorage.setItem("premiere.cle", f.get("cle").trim());
      demarrer();
    };
  }

  function ecranConnexion(message) {
    app.innerHTML = `<div class="ecran"><form class="carte" id="f-login">
      <div class="logo"><i>1</i>Première</div>
      <p class="sous">Les meilleurs prix en 1re, jour par jour.</p>
      <div class="champ"><label>E-mail</label><input name="email" type="email" autocomplete="username" required></div>
      <div class="champ"><label>Mot de passe</label><input name="mdp" type="password" autocomplete="current-password" required></div>
      ${message ? `<div class="erreur-txt">${esc(message)}</div>` : ""}
      <button class="btn principal">Se connecter</button>
      <button class="btn fantome" type="button" id="b-creer">Créer un compte</button></form></div>`;
    const f = document.getElementById("f-login");
    f.onsubmit = async (e) => {
      e.preventDefault();
      const d = new FormData(f);
      const { error } = await sb.auth.signInWithPassword({ email: d.get("email"), password: d.get("mdp") });
      if (error) ecranConnexion("Connexion impossible : " + error.message);
    };
    document.getElementById("b-creer").onclick = async () => {
      const d = new FormData(f);
      if (!d.get("email") || !d.get("mdp")) return ecranConnexion("Saisis un e-mail et un mot de passe, puis « Créer un compte ».");
      const { error } = await sb.auth.signUp({ email: d.get("email"), password: d.get("mdp") });
      ecranConnexion(error ? error.message : "Compte créé. Si Supabase t'envoie un e-mail de confirmation, valide-le puis connecte-toi.");
    };
  }

  // ---------------------------------------------------------------- routage
  async function route(silencieux) {
    if (!E.session) return ecranConnexion();
    clearTimeout(E.minuteur);
    const h = location.hash.replace(/^#\/?/, "");
    const [a, b, c] = h.split("/");
    try {
      await chargerCommun();
      if (a === "nouvelle") vueFormulaire(null);
      else if (a === "r" && c === "modifier") vueFormulaire(b);
      else if (a === "r" && b) await vueDetail(b, silencieux);
      else if (a === "rames") await vueRames();
      else if (a === "reglages") vueReglages();
      else vueAccueil();
    } catch (err) {
      console.error(err);
      cadre("", `<div class="bandeau erreur">Erreur : ${esc(err.message || err)}</div>
        <p class="petit">As-tu bien exécuté le fichier supabase/schema.sql dans ton projet Supabase ?</p>`);
    }
    planifier();
  }

  function planifier() {
    if (/^#\/(nouvelle|r\/[^/]+\/modifier)/.test(location.hash)) return;
    const actif = E.recherches.some((r) => ["en_attente", "en_cours", "bloquee"].includes(r.statut)) || E.analysesEnCours;
    E.minuteur = setTimeout(() => { if (!document.hidden && !document.activeElement.closest("form")) route(true); }, actif ? 8000 : 60000);
  }

  async function chargerCommun() {
    const [r, rob, al, et, ex, an] = await Promise.all([
      sb.from("train_recherches").select("*").order("created_at", { ascending: false }),
      sb.from("train_robot").select("*").maybeSingle(),
      sb.from("train_alertes").select("*").eq("lu", false).order("created_at", { ascending: false }).limit(5),
      sb.from("train_etiquettes").select("*"),
      sb.from("train_executions").select("recherche_id,meilleur_total,meilleur_aller,debut,statut").eq("statut", "terminee").order("debut", { ascending: false }).limit(400),
      sb.from("train_analyses").select("id,statut").in("statut", ["en_attente", "en_cours"]),
    ]);
    for (const x of [r, al, et, ex]) if (x.error) throw x.error;
    E.recherches = r.data;
    E.robot = rob.data;
    E.alertes = al.data;
    E.etiquettes = Object.fromEntries(et.data.map((e) => [e.signature, e]));
    E.analysesEnCours = (an.data || []).length > 0;
    E.meilleurs = {};
    E.historique = {};
    for (const e of ex.data) {
      if (!(e.recherche_id in E.meilleurs)) E.meilleurs[e.recherche_id] = e.meilleur_total;
      (E.historique[e.recherche_id] = E.historique[e.recherche_id] || []).push(e);
    }
  }

  function robotEnLigne() {
    return E.robot && (Date.now() - new Date(E.robot.vu_le)) < 3 * 60 * 1000;
  }

  function cadre(onglet, contenu) {
    const r = E.robot;
    const pill = robotEnLigne()
      ? `<span class="pastille ok robot" title="Le robot du Mac est allumé"><span class="point"></span><span class="txt">Mac ${r.occupe ? "· " + esc(r.occupe) : "en ligne"}</span></span>`
      : `<span class="pastille erreur robot" title="${r ? "Dernier signe " + ilya(r.vu_le) : "Jamais connecté"}"><span class="point"></span><span class="txt">Mac hors ligne</span></span>`;
    app.innerHTML = `<header class="entete"><div class="entete-in">
        <a class="logo" href="#/"><i>1</i>Première</a>${pill}
        <nav class="nav"><a href="#/" class="${onglet === "accueil" ? "actif" : ""}">Recherches</a>
        <a href="#/rames" class="${onglet === "rames" ? "actif" : ""}">Rames</a>
        <a href="#/reglages" class="${onglet === "reglages" ? "actif" : ""}">Réglages</a></nav></div></header>
      <main>${contenu}</main>`;
  }

  function pastilleStatut(r) {
    const m = { en_attente: ["attente", "En attente du Mac"], en_cours: ["attente", "En cours · " + (r.progression || 0) + " %"],
                terminee: ["ok", "À jour"], erreur: ["erreur", "Erreur"], bloquee: ["erreur", "Besoin d'aide sur le Mac"], pause: ["", "En pause"] }[r.statut] || ["", r.statut];
    return `<span class="pastille ${m[0]}"><span class="point"></span>${esc(m[1])}</span>`;
  }

  // ---------------------------------------------------------------- accueil
  function vueAccueil() {
    const alertes = E.alertes.map((a) => {
      const r = E.recherches.find((x) => x.id === a.recherche_id);
      return `<div class="bandeau"><span>📉</span><span><b>${r ? esc(r.origine + " → " + r.destination) : "Trajet"}</b> : ${euros(a.nouveau)}
        ${a.ancien != null ? `<span class="petit">(avant ${euros(a.ancien)})</span>` : ""}</span><span class="espace"></span>
        <a class="btn petit-btn" href="#/r/${a.recherche_id}">Voir</a><button class="btn petit-btn fantome" data-lu="${a.id}">OK</button></div>`;
    }).join("");
    const actives = E.recherches.filter((r) => !r.archive);
    const archivees = E.recherches.filter((r) => r.archive);
    const carteR = (r) => `<a class="carte rech" href="#/r/${r.id}">
        <div class="ligne"><span class="rech-titre">${esc(r.origine)} → ${esc(r.destination)}</span><span class="espace"></span>
          ${r.retour_debut ? '<span class="pastille">aller-retour</span>' : ""}</div>
        <div class="petit">${court(r.aller_debut)} → ${court(r.aller_fin)}${r.retour_debut ? " · retour " + court(r.retour_debut) + " → " + court(r.retour_fin) : ""}
          · ${esc(r.classe)} ${r.inoui_seul ? "· TGV INOUI" : ""}</div>
        <div class="ligne"><span class="rech-prix">${euros(E.meilleurs[r.id])}</span><span class="espace"></span>
          ${r.suivi ? `<span class="pastille accent">suivi ${r.heure_suivi}h</span>` : ""}${pastilleStatut(r)}</div>
        ${r.statut === "en_cours" ? `<div class="barre"><i style="width:${r.progression || 0}%"></i></div>` : ""}
        ${r.message ? `<div class="petit">${esc(r.message)}</div>` : ""}</a>`;
    cadre("accueil", `${alertes}
      <div class="ligne"><div><h1>Tes recherches</h1><p class="sous">Le robot du Mac balaie SNCF Connect jour par jour, en 1re et TGV INOUI.</p></div>
        <span class="espace"></span><a class="btn principal" href="#/nouvelle">+ Nouvelle recherche</a></div>
      <div style="height:16px"></div>
      ${actives.length ? `<div class="grille-cartes">${actives.map(carteR).join("")}</div>`
        : `<div class="carte vide"><p>Aucune recherche pour l'instant.</p><a class="btn principal" href="#/nouvelle">Chercher un trajet</a></div>`}
      ${archivees.length ? `<h2>Archivées</h2><div class="grille-cartes">${archivees.map(carteR).join("")}</div>` : ""}`);
    app.querySelectorAll("[data-lu]").forEach((b) => b.onclick = async () => { await sb.from("train_alertes").update({ lu: true }).eq("id", b.dataset.lu); route(true); });
  }

  // ---------------------------------------------------------------- formulaire
  function vueFormulaire(id) {
    const r = id ? E.recherches.find((x) => x.id === id) : null;
    const dernier = E.recherches[0];
    const v = r || { origine: dernier ? dernier.origine : "Nice", destination: dernier ? dernier.destination : "Le Mans",
      aller_debut: "", aller_fin: "", retour_debut: "", retour_fin: "", nuits_min: 1, nuits_max: "", classe: "1re", inoui_seul: true,
      via_paris: false, voyageurs: dernier ? dernier.voyageurs : [{ age: 25, carte: "Carte Avantage Jeune" }], chiens: dernier ? dernier.chiens : 0,
      suivi: false, heure_suivi: 8, seuil: "", analyser_rames: true };
    let voyageurs = JSON.parse(JSON.stringify(v.voyageurs || []));
    const ligneV = (x, i) => `<div class="voyageur">
        <div class="champ"><span>Âge</span><input type="number" min="0" max="120" value="${esc(x.age)}" data-age="${i}"></div>
        <div class="champ"><span>Carte</span><select data-carte="${i}">${CARTES.map((c) => `<option value="${esc(c)}" ${c === (x.carte || "") ? "selected" : ""}>${c || "Sans carte"}</option>`).join("")}</select></div>
        ${i > 0 ? `<button type="button" class="btn petit-btn fantome" data-retirer="${i}">Retirer</button>` : "<span></span>"}</div>`;
    cadre("accueil", `<h1>${r ? "Modifier la recherche" : "Nouvelle recherche"}</h1>
      <p class="sous">Le robot remplira SNCF Connect exactement avec ces réglages.</p><div style="height:14px"></div>
      <form class="formulaire" id="f-rech">
        <div class="carte" style="display:grid;gap:12px">
          <div class="deux"><div class="champ"><label>Départ</label><input name="origine" list="gares" value="${esc(v.origine)}" required></div>
          <div class="champ"><label>Arrivée</label><input name="destination" list="gares" value="${esc(v.destination)}" required></div></div>
          <datalist id="gares"><option>Nice<option>Paris<option>Le Mans<option>Lyon<option>Marseille<option>Nantes<option>Rennes<option>Bordeaux<option>Lille<option>Montpellier<option>Toulouse<option>Strasbourg</datalist>
          <div class="deux"><div class="champ"><label>Aller : à partir du</label><input type="date" name="aller_debut" value="${esc(v.aller_debut)}" required></div>
          <div class="champ"><label>jusqu'au</label><input type="date" name="aller_fin" value="${esc(v.aller_fin)}" required></div></div>
          <div class="interrupteur"><span><b>Retour</b><br><span class="petit">Cherche aussi le retour et le meilleur couple de dates</span></span><input type="checkbox" name="avec_retour" ${v.retour_debut ? "checked" : ""}></div>
          <div id="bloc-retour" style="display:${v.retour_debut ? "grid" : "none"};gap:12px">
            <div class="deux"><div class="champ"><label>Retour : à partir du</label><input type="date" name="retour_debut" value="${esc(v.retour_debut || "")}"></div>
            <div class="champ"><label>jusqu'au</label><input type="date" name="retour_fin" value="${esc(v.retour_fin || "")}"></div></div>
            <div class="deux"><div class="champ"><label>Nuits sur place, au moins</label><input type="number" min="0" name="nuits_min" value="${esc(v.nuits_min)}"></div>
            <div class="champ"><label>au plus (vide = pas de limite)</label><input type="number" min="0" name="nuits_max" value="${esc(v.nuits_max == null ? "" : v.nuits_max)}"></div></div>
          </div>
        </div>
        <div class="carte" style="display:grid;gap:12px"><h3 style="margin:0">Qui voyage ?</h3>
          <div id="voyageurs" style="display:grid;gap:8px"></div>
          <div class="ligne"><button type="button" class="btn petit-btn" id="b-ajout-v">+ Voyageur</button><span class="espace"></span>
            <div class="champ" style="grid-auto-flow:column;align-items:center;gap:8px"><span>Chiens</span>
            <select name="chiens" style="width:70px">${[0, 1, 2].map((n) => `<option ${n == v.chiens ? "selected" : ""}>${n}</option>`).join("")}</select></div></div>
        </div>
        <div class="carte">
          <div class="interrupteur"><span><b>1re classe</b><br><span class="petit">Sur tous les trains du trajet</span></span><input type="checkbox" name="premiere" ${v.classe === "1re" ? "checked" : ""}></div>
          <div class="interrupteur"><span><b>TGV INOUI uniquement</b><br><span class="petit">Écarte OUIGO, TER, Intercités…</span></span><input type="checkbox" name="inoui_seul" ${v.inoui_seul ? "checked" : ""}></div>
          <div class="interrupteur"><span><b>Correspondance à Paris</b><br><span class="petit">Ignore les trajets qui changent ailleurs (Lyon…)</span></span><input type="checkbox" name="via_paris" ${v.via_paris ? "checked" : ""}></div>
          <div class="interrupteur"><span><b>Analyser les rames</b><br><span class="petit">Plan de salle des 3 meilleurs trains, pour repérer les voitures Océane</span></span><input type="checkbox" name="analyser_rames" ${v.analyser_rames ? "checked" : ""}></div>
          <div class="interrupteur"><span><b>Suivre le prix chaque jour</b><br><span class="petit">Le robot revérifie et te prévient si ça baisse</span></span><input type="checkbox" name="suivi" ${v.suivi ? "checked" : ""}></div>
          <div class="deux" style="padding-top:6px"><div class="champ"><label>Heure du passage quotidien</label><select name="heure_suivi">${Array.from({ length: 24 }, (_, h) => `<option value="${h}" ${h == v.heure_suivi ? "selected" : ""}>${h} h</option>`).join("")}</select></div>
          <div class="champ"><label>Me prévenir sous (€, facultatif)</label><input type="number" min="0" step="1" name="seuil" value="${esc(v.seuil == null ? "" : v.seuil)}"></div></div>
        </div>
        <div id="f-erreur" class="erreur-txt"></div>
        <div class="ligne"><button class="btn principal">${r ? "Enregistrer et relancer" : "Lancer la recherche"}</button><a class="btn fantome" href="${r ? "#/r/" + r.id : "#/"}">Annuler</a></div>
      </form>`);
    const f = document.getElementById("f-rech");
    const dessinerV = () => {
      document.getElementById("voyageurs").innerHTML = voyageurs.map(ligneV).join("");
      f.querySelectorAll("[data-age]").forEach((el) => el.oninput = () => voyageurs[el.dataset.age].age = Number(el.value));
      f.querySelectorAll("[data-carte]").forEach((el) => el.onchange = () => voyageurs[el.dataset.carte].carte = el.value);
      f.querySelectorAll("[data-retirer]").forEach((el) => el.onclick = () => { voyageurs.splice(Number(el.dataset.retirer), 1); dessinerV(); });
    };
    dessinerV();
    document.getElementById("b-ajout-v").onclick = () => { if (voyageurs.length < 6) { voyageurs.push({ age: 30, carte: "" }); dessinerV(); } };
    f.avec_retour.onchange = () => document.getElementById("bloc-retour").style.display = f.avec_retour.checked ? "grid" : "none";
    f.onsubmit = async (e) => {
      e.preventDefault();
      const d = new FormData(f);
      const err = (m) => document.getElementById("f-erreur").textContent = m;
      if (d.get("aller_fin") < d.get("aller_debut")) return err("La fin de la période aller est avant son début.");
      if (ecart(d.get("aller_debut"), d.get("aller_fin")) > 92) return err("Période aller limitée à 3 mois.");
      const retour = f.avec_retour.checked;
      if (retour && (!d.get("retour_debut") || !d.get("retour_fin") || d.get("retour_fin") < d.get("retour_debut"))) return err("Indique une période de retour valide.");
      if (!voyageurs.length) return err("Ajoute au moins un voyageur.");
      const ligne = {
        origine: d.get("origine").trim(), destination: d.get("destination").trim(),
        aller_debut: d.get("aller_debut"), aller_fin: d.get("aller_fin"),
        retour_debut: retour ? d.get("retour_debut") : null, retour_fin: retour ? d.get("retour_fin") : null,
        nuits_min: Number(d.get("nuits_min") || 0), nuits_max: d.get("nuits_max") === "" || d.get("nuits_max") == null ? null : Number(d.get("nuits_max")),
        classe: f.premiere.checked ? "1re" : "2de", inoui_seul: f.inoui_seul.checked, via_paris: f.via_paris.checked,
        analyser_rames: f.analyser_rames.checked, suivi: f.suivi.checked, heure_suivi: Number(d.get("heure_suivi")),
        seuil: d.get("seuil") === "" ? null : Number(d.get("seuil")),
        voyageurs: voyageurs.map((x) => ({ age: Number(x.age) || 30, carte: x.carte || "" })), chiens: Number(d.get("chiens")),
        statut: "en_attente", progression: 0, message: "En attente du robot du Mac", prochaine_execution: new Date().toISOString(),
      };
      ligne.nom = ligne.origine + " → " + ligne.destination;
      const q = r ? sb.from("train_recherches").update(ligne).eq("id", r.id).select().single()
                  : sb.from("train_recherches").insert(ligne).select().single();
      const { data, error } = await q;
      if (error) return err(error.message);
      go("#/r/" + data.id);
    };
  }

  // ---------------------------------------------------------------- détail
  async function vueDetail(id, silencieux) {
    const r = E.recherches.find((x) => x.id === id);
    if (!r) return cadre("accueil", `<div class="carte vide">Recherche introuvable. <a href="#/">Retour</a></div>`);
    if (!E.detail || E.detail.id !== id) {
      E.detail = { id }; E.sens = "aller"; E.jourChoisi = null; E.filtreParis = r.via_paris; E.filtreOceane = false;
    }
    const ex = (await sb.from("train_executions").select("*").eq("recherche_id", id).order("debut", { ascending: false }).limit(90)).data || [];
    const enCours = ex.find((e) => e.statut === "en_cours");
    const derniere = ex.find((e) => e.statut === "terminee");
    let source = derniere;
    if (enCours && (!derniere || r.statut === "en_cours")) source = enCours;
    let releves = [];
    if (source) releves = await toutLire(() => sb.from("train_releves").select("*").eq("execution_id", source.id).order("jour").order("depart"));
    if (source === enCours && releves.length === 0 && derniere) {
      source = derniere;
      releves = await toutLire(() => sb.from("train_releves").select("*").eq("execution_id", derniere.id).order("jour").order("depart"));
    }
    const nums = [...new Set(releves.flatMap((t) => (t.legs || []).filter((l) => l.type === "TGV INOUI").map((l) => l.num)))];
    let voitures = [], analyses = [];
    if (nums.length) {
      voitures = (await sb.from("train_voitures").select("numero_train,jour,voiture,signature,classe").in("numero_train", nums).limit(5000)).data || [];
      analyses = (await sb.from("train_analyses").select("*").in("numero", nums).order("created_at", { ascending: false }).limit(500)).data || [];
    }
    E.detail = Object.assign(E.detail, { r, ex, source, releves, voitures, analyses });
    dessinerDetail();
  }

  function etiquettesDuTrain(num, jour) {
    const v = E.detail.voitures.filter((x) => x.numero_train === num);
    const duJour = v.filter((x) => x.jour === jour);
    const base = duJour.length ? duJour : v;
    const lab = {};
    for (const x of base) { const e = E.etiquettes[x.signature]; if (e) (lab[e.etiquette] = lab[e.etiquette] || new Set()).add(x.voiture); }
    return { labels: lab, observe: v.length > 0, memeJour: duJour.length > 0 };
  }

  function trajetOceane(t) {
    return (t.legs || []).some((l) => Object.keys(etiquettesDuTrain(l.num, t.jour).labels).some((k) => /oc[ée]ane/i.test(k)));
  }

  function filtrer(liste) {
    return liste.filter((t) => (!E.filtreParis || !t.via || t.via.includes("Paris")) && (!E.filtreOceane || trajetOceane(t)));
  }

  function minsParJour(sens) {
    const m = {};
    for (const t of filtrer(E.detail.releves.filter((x) => x.sens === sens))) {
      const v = Number(t.total);
      if (!(t.jour in m) || v < m[t.jour].total) m[t.jour] = { total: v, t };
    }
    return m;
  }

  function meilleuresPaires(r, mA, mR) {
    const out = [];
    for (const [ja, a] of Object.entries(mA)) for (const [jr, b] of Object.entries(mR)) {
      const n = ecart(ja, jr);
      if (n < (r.nuits_min || 0) || (r.nuits_max != null && n > r.nuits_max)) continue;
      out.push({ ja, jr, n, total: a.total + b.total, a: a.t, b: b.t });
    }
    return out.sort((x, y) => x.total - y.total).slice(0, 3);
  }

  function dessinerDetail() {
    const { r, ex, source, releves } = E.detail;
    const aRetour = !!r.retour_debut;
    const sens = aRetour ? E.sens : "aller";
    const mA = minsParJour("aller"), mR = minsParJour("retour");
    const mins = sens === "aller" ? mA : mR;
    const debut = sens === "aller" ? r.aller_debut : r.retour_debut;
    const fin = sens === "aller" ? r.aller_fin : r.retour_fin;
    const paires = aRetour ? meilleuresPaires(r, mA, mR) : [];
    const voyageurs = (r.voyageurs || []).map((v) => v.age + " ans" + (v.carte ? " · " + v.carte.replace("Carte ", "") : "")).join(", ");

    const entete = `<div class="ligne"><div><h1>${esc(r.origine)} → ${esc(r.destination)}</h1>
        <div class="ligne petit">${court(r.aller_debut)} → ${court(r.aller_fin)}${aRetour ? " · retour " + court(r.retour_debut) + " → " + court(r.retour_fin) : ""}
        · ${esc(r.classe)}${r.inoui_seul ? " · TGV INOUI" : ""} · ${esc(voyageurs)}${r.chiens ? " · " + r.chiens + " chien" + (r.chiens > 1 ? "s" : "") : ""}</div></div>
        <span class="espace"></span>${pastilleStatut(r)}</div>
      ${["en_cours", "en_attente"].includes(r.statut) ? `<div style="margin-top:10px" class="barre"><i style="width:${r.progression || 0}%"></i></div>` : ""}
      ${r.message ? `<p class="petit" style="margin:8px 0 0">${esc(r.message)}${r.statut === "en_attente" && !robotEnLigne() ? " — le Mac semble éteint ou le robot arrêté." : ""}</p>` : ""}
      ${source ? `<p class="petit" style="margin:4px 0 0">Prix relevés ${ilya(source.fin || source.debut)}${source.statut === "en_cours" ? " (en cours)" : ""}.</p>` : ""}
      <div class="ligne" style="margin-top:12px">
        <button class="btn petit-btn" id="b-relancer" ${["en_cours", "en_attente"].includes(r.statut) ? "disabled" : ""}>↻ Relancer</button>
        <button class="btn petit-btn" id="b-suivi">${r.suivi ? "Arrêter le suivi" : "Suivre chaque jour"}</button>
        <a class="btn petit-btn" href="#/r/${r.id}/modifier">Modifier</a>
        <button class="btn petit-btn fantome" id="b-archiver">${r.archive ? "Désarchiver" : "Archiver"}</button>
        <button class="btn petit-btn fantome" id="b-suppr">Supprimer</button></div>`;

    if (!releves.length) {
      cadre("accueil", entete + `<div class="carte vide" style="margin-top:20px">${["en_attente", "en_cours"].includes(r.statut)
        ? "Le robot du Mac va remplir SNCF Connect et balayer les jours. Les prix apparaîtront ici au fur et à mesure."
        : "Pas encore de prix pour cette recherche."}</div>`);
      return brancherDetail();
    }

    const pairesHtml = paires.length ? `<h2>Meilleurs allers-retours</h2><div class="paires">${paires.map((p) => `<div class="carte paire">
        <span class="petit">${p.n} nuit${p.n > 1 ? "s" : ""}</span><span class="total">${euros(p.total)}</span>
        <span><b>${Maj(jourFr(p.ja))}</b> ${esc(p.a.depart)} · ${euros(Number(p.a.total))}</span>
        <span><b>${Maj(jourFr(p.jr))}</b> ${esc(p.b.depart)} · ${euros(Number(p.b.total))}</span></div>`).join("")}</div>` : "";

    const valeurs = Object.values(mins).map((x) => x.total).sort((a, b) => a - b);
    const vmin = valeurs[0], vmax = valeurs[valeurs.length - 1];
    const podium = Object.entries(mins).sort((a, b) => a[1].total - b[1].total).slice(0, 3).map((x) => x[0]);
    const niveau = (v) => vmax === vmin ? 1 : 1 + Math.min(4, Math.floor((v - vmin) / (vmax - vmin) * 5));
    const joursVus = new Set(releves.filter((t) => t.sens === sens).map((t) => t.jour));

    let calendrier = "";
    if (debut && fin) {
      const d0 = dateDe(debut), d1 = dateDe(fin);
      for (let m = new Date(d0.getFullYear(), d0.getMonth(), 1); m <= d1; m = new Date(m.getFullYear(), m.getMonth() + 1, 1)) {
        let cases = JOURS_C.map((j) => `<div class="entete-j">${j}</div>`).join("") + '<div></div>'.repeat(jourSem(m));
        for (let d = new Date(m); d.getMonth() === m.getMonth(); d.setDate(d.getDate() + 1)) {
          const iso = isoDe(d);
          const dans = iso >= debut && iso <= fin;
          const x = mins[iso];
          if (x) cases += `<button class="case n${niveau(x.total)} ${E.jourChoisi === iso ? "choisi" : ""}" data-jour="${iso}">
              ${podium.includes(iso) ? '<span class="etoile">★</span>' : ""}<span class="num">${d.getDate()}</span>
              <span class="cprix">${euros(x.total)}</span><span class="cheure">${esc(x.t.depart)}</span></button>`;
          else if (dans && joursVus.size && iso <= [...joursVus].sort().pop()) cases += `<button class="case rien ${E.jourChoisi === iso ? "choisi" : ""}" data-jour="${iso}"><span class="num">${d.getDate()}</span><span class="cheure">aucun</span></button>`;
          else cases += `<div class="case hors"><span class="num">${d.getDate()}</span></div>`;
        }
        calendrier += `<section class="mois"><h3>${Maj(MOIS[m.getMonth()])} ${m.getFullYear()}</h3><div class="grille">${cases}</div></section>`;
      }
    }

    const jour = E.jourChoisi && E.jourChoisi >= debut && E.jourChoisi <= fin ? E.jourChoisi : podium[0];
    const duJour = filtrer(releves.filter((t) => t.sens === sens && t.jour === jour)).sort((a, b) => a.total - b.total);
    const top = filtrer(releves.filter((t) => t.sens === sens)).sort((a, b) => a.total - b.total).slice(0, 10);

    cadre("accueil", entete + pairesHtml + `
      <div class="ligne" style="margin-top:24px">
        ${aRetour ? `<div class="onglets"><button data-sens="aller" class="${sens === "aller" ? "actif" : ""}">Aller</button><button data-sens="retour" class="${sens === "retour" ? "actif" : ""}">Retour</button></div>` : ""}
        <span class="espace"></span>
        <button class="btn petit-btn ${E.filtreParis ? "principal" : ""}" id="f-paris">Correspondance à Paris</button>
        <button class="btn petit-btn ${E.filtreOceane ? "principal" : ""}" id="f-oceane">Rames Océane</button></div>
      <h2>Calendrier ${aRetour ? (sens === "aller" ? "aller" : "retour") : ""}</h2>
      <p class="legende">moins cher <i class="n1"></i><i class="n2"></i><i class="n3"></i><i class="n4"></i><i class="n5"></i> plus cher · ★ top 3 · prix pour tous les voyageurs${r.chiens ? ", chien compris" : ""}</p>
      ${valeurs.length ? calendrier : `<div class="carte vide">Aucun train ne passe les filtres.</div>`}
      ${jour ? `<h2>${Maj(jourFr(jour))}</h2><div class="trains">${duJour.length ? duJour.map((t) => carteTrain(t, false)).join("") : '<div class="carte vide">Aucun train ce jour-là avec ces filtres.</div>'}</div>` : ""}
      <h2>Les 10 trains les moins chers ${aRetour ? "(" + sens + ")" : ""}</h2><div class="trains">${top.map((t) => carteTrain(t, true)).join("")}</div>
      ${blocEvolution(ex)}${blocTendances(sens)}`);
    brancherDetail();
  }

  function carteTrain(t, avecJour) {
    const legs = (t.legs || []).map((l, i, arr) => {
      const et = etiquettesDuTrain(l.num, t.jour);
      const labels = Object.entries(et.labels).map(([k, s]) => `<span class="pastille ${/oc[ée]ane/i.test(k) ? "oceane" : ""}">${esc(k)} · voit. ${[...s].sort((a, b) => a - b).join(", ")}</span>`).join("");
      const an = E.detail.analyses.find((a) => a.numero === l.num && a.jour === t.jour);
      let bouton = "";
      if (l.type === "TGV INOUI") {
        if (an && ["en_attente", "en_cours"].includes(an.statut)) bouton = `<span class="pastille attente">plan en cours…</span>`;
        else if (et.memeJour) bouton = `<a class="btn petit-btn fantome" href="#/rames">Voir le plan</a>`;
        else bouton = `<button class="btn petit-btn fantome" data-analyser='${esc(JSON.stringify({ jour: t.jour, origine: (l.de || "").split(" - ")[0], destination: (l.a || "").split(" - ")[0], depart: l.dep, numero: l.num }))}'>Analyser la rame</button>`;
        if (an && an.statut === "erreur") bouton += `<span class="petit" title="${esc(an.message)}">échec</span>`;
      }
      const changement = i < arr.length - 1 && l.a && arr[i + 1].de && l.a !== arr[i + 1].de
        ? `<div class="changement">↳ Changement de gare : ${esc(gare(l.a))} → ${esc(gare(arr[i + 1].de))}</div>` : "";
      return `<div><div class="leg"><span class="num">${esc(l.type)} ${esc(l.num)}</span><span class="petit">${esc(l.dep)} ${esc(gare(l.de))} → ${esc(l.arr)} ${esc(gare(l.a))}</span>
        <span class="pastille">${esc(l.classe || "")}</span>${l.choix_place ? '<span class="pastille">choix de place</span>' : ""}${labels}${bouton}</div>${changement}</div>`;
    }).join("");
    return `<div class="train"><div><div class="heures">${avecJour ? `<span class="petit" style="font-weight:600">${Maj(jourFr(t.jour))} · </span>` : ""}${esc(t.depart)} → ${esc(t.arrivee)}</div>
        <div class="petit">${esc(t.duree)} · ${esc(t.correspondances)}${t.via ? " · via " + esc(gare(t.via)) : ""} · ${esc(t.tarif)}</div></div>
      <div class="prix">${euros(Number(t.total))}${Number(t.chien) ? `<div class="petit">dont chien ${t.chien_estime ? "≈ " : ""}${euros(Number(t.chien))}</div>` : ""}</div>
      <div class="legs">${legs}</div></div>`;
  }

  function blocEvolution(ex) {
    const pts = ex.filter((e) => e.statut === "terminee" && e.meilleur_total != null).slice().reverse();
    if (pts.length < 2) return "";
    const W = 640, H = 180, P = 32;
    const vs = pts.map((p) => Number(p.meilleur_total));
    const lo = Math.min(...vs), hi = Math.max(...vs), span = hi - lo || 1;
    const x = (i) => P + i * (W - 2 * P) / (pts.length - 1);
    const y = (v) => H - P - (v - lo) / span * (H - 2 * P);
    const ligne = pts.map((p, i) => `${x(i)},${y(Number(p.meilleur_total))}`).join(" ");
    const etiq = (p) => { const d = new Date(p.debut); return d.getDate() + "/" + (d.getMonth() + 1); };
    return `<h2>Évolution du meilleur prix</h2><div class="carte"><svg class="graph" viewBox="0 0 ${W} ${H}" role="img" aria-label="Évolution du meilleur prix">
      <line class="axe" x1="${P}" y1="${H - P}" x2="${W - P}" y2="${H - P}"/>
      <text x="4" y="${y(hi) + 4}">${euros(hi)}</text><text x="4" y="${y(lo) + 4}">${euros(lo)}</text>
      <polyline class="ligne-prix" points="${ligne}"/>
      ${pts.map((p, i) => `<circle class="pt" cx="${x(i)}" cy="${y(Number(p.meilleur_total))}" r="3.5"><title>${etiq(p)} : ${euros(Number(p.meilleur_total))}</title></circle>`).join("")}
      <text x="${P}" y="${H - 10}">${etiq(pts[0])}</text><text x="${W - P}" y="${H - 10}" text-anchor="end">${etiq(pts[pts.length - 1])}</text>
    </svg><p class="petit" style="margin:6px 0 0">Meilleur ${E.detail.r.retour_debut ? "aller-retour" : "prix"} à chaque passage du robot (${pts.length} passages).</p></div>`;
  }

  function blocTendances(sens) {
    const liste = filtrer(E.detail.releves.filter((t) => t.sens === sens));
    if (liste.length < 10) return "";
    const parJour = {};
    for (const [iso, x] of Object.entries(minsParJour(sens))) (parJour[jourSem(dateDe(iso))] = parJour[jourSem(dateDe(iso))] || []).push(x.total);
    const moy = JOURS_C.map((j, i) => parJour[i] ? parJour[i].reduce((a, b) => a + b, 0) / parJour[i].length : null);
    const max = Math.max(...moy.filter((v) => v != null));
    const W = 640, H = 160, bw = 56;
    const barres = moy.map((v, i) => v == null ? "" : `<rect class="baton" x="${30 + i * 86}" y="${H - 28 - (v / max) * (H - 50)}" width="${bw}" height="${(v / max) * (H - 50)}" rx="5"><title>${euros(v)}</title></rect>
        <text x="${30 + i * 86 + bw / 2}" y="${H - 28 - (v / max) * (H - 50) - 6}" text-anchor="middle">${Math.round(v)} €</text>`).join("") +
      JOURS_C.map((j, i) => `<text x="${30 + i * 86 + bw / 2}" y="${H - 8}" text-anchor="middle">${j}</text>`).join("");
    const parTrain = {};
    for (const t of liste) { const k = t.depart + " · " + (t.numeros || []).join(" + "); (parTrain[k] = parTrain[k] || []).push(Number(t.total)); }
    const lignes = Object.entries(parTrain).filter(([, v]) => v.length >= 2).map(([k, v]) => ({ k, n: v.length, moy: v.reduce((a, b) => a + b, 0) / v.length, min: Math.min(...v) }))
      .sort((a, b) => a.moy - b.moy).slice(0, 6);
    return `<h2>Tendances</h2><div class="carte"><h3>Prix moyen du meilleur train selon le jour de la semaine</h3>
      <svg class="graph" viewBox="0 0 ${W} ${H}" role="img" aria-label="Prix moyen par jour de la semaine">${barres}</svg></div>
      ${lignes.length ? `<div style="height:10px"></div><div class="defile"><table class="simple"><tr><th>Train (départ · numéros)</th><th>Vu</th><th>Moyenne</th><th>Plus bas</th></tr>
        ${lignes.map((l) => `<tr><td>${esc(l.k)}</td><td>${l.n} j</td><td>${euros(l.moy)}</td><td>${euros(l.min)}</td></tr>`).join("")}</table></div>` : ""}`;
  }

  function brancherDetail() {
    const r = E.detail.r;
    const maj = async (vals) => { const { error } = await sb.from("train_recherches").update(vals).eq("id", r.id); if (error) alert(error.message); route(true); };
    const q = (s) => app.querySelector(s);
    if (q("#b-relancer")) q("#b-relancer").onclick = () => maj({ statut: "en_attente", progression: 0, message: "En attente du robot du Mac", prochaine_execution: new Date().toISOString() });
    if (q("#b-suivi")) q("#b-suivi").onclick = () => maj(r.suivi ? { suivi: false } : { suivi: true, prochaine_execution: new Date().toISOString() });
    if (q("#b-archiver")) q("#b-archiver").onclick = () => maj({ archive: !r.archive, suivi: r.archive ? r.suivi : false });
    if (q("#b-suppr")) q("#b-suppr").onclick = async () => {
      if (!confirm("Supprimer cette recherche et tout son historique de prix ?")) return;
      await sb.from("train_recherches").delete().eq("id", r.id); go("#/");
    };
    app.querySelectorAll("[data-sens]").forEach((b) => b.onclick = () => { E.sens = b.dataset.sens; E.jourChoisi = null; dessinerDetail(); });
    app.querySelectorAll("[data-jour]").forEach((b) => b.onclick = () => { E.jourChoisi = b.dataset.jour; dessinerDetail(); });
    if (q("#f-paris")) q("#f-paris").onclick = () => { E.filtreParis = !E.filtreParis; dessinerDetail(); };
    if (q("#f-oceane")) q("#f-oceane").onclick = () => { E.filtreOceane = !E.filtreOceane; dessinerDetail(); };
    app.querySelectorAll("[data-analyser]").forEach((b) => b.onclick = async () => {
      const d = JSON.parse(b.dataset.analyser);
      b.disabled = true;
      const { error } = await sb.from("train_analyses").insert(Object.assign(d, { recherche_id: r.id, statut: "en_attente" }));
      if (error) alert(error.message); else route(true);
    });
  }

  // ---------------------------------------------------------------- rames
  function dessinPlan(salle) {
    const c = 15, W = salle.cols * c, H = salle.rows * c;
    const formes = salle.cases.map(([col, row, w, h, code]) => {
      const x = col * c, y = row * c, ww = w * c, hh = h * c;
      const t = code[0];
      if (t === "S") {
        const tablette = code.includes("t"), pmr = code.includes("p"), vers = code.slice(-1);
        const dos = vers === "E" ? `<rect class="dos" x="${x + 1}" y="${y + 1.5}" width="2.5" height="${hh - 3}" rx="1"/>` : vers === "W" ? `<rect class="dos" x="${x + ww - 3.5}" y="${y + 1.5}" width="2.5" height="${hh - 3}" rx="1"/>` : "";
        return `<rect class="s ${pmr ? "pmr" : ""}" x="${x + 1}" y="${y + 1}" width="${ww - 2}" height="${hh - 2}" rx="2.5"/>${dos}${tablette ? `<rect class="tab" x="${x + ww / 2 - 1}" y="${y + 3}" width="2" height="${hh - 6}"/>` : ""}`;
      }
      const cls = { T: "table", L: "bag", E: "esc", W: "wc" }[t] || "bag";
      return `<rect class="${cls}" x="${x + (t === "T" ? 3 : 1)}" y="${y + (t === "T" ? 2 : 1)}" width="${ww - (t === "T" ? 6 : 2)}" height="${hh - (t === "T" ? 4 : 2)}" rx="2"/>`;
    }).join("");
    return `<svg class="plan" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Plan de la salle ${salle.salle}">${formes}</svg>`;
  }

  async function vueRames() {
    const [vo, an] = await Promise.all([
      toutLire(() => sb.from("train_voitures").select("*").order("created_at", { ascending: false })),
      sb.from("train_analyses").select("*").order("created_at", { ascending: false }).limit(40),
    ]);
    if (an.error) throw an.error;
    const parSig = {};
    for (const v of vo) {
      const g = parSig[v.signature] = parSig[v.signature] || { sig: v.signature, ex: v, vus: [], trains: new Set() };
      g.vus.push(v); g.trains.add(v.numero_train);
    }
    const groupes = Object.values(parSig).sort((a, b) => (E.etiquettes[b.sig] ? 1 : 0) - (E.etiquettes[a.sig] ? 1 : 0) || b.vus.length - a.vus.length);
    const parTrain = {};
    for (const v of vo) {
      const t = parTrain[v.numero_train] = parTrain[v.numero_train] || { jours: new Set(), lab: {} };
      t.jours.add(v.jour);
      const e = E.etiquettes[v.signature];
      if (e) (t.lab[e.etiquette] = t.lab[e.etiquette] || new Set()).add(v.jour);
    }
    const motifs = Object.entries(parTrain).sort((a, b) => b[1].jours.size - a[1].jours.size).map(([num, t]) => {
      const labs = Object.entries(t.lab).map(([k, s]) => `<span class="pastille ${/oc[ée]ane/i.test(k) ? "oceane" : ""}">${esc(k)} ${s.size}/${t.jours.size} jours</span>`).join(" ");
      return `<tr><td><b>${esc(num)}</b></td><td>${t.jours.size}</td><td>${labs || '<span class="petit">aucune voiture marquée</span>'}</td></tr>`;
    }).join("");
    const enCours = an.data.filter((a) => ["en_attente", "en_cours", "erreur"].includes(a.statut)).slice(0, 8);

    cadre("rames", `<h1>Rames</h1>
      <p class="sous">SNCF Connect n'écrit pas le type de rame. Le robot relève donc le plan de salle de chaque voiture : orientation des sièges,
      tablettes, tables, salle basse ou haute. Chaque plan identique reçoit la même empreinte. Marque une empreinte « Océane » une fois :
      l'app reconnaîtra ces voitures dans tous tes trains.</p>
      ${enCours.length ? `<h2>Analyses</h2><div class="trains">${enCours.map((a) => `<div class="carte ligne"><b>${esc(a.numero || "")}</b>
        <span class="petit">${esc(a.origine)} → ${esc(a.destination)} · ${Maj(jourFr(a.jour))} ${esc(a.depart)}</span><span class="espace"></span>
        <span class="pastille ${a.statut === "erreur" ? "erreur" : "attente"}">${a.statut === "erreur" ? "échec" : a.statut === "en_cours" ? "en cours" : "en attente"}</span>
        ${a.message ? `<span class="petit">${esc(a.message)}</span>` : ""}</div>`).join("")}</div>` : ""}
      <h2>Analyser un train</h2>
      <form class="carte" id="f-analyse" style="display:grid;gap:10px">
        <div class="trois"><div class="champ"><label>Jour</label><input type="date" name="jour" required></div>
        <div class="champ"><label>Départ (heure)</label><input type="time" name="depart" required></div>
        <div class="champ"><label>N° du train</label><input name="numero" inputmode="numeric" placeholder="8913"></div></div>
        <div class="deux"><div class="champ"><label>De</label><input name="origine" list="gares2" value="Paris" required></div>
        <div class="champ"><label>À</label><input name="destination" list="gares2" value="Le Mans" required></div></div>
        <datalist id="gares2"><option>Paris<option>Le Mans<option>Nice<option>Nantes<option>Lyon<option>Marseille</datalist>
        <div><button class="btn principal">Demander le plan au robot</button></div></form>
      ${motifs ? `<h2>Trains déjà observés</h2><div class="defile"><table class="simple"><tr><th>Train</th><th>Jours vus</th><th>Voitures marquées</th></tr>${motifs}</table></div>` : ""}
      <h2>Empreintes de voitures</h2>
      ${groupes.length ? `<div class="emp">${groupes.map(blocEmpreinte).join("")}</div>` : `<div class="carte vide">Aucun plan de salle relevé pour l'instant. Lance une recherche avec « Analyser les rames », ou demande un train ci-dessus.</div>`}`);

    document.getElementById("f-analyse").onsubmit = async (e) => {
      e.preventDefault();
      const d = Object.fromEntries(new FormData(e.target));
      d.numero = (d.numero || "").trim() || null;
      d.statut = "en_attente";
      const { error } = await sb.from("train_analyses").insert(d);
      if (error) alert(error.message); else route(true);
    };
    app.querySelectorAll("[data-etiq]").forEach((f) => f.onsubmit = async (e) => {
      e.preventDefault();
      const val = new FormData(f).get("etiquette").trim();
      const sig = f.dataset.etiq;
      if (val) await sb.from("train_etiquettes").upsert({ user_id: E.session.user.id, signature: sig, etiquette: val });
      else await sb.from("train_etiquettes").delete().eq("signature", sig);
      route(true);
    });
  }

  function blocEmpreinte(g) {
    const e = E.etiquettes[g.sig];
    const res = g.ex.resume || {};
    const salles = (res.salles || []).map((s, i) => {
      const plan = (g.ex.plan || [])[i];
      return `<div><div class="chiffres"><span><b>Salle ${esc(s.salle)}</b></span><span><b>${s.sieges}</b> sièges</span><span><b>${s.tablettes}</b> à tablette</span>
        <span><b>${s.tables}</b> tables</span><span><b>${s.sens_majoritaire}/${s.sens_minoritaire}</b> sens</span>${s.isolees ? `<span><b>${s.isolees}</b> isolés</span>` : ""}${s.pmr ? `<span><b>${s.pmr}</b> PMR</span>` : ""}</div>
        ${plan ? `<div class="defile" style="margin-top:6px">${dessinPlan(plan)}</div>` : ""}</div>`;
    }).join("");
    const trains = [...g.trains].slice(0, 8).join(", ");
    return `<div class="carte" style="display:grid;gap:10px">
      <div class="ligne"><b>Empreinte ${esc(g.sig)}</b><span class="pastille">${esc(g.ex.classe)}</span>
        ${e ? `<span class="pastille ${/oc[ée]ane/i.test(e.etiquette) ? "oceane" : "accent"}">${esc(e.etiquette)}</span>` : ""}
        <span class="espace"></span><span class="petit">vue ${g.vus.length} fois · trains ${esc(trains)}</span></div>
      ${salles}
      <form class="ligne" data-etiq="${esc(g.sig)}"><input name="etiquette" list="etiquettes" value="${esc(e ? e.etiquette : "")}" placeholder="Océane, Duplex classique…" style="border:1px solid var(--trait);border-radius:8px;padding:6px 9px;background:var(--carte);min-width:200px">
        <datalist id="etiquettes"><option>Océane<option>Duplex classique<option>Réseau<option>À éviter</datalist>
        <button class="btn petit-btn">Enregistrer</button></form></div>`;
  }

  // ---------------------------------------------------------------- réglages
  function vueReglages() {
    const r = E.robot;
    cadre("reglages", `<h1>Réglages</h1>
      <div class="carte" style="display:grid;gap:8px"><h3 style="margin:0">Robot du Mac</h3>
        <div>${robotEnLigne() ? `✅ En ligne (${ilya(r.vu_le)})${r.occupe ? " · " + esc(r.occupe) : ""}` : r ? `⚠️ Dernier signe ${ilya(r.vu_le)}. Le Mac est peut-être en veille ou éteint.` : "⚠️ Le robot ne s'est jamais connecté."}</div>
        <p class="petit" style="margin:0">Le robot tourne en fond sur ton Mac (dossier <b>robot</b>, installé avec <code>bash installer.sh</code>).
        Il ouvre une fenêtre Chrome pendant ses recherches : laisse-la travailler. Si SNCF Connect affiche une vérification, fais-la dans cette fenêtre.
        Pour voir ce qu'il fait : <code>bash installer.sh journal</code>.</p></div>
      <div style="height:12px"></div>
      <div class="carte" style="display:grid;gap:8px"><h3 style="margin:0">Alertes sur l'iPhone</h3>
        <p class="petit" style="margin:0">Installe l'app gratuite <b>ntfy</b>, abonne-toi au sujet choisi pendant l'installation du robot :
        chaque baisse de prix t'envoie une notification. Le Mac affiche aussi une notification.</p></div>
      <div style="height:12px"></div>
      <div class="carte" style="display:grid;gap:8px"><h3 style="margin:0">Compte</h3>
        <div>${esc(E.session.user.email)}</div>
        <div class="ligne"><button class="btn" id="b-deco">Se déconnecter</button>
        ${localStorage.getItem("premiere.url") ? `<button class="btn fantome" id="b-reset">Changer de projet Supabase</button>` : ""}</div></div>`);
    document.getElementById("b-deco").onclick = () => sb.auth.signOut();
    const reset = document.getElementById("b-reset");
    if (reset) reset.onclick = () => { localStorage.removeItem("premiere.url"); localStorage.removeItem("premiere.cle"); location.reload(); };
  }

  demarrer();
})();
