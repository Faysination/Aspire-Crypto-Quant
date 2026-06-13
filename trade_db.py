import sqlite3
import os
from datetime import datetime

DB_PATH = "trades.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            entry REAL,
            exit REAL,
            pnl REAL,
            roe REAL,
            reason TEXT,
            closed_at TEXT,
            timestamp INTEGER
        )
    ''')
    try:
        c.execute('ALTER TABLE trades ADD COLUMN roe REAL')
    except:
        pass
    conn.commit()
    conn.close()

def insert_trades(trades: list):
    """
    trades is a list of dicts with:
    id, symbol, side, entry, exit, pnl, roe, reason, closed_at, timestamp
    Uses REPLACE INTO so existing trades with same ID are updated, not duplicated.
    """
    if not trades: return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    for t in trades:
        c.execute('''
            REPLACE INTO trades (id, symbol, side, entry, exit, pnl, roe, reason, closed_at, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            t.get('id'), t.get('symbol'), t.get('side'), t.get('entry', 0.0),
            t.get('exit', 0.0), t.get('pnl', 0.0), t.get('roe', 0.0), t.get('reason', ''),
            t.get('closed_at', ''), t.get('timestamp', 0)
        ))
        
    conn.commit()
    conn.close()

def get_trades(limit=10, offset=0, start_date=None, end_date=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = "SELECT * FROM trades WHERE 1=1"
    params = []
    
    if start_date:
        query += " AND closed_at >= ?"
        params.append(start_date + "T00:00:00Z")
    if end_date:
        query += " AND closed_at <= ?"
        params.append(end_date + "T23:59:59Z")
        
    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    c.execute(query, params)
    rows = c.fetchall()
    
    # Get total count for pagination
    count_query = "SELECT COUNT(*) FROM trades WHERE 1=1"
    count_params = []
    if start_date:
        count_query += " AND closed_at >= ?"
        count_params.append(start_date + "T00:00:00Z")
    if end_date:
        count_query += " AND closed_at <= ?"
        count_params.append(end_date + "T23:59:59Z")
        
    c.execute(count_query, count_params)
    total = c.fetchone()[0]
    
    conn.close()
    return [dict(r) for r in rows], total

def clear_trades():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM trades")
    conn.commit()
    conn.close()
