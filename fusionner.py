"""
Fusionne l'analyse des clubs (analyse_du_jour.json, football-data.org) et celle des sélections (analyse_apif.json,
API-Football) en un seul analyse_du_jour.json pour le site. Si analyse_apif.json n'existe pas, ne fait rien.
"""
import json
import os
import re
import unicodedata

import moteur_analyse as moteur


def charger(chemin):
    if not os.path.exists(chemin):
        return None
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def norm(nom):
    n = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"\b(fc|cf|afc|sc|ac|club)\b", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


def cle_paire(titre):
    dom, _, ext = titre.partition(" - ")
    return tuple(sorted((norm(dom), norm(ext))))


def main():
    clubs, sel = charger("analyse_du_jour.json"), charger("analyse_apif.json")
    if not sel:
        print("Pas d'analyse des sélections : rien à fusionner.")
        return
    base = clubs or {"date": sel.get("date"), "jours": {}}
    jours = {j: {"matchs": dict(c.get("matchs", {})), "infos": dict(c.get("infos", {}))}
             for j, c in (base.get("jours") or {}).items()}
    ajoutes = 0
    for jour, c in (sel.get("jours") or {}).items():
        cible = jours.setdefault(jour, {"matchs": {}, "infos": {}})
        deja = {cle_paire(k) for k in cible["matchs"]}
        for titre, marches in c.get("matchs", {}).items():
            if cle_paire(titre) in deja or titre in cible["matchs"]:
                continue                                     # déjà présent côté clubs
            cible["matchs"][titre] = marches
            cible["infos"][titre] = c["infos"][titre]
            ajoutes += 1
    for contenu in jours.values():
        contenu["combines"] = moteur.combines({k: v for k, v in contenu["matchs"].items() if v})
    aujourdhui = base.get("date") or sel.get("date")
    premier = jours.get(aujourdhui, {"matchs": {}, "infos": {}, "combines": []})
    with open("analyse_du_jour.json", "w", encoding="utf-8") as f:
        json.dump({"date": aujourdhui, "jours": jours, "matchs": premier["matchs"], "infos": premier["infos"],
                   "combines": premier["combines"], "couverture_selections": sel.get("couverture")},
                  f, ensure_ascii=False, indent=2)
    print(f"Fusion terminée : {ajoutes} match(s) de sélections ajouté(s).")


if __name__ == "__main__":
    main()
