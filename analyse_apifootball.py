"""
Analyse des matchs de SÉLECTIONS NATIONALES (qualifications, amicaux, CAN, Mondial, Coupe d'Asie, Euro, ligues des
nations...) avec API-Football. Écrit analyse_apif.json ; fusionner.py le combine avec l'analyse des clubs.

    python analyse_apifootball.py                       sélections reconnues par leur nom (aucun numéro à saisir)
    python analyse_apifootball.py --ligues 29 36 10     seulement ces compétitions (numéros : trouver_ligues.py)

Selon votre offre :
  - Offre gratuite : matchs d'hier à demain seulement et AUCUN historique d'équipe -> les matchs sont LISTÉS
    avec la mention « analyse indisponible » (aucun pronostic inventé).
  - Offre Pro : jusqu'à 7 jours et analyse complète (forme, buts attendus, scores, probabilités).
Le quota est surveillé : le programme s'arrête proprement avant d'épuiser la journée.
"""
import argparse
import json
from datetime import date, datetime, timedelta, timezone

import apif_api as api
import ligues_apif as L
import moteur_analyse as moteur


def jour_utc(iso):
    return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y-%m-%d")


def jours_depuis(iso):
    return max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).days)


def matchs_du_jour(jour, ids):
    corps = api.appel("/fixtures", {"date": jour}, ttl=1800)
    out = []
    for f in corps.get("response", []):
        if f["fixture"]["status"]["short"] not in ("NS", "TBD"):
            continue                                   # seulement les matchs pas encore commencés
        lg, dom, ext = f["league"], f["teams"]["home"], f["teams"]["away"]
        if ids:
            if lg["id"] not in ids:
                continue
        elif not L.est_selection_senior(lg["name"], dom["name"], ext["name"]):
            continue
        out.append({"id": f["fixture"]["id"], "heure": f["fixture"]["date"], "jour": jour_utc(f["fixture"]["date"]),
                    "ligue": lg["name"], "dom": dom["name"], "dom_id": dom["id"], "logo_dom": dom.get("logo"),
                    "ext": ext["name"], "ext_id": ext["id"], "logo_ext": ext.get("logo")})
    return out


def historique(equipe_id):
    """[(buts_marqués, buts_encaissés, jours_depuis)] sur les 10 derniers matchs terminés (toutes compétitions)."""
    corps = api.appel("/fixtures", {"team": equipe_id, "last": 10}, ttl=12 * 3600)
    res = []
    for f in corps.get("response", []):
        if f["fixture"]["status"]["short"] not in ("FT", "AET", "PEN"):
            continue
        g = f["goals"]
        if g["home"] is None or g["away"] is None:
            continue
        est_dom = f["teams"]["home"]["id"] == equipe_id
        res.append((g["home"] if est_dom else g["away"], g["away"] if est_dom else g["home"],
                    jours_depuis(f["fixture"]["date"])))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--jours", type=int, default=7)
    ap.add_argument("--ligues", nargs="*", type=int, default=[])
    ap.add_argument("--max", type=int, default=15, help="matchs par jour")
    ap.add_argument("--sans-historique", action="store_true", help="ne pas essayer de calculer de pronostic")
    a = ap.parse_args()

    # 1) offre et quota
    try:
        st = api.appel("/status", ttl=0)["response"]
    except api.ErreurApif as e:
        raise SystemExit(f"Connexion impossible : {e}")
    plan = ((st.get("subscription") or {}).get("plan") or "?")
    req = st.get("requests") or {}
    if req.get("limit_day") is not None and req.get("current") is not None:
        api.etat["restant_jour"] = req["limit_day"] - req["current"]
    gratuit = plan.strip().lower() == "free"
    nb_jours = min(a.jours, 2) if gratuit else min(a.jours, 7)
    historique_ok = not (gratuit or a.sans_historique)
    print(f"Offre : {plan} | requêtes restantes : {api.etat['restant_jour']} | jours demandés : {nb_jours} | "
          f"historique des équipes : {'oui' if historique_ok else 'NON (matchs listés sans pronostic)'}")

    # 2) matchs
    d0 = date.fromisoformat(a.date)
    par_jour = {}
    dernier_ok = None            # dernier jour réellement obtenu (limite de l'offre gratuite : aujourd'hui et demain)
    for i in range(nb_jours):
        jour = (d0 + timedelta(days=i)).isoformat()
        try:
            liste = matchs_du_jour(jour, set(a.ligues))
        except api.ErreurPlan as e:
            print(f"  {jour} : date non permise par votre offre -> arrêt ({e})")
            break
        except api.QuotaEpuise as e:
            print(f"  Quota : {e}")
            break
        except api.ErreurApif as e:
            print(f"  {jour} : erreur ({e}) -> jour ignoré")
            continue
        dernier_ok = jour
        for m in liste:
            par_jour.setdefault(m["jour"], []).append(m)
    matchs = []
    for j in sorted(par_jour):
        matchs += sorted(par_jour[j], key=lambda m: m["heure"])[: a.max]
    print(f"{len(matchs)} match(s) de sélections trouvé(s)")

    # 3) historiques (une seule fois par équipe)
    hist, raison = {}, None
    if historique_ok:
        for m in matchs:
            for eid in (m["dom_id"], m["ext_id"]):
                if eid in hist or not historique_ok:
                    continue
                try:
                    hist[eid] = historique(eid)
                except api.ErreurPlan:
                    historique_ok, raison = False, "Offre gratuite : historique des équipes indisponible"
                    print("  Historique refusé par l'offre -> matchs listés sans pronostic")
                except api.QuotaEpuise as e:
                    historique_ok, raison = False, "Quota du jour presque épuisé"
                    print(f"  Quota : {e}")
                except api.ErreurApif as e:
                    hist[eid] = []
                    print(f"  équipe {eid} : erreur ({e})")
    else:
        raison = "Offre gratuite : historique des équipes indisponible" if gratuit else "Analyse désactivée"

    # 4) pronostics
    jours_out = {(d0 + timedelta(days=i)).isoformat(): {"matchs": {}, "infos": {}, "combines": []} for i in range(nb_jours)}
    toutes = [x for v in hist.values() for x in v]
    base = (sum(gf + ga for gf, ga, _ in toutes) / (2 * len(toutes))) if toutes else 1.25
    moy_d, moy_e = base * 1.08, base * 0.92            # petit avantage du terrain (beaucoup de matchs sont sur terrain neutre)
    journal = []
    for m in matchs:
        nom = f"{m['dom']} - {m['ext']}"
        info = {"heure": m["heure"], "ligue": m["ligue"], "dom": m["dom"], "ext": m["ext"],
                "logo_dom": m["logo_dom"], "logo_ext": m["logo_ext"]}
        hd, he = hist.get(m["dom_id"], []), hist.get(m["ext_id"], [])
        if historique_ok and min(len(hd), len(he)) >= 5:
            notes = moteur.forces({m["dom"]: hd, m["ext"]: he}, moy_d, moy_e)
            lh, la = moteur.buts_attendus(notes, m["dom"], m["ext"], moy_d, moy_e)
            fd_, fe_ = moteur.forme_texte(hd), moteur.forme_texte(he)
            expl = moteur.explication(m["dom"], m["ext"], lh, la, *notes[m["dom"]], *notes[m["ext"]], fd_, fe_)
            expl.append("Sélections nationales : le niveau des adversaires passés n'est pas pris en compte, estimation moins fiable.")
            info.update({"forme_dom": fd_, "forme_ext": fe_, "buts_attendus": [round(lh, 2), round(la, 2)],
                         "scores": moteur.scores_probables(lh, la), "explication": expl})
            marches = moteur.marches(m["dom"], m["ext"], lh, la)
            journal.append({"source": "apif", "fixture_id": m["id"], "date": m["jour"], "match": nom, "dom": m["dom"],
                            "ext": m["ext"], "buts_attendus": [round(lh, 3), round(la, 3)], "marches": marches})
        else:
            marches = []
            info["sans_analyse"] = True
            info["raison"] = raison or "Historique insuffisant (moins de 5 matchs récents)"
        jours_out[m["jour"]]["matchs"][nom] = marches
        jours_out[m["jour"]]["infos"][nom] = info
    for contenu in jours_out.values():
        contenu["combines"] = moteur.combines({k: v for k, v in contenu["matchs"].items() if v})

    with open("analyse_apif.json", "w", encoding="utf-8") as f:
        json.dump({"date": a.date, "plan": plan, "couverture": {"plan": plan, "jusqu_au": dernier_ok}, "jours": jours_out},
                  f, ensure_ascii=False, indent=2)
    with open("predictions.jsonl", "a", encoding="utf-8") as f:
        for j in journal:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")
    analyses = sum(1 for j in jours_out.values() for v in j["matchs"].values() if v)
    print(f"Terminé : {len(matchs)} match(s) écrit(s), dont {analyses} analysé(s). Requêtes restantes aujourd'hui : {api.etat['restant_jour']}")


if __name__ == "__main__":
    main()
