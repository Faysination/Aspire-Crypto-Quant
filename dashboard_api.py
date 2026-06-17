"""
dashboard_api.py
Flask REST API for the Portfolio Bot dashboard.
"""

import os
from dotenv import load_dotenv
load_dotenv(".env", override=True)

import re
import json
import threading
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from binance_executor import PortfolioBot, BotConfig, activity_logs
import trade_db

app = Flask(__name__, static_folder="frontend")
CORS(app, origins=["*"]) # Allow all for local dev

bot: PortfolioBot = None
bot_thread: threading.Thread = None
equity_curve: list = [10000.0]

def start_bot():
    global bot, equity_curve
    trade_db.init_db()
    # Reload config from env
    cfg = BotConfig()
    bot = PortfolioBot(cfg)

    # Patch _close to track equity
    original_close = bot._close
    def patched_close(symbol, reason, price):
        original_close(symbol, reason, price)
        if bot.trade_log:
            last_pnl = bot.trade_log[-1]["pnl"]
            equity_curve.append(round(equity_curve[-1] + last_pnl, 4))
    bot._close = patched_close

    bot.run()

def restart_bot():
    global bot, bot_thread
    if bot:
        bot.running = False # Graceful stop
    if bot_thread:
        bot_thread.join(timeout=2)
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()

def update_env_file(key, value):
    env_path = ".env"
    if not os.path.exists(env_path):
        return
    with open(env_path, "r") as f:
        content = f.read()
    
    # If key exists, replace it
    if re.search(f"^{key}=", content, re.MULTILINE):
        content = re.sub(f"^{key}=.*$", f"{key}={value}", content, flags=re.MULTILINE)
    else:
        content += f"\n{key}={value}\n"
        
    with open(env_path, "w") as f:
        f.write(content)
    # Also set in current process environment so BotConfig picks it up
    os.environ[key] = str(value)

@app.route("/")
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(app.static_folder, path)

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/api/status")
def status():
    if not bot: return jsonify({"error": "bot not initialized"}), 503
    try:
        data = bot.get_status()
        
        if not bot.cfg.PAPER and bot.cfg.USE_FUTURES:
            try:
                bot.exchange.load_time_difference()
                bal = bot.exchange.fetch_balance({'type': 'future'})
                info = bal.get('info', {})
                data["equity"] = float(info.get('totalMarginBalance', 0))
                data["equity_pnl"] = float(info.get('totalUnrealizedProfit', 0))
            except Exception as e:
                if "-1021" not in str(e) and "-2008" not in str(e):
                    print(f"Error fetching live balance for status: {e}")
                data["equity"] = 0.0
                data["equity_pnl"] = 0.0
        else:
            data["equity"] = equity_curve[-1]
            data["equity_pnl"] = round(equity_curve[-1] - 10000, 4)

        # Universal Real-Time PnL calculation via Tickers
        if data.get("positions"):
            try:
                symbols = [p['symbol'] for p in data['positions']]
                tickers = bot.exchange.fetch_tickers(symbols)
                for pos in data["positions"]:
                    sym = pos['symbol']
                    ticker = tickers.get(sym) or tickers.get(f"{sym}:USDT")
                    if ticker and ticker.get('last'):
                        pos['unrealized_pnl'] = round(pos['qty'] * (ticker['last'] - pos['entry']) * (1 if pos['side'] == 'LONG' else -1), 4)
                    else:
                        pos['unrealized_pnl'] = 0.0
            except Exception as e:
                import traceback
                print(f"Error fetching PnL: {e}\n{traceback.format_exc()}")
                for pos in data["positions"]: pos['unrealized_pnl'] = 0.0
                    
        # Always fetch trade count regardless of mode
        try:
            import math
            trades_list, total_trades = trade_db.get_trades(limit=1000)
            data["trade_count"] = total_trades
            if len(trades_list) > 1:
                pnls = [t['pnl'] for t in trades_list if t['pnl'] is not None]
                if pnls:
                    mean_pnl = sum(pnls) / len(pnls)
                    variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
                    stdev = math.sqrt(variance)
                    data["sharpe_ratio"] = round(mean_pnl / stdev, 2) if stdev > 0 else 0.0
                else:
                    data["sharpe_ratio"] = 0.0
            else:
                data["sharpe_ratio"] = 0.0
        except Exception as e:
            print(f"Error computing sharpe: {e}")
            data["trade_count"] = 0
            data["sharpe_ratio"] = 0.0

        for pos in data.get("positions", []):
            margin = (pos.get('entry', 0) * pos.get('qty', 0)) / pos.get('leverage', 1)
            pos['unrealized_roe'] = (pos.get('unrealized_pnl', 0) / margin * 100) if margin > 0 else 0.0
            
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/history/csv")
def history_csv():
    trades, _ = trade_db.get_trades(limit=100000)
    
    import io
    import csv
    from flask import Response
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Symbol', 'Side', 'Entry', 'Exit', 'PnL (USDT)', 'ROE (%)', 'Reason', 'Closed At'])
    
    for t in trades:
        writer.writerow([
            t.get('id', ''),
            t.get('symbol', ''),
            t.get('side', ''),
            t.get('entry', ''),
            t.get('exit', ''),
            t.get('pnl', ''),
            t.get('roe', ''),
            t.get('reason', ''),
            t.get('closed_at', '')
        ])
        
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=trades_history.csv"}
    )

@app.route("/api/analytics")
def analytics():
    trades, total = trade_db.get_trades(limit=100000)
    if not trades:
        return jsonify({"error": "No trades found"}), 404
        
    # Reverse so oldest is first for cumulative equity
    trades = list(reversed(trades))
    
    overview = {
        "equity_curve": [], # {time, value}
        "symbols": {}, # sym: count
        "scatter": [] # {x: duration_hours, y: pnl}
    }
    
    stats = {
        "total_trades": total,
        "wins": 0,
        "losses": 0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "net_profit": 0.0,
        "longest_win_streak": 0,
        "longest_loss_streak": 0,
        "avg_win_duration_hrs": 0.0,
        "avg_loss_duration_hrs": 0.0,
    }
    
    risk = {
        "max_drawdown": 0.0,
        "max_drawdown_pct": 0.0,
        "worst_day": 0.0,
        "returns_histogram": {}, # "-1%": count
    }
    
    analysis = {
        "profit_by_symbol": {}
    }
    
    current_equity = 10000.0 # Starting simulated equity
    peak_equity = current_equity
    
    current_win_streak = 0
    current_loss_streak = 0
    
    total_win_duration = 0.0
    total_loss_duration = 0.0
    
    daily_returns = {}

    for t in trades:
        pnl = float(t.get('pnl') or 0.0)
        sym = t.get('symbol', 'UNKNOWN')
        
        # 1. Overview data
        current_equity += pnl
        overview["equity_curve"].append({"time": t.get("closed_at"), "value": round(current_equity, 2)})
        overview["symbols"][sym] = overview["symbols"].get(sym, 0) + 1
        
        # Duration calculation
        duration_hrs = 0.0
        try:
            from datetime import datetime, timezone
            closed = datetime.fromisoformat(t.get('closed_at').replace('Z', '+00:00'))
            opened = datetime.fromtimestamp(t.get('timestamp') / 1000, tz=timezone.utc)
            duration_hrs = (closed - opened).total_seconds() / 3600.0
        except:
            pass
            
        overview["scatter"].append({
            "x": round(duration_hrs, 2),
            "y": round(pnl, 2),
            "symbol": sym
        })
        
        # 2. Stats
        if pnl > 0:
            stats["wins"] += 1
            stats["gross_profit"] += pnl
            current_win_streak += 1
            current_loss_streak = 0
            stats["longest_win_streak"] = max(stats["longest_win_streak"], current_win_streak)
            total_win_duration += duration_hrs
        elif pnl < 0:
            stats["losses"] += 1
            stats["gross_loss"] += abs(pnl)
            current_loss_streak += 1
            current_win_streak = 0
            stats["longest_loss_streak"] = max(stats["longest_loss_streak"], current_loss_streak)
            total_loss_duration += duration_hrs
            
        # 3. Risk (Drawdown)
        if current_equity > peak_equity:
            peak_equity = current_equity
        drawdown = peak_equity - current_equity
        if drawdown > risk["max_drawdown"]:
            risk["max_drawdown"] = drawdown
            risk["max_drawdown_pct"] = (drawdown / peak_equity) * 100 if peak_equity > 0 else 0
            
        # Daily Returns
        try:
            day_str = closed.strftime('%Y-%m-%d')
            daily_returns[day_str] = daily_returns.get(day_str, 0) + pnl
        except:
            pass
            
        # 4. Analysis
        analysis["profit_by_symbol"][sym] = analysis["profit_by_symbol"].get(sym, 0.0) + pnl

    stats["net_profit"] = stats["gross_profit"] - stats["gross_loss"]
    stats["profit_factor"] = round(stats["gross_profit"] / stats["gross_loss"], 2) if stats["gross_loss"] > 0 else 999.0
    stats["win_rate"] = round((stats["wins"] / stats["total_trades"]) * 100, 2) if stats["total_trades"] > 0 else 0
    stats["avg_win_duration_hrs"] = round(total_win_duration / stats["wins"], 2) if stats["wins"] > 0 else 0
    stats["avg_loss_duration_hrs"] = round(total_loss_duration / stats["losses"], 2) if stats["losses"] > 0 else 0
    
    if daily_returns:
        risk["worst_day"] = min(daily_returns.values())
        for day, dpnl in daily_returns.items():
            pct = round((dpnl / 10000.0) * 100, 0) # Simulated pct relative to 10k start
            bucket = f"{int(pct)}%"
            risk["returns_histogram"][bucket] = risk["returns_histogram"].get(bucket, 0) + 1
            
    # Clean up floats
    stats["gross_profit"] = round(stats["gross_profit"], 2)
    stats["gross_loss"] = round(stats["gross_loss"], 2)
    stats["net_profit"] = round(stats["net_profit"], 2)
    risk["max_drawdown"] = round(risk["max_drawdown"], 2)
    risk["max_drawdown_pct"] = round(risk["max_drawdown_pct"], 2)
    risk["worst_day"] = round(risk["worst_day"], 2)
    for k in analysis["profit_by_symbol"]:
        analysis["profit_by_symbol"][k] = round(analysis["profit_by_symbol"][k], 2)

    return jsonify({
        "overview": overview,
        "stats": stats,
        "risk": risk,
        "analysis": analysis
    })

@app.route("/api/settings", methods=["GET", "POST"])
def settings_api():
    if not bot: return jsonify({"error": "bot not initialized"}), 503
    
    if request.method == "POST":
        data = request.json
        if "hard_stop" in data:
            bot.cfg.HARD_STOP_LOSS_USDT = float(data["hard_stop"])
        if "time_limit" in data:
            bot.cfg.TRADE_MAX_DURATION_MINUTES = float(data["time_limit"])
        return jsonify({"success": True})
        
    return jsonify({
        "hard_stop": bot.cfg.HARD_STOP_LOSS_USDT,
        "time_limit": bot.cfg.TRADE_MAX_DURATION_MINUTES
    })

@app.route("/api/history/clear", methods=["POST"])
def clear_history_api():
    try:
        trade_db.clear_trades()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/trades")
def get_trades_api():
    limit = int(request.args.get('limit', 10))
    page = int(request.args.get('page', 1))
    offset = (page - 1) * limit
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    trades, total = trade_db.get_trades(limit=limit, offset=offset, start_date=start_date, end_date=end_date)
    return jsonify({
        "trades": trades,
        "total": total,
        "page": page,
        "pages": (total // limit) + (1 if total % limit > 0 else 0)
    })

@app.route("/api/trade/close", methods=["POST"])
def force_close_trade():
    if not bot: return jsonify({"error": "bot not init"}), 503
    try:
        data = request.json
        symbol = data.get("symbol")
        if symbol in bot.positions:
            pos = bot.positions[symbol]
            current_price = bot.exchange.fetch_ticker(symbol)['last'] if not bot.cfg.PAPER else pos.entry
            bot._close(symbol, "MANUAL_FORCE_CLOSE", current_price)
            return jsonify({"status": "success", "msg": f"Closed {symbol}"})
        return jsonify({"error": "Position not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/account")
def account():
    if not bot: return jsonify({"error": "bot not init"}), 503
    try:
        import ccxt
        key = bot.cfg.API_KEY
        sec = bot.cfg.API_SECRET
        
        spot_urls, fut_urls = None, None
        if bot.cfg.DEMO_MODE:
            spot_urls = {
                'public': 'https://demo-api.binance.com/api/v3',
                'private': 'https://demo-api.binance.com/api/v3',
                'v1': 'https://demo-api.binance.com/api/v1',
                'v3': 'https://demo-api.binance.com/api/v3',
            }
            fut_urls = {
                'fapiPublic': 'https://demo-fapi.binance.com/fapi/v1',
                'fapiPrivate': 'https://demo-fapi.binance.com/fapi/v1',
                'fapiPrivateV2': 'https://demo-fapi.binance.com/fapi/v2',
                'fapiPrivateV3': 'https://demo-fapi.binance.com/fapi/v3',
            }

        ex_spot = ccxt.binance({'apiKey': key, 'secret': sec, 'options': {'defaultType': 'spot', 'margin': False, 'fetchCurrencies': False, 'adjustForTimeDifference': True, 'recvWindow': 60000}})
        if spot_urls: ex_spot.urls['api'].update(spot_urls)
        
        ex_fut = ccxt.binanceusdm({'apiKey': key, 'secret': sec, 'options': {'defaultType': 'future', 'fetchCurrencies': False, 'adjustForTimeDifference': True, 'recvWindow': 60000}})
        if fut_urls: ex_fut.urls['api'].update(fut_urls)

        spot_bal = {}
        try:
            ex_spot.load_time_difference()
            spot_bal = ex_spot.fetch_balance({'type': 'spot'})
        except Exception as e:
            if "-2008" not in str(e) and "-2015" not in str(e) and "-1022" not in str(e):
                print(f"Spot balance fetch failed: {e}")

        fut_bal = {}
        try:
            ex_fut.load_time_difference()
            fut_bal = ex_fut.fetch_balance({'type': 'future'})
        except Exception as e:
            if "-2008" not in str(e) and "-2015" not in str(e) and "-1022" not in str(e):
                print(f"Futures balance fetch failed: {e}")

        def extract_assets(bal_data):
            res = {}
            for asset, data in bal_data.items():
                if isinstance(data, dict) and 'total' in data and data['total'] > 0:
                    res[asset] = {"free": data.get("free", 0), "total": data["total"]}
            return res

        spot_res = extract_assets(spot_bal)
        fut_res = extract_assets(fut_bal)

        # Ensure base asset and USDT show up even if 0
        base = bot.cfg.SYMBOL.split("/")[0]
        for r, bal_data in [(spot_res, spot_bal), (fut_res, fut_bal)]:
            if base not in r: r[base] = {"free": bal_data.get(base, {}).get("free", 0), "total": bal_data.get(base, {}).get("total", 0)}
            if "USDT" not in r: r["USDT"] = {"free": bal_data.get("USDT", {}).get("free", 0), "total": bal_data.get("USDT", {}).get("total", 0)}
            
        return jsonify({"spot": spot_res, "futures": fut_res})
    except Exception as e:
        err_msg = f"Account fetch failed: {str(e)}"
        print(f"🔴 {err_msg}")
        return jsonify({"error": err_msg}), 500

@app.route("/api/candles")
def candles():
    if not bot: return jsonify([]), 503
    symbol = request.args.get("symbol", bot.cfg.SYMBOL)
    tf = request.args.get("timeframe", bot.cfg.TIMEFRAME)
    try:
        raw = bot.exchange.fetch_ohlcv(symbol, tf, limit=100)
        # Format for lightweight-charts: {time: unix_timestamp, open, high, low, close}
        formatted = [{"time": int(c[0]/1000), "open": c[1], "high": c[2], "low": c[3], "close": c[4]} for c in raw]
        return jsonify(formatted)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/logs")
def logs():
    return jsonify(activity_logs)

@app.route("/api/config", methods=["POST"])
def update_config():
    data = request.json
    if "symbol" in data:
        update_env_file("TRADING_SYMBOL", data["symbol"])
    if "auto_portfolio" in data:
        update_env_file("AUTO_PORTFOLIO", "true" if data["auto_portfolio"] else "false")
    if "paper" in data:
        update_env_file("PAPER", "true" if data["paper"] else "false")
    if "futures" in data:
        update_env_file("USE_FUTURES", "true" if data["futures"] else "false")
    
    # Restart bot to apply changes
    restart_bot()
    return jsonify({"status": "restarting"})
@app.route("/api/trade/manual", methods=["POST"])
def manual_trade():
    if not bot: return jsonify({"error": "bot not init"}), 503
    data = request.json
    action = data.get("action")
    if action not in ["LONG", "SHORT"]:
        return jsonify({"error": "invalid action"}), 400
    
    symbol = bot.cfg.SYMBOL
    try:
        # Fetch current price
        ticker = bot.exchange.fetch_ticker(symbol)
        price = ticker['last']
        
        # Get current regime if possible
        regime = None
        if symbol in bot.engines:
            regime = bot.engines[symbol].current_regime
            
        bot._enter(symbol, action, price, regime)
        return jsonify({"status": "executed", "side": action, "price": price})
    except Exception as e:
        from binance_executor import log_activity
        log_activity(f"🔴 Manual Trade Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(".env")
    restart_bot()
    app.run(host="0.0.0.0", port=5001, debug=False)
