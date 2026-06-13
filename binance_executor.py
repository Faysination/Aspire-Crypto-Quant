"""
binance_executor.py
────────────────────────────────────────────────────────────────────────────────
Live Binance execution layer via ccxt.
Handles: order placement, position tracking, multi-pair portfolio scanning.
"""

import os
import time
import logging
import json
from datetime import datetime, timezone
from typing import Optional, Dict

import ccxt
import pandas as pd

from regime_engine import RegimeEngine, EngineConfig, Signal, Regime, RegimeState

logger = logging.getLogger(__name__)

# In-memory log buffer for the UI
activity_logs = []

def log_activity(msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    log_str = f"[{ts}] {msg}"
    logger.info(msg)
    activity_logs.append(log_str)
    if len(activity_logs) > 100:
        activity_logs.pop(0)

class BotConfig:
    def __init__(self):
        self.API_KEY        = os.environ.get("BINANCE_API_KEY", "").strip()
        self.API_SECRET     = os.environ.get("BINANCE_API_SECRET", "").strip()
        self.AUTO_PORTFOLIO = os.environ.get("AUTO_PORTFOLIO", "false").lower() == "true"
        self.SYMBOL         = os.environ.get("TRADING_SYMBOL", "BTC/USDT")
        self.TIMEFRAME      = os.environ.get("TIMEFRAME", "15m")
        self.CAPITAL_USDT   = float(os.environ.get("CAPITAL_USDT", "100"))
        self.MAX_POSITION_USDT = float(os.environ.get("MAX_POSITION_USDT", "1000.0"))
        self.RISK_PCT       = float(os.environ.get("RISK_PCT", "0.02"))
        self.USE_FUTURES    = os.environ.get("USE_FUTURES", "false").lower() == "true"
        self.TRADE_MAX_DURATION_MINUTES = float(os.environ.get("TRADE_MAX_DURATION_MINUTES", "45"))
        self.HARD_STOP_LOSS_USDT = float(os.environ.get("HARD_STOP_LOSS_USDT", "-25.0"))
        self.TRAILING_STOP_PROFIT_USDT = float(os.environ.get("TRAILING_STOP_PROFIT_USDT", "50.0"))
        self.TRAILING_STOP_DISTANCE_USDT = float(os.environ.get("TRAILING_STOP_DISTANCE_USDT", "10.0"))
        self.CANDLE_LIMIT   = 200
        self.POLL_SECONDS   = int(os.environ.get("POLL_SECONDS", "30"))
        self.TG_TOKEN       = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.TG_CHAT_ID     = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.PAPER          = os.environ.get("PAPER", "true").lower() == "true"
        self.DEMO_MODE      = os.environ.get("DEMO_MODE", "false").lower() == "true"
        lev_str = os.environ.get("LEVERAGE", "20").lower().replace("x", "").strip()
        self.LEVERAGE = int(lev_str) if lev_str.isdigit() else 20

class Position:
    def __init__(self, symbol: str, side: str, entry: float, qty: float, sl: float, tp: float, regime: Regime, order_id: str = "PAPER", leverage: int = 1, stop_order_id: str = None):
        self.symbol    = symbol
        self.side      = side
        self.entry     = entry
        self.qty       = qty
        self.sl        = sl
        self.tp        = tp
        self.regime    = regime
        self.order_id  = order_id
        self.leverage  = leverage
        self.stop_order_id = stop_order_id
        self.opened_at = datetime.now(timezone.utc).isoformat()
        
        # Trailing mechanics
        self.trailing_activated = False
        self.peak_pnl_usdt = 0.0

    def pnl(self, current_price: float) -> float:
        mult = 1 if self.side == "LONG" else -1
        return (current_price - self.entry) * self.qty * mult

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "side": self.side, "entry": self.entry, "qty": self.qty,
            "sl": self.sl, "tp": self.tp, "regime": self.regime.value,
            "order_id": self.order_id, "opened_at": self.opened_at, "leverage": self.leverage
        }

class PortfolioBot:
    def __init__(self, cfg: BotConfig = None):
        self.cfg = cfg or BotConfig()
        self.engines: Dict[str, RegimeEngine] = {}
        self.positions: Dict[str, Position] = {}
        self.loss_cooldowns: Dict[str, float] = {}
        self.trade_log: list = []
        self.running = False
        
        exchange_class = ccxt.binanceusdm if self.cfg.USE_FUTURES else ccxt.binance
        ex_config = {
            "options": {
                "defaultType": "future" if self.cfg.USE_FUTURES else "spot",
                "adjustForTimeDifference": True,
                "recvWindow": 60000
            },
            "enableRateLimit": True,
        }
        
        if self.cfg.API_KEY and "your_api_key" not in self.cfg.API_KEY:
            ex_config["apiKey"] = self.cfg.API_KEY
            ex_config["secret"] = self.cfg.API_SECRET

        self.exchange = exchange_class(ex_config)
        if self.cfg.DEMO_MODE:
            if self.cfg.USE_FUTURES:
                self.exchange.urls['api'].update({
                    'fapiPublic': 'https://demo-fapi.binance.com/fapi/v1',
                    'fapiPrivate': 'https://demo-fapi.binance.com/fapi/v1',
                    'fapiPrivateV2': 'https://demo-fapi.binance.com/fapi/v2',
                    'fapiPrivateV3': 'https://demo-fapi.binance.com/fapi/v3',
                })
            else:
                self.exchange.urls['api'].update({
                    'public': 'https://demo-api.binance.com/api/v3',
                    'private': 'https://demo-api.binance.com/api/v3',
                    'v1': 'https://demo-api.binance.com/api/v1',
                    'v3': 'https://demo-api.binance.com/api/v3',
                })
            # Fix for CCXT's fetch_currencies hitting SAPI
            self.exchange.options['fetchCurrencies'] = False
        
        mode = "AUTO-PORTFOLIO" if self.cfg.AUTO_PORTFOLIO else f"SINGLE ({self.cfg.SYMBOL})"
        log_activity(f"Bot init | Mode: {mode} | {'PAPER' if self.cfg.PAPER else 'LIVE'} | Market: {'FUTURES' if self.cfg.USE_FUTURES else 'SPOT'}")

    def run(self):
        self.running = True
        log_activity("🚀 Bot execution started.")
        self._alert(f"🚀 *Zoya Bot Started*\nMode: `{'PAPER' if self.cfg.PAPER else 'LIVE'}`\nPortfolio: `{'AUTO' if self.cfg.AUTO_PORTFOLIO else self.cfg.SYMBOL}`")

        while self.running:
            try:
                self._tick()
            except Exception as e:
                log_activity(f"🔴 Error in main loop: {e}")
                time.sleep(10)
            time.sleep(self.cfg.POLL_SECONDS)

    def _get_symbols_to_scan(self):
        if not self.cfg.AUTO_PORTFOLIO:
            return [self.cfg.SYMBOL]
        try:
            markets = self.exchange.fetch_tickers()
            # Filter USDT pairs (handles spot /USDT and futures /USDT:USDT)
            usdt_pairs = [v for k, v in markets.items() if (k.endswith('/USDT') or k.endswith('/USDT:USDT')) and 'quoteVolume' in v and v['quoteVolume']]
            # Sort by volume descending
            usdt_pairs.sort(key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)
            # Strip the :USDT suffix for uniformity
            top_pairs = [p['symbol'].split(':')[0] for p in usdt_pairs[:50]]
            if not top_pairs: return [self.cfg.SYMBOL]
            return top_pairs
        except Exception as e:
            logger.error(f"Failed to fetch market scanners, defaulting to {self.cfg.SYMBOL}: {e}")
            return [self.cfg.SYMBOL]

    def _tick(self):
        if self.cfg.USE_FUTURES and not self.cfg.PAPER:
            self._sync_positions()
        
        symbols = self._get_symbols_to_scan()
        for sym in symbols:
            if not self.running: break
            if sym not in self.engines:
                self.engines[sym] = RegimeEngine(EngineConfig())
            
            try:
                self._process_symbol(sym)
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Error processing {sym}: {e}")

    def _process_symbol(self, symbol: str):
        raw = self.exchange.fetch_ohlcv(symbol, self.cfg.TIMEFRAME, limit=self.cfg.CANDLE_LIMIT)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)

        current_price = float(df["close"].iloc[-1])
        engine = self.engines[symbol]
        state, signal = engine.update(df)

        pos = self.positions.get(symbol)
        
        if pos:
            self._check_exit(symbol, state, current_price)
        
        # Enter if flat and signal generated
        if signal.side != "NONE" and symbol not in self.positions:
            cooldown_time = self.loss_cooldowns.get(symbol, 0)
            if time.time() - cooldown_time < 3600:
                log_activity(f"⏳ Skipped entry for {symbol} due to 1-hour loss cooldown.")
            else:
                self._enter(symbol, signal, current_price, state)
                
        # Status log
        pos_str = f"OPEN {self.positions[symbol].side}" if symbol in self.positions else "FLAT"
        log_activity(f"Analyzed {symbol} @ ${current_price:.2f} | Regime: {state.regime.value} | {pos_str}")

    def _check_exit(self, symbol: str, state: RegimeState, current_price: float):
        pos = self.positions.get(symbol)
        if not pos: return

        # 0. Hard Stop Loss ($)
        pnl_usdt = pos.pnl(current_price)
        
        if pnl_usdt <= self.cfg.HARD_STOP_LOSS_USDT:
            self._close(symbol, f"HARD_STOP_USDT_{self.cfg.HARD_STOP_LOSS_USDT}", current_price)
            return

        # 1. Force Close Duration Limit
        from dateutil.parser import isoparse
        opened_time = isoparse(pos.opened_at)
        dur_minutes = (datetime.now(timezone.utc) - opened_time).total_seconds() / 60.0
        if dur_minutes >= self.cfg.TRADE_MAX_DURATION_MINUTES:
            self._close(symbol, f"TIME_LIMIT ({int(dur_minutes)}m)", current_price)
            return

        # 2. Trailing Stop Loss Logic
        pnl_usdt = pos.pnl(current_price)
        if pnl_usdt > pos.peak_pnl_usdt:
            pos.peak_pnl_usdt = pnl_usdt
            
        if pnl_usdt >= self.cfg.TRAILING_STOP_PROFIT_USDT:
            target_profit = pos.peak_pnl_usdt - self.cfg.TRAILING_STOP_DISTANCE_USDT
            target_profit = max(0.0, target_profit) # Break-even floor
            
            if pos.side == "LONG":
                new_sl = pos.entry + (target_profit / pos.qty)
                if new_sl > pos.sl:
                    self._update_stop_loss(symbol, pos, new_sl)
            else:
                new_sl = pos.entry - (target_profit / pos.qty)
                if new_sl < pos.sl or pos.sl >= 9999999999:
                    self._update_stop_loss(symbol, pos, new_sl)

        if pos.side == "LONG" and current_price <= pos.sl:
            self._close(symbol, "STOP_LOSS", current_price)
            return
        if pos.side == "SHORT" and current_price >= pos.sl:
            self._close(symbol, "STOP_LOSS", current_price)
            return
        if pos.side == "LONG" and current_price >= pos.tp:
            self._close(symbol, "TAKE_PROFIT", current_price)
            return
        if pos.side == "SHORT" and current_price <= pos.tp:
            self._close(symbol, "TAKE_PROFIT", current_price)
            return

        engine = self.engines[symbol]
        should_exit, reason = engine.should_exit_position(pos.regime)
        if should_exit:
            self._close(symbol, f"AUTO_EXIT | {reason}", current_price)

    def _update_stop_loss(self, symbol: str, pos: Position, new_sl: float):
        if pos.sl == new_sl: return
        pos.sl = new_sl
        if self.cfg.PAPER or not self.cfg.USE_FUTURES:
            log_activity(f"📈 Trailing SL updated for {symbol} to ${new_sl:.6f} (PAPER)")
            return
            
        try:
            # Cancel old native stop
            if pos.stop_order_id:
                try:
                    self.exchange.cancel_order(pos.stop_order_id, symbol)
                except: pass
                
            # Create new native stop
            stop_side = "sell" if pos.side == "LONG" else "buy"
            stop_price = float(self.exchange.price_to_precision(symbol, new_sl))
            stop_params = {'stopPrice': stop_price, 'reduceOnly': True}
            stop_order = self.exchange.create_order(symbol, "stop_market", stop_side, pos.qty, price=None, params=stop_params)
            pos.stop_order_id = str(stop_order.get("id", ""))
            log_activity(f"📈 Trailing SL locked for {symbol} at ${stop_price} (Target Profit Locked)")
        except Exception as e:
            logger.error(f"Failed to trail SL for {symbol}: {e}")

    def _enter(self, symbol: str, signal: Signal, current_price: float, state: RegimeState):
        stop_dist = abs(current_price - signal.stop_loss)
        if stop_dist == 0: return
        risk_usdt = self.cfg.CAPITAL_USDT * self.cfg.RISK_PCT * signal.size_mult
        qty = risk_usdt / stop_dist
        
        # --- AUTO LEVERAGE ---
        try:
            bal = self.exchange.fetch_balance({'type': 'future'})
            free_usdt = float(bal['USDT']['free'])
        except:
            free_usdt = self.cfg.CAPITAL_USDT
            
        if not self.cfg.PAPER and free_usdt < 10.0:
            log_activity(f"⚠️ Ignored {symbol} signal: Insufficient free margin ({free_usdt:.2f} USDT).")
            return
            
        notional = qty * current_price
        target_margin = max(free_usdt * 0.10, 5.0) # Aim to use 10% of free balance per trade
        auto_leverage = int(notional / target_margin)
        auto_leverage = max(1, min(auto_leverage, self.cfg.LEVERAGE)) # Clamp between 1x and user config limit
        
        # Cap position size to maximum leverage notional to prevent blowing out margins
        max_notional_qty = (self.cfg.CAPITAL_USDT * auto_leverage) / current_price
        qty = min(qty, max_notional_qty)
        
        # --- MAX NOTIONAL CLAMP ---
        max_usd_qty = self.cfg.MAX_POSITION_USDT / current_price
        qty = min(qty, max_usd_qty)
        
        # Apply Exchange Precision and Limits
        try:
            market = self.exchange.market(symbol)
            min_qty = market['limits']['amount']['min']
            
            # Use market order max limits (Binance MARKET_LOT_SIZE)
            max_qty = market['limits'].get('market', {}).get('max')
            if not max_qty: max_qty = market['limits']['amount']['max']
            
            if max_qty and qty > max_qty: qty = max_qty
            qty = float(self.exchange.amount_to_precision(symbol, qty))
            
            if qty < min_qty or (qty * current_price) < 5.0:
                log_activity(f"⚠️ Skipped {symbol}: Size {qty} too small for Binance minimums.")
                return
        except Exception as e:
            logger.warning(f"Precision format failed for {symbol}: {e}")
            qty = round(qty, 4)

        if qty <= 0: return

        order_id = "PAPER"
        if not self.cfg.PAPER:
            if self.cfg.USE_FUTURES:
                try:
                    self.exchange.set_leverage(auto_leverage, symbol)
                except Exception as e:
                    log_activity(f"⚠️ Could not set leverage for {symbol}: {e}")
            
            side_ccxt  = "buy" if signal.side == "LONG" else "sell"
            
            # Smart retry loop for Binance leverage tier position limits
            order = None
            max_retries = 6
            for attempt in range(max_retries):
                try:
                    order = self.exchange.create_order(symbol, "market", side_ccxt, qty)
                    break
                except Exception as e:
                    err_str = str(e)
                    if "-2027" in err_str or "maximum allowable position" in err_str:
                        if attempt < max_retries - 1:
                            qty = float(self.exchange.amount_to_precision(symbol, qty * 0.5))
                            log_activity(f"⚠️ {symbol} size too large for leverage tier. Halving qty to {qty} and retrying...")
                            continue
                        else:
                            log_activity(f"🔴 Order failed for {symbol}: Leverage too high for this altcoin's limit.")
                            return
                    elif "-4005" in err_str or "Quantity greater than max" in err_str:
                        log_activity(f"🔴 Order failed for {symbol}: Quantity {qty} exceeds exchange hard limits.")
                        return
                    else:
                        log_activity(f"🔴 Order failed for {symbol}: {e}")
                        return
            
            if not order: return
            order_id = str(order.get("id", "BINANCE"))
            avg = order.get("average")
            current_price = float(avg) if avg else current_price
            
            # --- DISPATCH NATIVE STOP MARKET ORDER ---
            stop_order_id = None
            if self.cfg.USE_FUTURES and signal.stop_loss > 0:
                try:
                    stop_side = "sell" if signal.side == "LONG" else "buy"
                    stop_price = float(self.exchange.price_to_precision(symbol, signal.stop_loss))
                    stop_params = {'stopPrice': stop_price, 'reduceOnly': True}
                    stop_order = self.exchange.create_order(symbol, "stop_market", stop_side, qty, price=None, params=stop_params)
                    stop_order_id = str(stop_order.get("id", ""))
                    log_activity(f"🔐 Placed hard STOP_MARKET for {symbol} at ${stop_price}")
                except Exception as e:
                    log_activity(f"⚠️ Could not place hard stop order for {symbol}: {e}")

        self.positions[symbol] = Position(
            symbol=symbol, side=signal.side, entry=current_price, qty=qty,
            sl=signal.stop_loss, tp=signal.take_profit, regime=signal.regime, order_id=order_id,
            leverage=auto_leverage if self.cfg.USE_FUTURES else 1, stop_order_id=stop_order_id
        )

        log_activity(f"ENTRY: {signal.side} {symbol} @ ${current_price:.4f} | Size: {qty} | Lev: {auto_leverage}x")
        self._alert(f"*{'PAPER' if self.cfg.PAPER else 'LIVE'} ENTRY*\n{signal.side} `{symbol}` @ `${current_price:.4f}`")

    def _sync_positions(self):
        try:
            raw_pos = self.exchange.fetch_positions()
            active_symbols = set()
            for rp in raw_pos:
                contracts = float(rp.get('contracts', 0) or 0)
                if contracts > 0:
                    sym = rp.get('symbol', '')
                    if ':' in sym: sym = sym.split(':')[0]
                    active_symbols.add(sym)
                    side = rp.get('side', 'LONG').upper()
                    entry = float(rp.get('entryPrice', 0))
                    
                    # Calculate leverage from initial margin if possible
                    lev = 1
                    try:
                        imp = float(rp.get('initialMarginPercentage', 0))
                        if imp > 0: lev = int(round(1 / imp))
                    except: pass
                    
                    # Add if not tracking
                    if sym not in self.positions:
                        dummy_sl = 0.0 if side == "LONG" else 9999999999.0
                        dummy_tp = 9999999999.0 if side == "LONG" else 0.0
                        
                        self.positions[sym] = Position(
                            symbol=sym, side=side, entry=entry, qty=contracts,
                            sl=dummy_sl, tp=dummy_tp, regime=Regime.UNKNOWN, order_id="BINANCE", leverage=lev
                        )
                        log_activity(f"SYNC: Adopted existing {side} position on {sym}")
            
            # Remove any positions tracked locally that are no longer active
            tracked_symbols = list(self.positions.keys())
            for sym in tracked_symbols:
                if sym not in active_symbols:
                    pos = self.positions.pop(sym)
                    pnl = pos.pnl(pos.entry) # We don't know the exact exit price
                    self.trade_log.append({
                        **pos.to_dict(),
                        "exit": pos.entry, "pnl": 0.0, "reason": "CLOSED_EXTERNALLY",
                        "closed_at": datetime.now(timezone.utc).isoformat()
                    })
                    log_activity(f"SYNC: {sym} was closed externally.")
        except Exception as e:
            pass

    def _close(self, symbol: str, reason: str, current_price: float):
        pos = self.positions.get(symbol)
        if not pos: return
        pnl = pos.pnl(current_price)

        if not self.cfg.PAPER:
            # --- CANCEL NATIVE STOP MARKET ---
            if getattr(pos, "stop_order_id", None):
                try:
                    self.exchange.cancel_order(pos.stop_order_id, symbol)
                    log_activity(f"🔓 Cancelled hard STOP_MARKET for {symbol}")
                except Exception as e:
                    pass # It might have already triggered
                    
            try:
                side_ccxt = "sell" if pos.side == "LONG" else "buy"
                
                # Fetch max market lot size for safe chunking of massive positions
                try:
                    market = self.exchange.market(symbol)
                    max_qty = market['limits'].get('market', {}).get('max')
                    if not max_qty: max_qty = market['limits']['amount']['max']
                except:
                    max_qty = float('inf')
                    
                remaining = pos.qty
                while remaining > 0:
                    chunk = min(remaining, max_qty) if max_qty else remaining
                    try:
                        chunk = float(self.exchange.amount_to_precision(symbol, chunk))
                    except: pass
                    
                    if chunk <= 0: break
                    self.exchange.create_order(symbol, "market", side_ccxt, chunk)
                    remaining -= chunk
                    
            except Exception as e:
                log_activity(f"🔴 Close order failed for {symbol}: {e}")

        import uuid
        closed_dt = datetime.now(timezone.utc)
        trade_id = pos.order_id if pos.order_id not in ("PAPER", "BINANCE") else str(uuid.uuid4())
        
        roe = 0.0
        if pos.entry > 0:
            roe = ((current_price - pos.entry) / pos.entry * pos.leverage * 100) if pos.side == "LONG" else ((pos.entry - current_price) / pos.entry * pos.leverage * 100)

        trade_dict = {
            **pos.to_dict(),
            "id": trade_id,
            "exit": current_price, 
            "pnl": round(pnl, 4), 
            "roe": round(roe, 4),
            "reason": reason,
            "closed_at": closed_dt.isoformat(),
            "timestamp": int(closed_dt.timestamp() * 1000)
        }
        
        self.trade_log.append(trade_dict)
        if pnl < 0:
            self.loss_cooldowns[symbol] = time.time()
        
        try:
            import trade_db
            trade_db.insert_trades([trade_dict])
        except Exception as e:
            logger.error(f"Failed to save trade to DB natively: {e}")

        log_activity(f"CLOSE: {symbol} | {reason} | PnL: {pnl:+.4f} USDT")
        self._alert(f"*{'PAPER' if self.cfg.PAPER else 'LIVE'} CLOSE*\n`{symbol}`\nReason: `{reason}`\nPnL: `{pnl:+.4f} USDT`")
        del self.positions[symbol]

    def _alert(self, message: str):
        if not self.cfg.TG_TOKEN or not self.cfg.TG_CHAT_ID: return
        try:
            import urllib.request
            url  = f"https://api.telegram.org/bot{self.cfg.TG_TOKEN}/sendMessage"
            data = json.dumps({"chat_id": self.cfg.TG_CHAT_ID, "text": message, "parse_mode": "Markdown"}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except: pass

    def get_status(self) -> dict:
        main_sym = self.cfg.SYMBOL
        engine = self.engines.get(main_sym)
        indicators = {}
        if engine:
            indicators = {
                "ker": engine.state.ker,
                "adx": engine.state.adx,
                "rsi": engine.state.rsi,
                "atr_pct": engine.state.atr_pct,
            }
        
        # Flatten all open positions
        active_positions = [p.to_dict() for p in self.positions.values()]
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": main_sym,
            "auto_portfolio": self.cfg.AUTO_PORTFOLIO,
            "paper": self.cfg.PAPER,
            "futures": self.cfg.USE_FUTURES,
            "regime": engine.state.regime.value if engine else "UNKNOWN",
            "indicators": indicators,
            "positions": active_positions,
            "trade_count": len(self.trade_log),
            "recent_trades": self.trade_log[-20:],
        }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    bot = PortfolioBot()
    bot.run()
