-- Monetary figures are in GBP. This is recorded merchandise value, not profit.
-- Keep returns separate: a cancellation line does not necessarily identify its
-- original sale, so subtracting all refunds can distort a given month's sales.

-- The sheets overlap on 2010-12-01 through 2010-12-09: 22,523 identical rows.
-- Keep those rows from the first sheet and all later rows from the second.
DROP VIEW IF EXISTS canonical_lines;
CREATE VIEW canonical_lines AS
SELECT * FROM invoice_lines
WHERE source_sheet = 'Year 2009-2010'
   OR invoice_date >= '2010-12-10';

DROP VIEW IF EXISTS valid_sales;
CREATE VIEW valid_sales AS
SELECT source_sheet, source_row, invoice_no, stock_code, description,
       quantity, invoice_date, unit_price, customer_id, country,
       quantity * unit_price AS line_value,
       substr(invoice_date, 1, 7) AS invoice_month
FROM canonical_lines
WHERE invoice_no IS NOT NULL
  AND upper(invoice_no) NOT LIKE 'C%'
  AND quantity > 0
  AND unit_price > 0
  AND invoice_date IS NOT NULL;

DROP VIEW IF EXISTS customer_months;
CREATE VIEW customer_months AS
SELECT DISTINCT customer_id, invoice_month
FROM valid_sales
WHERE customer_id IS NOT NULL;

DROP VIEW IF EXISTS customer_cohorts;
CREATE VIEW customer_cohorts AS
SELECT customer_id, min(invoice_month) AS cohort_month
FROM customer_months
GROUP BY customer_id;

-- Query 1: data quality and scope. Categories are intentionally non-exclusive.
SELECT count(*) AS unique_lines,
       sum(customer_id IS NULL) AS missing_customer_lines,
       sum(upper(coalesce(invoice_no, '')) LIKE 'C%') AS cancellation_lines,
       sum(quantity <= 0) AS nonpositive_quantity_lines,
       sum(unit_price <= 0) AS nonpositive_price_lines,
       sum(invoice_date IS NULL) AS missing_date_lines
FROM canonical_lines;

-- Query 2: full-month sales trend. December 2009 and December 2011 are partial.
SELECT invoice_month, count(DISTINCT invoice_no) AS orders,
       count(DISTINCT customer_id) AS identified_customers,
       round(sum(line_value), 2) AS merchandise_value_gbp,
       round(sum(line_value) / count(DISTINCT invoice_no), 2) AS average_order_value_gbp
FROM valid_sales
WHERE invoice_month BETWEEN '2010-01' AND '2011-11'
GROUP BY invoice_month
ORDER BY invoice_month;

-- Query 3: cohort retention; month 0 is the first observed purchase.
-- The report filters cohorts by observation window before summarising.
WITH activity AS (
  SELECT c.cohort_month, m.customer_id, m.invoice_month,
         (cast(substr(m.invoice_month, 1, 4) AS INTEGER) -
          cast(substr(c.cohort_month, 1, 4) AS INTEGER)) * 12 +
         cast(substr(m.invoice_month, 6, 2) AS INTEGER) -
         cast(substr(c.cohort_month, 6, 2) AS INTEGER) AS month_number
  FROM customer_months m
  JOIN customer_cohorts c USING (customer_id)
)
SELECT cohort_month, month_number, count(*) AS active_customers
FROM activity
WHERE month_number BETWEEN 0 AND 12
GROUP BY cohort_month, month_number
ORDER BY cohort_month, month_number;

-- Query 4: leading markets, excluding lines with no positive merchandise value.
SELECT country, count(DISTINCT invoice_no) AS orders,
       round(sum(line_value), 2) AS merchandise_value_gbp
FROM valid_sales
GROUP BY country
ORDER BY merchandise_value_gbp DESC
LIMIT 10;

-- Query 5: cancellations are reported separately from positive sales.
SELECT substr(invoice_date, 1, 7) AS invoice_month,
       count(DISTINCT invoice_no) AS cancelled_invoices,
       round(sum(abs(quantity * unit_price)), 2) AS cancellation_value_gbp
FROM canonical_lines
WHERE upper(coalesce(invoice_no, '')) LIKE 'C%'
  AND quantity < 0 AND unit_price > 0 AND invoice_date IS NOT NULL
GROUP BY substr(invoice_date, 1, 7)
ORDER BY invoice_month;
