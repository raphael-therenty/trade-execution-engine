import time
from binance.client import Client
from config import TESTNET_API_KEY, TESTNET_API_SECRET, DEFAULT_SYMBOLS, PERIODIC_UPDATE_INTERVAL
from analysis_engine import AnalysisEngine
from execution_engine import run_execution_engine

# Profil d'exécution : chaque ligne peut préciser symbol et/ou side.
# Example:
# PROFILE_EXECUTION = ""
# LINKUSDT BUY t=0s, Δq=1.5
# LINKUSDT SELL t=10s, Δq=0.5
# ETHUSDT BUY t=15s, Δq=0.01
PROFILE_EXECUTION = """
LINKUSDT BUY t=0s, Δq=1.5
LINKUSDT SELL t=10s, Δq=0.5
LINKUSDT BUY t=20s, Δq=0.3
"""


def is_profile_valid(profile_text: str) -> bool:
    """
    Vérifie si le profil contient des lignes exécutables (non vides, non commentées).
    """
    if not profile_text:
        return False
    for line in profile_text.strip().splitlines():
        line_clean = line.strip()
        if line_clean and not line_clean.startswith("#"):
            # on a trouvé au moins une ligne active
            return True
    return False

def main():
    try:
        client = Client(TESTNET_API_KEY, TESTNET_API_SECRET, testnet=True)
        client.ping()
        print("✅ Connexion Testnet réussie.")
    except Exception as e:
        print(f"❌ Erreur de connexion: {e}")
        return

    # La liste des symboles est définie ici
    symbols_to_monitor = DEFAULT_SYMBOLS.copy()

    # default symbol to use when a profile line doesn't include a symbol
    DEFAULT_PROFILE_SYMBOL = "LINKUSDT"

    # Passe la liste des symboles au constructeur de l'AnalysisEngine
    analysis_engine = AnalysisEngine(symbols_to_monitor)

    # DEBUG optionnel pour voir le contenu exact du profil (désactiver si non voulu)
    # print(f"[DEBUG] Contenu brut du profil: {repr(PROFILE_EXECUTION)}")

    if is_profile_valid(PROFILE_EXECUTION):
        print(f"\n🚀 Lancement profil d'exécution (autonome)")
        run_execution_engine(
            client=client,
            default_symbol=DEFAULT_PROFILE_SYMBOL,
            side=None,
            profile_text=PROFILE_EXECUTION,
            analysis_engine=analysis_engine
        )

        # On s'assure que le moteur surveille aussi le symbole par défaut du profil
        if DEFAULT_PROFILE_SYMBOL and DEFAULT_PROFILE_SYMBOL not in analysis_engine.symbols_to_monitor:
            analysis_engine.symbols_to_monitor.append(DEFAULT_PROFILE_SYMBOL)
    else:
        print("⚠️ Aucun profil d’exécution fourni au démarrage — boucle de surveillance activée.")

    try:
        while True:
            analysis_engine.periodic_update()
            time.sleep(PERIODIC_UPDATE_INTERVAL)
    except KeyboardInterrupt:
        print("\n🛑 Arrêt manuel par l'utilisateur.")
    except Exception as e:
        print(f"💥 Erreur inattendue: {e}")

if __name__ == "__main__":
    main()
