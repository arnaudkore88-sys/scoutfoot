"""
Publie chaque jour le « Top 3 du jour » sur un canal Telegram : c'est la notification quotidienne gratuite.
Les abonnés du canal reçoivent le message sur leur téléphone, sans serveur ni compte supplémentaire.

Secrets nécessaires (GitHub : Settings > Secrets and variables > Actions) :
    TELEGRAM_BOT_TOKEN   le jeton donné par @BotFather
    TELEGRAM_CHAT_ID     l'identifiant du canal, par exemple  @scoutfoot_ci
Sans ces deux secrets, le programme ne fait rien (aucune erreur).
Il lit analyse_du_jour.json (déjà publié par l'analyse de minuit).
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")
SITE = os.environ.get("SITE_URL", "https://arnaudkore88-sys.github.io/scoutfoot/")
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def virgule(x):
    return f"{x:.2f}".replace(".", ",")


def meilleur(marches):
    """Même règle que l'application : le marché le plus probable parmi ceux qui ne dépassent pas 90 %."""
    tries = sorted(marches, key=lambda m: -m["proba"])
    return next((m for m in tries if m["proba"] <= 90), tries[0] if tries else None)


def top3(jour_data):
    lignes = []
    for titre, marches in (jour_data.get("matchs") or {}).items():
        m = meilleur(marches) if marches else None
        if m:
            info = (jour_data.get("infos") or {}).get(titre) or {}
            lignes.append((m["proba"], titre, m, info))
    lignes.sort(key=lambda x: -x[0])
    return lignes[:3]


def message(jour_iso, lignes):
    d = datetime.strptime(jour_iso, "%Y-%m-%d")
    out = [f"⚽ ScoutFoot · Top 3 du jour", f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}", ""]
    for i, (_, titre, m, info) in enumerate(lignes, 1):
        heure = ""
        if info.get("heure"):
            try:
                heure = datetime.fromisoformat(info["heure"].replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%H:%M") + " · "
            except ValueError:
                pass
        out.append(f"{i}. {heure}{titre}")
        out.append(f"   {m['marche']} : {round(m['proba'])} %  (cote ≈ {virgule(m['cote_estimee'])})")
    out += ["", f"Toutes les analyses : {SITE}", "",
            "Analyses indicatives, aucun gain garanti. Réservé aux 18 ans et plus. Jouez avec modération."]
    return "\n".join(out)


def envoyer(token, chat, texte):
    corps = urllib.parse.urlencode({"chat_id": chat, "text": texte, "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"{API}/bot{token}/sendMessage", data=corps)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def main():
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("Secrets Telegram absents : aucune notification envoyée.")
        return 0
    try:
        with open("analyse_du_jour.json", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        print("analyse_du_jour.json introuvable : rien à envoyer.")
        return 0
    jour = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    contenu = (data.get("jours") or {}).get(jour)
    lignes = top3(contenu) if contenu else []
    if not lignes:
        print(f"Aucun match analysé pour le {jour} : pas de message.")
        return 0
    try:
        rep = envoyer(token, chat, message(jour, lignes))
    except urllib.error.HTTPError as e:
        print(f"Telegram a refusé l'envoi (HTTP {e.code}). Vérifiez le jeton, le nom du canal et que le robot en est administrateur.")
        return 1
    except Exception as e:
        print(f"Envoi impossible : {e}")
        return 1
    print("Message envoyé." if rep.get("ok") else f"Réponse inattendue : {rep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
