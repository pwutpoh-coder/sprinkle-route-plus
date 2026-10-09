import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import calendar
import io

# 1. ตั้งค่าหน้าเพจ
st.set_page_config(
    page_title="Sprinkle Route Plus",
    page_icon="🗺️",
    layout="wide"
)

st.title("📍 Sprinkle Route Plus")
st.caption("ระบบบริหารจัดการและจัดสายส่งน้ำดื่มอัจฉริยะ (Interactive Lasso & Box Selection Engine)")

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
        '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728',
        '#9467bd', '#8c564b', '#e377c2', '#17becf',
        '#bcbd22', '#7f7f7f', '#ff9896', '#aec7e8'
    ]
    rgb_map = {car: rgb_palette[i % len(rgb_palette)] for i, car in enumerate(unique_cars)}
    df['color_hex'] = df['เบอร์รถ'].astype(str).map(rgb_map)
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
            'กำลังบรรทุก 100%ต่อสัปดาห์ (ถัง)': max_weekly_cap,
            '% การใช้งานกำลังบรรทุก (% Utilization)': round(utilization_pct, 2),
            'สถานะ': status
        })
    return pd.DataFrame(summary_list)

# 4. ฟังก์ชันแสดงแผนที่ Plotly รองรับ Lasso / Box Selection
def render_plotly_map(df_input, selected_cars, key_name):
    df_copy = df_input.copy()
    df_copy['car_str'] = df_copy['เบอร์รถ'].astype(str)
    
    # กรองเฉพาะรถที่เลือกแสดง
    df_filtered = df_copy[df_copy['car_str'].isin(selected_cars)]
    
    fig = px.scatter_mapbox(
        df_filtered,
        lat="latitude",
        lon="longitude",
        color="car_str",
        color_discrete_map={car: col for car, col in zip(df_copy['car_str'].unique(), df_copy['color_hex'].unique())},
        hover_name="รหัสสมาชิก",
        hover_data=["ชื่อ-นามสกุล", "ยอดส่ง/เดือน", "ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ", "เบอร์รถ"],
        zoom=11,
        height=600
    )
    
    fig.update_layout(
        mapbox_style="carto-positron",
        margin={"r":0,"t":0,"l":0,"b":0},
        clickmode='event+select',
        dragmode='lasso' # เริ่มต้นด้วยโหมดลากคลุมอิสระ (Lasso)
    )
    
    selection = st.plotly_chart(
        fig, 
        use_container_width=True, 
        on_select="rerun", 
        selection_mode=("box", "lasso"),
        key=key_name
    )
    return selection

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

# 5. อัลกอริทึมจัดการพื้นที่ลากคลุม (Lasso Selection Rebalancing) ให้ได้เกณฑ์ 90-93% และเกลี่ยส่วนที่เหลือ
def process_lasso_selection_route(df_in, selected_indices, target_min=90.0, target_max=93.0, new_car_capacity=200.0):
    df_res = df_in.copy()
    max_weekly_cap = new_car_capacity * 6.0
    target_min_vol = max_weekly_cap * (target_min / 100.0) # 90%
    target_max_vol = max_weekly_cap * (target_max / 100.0) # 93%

    if not selected_indices:
        return df_res, 0, 0, "ไม่พบจุดพิกัดที่ถูกลากคลุม กรุณาใช้เครื่องมือ Lasso หรือ Box เลือกพื้นที่บนแผนที่"

    # ดึงจุดที่ผู้ใช้ลากคลุมมาเป็นกลุ่มตั้งต้นของรถคันใหม่ ('NEW-CAR-99')
    selected_subset = df_res.iloc[selected_indices].copy()
    total_vol = selected_subset['ยอดส่งเฉลี่ยต่อสัปดาห์_คำนวณ'].sum()

    msg = ""
    # กรณี 1: ยอดเกินเกณฑ์ (>93%) -> ตัดขอบนอกออกอัตโนมัติจนกว่าจะเข้าเกณฑ์เป้าหมาย
    if total_vol > target_max_vol:
        # คำนวณจุดศูนย์กลางของพื้นที่ที่ลากคลุม เพื่อตัดจุดที่อยู่รอบนอกสุดออกก่อน
        center_lat = selected_subset['latitude'].mean()
        center_lon = selected_subset['longitude'].mean()
        selected_subset['dist_from_center'] = np.sqrt((selected_subset['latitude'] - center_lat)**2 + (selected_subset['longitude'] - center_lon)**2)
        selected_subset = selected_subset.sort_values(by='dist_from_center', ascending=False) # ไกลสุดอยู่บนสุด

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
        msg = f"⚠️ พื้นที่ลากคลุมมียอดส่งเกินเกณฑ์ (>93%) ระบบได้ทำการตัดขอบนอกออกอัตโนมัติ คงเหลือยอดส่ง {round(accumulated_vol, 2)} ถัง/สัปดาห์ (คิดเป็น {round((accumulated_vol/max_weekly_cap)*100, 2)}%) เข้าสู่เกณฑ์ปกติ"
        
        # นำจุดที่โดนตัดออกไปเกลี่ยเพิ่มให้กับเบอร์รถเดิมที่อยู่ใกล้ที่สุด
        for drop_idx in dropped_indices:
            drop_row = df_res.loc[drop_idx]
            # หารรถคันเดิมที่ใกล้ที่สุด (ยกเว้น NEW-CAR-99)
            other_cars = df_res[df_res['เบอร์รถ'] != 'NEW-CAR-99']
            if not other_cars.empty:
                dists = np.sqrt((other_cars['latitude'] - drop_row['latitude'])**2 + (other_cars['longitude'] - drop_row['longitude'])**2)
                nearest_car = other_cars.loc[dists.idxmin(), 'เบอร์รถ']
                df_res.loc[drop_idx, 'เบอร์รถ'] = nearest_car

    # กรณี 2: ยอดต่ำกว่าเกณฑ์ (<90%) -> แจ้งเตือนว่ายอดไม่ครบ และแนะนำให้ลากคลุมเพิ่ม หรือระบบช่วยดึงจุดใกล้เคียงมาเติมให้ครบ
    elif total_vol < target_min_vol:
        needed_vol = target_min_vol - total_vol
        msg = f"⚠️ ยอดส่งต่ำกว่าเกณฑ์ (<90% โดยมียอด {round(total_vol, 2)} ถัง/สัปดาห์ หรือ {round((total_vol/max_weekly_cap)*100, 2)}%) ระบบกำลังดึงจุดส่งรอบข้างที่ใกล้ที่สุดมาเติมให้ครบช่วง 90-93%..."
        
        df_res.loc[selected_subset.index, 'เบอร์รถ'] = 'NEW-CAR-99'
        current_new_vol = total_vol

        # หาจุดภายนอกที่อยู่ใกล้กลุ่มนี้ที่สุดมาเติม
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
                        current_new_vol += vol
                        added_count += 1
                else:
                    break
            msg += f" เติมจุดส่งใกล้เคียงสำเร็จ {added_count} จุด ยอดรวมใหม่เป็น {round(current_new_vol, 2)} ถัง/สัปดาห์ ({round((current_new_vol/max_weekly_cap)*100, 2)}%)"
    
    # กรณี 3: อยู่ในเกณฑ์พอดี (90-93%)
    else:
        df_res.loc[selected_subset.index, 'เบอร์รถ'] = 'NEW-CAR-99'
        msg = f"✅ พื้นที่ลากคลุมอยู่ในเกณฑ์ปกติเป๊ะ ({round((total_vol/max_weekly_cap)*100, 2)}% หรือ {round(total_vol, 2)} ถัง/สัปดาห์) สร้างสายส่งใหม่สำเร็จ"

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
        
        tab1, tab2, tab3 = st.tabs(["📊 สรุปกำลังส่งรายรถ & แผนที่ภาพรวม", "⚡ จัดสายส่งใหม่ (ลากคลุมพื้นที่ Lasso/Box)", "📥 สรุปและExport ข้อมูล"])
        
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
            st.subheader("🗺️ แผนที่แสดงพิกัดส่งน้ำดื่มภาพรวม")
            selected_cars_tab1 = st.multiselect("🎨 เลือกเบอร์รถแสดงผล:", options=all_cars, default=all_cars, key="tab1_car_selector")
            active_cars_tab1 = selected_cars_tab1 if selected_cars_tab1 else all_cars
            render_plotly_map(df, active_cars_tab1, "map_tab1")

        # TAB 2: จัดสายส่งใหม่ด้วยการลากคลุมพื้นที่ (Lasso / Box Select)
        with tab2:
            st.subheader("🖱️ จัดสายส่งใหม่ด้วยการลากคลุมพื้นที่บนแผนที่ (Interactive Lasso / Box Select)")
            st.info("💡 **วิธีใช้งาน:** ใช้เครื่องมือ **Lasso Select (ไอคอนบ่วงบาศ)** หรือ **Box Select (ไอคอนสี่เหลี่ยม)** ที่มุมขวาบนของแผนที่ด้านล่าง ลากคลุมพื้นที่ลูกค้าที่คุณต้องการสร้างเป็นสายส่งใหม่ ระบบจะทำการคำนวณและปรับสัดส่วนให้อยู่ในเกณฑ์ 90-93% อัตโนมัติ")

            selected_cars_tab2 = st.multiselect("🎨 เลือกเบอร์รถบนแผนที่เพื่อช่วยในการลากคลุม:", options=all_cars, default=all_cars, key="tab2_car_selector")
            active_cars_tab2 = selected_cars_tab2 if selected_cars_tab2 else all_cars

            # เรียกใช้ Plotly Map พร้อมรับข้อมูลการลากคลุม (Selection Event)
            selection_event = render_plotly_map(df, active_cars_tab2, "map_tab2")

            # ตรวจสอบจุดพิกัดที่ผู้ใช้ลากคลุมเลือก
            selected_indices = []
            if selection_event and "point_indices" in selection_event.get("selection", {}):
                # แปลงจุดที่เลือกในแบบ filtered กลับเป็น index ของ df หลัก
                filtered_df_temp = df[df['เบอร์รถ'].astype(str).isin(active_cars_tab2)].reset_index(drop=True)
                selected_filtered_indices = selection_event["selection"]["point_indices"]
                if selected_filtered_indices:
                    selected_indices = filtered_df_temp.iloc[selected_filtered_indices].index.tolist()

            if selected_indices:
                st.success(f"🎯 คุณลากคลุมเลือกจุดส่งทั้งหมด {len(selected_indices)} จุด")
                
                if st.button("🚀 ประมวลผลสร้างสายส่งใหม่จากพื้นที่ที่ลากคลุม (ปรับเข้าเกณฑ์ 90-93%)"):
                    new_df, tot_vol, max_cap, result_msg = process_lasso_selection_route(df, selected_indices)
                    st.session_state['df_lasso_opt'] = new_df
                    st.toast(result_msg, icon="📌")
                    st.success(result_msg)

            if 'df_lasso_opt' in st.session_state:
                st.divider()
                st.subheader("📋 ผลลัพธ์การจัดสายส่งใหม่ (เพิ่มรถคันใหม่: NEW-CAR-99)")
                current_lasso_df = st.session_state['df_lasso_opt']
                st.dataframe(calculate_vehicle_utilization(current_lasso_df, target_year, target_month), use_container_width=True)
                
                all_cars_opt = sorted(current_lasso_df['เบอร์รถ'].astype(str).unique())
                selected_cars_opt = st.multiselect("🎨 เลือกเบอร์รถแสดงผล (ผลลัพธ์สายส่งใหม่):", options=all_cars_opt, default=all_cars_opt, key="opt_lasso_selector")
                active_cars_opt = selected_cars_opt if selected_cars_opt else all_cars_opt
                
                render_plotly_map(current_lasso_df, active_cars_opt, "map_lasso_result")
                
                if st.button("💾 บันทึกผลลัพธ์นี้สำหรับ Export ข้อมูล"):
                    st.session_state['selected_option_df'] = current_lasso_df
                    st.success("บันทึกข้อมูลสายส่งใหม่เรียบร้อยแล้ว สามารถไปที่ Tab 3 เพื่อดาวน์โหลดได้ทันที")

        # TAB 3: Export ข้อมูล
        with tab3:
            st.subheader("📥 Export ข้อมูลแผนงานจัดสายส่ง")
            final_export_df = st.session_state.get('selected_option_df', df)
            cols_to_drop = ['latitude', 'longitude', 'color_hex']
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
