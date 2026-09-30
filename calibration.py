"""
Recalibrage des probabilités : corrige la sur-confiance (ou la sous-confiance) du moteur.

Principe : on rejoue des saisons passées (test_fiabilite.rejouer), on récupère les paires
(probabilité annoncée, résultat réel), puis on apprend une correspondance croissante
"annoncé -> réellement observé" (régression isotonique, algorithme PAV).
Exemple : si les "74 %" annoncés ne se réalisent que 61 % du temps, 74 % devient 61 %.

Utilisation :
    python3 calibration.py --demo                       # vérifie que la méthode améliore les résultats
    python3 calibration.py --csv saison_2024.csv        # apprend sur vos données réelles
    python3 calibration.py --api 61 2024                # idem via l'API
    -> écrit calibration.json, utilisé automatiquement par analyse_du_jour.py

Attention : apprenez sur des saisons, testez sur une autre saison (sinon le résultat est flatteur).
"""
import argparse
import json
import os

import test_fiabilite as tf

FICHIER = "calibration.json"
MIN_PAR_BLOC = 40   # un bloc trop petit est fusionné avec son voisin (évite le sur-ajustement)


def ajuster(paires):
    """Régression isotonique (PAV). Retourne une liste de points [proba_annoncee, proba_observee]."""
    def moy(b, i):
        return b[i] / b[2]

    # 1) PAV classique : on fusionne tant que la fréquence observée n'est pas croissante
    blocs = []  # [somme_p, somme_o, nombre]
    for p, o in sorted(paires):
        blocs.append([p, o, 1])
        while len(blocs) > 1 and moy(blocs[-2], 1) >= moy(blocs[-1], 1):
            b = blocs.pop()
            blocs[-1] = [blocs[-1][0] + b[0], blocs[-1][1] + b[1], blocs[-1][2] + b[2]]
    # 2) blocs trop petits : fusionnés avec leur voisin (évite le sur-ajustement)
    i = 0
    while i < len(blocs) and len(blocs) > 1:
        if blocs[i][2] < MIN_PAR_BLOC:
            j = i + 1 if i + 1 < len(blocs) else i - 1
            a, b = min(i, j), max(i, j)
            blocs[a] = [blocs[a][0] + blocs[b][0], blocs[a][1] + blocs[b][1], blocs[a][2] + blocs[b][2]]
            del blocs[b]
            i = max(0, a - 1)
        else:
            i += 1
    return [[moy(b, 0), moy(b, 1)] for b in blocs]


def corriger(p, points):
    """Interpolation linéaire entre les points ; valeurs bornées aux extrémités."""
    if not points:
        return p
    if p <= points[0][0]:
        return points[0][1]
    if p >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= p <= x1:
            return y0 + (y1 - y0) * (p - x0) / (x1 - x0) if x1 > x0 else y0
    return p


def sauver(points, fichier=FICHIER):
    with open(fichier, "w", encoding="utf-8") as f:
        json.dump(points, f)


def charger(fichier=FICHIER):
    if not os.path.exists(fichier):
        return None
    with open(fichier, encoding="utf-8") as f:
        return json.load(f)


def appliquer(liste_marches, points):
    """Recalibre les marchés fondés sur les buts. Les corners, cartons, 1re équipe à marquer
    et 1re mi-temps ne sont pas couverts par le test : on les laisse tels quels."""
    exclus = ("corners", "cartons", "1re équipe", "mi-temps")
    out = []
    for d in liste_marches:
        d = dict(d)
        if points and not any(mot in d["marche"] for mot in exclus):
            d["proba_brute"] = d["proba"]
            p = max(0.01, min(0.99, corriger(d["proba"] / 100, points)))
            d["proba"] = round(p * 100, 1)
            d["cote_estimee"] = round(1 / p, 2)
        out.append(d)
    return sorted(out, key=lambda d: -d["proba"])


# ---------- évaluation ----------
def brier(paires):
    return sum((p - o) ** 2 for p, o in paires) / len(paires)


def haut(paires, seuil=0.7):
    lot = [(p, o) for p, o in paires if p >= seuil]
    return (sum(p for p, _ in lot) / len(lot), sum(o for _, o in lot) / len(lot), len(lot)) if lot else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--csv")
    ap.add_argument("--api", nargs=2, metavar=("LIGUE", "SAISON"))
    ap.add_argument("--test-csv", help="autre saison (CSV) pour vérifier l'amélioration")
    a = ap.parse_args()

    if a.demo:
        apprentissage = tf.rejouer(tf.donnees_demo(seed=1))[3]
        test = tf.rejouer(tf.donnees_demo(seed=2))[3]   # autre "saison" fictive
    else:
        data = tf.charger_csv(a.csv) if a.csv else tf.charger_api(int(a.api[0]), int(a.api[1]))
        apprentissage = tf.rejouer(data)[3]
        test = tf.rejouer(tf.charger_csv(a.test_csv))[3] if a.test_csv else None

    points = ajuster(apprentissage)
    sauver(points)
    print(f"{len(apprentissage)} prédictions utilisées, {len(points)} paliers appris -> {FICHIER}")
    for x, y in points:
        print(f"   annoncé {x * 100:5.1f} %  ->  réalisé {y * 100:5.1f} %")

    if test:
        avant = brier(test)
        apres = brier([(corriger(p, points), o) for p, o in test])
        print(f"\nSur des données NON vues : Brier avant {avant:.4f} -> après {apres:.4f}")
        h0 = haut(test)
        h1 = haut([(corriger(p, points), o) for p, o in test])
        if h0:
            print(f"Prédictions >= 70 % : annoncé {h0[0] * 100:.0f} % / réalisé {h0[1] * 100:.0f} % (avant)")
        if h1:
            print(f"Après recalibrage (>= 70 %) : annoncé {h1[0] * 100:.0f} % / réalisé {h1[1] * 100:.0f} %")
        else:
            print("Après recalibrage : plus aucune prédiction n'atteint 70 % (le modèle était trop confiant).")
    else:
        print("\nAjoutez --test-csv autre_saison.csv pour vérifier l'amélioration sur une autre saison.")
