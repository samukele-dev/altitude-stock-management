import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import threading
import sqlite3
from datetime import datetime
import hashlib
import os
import time

# --- 1. GLOBAL UI CONFIGURATION ---
st.set_page_config(
    page_title="Altitude BPO Asset Tracker | Inventory Management",
    page_icon="🛡️",
    layout="wide"
)

# --- 2. DATABASE SETUP ---
def init_database():
    """Initialize SQLite database and create tables if they don't exist"""
    conn = sqlite3.connect('inventory.db', check_same_thread=False)
    c = conn.cursor()
    
    # Create inventory table
    c.execute('''CREATE TABLE IF NOT EXISTS inventory
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  asset_id TEXT UNIQUE,
                  brand TEXT,
                  model TEXT,
                  serial_number TEXT,
                  status TEXT,
                  location TEXT,
                  notes TEXT,
                  date_added TIMESTAMP,
                  last_updated TIMESTAMP,
                  category_sheet TEXT)''')
    
    # Create audit log table
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  action TEXT,
                  asset_id TEXT,
                  changes TEXT,
                  timestamp TIMESTAMP,
                  user TEXT)''')
    
    conn.commit()
    conn.close()


# --- 3. DATABASE OPERATIONS ---
class DatabaseManager:
    _lock = threading.Lock()  # Add a thread lock
    _connection = None  # Single connection instance
    
    @staticmethod
    def get_connection():
        """Get or create a single database connection"""
        if DatabaseManager._connection is None:
            DatabaseManager._connection = sqlite3.connect('inventory.db', check_same_thread=False)
        return DatabaseManager._connection
    
    @staticmethod
    def close_connection():
        """Close the database connection"""
        if DatabaseManager._connection:
            DatabaseManager._connection.close()
            DatabaseManager._connection = None
    
    @staticmethod
    def load_data():
        """Load all data from database"""
        with DatabaseManager._lock:  # Use lock for thread safety
            conn = DatabaseManager.get_connection()
            df = pd.read_sql_query("SELECT * FROM inventory ORDER BY brand, asset_id", conn)
            return df
    
    @staticmethod
    def add_asset(asset_data):
        """Add new asset to database"""
        with DatabaseManager._lock:  # Use lock for thread safety
            conn = DatabaseManager.get_connection()
            c = conn.cursor()
            
            # Generate unique asset ID if not provided
            if not asset_data.get('asset_id'):
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                # Create a more reliable unique ID using timestamp and hash
                unique_string = f"{timestamp}{asset_data['brand']}{asset_data.get('serial_number', '')}"
                asset_data['asset_id'] = f"AST-{timestamp}-{hashlib.md5(unique_string.encode()).hexdigest()[:6]}"
            
            try:
                c.execute('''INSERT INTO inventory 
                             (asset_id, brand, model, serial_number, status, location, notes, date_added, last_updated, category_sheet)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                          (asset_data['asset_id'],
                           asset_data['brand'],
                           asset_data['model'],
                           asset_data['serial_number'],
                           asset_data['status'],
                           asset_data['location'],
                           asset_data['notes'],
                           datetime.now(),
                           datetime.now(),
                           asset_data.get('category_sheet', 'General')))
                
                # Log the action
                c.execute('''INSERT INTO audit_log (action, asset_id, timestamp, user)
                             VALUES (?, ?, ?, ?)''',
                          ('ADD', asset_data['asset_id'], datetime.now(), 'admin'))
                
                conn.commit()
                return asset_data['asset_id']
                
            except sqlite3.IntegrityError as e:
                if "UNIQUE constraint failed" in str(e):
                    # If asset_id already exists, generate a new one with retry
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')  # Add microseconds
                    unique_string = f"{timestamp}{asset_data['brand']}{asset_data.get('serial_number', '')}{hashlib.md5(str(datetime.now()).encode()).hexdigest()[:4]}"
                    asset_data['asset_id'] = f"AST-{timestamp}-{hashlib.md5(unique_string.encode()).hexdigest()[:6]}"
                    
                    # Retry the insert
                    c.execute('''INSERT INTO inventory 
                                 (asset_id, brand, model, serial_number, status, location, notes, date_added, last_updated, category_sheet)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                              (asset_data['asset_id'],
                               asset_data['brand'],
                               asset_data['model'],
                               asset_data['serial_number'],
                               asset_data['status'],
                               asset_data['location'],
                               asset_data['notes'],
                               datetime.now(),
                               datetime.now(),
                               asset_data.get('category_sheet', 'General')))
                    
                    c.execute('''INSERT INTO audit_log (action, asset_id, timestamp, user)
                                 VALUES (?, ?, ?, ?)''',
                              ('ADD', asset_data['asset_id'], datetime.now(), 'admin'))
                    
                    conn.commit()
                    return asset_data['asset_id']
                else:
                    raise e
    
    @staticmethod
    def update_asset(asset_id, updates):
        """Update existing asset"""
        with DatabaseManager._lock:  # Use lock for thread safety
            conn = DatabaseManager.get_connection()
            c = conn.cursor()
            
            update_fields = []
            values = []
            for key, value in updates.items():
                if value is not None:
                    update_fields.append(f"{key} = ?")
                    values.append(value)
            
            values.append(datetime.now())  # last_updated
            values.append(asset_id)
            
            query = f"UPDATE inventory SET {', '.join(update_fields)}, last_updated = ? WHERE asset_id = ?"
            c.execute(query, values)
            
            # Log the action
            c.execute('''INSERT INTO audit_log (action, asset_id, changes, timestamp, user)
                         VALUES (?, ?, ?, ?, ?)''',
                      ('UPDATE', asset_id, str(updates), datetime.now(), 'admin'))
            
            conn.commit()
    
    @staticmethod
    def delete_asset(asset_id):
        """Delete asset from database"""
        with DatabaseManager._lock:  # Use lock for thread safety
            conn = DatabaseManager.get_connection()
            c = conn.cursor()
            
            # Log before deleting
            c.execute('''INSERT INTO audit_log (action, asset_id, timestamp, user)
                         VALUES (?, ?, ?, ?)''',
                      ('DELETE', asset_id, datetime.now(), 'admin'))
            
            c.execute("DELETE FROM inventory WHERE asset_id = ?", (asset_id,))
            conn.commit()
    
    @staticmethod
    def bulk_import_from_excel(file):
        """Import data from Excel file with preview and confirmation"""
        try:
            xl = pd.ExcelFile(file)
            
            # Preview data first
            st.markdown("### 📋 Import Preview")
            
            total_rows = 0
            sheet_details = []
            
            for sheet in xl.sheet_names:
                df = pd.read_excel(file, sheet_name=sheet)
                total_rows += len(df)
                sheet_details.append((sheet, len(df)))
                
                # Show preview for each sheet
                with st.expander(f"📄 {sheet} - {len(df)} rows"):
                    st.dataframe(df.head(), width='stretch')
                    
                    # Show column mapping
                    st.markdown("**Column Mapping:**")
                    cols = [str(col).strip().lower() for col in df.columns]
                    status_cols = [c for c in cols if 'status' in c]
                    model_cols = [c for c in cols if any(k in c for k in ['model', 'make', 'product'])]
                    serial_cols = [c for c in cols if any(k in c for k in ['serial', 'sn', 'id'])]
                    
                    st.markdown(f"- Status column: {status_cols[0] if status_cols else 'Not found (will use Unknown)'}")
                    st.markdown(f"- Model column: {model_cols[0] if model_cols else 'Not found (will use Unknown)'}")
                    st.markdown(f"- Serial column: {serial_cols[0] if serial_cols else 'Not found (will be empty)'}")
            
            st.markdown(f"**Total rows to import:** {total_rows}")
            st.markdown("**Sheet breakdown:**")
            for sheet, count in sheet_details:
                st.markdown(f"- {sheet}: {count} rows")
            
            # Use columns with regular buttons (not in a form)
            col1, col2 = st.columns(2)
            with col1:
                confirm_clicked = st.button("✅ Confirm Import", type="primary", key="confirm_import")
            with col2:
                cancel_clicked = st.button("❌ Cancel", key="cancel_import")
            
            if confirm_clicked:
                return DatabaseManager.perform_actual_import(xl)
            
            if cancel_clicked:
                st.session_state.show_import = False
                st.rerun()
            
            return 0
            
        except Exception as e:
            st.error(f"Preview error: {str(e)}")
            return 0

    @staticmethod
    def perform_actual_import(xl):
        """Perform the actual import after confirmation"""
        assets_added = 0
        assets_skipped = 0
        
        # Create progress containers
        progress_bar = st.progress(0)
        status_text = st.empty()
        stats_text = st.empty()
        
        total_sheets = len(xl.sheet_names)
        total_rows_processed = 0
        total_rows = sum(len(pd.read_excel(xl, sheet_name=sheet)) for sheet in xl.sheet_names)
        
        for sheet_idx, sheet in enumerate(xl.sheet_names):
            df = pd.read_excel(xl, sheet_name=sheet)
            
            # Clean column names
            df.columns = [str(col).strip().lower() for col in df.columns]
            
            # Find columns
            status_col = next((col for col in df.columns if 'status' in col), None)
            model_col = next((col for col in df.columns if any(k in col for k in ['model', 'make', 'product', 'item'])), None)
            serial_col = next((col for col in df.columns if any(k in col for k in ['serial', 'sn', 'id', 'asset'])), None)
            location_col = next((col for col in df.columns if any(k in col for k in ['location', 'place', 'site', 'office'])), None)
            
            for idx, row in df.iterrows():
                try:
                    status_text.text(f"📄 Importing: {sheet} - Row {idx + 1} of {len(df)}")
                    
                    # Get values with proper handling
                    model_value = str(row[model_col]) if model_col and pd.notna(row[model_col]) else 'Unknown'
                    serial_value = str(row[serial_col]) if serial_col and pd.notna(row[serial_col]) else ''
                    status_value = str(row[status_col]) if status_col and pd.notna(row[status_col]) else 'Unknown'
                    location_value = str(row[location_col]) if location_col and pd.notna(row[location_col]) else 'Unknown'
                    
                    asset_data = {
                        'brand': sheet.strip().title(),
                        'model': model_value,
                        'serial_number': serial_value,
                        'status': status_value,
                        'location': location_value,
                        'notes': f"Imported from {sheet} on {datetime.now().strftime('%Y-%m-%d')}",
                        'category_sheet': sheet
                    }
                    
                    DatabaseManager.add_asset(asset_data)
                    assets_added += 1
                    
                except Exception as e:
                    assets_skipped += 1
                    st.warning(f"⚠️ Skipped {sheet} row {idx + 1}: {str(e)[:100]}")
                
                # Update progress
                total_rows_processed += 1
                progress = total_rows_processed / total_rows if total_rows > 0 else 0
                progress_bar.progress(min(progress, 1.0))
                stats_text.text(f"✅ Added: {assets_added} | ⚠️ Skipped: {assets_skipped}")
        
        status_text.text("")
        stats_text.text("")
        st.success(f"✅ Import complete! Added: {assets_added}, Skipped: {assets_skipped}")
        return assets_added


# --- 4. DATA ENGINE ---
class StockDataEngine:
    @staticmethod
    def map_status(val):
        """Advanced mapping based on the specific statuses provided by user"""
        val = str(val).lower().strip()
        
        # 1. STOLEN / ROBBED
        if any(word in val for word in ['robbed', 'stolen']):
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

# --- 5. UI COMPONENTS ---
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
        .edit-button {
            background-color: #3b82f6;
            color: white;
            padding: 5px 10px;
            border-radius: 5px;
            text-decoration: none;
        }
        .delete-button {
            background-color: #ef4444;
            color: white;
            padding: 5px 10px;
            border-radius: 5px;
            text-decoration: none;
        }
        </style>
    """, unsafe_allow_html=True)

def render_dashboard_tab(df):
    st.markdown("<h2 style='color:#334155;'>Operational Overview</h2>", unsafe_allow_html=True)
    
    # Apply status mapping
    df['Dashboard_Status'] = df['status'].apply(StockDataEngine.map_status)
    
    # Metrics Row 1 - Overall Stats
    m1, m2, m3, m4, m5 = st.columns(5)
    stats = df['Dashboard_Status'].value_counts()
    
    m1.metric("Total Assets", len(df))
    m2.metric("In Use", stats.get("In Use", 0))
    m3.metric("In Stock", stats.get("In Stock", 0))
    m4.metric("Damaged", stats.get("Damaged", 0), delta_color="inverse")
    m5.metric("Stolen", stats.get("Stolen", 0), delta_color="inverse")

    st.markdown("---")
    
    # Brand Summary Section
    st.subheader("📊 Brand Performance Overview")
    
    # Calculate brand statistics
    brand_stats = df.groupby('brand').size().reset_index(name='Total Assets')
    brand_summary = brand_stats.set_index('brand')
    
    # Add status breakdown per brand
    status_breakdown = pd.crosstab(df['brand'], df['Dashboard_Status'])
    brand_summary = brand_summary.join(status_breakdown, how='left').fillna(0).astype(int)
    
    # Sort by total assets
    brand_summary = brand_summary.sort_values('Total Assets', ascending=False)
    
    # Modern Brand Display CSS
    st.markdown("""
    <style>
    .brand-card {
        background: white;
        border-radius: 12px;
        padding: 1.2rem;
        margin-bottom: 1rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        border: 1px solid #edf2f7;
        transition: all 0.2s ease;
    }
    .brand-card:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        border-color: #cbd5e0;
    }
    .brand-name {
        font-size: 1.1rem;
        font-weight: 600;
        color: #1e293b;
        margin-bottom: 0.8rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .brand-total {
        background: #f1f5f9;
        padding: 0.2rem 0.8rem;
        border-radius: 20px;
        font-size: 0.9rem;
        color: #475569;
    }
    .status-badge {
        display: inline-flex;
        align-items: center;
        padding: 0.3rem 0.8rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 500;
        margin-right: 0.5rem;
        margin-bottom: 0.5rem;
    }
    .status-instock { background: #e6f7ed; color: #0b5e42; }
    .status-inuse { background: #e6f0ff; color: #1e4b8c; }
    .status-damaged { background: #fff4e5; color: #9c4a0c; }
    .status-stolen { background: #fee9e7; color: #9b1c1c; }
    .progress-bar {
        width: 100%;
        height: 6px;
        background: #edf2f7;
        border-radius: 3px;
        margin: 0.8rem 0;
        display: flex;
        overflow: hidden;
    }
    .progress-segment {
        height: 100%;
        transition: width 0.3s ease;
    }
    </style>
    """, unsafe_allow_html=True)

    # Display all brands in a grid
    st.markdown("##### All Brands Overview")
    
    # Create a grid of brand cards (2 columns)
    cols = st.columns(2)
    for idx, (brand, data) in enumerate(brand_summary.iterrows()):
        with cols[idx % 2]:
            total = data['Total Assets']
            
            # Calculate percentages for progress bar
            pct_in_stock = (data.get('In Stock', 0) / total * 100) if total > 0 else 0
            pct_in_use = (data.get('In Use', 0) / total * 100) if total > 0 else 0
            pct_damaged = (data.get('Damaged', 0) / total * 100) if total > 0 else 0
            pct_stolen = (data.get('Stolen', 0) / total * 100) if total > 0 else 0
            
            # Calculate health score
            health_score = ((data.get('In Stock', 0) + data.get('In Use', 0)) / total * 100) if total > 0 else 0
            
            st.markdown(f"""
            <div class="brand-card">
                <div class="brand-name">
                    {brand}
                    <span class="brand-total">{total} assets</span>
                </div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                    <span style="font-size: 0.9rem; color: #64748b;">Health Score: {health_score:.1f}%</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-segment" style="width: {pct_in_stock}%; background: #10b981;" title="In Stock: {data.get('In Stock', 0)}"></div>
                    <div class="progress-segment" style="width: {pct_in_use}%; background: #3b82f6;" title="In Use: {data.get('In Use', 0)}"></div>
                    <div class="progress-segment" style="width: {pct_damaged}%; background: #f59e0b;" title="Damaged: {data.get('Damaged', 0)}"></div>
                    <div class="progress-segment" style="width: {pct_stolen}%; background: #ef4444;" title="Stolen: {data.get('Stolen', 0)}"></div>
                </div>
                <div>
                    <span class="status-badge status-instock">📦 {data.get('In Stock', 0)}</span>
                    <span class="status-badge status-inuse">💻 {data.get('In Use', 0)}</span>
                    <span class="status-badge status-damaged">⚠️ {data.get('Damaged', 0)}</span>
                    <span class="status-badge status-stolen">🚫 {data.get('Stolen', 0)}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")
    
    # Charts
    v1, v2 = st.columns([2, 1])
    chart_colors = {
        'In Stock': '#10b981', 
        'In Use': '#3b82f6', 
        'Damaged': '#f59e0b', 
        'Stolen': '#ef4444', 
        'Uncategorized': '#94a3b8'
    }

    with v1:
        st.subheader("Inventory Distribution by Brand")
        fig = px.histogram(
            df, 
            x="brand", 
            color="Dashboard_Status", 
            barmode="group", 
            template="plotly_white", 
            color_discrete_map=chart_colors,
            title="Asset Distribution by Brand and Status"
        )
        fig.update_layout(
            xaxis_tickangle=-45,
            xaxis_title="Brand",
            yaxis_title="Number of Assets",
            legend_title="Status",
            height=500
        )
        st.plotly_chart(fig, use_container_width=True)

    with v2:
        st.subheader("Status Distribution")
        status_counts = df['Dashboard_Status'].value_counts().reset_index()
        status_counts.columns = ['Status', 'Count']
        
        fig_pie = px.pie(
            status_counts, 
            values='Count', 
            names='Status', 
            hole=0.6,
            color='Status', 
            color_discrete_map=chart_colors,
            title="Current Status Distribution"
        )
        fig_pie.update_traces(
            textposition='inside', 
            textinfo='percent+label',
            hovertemplate='<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent}<extra></extra>'
        )
        fig_pie.update_layout(height=500)
        st.plotly_chart(fig_pie, use_container_width=True)

def render_inventory_tab(df):
    st.subheader("🗄️ Master Inventory List")
    
    # Action buttons
    col1, col2, col3, col4 = st.columns([1, 1, 1, 3])
    with col1:
        if st.button("➕ Add Asset", width='stretch'):
            st.session_state.show_add_form = True
    
    with col2:
        if st.button("📤 Import Excel", width='stretch'):
            st.session_state.show_import = True
    
    with col3:
        if st.button("📋 Audit Log", width='stretch'):
            st.session_state.show_audit = True
    
    # Add Asset Form
    if st.session_state.get('show_add_form', False):
        with st.form("add_asset_form"):
            st.markdown("##### Add New Asset")
            
            col1, col2 = st.columns(2)
            with col1:
                brand = st.text_input("Brand *")
                model = st.text_input("Model")
                serial = st.text_input("Serial Number")
            
            with col2:
                status = st.selectbox("Status *", ['In Stock', 'In Use', 'Damaged', 'Stolen', 'Other'])
                location = st.text_input("Location")
                category = st.text_input("Category/Sheet")
            
            notes = st.text_area("Notes")
            
            col1, col2 = st.columns(2)
            with col1:
                submitted = st.form_submit_button("✅ Save")
            with col2:
                if st.form_submit_button("❌ Cancel"):
                    st.session_state.show_add_form = False
                    st.rerun()
            
            if submitted:
                if brand and status:
                    asset_data = {
                        'brand': brand,
                        'model': model,
                        'serial_number': serial,
                        'status': status,
                        'location': location,
                        'notes': notes,
                        'category_sheet': category if category else 'General'
                    }
                    asset_id = DatabaseManager.add_asset(asset_data)
                    st.success(f"✅ Asset added successfully! ID: {asset_id}")
                    st.session_state.show_add_form = False
                    st.rerun()
                else:
                    st.error("Brand and Status are required!")
    
    # Import Excel Form 
    if st.session_state.get('show_import', False):
        st.markdown("##### 📤 Import from Excel")
        st.markdown("Upload your Excel file with multiple sheets. Each sheet name will become a brand.")
        
        uploaded_file = st.file_uploader("Choose Excel file", type=['xlsx', 'xls'], key="import_uploader")
        
        if uploaded_file is not None:
            assets_imported = DatabaseManager.bulk_import_from_excel(uploaded_file)
            if assets_imported > 0:
                st.success(f"✅ Successfully imported {assets_imported} assets!")
                st.session_state.show_import = False
                time.sleep(2)
                st.rerun()
    
    

    # Audit Log View
    if st.session_state.get('show_audit', False):
        st.markdown("##### 📋 Audit Log")
        conn = DatabaseManager.get_connection()
        audit_df = pd.read_sql_query("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 100", conn)
        conn.close()
        
        st.dataframe(audit_df, width='stretch')
        
        if st.button("Close Audit Log"):
            st.session_state.show_audit = False
            st.rerun()
        
        st.markdown("---")
    
    # Search and filter options
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        query = st.text_input("🔍 Search", placeholder="Search by any field...")
    with col2:
        status_options = ['All'] + sorted(df['status'].unique().tolist())
        status_filter = st.selectbox("Filter by Status", options=status_options)
    with col3:
        brand_options = ['All'] + sorted(df['brand'].unique().tolist())
        brand_filter = st.selectbox("Filter by Brand", options=brand_options)

    # Apply filters
    processed_df = df.copy()
    
    if query:
        mask = processed_df.astype(str).apply(lambda x: x.str.lower().str.contains(query.lower())).any(axis=1)
        processed_df = processed_df[mask]
    
    if status_filter != "All":
        processed_df = processed_df[processed_df['status'] == status_filter]
    
    if brand_filter != "All":
        processed_df = processed_df[processed_df['brand'] == brand_filter]

    # Display record count
    st.caption(f"Showing {len(processed_df)} of {len(df)} records")
    
    # Display records with expanders
    if not processed_df.empty:
        for idx, row in processed_df.iterrows():
            with st.expander(f"📦 {row.get('brand', 'Unknown')} - {row.get('model', 'No Model')} ({row.get('asset_id', 'No ID')})"):
                col1, col2, col3 = st.columns([2, 1, 1])
                
                with col1:
                    st.markdown(f"**Serial:** {row.get('serial_number', 'N/A')}")
                    st.markdown(f"**Status:** {row.get('status', 'N/A')}")
                    st.markdown(f"**Location:** {row.get('location', 'N/A')}")
                
                with col2:
                    if st.button(f"✏️ Edit", key=f"edit_{row['asset_id']}"):
                        st.session_state[f'editing_{row["asset_id"]}'] = True
                
                with col3:
                    if st.button(f"🗑️ Delete", key=f"delete_{row['asset_id']}"):
                        if st.session_state.get(f'confirm_delete_{row["asset_id"]}', False):
                            DatabaseManager.delete_asset(row['asset_id'])
                            st.success("Asset deleted!")
                            st.rerun()
                        else:
                            st.session_state[f'confirm_delete_{row["asset_id"]}'] = True
                            st.warning("Click again to confirm deletion")
                
                # Edit form
                if st.session_state.get(f'editing_{row["asset_id"]}', False):
                    with st.form(f"edit_form_{row['asset_id']}"):
                        st.markdown("##### Edit Asset")
                        
                        new_status = st.selectbox("Status", 
                                                 ['In Stock', 'In Use', 'Damaged', 'Stolen', 'Other'],
                                                 index=['In Stock', 'In Use', 'Damaged', 'Stolen', 'Other'].index(row['status']) if row['status'] in ['In Stock', 'In Use', 'Damaged', 'Stolen', 'Other'] else 0)
                        new_location = st.text_input("Location", value=row.get('location', ''))
                        new_notes = st.text_area("Notes", value=row.get('notes', ''))
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.form_submit_button("💾 Save Changes"):
                                updates = {
                                    'status': new_status,
                                    'location': new_location,
                                    'notes': new_notes
                                }
                                DatabaseManager.update_asset(row['asset_id'], updates)
                                st.success("Asset updated!")
                                st.session_state[f'editing_{row["asset_id"]}'] = False
                                st.rerun()
                        
                        with col2:
                            if st.form_submit_button("Cancel"):
                                st.session_state[f'editing_{row["asset_id"]}'] = False
                                st.rerun()


# --- 6. MAIN APP CONTROLLER ---
def main():
    # Initialize database
    init_database()
    
    apply_ui_theme()
    
    # Initialize session state
    if 'show_add_form' not in st.session_state:
        st.session_state.show_add_form = False
    if 'show_import' not in st.session_state:
        st.session_state.show_import = False
    if 'show_audit' not in st.session_state:
        st.session_state.show_audit = False
    
    # Sidebar
    with st.sidebar:
        st.markdown("<h1 style='color:white;'>Altitude BPO Asset Tracker</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color:#9ca3af;'>Inventory Management System</p>", unsafe_allow_html=True)
        
        # Database stats
        df = DatabaseManager.load_data()
        
        st.markdown("### 📊 Database Stats")
        st.markdown(f"**Total Assets:** {len(df)}")
        st.markdown(f"**Unique Brands:** {df['brand'].nunique() if not df.empty else 0}")
        st.markdown(f"**Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        st.markdown("---")
        
        # Export option
        if not df.empty:
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Export Database",
                csv,
                f"inventory_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "text/csv",
                width='stretch'
            )
        
        st.markdown("---")
        st.caption("v1.0.0")
        st.caption("© 2026 Altitude BPO developed by KWDS")

    # Main content
    df = DatabaseManager.load_data()
    
    if not df.empty:
        # Create tabs
        tab1, tab2 = st.tabs([
            "📊 Analytics Dashboard", 
            "📋 Inventory Management"
        ])
        
        with tab1:
            render_dashboard_tab(df)
        
        with tab2:
            render_inventory_tab(df)
    else:
        # Welcome screen with import option
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("<div class='dashboard-title' style='text-align: center;'>Welcome to Altitude BPO Asset Tracker</div>", unsafe_allow_html=True)
            
            st.markdown("""
            <div style='text-align: center; padding: 2rem; background: white; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>
                <h3>🚀 Get Started</h3>
                <p style='color: #4b5563;'>Your database is empty. Choose an option to begin:</p>
            </div>
            """, unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("➕ Add First Asset", width='stretch'):
                    st.session_state.show_add_form = True
            
            with col2:
                if st.button("📤 Import from Excel", width='stretch'):
                    st.session_state.show_import = True
            
            # Show add form if requested
            if st.session_state.show_add_form:
                with st.form("first_asset_form"):
                    st.markdown("##### Add Your First Asset")
                    
                    brand = st.text_input("Brand *")
                    model = st.text_input("Model")
                    serial = st.text_input("Serial Number")
                    status = st.selectbox("Status *", ['In Stock', 'In Use', 'Damaged', 'Stolen'])
                    location = st.text_input("Location")
                    
                    if st.form_submit_button("Add Asset"):
                        if brand and status:
                            asset_data = {
                                'brand': brand,
                                'model': model,
                                'serial_number': serial,
                                'status': status,
                                'location': location,
                                'notes': '',
                                'category_sheet': 'General'
                            }
                            asset_id = DatabaseManager.add_asset(asset_data)
                            st.success(f"✅ Asset added! ID: {asset_id}")
                            st.session_state.show_add_form = False
                            st.rerun()
                        else:
                            st.error("Brand and Status are required!")
            
            # Show import form if requested
            if st.session_state.show_import:
                with st.form("first_import_form"):
                    st.markdown("##### Import from Excel")
                    uploaded_file = st.file_uploader("Choose Excel file", type=['xlsx', 'xls'])
                    
                    if st.form_submit_button("Import Data"):
                        if uploaded_file:
                            with st.spinner("Importing data..."):
                                assets_added = DatabaseManager.bulk_import_from_excel(uploaded_file)
                                st.success(f"✅ Successfully imported {assets_added} assets!")
                                st.session_state.show_import = False
                                st.rerun()

if __name__ == "__main__":
    main()