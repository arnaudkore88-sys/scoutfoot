"""
Récupère les matchs du jour via API-Football, lance le moteur d'analyse et enregistre :
  - analyse_du_jour.json  : les marchés et combinés (à brancher sur l'application)
  - predictions.jsonl     : journal de toutes les prédictions (pour mesurer la fiabilité)

Utilisation :
    export API_FOOTBALL_KEY="votre_cle"
    python3 analyse_du_jour.py --date 2026-09-30 --ligues 61 39 135

Vérifiez les noms de paramètres et les limites de votre offre dans la documentation
d'API-Football (l'offre gratuite est limitée en nombre de requêtes par jour).
Ce script n'a pas pu être testé ici sans accès réseau : testez d'abord sur 1 ou 2 matchs.
"""
import argparse
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

import calibration
import moteur_analyse as moteur

BASE = "https://v3.football.api-sports.io"
CACHE = ".cache_api"


# ---------- appel API avec cache disque (économise les requêtes) ----------
def appel(chemin, params, ttl=6 * 3600):
    cle = os.environ.get("API_FOOTBALL_KEY")
    if not cle:
        raise SystemExit("Définissez la variable d'environnement API_FOOTBALL_KEY.")
    os.makedirs(CACHE, exist_ok=True)
    url = f"{BASE}{chemin}?{urllib.parse.urlencode(params)}"
    fichier = os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest() + ".json")
    if os.path.exists(fichier) and time.time() - os.path.getmtime(fichier) < ttl:
        with open(fichier, encoding="utf-8") as f:
            return json.load(f)
    for essai in range(3):
        try:
            req = urllib.request.Request(url, headers={"x-apisports-key": cle})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
            break
        except Exception as e:
            if essai == 2:
                raise
            time.sleep(2 * (essai + 1))
    if data.get("errors"):
        raise SystemExit(f"Erreur API : {data['errors']}")
    with open(fichier, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def jours_depuis(iso):
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return max(0, (datetime.now(timezone.utc) - d).days)


# ---------- données ----------
def matchs_du_jour(jour, ligues):
    """Liste des matchs à venir, filtrés sur les ligues demandées (identifiants API)."""
    data = appel("/fixtures", {"date": jour}, ttl=1800)
    out = []
    for f in data["response"]:
        if ligues and f["league"]["id"] not in ligues:
            continue
        out.append({
            "id": f["fixture"]["id"], "ligue": f["league"]["name"], "ligue_id": f["league"]["id"],
            "saison": f["league"]["season"],
            "dom": f["teams"]["home"]["name"], "dom_id": f["teams"]["home"]["id"],
            "ext": f["teams"]["away"]["name"], "ext_id": f["teams"]["away"]["id"],
            "heure": f["fixture"].get("date"),
            "logo_dom": f["teams"]["home"].get("logo"), "logo_ext": f["teams"]["away"].get("logo"),
        })
    return out


def historique_equipe(equipe_id, n=10):
    """[(buts_marqués, buts_encaissés, jours_depuis_le_match), ...] sur les n derniers matchs."""
    data = appel("/fixtures", {"team": equipe_id, "last": n, "status": "FT"})
    res = []
    for f in data["response"]:
        est_dom = f["teams"]["home"]["id"] == equipe_id
        gf = f["goals"]["home"] if est_dom else f["goals"]["away"]
        ga = f["goals"]["away"] if est_dom else f["goals"]["home"]
        if gf is None or ga is None:
            continue
        res.append((gf, ga, jours_depuis(f["fixture"]["date"])))
    return res


def moyennes_championnat(ligue_id, saison):
    """Moyenne de buts à domicile et à l'extérieur sur les matchs terminés de la saison."""
    data = appel("/fixtures", {"league": ligue_id, "season": saison, "status": "FT"}, ttl=24 * 3600)
    dom = [f["goals"]["home"] for f in data["response"] if f["goals"]["home"] is not None]
    ext = [f["goals"]["away"] for f in data["response"] if f["goals"]["away"] is not None]
    if len(dom) < 30:  # début de saison : valeurs par défaut prudentes
        return 1.50, 1.20
    return sum(dom) / len(dom), sum(ext) / len(ext)


def corners_cartons_moyens(equipe_id, n=5):
    """Moyenne (corners, cartons jaunes) de l'équipe sur ses n derniers matchs.
    Coûteux : 1 requête par match. À activer avec --details seulement."""
    data = appel("/fixtures", {"team": equipe_id, "last": n, "status": "FT"})
    corners, cartons = [], []
    for f in data["response"]:
        st = appel("/fixtures/statistics", {"fixture": f["fixture"]["id"], "team": equipe_id}, ttl=7 * 24 * 3600)
        for bloc in st["response"]:
            valeurs = {s["type"]: s["value"] for s in bloc["statistics"]}
            if valeurs.get("Corner Kicks") is not None:
                corners.append(valeurs["Corner Kicks"])
            if valeurs.get("Yellow Cards") is not None:
                cartons.append(valeurs["Yellow Cards"])
    moy = lambda l: sum(l) / len(l) if l else None
    return moy(corners), moy(cartons)


# ---------- programme principal ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--ligues", nargs="*", type=int, default=[], help="identifiants de ligues API-Football")
    ap.add_argument("--details", action="store_true", help="inclure corners et cartons (plus de requêtes)")
    ap.add_argument("--max", type=int, default=10, help="nombre maximum de matchs analysés")
    a = ap.parse_args()

    matchs = matchs_du_jour(a.date, a.ligues)[: a.max]
    print(f"{len(matchs)} match(s) trouvé(s) pour le {a.date}")
    analyses, journal, infos = {}, [], {}
    points_calib = calibration.charger()
    print("Calibration appliquée." if points_calib else "Pas de calibration.json : probabilités brutes.")

    for m in matchs:
        try:
            moy_d, moy_e = moyennes_championnat(m["ligue_id"], m["saison"])
            hist = {m["dom"]: historique_equipe(m["dom_id"]), m["ext"]: historique_equipe(m["ext_id"])}
            if min(len(hist[m["dom"]]), len(hist[m["ext"]])) < 5:
                print(f"  ignoré (historique insuffisant) : {m['dom']} - {m['ext']}")
                continue
            notes = moteur.forces(hist, moy_d, moy_e)
            lh, la = moteur.buts_attendus(notes, m["dom"], m["ext"], moy_d, moy_e)

            corners = cartons = None
            if a.details:
                cd, kd = corners_cartons_moyens(m["dom_id"])
                ce, ke = corners_cartons_moyens(m["ext_id"])
                if None not in (cd, ce):
                    corners = cd + ce
                if None not in (kd, ke):
                    cartons = kd + ke

            nom = f"{m['dom']} - {m['ext']}"
            infos[nom] = {"heure": m["heure"], "ligue": m["ligue"], "dom": m["dom"], "ext": m["ext"],
                          "logo_dom": m["logo_dom"], "logo_ext": m["logo_ext"]}
            analyses[nom] = moteur.marches(m["dom"], m["ext"], lh, la, corners, cartons)
            analyses[nom] = calibration.appliquer(analyses[nom], points_calib)  # sans effet si pas de calibration.json
            journal.append({"fixture_id": m["id"], "date": a.date, "match": nom, "dom": m["dom"], "ext": m["ext"],
                            "buts_attendus": [round(lh, 3), round(la, 3)], "marches": analyses[nom]})
            print(f"  ok : {nom} ({lh:.2f} - {la:.2f})")
        except Exception as e:
            print(f"  erreur sur {m['dom']} - {m['ext']} : {e}")

    with open("analyse_du_jour.json", "w", encoding="utf-8") as f:
        json.dump({"date": a.date, "matchs": analyses, "infos": infos, "combines": moteur.combines(analyses)},
                  f, ensure_ascii=False, indent=2)
    with open("predictions.jsonl", "a", encoding="utf-8") as f:
        for j in journal:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")
    print("Fichiers écrits : analyse_du_jour.json, predictions.jsonl")


if __name__ == "__main__":
    main()
