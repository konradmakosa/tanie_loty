-- Schemat bazy historii ofert (MySQL; SQLite obsługiwany przez db.php).
CREATE TABLE IF NOT EXISTS runs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  ts DATETIME NOT NULL,
  tab VARCHAR(8) NOT NULL,
  n_offers INT NOT NULL
);

CREATE TABLE IF NOT EXISTS offers (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id INT NOT NULL,
  ts DATETIME NOT NULL,
  tab VARCHAR(8) NOT NULL,
  origin CHAR(3) NOT NULL,
  dest CHAR(3) NOT NULL,
  dest_city VARCHAR(64),
  country VARCHAR(64),
  country_code CHAR(2),
  date_out DATE NOT NULL,
  date_in DATE NOT NULL,
  nights SMALLINT,
  price DECIMAL(9,2) NOT NULL,
  airline_code VARCHAR(4),
  category VARCHAR(4),
  source VARCHAR(12),
  transfers_out TINYINT,
  transfers_in TINYINT,
  INDEX idx_route (origin, dest, ts),
  INDEX idx_ts (ts)
);

CREATE TABLE IF NOT EXISTS route_daily (
  day DATE NOT NULL,
  origin CHAR(3) NOT NULL,
  dest CHAR(3) NOT NULL,
  dep_month CHAR(7) NOT NULL,
  min_price DECIMAL(9,2) NOT NULL,
  n INT NOT NULL DEFAULT 1,
  PRIMARY KEY (day, origin, dest, dep_month)
);
