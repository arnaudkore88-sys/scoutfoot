"""
Client minimal API-Football v3 (api-sports.io).
  - Domaine : https://v3.football.api-sports.io      - En-tête : x-apisports-key
    (x-rapidapi-key ne sert que si vous passez par RapidAPI : inutile ici)
  - Quota : lit les compteurs renvoyés par l'API (requêtes restantes du jour, restantes par minute),
    attend si la limite par minute est atteinte, s'arrête proprement avant d'épuiser le jour (réserve).
  - Erreurs : n'arrête JAMAIS le programme brutalement. Il lève des exceptions que l'appelant attrape :
      ErreurCle (clé absente ou refusée), ErreurPlan (non permis par votre offre), QuotaEpuise, ErreurApif.
  - Cache disque (.cache_apif) : un même appel n'est pas payé deux fois.
Clé : variable d'environnement API_FOOTBALL_KEY, ou fichier cle_api.txt (dossier courant ou parent).
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("APIF_BASE", "https://v3.football.api-sports.io")
CACHE = ".cache_apif"
RESERVE = int(os.environ.get("APIF_RESERVE", "8"))      # requêtes du jour laissées de côté
etat = {"restant_jour": None, "limite_jour": None, "restant_minute": None}


class ErreurApif(Exception):
    pass


class ErreurCle(ErreurApif):
    pass


class ErreurPlan(ErreurApif):
    pass


class QuotaEpuise(ErreurApif):
    pass


def lire_cle():
    cle = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if cle:
        return cle
    for chemin in ("cle_api.txt", os.path.join("..", "cle_api.txt")):
        if os.path.exists(chemin):
            with open(chemin, encoding="utf-8") as f:
                return f.read().strip()
    raise ErreurCle("Aucune clé : définissez API_FOOTBALL_KEY ou créez cle_api.txt")


def _entier(valeur):
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None


def appel(chemin, params=None, ttl=6 * 3600):
    url = BASE + chemin + ("?" + urllib.parse.urlencode(params) if params else "")
    os.makedirs(CACHE, exist_ok=True)
    fichier = os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest() + ".json")
    if ttl and os.path.exists(fichier) and time.time() - os.path.getmtime(fichier) < ttl:
        with open(fichier, encoding="utf-8") as f:
            return json.load(f)
    cle = lire_cle()
    for essai in range(4):
        if etat["restant_jour"] is not None and etat["restant_jour"] <= RESERVE and chemin != "/status":
            raise QuotaEpuise(f"Il ne reste que {etat['restant_jour']} requêtes aujourd'hui : arrêt avant l'épuisement.")
        if etat["restant_minute"] is not None and etat["restant_minute"] <= 1:
            time.sleep(61)                      # limite par minute atteinte : on attend la minute suivante
            etat["restant_minute"] = None
        try:
            req = urllib.request.Request(url, headers={"x-apisports-key": cle})
            with urllib.request.urlopen(req, timeout=25) as r:
                corps = json.load(r)
                h = r.headers
                etat["restant_jour"] = _entier(h.get("x-ratelimit-requests-remaining"))
                etat["limite_jour"] = _entier(h.get("x-ratelimit-requests-limit"))
                etat["restant_minute"] = _entier(h.get("X-RateLimit-Remaining"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(61)
                continue
            if e.code in (401, 403):
                raise ErreurCle(f"Clé refusée (HTTP {e.code})")
            if e.code >= 500 and essai < 3:
                time.sleep(5)
                continue
            raise ErreurApif(f"HTTP {e.code}")
        except Exception as e:
            if essai == 3:
                raise ErreurApif(f"Connexion impossible ({e})")
            time.sleep(3)
            continue
        erreurs = corps.get("errors")
        if erreurs:                              # liste vide ou dictionnaire vide = pas d'erreur
            texte = json.dumps(erreurs, ensure_ascii=False)
            bas = texte.lower()
            if isinstance(erreurs, dict) and "token" in erreurs:
                raise ErreurCle(texte)
            if "ratelimit" in bas or "too many requests" in bas:
                time.sleep(61)
                continue
            if "request limit" in bas or "requests" in (erreurs if isinstance(erreurs, dict) else {}):
                raise QuotaEpuise(texte)
            if "plan" in bas or "free plans" in bas:
                raise ErreurPlan(texte)
            raise ErreurApif(texte)
        if ttl:
            with open(fichier, "w", encoding="utf-8") as f:
                json.dump(corps, f)
        return corps
    raise ErreurApif("Trop de tentatives")
