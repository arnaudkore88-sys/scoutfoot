"""
Identifiants de compétitions d'API-Football v3 et filtres sur les noms.

IMPORTANT : ces numéros viennent de ma connaissance du catalogue d'API-Football, pas d'un appel en direct.
Vérifiez-les avec :  python trouver_ligues.py --verifier   (compare chaque numéro au nom réel donné par l'API).
"""
import re

SELECTIONS = {   # équipes nationales (hommes, A)
    1: "Coupe du monde", 4: "Euro", 5: "Ligue des nations UEFA", 6: "Coupe d'Afrique des nations (CAN)",
    7: "Coupe d'Asie", 9: "Copa América", 10: "Matchs amicaux (sélections)",
    29: "Qualifications Mondial - Afrique", 30: "Qualifications Mondial - Asie",
    31: "Qualifications Mondial - CONCACAF", 32: "Qualifications Mondial - Europe",
    33: "Qualifications Mondial - Océanie", 34: "Qualifications Mondial - Amérique du Sud",
    35: "Qualifications Coupe d'Asie", 36: "Qualifications CAN", 37: "Barrages intercontinentaux Mondial",
    536: "Ligue des nations CONCACAF", 960: "Qualifications Euro",
}
CLUBS = {        # clubs
    2: "Ligue des champions", 3: "Ligue Europa", 848: "Ligue Europa Conférence",
    39: "Premier League", 61: "Ligue 1", 140: "LaLiga", 135: "Serie A", 78: "Bundesliga",
    88: "Eredivisie", 94: "Primeira Liga", 40: "Championship", 71: "Brasileirão Série A", 253: "MLS",
    307: "Saudi Pro League", 203: "Süper Lig", 12: "Ligue des champions CAF", 20: "Coupe de la Confédération CAF",
    386: "Ligue 1 Côte d'Ivoire", 200: "Botola Pro (Maroc)", 233: "Premier League (Égypte)",
    288: "Premier Division (Afrique du Sud)",
}
TOUS = {**SELECTIONS, **CLUBS}

# Sans numéros : reconnaissance des compétitions de sélections par leur nom (plus robuste)
MOTIFS = re.compile(r"World Cup|Qualif|Friendlies$|Nations League|Africa Cup of Nations|Asian Cup|"
                    r"Euro Championship|Copa America|Gold Cup", re.I)
EXCLUS_LIGUE = re.compile(r"Club|Women|Femin|\bU-?\d\d\b|Youth|Olympic|Futsal|Beach", re.I)
EXCLUS_EQUIPE = re.compile(r"\bU-?\d\d\b|\bW$|Women|Olympic", re.I)


def est_selection_senior(ligue, dom, ext):
    """True pour les matchs de sélections A masculines (qualifications, amicaux, phases finales, ligues des nations)."""
    return bool(MOTIFS.search(ligue)) and not EXCLUS_LIGUE.search(ligue) \
        and not EXCLUS_EQUIPE.search(dom) and not EXCLUS_EQUIPE.search(ext)
