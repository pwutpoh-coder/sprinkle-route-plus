import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
from sklearn.cluster import KMeans
import calendar
import io
import re

# 1. ตั้งค่าหน้าเพจ
st.set_page_config(
    page_title="Sprinkle Route Plus",
    page_icon="🗺️",
    layout="wide"
)

st.title("📍 Sprinkle Route Plus")
st.caption("ระบบบริหารจัดการและจัดสายส่งน้ำดื่มอัจฉริยะ (Ultra High-Performance WebGL Engine)")

# 2. Sidebar สำหรับอัปโหลดไฟล์และตั้งค่า
st.sidebar.header("⚙️ ตั้งค่าข้อมูล")
uploaded_file = st.sidebar.file_uploader("อัปโหลดไฟล์ Excel / CSV", type=["xlsx", "csv"])

target_year = st.sidebar.number_input("ปี ค.ศ.", min_value=2024, max_value=2030, value=2026)
target_month = st.sidebar.selectbox("เดือน", range(1, 13), format_func=lambda x: calendar.month_name[x], index=7) # Default ส.ค. (8)

# Map วันในภาษาไทย
DAY_MAP = {
    'จันทร์': 0, 'จ': 0,
    'อังคาร': 1, 'อ': 1,
    'พุธ': 2, 'พ': 2,
    'พฤหัสบดี': 3, 'พฤหัส': 3, 'พฤ': 3,
    'ศุกร์': 4, 'ศ': 4,
    'เสาร์': 5, 'ส': 5,
    'อาทิตย์': 6, 'อา': 6
}

@st.cache_data
def get_days_count_in_month(year, month):
    """ คืนค่า Dictionary นับจำนวนวันแต่ละวันในเดือน """
    cal = calendar.monthcalendar(year, month)
    counts = {}
    for day_name, day_idx in DAY_MAP.items():
        if len(day_name) > 1 and day_name not in ['พฤหัส', 'พฤ']:
            cnt = sum(1 for week in cal if week[day_idx] != 0)
            counts[day_name] = cnt if cnt > 0 else 4
    return counts

@st.cache_data
def assign_vehicle_colors(df):
    unique_cars = sorted(df['เบอร์รถ'].astype(str).unique())
    rgb_palette = [
        [31, 119, 180], [255, 127, 14], [44, 160, 44], [214, 39, 40],
        [148, 103, 189], [140, 86, 75], [227, 119, 194], [23, 190, 207],
        [188, 189, 34], [127, 127, 127], [255, 152, 150], [174, 199, 232]
    ]
    
    rgb_map = {}
    for i, car in enumerate(unique_cars):
        rgb_map[car] = rgb_palette[i % len(rgb_palette)]
        
    df['color_rgb'] = df['เบอร์รถ'].astype(str).map(rgb_map)
    return df, rgb_map

# 3. ฟังก์ชันคำนวณยอดส่งเฉลี่ยต่อวันระดับบรรทัด
def calculate_row_daily_volume(row, day_counts):
    monthly_vol = float(row.get('ยอดส่ง/เดือน', 0))
    if monthly_vol <= 0:
        return 0.0

    raw_schedule = str(row.get('รอบส่งประจำสัปดาห์', '')).strip()
    if not raw_schedule or raw_schedule.lower() == 'nan':
        return round((monthly_vol / 4) / 6, 2)

    found_days = []
    for day_name in DAY_MAP.keys():
        if day_name in raw_schedule:
            std_name = 'พฤหัสบดี' if day_name in ['พฤหัสบดี', 'พฤหัส', 'พฤ'] else (
                       'จันทร์' if day_name in ['จันทร์', 'จ'] else (
                       'อังคาร' if day_name in ['อังคาร', 'อ'] else (
                       'พุธ' if day_name in ['พุธ', 'พ'] else (
                       'ศุกร์' if day_name in ['ศุกร์', 'ศ'] else (
                       'เสาร์' if day_name in ['เสาร์', 'ส'] else 'อาทิตย์')))))
            if std_name not in found_days:
                found_days.append(std_name)

    if not found_days:
        return round((monthly_vol / 4) / 6, 2)

    weekly_vol_sum = 0.0
    for day in found_days:
        days_in_month = day_counts.get(day, 4)
        weekly_vol_sum += (monthly_vol / days_in_month)

    daily_vol = weekly_vol_sum / 6.0
    return round(daily_vol, 2)

@st.cache_data
def process_data(df, year, month):
    df['ยอดส่ง/เดือน'] = pd.to_numeric(df.get('ยอดส่ง/เดือน', 0), errors='coerce').fillna(0)
    df['กำลังบรรทุกต่อวัน(ถัง)'] = pd.to_numeric(df.get('กำลังบรรทุกต่อวัน(ถัง)', 200), errors='coerce').fillna(200)

    if 'พิกัด Lat/Long' in df.columns:
        coords = df['พิกัด Lat/Long'].astype(str).str.split(',', expand=True)
        df['latitude'] = pd.to_numeric(coords[0].str.strip(), errors='coerce').fillna(13.7563)
        df['longitude'] = pd.to_numeric(coords[1].str.strip(), errors='coerce').fillna(100.5018)
    else:
        df['latitude'] = 13.7563
        df['longitude'] = 100.5018

    day_counts = get_days_count_in_month(year, month)
    df['ยอดส่งเฉลี่ยต่อวัน_คำนวณ'] = df.apply(lambda r: calculate_row_daily_volume(r, day_counts), axis=1)

    df, rgb_map = assign_vehicle_colors(df)
    return df, rgb_map

@st.cache_data
def calculate_vehicle_utilization(df, year, month):
    summary_list = []
    
    for car, group in df.groupby('เบอร์รถ'):
        total_monthly_vol = group['ยอดส่ง/เดือน'].sum()
        total_calculated_daily_vol = group['ยอดส่งเฉลี่ยต่อวัน_คำนวณ'].sum()
        
        max_daily_cap = group['กำลังบรรทุกต่อวัน(ถัง)'].iloc[0] if 'กำลังบรรทุกต่อวัน(ถัง)' in group.columns else 200
        utilization_pct = (total_calculated_daily_vol / max_daily_cap) * 100 if max_daily_cap > 0 else 0
        
        summary_list.append({
            'เบอร์รถ': car,
            'จำนวนจุดส่ง (บรรทัด)': len(group),
            'ยอดรวมส่งทั้งเดือน (ถัง)': total_monthly_vol,
            'ยอดส่งเฉลี่ยต่อวันรวม (ถัง)': round(total_calculated_daily_vol, 2),
            'กำลังบรรทุกสูงสุด/วัน (ถัง)': max_daily_cap,
            '% การใช้งานกำลังบรรทุก': round(utilization_pct, 2),
            'สถานะ': '⚠️ เกินกำหนด (>100%)' if utilization_pct > 100 else ('🟡 อยู่ในเกณฑ์เป้าหมาย (90-93%)' if 90 <= utilization_pct <= 93 else ('🟡 ใกล้เต็ม (93-100%)' if utilization_pct > 93 else '✅ ปกติ (<90%)'))
        })
    return pd.DataFrame(summary_list)

# 4. แผนที่ความเร็วสูง WebGL
def render_fast_pydeck_map(df_input, selected_cars):
    df_copy = df_input.copy()
    
    def get_render_color(row):
        car_str = str(row['เบอร์รถ'])
        if car_str in selected_cars:
            return row['color_rgb']
        return [210, 210, 210, 100]

    df_copy['render_color'] = df_copy.apply(get_render_color, axis=1)
    df_copy['car_str'] = df_copy['เบอร์รถ'].astype(str)
    
    mean_lat = df_copy['latitude'].mean()
    mean_lon = df_copy['longitude'].mean()

    view_state = pdk.ViewState(
        latitude=mean_lat if pd.notnull(mean_lat) else 13.7563,
        longitude=mean_lon if pd.notnull(mean_lon) else 100.5018,
        zoom=11,
        pitch=0
    )

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_copy,
        get_position=["longitude", "latitude"],
        get_fill_color="render_color",
        get_radius=100,
        pickable=True,
        opacity=0.85,
        stroked=True,
        get_line_color=[255, 255, 255],
        line_width_min_pixels=1,
    )

    tooltip = {
        "html": "<b>🚚 เบอร์รถ:</b> {car_str}<br/>"
                "<b>🆔 รหัสสมาชิก:</b> {รหัสสมาชิก}<br/>"
                "<b>👤 ชื่อ:</b> {ชื่อ-นามสกุล}<br/>"
                "<b>📦 ยอดส่งต่อเดือน:</b> {ยอดส่ง/เดือน} ถัง<br/>"
                "<b>⚡ ยอดส่งเฉลี่ย/วัน (บรรทัดนี้):</b> {ยอดส่งเฉลี่ยต่อวัน_คำนวณ} ถัง/วัน",
        "style": {
            "backgroundColor": "#1e293b",
            "color": "white",
            "font-family": "sans-serif",
            "fontSize": "13px",
            "padding": "10px",
            "borderRadius": "6px",
            "zIndex": "999"
        }
    }

    st.pydeck_chart(
        pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            tooltip=tooltip,
            map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
        )
    )

def render_limited_dataframe(df_to_show, key_suffix):
    col_limit, _ = st.columns([1, 2])
    with col_limit:
        limit = st.selectbox(
            "⚡ เลือกจำนวนรายการตารางที่ต้องการแสดง:",
            options=[20, 50, 100, "แสดงทั้งหมด"],
            index=1,
            key=f"row_limit_{key_suffix}"
        )
    
    if limit == "แสดงทั้งหมด":
        st.dataframe(df_to_show, use_container_width=True)
    else:
        st.dataframe(df_to_show.head(limit), use_container_width=True)
        st.caption(f"⚡ แสดง {limit} รายการแรกเพื่อความรวดเร็ว (ดาวน์โหลดทั้งหมดได้ที่ Tab 3)")

# 5. อัลกอริทึมตัดสายส่งใหม่โดยคุมเป้าหมาย % Utilization ให้อยู่ในช่วง 90% - 93% ทั้งคันใหม่และคันเก่า (แก้ไขจุด np.linalg.norm)
def rebalance_routes_strict_utilization(df_in, target_cars, fix_stay_ids, fix_move_ids, target_min_pct=90.0, target_max_pct=93.0, new_car_capacity=200.0):
    df_res = df_in.copy()
    
    # 1. บังคับย้ายรายการ Fix Move ไปยังคันใหม่ก่อน
    if fix_move_ids:
        df_res.loc[df_res['รหัสสมาชิก'].isin(fix_move_ids), 'เบอร์รถ'] = 'NEW-CAR-11'

    # คำนวณเป้าหมายยอดส่งต่อวันของรถคันใหม่ (90-93% ของ Capacity)
    new_car_target_min = new_car_capacity * (target_min_pct / 100.0)
    new_car_target_max = new_car_capacity * (target_max_pct / 100.0)

    # วนลูปตัดงานจากแต่ละรถต้นทางที่ถูกเลือก
    for car in target_cars:
        car_rows = df_res[df_res['เบอร์รถ'].astype(str) == str(car)]
        if car_rows.empty:
            continue
            
        car_cap = car_rows['กำลังบรรทุกต่อวัน(ถัง)'].iloc[0] if 'กำลังบรรทุกต่อวัน(ถัง)' in car_rows.columns else 200.0
        car_target_max_vol = car_cap * (target_max_pct / 100.0) # ยอดส่งสูงสุดที่ยอมให้เหลืออยู่หลังตัด (93%)
        car_target_min_vol = car_cap * (target_min_pct / 100.0) # ยอดส่งต่ำสุดที่ยอมให้เหลืออยู่หลังตัด (90%)

        # คำนวณยอดปัจจุบัน
        current_daily_vol = car_rows['ยอดส่งเฉลี่ยต่อวัน_คำนวณ'].sum()
        
        # ถ้ารถคันนี้เกิน 93% ให้คำนวณตัดออกจนกว่าจะลงมาอยู่ในช่วง 90-93%
        if current_daily_vol > car_target_max_vol:
            # กรองเฉพาะบรรทัดที่ได้รับอนุญาตให้ย้ายได้ (ไม่ติด Fix Stay)
            eligible_candidates = car_rows[~car_rows['รหัสสมาชิก'].isin(fix_stay_ids)].copy()
            if eligible_candidates.empty:
                continue

            # เรียงลำดับพื้นที่ให้เกาะกลุ่มด้วย ระยะทางจากจุดศูนย์กลาง
            if len(eligible_candidates) >= 2:
                coords = eligible_candidates[['latitude', 'longitude']].values
                center = coords.mean(axis=0)
                # แก้ไขเป็น np.linalg.norm
                eligible_candidates['dist_to_center'] = np.linalg.norm(coords - center, axis=1)
                # เรียงจากจุดที่อยู่รอบนอกเข้ามาหาศูนย์กลางเพื่อตัดออกเป็นกลุ่มพื้นที่
                eligible_candidates = eligible_candidates.sort_values(by='dist_to_center', ascending=False)

            # วนลูปตัดงานย้ายไป NEW-CAR-11
            for idx, candidate in eligible_candidates.iterrows():
                # ตรวจสอบ ยอดปัจจุบันของคันใหม่
                new_car_current_vol = df_res[df_res['เบอร์รถ'] == 'NEW-CAR-11']['ยอดส่งเฉลี่ยต่อวัน_คำนวณ'].sum()
                
                # ถ้ารถคันใหม่ยอดเต็มเป้าหมาย 93% แล้ว ให้หยุด
                if new_car_current_vol >= new_car_target_max:
                    break
                    
                cand_vol = candidate['ยอดส่งเฉลี่ยต่อวัน_คำนวณ']
                
                # ตรวจสอบว่าถ้าย้ายบรรทัดนี้แล้ว รถต้นทางจะไม่ลดต่ำเกิน 90%
                if (current_daily_vol - cand_vol) >= car_target_min_vol:
                    # ตรวจสอบว่าถ้าย้ายแล้ว รถคันใหม่จะไม่เกิน 93%
                    if (new_car_current_vol + cand_vol) <= new_car_target_max:
                        df_res.loc[idx, 'เบอร์รถ'] = 'NEW-CAR-11'
                        current_daily_vol -= cand_vol
                        
                # ถ้ารถต้นทางลงมาอยู่ในช่วง 90-93% แล้ว ให้หยุดตัดคันนี้
                if car_target_min_vol <= current_daily_vol <= car_target_max_vol:
                    break

    df_res, _ = assign_vehicle_colors(df_res)
    return df_res

# 6. ประมวลผลหลักเมื่ออัปโหลดไฟล์
if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file)
        else:
            df_raw = pd.read_excel(uploaded_file)
            
        df, rgb_map = process_data(df_raw, target_year, target_month)
        all_cars = sorted(df['เบอร์รถ'].astype(str).unique())
        
        tab1, tab2, tab3 = st.tabs(["📊 สรุปกำลังส่งรายรถ & แผนที่สีพิกัด", "⚡ จัดสายส่งใหม่ (3 ทางเลือก)", "📥 สรุปและ Export ข้อมูล"])
        
        # TAB 1: สรุปและแผนที่หลัก
        with tab1:
            st.subheader("📌 สรุปกำลังส่งเฉลี่ยต่อวันเทียบเปอร์เซ็นต์ (% Utilization)")
            veh_summary = calculate_vehicle_utilization(df, target_year, target_month)
            st.dataframe(veh_summary, use_container_width=True)
            
            st.divider()
            st.subheader("🗺️ แผนที่พิกัดส่งน้ำดื่ม (ประมวลผลความเร็วสูงพิเศษ WebGL)")
            
            selected_cars_tab1 = st.multiselect(
                "🎨 เลือกเบอร์รถเพื่อเน้นแสดงผลพิกัดบนแผนที่:",
                options=all_cars,
                default=all_cars,
                key="tab1_car_selector"
            )
            active_cars_tab1 = selected_cars_tab1 if selected_cars_tab1 else all_cars
            
            render_fast_pydeck_map(df, active_cars_tab1)

            st.subheader("📋 ตารางรายละเอียดพิกัดงาน (พร้อมยอดส่งเฉลี่ย/วันรายบรรทัด)")
            filtered_df_tab1 = df[df['เบอร์รถ'].astype(str).isin(active_cars_tab1)]
            cols_to_show = ['รหัสสมาชิก', 'ชื่อ-นามสกุล', 'เบอร์รถ', 'รอบส่งประจำสัปดาห์', 'ยอดส่ง/เดือน', 'ยอดส่งเฉลี่ยต่อวัน_คำนวณ', 'กำลังบรรทุกต่อวัน(ถัง)', 'ที่อยู่จัดส่ง บ้านเลขที่/อาคาร', 'พิกัด Lat/Long']
            existing_cols = [c for c in cols_to_show if c in filtered_df_tab1.columns]
            render_limited_dataframe(filtered_df_tab1[existing_cols], "tab1")

        # TAB 2: จัดสายส่งใหม่
        with tab2:
            st.subheader("⚙️ เงื่อนไขการจัดสายส่งใหม่ (ควบคุม % Utilization ให้อยู่ในช่วง 90% - 93%)")
            col_a, col_b = st.columns(2)
            with col_a:
                selected_source_cars = st.multiselect("🚚 เลือกเฉพาะเบอร์รถที่จะนำมาจัดสายส่งใหม่:", options=all_cars, default=all_cars)
            with col_b:
                fix_no = st.multiselect("🔒 รหัสสมาชิกที่ไม่ยอมให้ย้าย (Fix Stay)", df['รหัสสมาชิก'].unique())
                
            col_c, col_d = st.columns(2)
            with col_c:
                fix_move = st.multiselect("🚚 รหัสสมาชิกที่บังคับย้ายไปรถคันใหม่", df['รหัสสมาชิก'].unique())
            with col_d:
                target_pct_range = st.slider("ช่วงเป้าหมาย % กำลังบรรทุกของรถคันใหม่และคันที่ถูกตัด", 85.0, 98.0, (90.0, 93.0), step=0.5)

            if st.button("🚀 ประมวลผลสร้าง 3 ทางเลือกแบบเกาะกลุ่มพื้นที่ (เป้าหมาย 90-93%)"):
                source_cars = selected_source_cars if selected_source_cars else all_cars
                min_p, max_p = target_pct_range
                
                # ทางเลือกที่ 1, 2, 3 ปรับความยืดหยุ่นของเกณฑ์ % เพื่อเสนอแนวทางที่หลากหลาย
                st.session_state['df_opt1'] = rebalance_routes_strict_utilization(df, source_cars, fix_no, fix_move, target_min_pct=min_p, target_max_pct=max_p)
                st.session_state['df_opt2'] = rebalance_routes_strict_utilization(df, source_cars, fix_no, fix_move, target_min_pct=min_p-1.0, target_max_pct=max_p)
                st.session_state['df_opt3'] = rebalance_routes_strict_utilization(df, source_cars, fix_no, fix_move, target_min_pct=min_p, target_max_pct=max_p+1.0)
                st.success("คำนวณและปรับสัดส่วนกำลังบรรทุกให้อยู่ในเกณฑ์สำเร็จ!")

            if 'df_opt1' in st.session_state:
                opt_tab1, opt_tab2, opt_tab3 = st.tabs(["ทางเลือกที่ 1 (เกณฑ์เป๊ะ 90-93%)", "ทางเลือกที่ 2 (เน้นตัดออกกระจาย)", "ทางเลือกที่ 3 (เน้นรถคันใหม่เต็มกำลัง)"])

                for idx, (tab, opt_key) in enumerate(zip([opt_tab1, opt_tab2, opt_tab3], ['df_opt1', 'df_opt2', 'df_opt3']), 1):
                    with tab:
                        current_df = st.session_state[opt_key]
                        st.dataframe(calculate_vehicle_utilization(current_df, target_year, target_month), use_container_width=True)
                        
                        all_cars_opt = sorted(current_df['เบอร์รถ'].astype(str).unique())
                        selected_cars_opt = st.multiselect(f"🎨 เลือกเบอร์รถแสดงผล (Option {idx}):", options=all_cars_opt, default=all_cars_opt, key=f"opt{idx}_selector")
                        active_cars_opt = selected_cars_opt if selected_cars_opt else all_cars_opt
                        
                        render_fast_pydeck_map(current_df, active_cars_opt)
                        
                        filtered_opt = current_df[current_df['เบอร์รถ'].astype(str).isin(active_cars_opt)]
                        render_limited_dataframe(filtered_opt[existing_cols], f"opt{idx}")
                        
                        if st.button(f"เลือกทางเลือกที่ {idx} สำหรับ Export", key=f"btn_opt{idx}"):
                            st.session_state['selected_option_df'] = current_df
                            st.success(f"บันทึกทางเลือกที่ {idx} เรียบร้อยแล้ว")

        # TAB 3: Export ข้อมูล
        with tab3:
            st.subheader("📥 Export ข้อมูล")
            final_export_df = st.session_state.get('selected_option_df', df)
            cols_to_drop = ['latitude', 'longitude', 'color_rgb']
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
