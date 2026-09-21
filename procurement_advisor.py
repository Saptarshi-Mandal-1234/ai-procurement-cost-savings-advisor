"""
AI Procurement Cost-Savings Advisor
====================================
Streamlit + Plotly dashboard with 3 pages:
  1. Executive Overview
  2. Vendor & Spend Analysis
  3. Risk, Savings & AI Advisor
"""

import os
import warnings
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
#  DATA LOADING & PREPARATION
# ─────────────────────────────────────────────

DATA_DIR = "data"


@st.cache_data
def load_data():
    po = pd.read_csv(f"{DATA_DIR}/procurement_orders.csv")
    sm = pd.read_csv(f"{DATA_DIR}/supplier_master.csv")
    pm = pd.read_csv(f"{DATA_DIR}/product_master.csv")

    # Parse dates
    for col in ["Order_Date", "Delivery_Date_Planned", "Delivery_Date_Actual"]:
        po[col] = pd.to_datetime(po[col], errors="coerce")

    # Drop exact duplicates
    po.drop_duplicates(inplace=True)

    # Delivery delay in days (positive = late)
    po["Delay_Days"] = (po["Delivery_Date_Actual"] - po["Delivery_Date_Planned"]).dt.days
    po["On_Time"] = (po["Delay_Days"] <= 0).astype(int)
    po["Year_Month"] = po["Order_Date"].dt.to_period("M").astype(str)

    # Join supplier master
    df = po.merge(sm, on="Supplier_ID", how="left")

    # Join product master (keep Category, Subcategory, standard price, product name)
    pm_slim = pm[["Product_ID", "Category", "Subcategory", "Unit_Cost", "Standard_Price", "Product_Name"]].copy()
    pm_slim.rename(columns={"Unit_Cost": "Std_Unit_Cost", "Standard_Price": "Std_Price"}, inplace=True)
    df = df.merge(pm_slim, left_on="Raw_Material_ID", right_on="Product_ID", how="left")

    # Price variance: actual unit cost vs. product master standard cost
    df["Cost_Variance"] = df["Unit_Cost"] - df["Std_Unit_Cost"]

    # Data quality notes
    dq = {
        "Total PO rows": len(po),
        "Missing Certification_Level (supplier)": sm["Certification_Level"].isnull().sum(),
        "Missing Discontinuation_Date (product)": pm["Discontinuation_Date"].isnull().sum(),
        "PO rows with null Delay": df["Delay_Days"].isnull().sum(),
        "Duplicate POs removed": len(pd.read_csv(f"{DATA_DIR}/procurement_orders.csv")) - len(po),
    }
    return df, sm, pm, dq


# ─────────────────────────────────────────────
#  HELPER: KPI COMPUTATIONS
# ─────────────────────────────────────────────

def compute_kpis(df):
    total_spend = df["Total_Cost"].sum()
    avg_delay = df["Delay_Days"].mean()
    on_time_pct = df["On_Time"].mean() * 100
    active_suppliers = df["Supplier_ID"].nunique()

    # Potential savings: filter once so index alignment is guaranteed
    over = df[df["Cost_Variance"] > 0].copy()
    potential_savings = (over["Cost_Variance"] * over["Order_Quantity"]).sum()

    return {
        "Total Spend ($)": total_spend,
        "Avg Delivery Delay (days)": avg_delay,
        "On-Time Delivery (%)": on_time_pct,
        "Active Suppliers": active_suppliers,
        "Potential Savings ($)": potential_savings,
    }


# ─────────────────────────────────────────────
#  HELPER: RISK SCORING
# ─────────────────────────────────────────────

def compute_risk(df):
    sup = df.groupby(["Supplier_ID", "Supplier_Name"]).agg(
        Total_Spend=("Total_Cost", "sum"),
        Avg_Delay=("Delay_Days", "mean"),
        On_Time_Rate=("On_Time", "mean"),
        Order_Count=("PO_ID", "count"),
    ).reset_index()

    total_spend = sup["Total_Spend"].sum()
    sup["Spend_Share"] = sup["Total_Spend"] / total_spend

    def risk_flag(row):
        score = 0
        if row["Avg_Delay"] > 3:
            score += 2
        elif row["Avg_Delay"] > 1:
            score += 1
        if row["On_Time_Rate"] < 0.5:
            score += 2
        elif row["On_Time_Rate"] < 0.7:
            score += 1
        if row["Spend_Share"] > 0.10:
            score += 2
        elif row["Spend_Share"] > 0.05:
            score += 1
        if score >= 4:
            return "🔴 High"
        elif score >= 2:
            return "🟡 Medium"
        return "🟢 Low"

    sup["Risk_Level"] = sup.apply(risk_flag, axis=1)
    return sup.sort_values("Total_Spend", ascending=False)


# ─────────────────────────────────────────────
#  HELPER: SAVINGS OPPORTUNITIES
# ─────────────────────────────────────────────

def compute_savings(df):
    """
    Formula:
      Vendor consolidation savings = avg_unit_cost_top_supplier × total_alt_qty - total_alt_spend
      Price renegotiation savings   = (actual_unit_cost - p25_unit_cost) × qty  [for items above median variance]
    """
    # Renegotiation: items where actual unit cost > 25th percentile for that product
    p25 = df.groupby("Raw_Material_ID")["Unit_Cost"].quantile(0.25).rename("p25_cost")
    df2 = df.merge(p25, on="Raw_Material_ID")
    df2["Renego_Saving"] = (df2["Unit_Cost"] - df2["p25_cost"]).clip(lower=0) * df2["Order_Quantity"]
    renego = df2.groupby(["Raw_Material_ID", "Product_Name", "Category"])["Renego_Saving"].sum().reset_index()
    renego = renego[renego["Renego_Saving"] > 0].sort_values("Renego_Saving", ascending=False).head(10)

    # Consolidation: products bought from 3+ suppliers — cheapest supplier handles all volume
    multi = df.groupby(["Raw_Material_ID", "Supplier_ID"]).agg(
        Qty=("Order_Quantity", "sum"), Spend=("Total_Cost", "sum")
    ).reset_index()
    multi["Avg_Cost"] = multi["Spend"] / multi["Qty"]
    counts = multi.groupby("Raw_Material_ID")["Supplier_ID"].count()
    fragmented = counts[counts >= 3].index
    consol_savings = 0
    for pid in fragmented:
        rows = multi[multi["Raw_Material_ID"] == pid]
        min_cost = rows["Avg_Cost"].min()
        total_qty = rows["Qty"].sum()
        actual_spend = rows["Spend"].sum()
        best_spend = min_cost * total_qty
        consol_savings += max(0, actual_spend - best_spend)

    return renego, round(consol_savings, 2)


# ─────────────────────────────────────────────
#  HELPER: GENAI (with rule-based fallback)
# ─────────────────────────────────────────────

def call_llm(prompt: str, fallback_text: str) -> str:
    """Try OpenAI API; fall back to rule-based text on any failure."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return fallback_text
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.4,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return fallback_text


def negotiation_brief(sup_row, df):
    name = sup_row["Supplier_Name"]
    spend = f"${sup_row['Total_Spend']:,.0f}"
    delay = f"{sup_row['Avg_Delay']:.1f} days"
    otr = f"{sup_row['On_Time_Rate']*100:.1f}%"
    risk = sup_row["Risk_Level"]
    fallback = (
        f"**Negotiation Brief – {name}**\n\n"
        f"**Fact:** {name} accounts for {spend} total spend with an average delivery delay of {delay} "
        f"and on-time rate of {otr}.\n\n"
        f"**Insight:** Classified as {risk} risk. "
        f"{'Late deliveries are impacting production continuity.' if sup_row['Avg_Delay'] > 2 else 'Delivery performance is acceptable but cost optimisation is possible.'}\n\n"
        f"**Risk/Opportunity:** "
        f"{'High delay risk warrants penalty clauses or dual-sourcing.' if sup_row['Avg_Delay'] > 2 else 'Renegotiating unit costs could yield 5–8% savings.'}\n\n"
        f"**Action:** Schedule a supplier review, request a delivery improvement plan with monthly SLA reporting, "
        f"and benchmark unit costs against market rates. Introduce rebate clauses tied to on-time performance."
    )
    prompt = (
        f"Write a concise procurement negotiation brief (3 short paragraphs) for supplier '{name}'. "
        f"Stats: total spend={spend}, avg delay={delay}, on-time rate={otr}, risk={risk}. "
        f"Structure as Fact → Insight → Action. No bullet points."
    )
    return call_llm(prompt, fallback)


def cfo_memo(kpis, renego_df, consol_savings):
    top3 = renego_df.head(3)
    lines = "\n".join(
        f"- {r['Product_Name']} ({r['Category']}): ${r['Renego_Saving']:,.0f}" for _, r in top3.iterrows()
    )
    total_pot = kpis["Potential Savings ($)"]
    fallback = (
        f"**CFO Memo – Top 3 Savings Opportunities**\n\n"
        f"Total addressable savings identified: **${total_pot:,.0f}**\n\n"
        f"1. **Price Renegotiation** – Key items purchased above their 25th-percentile market cost:\n{lines}\n\n"
        f"2. **Vendor Consolidation** – Estimated **${consol_savings:,.0f}** recoverable by routing fragmented "
        f"multi-supplier orders to the lowest-cost qualified supplier per SKU.\n\n"
        f"3. **On-Time Delivery SLAs** – {100 - kpis['On-Time Delivery (%)']:.1f}% of orders are late "
        f"(avg {kpis['Avg Delivery Delay (days)']:.1f} days), causing downstream production costs. "
        f"Introducing financial penalties for delays is estimated to recover an additional 2–3% of spend.\n\n"
        f"**Recommendation:** Prioritise renegotiation with top-spend, high-variance suppliers this quarter."
    )
    prompt = (
        f"Write a CFO memo (3 numbered points) summarising the top 3 procurement savings opportunities. "
        f"Total spend: ${kpis['Total Spend ($)']:,.0f}. Potential savings: ${total_pot:,.0f}. "
        f"Top renegotiation items:\n{lines}\n"
        f"Consolidation savings: ${consol_savings:,.0f}. On-time rate: {kpis['On-Time Delivery (%)']:.1f}%. "
        f"Be concise and business-focused."
    )
    return call_llm(prompt, fallback)


def ask_data(question: str, df_summary: str) -> str:
    fallback = (
        "ℹ️ *No OpenAI API key set. To enable natural-language Q&A, add `OPENAI_API_KEY` to your environment.*\n\n"
        "In the meantime, here are quick stats:\n" + df_summary
    )
    prompt = (
        f"You are a procurement analyst. Answer this question concisely using the data summary below.\n"
        f"Question: {question}\n\nData summary:\n{df_summary}"
    )
    return call_llm(prompt, fallback)


# ─────────────────────────────────────────────
#  STREAMLIT APP
# ─────────────────────────────────────────────

st.set_page_config(page_title="AI Procurement Advisor", layout="wide", page_icon="📦")

df_full, sm, pm, dq = load_data()

# ── Sidebar ──────────────────────────────────
st.sidebar.title("📦 Procurement Advisor")
page = st.sidebar.radio("Navigate", ["Executive Overview", "Vendor & Spend Analysis", "Risk, Savings & AI Advisor"])

st.sidebar.markdown("---")
st.sidebar.subheader("Filters")

all_suppliers = sorted(df_full["Supplier_Name"].dropna().unique())
sel_suppliers = st.sidebar.multiselect("Supplier", all_suppliers, default=[])

all_cats = sorted(df_full["Category"].dropna().unique())
sel_cats = st.sidebar.multiselect("Category", all_cats, default=[])

min_date = df_full["Order_Date"].min().date()
max_date = df_full["Order_Date"].max().date()
date_range = st.sidebar.date_input("Order Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date)

# Apply filters
df = df_full.copy()
if sel_suppliers:
    df = df[df["Supplier_Name"].isin(sel_suppliers)]
if sel_cats:
    df = df[df["Category"].isin(sel_cats)]
if len(date_range) == 2:
    df = df[(df["Order_Date"].dt.date >= date_range[0]) & (df["Order_Date"].dt.date <= date_range[1])]

st.sidebar.markdown("---")
st.sidebar.caption("**Data Quality Notes**")
for k, v in dq.items():
    st.sidebar.caption(f"• {k}: **{v}**")

# ─────────────────────────────────────────────
#  PAGE 1: EXECUTIVE OVERVIEW
# ─────────────────────────────────────────────

if page == "Executive Overview":
    st.title("📊 Executive Overview")

    if df.empty:
        st.warning("No data matches the current filters. Please adjust the sidebar filters.")
        st.stop()

    kpis = compute_kpis(df)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("💰 Total Spend", f"${kpis['Total Spend ($)']:,.0f}")
    c2.metric("⏱ Avg Delay", f"{kpis['Avg Delivery Delay (days)']:.1f} days")
    c3.metric("✅ On-Time Delivery", f"{kpis['On-Time Delivery (%)']:.1f}%")
    c4.metric("🏭 Active Suppliers", f"{kpis['Active Suppliers']}")
    c5.metric("💡 Potential Savings", f"${kpis['Potential Savings ($)']:,.0f}")

    st.markdown("---")
    col_l, col_r = st.columns(2)

    with col_l:
        # Monthly spend trend
        monthly = df.groupby("Year_Month")["Total_Cost"].sum().reset_index()
        monthly_delay = df.groupby("Year_Month")["Delay_Days"].mean().reset_index()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=monthly["Year_Month"], y=monthly["Total_Cost"],
                                  name="Monthly Spend ($)", line=dict(color="#3b82d4")))
        fig.add_trace(go.Scatter(x=monthly_delay["Year_Month"], y=monthly_delay["Delay_Days"],
                                  name="Avg Delay (days)", yaxis="y2", line=dict(color="#e74c3c", dash="dot")))
        fig.update_layout(title="Monthly Spend vs. Avg Delay", yaxis=dict(title="Spend ($)"),
                          yaxis2=dict(title="Delay (days)", overlaying="y", side="right"),
                          legend=dict(orientation="h"), height=320)
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        # Spend by category
        cat_spend = df.groupby("Category")["Total_Cost"].sum().reset_index().sort_values("Total_Cost", ascending=False)
        fig2 = px.pie(cat_spend, names="Category", values="Total_Cost", title="Spend by Category",
                      color_discrete_sequence=px.colors.qualitative.Set2, hole=0.35)
        fig2.update_layout(height=320)
        st.plotly_chart(fig2, use_container_width=True)

    # Auto insights
    top_cat = cat_spend.iloc[0]["Category"]
    top_cat_pct = cat_spend.iloc[0]["Total_Cost"] / cat_spend["Total_Cost"].sum() * 100
    late_pct = 100 - kpis["On-Time Delivery (%)"]
    st.info(
        f"📌 **Insight 1:** **{top_cat}** is the top spend category at **{top_cat_pct:.1f}%** of total spend — "
        f"concentration risk; benchmark and renegotiate top-spend SKUs.\n\n"
        f"📌 **Insight 2:** **{late_pct:.1f}%** of orders arrived late (avg {kpis['Avg Delivery Delay (days)']:.1f} days). "
        f"Introducing SLA penalties could recover **${kpis['Potential Savings ($)']*0.03:,.0f}–${kpis['Potential Savings ($)']*0.05:,.0f}** annually."
    )

# ─────────────────────────────────────────────
#  PAGE 2: VENDOR & SPEND ANALYSIS
# ─────────────────────────────────────────────

elif page == "Vendor & Spend Analysis":
    st.title("🏭 Vendor & Spend Analysis")

    if df.empty:
        st.warning("No data matches the current filters. Please adjust the sidebar filters.")
        st.stop()

    # Spend by supplier
    sup_spend = df.groupby("Supplier_Name")["Total_Cost"].sum().reset_index().sort_values("Total_Cost", ascending=False).head(15)
    fig = px.bar(sup_spend, x="Total_Cost", y="Supplier_Name", orientation="h",
                 title="Top 15 Suppliers by Total Spend", labels={"Total_Cost": "Spend ($)", "Supplier_Name": ""},
                 color="Total_Cost", color_continuous_scale="Blues")
    fig.update_layout(height=380, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)

    with col1:
        # Avg delay by supplier (top 15 worst)
        delay_sup = df.groupby("Supplier_Name")["Delay_Days"].mean().reset_index().sort_values("Delay_Days", ascending=False).head(15)
        fig3 = px.bar(delay_sup, x="Delay_Days", y="Supplier_Name", orientation="h",
                      title="Top 15 Suppliers by Avg Delay", labels={"Delay_Days": "Avg Delay (days)", "Supplier_Name": ""},
                      color="Delay_Days", color_continuous_scale="Reds")
        fig3.update_layout(height=360)
        st.plotly_chart(fig3, use_container_width=True)

    with col2:
        # Monthly spend trend by category
        trend = df.groupby(["Year_Month", "Category"])["Total_Cost"].sum().reset_index()
        fig4 = px.line(trend, x="Year_Month", y="Total_Cost", color="Category",
                       title="Monthly Spend Trend by Category", labels={"Total_Cost": "Spend ($)", "Year_Month": ""})
        fig4.update_layout(height=360, xaxis_tickangle=-45)
        st.plotly_chart(fig4, use_container_width=True)

    col3, col4 = st.columns(2)

    with col3:
        # Price/unit-cost variation by category
        fig5 = px.box(df.dropna(subset=["Unit_Cost"]), x="Category", y="Unit_Cost",
                      title="Unit Cost Variation by Category", color="Category",
                      color_discrete_sequence=px.colors.qualitative.Pastel)
        fig5.update_layout(height=340, showlegend=False)
        st.plotly_chart(fig5, use_container_width=True)

    with col4:
        # Cost variance scatter (actual vs standard)
        samp_base = df.dropna(subset=["Cost_Variance", "Std_Unit_Cost"])
        if not samp_base.empty:
            samp = samp_base.sample(min(500, len(samp_base)), random_state=42)
            fig6 = px.scatter(samp, x="Std_Unit_Cost", y="Unit_Cost", color="Category",
                              title="Actual vs. Standard Unit Cost", opacity=0.6,
                              labels={"Std_Unit_Cost": "Standard Cost ($)", "Unit_Cost": "Actual Cost ($)"})
            # 45° reference line
            lim = max(float(samp["Std_Unit_Cost"].max()), float(samp["Unit_Cost"].max()))
            fig6.add_trace(go.Scatter(x=[0, lim], y=[0, lim], mode="lines", name="Parity", line=dict(dash="dash", color="grey")))
            fig6.update_layout(height=340)
            st.plotly_chart(fig6, use_container_width=True)
        else:
            st.info("Not enough data for cost variance scatter plot.")

    # Supplier ranking table
    st.subheader("Supplier Ranking Table")
    rank = df.groupby(["Supplier_ID", "Supplier_Name"]).agg(
        Total_Spend=("Total_Cost", "sum"),
        Avg_Delay=("Delay_Days", "mean"),
        On_Time_Rate=("On_Time", "mean"),
        Orders=("PO_ID", "count"),
    ).reset_index().sort_values("Total_Spend", ascending=False)
    rank["On_Time_Rate"] = (rank["On_Time_Rate"] * 100).round(1).astype(str) + "%"
    rank["Avg_Delay"] = rank["Avg_Delay"].round(2)
    rank["Total_Spend"] = rank["Total_Spend"].map("${:,.0f}".format)
    st.dataframe(rank.drop(columns=["Supplier_ID"]).reset_index(drop=True), use_container_width=True)

# ─────────────────────────────────────────────
#  PAGE 3: RISK, SAVINGS & AI ADVISOR
# ─────────────────────────────────────────────

elif page == "Risk, Savings & AI Advisor":
    st.title("⚠️ Risk, Savings & AI Advisor")

    if df.empty:
        st.warning("No data matches the current filters. Please adjust the sidebar filters.")
        st.stop()

    risk_df = compute_risk(df)
    renego_df, consol_savings = compute_savings(df)
    kpis = compute_kpis(df)

    # ── Risk Section ────────────────────────
    st.subheader("🔴 Supplier Risk Assessment")
    st.caption("Risk scoring: Avg Delay >3d (+2), >1d (+1) | On-Time Rate <50% (+2), <70% (+1) | Spend Share >10% (+2), >5% (+1) → High ≥4, Medium ≥2, Low <2")

    risk_display = risk_df[["Supplier_Name", "Risk_Level", "Total_Spend", "Avg_Delay", "On_Time_Rate", "Spend_Share"]].copy()
    risk_display["On_Time_Rate"] = (risk_display["On_Time_Rate"] * 100).round(1).astype(str) + "%"
    risk_display["Spend_Share"] = (risk_display["Spend_Share"] * 100).round(1).astype(str) + "%"
    risk_display["Total_Spend"] = risk_display["Total_Spend"].map("${:,.0f}".format)
    risk_display["Avg_Delay"] = risk_display["Avg_Delay"].round(2)
    st.dataframe(risk_display.reset_index(drop=True), use_container_width=True)

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        risk_counts = risk_df["Risk_Level"].value_counts().reset_index()
        fig_r = px.pie(risk_counts, names="Risk_Level", values="count", title="Supplier Risk Distribution",
                       color_discrete_map={"🔴 High": "#e74c3c", "🟡 Medium": "#f39c12", "🟢 Low": "#2ecc71"})
        st.plotly_chart(fig_r, use_container_width=True)
    with col_r2:
        top10 = risk_df.head(10).copy()
        top10["Spend_Share_Pct"] = (top10["Spend_Share"] * 100).round(1)
        fig_s = px.bar(top10, x="Supplier_Name", y="Spend_Share_Pct", color="Risk_Level",
                       title="Spend Concentration – Top 10 Suppliers",
                       labels={"Spend_Share_Pct": "Spend Share (%)", "Supplier_Name": ""},
                       color_discrete_map={"🔴 High": "#e74c3c", "🟡 Medium": "#f39c12", "🟢 Low": "#2ecc71"})
        fig_s.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig_s, use_container_width=True)

    # ── Savings Section ──────────────────────
    st.subheader("💰 Savings Opportunities")
    st.caption(
        "**Renegotiation formula:** Saving = (Actual Unit Cost − 25th-percentile cost for that SKU) × Quantity  \n"
        "**Consolidation formula:** Saving = Actual multi-supplier spend − (lowest avg cost × total volume) for SKUs with ≥3 suppliers"
    )

    col_s1, col_s2 = st.columns([2, 1])
    with col_s1:
        if not renego_df.empty:
            fig_renego = px.bar(renego_df, x="Renego_Saving", y="Product_Name", orientation="h",
                                color="Category", title="Top Renegotiation Opportunities by SKU",
                                labels={"Renego_Saving": "Potential Saving ($)", "Product_Name": ""})
            fig_renego.update_layout(height=320)
            st.plotly_chart(fig_renego, use_container_width=True)
        else:
            st.info("No renegotiation opportunities found in the current filter selection.")
    with col_s2:
        st.metric("🔀 Consolidation Savings", f"${consol_savings:,.0f}")
        st.metric("📋 Renegotiation Savings", f"${renego_df['Renego_Saving'].sum():,.0f}")
        st.metric("💡 Total Potential Savings", f"${kpis['Potential Savings ($)']:,.0f}")

    # ── Recommended Actions Table ────────────
    st.subheader("📋 Recommended Actions")
    high_risk = risk_df[risk_df["Risk_Level"] == "🔴 High"].head(3)
    actions = []
    for _, r in high_risk.iterrows():
        issue = ("High delay + low on-time rate" if r["Avg_Delay"] > 3 else "High spend concentration")
        actions.append({
            "Supplier": r["Supplier_Name"], "Issue": issue,
            "Action": "Implement SLA with penalty clauses; evaluate alternative suppliers",
            "Est. Impact": f"${r['Total_Spend']*0.03:,.0f} – ${r['Total_Spend']*0.05:,.0f} savings"
        })
    if not renego_df.empty:
        top_r = renego_df.iloc[0]
        actions.append({
            "Supplier": "Multiple", "Issue": f"High price variance on {top_r['Product_Name']}",
            "Action": "Renegotiate unit cost to 25th-percentile benchmark",
            "Est. Impact": f"${top_r['Renego_Saving']:,.0f}"
        })
    if consol_savings > 0:
        actions.append({
            "Supplier": "Multiple", "Issue": "Fragmented sourcing (≥3 suppliers per SKU)",
            "Action": "Consolidate to lowest-cost qualified supplier per SKU",
            "Est. Impact": f"${consol_savings:,.0f}"
        })
    st.dataframe(pd.DataFrame(actions), use_container_width=True)

    # ── AI Features ─────────────────────────
    st.markdown("---")
    st.subheader("🤖 AI Features")
    ai_tab1, ai_tab2, ai_tab3 = st.tabs(["Negotiation Brief", "CFO Memo", "Ask Your Data"])

    with ai_tab1:
        sel_sup = st.selectbox("Select Supplier", risk_df["Supplier_Name"].tolist())
        if st.button("Generate Negotiation Brief"):
            sup_row = risk_df[risk_df["Supplier_Name"] == sel_sup].iloc[0]
            with st.spinner("Generating…"):
                brief = negotiation_brief(sup_row, df)
            st.markdown(brief)

    with ai_tab2:
        if st.button("Generate CFO Memo"):
            with st.spinner("Generating…"):
                memo = cfo_memo(kpis, renego_df, consol_savings)
            st.markdown(memo)

    with ai_tab3:
        question = st.text_input("Ask a question about your procurement data:", placeholder="e.g. Which category has the highest average delay?")
        if st.button("Ask") and question:
            summary = (
                f"Total spend: ${kpis['Total Spend ($)']:,.0f}. "
                f"Avg delay: {kpis['Avg Delivery Delay (days)']:.1f} days. "
                f"On-time rate: {kpis['On-Time Delivery (%)']:.1f}%. "
                f"Active suppliers: {kpis['Active Suppliers']}. "
                f"Categories: {', '.join(df['Category'].dropna().unique())}. "
                f"Top supplier by spend: {risk_df.iloc[0]['Supplier_Name']} (${risk_df.iloc[0]['Total_Spend']:,.0f}). "
                f"Highest risk suppliers: {', '.join(risk_df[risk_df['Risk_Level']=='🔴 High']['Supplier_Name'].head(3).tolist())}."
            )
            with st.spinner("Thinking…"):
                answer = ask_data(question, summary)
            st.markdown(answer)
