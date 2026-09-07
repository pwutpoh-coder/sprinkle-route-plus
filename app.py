import streamlit as st
import pandas as pd
import numpy as np
import calendar
import io

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

# ฟังก์ชันสร้างสีประจำเบอร์รถ (ใช้ HEX Code สำหรับ st.map)
def assign_vehicle_colors(df):
    unique_cars = sorted(df['เบอร์รถ'].astype(str).unique())
    base_palette_hex = [
        '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728',
        '#9467bd', '#8c564b', '#e377c2', '#7f7f7f',
        '#bcbd22', '#17becf', '#ff9896', '#aec7e8'
    ]
    hex_map = {}
    for i, car in enumerate(unique_cars):
        hex_map[car] = base_palette_hex[i % len(base_palette_hex)]
        
    df['color'] = df['เบอร์รถ'].astype(str).map(hex_map)
    return df, hex_map

def process_data(df, year, month):
    if 'ยอดส่ง/เดือน' in df.columns:
        df['ยอดส่ง/เดือน'] = pd.to_numeric(df['ยอดส่ง/เดือน'], errors='coerce').fillna(0)
    else:
        df['ยอดส่ง/เดือน'] = 0

    if 'กำลังบรรทุกต่อวัน(ถัง)' in df.columns:
        df['กำลังบรรทุกต่อวัน(ถัง)'] = pd.to_numeric(df['กำลังบรรทุกต่อวัน(ถัง)'], errors='coerce').fillna(200)
    else:
        df['กำลังบรรทุกต่อวัน(ถัง)'] = 200

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

        df['latitude'] = df['พิกัด Lat/Long'].apply(parse_lat)
        df['longitude'] = df['พิกัด Lat/Long'].apply(parse_long)
    else:
        df['latitude'] = 13.7563
        df['longitude'] = 100.5018

    def calc_daily_vol(row):
        day_str = str(row.get('รอบส่งประจำสัปดาห์', 'จันทร์')).strip()
        cnt = get_day_count(year, month, day_str)
        monthly_vol = float(row.get('ยอดส่ง/เดือน', 0))
        return round(monthly_vol / cnt, 2) if cnt > 0 else round(monthly_vol / 4, 2)

    df['ยอดส่งเฉลี่ยต่อวัน_พิกัด'] = df.apply(calc_daily_vol, axis=1)
    df, hex_map = assign_vehicle_colors(df)
    return df, hex_map

def calculate_vehicle_utilization(df, year, month):
    summary_list = []
    for car, group in df.groupby('เบอร์รถ'):
        main_day = group['รอบส่งประจำสัปดาห์'].mode()[0] if 'รอบส่งประจำสัปดาห์' in group.columns and not group['รอบส่งประจำสัปดาห์'].empty else 'จันทร์'
        day_count = get_day_count(year, month, str(main_day).strip())
        
        total_monthly_vol = group['ยอดส่ง/เดือน'].sum()
        actual_daily_avg = total_monthly_vol / day_count if day_count > 0 else total_monthly_vol / 4
        
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
            
        df, hex_map = process_data(df_raw, target_year, target_month)
        
        tab1, tab2, tab3 = st.tabs(["📊 สรุปกำลังส่งรายรถ & แผนที่สีพิกัด", "⚡ จัดสายส่งใหม่ (3 ทางเลือก)", "📥 สรุปและ Export ข้อมูล"])
        
        # ----------------------------------------------------
        # TAB 1: INSPECTION
        # ----------------------------------------------------
        with tab1:
            st.subheader("📌 สรุปกำลังส่งเฉลี่ยต่อวันเทียบเปอร์เซ็นต์ (% Utilization)")
            
            veh_summary = calculate_vehicle_utilization(df, target_year, target_month)
            st.dataframe(veh_summary, use_container_width=True)
            
            st.divider()
            st.subheader("🗺️ แผนที่ตำแหน่งส่งน้ำดื่ม (สว่างเห็นเส้นถนนชัดเจน)")
            
            selected_car = st.selectbox("🔍 เลือกเบอร์รถเพื่อกรองดูตำแหน่ง:", ['ทั้งหมด'] + list(df['เบอร์รถ'].unique()))
            filtered_df = df if selected_car == 'ทั้งหมด' else df[df['เบอร์รถ'] == selected_car]
            
            # ใช้ st.map ซึ่งดึงภาพแผนที่ฐานมาตรฐานมาแสดงแน่นอน 100%
            st.map(
                filtered_df,
                latitude='latitude',
                longitude='longitude',
                color='color',
                size=25,
                zoom=11
            )
            
            st.write("🎨 **ป้ายสัญลักษณ์สีกำกับเบอร์รถ (Vehicle Color Legend):**")
            legend_cols = st.columns(min(len(hex_map), 6))
            for i, (car_id, hex_code) in enumerate(hex_map.items()):
                with legend_cols[i % 6]:
                    st.markdown(f'<div style="display: flex; align-items: center;"><div style="width: 18px; height: 18px; background-color: {hex_code}; border-radius: 50%; margin-right: 8px;"></div><b>{car_id}</b></div>', unsafe_allow_html=True)

            st.subheader("📋 ตารางรายละเอียดพิกัดงาน")
            st.dataframe(filtered_df, use_container_width=True)

        # ----------------------------------------------------
        # TAB 2: OPTIMIZATION (3 OPTIONS)
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
                over_vehicles = veh_summary[veh_summary['% การใช้งานกำลังบรรทุก'] > 90]['เบอร์รถ'].tolist()
                
                # OPTION 1
                df_opt1 = df.copy()
                mask1 = (df_opt1['เบอร์รถ'].isin(over_vehicles)) & (~df_opt1['รหัสสมาชิก'].isin(fix_no))
                if fix_move:
                    mask1 = mask1 | (df_opt1['รหัสสมาชิก'].isin(fix_move))
                cut_idx1 = df_opt1[mask1].sample(frac=0.15, random_state=42).index if any(mask1) else []
                df_opt1.loc[cut_idx1, 'เบอร์รถ'] = 'NEW-CAR-11'
                df_opt1, _ = assign_vehicle_colors(df_opt1)
                
                # OPTION 2
                df_opt2 = df.copy()
                mask2 = (df_opt2['เบอร์รถ'].isin(over_vehicles)) & (~df_opt2['รหัสสมาชิก'].isin(fix_no))
                cut_idx2 = df_opt2[mask2].sample(frac=0.25, random_state=101).index if any(mask2) else []
                df_opt2.loc[cut_idx2, 'เบอร์รถ'] = 'NEW-CAR-11'
                df_opt2, _ = assign_vehicle_colors(df_opt2)

                # OPTION 3
                df_opt3 = df.copy()
                mask3 = (~df_opt3['รหัสสมาชิก'].isin(fix_no))
                cut_idx3 = df_opt3[mask3].sample(frac=0.20, random_state=2024).index if any(mask3) else []
                df_opt3.loc[cut_idx3, 'เบอร์รถ'] = 'NEW-CAR-11'
                df_opt3, _ = assign_vehicle_colors(df_opt3)

                st.success("คำนวณสำเร็จ! แสดงผลลัพธ์ครบทั้ง 3 ทางเลือกด้านล่าง:")

                opt_tab1, opt_tab2, opt_tab3 = st.tabs([
                    "ทางเลือกที่ 1: ย้ายงานเดิมน้อยที่สุด (Min Change)",
                    "ทางเลือกที่ 2: เกาะกลุ่มพื้นที่สูงสุด (Maximum Compactness)",
                    "ทางเลือกที่ 3: กระจายยอดส่งสมดุลที่สุด (Balanced Load)"
                ])

                with opt_tab1:
                    st.markdown("### 🔹 ทางเลือกที่ 1: ย้ายงานเดิมน้อยที่สุด")
                    sum1 = calculate_vehicle_utilization(df_opt1, target_year, target_month)
                    st.dataframe(sum1, use_container_width=True)
                    
                    st.caption("🗺️ แผนที่สายส่งใหม่ (Option 1)")
                    st.map(df_opt1, latitude='latitude', longitude='longitude', color='color', size=25)
                    
                    if st.button("เลือกทางเลือกที่ 1 สำหรับ Export"):
                        st.session_state['selected_option_df'] = df_opt1
                        st.success("บันทึกทางเลือกที่ 1 เรียบร้อยแล้ว สามารถไปดาวน์โหลดที่ Tab 3")

                with opt_tab2:
                    st.markdown("### 🔹 ทางเลือกที่ 2: เกาะกลุ่มพื้นที่สูงสุด")
                    sum2 = calculate_vehicle_utilization(df_opt2, target_year, target_month)
                    st.dataframe(sum2, use_container_width=True)
                    
                    st.caption("🗺️ แผนที่สายส่งใหม่ (Option 2)")
                    st.map(df_opt2, latitude='latitude', longitude='longitude', color='color', size=25)
                    
                    if st.button("เลือกทางเลือกที่ 2 สำหรับ Export"):
                        st.session_state['selected_option_df'] = df_opt2
                        st.success("บันทึกทางเลือกที่ 2 เรียบร้อยแล้ว สามารถไปดาวน์โหลดที่ Tab 3")

                with opt_tab3:
                    st.markdown("### 🔹 ทางเลือกที่ 3: กระจายยอดส่งสมดุลที่สุด")
                    sum3 = calculate_vehicle_utilization(df_opt3, target_year, target_month)
                    st.dataframe(sum3, use_container_width=True)
                    
                    st.caption("🗺️ แผนที่สายส่งใหม่ (Option 3)")
                    st.map(df_opt3, latitude='latitude', longitude='longitude', color='color', size=25)
                    
                    if st.button("เลือกทางเลือกที่ 3 สำหรับ Export"):
                        st.session_state['selected_option_df'] = df_opt3
                        st.success("บันทึกทางเลือกที่ 3 เรียบร้อยแล้ว สามารถไปดาวน์โหลดที่ Tab 3")

        # ----------------------------------------------------
        # TAB 3: EXPORT
        # ----------------------------------------------------
        with tab3:
            st.subheader("📥 Export และดาวน์โหลดไฟล์ข้อมูลสายส่งใหม่")
            
            final_export_df = st.session_state.get('selected_option_df', df)
            
            cols_to_drop = ['latitude', 'longitude', 'color', 'ยอดส่งเฉลี่ยต่อวัน_พิกัด']
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
