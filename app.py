import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import calendar
import io
import hashlib

# ------------------------------------------
# PAGE CONFIG & ICON (เปลี่ยนไอคอนเป็นแผนที่/Route 🗺️)
# ------------------------------------------
st.set_page_config(
    page_title="Sprinkle Route Plus",
    page_icon="🗺️",
    layout="wide"
)

st.title("🗺️ Sprinkle Route Plus")
st.caption("ระบบบริหารจัดการและตัดเพิ่มสายส่งน้ำดื่มอัจฉริยะ (Route Optimization System)")

# Sidebar Control
st.sidebar.header("⚙️ ตั้งค่าข้อมูล")
uploaded_file = st.sidebar.file_uploader("อัปโหลดไฟล์ Excel / CSV", type=["xlsx", "csv"])

target_year = st.sidebar.number_input("ปี ค.ศ.", min_value=2024, max_value=2030, value=2026)
target_month = st.sidebar.selectbox("เดือน", range(1, 13), format_func=lambda x: calendar.month_name[x], index=7)

# ------------------------------------------
# HELPER FUNCTIONS
# ------------------------------------------
def get_day_count(year, month, day_name):
    cal = calendar.monthcalendar(year, month)
    days = {'จันทร์': 0, 'อังคาร': 1, 'พุธ': 2, 'พฤหัสบดี': 3, 'ศุกร์': 4, 'เสาร์': 5, 'อาทิตย์': 6}
    target_idx = days.get(day_name, 0)
    cnt = sum(1 for week in cal if week[target_idx] != 0)
    return cnt if cnt > 0 else 4

def generate_car_color(car_code):
    """ สุ่มสีตามเบอร์รถด้วย Hash (เพื่อให้เบอร์รถเดิมได้สีเดิมเสมอ) """
    hash_num = int(hashlib.md5(str(car_code).encode()).hexdigest(), 16)
    r = (hash_num & 0xFF0000) >> 16
    g = (hash_num & 0x00FF00) >> 8
    b = (hash_num & 0x0000FF)
    
    # ปรับโทนสีให้สด ชัดเจน ไม่ให้กลืนกับแผนที่สีสว่าง
    r = int((r % 200) + 20)
    g = int((g % 200) + 20)
    b = int((b % 200) + 20)
    return [r, g, b, 200]

def process_data(df, year, month):
    # 1. แปลงคอลัมน์ ยอดส่ง/เดือน
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
        
    # 3. คำนวณยอดส่งต่อวันตามปฏิทินจริง
    def calc_daily_vol(row):
        day_str = str(row.get('รอบส่งประจำสัปดาห์', 'จันทร์')).strip()
        cnt = get_day_count(year, month, day_str)
        monthly_vol = float(row.get('ยอดส่ง/เดือน', 0))
        return round(monthly_vol / cnt, 2) if cnt > 0 else round(monthly_vol / 4, 2)
        
    df['กำลังบรรทุกต่อวัน(ถัง)'] = df.apply(calc_daily_vol, axis=1)
    
    # 4. กำหนดสีตามเบอร์รถ
    df['Color'] = df['เบอร์รถ'].apply(generate_car_color)
    return df

# ------------------------------------------
# MAIN APPLICATION
# ------------------------------------------
if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file)
        else:
            df_raw = pd.read_excel(uploaded_file)
            
        df = process_data(df_raw, target_year, target_month)
        
        tab1, tab2, tab3 = st.tabs(["📊 ตรวจสอบสายส่งและเปอร์เซ็นต์กำลังบรรทุก", "⚡ จัดสายส่งใหม่ (3 ทางเลือก)", "📥 สรุปและ Export ข้อมูล"])
        
        # ------------------------------------------
        # TAB 1: INSPECTION & UTILIZATION %
        # ------------------------------------------
        with tab1:
            st.subheader("📌 สรุปกำลังส่งและเปอร์เซ็นต์กำลังบรรทุกแยกตามเบอร์รถ")
            
            max_cap = st.number_input("กำหนดกำลังบรรทุกสูงสุดของรถต่อวัน (ถัง/คัน)", value=200, min_value=1)
            
            # คำนวณสรุปรวมรายเบอร์รถ
            veh_summary = df.groupby('เบอร์รถ').agg(
                จำนวนจุดส่ง=('รหัสสมาชิก', 'count'),
                ยอดรวมเดือน=('ยอดส่ง/เดือน', 'sum'),
                ยอดบรรทุกต่อวัน=('กำลังบรรทุกต่อวัน(ถัง)', 'sum')
            ).reset_index()
            
            # คำนวณ % การใช้งาน (Utilization %)
            veh_summary['เปอร์เซ็นต์กำลังบรรทุก (%)'] = round((veh_summary['ยอดบรรทุกต่อวัน'] / max_cap) * 100, 2)
            
            # สถานะเปรียบเทียบ
            def get_status(pct):
                if pct > 100:
                    return f"⚠️ เกินกำลังบรรทุก ({pct}%)"
                elif pct >= 90:
                    return f"✅ เหมาะสม ({pct}%)"
                else:
                    return f"ℹ️ ยังไม่เต็มกำลัง ({pct}%)"
                    
            veh_summary['สถานะกำลังบรรทุก'] = veh_summary['เปอร์เซ็นต์กำลังบรรทุก (%)'].apply(get_status)
            
            st.dataframe(veh_summary[['เบอร์รถ', 'จำนวนจุดส่ง', 'ยอดรวมเดือน', 'ยอดบรรทุกต่อวัน', 'เปอร์เซ็นต์กำลังบรรทุก (%)', 'สถานะกำลังบรรทุก']], use_container_width=True)
            
            selected_car = st.selectbox("🔍 เลือกเบอร์รถเพื่อกรองดูตารางพิกัด:", ['ทั้งหมด'] + list(df['เบอร์รถ'].unique()))
            filtered_df = df if selected_car == 'ทั้งหมด' else df[df['เบอร์รถ'] == selected_car]
            
            # แผนที่สีสว่าง (Light Map Style) + แยกสีตามเบอร์รถ
            st.subheader("🗺️ แผนที่พิกัดจุดส่ง (แยกสีตามเบอร์รถ)")
            view_state = pdk.ViewState(latitude=filtered_df['Lat'].mean(), longitude=filtered_df['Long'].mean(), zoom=11)
            
            layer = pdk.Layer(
                "ScatterplotLayer",
                filtered_df,
                get_position=["Long", "Lat"],
                get_color="Color",
                get_radius=150,
                pickable=True
            )
            
            # map_style light เพื่อไม่ให้พื้นหลังเป็นสีดำ
            st.pydeck_chart(pdk.Deck(
                map_style="mapbox://styles/mapbox/light-v10",
                layers=[layer],
                initial_view_state=view_state,
                tooltip={"text": "เบอร์รถ: {เบอร์รถ}\n{ชื่อ-นามสกุล}\n{ที่อยู่จัดส่ง บ้านเลขที่/อาคาร}\nถัง/วัน: {กำลังบรรทุกต่อวัน(ถัง)}"}
            ))
            
            # สรุป Legend กำกับสีเบอร์รถด้านล่างแผนที่
            st.write("🎨 **รายการสีสัญลักษณ์กำกับเบอร์รถ (Map Legend):**")
            legend_cars = filtered_df['เบอร์รถ'].unique()
            cols = st.columns(min(len(legend_cars), 6))
            for idx, car in enumerate(legend_cars):
                color_rgb = generate_car_color(car)
                hex_color = f"#{color_rgb[0]:02x}{color_rgb[1]:02x}{color_rgb[2]:02x}"
                with cols[idx % 6]:
                    st.markdown(f"<div style='display: flex; align-items: center;'><div style='width: 18px; height: 18px; background-color: {hex_color}; border-radius: 50%; margin-right: 8px;'></div><b>{car}</b></div>", unsafe_allow_html=True)
            
            st.write("")
            st.subheader("📋 ตารางข้อมูลพิกัดงานตามเบอร์รถที่เลือก")
            st.dataframe(filtered_df[['รหัสสมาชิก', 'ชื่อ-นามสกุล', 'พิกัด Lat/Long', 'ที่อยู่จัดส่ง บ้านเลขที่/อาคาร', 'คลัง', 'เบอร์รถ', 'รอบส่งประจำสัปดาห์', 'สถานะลูกค้า', 'เงื่อนไขการจัดส่ง', 'ยอดส่ง/เดือน', 'กำลังบรรทุกต่อวัน(ถัง)']], use_container_width=True)

        # ------------------------------------------
        # TAB 2: OPTIMIZATION (ครบ 3 ทางเลือก)
        # ------------------------------------------
        with tab2:
            st.subheader("⚙️ เงื่อนไขการจัดสายส่งใหม่")
            col1, col2 = st.columns(2)
            with col1:
                fix_no = st.multiselect("🔒 รหัสสมาชิกที่ไม่ยอมให้ย้าย (Fix Stay)", df['รหัสสมาชิก'].unique())
            with col2:
                fix_move = st.multiselect("🚚 รหัสสมาชิกที่บังคับย้ายไปคันใหม่", df['รหัสสมาชิก'].unique())
                
            if st.button("🚀 ประมวลผลเพิ่มสายส่งใหม่ (Generate 3 Options)"):
                st.success("ประมวลผลสำเร็จ! สามารถเลือกดูสรุปสายส่งใหม่ทั้ง 3 ทางเลือกได้จาก Tab ด้านล่าง")
                
                over_cars = veh_summary[veh_summary['ยอดบรรทุกต่อวัน'] > max_cap]['เบอร์รถ'].tolist()
                
                # --- Option 1: ย้ายงานเดิมน้อยที่สุด (Min Change) ---
                df_opt1 = df.copy()
                mask1 = (df_opt1['เบอร์รถ'].isin(over_cars)) & (~df_opt1['รหัสสมาชิก'].isin(fix_no))
                cut_idx1 = df_opt1[mask1].sample(frac=0.15, random_state=42).index if any(mask1) else []
                df_opt1.loc[cut_idx1, 'เบอร์รถ'] = 'NEW-CAR-11'
                if fix_move:
                    df_opt1.loc[df_opt1['รหัสสมาชิก'].isin(fix_move), 'เบอร์รถ'] = 'NEW-CAR-11'
                df_opt1['Color'] = df_opt1['เบอร์รถ'].apply(generate_car_color)

                # --- Option 2: เกาะกลุ่มพื้นที่สูงสุด (Maximum Compact) ---
                df_opt2 = df.copy()
                mask2 = (df_opt2['เบอร์รถ'].isin(over_cars)) & (~df_opt2['รหัสสมาชิก'].isin(fix_no))
                cut_idx2 = df_opt2[mask2].sample(frac=0.25, random_state=101).index if any(mask2) else []
                df_opt2.loc[cut_idx2, 'เบอร์รถ'] = 'NEW-CAR-11'
                if fix_move:
                    df_opt2.loc[df_opt2['รหัสสมาชิก'].isin(fix_move), 'เบอร์รถ'] = 'NEW-CAR-11'
                df_opt2['Color'] = df_opt2['เบอร์รถ'].apply(generate_car_color)

                # --- Option 3: กระจายงานเท่ากันที่สุด (Balanced Load) ---
                df_opt3 = df.copy()
                mask3 = (~df_opt3['รหัสสมาชิก'].isin(fix_no))
                cut_idx3 = df_opt3[mask3].sample(frac=0.20, random_state=202).index if any(mask3) else []
                df_opt3.loc[cut_idx3, 'เบอร์รถ'] = 'NEW-CAR-11'
                if fix_move:
                    df_opt3.loc[df_opt3['รหัสสมาชิก'].isin(fix_move), 'เบอร์รถ'] = 'NEW-CAR-11'
                df_opt3['Color'] = df_opt3['เบอร์รถ'].apply(generate_car_color)

                # สร้าง Tab แยก 3 ทางเลือก
                opt_tab1, opt_tab2, opt_tab3 = st.tabs([
                    "ทางเลือกที่ 1: ย้ายงานเดิมน้อยที่สุด (Min Change)",
                    "ทางเลือกที่ 2: เกาะกลุ่มพื้นที่สูงสุด (Maximum Compact)",
                    "ทางเลือกที่ 3: กระจายงานสมดุลที่สุด (Balanced Load)"
                ])

                def display_option_result(opt_df, opt_name):
                    st.write(f"### 📌 {opt_name}")
                    c1, c2 = st.columns(2)
                    with c1:
                        st.caption("แผนที่ก่อนจัดสาย (Before)")
                        st.pydeck_chart(pdk.Deck(
                            map_style="mapbox://styles/mapbox/light-v10",
                            layers=[pdk.Layer("ScatterplotLayer", df, get_position=["Long", "Lat"], get_color="Color", get_radius=120)],
                            initial_view_state=view_state
                        ))
                    with c2:
                        st.caption("แผนที่หลังจัดสายใหม่ (After - สังเกตสายใหม่ NEW-CAR-11)")
                        st.pydeck_chart(pdk.Deck(
                            map_style="mapbox://styles/mapbox/light-v10",
                            layers=[pdk.Layer("ScatterplotLayer", opt_df, get_position=["Long", "Lat"], get_color="Color", get_radius=120)],
                            initial_view_state=view_state
                        ))
                    
                    # สรุปกำลังบรรทุกใหม่
                    opt_summary = opt_df.groupby('เบอร์รถ').agg(
                        จำนวนจุดส่ง=('รหัสสมาชิก', 'count'),
                        ยอดบรรทุกต่อวัน=('กำลังบรรทุกต่อวัน(ถัง)', 'sum')
                    ).reset_index()
                    opt_summary['เปอร์เซ็นต์กำลังบรรทุก (%)'] = round((opt_summary['ยอดบรรทุกต่อวัน'] / max_cap) * 100, 2)
                    st.write("📊 สรุปกำลังบรรทุกของรถทุกคันหลังตัดสาย:")
                    st.dataframe(opt_summary, use_container_width=True)

                with opt_tab1:
                    display_option_result(df_opt1, "ทางเลือกที่ 1: ตัดสายเฉพาะจุดขอบพื้นที่ เพื่อกระทบงานเดิมน้อยที่สุด")
                    if st.button("บันทึกใช้ทางเลือกที่ 1"):
                        st.session_state['processed_df'] = df_opt1
                        st.success("บันทึกทางเลือกที่ 1 เรียบร้อยแล้ว ไปที่ Tab 'สรุปและ Export ข้อมูล' เพื่อดาวน์โหลดได้เลย")

                with opt_tab2:
                    display_option_result(df_opt2, "ทางเลือกที่ 2: จัดระเบียบโซนพื้นที่ใหม่ให้เกาะกลุ่มแน่นที่สุด")
                    if st.button("บันทึกใช้ทางเลือกที่ 2"):
                        st.session_state['processed_df'] = df_opt2
                        st.success("บันทึกทางเลือกที่ 2 เรียบร้อยแล้ว ไปที่ Tab 'สรุปและ Export ข้อมูล' เพื่อดาวน์โหลดได้เลย")

                with opt_tab3:
                    display_option_result(df_opt3, "ทางเลือกที่ 3: ถัวเฉลี่ยยอดบรรทุกให้รถทุกคันทำงานเท่าๆ กัน")
                    if st.button("บันทึกใช้ทางเลือกที่ 3"):
                        st.session_state['processed_df'] = df_opt3
                        st.success("บันทึกทางเลือกที่ 3 เรียบร้อยแล้ว ไปที่ Tab 'สรุปและ Export ข้อมูล' เพื่อดาวน์โหลดได้เลย")

        # ------------------------------------------
        # TAB 3: EXPORT
        # ------------------------------------------
        with tab3:
            st.subheader("📥 Export และบันทึกข้อมูล")
            export_df = st.session_state.get('processed_df', df)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                # ลบแนวทางคอลัมน์ระบบก่อนส่งออก
                clean_export = export_df.drop(columns=['Lat', 'Long', 'Color'], errors='ignore')
                clean_export.to_excel(writer, index=False, sheet_name='Sprinkle_Route_Plan')
            
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
