"""
regime_engine.py
────────────────────────────────────────────────────────────────────────────────
Regime-Adaptive Strategy Engine
Based on IIT KGP Quant Games 2026 Winner (Sharpe: 2.276)
Ref: github.com/Aditya26189/regime-adaptive-quantitative-trading

Regimes:
  TRENDING_BULL  — KER > 0.6, ADX > 25, price above EMAs
  TRENDING_BEAR  — KER > 0.6, ADX > 25, price below EMAs
  RANGING        — KER < 0.3, low ADX → RSI Boost mean-reversion
  VOLATILE       — ATR > 75th percentile → 50% size, 3× ATR stop
  LOW_VOL        — ATR < 25th percentile → 120% size, 1.5× ATR stop

Survival mechanisms:
  • Regime persistence: 3 bars required before switching
  • Auto-exit: trend positions closed on regime → RANGING
  • RSI Boosting: entry at RSI 26–30 (not 30), filtering 60% false breakdowns
  • Volatility-adjusted sizing
────────────────────────────────────────────────────────────────────────────────
"""

import logging
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from collections import deque

logger = logging.getLogger(__name__)


# ─── Enums ────────────────────────────────────────────────────────────────────

class Regime(Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGING       = "RANGING"
    VOLATILE      = "VOLATILE"
    LOW_VOL       = "LOW_VOL"
    UNKNOWN       = "UNKNOWN"


# ─── Config ───────────────────────────────────────────────────────────────────

@dataclass
class EngineConfig:
    # KER (Kaufman Efficiency Ratio)
    ker_period:         int   = 10
    ker_trend_thresh:   float = 0.6
    ker_range_thresh:   float = 0.3

    # ADX
    adx_period:         int   = 14
    adx_trend_thresh:   float = 25.0

    # ATR
    atr_period:         int   = 14
    atr_vol_high_pct:   float = 75.0   # above = VOLATILE
    atr_vol_low_pct:    float = 25.0   # below = LOW_VOL
    atr_lookback:       int   = 100    # bars for percentile calc

    # RSI
    rsi_period:         int   = 14
    rsi_oversold:       float = 30.0   # standard
    rsi_oversold_boost: float = 26.0   # RSI Boosting: actual entry threshold
    rsi_overbought:     float = 70.0
    rsi_overbought_boost: float = 74.0

    # EMA
    ema_fast:           int   = 9
    ema_slow:           int   = 21

    # Regime persistence filter (bars before accepting switch)
    persistence_bars:   int   = 3

    # Position sizing multipliers
    size_trending:      float = 1.00
    size_ranging:       float = 0.80
    size_volatile:      float = 0.50
    size_low_vol:       float = 1.20

    # ATR stop multipliers
    stop_trending:      float = 2.5
    stop_ranging:       float = 2.0
    stop_volatile:      float = 3.0
    stop_low_vol:       float = 1.5

    # R:R (TP = stop_mult × rr_ratio)
    rr_ratio:           float = 1.8

    # Min bars needed before engine produces signals
    min_bars:           int   = 50


# ─── Output dataclasses ───────────────────────────────────────────────────────

@dataclass
class RegimeState:
    regime:           Regime  = Regime.UNKNOWN
    confirmed:        bool    = False   # True only after persistence_bars
    bars_in_regime:   int     = 0

    # Raw indicator values
    ker:    float = 0.0
    adx:    float = 0.0
    atr:    float = 0.0
    rsi:    float = 50.0
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    atr_pct:  float = 0.5   # 0–1, percentile of current ATR

    # Derived parameters for this regime
    size_mult:  float = 1.0
    stop_mult:  float = 2.5
    tp_mult:    float = 4.5  # stop_mult × rr_ratio


@dataclass
class Signal:
    side:       str     = "NONE"   # LONG | SHORT | NONE
    reason:     str     = ""
    regime:     Regime  = Regime.UNKNOWN
    entry:      float   = 0.0
    stop_loss:  float   = 0.0
    take_profit: float  = 0.0
    size_mult:  float   = 1.0
    rsi:        float   = 50.0
    atr:        float   = 0.0


# ─── Engine ───────────────────────────────────────────────────────────────────

class RegimeEngine:
    """
    Stateful regime-adaptive engine.
    Call .update(candle_df) each bar with a DataFrame of OHLCV data.
    """

    def __init__(self, config: EngineConfig = None):
        self.cfg = config or EngineConfig()
        self._regime_candidate: Optional[Regime] = None
        self._candidate_count: int = 0
        self._confirmed_regime: Regime = Regime.UNKNOWN
        self._atr_history: deque = deque(maxlen=self.cfg.atr_lookback)
        self.state: RegimeState = RegimeState()

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self, df: pd.DataFrame) -> tuple[RegimeState, Signal]:
        """
        df must have columns: open, high, low, close, volume
        All lowercase. Index can be DatetimeIndex or RangeIndex.
        Returns (RegimeState, Signal).
        Signal.side == "NONE" means no actionable entry this bar.
        """
        if len(df) < self.cfg.min_bars:
            return self.state, Signal()

        indicators = self._compute_indicators(df)
        raw_regime = self._classify_regime(indicators)
        confirmed  = self._apply_persistence(raw_regime)
        self.state = self._build_state(indicators, confirmed)
        signal     = self._generate_signal(df, self.state)
        return self.state, signal

    # ── Indicator computation ─────────────────────────────────────────────────

    def _compute_indicators(self, df: pd.DataFrame) -> dict:
        close = df["close"].values
        high  = df["high"].values
        low   = df["low"].values

        ker      = self._ker(close, self.cfg.ker_period)
        adx      = self._adx(high, low, close, self.cfg.adx_period)
        atr      = self._atr(high, low, close, self.cfg.atr_period)
        rsi      = self._rsi(close, self.cfg.rsi_period)
        ema_fast = self._ema(close, self.cfg.ema_fast)
        ema_slow = self._ema(close, self.cfg.ema_slow)

        self._atr_history.append(atr)
        atr_arr = np.array(self._atr_history)
        atr_pct = float(np.sum(atr_arr <= atr) / len(atr_arr)) if len(atr_arr) > 1 else 0.5

        return dict(
            ker=ker, adx=adx, atr=atr, rsi=rsi,
            ema_fast=ema_fast, ema_slow=ema_slow,
            atr_pct=atr_pct, price=close[-1]
        )

    # ── Classification ────────────────────────────────────────────────────────

    def _classify_regime(self, ind: dict) -> Regime:
        cfg = self.cfg

        # Volatility overrides first
        if ind["atr_pct"] > cfg.atr_vol_high_pct / 100:
            return Regime.VOLATILE
        if ind["atr_pct"] < cfg.atr_vol_low_pct / 100:
            return Regime.LOW_VOL

        # Trending
        if ind["ker"] > cfg.ker_trend_thresh and ind["adx"] > cfg.adx_trend_thresh:
            if ind["ema_fast"] > ind["ema_slow"] and ind["price"] > ind["ema_fast"]:
                return Regime.TRENDING_BULL
            if ind["ema_fast"] < ind["ema_slow"] and ind["price"] < ind["ema_fast"]:
                return Regime.TRENDING_BEAR

        # Ranging
        if ind["ker"] < cfg.ker_range_thresh:
            return Regime.RANGING

        # Default → last confirmed, or RANGING
        return self._confirmed_regime if self._confirmed_regime != Regime.UNKNOWN else Regime.RANGING

    # ── Persistence filter ────────────────────────────────────────────────────

    def _apply_persistence(self, raw: Regime) -> Regime:
        """Require persistence_bars consecutive detections before confirming."""
        if raw == self._regime_candidate:
            self._candidate_count += 1
        else:
            self._regime_candidate = raw
            self._candidate_count  = 1

        if self._candidate_count >= self.cfg.persistence_bars:
            if raw != self._confirmed_regime:
                logger.info(f"Regime switch: {self._confirmed_regime.value} → {raw.value}")
            self._confirmed_regime = raw

        return self._confirmed_regime

    # ── State builder ─────────────────────────────────────────────────────────

    def _build_state(self, ind: dict, regime: Regime) -> RegimeState:
        cfg = self.cfg

        size_map = {
            Regime.TRENDING_BULL: cfg.size_trending,
            Regime.TRENDING_BEAR: cfg.size_trending,
            Regime.RANGING:       cfg.size_ranging,
            Regime.VOLATILE:      cfg.size_volatile,
            Regime.LOW_VOL:       cfg.size_low_vol,
            Regime.UNKNOWN:       0.0,
        }
        stop_map = {
            Regime.TRENDING_BULL: cfg.stop_trending,
            Regime.TRENDING_BEAR: cfg.stop_trending,
            Regime.RANGING:       cfg.stop_ranging,
            Regime.VOLATILE:      cfg.stop_volatile,
            Regime.LOW_VOL:       cfg.stop_low_vol,
            Regime.UNKNOWN:       cfg.stop_ranging,
        }

        size_mult = size_map[regime]
        stop_mult = stop_map[regime]

        return RegimeState(
            regime=regime,
            confirmed=(self._candidate_count >= self.cfg.persistence_bars),
            bars_in_regime=self._candidate_count,
            ker=round(ind["ker"], 4),
            adx=round(ind["adx"], 2),
            atr=round(ind["atr"], 6),
            rsi=round(ind["rsi"], 2),
            ema_fast=round(ind["ema_fast"], 4),
            ema_slow=round(ind["ema_slow"], 4),
            atr_pct=round(ind["atr_pct"], 3),
            size_mult=size_mult,
            stop_mult=stop_mult,
            tp_mult=round(stop_mult * cfg.rr_ratio, 2),
        )

    # ── Signal generation ─────────────────────────────────────────────────────

    def _generate_signal(self, df: pd.DataFrame, state: RegimeState) -> Signal:
        """
        Generates entry signal based on confirmed regime.
        No signal if regime not yet confirmed (persistence filter).
        """
        if not state.confirmed:
            return Signal(regime=state.regime)

        price = df["close"].iloc[-1]
        atr   = state.atr
        cfg   = self.cfg

        def make_signal(side, reason):
            if side == "LONG":
                sl = price - atr * state.stop_mult
                tp = price + atr * state.tp_mult
            else:
                sl = price + atr * state.stop_mult
                tp = price - atr * state.tp_mult
            return Signal(
                side=side, reason=reason, regime=state.regime,
                entry=round(price, 8), stop_loss=round(sl, 8),
                take_profit=round(tp, 8), size_mult=state.size_mult,
                rsi=state.rsi, atr=atr
            )

        # ── Trending Bull: momentum breakout
        if state.regime == Regime.TRENDING_BULL:
            if state.ema_fast > state.ema_slow and price > state.ema_fast:
                return make_signal("LONG", f"TRENDING_BULL breakout | KER={state.ker} ADX={state.adx}")

        # ── Trending Bear: short momentum
        elif state.regime == Regime.TRENDING_BEAR:
            if state.ema_fast < state.ema_slow and price < state.ema_fast:
                return make_signal("SHORT", f"TRENDING_BEAR short | KER={state.ker} ADX={state.adx}")

        # ── Ranging: RSI Boost mean-reversion
        #    Entry at RSI 26–30 (not 30) — the IIT KGP winning technique
        #    Delays entry by +4 RSI points filtering 60% false breakdowns
        elif state.regime == Regime.RANGING:
            if cfg.rsi_oversold_boost <= state.rsi <= cfg.rsi_oversold:
                return make_signal("LONG",  f"RSI_BOOST mean-revert LONG  | RSI={state.rsi} (zone 26–30)")
            if cfg.rsi_overbought <= state.rsi <= cfg.rsi_overbought_boost:
                return make_signal("SHORT", f"RSI_BOOST mean-revert SHORT | RSI={state.rsi} (zone 70–74)")

        # ── Volatile: extremes only (wider RSI thresholds)
        elif state.regime == Regime.VOLATILE:
            if state.rsi < 20:
                return make_signal("LONG",  f"VOLATILE extreme oversold  | RSI={state.rsi}")
            if state.rsi > 80:
                return make_signal("SHORT", f"VOLATILE extreme overbought | RSI={state.rsi}")

        # ── Low Vol: efficiency capture with momentum confirmation
        elif state.regime == Regime.LOW_VOL:
            if state.ema_fast > state.ema_slow and state.rsi < 60:
                return make_signal("LONG",  f"LOW_VOL efficiency LONG  | ATR%={state.atr_pct}")
            if state.ema_fast < state.ema_slow and state.rsi > 40:
                return make_signal("SHORT", f"LOW_VOL efficiency SHORT | ATR%={state.atr_pct}")

        return Signal(regime=state.regime)

    # ── Should auto-exit? ─────────────────────────────────────────────────────

    def should_exit_position(self, position_regime: Regime) -> tuple[bool, str]:
        """
        Returns (should_exit, reason).
        Auto-exits trend positions when market transitions to RANGING.
        """
        current = self._confirmed_regime

        # Trend → ranging auto-exit
        if position_regime in (Regime.TRENDING_BULL, Regime.TRENDING_BEAR):
            if current == Regime.RANGING:
                return True, f"AUTO_EXIT: trend position closed, regime → RANGING"
            if position_regime == Regime.TRENDING_BULL and current == Regime.TRENDING_BEAR:
                return True, f"AUTO_EXIT: bull reversed to TRENDING_BEAR"
            if position_regime == Regime.TRENDING_BEAR and current == Regime.TRENDING_BULL:
                return True, f"AUTO_EXIT: bear reversed to TRENDING_BULL"

        # Volatile → anything safe
        if position_regime == Regime.VOLATILE and current not in (Regime.VOLATILE, Regime.UNKNOWN):
            return True, f"AUTO_EXIT: volatility regime ended → {current.value}"

        return False, ""

    # ── Indicators (no pandas-ta dependency for core engine) ──────────────────

    @staticmethod
    def _ker(close: np.ndarray, period: int) -> float:
        """Kaufman Efficiency Ratio"""
        if len(close) < period + 1:
            return 0.5
        direction  = abs(close[-1] - close[-1 - period])
        volatility = np.sum(np.abs(np.diff(close[-period - 1:])))
        return float(direction / volatility) if volatility > 0 else 0.5

    @staticmethod
    def _rsi(close: np.ndarray, period: int) -> float:
        if len(close) < period + 1:
            return 50.0
        deltas = np.diff(close[-(period + 1):])
        gains  = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100 - 100 / (1 + rs))

    @staticmethod
    def _ema(close: np.ndarray, period: int) -> float:
        if len(close) < period:
            return float(close[-1])
        k   = 2.0 / (period + 1)
        ema = float(np.mean(close[:period]))
        for price in close[period:]:
            ema = price * k + ema * (1 - k)
        return ema

    @staticmethod
    def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
        if len(high) < period + 1:
            return float(np.mean(high[-period:] - low[-period:]))
        trs = []
        for i in range(-period, 0):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i]  - close[i - 1])
            )
            trs.append(tr)
        return float(np.mean(trs))

    @staticmethod
    def _adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
        """Wilder's ADX"""
        if len(high) < period * 2 + 1:
            return 20.0
        h, l, c = high[-(period * 2 + 1):], low[-(period * 2 + 1):], close[-(period * 2 + 1):]
        plus_dm, minus_dm, tr_list = [], [], []
        for i in range(1, len(h)):
            up   = h[i] - h[i - 1]
            down = l[i - 1] - l[i]
            plus_dm.append(max(up, 0)   if up > down else 0)
            minus_dm.append(max(down, 0) if down > up else 0)
            tr_list.append(max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])))

        def wilder_smooth(data, n):
            s = sum(data[:n])
            result = [s]
            for v in data[n:]:
                s = s - s / n + v
                result.append(s)
            return result

        atr_s  = wilder_smooth(tr_list, period)
        pdm_s  = wilder_smooth(plus_dm, period)
        mdm_s  = wilder_smooth(minus_dm, period)

        dx_list = []
        for a, p, m in zip(atr_s, pdm_s, mdm_s):
            if a == 0: continue
            pdi = 100 * p / a
            mdi = 100 * m / a
            dx_list.append(100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0)

        return float(np.mean(dx_list[-period:])) if dx_list else 20.0
