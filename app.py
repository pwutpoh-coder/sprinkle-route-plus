import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import calendar
import io

st.set_page_config(
    page_title="Sprinkle Route Plus",
    page_icon="💧",
    layout="wide"
)

st.title("💧 Sprinkle Route Plus")
st.caption("ระบบบริหารจัดการและตัดเพิ่มสายส่งน้ำดื่มอัจฉริยะ (Production Multi-User Cloud)")

# Sidebar Control
st.sidebar.header("⚙️ ตั้งค่าข้อมูล")
uploaded_file = st.sidebar.file_uploader("อัปโหลดไฟล์ Excel / CSV", type=["xlsx", "csv"])

target_year = st.sidebar.number_input("ปี ค.ศ.", min_value=2024, max_value=2030, value=2026)
target_month = st.sidebar.selectbox("เดือน", range(1, 13), format_func=lambda x: calendar.month_name[x], index=7)

def get_day_count(year, month, day_name):
    cal = calendar.monthcalendar(year, month)
    days = {'จันทร์': 0, 'อังคาร': 1, 'พุธ': 2, 'พฤหัสบดี': 3, 'ศุกร์': 4, 'เสาร์': 5, 'อาทิตย์': 6}
    target_idx = days.get(day_name, 0)
    cnt = sum(1 for week in cal if week[target_idx] != 0)
    return cnt if cnt > 0 else 4

def process_data(df, year, month):
    # 1. แปลงค่า ยอดส่ง/เดือน ให้เป็นตัวเลขเสมอกัน (ถ้าเจอข้อความหรือค่าว่างจะเปลี่ยนเป็น 0 อัตโนมัติ ป้องกัน Error)
    if 'ยอดส่ง/เดือน' in df.columns:
        df['ยอดส่ง/เดือน'] = pd.to_numeric(df['ยอดส่ง/เดือน'], errors='coerce').fillna(0)
    else:
        df['ยอดส่ง/เดือน'] = 0

    # 2. แปลงพิกัด Lat/Long
    if 'พิกัด Lat/Long' in df.columns:
        def parse_lat(x):
            try:
                return float(str(x).split(',')[0].strip()) if pd.notnull(x) and ',' in str(x) else 13.7563
            except:
                return 13.7563

        def parse_long(x):
            try:
                return float(str(x).split(',')[1].strip()) if pd.notnull(x) and ',' in str(x) else 100.5018
            except:
                return 100.5018

        df['Lat'] = df['พิกัด Lat/Long'].apply(parse_lat)
        df['Long'] = df['พิกัด Lat/Long'].apply(parse_long)
    else:
        df['Lat'] = 13.7563
        df['Long'] = 100.5018
        
    # 3. คำนวณยอดส่งต่อวันตามจำนวนวันจริงในปฏิทิน
    def calc_daily_vol(row):
        day_str = str(row.get('รอบส่งประจำสัปดาห์', 'จันทร์')).strip()
        cnt = get_day_count(year, month, day_str)
        monthly_vol = float(row.get('ยอดส่ง/เดือน', 0))
        return round(monthly_vol / cnt, 2) if cnt > 0 else round(monthly_vol / 4, 2)
        
    df['กำลังบรรทุกต่อวัน(ถัง)'] = df.apply(calc_daily_vol, axis=1)
    return df

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file)
        else:
            df_raw = pd.read_excel(uploaded_file)
            
        df = process_data(df_raw, target_year, target_month)
        
        tab1, tab2, tab3 = st.tabs(["📊 ตรวจสอบสายส่งและเลือกเบอร์รถ", "⚡ จัดสายส่งใหม่ (3 ทางเลือก)", "📥 สรุปและ Export ข้อมูล"])
        
        with tab1:
            st.subheader("📌 สรุปกำลังส่งแยกตามเบอร์รถ")
            
            veh_summary = df.groupby('เบอร์รถ').agg(
                จำนวนจุดส่ง=('รหัสสมาชิก', 'count'),
                ยอดรวมเดือน=('ยอดส่ง/เดือน', 'sum'),
                ยอดบรรทุกต่อวัน=('กำลังบรรทุกต่อวัน(ถัง)', 'sum')
            ).reset_index()
            
            max_cap = st.number_input("กำหนดกำลังบรรทุกสูงสุดของรถต่อวัน (ถัง)", value=200)
            veh_summary['สถานะ'] = veh_summary['ยอดบรรทุกต่อวัน'].apply(lambda x: '⚠️ เกินกำลังบรรทุก' if x > max_cap else '✅ ปกติ')
            
            st.dataframe(veh_summary, use_container_width=True)
            
            selected_car = st.selectbox("🔍 เลือกเบอร์รถเพื่อกรองดูตารางพิกัด:", ['ทั้งหมด'] + list(df['เบอร์รถ'].unique()))
            
            filtered_df = df if selected_car == 'ทั้งหมด' else df[df['เบอร์รถ'] == selected_car]
            
            st.subheader("🗺️ แผนที่พิกัดจุดส่ง")
            view_state = pdk.ViewState(latitude=filtered_df['Lat'].mean(), longitude=filtered_df['Long'].mean(), zoom=11)
            layer = pdk.Layer(
                "ScatterplotLayer",
                filtered_df,
                get_position=["Long", "Lat"],
                get_color="[0, 102, 204, 180]",
                get_radius=120,
                pickable=True
            )
            st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip={"text": "{ชื่อ-นามสกุล}\n{ที่อยู่จัดส่ง บ้านเลขที่/อาคาร}\nถัง/วัน: {กำลังบรรทุกต่อวัน(ถัง)}"}))
            
            st.subheader("📋 ตารางข้อมูลพิกัดงานตามเบอร์รถที่เลือก")
            st.dataframe(filtered_df, use_container_width=True)
            
        with tab2:
            st.subheader("⚙️ เงื่อนไขการจัดสายส่งใหม่")
            col1, col2 = st.columns(2)
            with col1:
                fix_no = st.multiselect("🔒 รหัสสมาชิกที่ไม่ยอมให้ย้าย (Fix Stay)", df['รหัสสมาชิก'].unique())
            with col2:
                fix_move = st.multiselect("🚚 รหัสสมาชิกที่บังคับย้ายไปคันใหม่", df['รหัสสมาชิก'].unique())
                
            if st.button("🚀 ประมวลผลเพิ่มสายส่งใหม่ (Generate 3 Options)"):
                st.success("ประมวลผลสำเร็จ!")
                
                df_opt1 = df.copy()
                over_cars = veh_summary[veh_summary['ยอดบรรทุกต่อวัน'] > max_cap]['เบอร์รถ'].tolist()
                mask = (df_opt1['เบอร์รถ'].isin(over_cars)) & (~df_opt1['รหัสสมาชิก'].isin(fix_no))
                cut_idx = df_opt1[mask].sample(frac=0.15, random_state=42).index if any(mask) else []
                df_opt1.loc[cut_idx, 'เบอร์รถ'] = 'NEW-CAR-11'
                
                st.write("### ทางเลือกที่ 1: ย้ายงานเดิมน้อยที่สุด (Min Change)")
                c1, c2 = st.columns(2)
                with c1:
                    st.caption("แผนที่ก่อนจัดสาย (Before)")
                    st.pydeck_chart(pdk.Deck(layers=[pdk.Layer("ScatterplotLayer", df, get_position=["Long", "Lat"], get_color="[200, 30, 30, 160]", get_radius=100)], initial_view_state=view_state))
                with c2:
                    st.caption("แผนที่หลังจัดสายใหม่ (After)")
                    st.pydeck_chart(pdk.Deck(layers=[pdk.Layer("ScatterplotLayer", df_opt1, get_position=["Long", "Lat"], get_color="[0, 200, 100, 160]", get_radius=100)], initial_view_state=view_state))
                    
                st.session_state['processed_df'] = df_opt1

        with tab3:
            st.subheader("📥 Export และบันทึกข้อมูล")
            export_df = st.session_state.get('processed_df', df)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                export_df.to_excel(writer, index=False, sheet_name='Sprinkle_Plan')
            
            st.download_button(
                label="🟢 ดาวน์โหลดไฟล์ Excel (Sprinkle Route Plan)",
                data=output.getvalue(),
                file_name=f'Sprinkle_Route_Plan_{target_year}_{target_month}.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการประมวลผลข้อมูล: {e}")
else:
    st.info("กรุณาอัปโหลดไฟล์ข้อมูลที่แถบด้านซ้ายมือเพื่อเริ่มใช้งานระบบ")
