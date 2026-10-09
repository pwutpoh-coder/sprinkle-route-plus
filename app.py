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
st.caption("ระบบบริหารจัดการและจัดสายส่งน้ำดื่มอัจฉริยะ (Ultra High-Performance WebGL Engine with Live Area Preview)")

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
    help="ระบุจำนวนถังสูงสุดที่รถคันใหม่สามารถส่งได้ใน 1 วัน เพื่อใช้คำนวณเป้าหมาย % Utilization (90-93%)"
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

# 4. ฟังก์ชันแสดงแผนที่ Pydeck ที่คมชัด ซูม เลื่อน และแสดงกรอบพื้นที่ (Bounding Box Guide Lines)
def render_dynamic_axis_pydeck_map(df_input, selected_cars, lat_min, lat_max, lon_min, lon_max):
    df_copy = df_input.copy()
    if 'color_rgb' not in df_copy.columns:
        df_copy, _ = assign_vehicle_colors(df_copy)
    
    def get_render_color(row):
        car_str = str(row['เบอร์รถ'])
        if lat_min <= row['latitude'] <= lat_max and lon_min <= row['longitude'] <= lon_max:
            return [255, 0, 0, 240] # จุดภายในกรอบ Lat/Long (สีแดงเด่นชัด)
        elif car_str in selected_cars:
            return row['color_rgb']
        return [200, 200, 200, 40]

    df_copy['render_color'] = df_copy.apply(get_render_color, axis=1)
    df_copy['car_str'] = df_copy['เบอร์รถ'].astype(str)
    
    mean_lat = (lat_min + lat_max) / 2.0
    mean_lon = (lon_min + lon_max) / 2.0

    view_state = pdk.ViewState(
        latitude=mean_lat,
        longitude=mean_lon,
        zoom=11,
        pitch=0
    )

    # 1. เลเยอร์จุดพิกัด
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

    # 2. เลเยอร์เส้นกรอบพื้นที่ (Bounding Box Guide Lines)
    box_coords = [
        [lon_min, lat_min],
        [lon_max, lat_min],
        [lon_max, lat_max],
        [lon_min, lat_max],
        [lon_min, lat_min]
    ]
    
    mid_lat = (lat_min + lat_max) / 2.0
    mid_lon = (lon_min + lon_max) / 2.0
    cross_lat_path = [[lon_min, mid_lat], [lon_max, mid_lat]]
    cross_lon_path = [[mid_lon, lat_min], [mid_lon, lat_max]]

    path_data = [
        {"path": box_coords, "name": "BoundingBox"},
        {"path": cross_lat_path, "name": "CrossLat"},
        {"path": cross_lon_path, "name": "CrossLon"}
    ]
    
    line_layer = pdk.Layer(
        "PathLayer",
        data=path_data,
        get_path="path",
        get_color=[255, 102, 0, 220],
        width_scale=15,
        width_min_pixels=2,
        pickable=False
    )

    tooltip = {
        "html": "<b>🚚 เบอร์รถ:</b> {car_str}<br/>"
                "<b>🆔 รหัสสมาชิก:</b> {รหัสสมาชิก}<br/>"
                "<b>👤 ชื่อ:</b> {ชื่อ-นามสกุล}<br/>"
                "<b>📍 Lat/Long:</b> {latitude}, {longitude}<br/>"
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
            layers=[line_layer, scatter_layer],
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

# 5. ฟังก์ชันจัดสายส่งใหม่ด้วยการเลือกพื้นที่ (Bounding Box Selection) พร้อมคำนวณเทียบเป้าหมาย
def process_area_selection_route(df_in, lat_min, lat_max, lon_min, lon_max, custom_daily_cap, target_min=90.0, target_max=93.0):
    df_res = df_in.copy()
    max_daily_cap = custom_daily_cap
    max_weekly_cap = max_daily_cap * 6.0
    target_min_vol = max_weekly_cap * (target_min / 100.0)
    target_max_vol = max_weekly_cap * (target_max / 100.0)

    df_res.loc[df_res['เบอร์รถ'] == 'NEW-CAR-99', 'กำลังบรรทุกต่อวัน(ถัง)'] = max_daily_cap

    mask = (df_res['latitude'] >= lat_min) & (df_res['latitude'] <= lat_max) & \
           (df_res['longitude'] >= lon_min) & (df_res['longitude'] <= lon_max)
    
    selected_subset = df_res[mask].copy()
    if selected_subset.empty:
        return df_res, 0, 0, "⚠️ ไม่พบจุดพิกัดในกรอบพื้นที่ที่คุณเลือก กรุณาปรับขยายสเกล Lat/Lon ให้ครอบคลุมจุดส่ง"

    total_vol = selected_subset['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ'].sum()
    msg = ""

    if total_vol > target_max_vol:
        center_lat = selected_subset['latitude'].mean()
        center_lon = selected_subset['longitude'].mean()
        selected_subset['dist_from_center'] = np.sqrt((selected_subset['latitude'] - center_lat)**2 + (selected_subset['longitude'] - center_lon)**2)
        selected_subset = selected_subset.sort_values(by='dist_from_center', ascending=False)

        accumulated_vol = total_vol
        valid_indices = []
        dropped_indices = []

        for idx, row in selected_subset.iterrows():
            if accumulated_vol > target_max_vol:
                accumulated_vol -= row['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ']
                dropped_indices.append(idx)
            else:
                valid_indices.append(idx)

        df_res.loc[valid_indices, 'เบอร์รถ'] = 'NEW-CAR-99'
        df_res.loc[valid_indices, 'กำลังบรรทุกต่อวัน(ถัง)'] = max_daily_cap
        
        pct_util = round((accumulated_vol / max_weekly_cap) * 100, 2)
        msg = f"⚠️ พื้นที่เลือกมียอดส่งเกินเกณฑ์ (>93%) ระบบตัดขอบนอกออกอัตโนมัติ คงเหลือ {round(accumulated_vol, 2)} ถัง/สัปดาห์ (คิดเป็น {pct_util}%) เข้าสู่เกณฑ์ปกติ"
        
        for drop_idx in dropped_indices:
            drop_row = df_res.loc[drop_idx]
            other_cars = df_res[df_res['เบอร์รถ'] != 'NEW-CAR-99']
            if not other_cars.empty:
                dists = np.sqrt((other_cars['latitude'] - drop_row['latitude'])**2 + (other_cars['longitude'] - drop_row['longitude'])**2)
                nearest_car = other_cars.loc[dists.idxmin(), 'เบอร์รถ']
                df_res.loc[drop_idx, 'เบอร์รถ'] = nearest_car

    elif total_vol < target_min_vol:
        pct_util_initial = round((total_vol / max_weekly_cap) * 100, 2)
        msg = f"⚠️ ยอดส่งต่ำกว่าเกณฑ์ (<90% โดยมียอด {round(total_vol, 2)} ถัง/สัปดาห์ คิดเป็น {pct_util_initial}%) ระบบกำลังดึงจุดส่งรอบข้างที่ใกล้ที่สุดมาเติมให้ครบช่วง 90-93%..."
        
        df_res.loc[selected_subset.index, 'เบอร์รถ'] = 'NEW-CAR-99'
        df_res.loc[selected_subset.index, 'กำลังบรรทุกต่อวัน(ถัง)'] = max_daily_cap
        current_new_vol = total_vol

        outside_df = df_res[df_res['เบอร์รถ'] != 'NEW-CAR-99'].copy()
        if not outside_df.empty:
            center_lat = selected_subset['latitude'].mean()
            center_lon = selected_subset['longitude'].mean()
            outside_df['dist'] = np.sqrt((outside_df['latitude'] - center_lat)**2 + (outside_df['longitude'] - center_lon)**2)
            outside_df = outside_df.sort_values(by='dist', ascending=True)

            added_count = 0
            for idx, row in outside_df.iterrows():
                if current_new_vol < target_min_vol:
                    vol = row['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ']
                    if current_new_vol + vol <= target_max_vol:
                        df_res.loc[idx, 'เบอร์รถ'] = 'NEW-CAR-99'
                        df_res.loc[idx, 'กำลังบรรทุกต่อวัน(ถัง)'] = max_daily_cap
                        current_new_vol += vol
                        added_count += 1
                else:
                    break
            pct_util_final = round((current_new_vol / max_weekly_cap) * 100, 2)
            msg += f" เติมจุดส่งใกล้เคียงสำเร็จ {added_count} จุด ยอดรวมใหม่เป็น {round(current_new_vol, 2)} ถัง/สัปดาห์ (คิดเป็น {pct_util_final}%)"
    
    else:
        df_res.loc[selected_subset.index, 'เบอร์รถ'] = 'NEW-CAR-99'
        df_res.loc[selected_subset.index, 'กำลังบรรทุกต่อวัน(ถัง)'] = max_daily_cap
        pct_util = round((total_vol / max_weekly_cap) * 100, 2)
        msg = f"✅ พื้นที่เลือกอยู่ในเกณฑ์ปกติเป๊ะ (ยอดรวม {round(total_vol, 2)} ถัง/สัปดาห์ คิดเป็น {pct_util}%) สร้างสายส่งใหม่สำเร็จ"

    df_res, _ = assign_vehicle_colors(df_res)
    return df_res, total_vol, max_weekly_cap, msg

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
        
        tab1, tab2, tab3 = st.tabs(["📊 สรุปกำลังส่งรายรถ & แผนที่ภาพรวม", "⚡ จัดสายส่งใหม่ (สเกล Lat/Lon พร้อมพรีวิวยอดสด)", "📥 สรุปและExport ข้อมูล"])
        
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
                tooltip = {"html": "<b>🚚 เบอร์รถ:</b> {car_str}<br/><b>🆔 รหัสสมาชิก:</b> {รหัสสมาชิก}<br/><b>👤 ชื่อ:</b> {ชื่อ-นามสกุล}<br/><b>📦 ยอดส่งต่อเดือน:</b> {ยอดส่ง/เดือน} ถัง", "style": {"backgroundColor": "#1e293b", "color": "white", "padding": "10px", "borderRadius": "6px"}}
                st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip=tooltip, map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"))

            render_fast_pydeck_map(df, active_cars_tab1)

        # TAB 2: จัดสายส่งใหม่พร้อมพรีวิวยอดส่งสดแบบเรียลไทม์
        with tab2:
            st.subheader("🗺️ กำหนดสเกล Lat / Lon พร้อมพรีวิวยอดส่งและ % Utilization ของรถคันใหม่แบบเรียลไทม์")
            st.info(f"💡 **ข้อมูลตั้งต้นรถคันใหม่:** กำหนดกำลังส่ง 100% ต่อวัน = **{new_car_daily_capacity} ถัง/วัน** (100% ต่อสัปดาห์ = **{new_car_daily_capacity * 6} ถัง** | เป้าหมายเกณฑ์ปกติ 90-93% คือ **{round(new_car_daily_capacity * 6 * 0.9, 2)} ถึง {round(new_car_daily_capacity * 6 * 0.93, 2)} ถัง/สัปดาห์**)")

            # ส่วนควบคุมสเกล Lat / Lon พร้อมแสดงค่าปัจจุบันกำกับ
            col_lat1, col_lat2 = st.columns(2)
            with col_lat1:
                lat_min_val = float(df['latitude'].min())
                lat_max_val = float(df['latitude'].max())
                lat_range = st.slider("🌐 เลือกช่วงละติจูด (Latitude Range):", lat_min_val, lat_max_val, (lat_min_val + 0.05, lat_max_val - 0.05), step=0.001, key="lat_slider")
                st.caption(f"📌 ค่า Lat ปัจจุบัน: จาก **{lat_range[0]:.4f}** ถึง **{lat_range[1]:.4f}**")
            with col_lat2:
                lon_min_val = float(df['longitude'].min())
                lon_max_val = float(df['longitude'].max())
                lon_range = st.slider("🌐 เลือกช่วงลองจิจูด (Longitude Range):", lon_min_val, lon_max_val, (lon_min_val + 0.05, lon_max_val - 0.05), step=0.001, key="lon_slider")
                st.caption(f"📌 ค่า Lon ปัจจุบัน: จาก **{lon_range[0]:.4f}** ถึง **{lon_range[1]:.4f}**")

            # คำนวณและแสดงพรีวิวยอดส่งในกรอบปัจจุบันทันทีแบบเรียลไทม์
            preview_subset = df[(df['latitude'] >= lat_range[0]) & (df['latitude'] <= lat_range[1]) & 
                                (df['longitude'] >= lon_range[0]) & (df['longitude'] <= lon_range[1])]
            
            preview_total_vol = preview_subset['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ'].sum() if not preview_subset.empty else 0.0
            max_weekly_target = new_car_daily_capacity * 6.0
            preview_util_pct = (preview_total_vol / max_weekly_target) * 100 if max_weekly_target > 0 else 0.0

            # กล่องแสดงผลพรีวิวแบบเด่นชัด
            st.markdown("---")
            col_p1, col_p2, col_p3 = st.columns(3)
            col_p1.metric("📍 จำนวนจุดส่งในกรอบพื้นที่", f"{len(preview_subset):,} จุด")
            col_p2.metric("📦 ยอดส่งรวมในกรอบ", f"{round(preview_total_vol, 2):,} ถัง/สัปดาห์")
            
            if 90 <= preview_util_pct <= 93:
                col_p3.metric("🎯 % Utilization (พรีวิว)", f"{round(preview_util_pct, 2)}%", "🟢 อยู่ในเกณฑ์เป้าหมาย 90-93%")
            elif preview_util_pct > 93:
                col_p3.metric("🎯 % Utilization (พรีวิว)", f"{round(preview_util_pct, 2)}%", "🔴 เกินเกณฑ์ (>93%) - ระบบจะตัดขอบนอกออกให้อัตโนมัติ")
            else:
                col_p3.metric("🎯 % Utilization (พรีวิว)", f"{round(preview_util_pct, 2)}%", "⚠️ ต่ำกว่าเกณฑ์ (<90%) - ระบบจะดึงจุดใกล้เคียงมาเติมให้")
            st.markdown("---")

            # แสดงแผนที่นำทางพร้อมเส้นกรอบและแกน Lat/Long แบบคมชัด ซูม เลื่อน ได้อิสระ
            render_dynamic_axis_pydeck_map(df, all_cars, lat_range[0], lat_range[1], lon_range[0], lon_range[1])

            if st.button("🚀 ประมวลผลสร้างสายส่งใหม่ (NEW-CAR-99) จากกรอบพื้นที่นี้"):
                new_df, tot_vol, max_cap, result_msg = process_area_selection_route(df, lat_range[0], lat_range[1], lon_range[0], lon_range[1], new_car_daily_capacity)
                st.session_state['df_area_opt'] = new_df
                st.success(result_msg)

            if 'df_area_opt' in st.session_state:
                st.divider()
                st.subheader("📋 ผลลัพธ์การจัดสายส่งใหม่ (เพิ่มรถคันใหม่: NEW-CAR-99)")
                current_area_df = st.session_state['df_area_opt']
                st.dataframe(calculate_vehicle_utilization(current_area_df, target_year, target_month), use_container_width=True)
                
                all_cars_opt = sorted(current_area_df['เบอร์รถ'].astype(str).unique())
                selected_cars_opt = st.multiselect("🎨 เลือกเบอร์รถแสดงผล (ผลลัพธ์สายส่งใหม่):", options=all_cars_opt, default=all_cars_opt, key="opt_area_selector")
                active_cars_opt = selected_cars_opt if selected_cars_opt else all_cars_opt
                
                render_dynamic_axis_pydeck_map(current_area_df, active_cars_opt, lat_range[0], lat_range[1], lon_range[0], lon_range[1])
                
                filtered_opt = current_area_df[current_area_df['เบอร์รถ'].astype(str).isin(active_cars_opt)]
                cols_to_show = ['รหัสสมาชิก', 'ชื่อ-นามสกุล', 'เบอร์รถ', 'รอบส่งประจำสัปดาห์', 'ยอดส่ง/เดือน', 'ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ', 'กำลังบรรทุกต่อวัน(ถัง)', 'ที่อยู่จัดส่ง บ้านเลขที่/อาคาร', 'พิกัด Lat/Long']
                existing_cols = [c for c in cols_to_show if c in filtered_opt.columns]
                render_limited_dataframe(filtered_opt[existing_cols], "area_opt")
                
                if st.button("💾 บันทึกผลลัพธ์นี้สำหรับ Export ข้อมูล"):
                    st.session_state['selected_option_df'] = current_area_df
                    st.success("บันทึกข้อมูลสายส่งใหม่เรียบร้อยแล้ว สามารถไปที่ Tab 3 เพื่อดาวน์โหลดได้ทันที")

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
                data
