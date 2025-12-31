import streamlit as st
import sqlite3
import pandas as pd
import re
import altair as alt

st.set_page_config(page_title="NYC History Database", layout="wide")

# --- STYLING ---
st.markdown("""
    <style>
    .main { background-color: #fdfaf0; }
    h1 { color: #2c3e50; font-family: 'Georgia', serif; margin-bottom: -10px; }
    .stDataFrame { border: 1px solid #6d6d6d; }
    .stMultiSelect div[data-baseweb="select"] > div:first-child {
        max-height: 120px;
        overflow-y: auto;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("🏙️ NYC Historical Directory Explorer")

# --- DATABASE HELPERS ---
def get_db_connection():
    return sqlite3.connect("nyc_history.db")

@st.cache_data
def get_valid_years(threshold=1000):
    try:
        conn = get_db_connection()
        sql = "SELECT year FROM directory GROUP BY year HAVING COUNT(*) >= ? ORDER BY year ASC"
        df_years = pd.read_sql(sql, conn, params=(threshold,))
        conn.close()
        return [int(y) for y in df_years['year'].tolist()]
    except: return []

# --- FILTER DATA ---
available_years = get_valid_years(threshold=1000)

if not available_years:
    st.warning("⚠️ No fully processed volumes found (Threshold: 1,000+ entries).")
    st.stop()

# --- STATE & URL SYNC ---
params = st.query_params
if "year_selector" not in st.session_state:
    url_years = params.get_all("years")
    if url_years:
        st.session_state["year_selector"] = [int(y) for y in url_years if int(y) in available_years]
    else:
        st.session_state["year_selector"] = available_years

# --- UI: SEARCH FILTERS ---
col1, col2, col3 = st.columns(3)
with col1:
    name_q = st.text_input("Filter by Name", value=params.get("name", ""), placeholder="First or Last...")
with col2:
    occ_q = st.text_input("Filter by Occupation", value=params.get("occupation", ""), placeholder="Trade or job...")
with col3:
    addr_q = st.text_input("Filter by Address", value=params.get("address", ""), placeholder="Street or Number...")

# --- UI: YEAR SELECTION ---
st.write("### 📅 Select Years")
c1, c2, _ = st.columns([1, 1, 6])
if c1.button("Select All"): 
    st.session_state["year_selector"] = available_years
    st.rerun()
if c2.button("Deselect All"): 
    st.session_state["year_selector"] = []
    st.rerun()

final_selected_years = st.multiselect("Included editions:", available_years, key="year_selector", label_visibility="collapsed")
quality_toggle = st.checkbox("✨ High-Quality View Only", value=True)

# Sync URL
st.query_params.update({"name": name_q, "occupation": occ_q, "address": addr_q, "years": [str(y) for y in final_selected_years]})

# --- DATA PROCESSING ---
conn = get_db_connection()
where_clauses = []
sql_params = []

if quality_toggle:
    where_clauses.append("is_high_quality = 1")
if name_q:
    where_clauses.append("(last_name || ' ' || first_name || ' ' || first_name || ' ' || last_name) LIKE ? COLLATE NOCASE")
    sql_params.append(f"%{name_q}%")
if occ_q:
    where_clauses.append("occupation LIKE ? COLLATE NOCASE")
    sql_params.append(f"%{occ_q}%")
if addr_q:
    where_clauses.append("(business_address || ' ' || home_address) LIKE ? COLLATE NOCASE")
    sql_params.append(f"%{addr_q}%")

base_filter = " AND " + " AND ".join(where_clauses) if where_clauses else ""

# --- 📈 DATA VISUALIZATION (COMPACT, TIGHT Y, WITH GRID) ---
st.write("### 📈 Comparative Density")

chart_sql = f"""
    SELECT year, COUNT(*) as count 
    FROM directory 
    WHERE year IN ({','.join(['?']*len(available_years))}) {base_filter}
    GROUP BY year
"""
chart_data_raw = pd.read_sql(chart_sql, conn, params=available_years + sql_params)

# Map results to full timeline
full_timeline_df = pd.DataFrame(available_years, columns=['year'])
chart_df = full_timeline_df.merge(chart_data_raw, on='year', how='left').fillna(0)

# Create a static Altair Chart
line_chart = alt.Chart(chart_df).mark_line(
    color="#2c3e50", 
    strokeWidth=2.5,
    point=alt.OverlayMarkDef(color="#2c3e50", size=50) 
).encode(
    x=alt.X('year:O', title='Year', axis=alt.Axis(labelAngle=0, grid=True)), 
    y=alt.Y('count:Q', 
            title='Records', 
            scale=alt.Scale(zero=False, padding=10),
            axis=alt.Axis(grid=True)), 
    tooltip=['year', 'count']
).properties(
    height=180, # Slightly more compact
    width='container'
).configure_axis(
    gridColor="#EAEAEA", # Very light gray for the grid lines
    gridDash=[2, 2],    # Optional: subtle dashed lines
    domain=False
).configure_view(
    strokeWidth=0
)

st.altair_chart(line_chart, use_container_width=True)

# --- 📜 TABLE VIEW ---
if not final_selected_years:
    st.info("Select at least one year above to display the names ledger.")
    st.stop()

table_where = f" WHERE year IN ({','.join(['?']*len(final_selected_years))}) " + base_filter
table_params = list(final_selected_years) + sql_params

count_df = pd.read_sql(f"SELECT COUNT(*) as total FROM directory {table_where}", conn, params=table_params)
total_count = count_df['total'][0]

sql_data = f"""
    SELECT 
        first_name || ' ' || last_name as Name, 
        occupation as Occupation, 
        CASE WHEN home_address != '' THEN home_address ELSE business_address END as Address,
        business_address as 'Business Address', 
        year, publisher, printed_page
    FROM directory 
    {table_where}
    ORDER BY year ASC, street_sort ASC, house_sort ASC, last_name ASC 
    LIMIT 5000
"""

df = pd.read_sql(sql_data, conn, params=table_params)
conn.close()

st.write(f"### Results in Table: {total_count:,}")
if not df.empty:
    df['year'] = df['year'].astype(str)
    st.dataframe(df, use_container_width=True, hide_index=True, height=500)
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("💾 Download Table as CSV", csv, "nyc_ledger.csv", "text/csv")