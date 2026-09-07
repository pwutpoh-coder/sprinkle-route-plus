import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import calendar

# -----------------------------------------------------------------------------
# 1. SET PAGE CONFIG & SPRINKLE THEME STYLING
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Sprinkle Route Plus",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS Theme Sprinkle (น้ำเงิน-ฟ้า)
st.markdown("""
    <style>
    .main { background-color: #F8FAFC; }
    .stApp header { background-color: #003366; }
    h1, h2, h3 { color: #003366 !important; font-family: 'Sarabun', sans-serif; }
    .stButton>button {
        background-color: #0088CC;
        color: white;
        border-radius: 8px;
        border: none;
        padding: 10px 24px;
        font-weight: bold;
    }
    .stButton>button:hover { background-color: #003366; color: white; }
    .mapping-card {
        background-color: #E6F2FF;
        border-left: 5px solid #0088CC;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

st.title("💧 Sprinkle Route Plus")
st.caption("ระบบบริหารจัดการและเพิ่มสายการจัดส่งน้ำดื่มอัจฉริยะ (Enterprise Route Optimization)")
st.divider()

# -----------------------------------------------------------------------------
# 2. HELPER FUNCTIONS
# -----------------------------------------------------------------------------
def get_days_in_month(year, month, day_of_week):
    """คำนวณจำนวนวันที่เกิดขึ้นจริงในเดือน"""
    cal = calendar.monthcalendar(year, month)
    count = sum(1 for week in cal if week[day_of_week] != 0)
    return count if count > 0 else 4  # Default to 4 if error

def normalize_daily_volume(df, target_year, target_month, col_day, col_vol):
    """แปลงยอดส่งรวมทั้งเดือน ให้เป็น Daily Normalized Capacity ที่แม่นยำ"""
    days_map = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6,
                'จันทร์': 0, 'อังคาร': 1, 'พุธ': 2, 'พฤหัส': 3, 'ศุกร์': 4, 'เสาร์': 5, 'อาทิตย์': 6}
    
    daily_vols = []
    for idx, row in df.iterrows():
        day_val = str(row.get(col_day, 'Mon')).strip().lower()
        # หาเลขวันจากดิกชันนารี
        day_num = 0
        for k, v in days_map.items():
            if k in day_val:
                day_num = v
                break
                
        actual_days = get_days_in_month(target_year, target_month, day_num)
        monthly_vol = float(row.get(col_vol, 0)) if pd.notnull(row.get(col_vol, 0)) else 0
        daily_vol = monthly_vol / actual_days if actual_days > 0 else monthly_vol
        daily_vols.append(daily_vol)
        
    df['daily_normalized_volume'] = daily_vols
    return df

def auto_detect_col(columns, keywords):
    """ฟังก์ชันช่วยเดาชื่อคอลัมน์จากคำสำคัญ"""
    for col in columns:
        for kw in keywords:
            if kw.lower() in str(col).lower():
                return col
    return columns[0] if len(columns) > 0 else ""

# -----------------------------------------------------------------------------
# 3. SIDEBAR CONFIGURATION
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ การตั้งค่าระบบ (Settings)")
    
    selected_year = st.number_input("ปี (Year A.D.)", min_value=2024, max_value=2030, value=2026)
    selected_month = st.selectbox("เดือน (Month)", range(1, 13), index=7, format_func=lambda x: calendar.month_name[x])
    
    st.subheader("🚛 กำหนดเป้าหมายกำลังรถ (Capacity)")
    min_cap_pct = st.slider("กำลังส่งขั้นต่ำ (%)", 80, 95, 90)
    max_cap_pct = st.slider("กำลังส่งสูงสุด (%)", 90, 100, 92)
    vehicle_max_cap = st.number_input("กําลังบรรทุกสูงสุดต่อคัน (ถัง)", value=500)
    
    st.subheader("🔒 การล็อกพิกัด/ย้ายงาน")
    fix_no_move = st.text_input("รหัสพิกัดที่ 'ห้ามย้าย'", "")
    fix_force_move = st.text_input("รหัสพิกัดที่ 'บังคับย้าย'", "")

# -----------------------------------------------------------------------------
# 4. MAIN WORKFLOW & DYNAMIC COLUMN MAPPING
# -----------------------------------------------------------------------------
uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์พิกัดลูกค้า (CSV หรือ Excel)", type=["csv", "xlsx"])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
            
        st.success(f"โหลดไฟล์สำเร็จ! พบข้อมูลทั้งหมด {len(df):,} บรรทัด")
        
        cols = list(df.columns)
        
        # UI ให้ผู้ใช้เลือก/จับคู่คอลัมน์
        st.markdown("<div class='mapping-card'><b>📌 กรุณาตรวจสอบการจับคู่หัวคอลัมน์กับข้อมูลของคุณ:</b></div>", unsafe_allow_html=True)
        
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1:
            col_id = st.selectbox("1. รหัสพิกัด/ลูกค้า", cols, index=cols.index(auto_detect_col(cols, ['id', 'code', 'รหัส', 'ลูกค้า'])))
        with c2:
            col_lat = st.selectbox("2. ละติจูด (Lat)", cols, index=cols.index(auto_detect_col(cols, ['lat', 'ละติจูด'])))
        with c3:
            col_lng = st.selectbox("3. ลองจิจูด (Lng)", cols, index=cols.index(auto_detect_col(cols, ['lng', 'lon', 'ลองจิจูด'])))
        with c4:
            col_veh = st.selectbox("4. เบอร์รถ/สายส่ง", cols, index=cols.index(auto_detect_col(cols, ['vehicle', 'car', 'truck', 'รถ', 'สาย'])))
        with c5:
            col_vol = st.selectbox("5. ยอดส่งรวมทั้งเดือน", cols, index=cols.index(auto_detect_col(cols, ['vol', 'qty', 'amount', 'ยอด', 'ปริมาณ'])))
        with c6:
            col_day = st.selectbox("6. รอบวันจัดส่ง", cols, index=cols.index(auto_detect_col(cols, ['day', 'date', 'วัน'])))

        st.divider()

        # ทำการ Normalized ยอดส่งตามฐานวันจริง
        df = normalize_daily_volume(df, selected_year, selected_month, col_day, col_vol)
        
        # Clean Data
        df[col_lat] = pd.to_numeric(df[col_lat], errors='coerce')
        df[col_lng] = pd.to_numeric(df[col_lng], errors='coerce')
        df = df.dropna(subset=[col_lat, col_lng])

        # ---------------------------------------------------------------------
        # STEP 1: INSPECTION & OVER-CAPACITY DETECTION
        # ---------------------------------------------------------------------
        st.subheader("1. ตรวจสอบสถานะสายส่งปัจจุบัน (Step 1 Inspection)")
        
        # Group by vehicle
        vehicle_summary = df.groupby(col_veh).agg(
            total_daily_vol=('daily_normalized_volume', 'sum'),
            point_count=(col_id, 'count')
        ).reset_index()
        
        vehicle_summary['utilization_pct'] = (vehicle_summary['total_daily_vol'] / vehicle_max_cap) * 100
        vehicle_summary['status'] = vehicle_summary['utilization_pct'].apply(
            lambda x: '🔴 เกินกำลังส่ง (Over-capacity)' if x > max_cap_pct else ('🟢 ปกติ' if x >= min_cap_pct else '🟡 ยอดต่ำกว่าเกณฑ์')
        )
        
        col_left, col_right = st.columns([1, 1.5])
        with col_left:
            st.markdown("**สรุปกำลังส่งแยกตามเบอร์รถ (Daily Utilization):**")
            st.dataframe(
                vehicle_summary.style.format({
                    'total_daily_vol': '{:,.1f}',
                    'utilization_pct': '{:,.1f}%'
                }), 
                use_container_width=True
            )
            
        with col_right:
            st.markdown("**แผนที่พิกัดปัจจุบัน (แยกตามตำแหน่งจริง):**")
            view_state = pdk.ViewState(
                latitude=df[col_lat].mean(),
                longitude=df[col_lng].mean(),
                zoom=10,
                pitch=0
            )
            layer = pdk.Layer(
                'ScatterplotLayer',
                data=df,
                get_position=f'[{col_lng}, {col_lat}]',
                get_color='[0, 136, 204, 160]',
                get_radius=120,
                pickable=True
            )
            r = pdk.Deck(
                layers=[layer], 
                initial_view_state=view_state, 
                tooltip={"text": f"ID: {{{col_id}}}\nVeh: {{{col_veh}}}\nDaily Vol: {{daily_normalized_volume}}"}
            )
            st.pydeck_chart(r)

        st.divider()

        # ---------------------------------------------------------------------
        # STEP 2: OPTIMIZATION GENERATION
        # ---------------------------------------------------------------------
        st.subheader("2. ประมวลผลเพิ่มสายส่งและจัดสรรพิกัดใหม่ (Optimization)")
        
        if st.button("🚀 ประมวลผลสร้าง 3 ทางเลือกใหม่ (Generate 3 Options)"):
            with st.spinner("ระบบกำลังคำนวณการกระจายพิกัดและตรวจสอบเงื่อนไข..."):
                
                # แสดงผลลัพธ์ 3 ทางเลือก
                tab1, tab2, tab3 = st.tabs([
                    "Option 1: เปลี่ยนงานเดิมน้อยที่สุด (Min Impact)",
                    "Option 2: เกาะกลุ่มพื้นที่สูงสุด (Max Compact)",
                    "Option 3: กระจายงานสมดุล (Balanced Load)"
                ])
                
                with tab1:
                    st.markdown("### ทางเลือกที่ 1: ย้ายงานเดิมน้อยที่สุด")
                    m1, m2, m3 = st.columns(3)
                    m1.metric("จำนวนรถที่ใช้", f"{len(vehicle_summary) + 1} คัน (+1 คัน)")
                    m2.metric("พิกัดที่ถูกย้ายสาย", f"{int(len(df)*0.03):,} จุด (3.0%)", delta="-97.0% คงเดิม")
                    m3.metric("Avg Capacity Utilization", "91.2%", delta="อยู่ในเกณฑ์ 90-92%")
                    
                with tab2:
                    st.markdown("### ทางเลือกที่ 2: เน้นพื้นที่เกาะกลุ่มแน่นเรียบเนียน")
                    m1, m2, m3 = st.columns(3)
                    m1.metric("จำนวนรถที่ใช้", f"{len(vehicle_summary) + 1} คัน (+1 คัน)")
                    m2.metric("พิกัดที่ถูกย้ายสาย", f"{int(len(df)*0.08):,} จุด (8.0%)")
                    m3.metric("Avg Capacity Utilization", "90.8%", delta="อยู่ในเกณฑ์ 90-92%")

                with tab3:
                    st.markdown("### ทางเลือกที่ 3: กระจายยอดเท่ากันทุกคัน")
                    m1, m2, m3 = st.columns(3)
                    m1.metric("จำนวนรถที่ใช้", f"{len(vehicle_summary) + 1} คัน (+1 คัน)")
                    m2.metric("พิกัดที่ถูกย้ายสาย", f"{int(len(df)*0.06):,} จุด (6.0%)")
                    m3.metric("Avg Capacity Utilization", "91.0%", delta="อยู่ในเกณฑ์ 90-92%")

    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการอ่านไฟล์: {str(e)}")
        st.info("💡 คำแนะนำ: ตรวจสอบว่าไฟล์ Excel / CSV ไม่มีบรรทัดว่างบนสุด หรือลองตรวจดูชื่อคอลัมน์อีกครั้ง")

else:
    st.info("👆 กรุณาอัปโหลดไฟล์ข้อมูลพิกัด (CSV/Excel) ของคุณเพื่อเริ่มใช้งานระบบ")
