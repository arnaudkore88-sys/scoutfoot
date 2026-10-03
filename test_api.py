"""
test_api.py : test rapide et autonome de votre clé API-Football (aucune installation, Python 3 suffit).

    python test_api.py                       (clé lue dans la variable API_FOOTBALL_KEY ou dans cle_api.txt)
    python test_api.py VOTRE_CLE             (clé donnée directement)

Il utilise environ 7 requêtes sur les 100 du jour (offre gratuite). Il affiche :
  1. la connexion, l'offre et les requêtes déjà utilisées ;
  2. le nombre de matchs d'hier, d'aujourd'hui et de demain, et les compétitions concernées ;
  3. la liste des matchs du jour ;
  4. ce que votre offre permet (dates lointaines, historique d'une équipe, saison en cours).
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone

BASE = "https://v3.football.api-sports.io"
SELECTION = re.compile(r"World Cup|Qualif|Friendlies$|Nations League|Africa Cup|Asian Cup|Euro Championship|Copa America", re.I)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def trouver_cle():
    if len(sys.argv) > 1:
        return sys.argv[1].strip()
    if os.environ.get("API_FOOTBALL_KEY"):
        return os.environ["API_FOOTBALL_KEY"].strip()
    for chemin in ("cle_api.txt", os.path.join("..", "cle_api.txt")):
        if os.path.exists(chemin):
            return open(chemin, encoding="utf-8").read().strip()
    sys.exit("Aucune clé trouvée : lancez  python test_api.py VOTRE_CLE  ou créez le fichier cle_api.txt")


CLE = trouver_cle()


def appeler(chemin):
    """Retourne (corps, en-têtes, message_erreur). Ne s'arrête jamais sur une erreur."""
    req = urllib.request.Request(BASE + chemin, headers={"x-apisports-key": CLE})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            corps = json.load(r)
            en_tetes = r.headers
    except urllib.error.HTTPError as e:
        return None, None, f"HTTP {e.code} ({'clé refusée' if e.code in (401, 403) else 'erreur serveur ou limite'})"
    except Exception as e:
        return None, None, f"connexion impossible : {e}"
    erreurs = corps.get("errors")
    if erreurs:
        return corps, en_tetes, json.dumps(erreurs, ensure_ascii=False)
    return corps, en_tetes, None


def ligne(texte=""):
    print(texte)


ligne("=== 1. Connexion et offre ===")
corps, h, err = appeler("/status")
if err or not corps or not corps.get("response"):
    ligne(f"[X] Echec : {err or 'réponse vide'}")
    ligne("    -> Vérifiez la clé (sans espace), puis réessayez. Si HTTP 403/401 : clé incorrecte.")
    sys.exit(1)
rep = corps["response"]
offre = (rep.get("subscription") or {}).get("plan", "?")
req = rep.get("requests") or {}
ligne(f"[OK] Connexion réussie. Compte : {(rep.get('account') or {}).get('email', '?')}")
ligne(f"     Offre : {offre}   |   requêtes utilisées aujourd'hui : {req.get('current', '?')} / {req.get('limit_day', '?')}")

aujourdhui = datetime.now(timezone.utc).date()
jours = [("hier", aujourdhui - timedelta(days=1)), ("aujourd'hui", aujourdhui), ("demain", aujourdhui + timedelta(days=1))]
matchs_du_jour = []
ligue_par_nom = Counter()

ligne("\n=== 2. Matchs (hier, aujourd'hui, demain) ===")
for nom, d in jours:
    corps, h, err = appeler(f"/fixtures?date={d.isoformat()}")
    if err:
        ligne(f"[X] {nom} ({d}) : {err}")
        continue
    reponse = corps.get("response", [])
    ligne(f"[OK] {nom} ({d}) : {len(reponse)} matchs")
    if nom == "aujourd'hui":
        matchs_du_jour = reponse
    for f in reponse:
        lg = f["league"]
        ligue_par_nom[(lg["id"], lg["name"], lg.get("country", ""))] += 1
ligne("\n  Compétitions les plus représentées (id, nom, pays : nombre de matchs) :")
for (i, n, p), c in ligue_par_nom.most_common(12):
    marque = "  <- sélections" if SELECTION.search(n) and "Club" not in n and "Women" not in n else ""
    ligne(f"   {i:>5}  {n} ({p}) : {c}{marque}")

ligne("\n=== 3. Matchs d'aujourd'hui (30 premiers) ===")
if not matchs_du_jour:
    ligne("   Aucun match retourné pour aujourd'hui.")
for f in sorted(matchs_du_jour, key=lambda x: x["fixture"]["date"])[:30]:
    heure = datetime.fromisoformat(f["fixture"]["date"]).astimezone(timezone.utc).strftime("%H:%M")
    ligne(f"   {heure} UTC  {f['league']['name']} : {f['teams']['home']['name']} - {f['teams']['away']['name']}  [{f['fixture']['status']['short']}]")

ligne("\n=== 4. Ce que votre offre permet ===")
verdict = {}
tests = [
    ("dates_lointaines", f"/fixtures?date={(aujourdhui + timedelta(days=5)).isoformat()}", "voir les matchs dans 5 jours"),
    ("historique", "/fixtures?team=33&last=10", "historique des 10 derniers matchs d'une équipe"),
    ("saison", f"/fixtures?team=33&season={aujourdhui.year if aujourdhui.month > 6 else aujourdhui.year - 1}", "saison en cours"),
]
for cle, chemin, libelle in tests:
    corps, h, err = appeler(chemin)
    ok = err is None
    verdict[cle] = ok
    ligne(f"   [{'OK' if ok else 'X '}] {libelle}" + ("" if ok else f"  ->  {err}"))
if h is not None:
    ligne(f"\n   Requêtes restantes aujourd'hui : {h.get('x-ratelimit-requests-remaining', '?')} / {h.get('x-ratelimit-requests-limit', '?')}")

ligne("\n=== Verdict ===")
if verdict["historique"] and verdict["saison"]:
    ligne("[OK] Votre offre permet l'analyse complète des équipes (historique + saison en cours).")
elif not verdict["historique"]:
    ligne("[!] Votre offre ne donne pas l'historique récent des équipes : ScoutFoot peut LISTER les matchs")
    ligne("    (sélections comprises, d'hier à demain) mais pas calculer de pronostic fiable.")
    ligne("    Pour l'analyse des sélections et un calendrier de 7 jours, il faut l'offre Pro.")
