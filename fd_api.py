"""
Client minimal pour football-data.org (v4), offre gratuite : 10 appels par minute.
Chaque appel est mis en cache sur disque et espacé de 6,5 secondes pour respecter la limite.

Clé : variable d'environnement FOOTBALL_DATA_KEY (voir lancer_jour_fd.bat et cle_fd.txt).
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.football-data.org/v4"
CACHE = ".cache_fd"
PAUSE = 6.5
_dernier = [0.0]


class ErreurFD(Exception):
    pass


def appel(chemin, params=None, ttl=6 * 3600):
    cle = os.environ.get("FOOTBALL_DATA_KEY")
    if not cle:
        raise SystemExit("Définissez la variable FOOTBALL_DATA_KEY (fichier cle_fd.txt).")
    os.makedirs(CACHE, exist_ok=True)
    url = BASE + chemin + ("?" + urllib.parse.urlencode(params) if params else "")
    fichier = os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest() + ".json")
    if os.path.exists(fichier) and time.time() - os.path.getmtime(fichier) < ttl:
        with open(fichier, encoding="utf-8") as f:
            return json.load(f)
    for essai in range(4):
        attente = PAUSE - (time.time() - _dernier[0])
        if attente > 0:
            time.sleep(attente)
        try:
            req = urllib.request.Request(url, headers={"X-Auth-Token": cle})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.load(r)
            _dernier[0] = time.time()
            break
        except urllib.error.HTTPError as e:
            _dernier[0] = time.time()
            if e.code == 429:            # trop d'appels : on patiente
                time.sleep(30)
                continue
            if e.code in (401, 403):
                raise ErreurFD("acces_refuse")   # clé incorrecte, ou compétition hors offre gratuite
            if e.code == 404:
                raise ErreurFD("introuvable")
            raise ErreurFD(f"http_{e.code}")
        except Exception:
            if essai == 3:
                raise ErreurFD("reseau")
            time.sleep(3)
    else:
        raise ErreurFD("trop_de_requetes")
    with open(fichier, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data
