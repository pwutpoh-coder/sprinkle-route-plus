import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
from sklearn.cluster import KMeans
import calendar
import io

st.set_page_config(
    page_title="Sprinkle Route Plus",
    page_icon="🗺️",
    layout="wide"
)

st.title("📍 Sprinkle Route Plus")
st.caption("ระบบบริหารจัดการและจัดสายส่งน้ำดื่มอัจฉริยะ (Ultra High-Performance WebGL Engine)")

# Sidebar Control
st.sidebar.header("⚙️ ตั้งค่าข้อมูล")
uploaded_file = st.sidebar.file_uploader("อัปโหลดไฟล์ Excel / CSV", type=["xlsx", "csv"])

target_year = st.sidebar.number_input("ปี ค.ศ.", min_value=2024, max_value=2030, value=2026)
target_month = st.sidebar.selectbox("เดือน", range(1, 13), format_func=lambda x: calendar.month_name[x], index=7)

@st.cache_data
def get_day_count(year, month, day_name):
    cal = calendar.monthcalendar(year, month)
    days = {'จันทร์': 0, 'อังคาร': 1, 'พุธ': 2, 'พฤหัสบดี': 3, 'ศุกร์': 4, 'เสาร์': 5, 'อาทิตย์': 6}
    target_idx = days.get(day_name, 0)
    cnt = sum(1 for week in cal if week[target_idx] != 0)
    return cnt if cnt > 0 else 4

# แม่สี RGB สำหรับ Pydeck [R, G, B]
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

    def calc_daily_vol(row):
        day_str = str(row.get('รอบส่งประจำสัปดาห์', 'จันทร์')).strip()
        cnt = get_day_count(year, month, day_str)
        monthly_vol = float(row.get('ยอดส่ง/เดือน', 0))
        return round(monthly_vol / cnt, 2) if cnt > 0 else round(monthly_vol / 4, 2)

    df['ยอดส่งเฉลี่ยต่อวัน_พิกัด'] = df.apply(calc_daily_vol, axis=1)
    df, rgb_map = assign_vehicle_colors(df)
    return df, rgb_map

@st.cache_data
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

# ฟังก์ชันแสดงผลแผนที่ความเร็วสูงสุดด้วย Pydeck WebGL
def render_fast_pydeck_map(df_input, selected_cars):
    # กรองเบอร์รถที่เลือก
    df_copy = df_input.copy()
    
    # ปรับสีคันที่ไม่เลือกให้เป็นสีเทาอ่อน [210, 210, 210]
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
        opacity=0.8,
        stroked=True,
        get_line_color=[255, 255, 255],
        line_width_min_pixels=1,
    )

    tooltip = {
        "html": "<b>🚚 เบอร์รถ:</b> {car_str}<br/>"
                "<b>🆔 รหัสสมาชิก:</b> {รหัสสมาชิก}<br/>"
                "<b>👤 ชื่อ:</b> {ชื่อ-นามสกุล}<br/>"
                "<b>📦 ยอดส่ง:</b> {ยอดส่ง/เดือน} ถัง/เดือน",
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
            map_style="mapbox://styles/mapbox/light-v10"
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

def rebalance_routes_spatial(df_in, target_cars, fix_stay_ids, fix_move_ids, fraction_to_move):
    df_res = df_in.copy()
    eligible_mask = (df_res['เบอร์รถ'].astype(str).isin(target_cars)) & (~df_res['รหัสสมาชิก'].isin(fix_stay_ids))
    if fix_move_ids:
        eligible_mask = eligible_mask | (df_res['รหัสสมาชิก'].isin(fix_move_ids))
        
    eligible_df = df_res[eligible_mask]
    
    if len(eligible_df) >= 5:
        coords = eligible_df[['latitude', 'longitude']].values
        n_clusters = max(2, int(len(eligible_df) * fraction_to_move / 5))
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=5).fit(coords)
        
        eligible_df_copy = eligible_df.copy()
        eligible_df_copy['cluster'] = kmeans.labels_
        target_cluster = eligible_df_copy['cluster'].value_counts().idxmax()
        move_indices = eligible_df_copy[eligible_df_copy['cluster'] == target_cluster].index
        
        df_res.loc[move_indices, 'เบอร์รถ'] = 'NEW-CAR-11'
        
    df_res, _ = assign_vehicle_colors(df_res)
    return df_res

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file)
        else:
            df_raw = pd.read_excel(uploaded_file)
            
        df, rgb_map = process_data(df_raw, target_year, target_month)
        all_cars = sorted(df['เบอร์รถ'].astype(str).unique())
        
        tab1, tab2, tab3 = st.tabs(["📊 สรุปกำลังส่งรายรถ & แผนที่สีพิกัด", "⚡ จัดสายส่งใหม่ (3 ทางเลือก)", "📥 สรุปและ Export ข้อมูล"])
        
        # TAB 1
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

            st.subheader("📋 ตารางรายละเอียดพิกัดงาน")
            filtered_df_tab1 = df[df['เบอร์รถ'].astype(str).isin(active_cars_tab1)]
            cols_to_show = ['รหัสสมาชิก', 'ชื่อ-นามสกุล', 'เบอร์รถ', 'รอบส่งประจำสัปดาห์', 'ยอดส่ง/เดือน', 'กำลังบรรทุกต่อวัน(ถัง)', 'ที่อยู่จัดส่ง บ้านเลขที่/อาคาร', 'พิกัด Lat/Long']
            existing_cols = [c for c in cols_to_show if c in filtered_df_tab1.columns]
            render_limited_dataframe(filtered_df_tab1[existing_cols], "tab1")

        # TAB 2
        with tab2:
            st.subheader("⚙️ เงื่อนไขการจัดสายส่งใหม่")
            col_a, col_b = st.columns(2)
            with col_a:
                selected_source_cars = st.multiselect("🚚 เลือกเฉพาะเบอร์รถที่จะนำมาจัดสายส่งใหม่:", options=all_cars, default=all_cars)
            with col_b:
                fix_no = st.multiselect("🔒 รหัสสมาชิกที่ไม่ยอมให้ย้าย (Fix Stay)", df['รหัสสมาชิก'].unique())
                
            col_c, col_d = st.columns(2)
            with col_c:
                fix_move = st.multiselect("🚚 รหัสสมาชิกที่บังคับย้ายไปรถคันใหม่", df['รหัสสมาชิก'].unique())
            with col_d:
                target_pct = st.slider("เป้าหมาย % กำลังบรรทุกของรถคันใหม่", 80, 100, (90, 95))

            if st.button("🚀 ประมวลผลสร้าง 3 ทางเลือกแบบเกาะกลุ่มพื้นที่"):
                source_cars = selected_source_cars if selected_source_cars else all_cars
                st.session_state['df_opt1'] = rebalance_routes_spatial(df, source_cars, fix_no, fix_move, fraction_to_move=0.12)
                st.session_state['df_opt2'] = rebalance_routes_spatial(df, source_cars, fix_no, fix_move, fraction_to_move=0.20)
                st.session_state['df_opt3'] = rebalance_routes_spatial(df, source_cars, fix_no, fix_move, fraction_to_move=0.28)
                st.success("คำนวณสำเร็จ!")

            if 'df_opt1' in st.session_state:
                opt_tab1, opt_tab2, opt_tab3 = st.tabs(["ทางเลือกที่ 1", "ทางเลือกที่ 2", "ทางเลือกที่ 3"])

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

        # TAB 3
        with tab3:
            st.subheader("📥 Export ข้อมูล")
            final_export_df = st.session_state.get('selected_option_df', df)
            cols_to_drop = ['latitude', 'longitude', 'color_rgb', 'ยอดส่งเฉลี่ยต่อวัน_พิกัด']
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
