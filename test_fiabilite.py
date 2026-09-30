"""
Test de fiabilité : rejoue des saisons passées match par match.
Pour chaque match, le moteur n'utilise QUE les matchs déjà joués avant lui, puis on compare
ses probabilités à ce qui s'est réellement passé.

Mesures :
  - Score de Brier (plus petit = meilleur), comparé à une référence naïve
    (la fréquence moyenne observée jusque-là).
  - Calibration : parmi les prédictions annoncées autour de 70 %, combien se réalisent vraiment ?

Utilisation :
    python3 test_fiabilite.py --demo                      # vérifie que le code fonctionne
    python3 test_fiabilite.py --csv saison_2024.csv       # colonnes : date,dom,ext,buts_dom,buts_ext
    python3 test_fiabilite.py --api 61 2024               # ligue 61, saison 2024 (nécessite API_FOOTBALL_KEY)
"""
import argparse
import csv
import math
import random
from collections import defaultdict
from datetime import date, timedelta

import moteur_analyse as moteur

MIN_MATCHS = 5      # matchs minimum par équipe avant de la prédire
FENETRE = 10        # nombre de matchs récents utilisés


# ---------- chargement des données ----------
def charger_csv(chemin):
    out = []
    with open(chemin, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append((date.fromisoformat(r["date"][:10]), r["dom"], r["ext"],
                        int(r["buts_dom"]), int(r["buts_ext"])))
    return sorted(out)


def charger_api(ligue, saison):
    import analyse_du_jour as api
    data = api.appel("/fixtures", {"league": ligue, "season": saison, "status": "FT"}, ttl=7 * 24 * 3600)
    out = []
    for f in data["response"]:
        if f["goals"]["home"] is None:
            continue
        out.append((date.fromisoformat(f["fixture"]["date"][:10]), f["teams"]["home"]["name"],
                    f["teams"]["away"]["name"], f["goals"]["home"], f["goals"]["away"]))
    return sorted(out)


def donnees_demo(seed=1):
    """Saison fictive générée avec des forces d'équipes connues (pour tester le code)."""
    rnd = random.Random(seed)
    equipes = [f"Equipe{i}" for i in range(12)]
    force = {e: (rnd.uniform(0.6, 1.5), rnd.uniform(0.6, 1.5)) for e in equipes}

    def tirage(lam):
        L, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rnd.random()
            if p <= L:
                return k
            k += 1

    out, jour = [], date(2024, 8, 1)
    for _ in range(6):
        for d in equipes:
            for e in equipes:
                if d != e:
                    lh = 1.5 * force[d][0] * force[e][1]
                    la = 1.2 * force[e][0] * force[d][1]
                    out.append((jour, d, e, tirage(lh), tirage(la)))
                    jour += timedelta(days=1) if rnd.random() < 0.3 else timedelta(days=0)
        jour += timedelta(days=7)
    return sorted(out)


# ---------- le test ----------
def evenements(dom, ext):
    """Marchés testés : nom -> (probabilité depuis le tableau, résultat réel depuis le score)."""
    return {
        "Victoire domicile": (lambda x, y: x > y),
        "Match nul": (lambda x, y: x == y),
        "Victoire extérieur": (lambda x, y: x < y),
        "Plus de 2,5 buts": (lambda x, y: x + y > 2.5),
        "Les deux marquent": (lambda x, y: x > 0 and y > 0),
    }


def rejouer(matchs):
    hist = defaultdict(list)             # équipe -> [(date, gf, ga)]
    total_d = total_e = n_vus = 0
    freq = defaultdict(lambda: [0, 0])   # référence naïve : [réalisés, total] par marché
    brier = defaultdict(float)
    brier_ref = defaultdict(float)
    compte = defaultdict(int)
    paires = []                          # (probabilité, réalisé) pour la calibration

    for jour, dom, ext, gd, ge in matchs:
        if n_vus >= 30 and len(hist[dom]) >= MIN_MATCHS and len(hist[ext]) >= MIN_MATCHS:
            moy_d, moy_e = total_d / n_vus, total_e / n_vus
            h = {e: [(gf, ga, (jour - d).days) for d, gf, ga in hist[e][-FENETRE:]] for e in (dom, ext)}
            notes = moteur.forces(h, moy_d, moy_e)
            lh, la = moteur.buts_attendus(notes, dom, ext, moy_d, moy_e)
            m = moteur.tableau_scores(lh, la)
            for nom, cond in evenements(dom, ext).items():
                p = moteur.proba(m, cond)
                reel = 1.0 if cond(gd, ge) else 0.0
                r, t = freq[nom]
                p_ref = r / t if t else 0.5
                brier[nom] += (p - reel) ** 2
                brier_ref[nom] += (p_ref - reel) ** 2
                compte[nom] += 1
                paires.append((p, reel))
        for nom, cond in evenements(dom, ext).items():
            freq[nom][1] += 1
            freq[nom][0] += 1 if cond(gd, ge) else 0
        hist[dom].append((jour, gd, ge))
        hist[ext].append((jour, ge, gd))
        total_d += gd
        total_e += ge
        n_vus += 1
    return brier, brier_ref, compte, paires


def rapport(brier, brier_ref, compte, paires):
    print(f"\n{max(compte.values(), default=0)} matchs prédits\n")
    print(f"{'Marché':<22}{'Brier modèle':>14}{'Brier naïf':>12}{'Amélioration':>14}")
    for nom in brier:
        b, r = brier[nom] / compte[nom], brier_ref[nom] / compte[nom]
        print(f"{nom:<22}{b:>14.4f}{r:>12.4f}{(1 - b / r) * 100:>13.1f}%")
    print("\nCalibration (toutes prédictions confondues)")
    print(f"{'Annoncé':>10}{'Réalisé':>10}{'Nombre':>9}")
    for i in range(10):
        lot = [(p, o) for p, o in paires if i / 10 <= p < (i + 1) / 10 or (i == 9 and p == 1)]
        if len(lot) >= 20:
            print(f"{sum(p for p, _ in lot) / len(lot) * 100:>9.0f}%{sum(o for _, o in lot) / len(lot) * 100:>9.0f}%{len(lot):>9}")
    print("\nLecture : une amélioration positive signifie que le modèle bat la référence naïve.")
    print("Une bonne calibration = colonnes 'Annoncé' et 'Réalisé' proches.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--csv")
    ap.add_argument("--api", nargs=2, metavar=("LIGUE", "SAISON"))
    a = ap.parse_args()
    if a.csv:
        data = charger_csv(a.csv)
    elif a.api:
        data = charger_api(int(a.api[0]), int(a.api[1]))
    else:
        data = donnees_demo()
        print("Mode démonstration : données fictives.")
    rapport(*rejouer(data))
