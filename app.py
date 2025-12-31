import streamlit as st
import sqlite3
import pandas as pd
import re
import altair as alt

st.set_page_config(page_title="NYC History Archive", layout="wide")

# --- STYLING ---
st.markdown("""
    <style>
    .main { background-color: #fdfaf0; }
    h1 { color: #2c3e50; font-family: 'Georgia', serif; margin-top: -20px; }
    .stDataFrame { border: 2px solid #6d6d6d; }
    /* Top Navigation Bar Styling */
    div.row-widget.stRadio > div {
        flex-direction: row;
        justify-content: center;
        background-color: #e8e4d9;
        padding: 10px;
        border-radius: 10px;
        margin-bottom: 20px;
    }
    div.row-widget.stRadio label {
        background-color: #e8e4d9;
        padding: 5px 15px;
        border-radius: 5px;
        cursor: pointer;
    }
    .stMultiSelect div[data-baseweb="select"] > div:first-child {
        max-height: 120px;
        overflow-y: auto;
    }
    </style>
    """, unsafe_allow_html=True)

# --- NAVIGATION AT TOP ---
page = st.radio("Menu", ["Search Ledger", "Historical Analytics"], horizontal=True, label_visibility="collapsed")

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

available_years = get_valid_years(threshold=1000)

if not available_years:
    st.title("🏙️ NYC Historical Directory")
    st.warning("⚠️ No fully processed volumes found (Threshold: 1,000+ entries).")
    st.stop()

# --- PAGE 1: SEARCH LEDGER ---
if page == "Search Ledger":
    st.title("🏙️ NYC Historical Directory Explorer")
    
    params = st.query_params
    if "year_selector" not in st.session_state:
        st.session_state["year_selector"] = available_years

    # 1. Search Filters
    col1, col2, col3 = st.columns(3)
    with col1: n_q = st.text_input("Filter by Name", value=params.get("name", ""), placeholder="First or Last...")
    with col2: o_q = st.text_input("Filter by Occupation", value=params.get("occupation", ""), placeholder="Trade or job...")
    with col3: a_q = st.text_input("Filter by Address", value=params.get("address", ""), placeholder="Street or Number...")

    # 2. Year Selection (Always Expanded)
    st.write("### 📅 Select Years")
    c1, c2, _ = st.columns([1, 1, 6])
    if c1.button("Select All"): 
        st.session_state["year_selector"] = available_years
        st.rerun()
    if c2.button("Deselect All"): 
        st.session_state["year_selector"] = []
        st.rerun()
    
    final_years = st.multiselect("Include editions:", available_years, key="year_selector", label_visibility="collapsed")
    qual_tgl = st.checkbox("✨ High-Quality View Only", value=True)

    st.query_params.update({"name": n_q, "occupation": o_q, "address": a_q, "years": [str(y) for y in final_years]})

    if not final_years:
        st.info("Select years above to display the ledger.")
        st.stop()

    # 3. Data Processing
    conn = get_db_connection()
    where = [f"year IN ({','.join(['?']*len(final_years))})"]
    p = list(final_years)
    if qual_tgl: where.append("is_high_quality = 1")
    if n_q: 
        where.append("(last_name || ' ' || first_name || ' ' || first_name || ' ' || last_name) LIKE ? COLLATE NOCASE")
        p.append(f"%{n_q}%")
    if o_q: where.append("occupation LIKE ? COLLATE NOCASE"); p.append(f"%{o_q}%")
    if a_q: where.append("(business_address || ' ' || home_address) LIKE ? COLLATE NOCASE"); p.append(f"%{a_q}%")

    where_sql = " WHERE " + " AND ".join(where)

    # --- 📈 SEARCH DENSITY CHART ---
    st.write("### 📈 Search Result Density")
    chart_sql = f"SELECT year, COUNT(*) as count FROM directory {where_sql} GROUP BY year"
    chart_data_raw = pd.read_sql(chart_sql, conn, params=p)
    full_timeline = pd.DataFrame(available_years, columns=['year'])
    chart_df = full_timeline.merge(chart_data_raw, on='year', how='left').fillna(0)
    
    line_chart = alt.Chart(chart_df).mark_line(color="#2c3e50", strokeWidth=2.5, point=alt.OverlayMarkDef(color="#2c3e50", size=50)).encode(
        x=alt.X('year:O', title='Year', axis=alt.Axis(labelAngle=0, grid=True)),
        y=alt.Y('count:Q', title='Records', scale=alt.Scale(zero=False, padding=10), axis=alt.Axis(grid=True)),
        tooltip=['year', 'count']
    ).properties(height=180, width='container').configure_axis(gridColor="#EAEAEA", gridDash=[2, 2], domain=False).configure_view(strokeWidth=0)
    st.altair_chart(line_chart, use_container_width=True)

    # --- 📜 TABLE VIEW ---
    count_df = pd.read_sql(f"SELECT COUNT(*) as total FROM directory {where_sql}", conn, params=p)
    total_count = count_df['total'][0]
    
    sql_data = f"""
        SELECT year, first_name || ' ' || last_name as Name, occupation, 
               CASE WHEN home_address != '' THEN home_address ELSE business_address END as Address,
               business_address as 'Business Address', publisher, printed_page
        FROM directory {where_sql}
        ORDER BY year ASC, street_sort ASC, house_sort ASC, last_name ASC LIMIT 5000
    """
    df = pd.read_sql(sql_data, conn, params=p)
    conn.close()

    st.write(f"### Records Found: {total_count:,}")
    if not df.empty:
        df['year'] = df['year'].astype(str)
        st.dataframe(df, use_container_width=True, hide_index=True, height=500)

# --- PAGE 2: ANALYTICS ---
elif page == "Historical Analytics":
    st.title("📈 Historical Analytics & Trends")
    conn = get_db_connection()

    # SECTION 1: Total Volume
    st.write("### 📏 Total Database Volume")
    growth_df = pd.read_sql("SELECT year, COUNT(*) as Count FROM directory GROUP BY year ORDER BY year", conn)
    st.altair_chart(alt.Chart(growth_df).mark_area(line={'color':'#2c3e50'}, color=alt.Gradient(gradient='linear', stops=[alt.GradientStop(color='white', offset=0), alt.GradientStop(color='#2c3e50', offset=1)], x1=1, x2=1, y1=1, y2=0)).encode(x='year:O', y='Count:Q', tooltip=['year', 'Count']).properties(height=150), use_container_width=True)

    # SECTION 2: OCCUPATIONS (Cleaned aggregation to prevent double bars)
    st.write("---")
    col1, col2 = st.columns(2)
    with col1:
        st.write("### 🎩 Top Occupations (Excl. Widow)")
        occ_year = st.selectbox("Select Year", available_years)
        # Use TRIM and UPPER to merge similar entries in DB
        occ_df = pd.read_sql("""
            SELECT UPPER(TRIM(occupation)) as Trade, COUNT(*) as Count 
            FROM directory 
            WHERE year = ? AND occupation != '' AND occupation NOT LIKE '%widow%' AND is_high_quality = 1 
            GROUP BY Trade ORDER BY Count DESC LIMIT 15
        """, conn, params=(occ_year,))
        # Use aggregate='sum' in Altair for 100% safety
        st.altair_chart(alt.Chart(occ_df).mark_bar(color="#8e44ad").encode(
            x=alt.X('sum(Count):Q', title="Total Count"), 
            y=alt.Y('Trade:N', sort='-x', title="Profession"), 
            tooltip=['Trade', 'sum(Count)']
        ).properties(height=400), use_container_width=True)

    with col2:
        st.write("### 🏆 #1 Top Job Evolution")
        occ_evo_sql = """
            WITH Ranked AS (
                SELECT year, UPPER(TRIM(occupation)) as Trade, COUNT(*) as Count, 
                RANK() OVER (PARTITION BY year ORDER BY COUNT(*) DESC) as rnk 
                FROM directory 
                WHERE occupation != '' AND occupation NOT LIKE '%widow%' AND is_high_quality = 1 
                GROUP BY year, Trade
            ) SELECT year, Trade, Count FROM Ranked WHERE rnk = 1 ORDER BY year
        """
        occ_evo_df = pd.read_sql(occ_evo_sql, conn)
        occ_line = alt.Chart(occ_evo_df).mark_line(color="#8e44ad", strokeWidth=3).encode(x='year:O', y=alt.Y('Count:Q', scale=alt.Scale(zero=False)))
        st.altair_chart(occ_line + occ_line.mark_text(align='left', dx=5, dy=-5).encode(text='Trade:N'), use_container_width=True)

    # SECTION 3: STREETS (Cleaned aggregation to prevent double bars)
    st.write("---")
    col_a, col_b = st.columns(2)
    with col_a:
        st.write("### 🏙️ Busiest Streets")
        street_year = st.selectbox("Select Year", available_years, key="s_y")
        street_df = pd.read_sql("""
            SELECT UPPER(TRIM(street_sort)) as Street, COUNT(*) as Count 
            FROM directory 
            WHERE year = ? AND street_sort != 'zzzzz' 
            GROUP BY Street ORDER BY Count DESC LIMIT 15
        """, conn, params=(street_year,))
        st.altair_chart(alt.Chart(street_df).mark_bar(color="#27ae60").encode(
            x=alt.X('sum(Count):Q', title="Residents"), 
            y=alt.Y('Street:N', sort='-x'), 
            tooltip=['Street', 'sum(Count)']
        ).properties(height=400), use_container_width=True)

    with col_b:
        st.write("### 🏆 #1 Busiest Street Evolution")
        evo_sql = """
            WITH Ranked AS (
                SELECT year, UPPER(TRIM(street_sort)) as Street, COUNT(*) as Count, 
                RANK() OVER (PARTITION BY year ORDER BY COUNT(*) DESC) as rnk 
                FROM directory 
                WHERE street_sort != 'zzzzz' 
                GROUP BY year, Street
            ) SELECT year, Street, Count FROM Ranked WHERE rnk = 1 ORDER BY year
        """
        evo_df = pd.read_sql(evo_sql, conn)
        evo_line = alt.Chart(evo_df).mark_line(color="#c0392b", strokeWidth=3).encode(x='year:O', y=alt.Y('Count:Q', scale=alt.Scale(zero=False)))
        st.altair_chart(evo_line + evo_line.mark_text(align='left', dx=5, dy=-5).encode(text='Street:N'), use_container_width=True)

    # SECTION 4: Trade Geography
    st.write("---")
    st.write("### 🧭 Trade Mapping (Geographic Hubs)")
    c1, c2 = st.columns(2)
    with c1: trade_q = st.text_input("Enter Profession to Map", "Merchant")
    with c2: map_year = st.selectbox("Select Year", available_years, key="m_y")
    map_df = pd.read_sql("""
        SELECT UPPER(TRIM(street_sort)) as Street, COUNT(*) as Count 
        FROM directory 
        WHERE year = ? AND occupation LIKE ? AND street_sort != 'zzzzz' 
        GROUP BY Street ORDER BY Count DESC LIMIT 15
    """, conn, params=(map_year, f"%{trade_q}%"))
    if not map_df.empty:
        st.altair_chart(alt.Chart(map_df).mark_bar(color="#e67e22").encode(
            y=alt.Y('Street:N', sort='-x'), 
            x=alt.X('sum(Count):Q'), 
            tooltip=['Street', 'sum(Count)']
        ).properties(height=400), use_container_width=True)
    
    conn.close()