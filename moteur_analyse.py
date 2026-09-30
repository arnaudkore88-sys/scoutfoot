"""
Moteur d'analyse de matchs : buts attendus -> tableau des scores -> probabilités.

Aucune dépendance externe (Python 3.9+). Les données d'entrée (résultats passés)
viennent d'une API de stats (API-Football, Sportmonks...). Les résultats sont des
ESTIMATIONS : à valider par un test sur des saisons passées avant toute publication.
"""
import json
import math
from itertools import combinations

MAX_BUTS = 10          # taille du tableau des scores (0..10 buts par équipe)
DEMI_VIE_JOURS = 90    # un match vieux de 90 jours compte moitié moins
SHRINK = 3.0           # "matchs virtuels" moyens ajoutés pour éviter les notes extrêmes
RHO = -0.08            # correction Dixon-Coles des petits scores
PART_1RE_MT = 0.45     # part approximative des buts marqués en 1re mi-temps


# ---------- outils mathématiques ----------
def poisson_pmf(k, lam):
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1)) if lam > 0 else float(k == 0)


def poisson_plus_que(ligne, mu):
    """P(N > ligne) pour N ~ Poisson(mu) ; ex. ligne=8.5 -> P(N >= 9)."""
    n = math.floor(ligne)
    return 1.0 - sum(poisson_pmf(k, mu) for k in range(n + 1))


# ---------- 1) force des équipes ----------
def poids(jours):
    return 0.5 ** (jours / DEMI_VIE_JOURS)


def forces(historique, moy_dom, moy_ext):
    """
    historique : {equipe: [(buts_marques, buts_encaisses, jours_depuis_le_match), ...]}
    Retourne {equipe: (attaque, defense)} relatives à la moyenne du championnat
    (attaque > 1 = marque plus que la moyenne ; defense > 1 = encaisse plus que la moyenne).
    """
    moy = (moy_dom + moy_ext) / 2
    notes = {}
    for equipe, matchs in historique.items():
        w = sum(poids(j) for _, _, j in matchs)
        gf = sum(poids(j) * f for f, _, j in matchs)
        ga = sum(poids(j) * a for _, a, j in matchs)
        att = ((gf + SHRINK * moy) / (w + SHRINK)) / moy
        dfn = ((ga + SHRINK * moy) / (w + SHRINK)) / moy
        notes[equipe] = (att, dfn)
    return notes


def buts_attendus(notes, dom, ext, moy_dom, moy_ext):
    att_d, def_d = notes[dom]
    att_e, def_e = notes[ext]
    return moy_dom * att_d * def_e, moy_ext * att_e * def_d


# ---------- 2) tableau des scores ----------
def tableau_scores(lh, la):
    def tau(x, y):
        if x == 0 and y == 0:
            return 1 - lh * la * RHO
        if x == 0 and y == 1:
            return 1 + lh * RHO
        if x == 1 and y == 0:
            return 1 + la * RHO
        if x == 1 and y == 1:
            return 1 - RHO
        return 1.0

    m = [[poisson_pmf(x, lh) * poisson_pmf(y, la) * tau(x, y)
          for y in range(MAX_BUTS + 1)] for x in range(MAX_BUTS + 1)]
    total = sum(sum(l) for l in m)
    return [[c / total for c in l] for l in m]


def proba(m, condition):
    """Somme des cases (x = buts domicile, y = buts extérieur) qui vérifient la condition."""
    return sum(m[x][y] for x in range(len(m)) for y in range(len(m)) if condition(x, y))


# ---------- 3) tous les marchés d'un match ----------
def marches(dom, ext, lh, la, corners_moy=None, cartons_moy=None):
    m = tableau_scores(lh, la)
    p = {}
    p[f"Victoire {dom}"] = proba(m, lambda x, y: x > y)
    p["Match nul"] = proba(m, lambda x, y: x == y)
    p[f"Victoire {ext}"] = proba(m, lambda x, y: x < y)
    p[f"{dom} ou nul"] = proba(m, lambda x, y: x >= y)
    p[f"{ext} ou nul"] = proba(m, lambda x, y: y >= x)
    for ligne in (1.5, 2.5, 3.5):
        p[f"Plus de {ligne} buts"] = proba(m, lambda x, y, l=ligne: x + y > l)
    p["Moins de 3,5 buts"] = 1 - p["Plus de 3.5 buts"]
    p["Les deux équipes marquent"] = proba(m, lambda x, y: x > 0 and y > 0)

    # Marchés combinés sur UN match : on additionne les cases compatibles
    p[f"{dom} gagne et plus de 1,5 but"] = proba(m, lambda x, y: x > y and x + y > 1.5)
    p[f"{dom} ou nul et moins de 3,5 buts"] = proba(m, lambda x, y: x >= y and x + y < 3.5)

    # Score exact le plus probable
    x, y = max(((i, j) for i in range(6) for j in range(6)), key=lambda c: m[c[0]][c[1]])
    p[f"Score exact : {x}-{y}"] = m[x][y]

    # Première mi-temps (approximation) et première équipe à marquer (si but)
    p["But en 1re mi-temps"] = 1 - math.exp(-PART_1RE_MT * (lh + la))
    p[f"1re équipe à marquer : {dom}"] = lh / (lh + la) * (1 - math.exp(-(lh + la)))
    p[f"1re équipe à marquer : {ext}"] = la / (lh + la) * (1 - math.exp(-(lh + la)))

    # Corners / cartons : moyennes totales attendues par match (à calculer depuis l'API)
    if corners_moy:
        for l in (7.5, 8.5, 9.5, 10.5):
            p[f"Plus de {l} corners"] = poisson_plus_que(l, corners_moy)
    if cartons_moy:
        for l in (2.5, 3.5, 4.5):
            p[f"Plus de {l} cartons jaunes"] = poisson_plus_que(l, cartons_moy)

    # Nettoyage des noms (points -> virgules) et cotes estimées
    out = []
    for nom, pr in p.items():
        out.append({
            "marche": nom.replace(".", ","),
            "proba": round(pr * 100, 1),
            "cote_estimee": round(1 / pr, 2) if pr > 0.001 else None,
        })
    return sorted(out, key=lambda d: -d["proba"])


# ---------- 4) combinés (une sélection par match, matchs indépendants) ----------
def combines(analyses, mini=65, maxi=90, tailles=(2, 3, 4, 5)):
    """
    analyses : {"PSG - Lens": [ {marche, proba, ...}, ... ], ...}
    Ne combine JAMAIS deux marchés du même match (ils sont liés).
    """
    jambes = []
    for match, liste in analyses.items():
        ok = [d for d in liste if mini <= d["proba"] <= maxi]
        if ok:
            meilleur = max(ok, key=lambda d: d["proba"])
            jambes.append((match, meilleur))
    jambes.sort(key=lambda j: -j[1]["proba"])

    resultats = []
    for k in tailles:
        if len(jambes) < k:
            break
        choix = jambes[:k]
        pr = math.prod(j[1]["proba"] / 100 for j in choix)
        resultats.append({
            "taille": k,
            "proba": round(pr * 100, 1),
            "cote_estimee": round(1 / pr, 2),
            "selections": [f"{m} : {d['marche']} ({d['proba']} %)" for m, d in choix],
        })
    return resultats


# ---------- démonstration avec des données fictives ----------
if __name__ == "__main__":
    MOY_DOM, MOY_EXT = 1.55, 1.20  # à calculer sur le championnat concerné

    historique = {
        "PSG":  [(3, 0, 5), (2, 1, 12), (4, 1, 19), (1, 1, 26), (3, 0, 33), (2, 0, 40)],
        "Lens": [(1, 2, 6), (2, 0, 13), (0, 1, 20), (1, 1, 27), (2, 2, 34), (1, 0, 41)],
        "Arsenal":  [(2, 0, 4), (3, 1, 11), (1, 1, 18), (2, 0, 25), (2, 1, 32), (3, 0, 39)],
        "Brighton": [(1, 1, 5), (2, 1, 12), (0, 2, 19), (2, 2, 26), (1, 0, 33), (1, 1, 40)],
        "Inter":  [(2, 0, 6), (3, 0, 13), (1, 0, 20), (2, 1, 27), (2, 0, 34), (1, 1, 41)],
        "Torino": [(0, 1, 5), (1, 2, 12), (1, 1, 19), (0, 0, 26), (2, 1, 33), (0, 2, 40)],
    }
    affiches = [("PSG", "Lens", 9.6, 3.7), ("Arsenal", "Brighton", 10.2, 3.9), ("Inter", "Torino", 9.1, 4.3)]

    notes = forces(historique, MOY_DOM, MOY_EXT)
    analyses = {}
    for dom, ext, corners, cartons in affiches:
        lh, la = buts_attendus(notes, dom, ext, MOY_DOM, MOY_EXT)
        analyses[f"{dom} - {ext}"] = marches(dom, ext, lh, la, corners, cartons)
        print(f"{dom} - {ext} : buts attendus {lh:.2f} - {la:.2f}")
        for d in analyses[f"{dom} - {ext}"][:4]:
            print(f"   {d['proba']:>5} %  cote ~{d['cote_estimee']}  {d['marche']}")

    print("\nCombinés :")
    for c in combines(analyses):
        print(f"  {c['taille']} matchs : {c['proba']} %  cote ~{c['cote_estimee']}")
        for s in c["selections"]:
            print("     -", s)

    with open("analyse_du_jour.json", "w", encoding="utf-8") as f:
        json.dump({"matchs": analyses, "combines": combines(analyses)}, f, ensure_ascii=False, indent=2)
