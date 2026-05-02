-- JAL LSP Optimizer DB Schema

CREATE TABLE IF NOT EXISTS airports (
    code        TEXT PRIMARY KEY,
    name_ko     TEXT,
    name_jp     TEXT,
    region      TEXT,
    is_base     INTEGER DEFAULT 0,
    tier        INTEGER DEFAULT 3   -- 1=high freq, 2=medium, 3=low
);

CREATE TABLE IF NOT EXISTS routes (
    origin       TEXT,
    destination  TEXT,
    miles        INTEGER NOT NULL,
    flight_min   INTEGER NOT NULL,    -- typical block time
    daily_freq   INTEGER DEFAULT 1,
    PRIMARY KEY (origin, destination)
);

CREATE TABLE IF NOT EXISTS flights (
    flight_no    TEXT,
    origin       TEXT,
    destination  TEXT,
    dep_time     TEXT,                  -- HH:MM
    arr_time     TEXT,                  -- HH:MM
    op_days      TEXT DEFAULT '1111111',-- 1=운항, 0=미운항. Mon=1번째자리
    PRIMARY KEY (flight_no, origin, destination, dep_time)
);

CREATE TABLE IF NOT EXISTS fare_cache (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    origin       TEXT,
    destination  TEXT,
    flight_date  TEXT,                  -- YYYY-MM-DD
    fare_class   TEXT,
    price_jpy    INTEGER,
    source       TEXT,                  -- 'manual', 'booking', 'amadeus', 'seed'
    confidence   INTEGER DEFAULT 1,     -- 3=booking, 2=manual recent, 1=amadeus, 0=seed
    observed_at  TEXT,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS bookings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    flight_no    TEXT,
    origin       TEXT,
    destination  TEXT,
    flight_date  TEXT,
    fare_class   TEXT,
    price_jpy    INTEGER,
    booked_at    TEXT,
    pnr          TEXT,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS amadeus_usage (
    month        TEXT PRIMARY KEY,      -- YYYY-MM
    call_count   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key          TEXT PRIMARY KEY,
    value        TEXT
);

CREATE INDEX IF NOT EXISTS idx_flights_origin       ON flights(origin);
CREATE INDEX IF NOT EXISTS idx_flights_dest         ON flights(destination);
CREATE INDEX IF NOT EXISTS idx_fare_cache_route     ON fare_cache(origin, destination, flight_date);
CREATE INDEX IF NOT EXISTS idx_routes_origin        ON routes(origin);
