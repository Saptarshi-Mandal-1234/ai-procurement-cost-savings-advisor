# AI Procurement Cost-Savings Advisor

This project is a simple but practical dashboard for procurement teams who want a clearer view of supplier performance, spending patterns, and savings opportunities.

Instead of looking through raw CSV files manually, this app brings the data together in one place and turns it into useful insights. It helps answer questions like:

- Which suppliers are costing the most?
- Which categories are driving spend?
- Are deliveries consistently late?
- Where are the best opportunities to cut cost or improve supplier performance?

---

## What the app does

The dashboard combines:
- supplier data,
- purchase order data,
- product information,
- and cost metrics

into a single Streamlit dashboard that lets users explore procurement data interactively.

It includes:
- KPI cards for spend, delay, and on-time performance
- charts for monthly spend and category trends
- supplier rankings and risk summaries
- savings opportunities based on price variance and fragmentation
- optional AI-generated summaries for negotiation and executive reporting

---

## Why this project exists

Procurement teams often have the data they need, but not the structure to make sense of it quickly. This project was built to make that process easier by turning operational procurement data into a clear, visual decision-support tool.

The idea is not to replace procurement judgment, but to support it with better visibility and faster analysis.

---

## Dashboard pages

### 1. Executive Overview
This page gives the high-level picture:
- total spend,
- average delay,
- on-time delivery,
- active suppliers,
- potential savings,
- and key category trends.

### 2. Vendor & Spend Analysis
This page focuses on where spend is going and how suppliers are performing:
- top suppliers by spend,
- delay by supplier,
- monthly spend trends by category,
- cost variation by product category,
- supplier ranking table.

### 3. Risk, Savings & AI Advisor
This page combines risk analysis and cost-saving recommendations:
- supplier risk classification,
- spend concentration,
- renegotiation opportunities,
- consolidation opportunities,
- recommended actions,
- AI-generated summaries when an API key is available.

---

## Data

The app expects the following files in a `data/` folder:

```bash
data/
  procurement_orders.csv
  supplier_master.csv
  product_master.csv
```

The dashboard reads these files, cleans the data, calculates key metrics, and builds the visuals.

---

## Tech stack

- Python
- Streamlit
- Pandas
- Plotly
- OpenAI API (optional)

---

## How to run

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Start the app:

```bash
streamlit run procurement_advisor.py
```

---

## AI features

The app can generate optional AI-based insights such as:
- negotiation brief for a supplier,
- CFO-style memo summarizing savings opportunities,
- natural-language Q&A about the procurement dataset.

If no OpenAI API key is set, the app falls back to a rule-based summary so the dashboard still works without external services.

To enable AI generation, set:

```bash
# Windows
set OPENAI_API_KEY=sk-...

# macOS / Linux
export OPENAI_API_KEY=sk-...
```

---

## Example use case

A procurement manager can use this dashboard to:
- review the suppliers contributing the most spend,
- identify categories with high cost variance,
- spot suppliers with poor delivery reliability,
- estimate savings from cost renegotiation or supplier consolidation,
- prepare a clearer business case for action.

This makes the tool useful for both operational review and executive decision-making.

---

## Repository contents

- `procurement_advisor.py` – main Streamlit application
- `README.md` – project documentation
- `requirements.txt` – Python dependencies
- `Project_Report.docx` – supporting project report

---

## Notes

This project is intentionally designed to be practical and easy to explore. It is best understood as a decision-support dashboard for procurement analysis rather than a large enterprise system, and it is intended to demonstrate how procurement data can be transformed into clear operational insights.
