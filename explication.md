Profil dynamique BUY/SELL

Le parser parse_execution_profile accepte désormais BUY ou SELL au début de chaque ligne. Si l’entrée n’indique pas le side, la fonction run_execution_engine utilisera le side passé en argument (si fourni). Cela te donne la flexibilité maximale.

Flow par ordre

Après chaque create_order(...), ExecutionEngine appelle analysis_engine.update_from_execution(order) — le flux (l’ordre entier renvoyé par Binance) est envoyé immédiatement. L’AnalysisEngine l’append dans order_history.csv puis rafraîchit les calculs et écrit portfolio_update.csv.

PnL latent basé sur l’historique réel

get_pnl_data calcule avg_buy_price à partir des trades (get_my_trades) : buy_qty, buy_cost, sell_qty, etc. Le PnL latent est (prix_courant - avg_buy_price) * position. C’est une méthode standard et robuste pour ton usage (les positions nettes et l’historique des trades sont utilisés).

CSV

order_history.csv est appendé à chaque exécution (flow), et est réécrit complètement lors de periodic_update (pour garantir cohérence).

portfolio_update.csv est réécrit à chaque update (et inclut la ligne TOTAL).

Compatibilité

J’ai conservé ta logique et noms existants autant que possible (ex. update_from_execution, periodic_update, signature run_execution_engine), pour que tu puisses intégrer les changements sans casser le reste.

