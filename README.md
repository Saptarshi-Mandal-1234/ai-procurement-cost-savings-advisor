# AI Procurement Cost-Savings Advisor

A Streamlit-powered decision dashboard that transforms vendor and spend data into actionable procurement insights using Plotly visualisations and optional AI-generated narratives.

## Dataset
[Supply Chain Datasets – Kaggle](https://www.kaggle.com/datasets/ayodejiibrahimlateef/supply-chain-datasets)

---

## Architecture

| Layer | Technology |
|---|---|
| **Frontend** | Streamlit (3-page sidebar navigation, KPI cards, filters) |
| **Visualisations** | Plotly Express + Graph Objects (bar, line, pie, box, scatter) |
| **Backend / Data** | Pandas (data loading, joins, aggregations, delay computation) |
| **AI / GenAI** | OpenAI `gpt-4o-mini` (optional) with automatic rule-based fallback |

---

## Dashboard Pages

1. **Executive Overview** – KPI cards (total spend, avg delay, on-time %, active suppliers, potential savings), monthly spend vs delay trend, spend by category donut, auto-generated insights.
2. **Vendor & Spend Analysis** – Top 15 suppliers by spend, delay league table, monthly spend trend by category, unit-cost box plots, actual vs standard cost scatter, supplier ranking table.
3. **Risk, Savings & AI Advisor** – Supplier risk matrix (High / Medium / Low), spend concentration chart, renegotiation & consolidation savings bars, recommended actions table, AI tabs (Negotiation Brief, CFO Memo, Ask Your Data).

---

## AI Features

- **Negotiation Brief**: Per-supplier brief structured as Fact → Insight → Risk/Opportunity → Action.
- **CFO Memo**: Top-3 savings opportunities memo ready for executive review.
- **Ask Your Data**: Natural-language Q&A over summarised procurement statistics.

> The app runs **fully without an API key** — every AI output has a rule-based template fallback.  
> To enable live AI generation, set the environment variable:
> ```
> set OPENAI_API_KEY=sk-...      # Windows
> export OPENAI_API_KEY=sk-...   # macOS / Linux
> ```

---

## How to Run

```bash
pip install -r requirements.txt
streamlit run procurement_advisor.py
```

The app expects the data files in a `data/` subfolder relative to the script:
```
data/
  procurement_orders.csv
  supplier_master.csv
  product_master.csv
```

---

## Key Metrics & Formulas

| KPI | Formula |
|---|---|
| Delivery Delay | `Delivery_Date_Actual − Delivery_Date_Planned` (days) |
| On-Time Rate | `count(Delay ≤ 0) / total orders` |
| Potential Savings | `Σ (Actual Unit Cost − Standard Unit Cost) × Qty` for over-priced orders |
| Renegotiation Saving | `Σ (Actual Unit Cost − P25 cost per SKU) × Qty` |
| Consolidation Saving | `Actual multi-supplier spend − (lowest avg cost × total volume)` for SKUs with ≥3 suppliers |
| Supplier Risk Score | Delay + On-Time Rate + Spend Concentration sub-scores (0–6 scale) |
