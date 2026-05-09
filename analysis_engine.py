from binance.client import Client
import datetime
import csv
import os
# Assurez-vous que config.py contient vos clés et les noms de fichiers
from config import TESTNET_API_KEY, TESTNET_API_SECRET, PORTFOLIO_CSV, ORDER_HISTORY_CSV

class AnalysisEngine:
    def __init__(self, symbols_to_monitor):
        """
        Initialise le moteur en mémorisant la liste des symboles à surveiller.
        """
        self.client = Client(TESTNET_API_KEY, TESTNET_API_SECRET, testnet=True)
        self.last_update = None
        self.ledger = {}  # per-symbol buy queue + realized pnl
        self.symbols_to_monitor = symbols_to_monitor  # <-- Mémorise la liste
        print(f"✅ [AnalysisEngine] Connecté. Surveillance: {self.symbols_to_monitor}")

    # ---------- Order history ----------
    def get_order_history(self, symbol):
        try:
            return self.client.get_all_orders(symbol=symbol)
        except Exception as e:
            print(f"[OrderHistory] Erreur pour {symbol}: {e}")
            return []

    def save_order_history_csv(self, symbols):
        fieldnames = ["symbol", "orderId", "side", "status", "origQty", "price", "executedQty", "time"]
        try:
            with open(ORDER_HISTORY_CSV, mode='w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for symbol in symbols:
                    orders = self.get_order_history(symbol)
                    for o in orders:
                        writer.writerow({
                            "symbol": symbol,
                            "orderId": o.get("orderId"),
                            "side": o.get("side"),
                            "status": o.get("status"),
                            "origQty": o.get("origQty"),
                            "price": o.get("price"),
                            "executedQty": o.get("executedQty"),
                            "time": o.get("time")
                        })
        except Exception as e:
            print(f"[CSV] Erreur sauvegarde order_history: {e}")

    def append_order_to_history_csv(self, order):
        fieldnames = ["symbol", "orderId", "side", "status", "origQty", "price", "executedQty", "time"]
        try:
            write_header = not os.path.exists(ORDER_HISTORY_CSV)
            with open(ORDER_HISTORY_CSV, mode='a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if write_header:
                    writer.writeheader()
                price = self._get_order_fill_price(order)
                writer.writerow({
                    "symbol": order.get("symbol"),
                    "orderId": order.get("orderId"),
                    "side": order.get("side"),
                    "status": order.get("status"),
                    "origQty": order.get("origQty"),
                    "price": price,
                    "executedQty": order.get("executedQty"),
                    "time": order.get("transactTime") or order.get("time")
                })
        except Exception as e:
            print(f"[CSV] Erreur append order_history: {e}")

    def _get_order_fill_price(self, order):
        try:
            fills = order.get("fills")
            if fills:
                total_qty = sum(float(f.get("qty", 0)) for f in fills)
                total_cost = sum(float(f.get("qty", 0)) * float(f.get("price", 0)) for f in fills)
                return total_cost / total_qty if total_qty > 0 else float(order.get("price", 0) or 0)
            else:
                return float(order.get("price", 0) or 0)
        except:
            return float(order.get("price", 0) or 0)

    # ---------- Ledger & realized PnL (FIFO) ----------
    def rebuild_ledger_from_trades(self, symbol):
        """
        Calcule le PnL réalisé et la position restante en utilisant 
        TOUT l'historique des trades (via get_my_trades) avec la méthode FIFO.
        """
        try:
            trades = self.client.get_my_trades(symbol=symbol)
            trades_sorted = sorted(trades, key=lambda x: x.get("time", x.get("id", 0)))

            buy_queue = []  # list of [qty, price]
            realized_pnl = 0.0

            for t in trades_sorted:
                qty = float(t.get("qty", 0))
                price = float(t.get("price", 0))
                is_buyer = t.get("isBuyer", False)
                if is_buyer:
                    buy_queue.append([qty, price])
                else:  # C'est une VENTE
                    qty_to_sell = qty
                    while qty_to_sell > 0 and buy_queue:
                        b_qty, b_price = buy_queue[0]
                        consume = min(b_qty, qty_to_sell)

                        # Calcul du PnL réalisé sur cette transaction
                        realized_pnl += (price - b_price) * consume

                        b_qty -= consume
                        qty_to_sell -= consume

                        if b_qty <= 0:
                            buy_queue.pop(0)  # Lot d'achat entièrement consommé
                        else:
                            buy_queue[0][0] = b_qty  # Lot d'achat partiellement consommé

            net_qty = sum([b[0] for b in buy_queue])
            avg_buy_price = (sum([b[0] * b[1] for b in buy_queue]) / net_qty) if net_qty > 0 else 0.0

            self.ledger[symbol] = {
                "buy_queue": buy_queue,
                "realized_pnl": realized_pnl,
                "net_qty": net_qty,
                "avg_buy_price": avg_buy_price
            }
            return self.ledger[symbol]
        except Exception as e:
            print(f"[Ledger] Erreur rebuild ledger pour {symbol}: {e}")
            return self.ledger.get(symbol, {"buy_queue": [], "realized_pnl": 0.0, "net_qty": 0.0, "avg_buy_price": 0.0})

    # ---------- PnL & positions ----------
    def get_pnl_data(self, symbol, quote_asset='USDT'):
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])
            base_asset = symbol.replace(quote_asset, '')
            balance = self.client.get_asset_balance(asset=base_asset)

            # 1. Position Totale (Solde de l'API)
            position_amount = float(balance['free'] or 0) + float(balance['locked'] or 0)
            position_value = position_amount * current_price

            # 2. Reconstruction du Ledger (Basé sur l'historique des trades)
            ledger = self.rebuild_ledger_from_trades(symbol)
            avg_buy_price = ledger.get("avg_buy_price", 0.0)
            realized_pnl = ledger.get("realized_pnl", 0.0)

            # 3. Position Tracée (Quantité nette du Ledger FIFO)
            net_qty_from_ledger = ledger.get("net_qty", 0.0)

            pnl_latent = (current_price - avg_buy_price) * net_qty_from_ledger if avg_buy_price and net_qty_from_ledger != 0 else 0.0

            return {
                "symbol": symbol,
                "position": position_amount,
                "price": current_price,
                "value": position_value,
                "pnl_latent": pnl_latent,
                "avg_buy_price": avg_buy_price,
                "realized_pnl": realized_pnl
            }
        except Exception as e:
            print(f"[PnL] Erreur pour {symbol}: {e}")
            return {
                "symbol": symbol,
                "position": 0.0,
                "price": 0.0,
                "value": 0.0,
                "pnl_latent": 0.0,
                "avg_buy_price": 0.0,
                "realized_pnl": 0.0
            }

    def get_order_book_snapshot(self, symbol):
        try:
            depth = self.client.get_order_book(symbol=symbol, limit=5)
            return {"bid": float(depth['bids'][0][0]), "ask": float(depth['asks'][0][0])}
        except:
            return {"bid": 0.0, "ask": 0.0}

    # ---------- Market summary helper (uses Binance get_ticker) ----------
    def get_market_summary(self, symbol):
        """
        Retourne un résumé marché via get_ticker pour afficher:
        lastPrice, bidPrice, askPrice, priceChangePercent, highPrice, lowPrice, volume.
        """
        try:
            t = self.client.get_ticker(symbol=symbol)
            return {
                "symbol": t.get("symbol"),
                "lastPrice": t.get("lastPrice"),
                "bidPrice": t.get("bidPrice"),
                "askPrice": t.get("askPrice"),
                "priceChangePercent": t.get("priceChangePercent"),
                "highPrice": t.get("highPrice"),
                "lowPrice": t.get("lowPrice"),
                "volume": t.get("volume"),
                "weightedAvgPrice": t.get("weightedAvgPrice")
            }
        except Exception as e:
            print(f"[Market] Erreur get_ticker pour {symbol}: {e}")
            return {
                "symbol": symbol,
                "lastPrice": None,
                "bidPrice": None,
                "askPrice": None,
                "priceChangePercent": None,
                "highPrice": None,
                "lowPrice": None,
                "volume": None,
                "weightedAvgPrice": None
            }

    # ---------- Flow per-order ----------
    def update_from_execution(self, executed_order):
        """
        Appelé par l'ExecutionEngine après un ordre.
        Met à jour le portefeuille COMPLET.
        """
        try:
            symbol = executed_order.get("symbol")
            if not symbol:
                print("[AnalysisEngine] ordre reçu sans symbole, ignore.")
                return

            if symbol not in self.symbols_to_monitor:
                self.symbols_to_monitor.append(symbol)
                print(f"[AnalysisEngine] Ajout de {symbol} à la liste de surveillance.")

            self.append_order_to_history_csv(executed_order)
            self.rebuild_ledger_from_trades(symbol)

            # Appelle update avec la liste COMPLÈTE des symboles mémorisés
            self.update(self.symbols_to_monitor)

        except Exception as e:
            print(f"[AnalysisEngine] Erreur update_from_execution: {e}")

    # ---------- Update & CSV write ----------
    def update(self, symbols):
        """
        Met à jour le PnL pour TOUS les symboles fournis
        et génère le CSV du portefeuille.
        """
        portfolio_data = []
        total_value, total_pnl_latent = 0.0, 0.0
        total_realized_pnl = 0.0

        cash_row = {}  # Pour stocker la ligne USDT_CASH
        total_row = {}  # Pour stocker la ligne TOTAL

        # Cash USDT
        try:
            usdt_balance = self.client.get_asset_balance('USDT')
            usdt_total = float(usdt_balance['free'] or 0) + float(usdt_balance['locked'] or 0)
        except:
            usdt_total = 0.0

        # Boucle sur TOUS les symboles mémorisés
        for symbol in symbols:
            pnl_info = self.get_pnl_data(symbol)
            book = self.get_order_book_snapshot(symbol)
            portfolio_data.append({
                "symbol": symbol,
                "position": pnl_info["position"],
                "price": pnl_info["price"],
                "value": pnl_info["value"],
                "pnl_latent": pnl_info["pnl_latent"],
                "avg_buy_price": pnl_info["avg_buy_price"],
                "realized_pnl": pnl_info["realized_pnl"],
                "bid": book["bid"],
                "ask": book["ask"]
            })
            total_value += pnl_info["value"]
            total_pnl_latent += pnl_info["pnl_latent"]
            total_realized_pnl += pnl_info["realized_pnl"]

        # TOTAL
        total_row = {
            "symbol": "TOTAL",
            "position": "",
            "price": "",
            "value": total_value + usdt_total,
            "pnl_latent": total_pnl_latent,
            "avg_buy_price": "",
            "realized_pnl": total_realized_pnl,
            "bid": "",
            "ask": ""
        }
        portfolio_data.append(total_row)

        # Ligne USDT
        cash_row = {
            "symbol": "USDT_CASH",
            "position": usdt_total,
            "price": 1.0,
            "value": usdt_total,
            "pnl_latent": 0.0,
            "avg_buy_price": 1.0,
            "realized_pnl": 0.0,
            "bid": "",
            "ask": ""
        }
        portfolio_data.append(cash_row)

        # Sauvegarde CSV
        self.save_csv(portfolio_data)
        self.save_order_history_csv(symbols)

        # --- SECTION AFFICHAGE PORTFEUILLE (PnL) ---
        print("\n--- 📊 État du Portefeuille (Console) ---")
        header = f"{'Symbole':<11} | {'Position':<12} | {'Prix Actuel':<11} | {'Valeur':<12} | {'PnL Latent':<11} | {'PnL Réalisé':<11}"
        print(header)
        print("-" * len(header))

        for row in portfolio_data:
            if row['symbol'] == 'TOTAL' or row['symbol'] == 'USDT_CASH':
                continue  # On ignore pour l'instant

            print(f"{row['symbol']:<11} | {float(row['position']):<12.6f} | {float(row['price']):<11.4f} | {float(row['value']):<12.2f} | {float(row['pnl_latent']):<11.2f} | {float(row['realized_pnl']):<11.2f}")

        # Afficher le cash et le total à la fin
        print("-" * len(header))
        print(f"{cash_row['symbol']:<11} | {float(cash_row['position']):<12.2f} | {'':<11} | {float(cash_row['value']):<12.2f} | {'':<11} | {'':<11}")
        print(f"{total_row['symbol']:<11} | {'':<12} | {'':<11} | {float(total_row['value']):<12.2f} | {float(total_row['pnl_latent']):<11.2f} | {float(total_row['realized_pnl']):<11.2f}")

        # --- CORRECTION : AJOUT DU RÉCAP MARCHÉ ---
        print("\n--- 📈 Récapitulatif Marché (24h) ---")
        header_market = f"{'Symbole':<11} | {'Last Price':<11} | {'% Change':<9} | {'Volume':<15}"
        print(header_market)
        print("-" * len(header_market))

        for symbol in symbols:
            try:
                m = self.get_market_summary(symbol)
                if m and m.get('lastPrice') is not None:
                    # Formate les nombres en float avant de les aligner
                    last_price = float(m['lastPrice'])
                    change_percent = float(m['priceChangePercent'])
                    volume = float(m['volume'])
                    print(f"{m['symbol']:<11} | {last_price:<11.4f} | {change_percent:<9.2f}% | {volume:<15.2f}")
                else:
                    print(f"{symbol:<11} | {'N/A':<11} | {'N/A':<9} | {'N/A':<15}")
            except Exception as e:
                print(f"[Market] Erreur récap {symbol}: {e}")
        # --- FIN DE LA CORRECTION ---

        self.last_update = datetime.datetime.now()
        print(f"\n📝 Mise à jour (complète) terminée à {self.last_update}")

    def save_csv(self, data):
        fieldnames = ["symbol", "position", "price", "value", "pnl_latent", "avg_buy_price", "realized_pnl", "bid", "ask"]
        try:
            with open(PORTFOLIO_CSV, mode='w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in data:
                    writer.writerow(row)
        except Exception as e:
            print(f"[CSV] Erreur sauvegarde portefeuille: {e}")

    def periodic_update(self):
        """
        Mise à jour périodique utilisant la liste de symboles mémorisée.
        """
        print("\n⏰ [AnalysisEngine] Mise à jour périodique...")
        self.update(self.symbols_to_monitor)
