import time
import re
from decimal import Decimal
from binance.client import Client
from binance.exceptions import BinanceAPIException

# parse accepts optional SYMBOL and optional side at the start of each line
# examples:
#   LINKUSDT BUY t=0.00s, Δq=1.234
#   ETHUSDT SELL t=30.0s, Δq=0.5
#   BUY t=5s, Δq=0.1   (use default_symbol)
pattern_line = re.compile(
    r"^(?:(?P<symbol>[A-Z0-9]{3,12})\s+)?(?:(?P<side>BUY|SELL)\s+)?t=(?P<time>\d+(?:\.\d+)?)s?,\s*Δq=(?P<qty>\d+(?:\.\d+)?)",
    re.IGNORECASE
)

def parse_execution_profile(profile_text):
    steps = []
    if not profile_text:
        return steps

    last_symbol = None

    for line in profile_text.strip().splitlines():
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue  # ignore empty lines and comments

        m = pattern_line.search(line_stripped)
        if m:
            symbol = m.group("symbol").upper() if m.group("symbol") else None
            side = m.group("side").upper() if m.group("side") else None
            t = float(m.group("time"))
            q = Decimal(m.group("qty"))

            # Gère l'ambiguïté : si le "symbole" est BUY ou SELL et qu'il n'y a pas de "side",
            # alors le "symbole" était en fait le "side".
            if symbol in ['BUY', 'SELL'] and side is None:
                side = symbol
                symbol = None

            # Propagation du dernier symbole si nécessaire
            if symbol:
                last_symbol = symbol
            else:
                symbol = last_symbol

            steps.append({"symbol": symbol, "side": side, "time": t, "quantity": q})
    return steps

def get_symbol_filter(client, symbol, filter_type):
    try:
        info = client.get_symbol_info(symbol)
        if not info:
            return None
        for f in info["filters"]:
            if f["filterType"] == filter_type:
                return f
        return None
    except:
        return None

def get_current_price(client, symbol):
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return Decimal(ticker["price"])
    except:
        return None

def format_quantity(quantity, lot_size_filter):
    try:
        step_size = Decimal(lot_size_filter.get("stepSize", "0.01"))
        precision = abs(step_size.as_tuple().exponent)
        # truncate to step size
        formatted_qty = (quantity // step_size) * step_size
        # return as string with correct precision
        return f"{formatted_qty:.{precision}f}"
    except:
        return "0"

def adjust_execution_profile(profile_steps, client, symbol):
    lot_size = get_symbol_filter(client, symbol, "LOT_SIZE")
    min_notional = get_symbol_filter(client, symbol, "MIN_NOTIONAL") or get_symbol_filter(client, symbol, "NOTIONAL")

    step_size = Decimal(lot_size["stepSize"]) if lot_size and "stepSize" in lot_size else Decimal("0.01")
    if min_notional:
        min_notional_value = Decimal(min_notional.get("minNotional") or min_notional.get("notional", "1.0"))
    else:
        min_notional_value = Decimal("1.0")

    price = get_current_price(client, symbol) or Decimal("10.0")
    adjusted = []
    for step in profile_steps:
        qty = (step["quantity"] // step_size) * step_size
        if qty * price >= min_notional_value and qty > 0:
            adjusted.append({"symbol": step.get("symbol"), "side": step.get("side"), "time": step["time"], "quantity": qty})
        else:
            print(f"[Adjust] étape ignorée (qty {qty} trop petite / valeur {(qty*price):.4f} < {min_notional_value})")
    return adjusted

def run_execution_engine(client, default_symbol=None, side=None, profile_text=None, analysis_engine=None):
    """
    default_symbol: used when a line doesn't include a symbol
    side: default side if a line doesn't include one
    profile_text: multi-line profile (lines may include symbol and/or side)
    analysis_engine: instance to call update_from_execution(order)
    """
    print(f"\n--- Exécution (default_symbol={default_symbol}, default_side={side}) ---")
    if not profile_text:
        print("⚠️ Aucun profil fourni, exécution ignorée.")
        return

    steps = parse_execution_profile(profile_text)
    if not steps:
        print("⚠️ Aucun step parsable dans le profil, annulation.")
        return

    # Ajustement et propagation symbol/side
    steps_adjusted = []
    for s in steps:
        # La logique ici est plus simple car parse_execution_profile a déjà propagé le 'last_symbol'.
        step_symbol = s.get("symbol") or default_symbol

        if not step_symbol:
            print(f"[Step] pas de symbole pour l'étape et pas de default_symbol -> ignore")
            continue

        adjusted = adjust_execution_profile([s], client, step_symbol)
        for a in adjusted:
            steps_adjusted.append({
                "symbol": step_symbol,
                "side": a.get("side") or s.get("side") or side,
                "time": a["time"],
                "quantity": a["quantity"]
            })

    if not steps_adjusted:
        print("⚠️ Aucune étape valide après ajustement.")
        return

    steps_adjusted = sorted(steps_adjusted, key=lambda x: x["time"])

    last_exec_time = 0.0
    total_executed = Decimal("0.0")
    executed_orders_count = 0

    for i, step in enumerate(steps_adjusted):
        step_symbol = step["symbol"]
        step_side = step.get("side") or side
        if not step_side:
            print(f"[Step {i+1}] aucun side défini et pas de side par défaut -> ignore")
            continue

        sleep_time = step["time"] - last_exec_time
        if sleep_time > 0:
            time.sleep(sleep_time)

        lot_size = get_symbol_filter(client, step_symbol, "LOT_SIZE") or {"stepSize": "0.01"}
        qty_str = format_quantity(step["quantity"], lot_size)
        try:
            if Decimal(qty_str) <= 0:
                print(f"[Step {i+1}] quantité invalide ({qty_str}) -> ignore")
                last_exec_time = step["time"]
                continue
        except:
            print(f"[Step {i+1}] erreur lecture quantité ({qty_str}) -> ignore")
            last_exec_time = step["time"]
            continue

        try:
            order = client.create_order(
                symbol=step_symbol,
                side=step_side,
                type=Client.ORDER_TYPE_MARKET,
                quantity=qty_str
            )
            executed_qty = Decimal(order.get("executedQty", "0"))
            total_executed += executed_qty
            executed_orders_count += 1
            print(f"✅ Étape {i+1}: {step_side} {qty_str} {step_symbol} exécuté (executedQty={order.get('executedQty')})")

            if analysis_engine:
                # Met à jour le flow d'exécution et le ledger
                analysis_engine.update_from_execution(order)

                # Récap marché pour le symbole exécuté (24h ticker)
                try:
                    m = analysis_engine.get_market_summary(step_symbol)
                    print("\n📈 Récap marché (exécuté) :")
                    print(f"   {m.get('symbol')} last={m.get('lastPrice')} bid={m.get('bidPrice')} ask={m.get('askPrice')} 24hΔ={m.get('priceChangePercent')}% high={m.get('highPrice')} low={m.get('lowPrice')} vol={m.get('volume')}")
                except Exception as e:
                    print(f"[Market] Erreur affichage récap marché pour {step_symbol}: {e}")

                # Récap marché : bid/ask et 24h pour chaque symbole présent dans le ledger (portefeuille)
                try:
                    print("\n📊 Infos marché portefeuille :")
                    symbols_portfolio = sorted(list(analysis_engine.ledger.keys()))
                    if step_symbol not in symbols_portfolio:
                        symbols_portfolio.append(step_symbol)
                    for sym in symbols_portfolio:
                        m2 = analysis_engine.get_market_summary(sym)
                        # utilisation correcte de m2 ici
                        print(f"   {m2.get('symbol')}: last={m2.get('lastPrice')} bid={m2.get('bidPrice')} ask={m2.get('askPrice')} 24hΔ={m2.get('priceChangePercent')}% vol={m2.get('volume')}")
                except Exception as e:
                    print(f"[Market] Erreur affichage marché portefeuille: {e}")

        except BinanceAPIException as e:
            print(f"[BinanceAPIException] {e}")
        except Exception as e:
            print(f"[Exception] {e}")

        last_exec_time = step["time"]

    # --- Récapitulatif final ---
    print(f"\n--- Récapitulatif Exécution ---")
    print(f"Nombre d'étapes dans le profil : {len(steps)}")
    print(f"Nombre d'ordres exécutés : {executed_orders_count}")
    print(f"Quantité totale exécutée : {total_executed}")
    list_summary = [f"{s.get('side') or 'UNK'} {s.get('symbol') or default_symbol}" for s in steps_adjusted]
    print("Côtés et symboles traités :", list_summary)
    print(f"--- Fin du profil ---")
