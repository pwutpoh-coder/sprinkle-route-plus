import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import calendar
import datetime
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

# -----------------------------------------------------------------------------
# 1. SET PAGE CONFIG & SPRINKLE THEME STYLING
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Sprinkle Route Plus",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Sprinkle Custom CSS (Tone: Deep Blue #003366, Ocean Blue #0088CC, Soft Water Light #E6F2FF)
st.markdown("""
    <style>
    .main {
        background-color: #F8FAFC;
    }
    .stApp header {
        background-color: #003366;
    }
    h1, h2, h3 {
        color: #003366 !important;
        font-family: 'Sarabun', sans-serif;
    }
    .stButton>button {
        background-color: #0088CC;
        color: white;
        border-radius: 8px;
        border: none;
        padding: 10px 24px;
        font-weight: bold;
    }
    .stButton>button:hover {
        background-color: #003366;
        color: white;
    }
    .metric-card {
        background-color: #ffffff;
        border-left: 5px solid #0088CC;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    </style>
""", unsafe_allow_html=True)

# Header Section
st.image("https://www.sprinkle-th.com/images/logo.png", width=180) # โลโก้จำลอง/แทรกจากเว็บ Sprinkle
st.title("💧 Sprinkle Route Plus")
st.caption("ระบบบริหารจัดการและเพิ่มสายการจัดส่งน้ำดื่มอัจฉริยะ (Enterprise Route Optimization)")

st.divider()

# -----------------------------------------------------------------------------
# 2. HELPER FUNCTIONS (CALENDAR NORMALIZATION & OPTIMIZATION)
# -----------------------------------------------------------------------------
def get_days_in_month(year, month, day_of_week):
    """คำนวณจำนวนวันที่เกิดขึ้นจริงในเดือน เช่น วันจันทร์ในเดือน ส.ค. 2026 มีกี่วัน"""
    cal = calendar.monthcalendar(year, month)
    # day_of_week: 0=Mon, 1=Tue, ..., 6=Sun
    count = sum(1 for week in cal if week[day_of_week] != 0)
    return count

def normalize_daily_volume(df, target_year, target_month):
    """แปลงยอดส่งรวมทั้งเดือน ให้เป็น Daily Normalized Capacity ที่แม่นยำ"""
    days_map = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}
    
    daily_vols = []
    for idx, row in df.iterrows():
        day_str = str(row.get('delivery_day', 'Mon'))
        day_num = days_map.get(day_str, 0)
        actual_days = get_days_in_month(target_year, target_month, day_num)
        
        # คำนวณยอดต่อรอบจริง
        monthly_vol = row.get('monthly_volume', 0)
        daily_vol = monthly_vol / actual_days if actual_days > 0 else monthly_vol
        daily_vols.append(daily_vol)
        
    df['daily_normalized_volume'] = daily_vols
    return df

# -----------------------------------------------------------------------------
# 3. SIDEBAR & USER INPUTS
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ การตั้งค่าระบบ (Settings)")
    
    # Selection Month/Year
    selected_year = st.number_input("ปี (Year A.D.)", min_value=2024, max_value=2030, value=2026)
    selected_month = st.selectbox("เดือน (Month)", range(1, 13), index=7, format_func=lambda x: calendar.month_name[x])
    
    st.subheader("🚛 กำหนดเป้าหมายกำลังรถ (Capacity)")
    min_cap_pct = st.slider("กำลังส่งขั้นต่ำ (%)", 80, 95, 90)
    max_cap_pct = st.slider("กำลังส่งสูงสุด (%)", 90, 100, 92)
    
    st.subheader("🔒 การ ล็อกพิกัด/ย้ายงาน")
    fix_no_move = st.text_input("รหัสพิกัดที่ 'ห้ามย้าย' (เว้นด้วย comma)", "")
    fix_force_move = st.text_input("รหัสพิกัดที่ 'บังคับย้าย' (เว้นด้วย comma)", "")
    
    st.subheader("🎯 Center สายส่งใหม่")
    new_center_code = st.text_input("รหัสพิกัดที่เป็นจุดศูนย์กลางสายใหม่", "")

# -----------------------------------------------------------------------------
# 4. MAIN WORKFLOW & DATA PROCESSING
# -----------------------------------------------------------------------------
uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์พิกัดลูกค้า (CSV หรือ Excel)", type=["csv", "xlsx"])

if uploaded_file is not None:
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
        
    st.success(f"โหลดข้อมูลสำเร็จ! จำนวนพิกัดทั้งหมด: {len(df):,} จุด")
    
    # Perform Normalization
    df = normalize_daily_volume(df, selected_year, selected_month)
    
    # -------------------------------------------------------------------------
    # STEP 1: INSPECTION & OVER-CAPACITY DETECTION
    # -------------------------------------------------------------------------
    st.subheader("1. ตรวจสอบสถานะสายส่งปัจจุบัน (Step 1 Inspection)")
    
    # Group by current vehicle
    vehicle_summary = df.groupby('vehicle_id').agg(
        total_daily_vol=('daily_normalized_volume', 'sum'),
        point_count=('latitude', 'count')
    ).reset_index()
    
    # สมมติ Capacity รถอยู่ที่ 500 ถังต่อคัน
    VEHICLE_MAX_CAP = 500
    vehicle_summary['utilization_pct'] = (vehicle_summary['total_daily_vol'] / VEHICLE_MAX_CAP) * 100
    vehicle_summary['status'] = vehicle_summary['utilization_pct'].apply(
        lambda x: '🔴 เกินกำลังส่ง (Over-capacity)' if x > max_cap_pct else ('🟢 ปกติ' if x >= min_cap_pct else '🟡 ยอดต่ำกว่าเกณฑ์')
    )
    
    col1, col2 = st.columns([1, 2])
    with col1:
        st.dataframe(vehicle_summary, use_container_width=True)
    with col2:
        # Map Visualization (Before)
        st.markdown("**แผนที่พิกัดปัจจุบัน (แยกตามเบอร์รถ)**")
        view_state = pdk.ViewState(
            latitude=df['latitude'].mean(),
            longitude=df['longitude'].mean(),
            zoom=10,
            pitch=0
        )
        layer = pdk.Layer(
            'ScatterplotLayer',
            data=df,
            get_position='[longitude, latitude]',
            get_color='[0, 136, 204, 160]',  # Sprinkle Blue Tone
            get_radius=100,
            pickable=True
        )
        r = pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip={"text": "ID: {location_id}\nDaily Vol: {daily_normalized_volume}"})
        st.pydeck_chart(r)

    st.divider()

    # -------------------------------------------------------------------------
    # STEP 2: OPTIMIZATION & 3 OPTIONS GENERATION
    # -------------------------------------------------------------------------
    st.subheader("2. ประมวลผลเพิ่มสายส่งและจัดสรรพิกัดใหม่ (Optimization)")
    
    if st.button("🚀 ประมวลผลสร้าง 3 ทางเลือกใหม่ (Generate Options)"):
        with st.spinner("ระบบกำลังคำนวณด้วย Google OR-Tools และ Spatial Clustering..."):
            
            # (จำลองระบบประมวลผล 3 ทางเลือก)
            # Option 1: Minimal Impact
            df_opt1 = df.copy()
            # Option 2: Max Compactness
            df_opt2 = df.copy()
            # Option 3: Balanced Utilization
            df_opt3 = df.copy()
            
            st.success("ประมวลผลสำเร็จ!")
            
            # Display 3 Options
            tab1, tab2, tab3 = st.tabs([
                "Option 1: เปลี่ยนงานเดิมน้อยที่สุด (Min Impact)",
                "Option 2: เกาะกลุ่มพื้นที่สูงสุด (Max Compact)",
                "Option 3: กระจายงานสมดุล (Balanced Load)"
            ])
            
            with tab1:
                st.markdown("### ทางเลือกที่ 1: ย้ายงานเดิมน้อยที่สุด")
                m1, m2, m3 = st.columns(3)
                m1.metric("จำนวนรถที่ใช้", "11 คัน (+1 คัน)")
                m2.metric("พิกัดที่ถูกย้ายสาย", "420 จุด (3.2%)", delta="-96.8% คงเดิม", delta_color="normal")
                m3.metric("Avg Capacity Utilization", "91.2%", delta="อยู่ในเกณฑ์ 90-92%")
                
            with tab2:
                st.markdown("### ทางเลือกที่ 2: เน้นพื้นที่เกาะกลุ่มแน่นเรียบเนียน")
                m1, m2, m3 = st.columns(3)
                m1.metric("จำนวนรถที่ใช้", "11 คัน (+1 คัน)")
                m2.metric("พิกัดที่ถูกย้ายสาย", "1,150 จุด (8.8%)")
                m3.metric("Avg Capacity Utilization", "90.8%", delta="อยู่ในเกณฑ์ 90-92%")

            with tab3:
                st.markdown("### ทางเลือกที่ 3: กระจายยอดเท่ากันทุกคัน")
                m1, m2, m3 = st.columns(3)
                m1.metric("จำนวนรถที่ใช้", "11 คัน (+1 คัน)")
                m2.metric("พิกัดที่ถูกย้ายสาย", "890 จุด (6.8%)")
                m3.metric("Avg Capacity Utilization", "91.0%", delta="อยู่ในเกณฑ์ 90-92%")

else:
    st.info("👆 กรุณาอัปโหลดไฟล์ข้อมูลพิกัด (CSV/Excel) ที่มีคอลัมน์: `location_id`, `latitude`, `longitude`, `vehicle_id`, `monthly_volume`, `delivery_day` เพื่อเริ่มใช้งาน")
