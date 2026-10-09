import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import calendar
import io

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
uploaded_main_file = st.sidebar.file_uploader("1. อัปโหลดไฟล์รายละเอียดลูกค้า (Excel / CSV)", type=["xlsx", "csv"])
uploaded_cap_file = st.sidebar.file_uploader("2. อัปโหลดไฟล์ข้อมูลกำลังส่ง 100% ของแต่ละเบอร์รถ (.xlsx)", type=["xlsx"])

target_year = st.sidebar.number_input("ปี ค.ศ.", min_value=2024, max_value=2030, value=2026)
target_month = st.sidebar.selectbox("เดือน", range(1, 13), format_func=lambda x: calendar.month_name[x], index=7) # Default ส.ค. (8)

# Map วันในภาษาไทย (ตัดวันอาทิตย์ออก)
DAY_MAP = {
    'จันทร์': 0, 'จ': 0,
    'อังคาร': 1, 'อ': 1,
    'พุธ': 2, 'พ': 2,
    'พฤหัสบดี': 3, 'พฤหัส': 3, 'พฤ': 3,
    'ศุกร์': 4, 'ศ': 4,
    'เสาร์': 5, 'ส': 5
}

@st.cache_data
def get_days_count_in_month(year, month):
    cal = calendar.monthcalendar(year, month)
    counts = {}
    total_working_days = 0
    for week in cal:
        for i, day in enumerate(week):
            if day != 0 and i != 6:
                total_working_days += 1

    for day_name, day_idx in DAY_MAP.items():
        if len(day_name) > 1 and day_name not in ['พฤหัส', 'พฤ']:
            cnt = sum(1 for week in cal if week[day_idx] != 0)
            counts[day_name] = cnt if cnt > 0 else 4
            
    counts['TOTAL_WORKING_DAYS'] = total_working_days if total_working_days > 0 else 26
    return counts

@st.cache_data
def assign_vehicle_colors(df):
    unique_cars = sorted(df['เบอร์รถ'].astype(str).unique())
    rgb_palette = [
        [31, 119, 180], [255, 127, 14], [44, 160, 44], [214, 39, 40],
        [148, 103, 189], [140, 86, 75], [227, 119, 194], [23, 190, 207],
        [188, 189, 34], [127, 127, 127], [255, 152, 150], [174, 199, 232]
    ]
    rgb_map = {car: rgb_palette[i % len(rgb_palette)] for i, car in enumerate(unique_cars)}
    df['color_rgb'] = df['เบอร์รถ'].astype(str).map(rgb_map)
    return df, rgb_map

# 3. ฟังก์ชันคำนวณยอดส่งต่อสัปดาห์ระดับบรรทัด
def calculate_row_weekly_volume(row, day_counts):
    monthly_vol = float(row.get('ยอดส่ง/เดือน', 0))
    if monthly_vol <= 0:
        return 0.0

    raw_schedule = str(row.get('รอบส่งประจำสัปดาห์', '')).strip()
    total_working_days = day_counts.get('TOTAL_WORKING_DAYS', 26)
    
    if not raw_schedule or raw_schedule.lower() == 'nan':
        weekly_vol = (monthly_vol / total_working_days) * 6.0
        return round(weekly_vol, 2)

    found_days = []
    for day_name in DAY_MAP.keys():
        if day_name in raw_schedule:
            std_name = 'พฤหัสบดี' if day_name in ['พฤหัสบดี', 'พฤหัส', 'พฤ'] else (
                       'จันทร์' if day_name in ['จันทร์', 'จ'] else (
                       'อังคาร' if day_name in ['อังคาร', 'อ'] else (
                       'พุธ' if day_name in ['พุธ', 'พ'] else (
                       'ศุกร์' if day_name in ['ศุกร์', 'ศ'] else 'เสาร์'))))
            if std_name not in found_days:
                found_days.append(std_name)

    if not found_days:
        weekly_vol = (monthly_vol / total_working_days) * 6.0
        return round(weekly_vol, 2)

    avg_days_in_month = sum(day_counts.get(day, 4) for day in found_days) / len(found_days)
    if avg_days_in_month <= 0:
        avg_days_in_month = 4.0

    weekly_vol = monthly_vol / avg_days_in_month
    return round(weekly_vol, 2)

@st.cache_data
def process_data(df_main, df_cap, year, month):
    df = df_main.copy()
    df['ยอดส่ง/เดือน'] = pd.to_numeric(df.get('ยอดส่ง/เดือน', 0), errors='coerce').fillna(0)
    
    if df_cap is not None:
        if 'กำลังส่ง' in df_cap.columns and 'เบอร์รถ' in df_cap.columns:
            df_cap['เบอร์รถ_str'] = df_cap['เบอร์รถ'].astype(str)
            df['เบอร์รถ_str'] = df['เบอร์รถ'].astype(str)
            df = pd.merge(df, df_cap[['เบอร์รถ_str', 'กำลังส่ง']], on='เบอร์รถ_str', how='left')
            df.rename(columns={'กำลังส่ง': 'กำลังบรรทุกต่อวัน(ถัง)'}, inplace=True)
            df.drop(columns=['เบอร์รถ_str'], inplace=True, errors='ignore')
            
    df['กำลังบรรทุกต่อวัน(ถัง)'] = pd.to_numeric(df.get('กำลังบรรทุกต่อวัน(ถัง)', 200), errors='coerce').fillna(200)

    if 'พิกัด Lat/Long' in df.columns:
        coords = df['พิกัด Lat/Long'].astype(str).str.split(',', expand=True)
        df['latitude'] = pd.to_numeric(coords[0].str.strip(), errors='coerce').fillna(13.7563)
        df['longitude'] = pd.to_numeric(coords[1].str.strip(), errors='coerce').fillna(100.5018)
    else:
        df['latitude'] = 13.7563
        df['longitude'] = 100.5018

    day_counts = get_days_count_in_month(year, month)
    df['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ'] = df.apply(lambda r: calculate_row_weekly_volume(r, day_counts), axis=1)

    df, rgb_map = assign_vehicle_colors(df)
    return df, rgb_map

@st.cache_data
def calculate_vehicle_utilization(df, year, month):
    summary_list = []
    for car, group in df.groupby('เบอร์รถ'):
        total_monthly_vol = group['ยอดส่ง/เดือน'].sum()
        total_calculated_weekly_vol = group['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ'].sum() 
        max_daily_cap = group['กำลังบรรทุกต่อวัน(ถัง)'].iloc[0] if 'กำลังบรรทุกต่อวัน(ถัง)' in group.columns else 200
        max_weekly_cap = max_daily_cap * 6.0

        utilization_pct = (total_calculated_weekly_vol / max_weekly_cap) * 100 if max_weekly_cap > 0 else 0
        
        if utilization_pct > 93:
            status = '🔴 เกินเกณฑ์ (>93%)'
        elif 90 <= utilization_pct <= 93:
            status = '🟢 เกณฑ์ปกติ (90-93%)'
        else:
            status = '⚠️ ต่ำกว่าเกณฑ์ (<90%)'
        
        summary_list.append({
            'เบอร์รถ': car,
            'จำนวนจุดส่ง (บรรทัด)': len(group),
            'ยอดรวมส่งทั้งเดือน (ถัง)': total_monthly_vol,
            'ยอดส่งเฉลี่ยต่อสัปดาห์รวม (ถัง)': round(total_calculated_weekly_vol, 2),
            'กำลังบรรทุก 100% ต่อวัน (ถัง)': max_daily_cap,
            'กำลังบรรทุก 100% ต่อสัปดาห์ (ถัง)': max_weekly_cap,
            '% การใช้งานกำลังบรรทุก (% Utilization)': round(utilization_pct, 2),
            'สถานะ': status
        })
    return pd.DataFrame(summary_list)

# 4. ฟังก์ชันแสดงแผนที่ Pydeck แบบมีความละเอียดสูง มีแผนที่พื้นหลัง ซูม/เลื่อนได้สมบูรณ์
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
        get_radius=120,
        pickable=True,
        opacity=0.9,
        stroked=True,
        get_line_color=[255, 255, 255],
        line_width_min_pixels=1,
    )

    tooltip = {
        "html": "<b>🚚 เบอร์รถ:</b> {car_str}<br/>"
                "<b>🆔 รหัสสมาชิก:</b> {รหัสสมาชิก}<br/>"
                "<b>👤 ชื่อ:</b> {ชื่อ-นามสกุล}<br/>"
                "<b>📦 ยอดส่งต่อเดือน:</b> {ยอดส่ง/เดือน} ถัง<br/>"
                "<b>⚡ ยอดส่งเฉลี่ย/สัปดาห์:</b> {ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ} ถัง/สัปดาห์",
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
        st.caption(f"⚡ แสดง {limit} รายการแรกเพื่อความรวดเร็ว")

# 5. ฟังก์ชันจัดสายส่งใหม่โดยอ้างอิงพื้นที่ใกล้เคียงเบอร์รถเดิมหรือสมาชิกรายอื่น
def rebalance_routes_strict_utilization(df_in, target_cars, fix_stay_ids, fix_move_ids, reference_type, reference_value, target_min_pct=90.0, target_max_pct=93.0, new_car_capacity=200.0):
    df_res = df_in.copy()
    
    if fix_move_ids:
        df_res.loc[df_res['รหัสสมาชิก'].isin(fix_move_ids), 'เบอร์รถ'] = 'NEW-CAR-99'

    max_weekly_cap = new_car_capacity * 6.0
    new_car_target_min = max_weekly_cap * (target_min_pct / 100.0)
    new_car_target_max = max_weekly_cap * (target_max_pct / 100.0)

    ref_center = None
    if reference_type == "อ้างอิงตามพื้นที่เบอร์รถเดิม" and reference_value:
        ref_rows = df_res[df_res['เบอร์รถ'].astype(str) == str(reference_value)]
        if not ref_rows.empty:
            ref_center = ref_rows[['latitude', 'longitude']].values.mean(axis=0)
    elif reference_type == "อ้างอิงตามพิกัดรหัสสมาชิกรายใดรายหนึ่ง" and reference_value:
        ref_rows = df_res[df_res['รหัสสมาชิก'].astype(str) == str(reference_value)]
        if not ref_rows.empty:
            ref_center = ref_rows[['latitude', 'longitude']].values[0]

    for car in target_cars:
        car_rows = df_res[df_res['เบอร์รถ'].astype(str) == str(car)]
        if car_rows.empty:
            continue
            
        car_cap_daily = car_rows['กำลังบรรทุกต่อวัน(ถัง)'].iloc[0] if 'กำลังบรรทุกต่อวัน(ถัง)' in car_rows.columns else 200.0
        car_weekly_cap = car_cap_daily * 6.0
        car_target_max_vol = car_weekly_cap * (target_max_pct / 100.0)
        car_target_min_vol = car_weekly_cap * (target_min_pct / 100.0)

        current_weekly_vol = car_rows['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ'].sum()
        
        if current_weekly_vol > car_target_max_vol:
            eligible_candidates = car_rows[~car_rows['รหัสสมาชิก'].isin(fix_stay_ids)].copy()
            if eligible_candidates.empty:
                continue

            if ref_center is not None:
                coords = eligible_candidates[['latitude', 'longitude']].values
                eligible_candidates['dist_to_ref'] = np.linalg.norm(coords - ref_center, axis=1)
                eligible_candidates = eligible_candidates.sort_values(by='dist_to_ref', ascending=True)
            else:
                if len(eligible_candidates) >= 2:
                    coords = eligible_candidates[['latitude', 'longitude']].values
                    center = coords.mean(axis=0)
                    eligible_candidates['dist_to_center'] = np.linalg.norm(coords - center, axis=1)
                    eligible_candidates = eligible_candidates.sort_values(by='dist_to_center', ascending=False)

            for idx, candidate in eligible_candidates.iterrows():
                new_car_current_vol = df_res[df_res['เบอร์รถ'] == 'NEW-CAR-99']['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ'].sum()
                
                if new_car_current_vol >= new_car_target_max:
                    break
                    
                cand_vol = candidate['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ']
                
                if (current_weekly_vol - cand_vol) >= car_target_min_vol:
                    if (new_car_current_vol + cand_vol) <= new_car_target_max:
                        df_res.loc[idx, 'เบอร์รถ'] = 'NEW-CAR-99'
                        current_weekly_vol -= cand_vol
                        
                if car_target_min_vol <= current_weekly_vol <= car_target_max_vol:
                    break

    df_res, _ = assign_vehicle_colors(df_res)
    return df_res

# 6. ประมวลผลหลักเมื่ออัปโหลดไฟล์
if uploaded_main_file is not None and uploaded_cap_file is not None:
    try:
        if uploaded_main_file.name.endswith('.csv'):
            df_main_raw = pd.read_csv(uploaded_main_file)
        else:
            df_main_raw = pd.read_excel(uploaded_main_file)
            
        df_cap_raw = pd.read_excel(uploaded_cap_file)
            
        df, rgb_map = process_data(df_main_raw, df_cap_raw, target_year, target_month)
        all_cars = sorted(df['เบอร์รถ'].astype(str).unique())
        
        tab1, tab2, tab3 = st.tabs(["📊 สรุปกำลังส่งรายรถ & แผนที่ภาพรวม", "⚡ จัดสายส่งใหม่ (เลือกพื้นที่อ้างอิง)", "📥 สรุปและExport ข้อมูล"])
        
        # TAB 1: สรุปและแผนที่หลัก
        with tab1:
            st.subheader(f"📌 สรุปกำลังส่งรายสัปดาห์เทียบเปอร์เซ็นต์ (% Utilization) [เดือน {calendar.month_name[target_month]} {target_year}]")
            veh_summary = calculate_vehicle_utilization(df, target_year, target_month)
            st.dataframe(veh_summary, use_container_width=True)
            
            over_limit_cars = veh_summary[veh_summary['% การใช้งานกำลังบรรทุก (% Utilization)'] > 93]['เบอร์รถ'].tolist()
            if over_limit_cars:
                st.warning(f"🚨 รถที่มียอดส่งเกินเกณฑ์ (>93%) ได้แก่: {', '.join(map(str, over_limit_cars))}")
            else:
                st.success("✅ ทุกคันอยู่ในเกณฑ์ปกติหรือต่ำกว่าเกณฑ์")
            
            st.divider()
            st.subheader("🗺️ แผนที่พิกัดส่งน้ำดื่ม (WebGL Engine - รองรับซูม เลื่อน พื้นหลังคมชัด)")
            selected_cars_tab1 = st.multiselect("🎨 เลือกเบอร์รถแสดงผล:", options=all_cars, default=all_cars, key="tab1_car_selector")
            active_cars_tab1 = selected_cars_tab1 if selected_cars_tab1 else all_cars
            render_fast_pydeck_map(df, active_cars_tab1)

        # TAB 2: จัดสายส่งใหม่
        with tab2:
            st.subheader("⚙️ เงื่อนไขการจัดสายส่งใหม่ (ควบคุม % Utilization ให้อยู่ในช่วง 90% - 93%)")
            
            st.markdown("📍 **กำหนดจุดศูนย์กลาง / พื้นที่เป้าหมายของสายส่งใหม่ (รถคันใหม่ NEW-CAR-99)**")
            ref_col1, ref_col2 = st.columns(2)
            with ref_col1:
                ref_type = st.radio(
                    "เลือกรูปแบบการอ้างอิงพื้นที่สำหรับสายส่งใหม่:",
                    options=["อ้างอิงตามพื้นที่เบอร์รถเดิม", "อ้างอิงตามพิกัดรหัสสมาชิกรายใดรายหนึ่ง"]
                )
            with ref_col2:
                if ref_type == "อ้างอิงตามพื้นที่เบอร์รถเดิม":
                    ref_val = st.selectbox("เลือกเบอร์รถต้นแบบที่ต้องการให้สายส่งใหม่อยู่ใกล้พื้นที่:", options=all_cars)
                else:
                    ref_val = st.selectbox("เลือกรหัสสมาชิก / ลูกค้าต้นแบบ:", options=df['รหัสสมาชิก'].unique())

            st.divider()
            col_a, col_b = st.columns(2)
            with col_a:
                selected_source_cars = st.multiselect("🚚 เลือกเฉพาะเบอร์รถที่จะนำมาจัดสายส่งใหม่:", options=all_cars, default=over_limit_cars if over_limit_cars else all_cars, key="source_cars_tab2")
            with col_b:
                fix_no = st.multiselect("🔒 รหัสสมาชิกที่ไม่ยอมให้ย้าย (Fix Stay)", df['รหัสสมาชิก'].unique(), key="fix_stay_tab2")
                
            col_c, col_d = st.columns(2)
            with col_c:
                fix_move = st.multiselect("🚚 รหัสสมาชิกที่บังคับย้ายไปรถคันใหม่", df['รหัสสมาชิก'].unique(), key="fix_move_tab2")
            with col_d:
                target_pct_range = st.slider("ช่วงเป้าหมาย % กำลังบรรทุกของรถคันใหม่และคันที่ถูกตัด", 85.0, 98.0, (90.0, 93.0), step=0.5, key="slider_tab2")

            if st.button("🚀 ประมวลผลสร้าง 3 ทางเลือกตามพื้นที่อ้างอิง (เป้าหมาย 90-93%)"):
                source_cars = selected_source_cars if selected_source_cars else all_cars
                min_p, max_p = target_pct_range
                
                st.session_state['df_opt1'] = rebalance_routes_strict_utilization(df, source_cars, fix_no, fix_move, ref_type, ref_val, target_min_pct=min_p, target_max_pct=max_p)
                st.session_state['df_opt2'] = rebalance_routes_strict_utilization(df, source_cars, fix_no, fix_move, ref_type, ref_val, target_min_pct=min_p-1.0, target_max_pct=max_p)
                st.session_state['df_opt3'] = rebalance_routes_strict_utilization(df, source_cars, fix_no, fix_move, ref_type, ref_val, target_min_pct=min_p, target_max_pct=max_p+1.0)
                st.success("คำนวณและปรับสัดส่วนกำลังบรรทุกตามพื้นที่อ้างอิงสำเร็จ!")

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
                        render_limited_dataframe(filtered_opt[existing_cols] if 'existing_cols' in locals() else filtered_opt, f"opt{idx}")
                        
                        if st.button(f"เลือกทางเลือกที่ {idx} สำหรับ Export", key=f"btn_opt{idx}"):
                            st.session_state['selected_option_df'] = current_df
                            st.success(f"บันทึกทางเลือกที่ {idx} เรียบร้อยแล้ว")

        # TAB 3: Export ข้อมูล
        with tab3:
            st.subheader("📥 Export ข้อมูลแผนงานจัดสายส่ง")
            final_export_df = st.session_state.get('selected_option_df', df)
            cols_to_drop = ['latitude', 'longitude', 'color_rgb']
            clean_export_df = final_export_df.drop(columns=[c for c in cols_to_drop if c in final_export_df.columns])

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                clean_export_df.to_excel(writer, index=False, sheet_name='Sprinkle_Route_Plan')
            
            st.download_button(
                label="🟢 ดาวน์โหลดไฟล์ Excel แผนงานจัดสายส่ง (Sprinkle Route Plan)",
                data=output.getvalue(),
                file_name=f'Sprinkle_Route_Plan_{target_year}_{target_month}.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการประมวลผล: {e}")
else:
    st.info("👈 กรุณาอัปโหลดทั้ง **ไฟล์รายละเอียดลูกค้า** และ **ไฟล์ข้อมูลกำลังส่ง 100%** ที่แถบด้านซ้ายมือเพื่อเริ่มใช้งานระบบ")
