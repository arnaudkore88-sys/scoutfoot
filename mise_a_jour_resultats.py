"""
Complète le journal des prédictions avec les résultats réels des matchs terminés,
puis affiche un rapport de fiabilité (c'est cet historique que vous pourrez montrer
à vos utilisateurs).

Utilisation :
    export API_FOOTBALL_KEY="votre_cle"
    python3 mise_a_jour_resultats.py            # récupère les résultats puis affiche le rapport
    python3 mise_a_jour_resultats.py --rapport  # affiche seulement le rapport (aucune requête)

Entrée  : predictions.jsonl  (écrit par analyse_du_jour.py)
Sortie  : resultats.jsonl    (une ligne par match terminé, avec "reel" = 1 ou 0 pour chaque marché)

Marchés non vérifiables ici (corners, cartons, 1re équipe à marquer) : ignorés du rapport.
Non testé avec l'API réelle : vérifiez sur 1 ou 2 matchs terminés.
"""
import argparse
import json
import os
import re

PRED, RES = "predictions.jsonl", "resultats.jsonl"


def lire(fichier):
    if not os.path.exists(fichier):
        return []
    with open(fichier, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def resoudre(marche, dom, ext, gd, ge, ht=None):
    """True / False si le marché est vérifiable avec le score, None sinon.
    gd, ge : buts à 90 minutes ; ht : (buts_dom, buts_ext) à la mi-temps ou None."""
    total = gd + ge
    m = marche

    # Marchés combinés d'abord (leurs noms contiennent ceux des marchés simples)
    if m == f"{dom} gagne et plus de 1,5 but":
        return gd > ge and total > 1.5
    if m == f"{dom} ou nul et moins de 3,5 buts":
        return gd >= ge and total < 3.5

    if m == f"Victoire {dom}":
        return gd > ge
    if m == f"Victoire {ext}":
        return ge > gd
    if m == "Match nul":
        return gd == ge
    if m == f"{dom} ou nul":
        return gd >= ge
    if m == f"{ext} ou nul":
        return ge >= gd
    if m == "Les deux équipes marquent":
        return gd > 0 and ge > 0

    r = re.fullmatch(r"(Plus|Moins) de (\d+),(\d) buts?", m)
    if r:
        ligne = float(f"{r.group(2)}.{r.group(3)}")
        return total > ligne if r.group(1) == "Plus" else total < ligne

    r = re.fullmatch(r"Score exact : (\d+)-(\d+)", m)
    if r:
        return gd == int(r.group(1)) and ge == int(r.group(2))

    if m == "But en 1re mi-temps":
        return None if ht is None else (ht[0] + ht[1]) > 0
    return None  # corners, cartons, 1re équipe à marquer...


def recuperer(p):
    """Retourne ({"home","away"}, mi-temps ou None) si le match est terminé, sinon None.
    Fonctionne pour les prédictions API-Football (par défaut) et football-data.org (source "fd")."""
    if p.get("source") == "fd":
        import fd_api                      # nécessite FOOTBALL_DATA_KEY
        try:
            m = fd_api.appel(f"/matches/{p['fixture_id']}", ttl=300)
        except fd_api.ErreurFD:
            return None
        m = m.get("match", m)
        if m.get("status") != "FINISHED":
            return None
        sc = m["score"]
        ft = sc.get("regularTime") or {}
        if ft.get("home") is None:
            ft = sc["fullTime"]
        if ft.get("home") is None:
            return None
        ht = sc.get("halfTime") or {}
        return ({"home": ft["home"], "away": ft["away"]},
                (ht["home"], ht["away"]) if ht.get("home") is not None else None)
    import analyse_du_jour as api          # nécessite API_FOOTBALL_KEY
    data = api.appel("/fixtures", {"id": p["fixture_id"]}, ttl=300)
    if not data["response"]:
        return None
    f = data["response"][0]
    if f["fixture"]["status"]["short"] not in ("FT", "AET", "PEN"):
        return None
    ft = f["score"]["fulltime"]
    if ft["home"] is None:
        return None
    ht = f["score"]["halftime"]
    return ({"home": ft["home"], "away": ft["away"]},
            (ht["home"], ht["away"]) if ht["home"] is not None else None)


def mettre_a_jour():
    deja = {r["fixture_id"] for r in lire(RES)}
    nouveaux = 0
    with open(RES, "a", encoding="utf-8") as sortie:
        for p in lire(PRED):
            if p["fixture_id"] in deja:
                continue
            res = recuperer(p)
            if res is None:
                continue      # pas encore terminé (ou introuvable) : on réessaiera plus tard
            ft, ht = res
            dom = p.get("dom") or p["match"].split(" - ", 1)[0]
            ext = p.get("ext") or p["match"].split(" - ", 1)[1]
            lignes = []
            for mk in p["marches"]:
                reel = resoudre(mk["marche"], dom, ext, ft["home"], ft["away"], ht)
                if reel is not None:
                    lignes.append({"marche": mk["marche"], "proba": mk["proba"], "reel": int(reel)})
            sortie.write(json.dumps({"fixture_id": p["fixture_id"], "date": p["date"], "match": p["match"],
                                     "score": [ft["home"], ft["away"]], "marches": lignes},
                                    ensure_ascii=False) + "\n")
            nouveaux += 1
    print(f"{nouveaux} nouveau(x) match(s) terminé(s) enregistré(s).")


def famille(marche):
    """Regroupe les marchés par type (sans le nom des équipes) pour le rapport."""
    if marche.endswith(" ou nul et moins de 3,5 buts"):
        return "Équipe ou nul + moins de 3,5 buts"
    if marche.endswith(" gagne et plus de 1,5 but"):
        return "Équipe gagne + plus de 1,5 but"
    if marche.startswith("Victoire "):
        return "Victoire d'une équipe"
    if marche.endswith(" ou nul"):
        return "Double chance"
    if marche.startswith("Score exact"):
        return "Score exact"
    return marche


def rapport():
    paires = [(mk["proba"] / 100, mk["reel"]) for r in lire(RES) for mk in r["marches"]]
    matchs = len(lire(RES))
    if not paires:
        print("Aucun résultat enregistré pour le moment.")
        return
    brier = sum((p - o) ** 2 for p, o in paires) / len(paires)
    print(f"{matchs} matchs, {len(paires)} prédictions vérifiées. Score de Brier : {brier:.4f} (0,25 = pile ou face)")
    print(f"\n{'Annoncé':>12}{'Réalisé':>10}{'Nombre':>9}")
    for a, b in [(0, .5), (.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)]:
        lot = [(p, o) for p, o in paires if a <= p < b]
        if lot:
            print(f"{a * 100:>5.0f}-{min(b, 1) * 100:<5.0f}%{sum(o for _, o in lot) / len(lot) * 100:>9.0f}%{len(lot):>9}")
    print("\nPar marché (marchés avec au moins 30 prédictions) :")
    par = {}
    for r in lire(RES):
        for mk in r["marches"]:
            par.setdefault(famille(mk["marche"]), []).append((mk["proba"] / 100, mk["reel"]))
    for nom, l in sorted(par.items(), key=lambda kv: -len(kv[1])):
        if len(l) >= 30:
            print(f"  {nom:<40} annoncé {sum(p for p, _ in l) / len(l) * 100:4.0f} %  réalisé {sum(o for _, o in l) / len(l) * 100:4.0f} %  (n={len(l)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rapport", action="store_true")
    a = ap.parse_args()
    if not a.rapport:
        mettre_a_jour()
    rapport()
