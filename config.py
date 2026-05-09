# config.py
# =========================================================
# Stockage centralisé des API Keys et paramètres globaux
# =========================================================

TESTNET_API_KEY = "n6yxVeM2vH2aB0gdpfNou4BETbzBiH0Jr2BThxblYu7TvnZ5gGwLol53sDEdUa5i"
TESTNET_API_SECRET = "lW4qS4c6VnbK4MvBybqf7mdb9MKkebLcUpL8opmT9zHHGY6FMiu73MAb3ydsTFp2"

# Liste par défaut de symboles à surveiller
DEFAULT_SYMBOLS = ['ETHUSDT', 'LINKUSDT']

# Intervalle mise à jour périodique (en secondes)
PERIODIC_UPDATE_INTERVAL = 30  

# Noms de fichiers CSV
PORTFOLIO_CSV = "portfolio_update.csv"
ORDER_HISTORY_CSV = "order_history.csv"
