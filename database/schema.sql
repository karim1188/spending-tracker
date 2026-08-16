PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_message_guid TEXT NOT NULL UNIQUE,
    bank TEXT,
    sender TEXT,
    transaction_type TEXT,
    amount REAL,
    currency TEXT,
    merchant TEXT,
    card_last4 TEXT,
    account_last4 TEXT,
    transaction_time DATETIME,
    balance REAL,
    category TEXT,
    subcategory TEXT,
    raw_message TEXT,
    is_recurring INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS collector_state (
    source TEXT PRIMARY KEY,
    last_message_id INTEGER NOT NULL DEFAULT 0,
    last_checked_at DATETIME
);

CREATE TABLE IF NOT EXISTS bank_senders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bank TEXT NOT NULL,
    sender TEXT NOT NULL,
    UNIQUE (bank, sender)
);

CREATE TABLE IF NOT EXISTS merchant_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transactions_time ON transactions (transaction_time);
CREATE INDEX IF NOT EXISTS idx_transactions_bank ON transactions (bank);
CREATE INDEX IF NOT EXISTS idx_bank_senders_sender ON bank_senders (sender);

CREATE TABLE IF NOT EXISTS excluded_messages (
    guid TEXT PRIMARY KEY,
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sender_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT NOT NULL UNIQUE,
    category TEXT,
    bank TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notify_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recurring_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT,
    category TEXT,
    frequency TEXT NOT NULL DEFAULT 'monthly',
    source TEXT NOT NULL DEFAULT 'transaction',
    monthly_amount REAL NOT NULL DEFAULT 0,
    source_transaction_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);
