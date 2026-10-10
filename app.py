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
st.caption("ระบบบริหารจัดการและจัดสายส่งน้ำดื่มอัจฉริยะ (Fixed Vehicle Target & Intelligent Auto-Rebalance Engine)")

# 2. Sidebar สำหรับอัปโหลดไฟล์และตั้งค่า
st.sidebar.header("⚙️ ตั้งค่าข้อมูล")
uploaded_main_file = st.sidebar.file_uploader("1. อัปโหลดไฟล์รายละเอียดลูกค้า (Excel / CSV)", type=["xlsx", "csv"])
uploaded_cap_file = st.sidebar.file_uploader("2. อัปโหลดไฟล์ข้อมูลกำลังส่ง 100% ของแต่ละเบอร์รถ (.xlsx)", type=["xlsx"])

target_year = st.sidebar.number_input("ปี ค.ศ.", min_value=2024, max_value=2030, value=2026)
target_month = st.sidebar.selectbox("เดือน", range(1, 13), format_func=lambda x: calendar.month_name[x], index=7) # Default ส.ค. (8)

# ตั้งค่ากำลังส่ง 100% ต่อวันของรถคันใหม่
st.sidebar.divider()
st.sidebar.header("🚚 ตั้งค่ารถคันใหม่ (New Car)")
new_car_daily_capacity = st.sidebar.number_input(
    "กำลังส่ง 100% ต่อวันของรถคันใหม่ (ถัง/วัน):",
    min_value=50.0,
    max_value=500.0,
    value=200.0,
    step=10.0,
    help="ระบุจำนวนถังสูงสุดที่รถคันใหม่สามารถส่งได้ใน 1 วัน"
)

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

def calculate_vehicle_utilization(df, year, month, fixed_targets=None):
    if fixed_targets is None:
        fixed_targets = {}
        
    summary_list = []
    for car, group in df.groupby('เบอร์รถ'):
        total_monthly_vol = group['ยอดส่ง/เดือน'].sum()
        total_calculated_weekly_vol = group['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ'].sum() 
        max_daily_cap = group['กำลังบรรทุกต่อวัน(ถัง)'].iloc[0] if 'กำลังบรรทุกต่อวัน(ถัง)' in group.columns else 200
        max_weekly_cap = max_daily_cap * 6.0

        utilization_pct = (total_calculated_weekly_vol / max_weekly_cap) * 100 if max_weekly_cap > 0 else 0
        
        # ตรวจสอบเป้าหมายที่ถูก Fix ไว้ (ถ้ามี)
        target_val = fixed_targets.get(str(car), None)
        if target_val is not None:
            if abs(utilization_pct - target_val) <= 0.5:
                status = f'🔒 ตรงเป้าที่ Fix ไว้ ({target_val}%)'
            elif utilization_pct > target_val:
                status = f'🔴 สูงกว่าเป้าที่ Fix ({target_val}%)'
            else:
                status = f'⚠️ ต่ำกว่าเป้าที่ Fix ({target_val}%)'
        else:
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

# 4. ฟังก์ชันแผนที่ Pydeck
def render_dynamic_axis_pydeck_map(df_input, selected_cars, lat_min, lat_max, lon_min, lon_max):
    df_copy = df_input.copy()
    if 'color_rgb' not in df_copy.columns:
        df_copy, _ = assign_vehicle_colors(df_copy)
    
    def get_render_color(row):
        car_str = str(row['เบอร์รถ'])
        if car_str == 'NEW-CAR-99':
            return [255, 0, 0, 255]
        elif lat_min <= row['latitude'] <= lat_max and lon_min <= row['longitude'] <= lon_max:
            return [255, 140, 0, 240]
        elif car_str in selected_cars:
            return row['color_rgb']
        return [200, 200, 200, 40]

    df_copy['render_color'] = df_copy.apply(get_render_color, axis=1)
    df_copy['car_str'] = df_copy['เบอร์รถ'].astype(str)
    
    mean_lat = (lat_min + lat_max) / 2.0
    mean_lon = (lon_min + lon_max) / 2.0

    view_state = pdk.ViewState(latitude=mean_lat, longitude=mean_lon, zoom=11, pitch=0)

    scatter_layer = pdk.Layer(
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

    box_coords = [[lon_min, lat_min], [lon_max, lat_min], [lon_max, lat_max], [lon_min, lat_max], [lon_min, lat_min]]
    mid_lat = (lat_min + lat_max) / 2.0
    mid_lon = (lon_min + lon_max) / 2.0
    path_data = [
        {"path": box_coords, "name": "BoundingBox"},
        {"path": [[lon_min, mid_lat], [lon_max, mid_lat]], "name": "CrossLat"},
        {"path": [[mid_lon, lat_min], [mid_lon, lat_max]], "name": "CrossLon"}
    ]
    
    line_layer = pdk.Layer(
        "PathLayer",
        data=path_data,
        get_path="path",
        get_color=[255, 69, 0, 230],
        width_scale=15,
        width_min_pixels=2,
        pickable=False
    )

    tooltip = {
        "html": "<b>🚚 เบอร์รถ:</b> {car_str}<br/><b>🆔 รหัส:</b> {รหัสสมาชิก}<br/><b>👤 ชื่อ:</b> {ชื่อ-นามสกุล}<br/><b>📦 ยอด/เดือน:</b> {ยอดส่ง/เดือน} ถัง",
        "style": {"backgroundColor": "#1e293b", "color": "white", "padding": "10px", "borderRadius": "6px"}
    }

    st.pydeck_chart(pdk.Deck(layers=[line_layer, scatter_layer], initial_view_state=view_state, tooltip=tooltip, map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"))

def render_limited_dataframe(df_to_show, key_suffix):
    col_limit, _ = st.columns([1, 2])
    with col_limit:
        limit = st.selectbox("⚡ เลือกจำนวนรายการตาราง:", options=[20, 50, 100, "แสดงทั้งหมด"], index=1, key=f"row_limit_{key_suffix}")
    if limit == "แสดงทั้งหมด":
        st.dataframe(df_to_show, use_container_width=True)
    else:
        st.dataframe(df_to_show.head(limit), use_container_width=True)

# 5. ฟังก์ชันจัดสายส่งพร้อมระบบ Fix Target และ Auto-Rebalancing คันเดิมที่ถูกดึงลูกค้าออก
def process_area_selection_route(df_in, lat_min, lat_max, lon_min, lon_max, custom_daily_cap, fixed_targets=None, target_min=90.0, target_max=93.0):
    df_res = df_in.copy()
    max_daily_cap = custom_daily_cap
    max_weekly_cap = max_daily_cap * 6.0
    target_min_vol = max_weekly_cap * (target_min / 100.0)
    target_max_vol = max_weekly_cap * (target_max / 100.0)

    if fixed_targets is None:
        fixed_targets = {}

    df_res.loc[df_res['เบอร์รถ'] == 'NEW-CAR-99', 'กำลังบรรทุกต่อวัน(ถัง)'] = max_daily_cap

    # 1. บันทึกรายชื่อรถเดิมที่ได้รับผลกระทบจากการถูกดึงจุดส่งออกไป
    mask = (df_res['latitude'] >= lat_min) & (df_res['latitude'] <= lat_max) & \
           (df_res['longitude'] >= lon_min) & (df_res['longitude'] <= lon_max)
    
    selected_subset = df_res[mask].copy()
    if selected_subset.empty:
        return df_res, 0, 0, "⚠️ ไม่พบจุดพิกัดในกรอบพื้นที่ที่คุณเลือก"

    affected_cars = selected_subset['เบอร์รถ'][selected_subset['เบอร์รถ'] != 'NEW-CAR-99'].unique()

    total_vol = selected_subset['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ'].sum()
    msg = ""

    # 2. ปรับแต่งยอดของรถคันใหม่ให้อยู่ในช่วงเกณฑ์ (90-93%)
    if total_vol > target_max_vol:
        center_lat = selected_subset['latitude'].mean()
        center_lon = selected_subset['longitude'].mean()
        selected_subset['dist'] = np.sqrt((selected_subset['latitude'] - center_lat)**2 + (selected_subset['longitude'] - center_lon)**2)
        selected_subset = selected_subset.sort_values(by='dist', ascending=False)

        accumulated_vol = total_vol
        valid_indices = []
        for idx, row in selected_subset.iterrows():
            if accumulated_vol > target_max_vol:
                accumulated_vol -= row['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ']
            else:
                valid_indices.append(idx)

        df_res.loc[valid_indices, 'เบอร์รถ'] = 'NEW-CAR-99'
        df_res.loc[valid_indices, 'กำลังบรรทุกต่อวัน(ถัง)'] = max_daily_cap
        msg = f"🔴 ยอดในกรอบเกินเกณฑ์ ระบบตัดขอบนอกออกอัตโนมัติให้เหลือ {round(accumulated_vol, 2)} ถัง/สัปดาห์ (เข้าเกณฑ์ปกติ 90-93%)"

    elif total_vol < target_min_vol:
        df_res.loc[selected_subset.index, 'เบอร์รถ'] = 'NEW-CAR-99'
        df_res.loc[selected_subset.index, 'กำลังบรรทุกต่อวัน(ถัง)'] = max_daily_cap
        current_new_vol = total_vol

        outside_df = df_res[(df_res['เบอร์รถ'] != 'NEW-CAR-99') & (~df_res.index.isin(selected_subset.index))].copy()
        if not outside_df.empty:
            center_lat = selected_subset['latitude'].mean()
            center_lon = selected_subset['longitude'].mean()
            outside_df['dist'] = np.sqrt((outside_df['latitude'] - center_lat)**2 + (outside_df['longitude'] - center_lon)**2)
            outside_df = outside_df.sort_values(by='dist', ascending=True)

            for idx, row in outside_df.iterrows():
                if current_new_vol < target_min_vol:
                    vol = row['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ']
                    if (current_new_vol + vol) <= target_max_vol:
                        df_res.loc[idx, 'เบอร์รถ'] = 'NEW-CAR-99'
                        df_res.loc[idx, 'กำลังบรรทุกต่อวัน(ถัง)'] = max_daily_cap
                        current_new_vol += vol
                else:
                    break
        msg = f"⚠️ ยอดในกรอบต่ำกว่าเกณฑ์ ระบบดึงจุดใกล้เคียงมาเติมจนได้ {round(current_new_vol, 2)} ถัง/สัปดาห์"
    else:
        df_res.loc[selected_subset.index, 'เบอร์รถ'] = 'NEW-CAR-99'
        df_res.loc[selected_subset.index, 'กำลังบรรทุกต่อวัน(ถัง)'] = max_daily_cap
        msg = f"🟢 พื้นที่เลือกอยู่ในเกณฑ์ปกติ (ยอดรวม {round(total_vol, 2)} ถัง/สัปดาห์)"

    # 3. Auto-Rebalance รถคันเดิมที่ได้รับผลกระทบ (เติมจุดส่งใกล้เคียงให้ครบตามเป้า หรือตามที่ Fix ไว้)
    for car in affected_cars:
        car_group = df_res[df_res['เบอร์รถ'] == car]
        if car_group.empty:
            continue
            
        max_c = car_group['กำลังบรรทุกต่อวัน(ถัง)'].iloc[0]
        max_w = max_c * 6.0
        
        # ตรวจสอบว่าเบอร์รถนี้มีการ Fix % ไว้หรือไม่ ถ้าไม่มีใช้ช่วง 90-93%
        fixed_pct = fixed_targets.get(str(car), None)
        target_vol_car = (fixed_pct / 100.0) * max_w if fixed_pct is not None else 0.90 * max_w
        
        current_car_vol = car_group['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ'].sum()
        
        # ถ้ายอดต่ำกว่าเป้า/เกณฑ์ ให้ดึงจุดใกล้เคียงจากคันอื่นที่ยังว่างมาเติม
        if current_car_vol < target_vol_car:
            center_lat_c = car_group['latitude'].mean()
            center_lon_c = car_group['longitude'].mean()
            
            candidates = df_res[(df_res['เบอร์รถ'] != 'NEW-CAR-99') & (df_res['เบอร์รถ'] != car)].copy()
            if not candidates.empty:
                candidates['dist'] = np.sqrt((candidates['latitude'] - center_lat_c)**2 + (candidates['longitude'] - center_lon_c)**2)
                candidates = candidates.sort_values(by='dist', ascending=True)
                
                for c_idx, c_row in candidates.iterrows():
                    if current_car_vol < target_vol_car:
                        vol = c_row['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ']
                        # ตรวจสอบว่าคันต้นทางจะไม่ต่ำกว่าเกณฑ์เกินไป (หรือปล่อยให้ระบบเกลี่ย)
                        df_res.loc[c_idx, 'เบอร์รถ'] = car
                        current_car_vol += vol
                    else:
                        break

    df_res, _ = assign_vehicle_colors(df_res)
    return df_res, total_vol, max_weekly_cap, msg

# 6. ประมวลผลหลัก
if uploaded_main_file is not None and uploaded_cap_file is not None:
    try:
        if uploaded_main_file.name.endswith('.csv'):
            df_main_raw = pd.read_csv(uploaded_main_file)
        else:
            df_main_raw = pd.read_excel(uploaded_main_file)
            
        df_cap_raw = pd.read_excel(uploaded_cap_file)
            
        df, rgb_map = process_data(df_main_raw, df_cap_raw, target_year, target_month)
        all_cars = sorted(df['เบอร์รถ'].astype(str).unique())
        
        # Sidebar สำหรับตั้งค่า Fix % เฉพาะเบอร์รถ
        st.sidebar.divider()
        st.sidebar.header("📌 ตั้งค่า Fix % เป้าหมายรถแต่ละคัน")
        fixed_targets_dict = {}
        for car in all_cars:
            use_fix = st.sidebar.checkbox(f"Fix % รถเบอร์ {car}", value=False, key=f"fix_chk_{car}")
            if use_fix:
                val = st.sidebar.number_input(f"เป้าหมาย % รถ {car}", min_value=50.0, max_value=100.0, value=91.0, step=1.0, key=f"fix_val_{car}")
                fixed_targets_dict[str(car)] = val

        tab1, tab2, tab3 = st.tabs(["📊 สรุปกำลังส่งรายรถ & แผนที่ภาพรวม", "⚡ จัดสายส่งใหม่ & Auto-Rebalance", "📥 สรุปและExport ข้อมูล"])
        
        with tab1:
            st.subheader(f"📌 สรุปกำลังส่งรายสัปดาห์เทียบเปอร์เซ็นต์ (% Utilization) [เดือน {calendar.month_name[target_month]} {target_year}]")
            veh_summary = calculate_vehicle_utilization(df, target_year, target_month, fixed_targets_dict)
            st.dataframe(veh_summary, use_container_width=True)
            
            st.divider()
            st.subheader("🗺️ แผนที่พิกัดส่งน้ำดื่มภาพรวม")
            selected_cars_tab1 = st.multiselect("🎨 เลือกเบอร์รถแสดงผล:", options=all_cars, default=all_cars, key="tab1_car_selector")
            active_cars_tab1 = selected_cars_tab1 if selected_cars_tab1 else all_cars
            
            def render_fast_pydeck_map(df_input, selected_cars):
                df_copy = df_input.copy()
                if 'color_rgb' not in df_copy.columns:
                    df_copy, _ = assign_vehicle_colors(df_copy)
                def get_render_color(row):
                    return row['color_rgb'] if str(row['เบอร์รถ']) in selected_cars else [210, 210, 210, 100]
                df_copy['render_color'] = df_copy.apply(get_render_color, axis=1)
                df_copy['car_str'] = df_copy['เบอร์รถ'].astype(str)
                view_state = pdk.ViewState(latitude=df_copy['latitude'].mean(), longitude=df_copy['longitude'].mean(), zoom=11, pitch=0)
                layer = pdk.Layer("ScatterplotLayer", data=df_copy, get_position=["longitude", "latitude"], get_fill_color="render_color", get_radius=120, pickable=True, opacity=0.9, stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=1)
                tooltip = {"html": "<b>🚚 เบอร์รถ:</b> {car_str}<br/><b>🆔 รหัส:</b> {รหัสสมาชิก}<br/><b>👤 ชื่อ:</b> {ชื่อ-นามสกุล}<br/><b>📦 ยอด/เดือน:</b> {ยอดส่ง/เดือน} ถัง", "style": {"backgroundColor": "#1e293b", "color": "white", "padding": "10px", "borderRadius": "6px"}}
                st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip=tooltip, map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"))

            render_fast_pydeck_map(df, active_cars_tab1)

        with tab2:
            st.subheader("🗺️ จัดสายส่งใหม่พร้อมระบบ Auto-Rebalance และ Fix Target")
            
            lat_min_data = float(df['latitude'].min())
            lat_max_data = float(df['latitude'].max())
            lon_min_data = float(df['longitude'].min())
            lon_max_data = float(df['longitude'].max())

            if 'lat_range_val' not in st.session_state:
                st.session_state['lat_range_val'] = (lat_min_data + 0.03, lat_max_data - 0.03)
            if 'lon_range_val' not in st.session_state:
                st.session_state['lon_range_val'] = (lon_min_data + 0.03, lon_max_data - 0.03)

            col_btn1, col_btn2 = st.columns([4, 1])
            with col_btn2:
                if st.button("🔄 รีเซ็ตกรอบพื้นที่"):
                    st.session_state['lat_range_val'] = (lat_min_data + 0.03, lat_max_data - 0.03)
                    st.session_state['lon_range_val'] = (lon_min_data + 0.03, lon_max_data - 0.03)
                    st.rerun()

            col_lat1, col_lat2 = st.columns(2)
            with col_lat1:
                lat_range = st.slider(f"🌐 ช่วงละติจูด ({lat_min_data:.4f} - {lat_max_data:.4f}):", lat_min_data, lat_max_data, st.session_state['lat_range_val'], step=0.001, key="lat_slider")
                st.session_state['lat_range_val'] = lat_range
            with col_lat2:
                lon_range = st.slider(f"🌐 ช่วงลองจิจูด ({lon_min_data:.4f} - {lon_max_data:.4f}):", lon_min_data, lon_max_data, st.session_state['lon_range_val'], step=0.001, key="lon_slider")
                st.session_state['lon_range_val'] = lon_range

            preview_subset = df[(df['latitude'] >= lat_range[0]) & (df['latitude'] <= lat_range[1]) & 
                                (df['longitude'] >= lon_range[0]) & (df['longitude'] <= lon_range[1])]
            
            preview_total_vol = preview_subset['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ'].sum() if not preview_subset.empty else 0.0
            max_weekly_target = new_car_daily_capacity * 6.0
            preview_util_pct = (preview_total_vol / max_weekly_target) * 100 if max_weekly_target > 0 else 0.0

            st.markdown("---")
            col_p1, col_p2, col_p3 = st.columns(3)
            col_p1.metric("📍 จุดส่งในกรอบ", f"{len(preview_subset):,} จุด")
            col_p2.metric("📦 ยอดส่งรวมในกรอบ", f"{round(preview_total_vol, 2):,} ถัง/สัปดาห์")
            col_p3.metric("🎯 % Utilization (พรีวิว)", f"{round(preview_util_pct, 2)}%")

            if not preview_subset.empty:
                car_breakdown = preview_subset.groupby('เบอร์รถ').agg(
                    จำนวนลูกค้า=('รหัสสมาชิก', 'count'),
                    ยอดส่งรวม=('ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ', 'sum')
                ).reset_index()
                st.markdown("🚚 **พิกัดในกรอบนี้เดิมเป็นของรถคันอ้างอิง:**")
                st.dataframe(car_breakdown, use_container_width=True)

            st.markdown("---")
            render_dynamic_axis_pydeck_map(df, all_cars, lat_range[0], lat_range[1], lon_range[0], lon_range[1])

            if st.button("🚀 ประมวลผลสร้างสายส่งใหม่ & Auto-Rebalance รถคันเดิมอัตโนมัติ"):
                new_df, tot_vol, max_cap, result_msg = process_area_selection_route(df, lat_range[0], lat_range[1], lon_range[0], lon_range[1], new_car_daily_capacity, fixed_targets_dict)
                st.session_state['df_area_opt'] = new_df
                st.success(result_msg)

            if 'df_area_opt' in st.session_state:
                st.divider()
                st.subheader("📋 สรุปแผนที่และผลลัพธ์สายส่งใหม่ทั้งหมด")
                current_area_df = st.session_state['df_area_opt']
                
                st.dataframe(calculate_vehicle_utilization(current_area_df, target_year, target_month, fixed_targets_dict), use_container_width=True)
                
                all_cars_opt = sorted(current_area_df['เบอร์รถ'].astype(str).unique())
                selected_cars_opt = st.multiselect("🎨 เลือกเบอร์รถแสดงผลบนแผนที่ภาพรวมใหม่:", options=all_cars_opt, default=all_cars_opt, key="opt_area_selector")
                active_cars_opt = selected_cars_opt if selected_cars_opt else all_cars_opt
                
                render_dynamic_axis_pydeck_map(current_area_df, active_cars_opt, lat_range[0], lat_range[1], lon_range[0], lon_range[1])
                
                filtered_opt = current_area_df[current_area_df['เบอร์รถ'].astype(str).isin(active_cars_opt)]
                cols_to_show = ['รหัสสมาชิก', 'ชื่อ-นามสกุล', 'เบอร์รถ', 'รอบส่งประจำสัปดาห์', 'ยอดส่ง/เดือน', 'ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ', 'กำลังบรรทุกต่อวัน(ถัง)', 'ที่อยู่จัดส่ง บ้านเลขที่/อาคาร', 'พิกัด Lat/Long']
                existing_cols = [c for c in cols_to_show if c in filtered_opt.columns]
                render_limited_dataframe(filtered_opt[existing_cols], "area_opt")
                
                if st.button("💾 บันทึกผลลัพธ์นี้สำหรับ Export ข้อมูล"):
                    st.session_state['selected_option_df'] = current_area_df
                    st.success("บันทึกข้อมูลสายส่งใหม่เรียบร้อยแล้ว ไปที่ Tab 3 เพื่อดาวน์โหลดได้ทันที")

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
