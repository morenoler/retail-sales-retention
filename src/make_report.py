"""Run the documented SQL definitions and build an offline HTML report."""

from __future__ import annotations

import csv
import html
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "retail.sqlite"
OUT = ROOT / "output"


def rows(conn: sqlite3.Connection, query: str) -> list[dict]:
    return [dict(row) for row in conn.execute(query)]


def save_csv(path: Path, data: list[dict]) -> None:
    if not data:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)


def month_offset(month: str, offset: int) -> str:
    year, number = map(int, month.split("-"))
    index = year * 12 + number - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def calculate(conn: sqlite3.Connection) -> dict:
    sql = (ROOT / "sql" / "analysis.sql").read_text(encoding="utf-8")
    conn.executescript(sql.split("-- Query 1:")[0])
    quality = rows(conn, """
        SELECT count(*) unique_lines,
               sum(customer_id IS NULL) missing_customer_lines,
               sum(upper(coalesce(invoice_no,'')) LIKE 'C%') cancellation_lines,
               sum(quantity <= 0) nonpositive_quantity_lines,
               sum(unit_price <= 0) nonpositive_price_lines,
               sum(invoice_date IS NULL) missing_date_lines
        FROM canonical_lines
    """)[0]
    quality["raw_lines"] = conn.execute("SELECT count(*) FROM invoice_lines").fetchone()[0]
    quality["overlap_lines"] = quality["raw_lines"] - quality["unique_lines"]
    quality["valid_sale_lines"] = conn.execute("SELECT count(*) FROM valid_sales").fetchone()[0]
    monthly = rows(conn, """
        SELECT invoice_month, count(DISTINCT invoice_no) orders,
               count(DISTINCT customer_id) identified_customers,
               round(sum(line_value), 2) merchandise_value_gbp,
               round(sum(line_value) / count(DISTINCT invoice_no), 2) average_order_value_gbp
        FROM valid_sales
        WHERE invoice_month BETWEEN '2010-01' AND '2011-11'
        GROUP BY invoice_month ORDER BY invoice_month
    """)
    cohorts_raw = rows(conn, """
        WITH activity AS (
          SELECT c.cohort_month, m.customer_id,
                 (cast(substr(m.invoice_month,1,4) AS INTEGER) -
                  cast(substr(c.cohort_month,1,4) AS INTEGER)) * 12 +
                 cast(substr(m.invoice_month,6,2) AS INTEGER) -
                 cast(substr(c.cohort_month,6,2) AS INTEGER) AS month_number
          FROM customer_months m JOIN customer_cohorts c USING (customer_id)
        )
        SELECT cohort_month, month_number, count(*) active_customers
        FROM activity WHERE month_number BETWEEN 0 AND 6
        GROUP BY cohort_month, month_number
        ORDER BY cohort_month, month_number
    """)
    by_cohort: dict[str, dict[int, int]] = {}
    for row in cohorts_raw:
        by_cohort.setdefault(row["cohort_month"], {})[row["month_number"]] = row["active_customers"]
    # Only full observation months count. Last complete month is 2011-11.
    cohorts = []
    for cohort, counts in by_cohort.items():
        if cohort < "2010-01" or month_offset(cohort, 6) > "2011-11":
            continue
        size = counts[0]
        cohorts.append({"cohort_month": cohort, "customers": size, **{
            f"m{i}": round(100 * counts.get(i, 0) / size, 1) for i in range(1, 7)
        }})
    countries = rows(conn, """
        SELECT country, count(DISTINCT invoice_no) orders,
               round(sum(line_value), 2) merchandise_value_gbp
        FROM valid_sales GROUP BY country
        ORDER BY merchandise_value_gbp DESC LIMIT 10
    """)
    cancellations = rows(conn, """
        SELECT substr(invoice_date,1,7) invoice_month,
               count(DISTINCT invoice_no) cancelled_invoices,
               round(sum(abs(quantity * unit_price)),2) cancellation_value_gbp
        FROM canonical_lines
        WHERE upper(coalesce(invoice_no,'')) LIKE 'C%'
          AND quantity < 0 AND unit_price > 0 AND invoice_date IS NOT NULL
        GROUP BY substr(invoice_date,1,7) ORDER BY invoice_month
    """)
    return {"quality": quality, "monthly": monthly, "cohorts": cohorts,
            "countries": countries, "cancellations": cancellations}


def build_html(result: dict) -> str:
    monthly, cohorts = result["monthly"], result["cohorts"]
    q = result["quality"]
    total = sum(x["merchandise_value_gbp"] for x in monthly)
    best = max(monthly, key=lambda x: x["merchandise_value_gbp"])
    mature = [x for x in cohorts if x["cohort_month"] <= "2011-08"]
    retention_3 = round(sum(x["customers"] * x["m3"] for x in mature) /
                        sum(x["customers"] for x in mature), 1)
    cohort_cells = "".join(
        "<tr><th>" + html.escape(c["cohort_month"]) + "</th>"
        + f"<td>{c['customers']:,}</td>"
        + "".join(f"<td style='background:rgba(35,112,137,{min(c[f'm{i}']/45, .8):.2f})'>"
                  f"{c[f'm{i}']:.1f}%</td>" for i in range(1, 7)) + "</tr>"
        for c in cohorts
    )
    country_cells = "".join(
        f"<tr><td>{html.escape(str(x['country']))}</td><td>{x['orders']:,}</td>"
        f"<td>£{x['merchandise_value_gbp']:,.0f}</td></tr>"
        for x in result["countries"]
    )
    data_json = json.dumps(monthly, ensure_ascii=False).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Продажи и удержание — Online Retail II</title>
<style>
:root {{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#18313b;background:#f5f8f8}}
* {{box-sizing:border-box}} body {{margin:0}} main {{max-width:1120px;margin:auto;padding:30px 24px 70px}}
header {{background:#113b49;color:#fff;padding:38px 24px}} header>div {{max-width:1072px;margin:auto}}
h1 {{font-size:clamp(28px,4vw,42px);margin:8px 0}} h2 {{margin:0 0 18px;font-size:22px}}
p {{line-height:1.55}} .eyebrow {{color:#a5d8cd;letter-spacing:.1em;text-transform:uppercase;font-size:12px}}
.muted {{color:#59717a;font-size:14px}} header .muted {{color:#d4e2e2}}
.grid {{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:22px 0}}
.card,.panel {{background:#fff;border:1px solid #dfe8e8;border-radius:12px;padding:20px}}
.card strong {{display:block;font-size:26px;margin:8px 0}} .card span {{font-size:13px;color:#59717a}}
.panel {{margin-top:16px}} .split {{display:grid;grid-template-columns:1.4fr 1fr;gap:16px}}
table {{border-collapse:collapse;width:100%;font-size:13px}} th,td {{padding:8px 10px;text-align:right;border-bottom:1px solid #e6eeee;white-space:nowrap}}
th:first-child,td:first-child {{text-align:left}} thead th {{color:#59717a;font-weight:600}}
.scroll {{overflow:auto}} .chart {{width:100%;height:260px}} button {{border:1px solid #9ab6bb;background:white;border-radius:7px;padding:7px 12px;cursor:pointer}}
button.active {{background:#14677b;color:white;border-color:#14677b}} .controls {{display:flex;gap:6px;margin-bottom:8px}}
.note {{border-left:3px solid #14677b;padding-left:12px}} a {{color:#14677b}}
@media(max-width:750px) {{.grid,.split {{grid-template-columns:1fr 1fr}}}}
@media(max-width:520px) {{.grid,.split {{grid-template-columns:1fr}} main {{padding:20px 14px}}}}
</style></head><body>
<header><div><div class="eyebrow">Исследование данных · UCI Online Retail II</div>
<h1>Продажи и удержание покупателей</h1>
<p class="muted">Транзакции британского онлайн-магазина, декабрь 2009 — декабрь 2011. Денежные значения — фунты стерлингов.</p></div></header>
<main>
<div class="grid">
 <div class="card"><span>Объём продаж за полные месяцы</span><strong>£{total/1_000_000:,.2f} млн</strong><span>Январь 2010 — ноябрь 2011</span></div>
 <div class="card"><span>Уникальных строк</span><strong>{q['unique_lines']:,}</strong><span>{q['overlap_lines']:,} повторов между листами убраны</span></div>
 <div class="card"><span>Месяц с наибольшим объёмом</span><strong>{best['invoice_month']}</strong><span>£{best['merchandise_value_gbp']:,.0f}</span></div>
 <div class="card"><span>Повторная покупка на 3-й месяц</span><strong>{retention_3:.1f}%</strong><span>Взвешено по размеру когорт</span></div>
</div>
<div class="split"><section class="panel"><h2>Динамика продаж</h2>
<div class="controls"><button class="active" data-metric="merchandise_value_gbp">Стоимость товаров</button><button data-metric="orders">Заказы</button></div>
<svg id="chart" class="chart" viewBox="0 0 650 260" role="img" aria-label="Динамика продаж по месяцам"></svg>
<p class="muted">Неполные декабрь 2009 и декабрь 2011 исключены из сравнения месяцев.</p></section>
<section class="panel"><h2>Как читать расчёты</h2>
<p><strong>Продажа:</strong> строка с положительными количеством и ценой, без префикса C в номере счёта.</p>
<p><strong>Удержание:</strong> доля покупателей когорты, совершивших хотя бы одну покупку в конкретном последующем месяце. Это не накопленная доля вернувшихся.</p>
<p><strong>Важное ограничение:</strong> первая покупка в файле может не быть первой покупкой клиента за всё время. Данные начинаются в декабре 2009 года.</p></section></div>
<section class="panel"><h2>Возврат покупателей по когортам</h2><div class="scroll"><table>
<thead><tr><th>Первая покупка</th><th>Клиентов</th><th>М+1</th><th>М+2</th><th>М+3</th><th>М+4</th><th>М+5</th><th>М+6</th></tr></thead>
<tbody>{cohort_cells}</tbody></table></div>
<p class="muted">Когорты с полным шестимесячным окном; повторная покупка считается только для клиентов с Customer ID. Цвет показывает величину доли.</p></section>
<section class="panel"><h2>Страны с наибольшим объёмом продаж</h2><div class="scroll"><table>
<thead><tr><th>Страна</th><th>Заказы</th><th>Стоимость товаров</th></tr></thead><tbody>{country_cells}</tbody></table></div></section>
<section class="panel"><h2>Качество данных и вывод</h2>
<p>Из {q['raw_lines']:,} строк исходной книги {q['overlap_lines']:,} продублированы между двумя листами в декабре 2010 года и учитываются один раз. {q['missing_customer_lines']:,} строк без Customer ID исключены из когортного анализа, но входят в общую стоимость продаж при выполнении остальных условий. В очищенном наборе {q['cancellation_lines']:,} строк с префиксом C; отмены считаются отдельно, поскольку нет надёжной связи каждой отмены с исходной продажей.</p>
<p class="note">Практический следующий шаг — исследовать, какие товары и каналы приводят клиентов с высокой вероятностью повторной покупки. В этом наборе нет каналов привлечения и маржи, поэтому здесь нельзя оценить окупаемость кампаний или прибыль.</p>
<p class="muted">Источник: <a href="https://archive.ics.uci.edu/dataset/502/online+retail+ii">UCI Online Retail II</a> · Chen, D. (2012), CC BY 4.0. Отчёт строится локально из исходного Excel-файла.</p></section>
</main><script>
const monthly={data_json};
function draw(metric) {{
 const svg=document.getElementById('chart'); const values=monthly.map(x=>x[metric]);
 const max=Math.max(...values)*1.08, left=52, top=16, width=580, height=190;
 const x=i=>left+i*width/(values.length-1), y=v=>top+height-v/max*height;
 const path=values.map((v,i)=>(i?'L':'M')+x(i).toFixed(1)+','+y(v).toFixed(1)).join(' ');
 let s=`<line x1="${{left}}" y1="${{top+height}}" x2="${{left+width}}" y2="${{top+height}}" stroke="#b9cdcf"/>`;
 s+=`<path d="${{path}}" fill="none" stroke="#14677b" stroke-width="3"/>`;
 values.forEach((v,i)=>{{s+=`<circle cx="${{x(i)}}" cy="${{y(v)}}" r="3" fill="#14677b"><title>${{monthly[i].invoice_month}}: ${{metric==='orders'?v.toLocaleString():('£'+v.toLocaleString())}}</title></circle>`}});
 [0,6,12,18,22].forEach(i=>{{s+=`<text x="${{x(i)}}" y="232" text-anchor="middle" font-size="11" fill="#59717a">${{monthly[i].invoice_month}}</text>`}});
 [0,.5,1].forEach(p=>{{s+=`<text x="44" y="${{y(max*p)+4}}" text-anchor="end" font-size="11" fill="#59717a">${{metric==='orders'?Math.round(max*p/1000)+'k':'£'+(max*p/1e6).toFixed(1)+'m'}}</text>`}});
 svg.innerHTML=s;
}}
document.querySelectorAll('button[data-metric]').forEach(b=>b.addEventListener('click',()=>{{document.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');draw(b.dataset.metric)}}));
draw('merchandise_value_gbp');
</script></body></html>"""


def main() -> None:
    if not DB.exists():
        raise FileNotFoundError("Run python src/build_db.py first")
    OUT.mkdir(exist_ok=True)
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        result = calculate(conn)
    for key in ("monthly", "cohorts", "countries", "cancellations"):
        save_csv(OUT / f"{key}.csv", result[key])
    (OUT / "dashboard.html").write_text(build_html(result), encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote dashboard and CSVs to {OUT}")


if __name__ == "__main__":
    main()
