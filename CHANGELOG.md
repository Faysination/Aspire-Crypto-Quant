# Changelog

All notable changes to the **Aspire Crypto Quant** project will be documented in this file.

## [Unreleased]
### Added
- **FX Blue Analytics Suite**: Added a completely new analytics dashboard separated into 4 distinct sub-tabs (Overview, Analysis, Stats, and Risk).
- **Institutional Metrics**: Calculates Win Rate, Max Drawdown, Net Profit, Longest Streaks, Average Durations, and Profit Factor based on SQLite trade history.
- **Export to CSV**: Added a button to instantly download full trade history as an Excel-ready spreadsheet (`/api/history/csv`).
- **Responsive Navigation Bar**: Upgraded the top bar into a sleek, full-width glass navigation menu for switching between the Live Dashboard and Analytics Suite.

### Changed
- **Full-Width Layout**: Redesigned the main interface to utilize 100% of horizontal screen space and elegantly collapse on mobile devices.
- **Toggle Labels**: Renamed top navigation toggles to "Single Pair", "Full Market", and "Demo" to be more intuitive.

### Fixed
- **Delayed Stop-Loss Execution ("Sleep Mode" Bug)**: Separated the open-position risk manager from the massive 300+ coin portfolio scanner. The engine now queries Binance for split-second tickers on all open positions every 2 seconds via a High-Frequency Background Loop, ensuring stops trigger instantly even if the UI is minimized.
- **Double-Entry Bug (1-Hour Cooldown bypass)**: `_sync_positions` now correctly intercepts native exchange Stop Market executions, fetches the closed order price, correctly logs the exact loss, and enforces the 1-hour `loss_cooldown` logic.
- **Timestamp Desync**: Fixed `-1021 Timestamp for this request was 1000ms ahead of the server's time` errors by implementing a time synchronization function on bot initialization.
- **Spot Wallet Fetch Error**: Suppressed expected `-2008 Invalid Api-Key ID` errors when probing the spot wallet with Futures-only API keys.

### Security
- **Git Tracking**: Removed `.env` from tracking and completely revoked the leaked Telegram Bot Token to secure the system.
