DROP TABLE IF EXISTS refunds, orders, customers CASCADE;

DROP TABLE IF EXISTS refund_requests;

CREATE TABLE customers (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);
CREATE TABLE orders (
    id          TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    status      TEXT NOT NULL CHECK (status IN ('processing','shipped','delivered','cancelled')),
    carrier     TEXT,
    eta         DATE,            -- expected date while shipped, delivery date once delivered
    total       NUMERIC(10, 2) NOT NULL,
    placed_on   DATE NOT NULL
);
CREATE TABLE refunds (
    id           TEXT PRIMARY KEY,
    order_id     TEXT NOT NULL REFERENCES orders(id),
    amount       NUMERIC(10, 2) NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('requested','approved','paid')),
    requested_on DATE NOT NULL
);

CREATE TABLE refund_requests (
  id              SERIAL PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  order_id        TEXT NOT NULL,
  amount          NUMERIC(10,2) NOT NULL CHECK (amount > 0),
  reason          TEXT NOT NULL,
  status          TEXT NOT NULL CHECK (status IN ('pending_approval','executed','rejected')),
  flags           TEXT,
  decision_note   TEXT,
  reviewer        TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at      TIMESTAMPTZ
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_refunds_order ON refunds(order_id);

INSERT INTO customers (id, name, email) VALUES
  ('C001', 'Alice Example',  'alice@example.com'),
  ('C002', 'Bob Martin',     'bob.martin@example.com'),
  ('C003', 'Priya Nair',     'priya.nair@example.com'),
  ('C004', 'Carlos Diaz',    'carlos.diaz@example.com'),
  ('C005', 'Dana Whitfield', 'dana.w@example.com'),          -- no orders
  ('C006', 'Evan Cho',       'evan.cho@example.com'),         -- many orders
  ('C007', 'Grace Hopper',   'Grace.Hopper@Example.com');     -- mixed-case email

INSERT INTO orders (id, customer_id, status, carrier, eta, total, placed_on) VALUES
  ('A1001', 'C001', 'shipped',    'UPS',   '2026-10-10',  59.90, '2026-10-03'),
  ('A1002', 'C001', 'processing', NULL,    NULL,         120.00, '2026-10-06'),
  ('A1003', 'C001', 'delivered',  'FedEx', '2026-09-28',  35.50, '2026-09-22'),
  ('A1004', 'C002', 'delivered',  'DHL',   '2026-09-30',  89.99, '2026-09-25'),
  ('A1005', 'C002', 'cancelled',  NULL,    NULL,          45.00, '2026-10-01'),
  ('A1006', 'C003', 'shipped',    'FedEx', '2026-10-09', 210.00, '2026-10-04'),
  ('A1007', 'C003', 'delivered',  'UPS',   '2026-09-15',  15.25, '2026-09-10'),
  ('A1008', 'C004', 'delivered',  'UPS',   '2026-08-20', 300.00, '2026-08-15'),  -- old, outside return window
  ('A1009', 'C004', 'processing', NULL,    NULL,          72.40, '2026-10-07'),
  ('A1010', 'C006', 'shipped',    'DHL',   '2026-10-08',  19.99, '2026-10-05'),
  ('A1011', 'C006', 'shipped',    'UPS',   '2026-10-02',  64.00, '2026-09-27'),  -- shipped but ETA already passed
  ('A1012', 'C006', 'delivered',  'FedEx', '2026-10-01', 150.00, '2026-09-26'),
  ('A1013', 'C006', 'cancelled',  NULL,    NULL,          27.80, '2026-09-30'),
  ('A1014', 'C007', 'processing', NULL,    NULL,          99.00, '2026-10-06');

INSERT INTO refunds (id, order_id, amount, status, requested_on) VALUES
  ('R001', 'A1003',  35.50, 'paid',      '2026-10-01'),
  ('R002', 'A1005',  45.00, 'approved',  '2026-10-02'),
  ('R003', 'A1007',  15.25, 'requested', '2026-10-05'),
  ('R004', 'A1012',  50.00, 'approved',  '2026-10-04'),   -- partial refund
  ('R005', 'A1013',  27.80, 'paid',      '2026-10-01');