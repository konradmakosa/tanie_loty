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

CREATE TABLE IF NOT EXISTS subscribers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(190) NOT NULL,
  port VARCHAR(16) NOT NULL,
  token CHAR(32) NOT NULL UNIQUE,
  confirmed_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  last_sent_at DATETIME NULL,
  reminded_at DATETIME NULL,
  UNIQUE KEY uq_email_port (email, port)
);

CREATE TABLE IF NOT EXISTS alerts_sent (
  deal_id VARCHAR(48) NOT NULL,
  port VARCHAR(16) NOT NULL,
  sent_at DATETIME NOT NULL,
  PRIMARY KEY (deal_id, port)
);
