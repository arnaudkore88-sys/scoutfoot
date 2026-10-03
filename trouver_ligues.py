"""
Outil de recherche des numéros de compétitions API-Football.

    python trouver_ligues.py --verifier              compare MES numéros au nom réel donné par l'API (1 requête)
    python trouver_ligues.py --chercher qualif       cherche les compétitions dont le nom contient « qualif »
    python trouver_ligues.py --pays Ivory-Coast      liste les compétitions d'un pays (nom en anglais)
Clé : API_FOOTBALL_KEY ou cle_api.txt.
"""
import argparse
import sys

import apif_api as api
import ligues_apif as L

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def toutes():
    return api.appel("/leagues", ttl=7 * 86400).get("response", [])


def saison_en_cours(item):
    s = [x["year"] for x in item.get("seasons", []) if x.get("current")]
    return s[0] if s else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verifier", action="store_true")
    ap.add_argument("--chercher")
    ap.add_argument("--pays")
    a = ap.parse_args()
    try:
        if a.verifier:
            par_id = {x["league"]["id"]: x for x in toutes()}
            print(f"{'ID':>5}  {'Mon libellé':<42} {'Nom réel dans l API-Football':<46} Saison")
            for i, libelle in L.TOUS.items():
                x = par_id.get(i)
                if x:
                    print(f"{i:>5}  {libelle:<42} {x['league']['name'] + ' (' + x['country']['name'] + ')':<46} {saison_en_cours(x)}")
                else:
                    print(f"{i:>5}  {libelle:<42} *** ABSENT de l'API : numéro à corriger ***")
        elif a.chercher:
            mot = a.chercher.lower()
            for x in toutes():
                if mot in x["league"]["name"].lower():
                    print(f"{x['league']['id']:>5}  {x['league']['name']} ({x['country']['name']})  saison en cours : {saison_en_cours(x)}")
        elif a.pays:
            for x in api.appel("/leagues", {"country": a.pays}, ttl=7 * 86400).get("response", []):
                print(f"{x['league']['id']:>5}  {x['league']['name']}  [{x['league']['type']}]  saison en cours : {saison_en_cours(x)}")
        else:
            ap.print_help()
    except api.ErreurApif as e:
        sys.exit(f"Erreur : {e}")


if __name__ == "__main__":
    main()
