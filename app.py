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
    </style>
    """, unsafe_allow_html=True)

st.title("🏙️ NYC Historical Directory Explorer")

# --- DATA QUALITY & SORTING HELPERS ---
def is_likely_human_readable(row):
    """Gatekeeper: Hides noisy OCR debris."""
    fields = [str(row['last_name']), str(row['first_name']), str(row['occupation']), 
              str(row['business_address']), str(row['home_address'])]
    text_blob = " ".join(fields)
    # Filter illegal symbols
    if re.search(r"[^a-zA-Z0-9\s.,']", text_blob): return False
    # Filter split house numbers (e.g. 5 1 Read)
    if re.search(r'^\d+\s+\d+\s+', str(row['business_address'])): return False
    # Gibberish check
    for w in text_blob.lower().split():
        if len(w) > 4 and w.isalpha() and not any(v in w for v in 'aeiouy'): return False
    return True

def parse_address_for_sorting(addr):
    """Extracts street name and house number for natural sorting."""
    if not addr or pd.isna(addr) or str(addr).strip() == "":
        return "~~~~", 999999
    s = re.sub(r'^\s*r\.\s*|^\s*rear\s*', '', str(addr), flags=re.IGNORECASE).strip()
    num_match = re.match(r'^(\d+)', s)
    house_num = int(num_match.group(1)) if num_match else 0
    street_name = re.sub(r'^\d+\s*', '', s).strip().lower()
    if not street_name: street_name = "~~~~"
    return street_name, house_num

def parse_page_for_sorting(pg):
    """Extracts numeric value from page strings for 1, 2, 10 sorting."""
    if not pg or pd.isna(pg): return 999999
    # Find the first group of digits in the string
    match = re.search(r'(\d+)', str(pg))
    return int(match.group(1)) if match else 999999

# --- DATABASE HELPERS ---
def get_db_connection():
    return sqlite3.connect("nyc_history.db")

@st.cache_data
def get_available_years():
    try:
        conn = get_db_connection()
        df_years = pd.read_sql("SELECT DISTINCT year FROM directory ORDER BY year ASC", conn)
        conn.close()
        return df_years['year'].tolist()
    except: return []

# --- URL QUERY PARAMETER SYNC ---
params = st.query_params

# --- UI: FILTERS ---
col1, col2, col3 = st.columns(3)
with col1:
    name_input = st.text_input("Filter by Name", value=params.get("name", ""), placeholder="First or Last...")
with col2:
    occ_input = st.text_input("Filter by Occupation", value=params.get("occupation", ""), placeholder="e.g. 'Grocer'...")
with col3:
    addr_input = st.text_input("Filter by Address", value=params.get("address", ""), placeholder="Street or Number...")

quality_toggle = st.checkbox("✨ High-Quality View (Hides rows with symbols or noisy OCR)", value=True)

available_years = get_available_years()
if available_years:
    try:
        start_val = int(params.get("startYear", min(available_years)))
        end_val = int(params.get("endYear", max(available_years)))
        start_val = max(min(available_years), min(max(available_years), start_val))
        end_val = max(min(available_years), min(max(available_years), end_val))
    except: start_val, end_val = min(available_years), max(available_years)
    year_range = st.select_slider("Year Range", options=available_years, value=(start_val, end_val))
else:
    st.info("Database loading...")
    year_range = (1786, 1934)

st.query_params.update({"name": name_input, "occupation": occ_input, "address": addr_input, "startYear": year_range[0], "endYear": year_range[1]})

# --- DATA PROCESSING ---
conn = get_db_connection()
sql = "SELECT last_name, first_name, occupation, business_address, home_address, year, publisher, printed_page FROM directory WHERE year BETWEEN ? AND ?"
sql_params = [year_range[0], year_range[1]]

if name_input:
    sql += " AND (last_name || ' ' || first_name || ' ' || first_name || ' ' || last_name) LIKE ? COLLATE NOCASE"
    sql_params.append(f"%{name_input}%")
if occ_input:
    sql += " AND occupation LIKE ? COLLATE NOCASE"
    sql_params.append(f"%{occ_input}%")
if addr_input:
    sql += " AND (business_address || ' ' || home_address) LIKE ? COLLATE NOCASE"
    sql_params.append(f"%{addr_input}%")

df = pd.read_sql(sql + " LIMIT 50000", conn, params=sql_params)
conn.close()

if not df.empty:
    if quality_toggle:
        df = df[df.apply(is_likely_human_readable, axis=1)]

    # 1. CONSOLIDATE COLUMNS
    df['Name'] = df['first_name'].fillna('') + " " + df['last_name'].fillna('')
    df['Address'] = df['home_address'].fillna('')
    mask = (df['Address'] == '') | (df['Address'].isna())
    df.loc[mask, 'Address'] = df['business_address'].fillna('')

    # 2. GENERATE SORT KEYS
    df[['_street', '_num']] = df['Address'].apply(lambda x: pd.Series(parse_address_for_sorting(x)))
    df['_pg_sort'] = df['printed_page'].apply(parse_page_for_sorting)
    df['_ln_sort'] = df['last_name'].apply(lambda x: x.lower() if (x and str(x).strip() != "") else "~~~~")

    # 3. RESEARCH SORT HIERARCHY
    # Year > Street > House Number > Page > Last Name
    df = df.sort_values(by=['year', '_street', '_num', '_pg_sort', '_ln_sort'])

    # 4. REORDER & CLEAN COLUMNS
    final_df = df[['Name', 'occupation', 'Address', 'business_address', 'year', 'publisher', 'printed_page']]
    final_df['year'] = final_df['year'].astype(str)

    # 5. DISPLAY
    st.write(f"### Records Found: {len(final_df)}")
    st.dataframe(final_df, use_container_width=True, hide_index=True, height=700)

    # 6. EXPORT
    csv = final_df.to_csv(index=False).encode('utf-8')
    st.download_button("💾 Download Ledger as CSV", csv, "nyc_research_export.csv", "text/csv")
else:
    st.info("No records found. Adjust your filters or disable the High-Quality View.")