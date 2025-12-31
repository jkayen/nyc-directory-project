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

# --- DATA QUALITY LOGIC ---
def is_likely_human_readable(row):
    """
    Gatekeeper: Returns False if any field contains noisy OCR artifacts.
    """
    b_addr = str(row['business_address']).strip()
    h_addr = str(row['home_address']).strip()
    fields = [str(row['last_name']), str(row['first_name']), str(row['occupation']), b_addr, h_addr]
    text_blob = " ".join(fields)

    # 1. NEW: Split House Number Filter (e.g., "5 1 Read" or "2 5 Duane")
    # This looks for: Start of string -> digit(s) -> space -> digit(s) -> space
    split_num_pattern = r'^\d+\s+\d+\s+'
    if re.search(split_num_pattern, b_addr) or re.search(split_num_pattern, h_addr):
        return False

    # 2. STRICT SYMBOL CHECK
    # Allowed: Alphabets, Numbers, Spaces, Periods, Commas, Apostrophes
    illegal_char_pattern = r"[^a-zA-Z0-9\s.,']"
    if re.search(illegal_char_pattern, text_blob):
        return False

    # 3. VOWEL CHECK (Gibberish Filter)
    words = text_blob.lower().split()
    for w in words:
        if len(w) > 4 and w.isalpha():
            if not any(v in w for v in 'aeiouy'):
                return False
    
    return True

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
    except:
        return []

def parse_address_for_sorting(addr):
    """Separates house number for natural sort. Blanks go to bottom."""
    if not addr or pd.isna(addr) or str(addr).strip() == "":
        return "~~~~", 999999
    s = re.sub(r'^\s*r\.\s*|^\s*rear\s*', '', str(addr), flags=re.IGNORECASE).strip()
    num_match = re.match(r'^(\d+)', s)
    house_num = int(num_match.group(1)) if num_match else 0
    street_name = re.sub(r'^\d+\s*', '', s).strip().lower()
    if not street_name: street_name = "~~~~"
    return street_name, house_num

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

# Data Quality Toggle
quality_toggle = st.checkbox("✨ High-Quality View (Hides rows with split numbers, symbols, or gibberish)", value=True)

available_years = get_available_years()
if available_years:
    try:
        start_val = int(params.get("startYear", min(available_years)))
        end_val = int(params.get("endYear", max(available_years)))
        start_val = max(min(available_years), min(max(available_years), start_val))
        end_val = max(min(available_years), min(max(available_years), end_val))
    except:
        start_val, end_val = min(available_years), max(available_years)

    year_range = st.select_slider("Year Range", options=available_years, value=(start_val, end_val))
else:
    st.info("Database loading...")
    year_range = (1786, 1934)

# Update URL Bar
st.query_params.update({"name": name_input, "occupation": occ_input, "address": addr_input, "startYear": year_range[0], "endYear": year_range[1]})

# --- DATA PROCESSING ---
conn = get_db_connection()
# Fetching slightly more to ensure quality filter has enough results to show
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
    # 1. APPLY QUALITY FILTER
    if quality_toggle:
        df = df[df.apply(is_likely_human_readable, axis=1)]

    # 2. CONSOLIDATE COLUMNS
    df['Name'] = df['first_name'].fillna('') + " " + df['last_name'].fillna('')
    df['Address'] = df['home_address'].fillna('')
    mask = (df['Address'] == '') | (df['Address'].isna())
    df.loc[mask, 'Address'] = df['business_address'].fillna('')

    # 3. GENERATE SORT KEYS (Blanks to bottom)
    df[['_street', '_num']] = df['Address'].apply(lambda x: pd.Series(parse_address_for_sorting(x)))
    df['_ln_sort'] = df['last_name'].apply(lambda x: x.lower() if (x and str(x).strip() != "") else "~~~~")

    # 4. SORT HIERARCHY: Year > Street > Number > Last Name
    df = df.sort_values(by=['year', '_street', '_num', '_ln_sort'])

    # 5. REORDER & CLEAN COLUMNS
    final_df = df[['Name', 'occupation', 'Address', 'business_address', 'year', 'publisher', 'printed_page']]
    final_df['year'] = final_df['year'].astype(str)

    # 6. DISPLAY
    st.write(f"### Records Found: {len(final_df)}")
    st.dataframe(final_df, use_container_width=True, hide_index=True, height=700)

    # 7. EXPORT
    csv = final_df.to_csv(index=False).encode('utf-8')
    st.download_button("💾 Download as CSV (Excel)", csv, "nyc_research_export.csv", "text/csv")
else:
    st.info("No records found. Try adjusting filters or disabling the High-Quality View.")