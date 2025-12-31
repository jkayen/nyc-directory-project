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
    /* Prevent the multiselect area from becoming a massive list of tags */
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
def get_available_years():
    try:
        conn = get_db_connection()
        df_years = pd.read_sql("SELECT DISTINCT year FROM directory ORDER BY year ASC", conn)
        conn.close()
        return [int(y) for y in df_years['year'].tolist()]
    except:
        return []

available_years = get_available_years()

# --- SESSION STATE & URL SYNC ---
# This is the key to making the "Select All" buttons work visually
if "year_selector" not in st.session_state:
    # Try to load from URL params first, otherwise default to all years
    url_years = st.query_params.get_all("years")
    if url_years:
        st.session_state["year_selector"] = [int(y) for y in url_years if y.isdigit()]
    else:
        st.session_state["year_selector"] = available_years

# --- UI: SEARCH FILTERS ---
col1, col2, col3 = st.columns(3)
with col1:
    name_query = st.text_input("Filter by Name", value=st.query_params.get("name", ""), placeholder="First or Last name...")
with col2:
    occ_query = st.text_input("Filter by Occupation", value=st.query_params.get("occupation", ""), placeholder="e.g. 'Grocer'...")
with col3:
    addr_query = st.text_input("Filter by Address", value=st.query_params.get("address", ""), placeholder="Street or Number...")

# --- UI: YEAR SELECTION BUTTONS ---
st.write("**Target Years**")
btn_col1, btn_col2, _ = st.columns([1, 1, 6])

if btn_col1.button("Select All"):
    st.session_state["year_selector"] = available_years
    st.rerun()

if btn_col2.button("Deselect All"):
    st.session_state["year_selector"] = []
    st.rerun()

# The widget is now bound to the 'year_selector' key in session_state
final_selected_years = st.multiselect(
    "Include these years in search:",
    options=available_years,
    key="year_selector",
    label_visibility="collapsed"
)

quality_toggle = st.checkbox("✨ High-Quality View Only", value=True)

# Update URL Bar for sharing
st.query_params.update({
    "name": name_query,
    "occupation": occ_query,
    "address": addr_query,
    "years": [str(y) for y in final_selected_years]
})

# --- DATA PROCESSING ---
if not final_selected_years:
    st.warning("Please select at least one year to view data.")
    st.stop()

conn = get_db_connection()

# Query with hidden sort columns included
sql = f"""
    SELECT 
        year, 
        first_name || ' ' || last_name as Name, 
        occupation, 
        CASE WHEN home_address != '' THEN home_address ELSE business_address END as Address,
        business_address as 'Business Address', 
        publisher, 
        printed_page,
        street_sort,
        house_sort,
        last_name
    FROM directory 
    WHERE year IN ({','.join(['?']*len(final_selected_years))})
"""
sql_params = list(final_selected_years)

if quality_toggle:
    sql += " AND is_high_quality = 1"
if name_query:
    sql += " AND (last_name || ' ' || first_name || ' ' || first_name || ' ' || last_name) LIKE ? COLLATE NOCASE"
    sql_params.append(f"%{name_query}%")
if occ_query:
    sql += " AND occupation LIKE ? COLLATE NOCASE"
    sql_params.append(f"%{occ_query}%")
if addr_query:
    sql += " AND (business_address || ' ' || home_address) LIKE ? COLLATE NOCASE"
    sql_params.append(f"%{addr_query}%")

# 1. Total Count
count_df = pd.read_sql(f"SELECT COUNT(*) as total FROM ({sql})", conn, params=sql_params)
total_matches = count_df['total'][0]

# 2. Sorted Data
sql += " ORDER BY year ASC, street_sort ASC, house_sort ASC, last_name ASC LIMIT 5000"
df = pd.read_sql(sql, conn, params=sql_params)
conn.close()

# --- DISPLAY ---
st.write(f"### Found {total_matches:,} matches")
if total_matches > 5000:
    st.info("💡 Showing first 5,000 results. Filter further to narrow your research.")

if not df.empty:
    # Remove internal sort columns before display
    display_cols = ['year', 'Name', 'occupation', 'Address', 'Business Address', 'publisher', 'printed_page']
    df_display = df[display_cols]
    df_display['year'] = df_display['year'].astype(str)
    
    st.dataframe(
        df_display, 
        use_container_width=True, 
        hide_index=True, 
        height=700
    )

    # Export
    csv = df_display.to_csv(index=False).encode('utf-8')
    st.download_button("💾 Export Results to CSV", csv, "nyc_results.csv", "text/csv")