import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO
import time

# --- 1. GLOBAL UI CONFIGURATION ---
st.set_page_config(
    page_title="AssetTrack Pro | Inventory Management",
    page_icon="🛡️",
    layout="wide"
)

# --- 2. ADVANCED FRONTEND STYLING (CSS) ---
def apply_ui_theme():
    st.markdown("""
        <style>
        .stApp { background: #fdfdfd; }
        section[data-testid="stSidebar"] { background-color: #111827; color: white; }
        div[data-testid="stMetric"] {
            background-color: #ffffff;
            border: 1px solid #e5e7eb;
            padding: 15px;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }
        .dashboard-title { font-size: 36px; font-weight: 800; color: #1e293b; margin-bottom: 20px; }
        </style>
    """, unsafe_allow_html=True)

# --- 3. DATA ENGINE ---
class StockDataEngine:
    @staticmethod
    def map_status(val):
        """Advanced mapping based on the specific statuses provided by user"""
        val = str(val).lower().strip()
        
        # 1. STOLEN / ROBBED
        if any(word in val for word in ['robbed', 'stolen', 'robbed']):
            return 'Stolen'
        
        # 2. DAMAGED / FAULTY / ISSUES
        if any(word in val for word in [
            'faulty', 'damaged', 'broken', 'issue', 'malfunctioning', 
            'cracked', 'basement', 'switch on', 'lcd', 'motherboard', 
            'windows 11', 'fault'
        ]):
            return 'Damaged'
        
        # 3. IN STOCK / WAITING
        if any(word in val for word in ['onboarding', 'waiting', 'stock']):
            return 'In Stock'
        
        # 4. IN USE / WORKING
        if any(word in val for word in ['use', 'works', 'office']):
            return 'In Use'
            
        return 'Uncategorized'

    @staticmethod
    def load_excel(file):
        try:
            xl = pd.ExcelFile(file)
            combined_data = []
            for sheet in xl.sheet_names:
                df = pd.read_excel(file, sheet_name=sheet)
                df['Category_Sheet'] = sheet
                combined_data.append(df)
            
            final_df = pd.concat(combined_data, ignore_index=True)
            
            # --- FIX: Rename Duplicate Columns to prevent DuplicateError ---
            cols = pd.Series([str(c).strip().title() for c in final_df.columns])
            for dup in cols[cols.duplicated()].unique(): 
                cols[cols[cols == dup].index] = [f"{dup}_{i}" if i != 0 else dup for i in range(len(cols[cols == dup]))]
            final_df.columns = cols
            
            # Find the Status Column regardless of exact naming
            status_col = next((c for c in final_df.columns if 'Status' in c), None)
            brand_col = next((c for c in final_df.columns if 'Brand' in c or 'Make' in c), None)

            if status_col:
                final_df['Status_Original'] = final_df[status_col].fillna('Unknown')
                final_df['Dashboard_Status'] = final_df[status_col].apply(StockDataEngine.map_status)
            else:
                st.error("No column containing 'Status' found in Excel.")
                return None

            if brand_col:
                final_df['Brand_Clean'] = final_df[brand_col].fillna('Generic').astype(str).str.title()
            else:
                final_df['Brand_Clean'] = 'Unknown Brand'
                
            return final_df
        except Exception as e:
            st.error(f"Critical Data Error: {str(e)}")
            return None

# --- 4. FRONTEND VIEWS ---

def render_dashboard_tab(df):
    st.markdown("<h2 style='color:#334155;'>Operational Overview</h2>", unsafe_allow_html=True)
    
    # Metrics
    m1, m2, m3, m4, m5 = st.columns(5)
    stats = df['Dashboard_Status'].value_counts()
    
    m1.metric("Total Assets", len(df))
    m2.metric("In Use", stats.get("In Use", 0))
    m3.metric("In Stock", stats.get("In Stock", 0))
    m4.metric("Damaged", stats.get("Damaged", 0), delta_color="inverse")
    m5.metric("Stolen", stats.get("Stolen", 0), delta_color="inverse")

    st.markdown("---")
    
    # Charts
    v1, v2 = st.columns([2, 1])
    chart_colors = {'In Stock': '#10b981', 'In Use': '#3b82f6', 'Damaged': '#f59e0b', 'Stolen': '#ef4444', 'Uncategorized': '#94a3b8'}

    with v1:
        st.subheader("Inventory by Brand & Condition")
        fig = px.histogram(
            df, x="Brand_Clean", color="Dashboard_Status", 
            barmode="group", template="plotly_white", color_discrete_map=chart_colors
        )
        st.plotly_chart(fig, use_container_width=True)

    with v2:
        st.subheader("Status Breakdown")
        fig_pie = px.pie(
            df, names='Dashboard_Status', hole=0.6,
            color='Dashboard_Status', color_discrete_map=chart_colors
        )
        st.plotly_chart(fig_pie, use_container_width=True)

def render_inventory_tab(df):
    st.subheader("🗄️ Master Inventory List")
    search_col, filter_col = st.columns([3, 1])
    with search_col:
        query = st.text_input("Search anything (Brand, Status, Serial)...")
    with filter_col:
        sheet_filter = st.selectbox("Filter by Category", options=["All"] + list(df['Category_Sheet'].unique()))

    processed_df = df.copy()
    if query:
        processed_df = processed_df[processed_df.apply(lambda row: query.lower() in row.astype(str).str.lower().values, axis=1)]
    if sheet_filter != "All":
        processed_df = processed_df[processed_df['Category_Sheet'] == sheet_filter]

    st.dataframe(processed_df, use_container_width=True, height=500)
    
    csv = processed_df.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download Filtered CSV", csv, "inventory_report.csv", "text/csv")

# --- 5. MAIN APP CONTROLLER ---

def main():
    apply_ui_theme()
    with st.sidebar:
        st.markdown("<h1 style='color:white;'>AssetTrack Pro</h1>", unsafe_allow_html=True)
        uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx"])
        st.markdown("---")
        st.caption("v3.0.0 - Resolved Duplicate Name Error")

    if uploaded_file:
        df = StockDataEngine.load_excel(uploaded_file)
        if df is not None:
            tab1, tab2 = st.tabs(["📊 Analytics Dashboard", "📋 Full Inventory"])
            with tab1: render_dashboard_tab(df)
            with tab2: render_inventory_tab(df)
    else:
        st.markdown("<div class='dashboard-title'>Welcome to AssetTrack</div>", unsafe_allow_html=True)
        st.info("Please upload your Excel file in the sidebar to begin.")

if __name__ == "__main__":
    main()