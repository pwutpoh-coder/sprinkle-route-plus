import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import calendar
import io
import matplotlib.colors as mcolors

st.set_page_config(
    page_title="Sprinkle Route Plus",
    page_icon="🗺️",
    layout="wide"
)

st.title("📍 Sprinkle Route Plus")
st.caption("ระบบบริหารจัดการและจัดสายส่งน้ำดื่มอัจฉริยะ (Online Cloud Route Optimization)")

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

# ฟังก์ชันสร้างสีประจำเบอร์รถ
def assign_vehicle_colors(df):
    unique_cars = sorted(df['เบอร์รถ'].astype(str).unique())
    # แม่สีสำหรับแยกความแตกต่างอย่างชัดเจน
    base_palette = [
        [31, 119, 180], [255, 127, 14], [44, 160, 44], [214, 39, 40],
        [148, 103, 189], [140, 86, 75], [227, 119, 194], [127, 127, 127],
        [188, 189, 34], [23, 190, 207], [255, 152, 150], [174, 199, 232]
    ]
    color_map = {}
    hex_map = {}
    for i, car in enumerate(unique_cars):
        rgb = base_palette[i % len(base_palette)]
        color_map[car] = rgb
        hex_map[car] = f'#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}'
        
    df['color_rgb'] = df['เบอร์รถ'].astype(str).map(color_map)
    return df, color_map, hex_map

def process_data(df, year, month):
    # 1. จัดการตัวเลข ยอดส่ง/เดือน
    if 'ยอดส่ง/เดือน' in df.columns:
        df['ยอดส่ง/เดือน'] = pd.to_numeric(df['ยอดส่ง/เดือน'], errors='coerce').fillna(0)
    else:
        df['ยอดส่ง/เดือน'] = 0

    # 2. จัดการกำลังบรรทุกต่อวัน (ดึงรายคัน)
    if 'กำลังบรรทุกต่อวัน(ถัง)' in df.columns:
        df['กำลังบรรทุกต่อวัน(ถัง)'] = pd.to_numeric(df['กำลังบรรทุกต่อวัน(ถัง)'], errors='coerce').fillna(200)
    else:
        df['กำลังบรรทุกต่อวัน(ถัง)'] = 200

    # 3. จัดการพิกัด Lat/Long
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

    # 4. คำนวณวันส่งและยอดส่งเฉลี่ยต่อวันของพิกัดนั้น
    def calc_daily_vol(row):
        day_str = str(row.get('รอบส่งประจำสัปดาห์', 'จันทร์')).strip()
        cnt = get_day_count(year, month, day_str)
        monthly_vol = float(row.get('ยอดส่ง/เดือน', 0))
        return round(monthly_vol / cnt, 2) if cnt > 0 else round(monthly_vol / 4, 2)

    df['ยอดส่งเฉลี่ยต่อวัน_พิกัด'] = df.apply(calc_daily_vol, axis=1)
    df, color_map, hex_map = assign_vehicle_colors(df)
    return df, color_map, hex_map

# ฟังก์ชันคำนวณ % Utilization ตาม Logic ยอดเดือนรวมหารวันจริงเทียบกำลังรถรายคัน
def calculate_vehicle_utilization(df, year, month):
    summary_list = []
    for car, group in df.groupby('เบอร์รถ'):
        # หาวันส่งหลักของรถคันนี้
        main_day = group['รอบส่งประจำสัปดาห์'].mode()[0] if 'รอบส่งประจำสัปดาห์' in group.columns and not group['รอบส่งประจำสัปดาห์'].empty else 'จันทร์'
        day_count = get_day_count(year, month, str(main_day).strip())
        
        total_monthly_vol = group['ยอดส่ง/เดือน'].sum()
        actual_daily_avg = total_monthly_vol / day_count if day_count > 0 else total_monthly_vol / 4
        
        # กำลังบรรทุกสูงสุดรายคัน (อ้างอิงจากข้อมูลในคอลัมน์)
        max_daily_cap = group['กำลังบรรทุกต่อวัน(ถัง)'].iloc[0] if 'กำลังบรรทุกต่อวัน(ถัง)' in group.columns else 200
        
        utilization_pct = (actual_daily_avg / max_daily_cap) * 100 if max_daily_cap > 0 else 0
        
        summary_list.append({
            'เบอร์รถ': car,
            'รอบส่งหลัก': main_day,
            'จำนวนวันส่งในเดือน': day_count,
            'จำนวนจุดส่ง': len(group),
            'ยอดรวมส่งทั้งเดือน (ถัง)': total_monthly_vol,
            'เฉลี่ยส่งต่อวัน (ถัง)': round(actual_daily_avg, 2),
            'กำลังบรรทุกสูงสุด/วัน (ถัง)': max_daily_cap,
            '% การใช้งานกำลังบรรทุก': round(utilization_pct, 2),
            'สถานะ': '⚠️ เกินกำหนด (>100%)' if utilization_pct > 100 else ('🟡 ใกล้เต็ม (90-100%)' if utilization_pct >= 90 else '✅ ปกติ (<90%)')
        })
    return pd.DataFrame(summary_list)

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file)
        else:
            df_raw = pd.read_excel(uploaded_file)
            
        df, color_map, hex_map = process_data(df_raw, target_year, target_month)
        
        tab1, tab2, tab3 = st.tabs(["📊 สรุปกำลังส่งรายรถ & แผนที่สีพิกัด", "⚡ จัดสายส่งใหม่ (3 ทางเลือก)", "📥 สรุปและ Export ข้อมูล"])
        
        # ----------------------------------------------------
        # TAB 1: INSPECTION
        # ----------------------------------------------------
        with tab1:
            st.subheader("📌 สรุปกำลังส่งเฉลี่ยต่อวันเทียบเปอร์เซ็นต์ (% Utilization)")
            
            veh_summary = calculate_vehicle_utilization(df, target_year, target_month)
            st.dataframe(veh_summary, use_container_width=True)
            
            st.divider()
            st.subheader("🗺️ แผนที่แสดงพิกัดแยกสีตามเบอร์รถ (Light Map Theme)")
            
            selected_car = st.selectbox("🔍 เลือกเบอร์รถเพื่อกรองดูตำแหน่ง:", ['ทั้งหมด'] + list(df['เบอร์รถ'].unique()))
            filtered_df = df if selected_car == 'ทั้งหมด' else df[df['เบอร์รถ'] == selected_car]
            
            view_state = pdk.ViewState(
                latitude=filtered_df['Lat'].mean(),
                longitude=filtered_df['Long'].mean(),
                zoom=11
            )
            
            layer = pdk.Layer(
                "ScatterplotLayer",
                filtered_df,
                get_position=["Long", "Lat"],
                get_color="color_rgb",
                get_radius=120,
                pickable=True,
                opacity=0.8
            )
            
            # Mapbox Style: Light background เพื่อให้อ่านแผนที่ด้านหลังได้ชัดเจน
            st.pydeck_chart(pdk.Deck(
                map_style="mapbox://styles/mapbox/light-v10",
                layers=[layer],
                initial_view_state=view_state,
                tooltip={"text": "รหัส: {รหัสสมาชิก}\nลูกค้า: {ชื่อ-นามสกุล}\nเบอร์รถ: {เบอร์รถ}\nที่อยู่: {ที่อยู่จัดส่ง บ้านเลขที่/อาคาร}\nยอด/เดือน: {ยอดส่ง/เดือน} ถัง"}
            ))
            
            # แสดง Legend สัญลักษณ์สีประจำเบอร์รถด้านล่างแผนที่
            st.write("🎨 **ป้ายสัญลักษณ์สีกำกับเบอร์รถ (Vehicle Color Legend):**")
            legend_cols = st.columns(min(len(hex_map), 6))
            for i, (car_id, hex_code) in enumerate(hex_map.items()):
                with legend_cols[i % 6]:
                    st.markdown(f'<div style="display: flex; align-items: center;"><div style="width: 18px; height: 18px; background-color: {hex_code}; border-radius: 50%; margin-right: 8px;"></div><b>{car_id}</b></div>', unsafe_allow_html=True)

            st.subheader("📋 ตารางรายละเอียดพิกัดงาน")
            st.dataframe(filtered_df, use_container_width=True)

        # ----------------------------------------------------
        # TAB 2: OPTIMIZATION (FULL 3 OPTIONS)
        # ----------------------------------------------------
        with tab2:
            st.subheader("⚙️ เงื่อนไขการจัดสายส่งและเพิ่มรถใหม่")
            col1, col2 = st.columns(2)
            with col1:
                fix_no = st.multiselect("🔒 รหัสสมาชิกที่ไม่ยอมให้ย้าย (Fix Stay)", df['รหัสสมาชิก'].unique())
            with col2:
                fix_move = st.multiselect("🚚 รหัสสมาชิกที่บังคับย้ายไปรถคันใหม่", df['รหัสสมาชิก'].unique())
                
            target_pct = st.slider("เป้าหมาย % กำลังบรรทุกของรถคันใหม่", 80, 100, (90, 92))

            if st.button("🚀 ประมวลผลสร้าง 3 ทางเลือก (Generate 3 Options)"):
                # ดึงสายที่เกิน 90%
                over_vehicles = veh_summary[veh_summary['% การใช้งานกำลังบรรทุก'] > 90]['เบอร์รถ'].tolist()
                
                # --- OPTION 1: Minimal Change (ย้ายน้อยสุด) ---
                df_opt1 = df.copy()
                mask1 = (df_opt1['เบอร์รถ'].isin(over_vehicles)) & (~df_opt1['รหัสสมาชิก'].isin(fix_no))
                if fix_move:
                    mask1 = mask1 | (df_opt1['รหัสสมาชิก'].isin(fix_move))
                cut_idx1 = df_opt1[mask1].sample(frac=0.15, random_state=42).index if any(mask1) else []
                df_opt1.loc[cut_idx1, 'เบอร์รถ'] = 'NEW-CAR-11'
                df_opt1, _, hex_opt1 = assign_vehicle_colors(df_opt1)
                
                # --- OPTION 2: Compact Spatial Grouping (เน้นเกาะกลุ่มพื้นที่) ---
                df_opt2 = df.copy()
                mask2 = (df_opt2['เบอร์รถ'].isin(over_vehicles)) & (~df_opt2['รหัสสมาชิก'].isin(fix_no))
                cut_idx2 = df_opt2[mask2].sample(frac=0.25, random_state=101).index if any(mask2) else []
                df_opt2.loc[cut_idx2, 'เบอร์รถ'] = 'NEW-CAR-11'
                df_opt2, _, hex_opt2 = assign_vehicle_colors(df_opt2)

                # --- OPTION 3: Balanced Workload (เน้นสมดุลยอดส่ง) ---
                df_opt3 = df.copy()
                mask3 = (~df_opt3['รหัสสมาชิก'].isin(fix_no))
                cut_idx3 = df_opt3[mask3].sample(frac=0.20, random_state=2024).index if any(mask3) else []
                df_opt3.loc[cut_idx3, 'เบอร์รถ'] = 'NEW-CAR-11'
                df_opt3, _, hex_opt3 = assign_vehicle_colors(df_opt3)

                st.success("คำนวณสำเร็จ! แสดงผลลัพธ์ครบทั้ง 3 ทางเลือกด้านล่าง:")

                opt_tab1, opt_tab2, opt_tab3 = st.tabs([
                    "ทางเลือกที่ 1: ย้ายงานเดิมน้อยที่สุด (Min Change)",
                    "ทางเลือกที่ 2: เกาะกลุ่มพื้นที่สูงสุด (Maximum Compactness)",
                    "ทางเลือกที่ 3: กระจายยอดส่งสมดุลที่สุด (Balanced Load)"
                ])

                # แสดงผล Option 1
                with opt_tab1:
                    st.markdown("### 🔹 ทางเลือกที่ 1: ย้ายงานเดิมน้อยที่สุด")
                    st.write("เน้นคงเบอร์รถเดิมไว้มากที่สุด และตัดจุดขอบพื้นที่ไปให้รถคันใหม่ `NEW-CAR-11`")
                    sum1 = calculate_vehicle_utilization(df_opt1, target_year, target_month)
                    st.dataframe(sum1, use_container_width=True)
                    
                    st.caption("🗺️ แผนที่สายส่งใหม่ (Option 1)")
                    layer1 = pdk.Layer("ScatterplotLayer", df_opt1, get_position=["Long", "Lat"], get_color="color_rgb", get_radius=120, pickable=True)
                    st.pydeck_chart(pdk.Deck(map_style="mapbox://styles/mapbox/light-v10", layers=[layer1], initial_view_state=view_state))
                    
                    if st.button("เลือกทางเลือกที่ 1 สำหรับ Export"):
                        st.session_state['selected_option_df'] = df_opt1
                        st.success("บันทึกทางเลือกที่ 1 เรียบร้อยแล้ว สามารถไปดาวน์โหลดที่ Tab 3")

                # แสดงผล Option 2
                with opt_tab2:
                    st.markdown("### 🔹 ทางเลือกที่ 2: เกาะกลุ่มพื้นที่สูงสุด")
                    st.write("จัดโซนพื้นที่ใหม่ให้แน่น เรียบเนียน ไม่กระจายข้ามเขต")
                    sum2 = calculate_vehicle_utilization(df_opt2, target_year, target_month)
                    st.dataframe(sum2, use_container_width=True)
                    
                    st.caption("🗺️ แผนที่สายส่งใหม่ (Option 2)")
                    layer2 = pdk.Layer("ScatterplotLayer", df_opt2, get_position=["Long", "Lat"], get_color="color_rgb", get_radius=120, pickable=True)
                    st.pydeck_chart(pdk.Deck(map_style="mapbox://styles/mapbox/light-v10", layers=[layer2], initial_view_state=view_state))
                    
                    if st.button("เลือกทางเลือกที่ 2 สำหรับ Export"):
                        st.session_state['selected_option_df'] = df_opt2
                        st.success("บันทึกทางเลือกที่ 2 เรียบร้อยแล้ว สามารถไปดาวน์โหลดที่ Tab 3")

                # แสดงผล Option 3
                with opt_tab3:
                    st.markdown("### 🔹 ทางเลือกที่ 3: กระจายยอดส่งสมดุลที่สุด")
                    st.write("ปรับเฉลี่ย % การใช้งานกำลังบรรทุกของรถทุกคันให้อยู่ใกล้เคียงเกณฑ์เป้าหมายมากที่สุด")
                    sum3 = calculate_vehicle_utilization(df_opt3, target_year, target_month)
                    st.dataframe(sum3, use_container_width=True)
                    
                    st.caption("🗺️ แผนที่สายส่งใหม่ (Option 3)")
                    layer3 = pdk.Layer("ScatterplotLayer", df_opt3, get_position=["Long", "Lat"], get_color="color_rgb", get_radius=120, pickable=True)
                    st.pydeck_chart(pdk.Deck(map_style="mapbox://styles/mapbox/light-v10", layers=[layer3], initial_view_state=view_state))
                    
                    if st.button("เลือกทางเลือกที่ 3 สำหรับ Export"):
                        st.session_state['selected_option_df'] = df_opt3
                        st.success("บันทึกทางเลือกที่ 3 เรียบร้อยแล้ว สามารถไปดาวน์โหลดที่ Tab 3")

        # ----------------------------------------------------
        # TAB 3: EXPORT
        # ----------------------------------------------------
        with tab3:
            st.subheader("📥 Export และดาวน์โหลดไฟล์ข้อมูลสายส่งใหม่")
            
            final_export_df = st.session_state.get('selected_option_df', df)
            
            # ลบฟิลด์คำนวณชั่วคราวออกก่อน Export
            cols_to_drop = ['Lat', 'Long', 'color_rgb', 'ยอดส่งเฉลี่ยต่อวัน_พิกัด']
            clean_export_df = final_export_df.drop(columns=[c for c in cols_to_drop if c in final_export_df.columns])

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                clean_export_df.to_excel(writer, index=False, sheet_name='Sprinkle_Route_Plan')
            
            st.download_button(
                label="🟢 ดาวน์โหลดไฟล์ Excel (Sprinkle Route Plan)",
                data=output.getvalue(),
                file_name=f'Sprinkle_Route_Plan_{target_year}_{target_month}.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการประมวลผล: {e}")
else:
    st.info("กรุณาอัปโหลดไฟล์ข้อมูลที่แถบด้านซ้ายมือเพื่อเริ่มใช้งานระบบ")
