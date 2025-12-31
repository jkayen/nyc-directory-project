import streamlit as st
import sqlite3
import pandas as pd
import re

st.set_page_config(page_title="NYC History Database", layout="wide")

# --- STYLING ---
st.markdown("""
    <style>
    .main { background-color: #fdfaf0; }
    h1 { color: #2c3e50; font-family: 'Georgia', serif; }
    .stDataFrame { border: 2px solid #6d6d6d; }
    /* Limit height of the year selector to save space */
    .stMultiSelect div[data-baseweb="select"] > div:first-child {
        max-height: 150px;
        overflow-y: auto;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("🏙️ NYC Historical Directory Explorer")

# --- DATABASE HELPERS ---
def get_db_connection():
    return sqlite3.connect("nyc_history.db")

@st.cache_data
def get_available_years():
    try:
        conn = get_db_connection()
        df_years = pd.read_sql("SELECT DISTINCT year FROM directory ORDER BY year ASC", conn)
        conn.close()
        return [int(y) for y in df_years['year'].tolist()]
    except: return []

available_years = get_available_years()

# --- STATE & URL SYNC ---
if "year_selector" not in st.session_state:
    url_years = st.query_params.get_all("years")
    st.session_state["year_selector"] = [int(y) for y in url_years if y.isdigit()] if url_years else available_years

# --- UI: SEARCH FILTERS ---
col1, col2, col3 = st.columns(3)
with col1:
    name_q = st.text_input("Filter by Name", value=st.query_params.get("name", ""), placeholder="First or Last...")
with col2:
    occ_q = st.text_input("Filter by Occupation", value=st.query_params.get("occupation", ""), placeholder="Trade or job...")
with col3:
    addr_q = st.text_input("Filter by Address", value=st.query_params.get("address", ""), placeholder="Street or Number...")

# --- UI: YEAR SELECTION (Permanently Expanded) ---
st.write("### 📅 Select Years")
c1, c2, _ = st.columns([1, 1, 6])
if c1.button("Select All"): 
    st.session_state["year_selector"] = available_years
    st.rerun()
if c2.button("Deselect All"): 
    st.session_state["year_selector"] = []
    st.rerun()

final_selected_years = st.multiselect(
    "Include years:", available_years, key="year_selector", label_visibility="collapsed"
)

# High Quality Toggle
quality_toggle = st.checkbox("✨ High-Quality View Only (Hides OCR artifacts and incomplete addresses)", value=True)

# Sync URL Bar
st.query_params.update({
    "name": name_q, 
    "occupation": occ_q, 
    "address": addr_q, 
    "years": [str(y) for y in final_selected_years]
})

# --- DATA PROCESSING ---
if not final_selected_years:
    st.warning("Please select at least one year to view the ledger.")
    st.stop()

conn = get_db_connection()

# 1. Build the Dynamic WHERE clause
# This ensures the COUNT and the DATA use the exact same rules
where_clauses = [f"year IN ({','.join(['?']*len(final_selected_years))})"]
sql_params = list(final_selected_years)

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

where_sql = " WHERE " + " AND ".join(where_clauses)

# 2. Get THE ACCURATE COUNT (Instantly from SQL Index)
count_df = pd.read_sql(f"SELECT COUNT(*) as total FROM directory {where_sql}", conn, params=sql_params)
total_count = count_df['total'][0]

# 3. Get the Ledger Data
sql_data = f"""
    SELECT 
        first_name || ' ' || last_name as Name, 
        occupation as Occupation, 
        CASE WHEN home_address != '' THEN home_address ELSE business_address END as Address,
        business_address as 'Business Address', 
        year as Year, 
        publisher as Publisher, 
        printed_page as Page
    FROM directory 
    {where_sql}
    ORDER BY year ASC, street_sort ASC, house_sort ASC, last_name ASC 
    LIMIT 5000
"""

df = pd.read_sql(sql_data, conn, params=sql_params)
conn.close()

# --- DISPLAY RESULTS ---
st.write(f"### Results Found: {total_count:,}")

if total_count > 5000:
    st.caption(f"Showing the first 5,000 entries. Use the filters above to narrow your results.")

if not df.empty:
    df['Year'] = df['Year'].astype(str)
    st.dataframe(df, use_container_width=True, hide_index=True, height=750)
    
    # Download Button
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("💾 Download Visible Ledger (CSV)", csv, "nyc_ledger_export.csv", "text/csv")
else:
    st.info("No matching records found. Try adjusting your filters or the High-Quality toggle.")