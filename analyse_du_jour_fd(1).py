"""
Analyse du jour avec football-data.org (alternative gratuite à API-Football).

    set FOOTBALL_DATA_KEY=votre_jeton
    python analyse_du_jour_fd.py --date 2026-09-30 --ligues PL PD SA BL1 FL1

Écrit analyse_du_jour.json (pour le site) et ajoute au journal predictions.jsonl.

Codes des compétitions de l'offre gratuite :
  PL Premier League · PD LaLiga · SA Serie A · BL1 Bundesliga · FL1 Ligue 1 · CL Ligue des champions
  DED Eredivisie · PPL Primeira Liga · ELC Championship · BSA Brasileirão · WC Coupe du monde · EC Euro

Limites de l'offre gratuite : pas de corners ni de cartons, saison en cours seulement,
10 appels par minute (la première exécution prend donc quelques minutes).
"""
import argparse
import json
from datetime import date, datetime, timedelta, timezone

import calibration
import fd_api
import moteur_analyse as moteur

IDS = {"PL": 2021, "PD": 2014, "SA": 2019, "BL1": 2002, "FL1": 2015, "CL": 2001,
       "DED": 2003, "PPL": 2017, "ELC": 2016, "BSA": 2013, "WC": 2000, "EC": 2018}


def jours_depuis(iso):
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return max(0, (datetime.now(timezone.utc) - d).days)


def nom(equipe):
    return equipe.get("shortName") or equipe.get("name") or "?"


def matchs_du_jour(jour, codes, nb=1):
    d0 = date.fromisoformat(jour)
    fin = (d0 + timedelta(days=nb)).isoformat()
    jours_ok = {(d0 + timedelta(days=i)).isoformat() for i in range(nb)}
    try:   # requête groupée (un seul appel)
        liste = fd_api.appel("/matches", {"dateFrom": jour, "dateTo": fin,
                                          "competitions": ",".join(str(IDS[c]) for c in codes)},
                             ttl=1800).get("matches", [])
    except fd_api.ErreurFD as e:
        print(f"  requête groupée impossible ({e}) : essai compétition par compétition")
        liste, erreurs = [], []
        for c in codes:
            try:
                d = fd_api.appel(f"/competitions/{c}/matches", {"dateFrom": jour, "dateTo": fin}, ttl=1800)
            except fd_api.ErreurFD as e2:
                erreurs.append(f"{c}: {e2}")
                print(f"  {c} ignorée ({e2})")
                continue
            for m in d.get("matches", []):
                m.setdefault("competition", d.get("competition") or {"name": c, "code": c})
                liste.append(m)
        if not liste and erreurs:
            raise fd_api.ErreurFD("; ".join(erreurs))
    out = []
    for m in liste:
        if m["utcDate"][:10] not in jours_ok or m["status"] not in ("TIMED", "SCHEDULED"):
            continue
        out.append({"id": m["id"], "heure": m["utcDate"], "ligue": m["competition"]["name"],
                    "code": m["competition"].get("code"),
                    "dom": nom(m["homeTeam"]), "dom_id": m["homeTeam"]["id"], "logo_dom": m["homeTeam"].get("crest"),
                    "ext": nom(m["awayTeam"]), "ext_id": m["awayTeam"]["id"], "logo_ext": m["awayTeam"].get("crest")})
    return sorted(out, key=lambda x: x["heure"])


def historique_equipe(equipe_id, n=10):
    """[(buts_marqués, buts_encaissés, jours_depuis_le_match)] sur les n derniers matchs terminés."""
    data = fd_api.appel(f"/teams/{equipe_id}/matches", {"status": "FINISHED"}, ttl=12 * 3600)
    res = []
    for m in sorted(data.get("matches", []), key=lambda x: x["utcDate"]):
        ft = m["score"]["fullTime"]
        if ft.get("home") is None or ft.get("away") is None:
            continue
        est_dom = m["homeTeam"]["id"] == equipe_id
        res.append((ft["home"] if est_dom else ft["away"], ft["away"] if est_dom else ft["home"],
                    jours_depuis(m["utcDate"])))
    return res[-n:]


def moyennes_competition(code):
    data = fd_api.appel(f"/competitions/{code}/matches", {"status": "FINISHED"}, ttl=24 * 3600)
    dom = [m["score"]["fullTime"]["home"] for m in data.get("matches", []) if m["score"]["fullTime"].get("home") is not None]
    ext = [m["score"]["fullTime"]["away"] for m in data.get("matches", []) if m["score"]["fullTime"].get("away") is not None]
    if len(dom) < 30:   # début de saison : valeurs prudentes
        return 1.50, 1.20
    return sum(dom) / len(dom), sum(ext) / len(ext)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--jours", type=int, default=4, help="nombre de jours analysés, aujourd'hui inclus (1 à 7)")
    ap.add_argument("--ligues", nargs="+", default=["PL", "PD", "SA", "BL1", "FL1"])
    ap.add_argument("--max", type=int, default=10, help="nombre maximum de matchs analysés par jour")
    a = ap.parse_args()
    if not 1 <= a.jours <= 7:
        raise SystemExit("--jours doit être compris entre 1 et 7.")
    inconnus = [c for c in a.ligues if c not in IDS]
    if inconnus:
        raise SystemExit(f"Codes inconnus : {inconnus}. Codes valides : {sorted(IDS)}")

    try:
        tous = matchs_du_jour(a.date, a.ligues, a.jours)
    except fd_api.ErreurFD as e:
        raise SystemExit(f"Impossible de récupérer les matchs ({e}). Vérifiez la clé et la connexion.")
    par_jour = {}
    for m in tous:
        par_jour.setdefault(m["heure"][:10], []).append(m)
    matchs = []
    for j in sorted(par_jour):
        matchs += par_jour[j][: a.max]
    print(f"{len(matchs)} match(s) à analyser sur {a.jours} jour(s) à partir du {a.date}")
    points = calibration.charger()
    print("Calibration appliquée." if points else "Pas de calibration.json : probabilités brutes.")

    d0 = date.fromisoformat(a.date)
    jours_out = {(d0 + timedelta(days=i)).isoformat(): {"matchs": {}, "infos": {}, "combines": []}
                 for i in range(a.jours)}
    moyennes, journal = {}, []

    for m in matchs:
        jour = m["heure"][:10]
        try:
            if m["code"] not in moyennes:
                moyennes[m["code"]] = moyennes_competition(m["code"])
            moy_d, moy_e = moyennes[m["code"]]
            hist = {m["dom"]: historique_equipe(m["dom_id"]), m["ext"]: historique_equipe(m["ext_id"])}
            if min(len(hist[m["dom"]]), len(hist[m["ext"]])) < 5:
                print(f"  ignoré (historique insuffisant) : {m['dom']} - {m['ext']}")
                continue
            notes = moteur.forces(hist, moy_d, moy_e)
            lh, la = moteur.buts_attendus(notes, m["dom"], m["ext"], moy_d, moy_e)
            nom_match = f"{m['dom']} - {m['ext']}"
            marches = calibration.appliquer(moteur.marches(m["dom"], m["ext"], lh, la), points)
            jours_out[jour]["matchs"][nom_match] = marches
            jours_out[jour]["infos"][nom_match] = {"heure": m["heure"], "ligue": m["ligue"], "dom": m["dom"], "ext": m["ext"],
                                                   "logo_dom": m["logo_dom"], "logo_ext": m["logo_ext"]}
            journal.append({"source": "fd", "fixture_id": m["id"], "date": jour, "match": nom_match,
                            "dom": m["dom"], "ext": m["ext"], "buts_attendus": [round(lh, 3), round(la, 3)],
                            "marches": marches})
            print(f"  ok : {jour} {nom_match} ({lh:.2f} - {la:.2f})")
        except fd_api.ErreurFD as e:
            print(f"  erreur sur {m['dom']} - {m['ext']} : {e}")

    for jour, contenu in jours_out.items():
        contenu["combines"] = moteur.combines(contenu["matchs"])
    premier = jours_out[a.date]      # les anciennes versions de la page lisent ces trois clés (jour d'aujourd'hui)
    with open("analyse_du_jour.json", "w", encoding="utf-8") as f:
        json.dump({"date": a.date, "jours": jours_out, "matchs": premier["matchs"], "infos": premier["infos"],
                   "combines": premier["combines"]}, f, ensure_ascii=False, indent=2)
    with open("predictions.jsonl", "a", encoding="utf-8") as f:
        for j in journal:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")
    print("Fichiers écrits : analyse_du_jour.json, predictions.jsonl")


if __name__ == "__main__":
    main()
