import streamlit as st
import pandas as pd
import numpy as np
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from sklearn.cluster import KMeans
import calendar
import io

st.set_page_config(
    page_title="Sprinkle Route Plus",
    page_icon="🗺️",
    layout="wide"
)

st.title("📍 Sprinkle Route Plus")
st.caption("ระบบบริหารจัดการและจัดสายส่งน้ำดื่มอัจฉริยะ (Minimal High-Performance Route Optimization)")

# Sidebar Control
st.sidebar.header("⚙️ ตั้งค่าข้อมูล")
uploaded_file = st.sidebar.file_uploader("อัปโหลดไฟล์ Excel / CSV", type=["xlsx", "csv"])

target_year = st.sidebar.number_input("ปี ค.ศ.", min_value=2024, max_value=2030, value=2026)
target_month = st.sidebar.selectbox("เดือน", range(1, 13), format_func=lambda x: calendar.month_name[x], index=7)

# Caching การคำนวณจำนวนวันในเดือน
@st.cache_data
def get_day_count(year, month, day_name):
    cal = calendar.monthcalendar(year, month)
    days = {'จันทร์': 0, 'อังคาร': 1, 'พุธ': 2, 'พฤหัสบดี': 3, 'ศุกร์': 4, 'เสาร์': 5, 'อาทิตย์': 6}
    target_idx = days.get(day_name, 0)
    cnt = sum(1 for week in cal if week[target_idx] != 0)
    return cnt if cnt > 0 else 4

# Caching การสร้างแม่สีประจำเบอร์รถ
@st.cache_data
def assign_vehicle_colors(df):
    unique_cars = sorted(df['เบอร์รถ'].astype(str).unique())
    base_palette_hex = [
        '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728',
        '#9467bd', '#8c564b', '#e377c2', '#17becf',
        '#bcbd22', '#7f7f7f', '#ff9896', '#aec7e8'
    ]
    hex_map = {car: base_palette_hex[i % len(base_palette_hex)] for i, car in enumerate(unique_cars)}
    df['base_color'] = df['เบอร์รถ'].astype(str).map(hex_map)
    return df, hex_map

# Caching การเตรียมข้อมูลเบื้องต้น
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
    df, hex_map = assign_vehicle_colors(df)
    return df, hex_map

# Caching สรุป Utilization
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

# ฟังก์ชันแสดงแผนที่มินิมอลสีสว่าง (CartoDB Positron) โหลดเร็วสูง
def render_folium_map_fast(df_input, selected_cars, key_prefix):
    map_center = [df_input['latitude'].mean(), df_input['longitude'].mean()]
    
    # ใช้ไทล์แผนที่โทนขาว-เทาสว่าง เรียบง่าย ไม่กินสเปก
    m = folium.Map(
        location=map_center,
        zoom_start=12,
        tiles="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
    )

    # แยกกรองข้อมูลเพื่อความรวดเร็วในการเรนเดอร์
    df_visible = df_input[df_input['เบอร์รถ'].astype(str).isin(selected_cars)]
    df_gray = df_input[~df_input['เบอร์รถ'].astype(str).isin(selected_cars)]

    # แสดงหมุดพิกัดของเบอร์รถที่เลือก
    for _, row in df_visible.iterrows():
        car_str = str(row['เบอร์รถ'])
        marker_color = row['base_color']
        
        popup_html = f"""
        <div style="font-family: sans-serif; font-size: 12px; width: 180px;">
            <b>🆔 รหัส:</b> {row.get('รหัสสมาชิก', '-')}<br/>
            <b>👤 ชื่อ:</b> {row.get('ชื่อ-นามสกุล', '-')}<br/>
            <b>🚚 รถ:</b> <b style="color:{marker_color};">{car_str}</b><br/>
            <b>📦 ยอด:</b> {row.get('ยอดส่ง/เดือน', 0)} ถัง
        </div>
        """

        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=6,
            color=marker_color,
            fill=True,
            fill_color=marker_color,
            fill_opacity=0.85,
            popup=folium.Popup(popup_html, max_width=220),
            tooltip=f"🚚 รถ: {car_str} | {row.get('ชื่อ-นามสกุล', '-')}"
        ).add_to(m)

    # รวมจุดสีเทาที่ไม่ถูกเลือกให้เป็นกลุ่ม Cluster เพื่อประหยัดการเรนเดอร์บนเบราว์เซอร์
    if not df_gray.empty:
        gray_cluster = MarkerCluster(name="จุดที่ไม่ถูกเลือก", options={'maxClusterRadius': 40}).add_to(m)
        for _, row in df_gray.iterrows():
            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=4,
                color='#CCCCCC',
                fill=True,
                fill_color='#CCCCCC',
                fill_opacity=0.4
            ).add_to(gray_cluster)

    # returned_objects=[] เพื่อป้องกันการส่งข้อมูลกลับฝั่ง Server เวลาเลื่อน/คลิกแผนที่
    st_folium(m, width="100%", height=500, key=f"folium_{key_prefix}", returned_objects=[])

# ฟังก์ชันจัดการการแสดงผลตารางแบบปรับจำนวนรายการได้
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
        st.caption(f"⚡ แสดง {limit} รายการแรกเพื่อความรวดเร็ว (ดาวน์โหลดข้อมูลทั้งหมดได้ที่ Tab 3)")

# อัลกอริทึมจัดสายส่งแบบ Fast Spatial Clustering
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
            
        df, hex_map = process_data(df_raw, target_year, target_month)
        all_cars = sorted(df['เบอร์รถ'].astype(str).unique())
        
        tab1, tab2, tab3 = st.tabs(["📊 สรุปกำลังส่งรายรถ & แผนที่สีพิกัด", "⚡ จัดสายส่งใหม่ (3 ทางเลือก)", "📥 สรุปและ Export ข้อมูล"])
        
        # ----------------------------------------------------
        # TAB 1: INSPECTION
        # ----------------------------------------------------
        with tab1:
            st.subheader("📌 สรุปกำลังส่งเฉลี่ยต่อวันเทียบเปอร์เซ็นต์ (% Utilization)")
            veh_summary = calculate_vehicle_utilization(df, target_year, target_month)
            st.dataframe(veh_summary, use_container_width=True)
            
            st.divider()
            st.subheader("🗺️ แผนที่พิกัดส่งน้ำดื่ม (โหมดมินิมอลสว่าง - คลีนและโหลดไว)")
            
            selected_cars_tab1 = st.multiselect(
                "🎨 เลือกเบอร์รถเพื่อเน้นแสดงผลพิกัดบนแผนที่:",
                options=all_cars,
                default=all_cars,
                key="tab1_car_selector"
            )
            active_cars_tab1 = selected_cars_tab1 if selected_cars_tab1 else all_cars
            
            render_folium_map_fast(df, active_cars_tab1, "tab1")

            st.subheader("📋 ตารางรายละเอียดพิกัดงาน")
            filtered_df_tab1 = df[df['เบอร์รถ'].astype(str).isin(active_cars_tab1)]
            cols_to_show = ['รหัสสมาชิก', 'ชื่อ-นามสกุล', 'เบอร์รถ', 'รอบส่งประจำสัปดาห์', 'ยอดส่ง/เดือน', 'กำลังบรรทุกต่อวัน(ถัง)', 'ที่อยู่จัดส่ง บ้านเลขที่/อาคาร', 'พิกัด Lat/Long']
            existing_cols = [c for c in cols_to_show if c in filtered_df_tab1.columns]
            render_limited_dataframe(filtered_df_tab1[existing_cols], "tab1")

        # ----------------------------------------------------
        # TAB 2: OPTIMIZATION (3 OPTIONS)
        # ----------------------------------------------------
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
                        
                        render_folium_map_fast(current_df, active_cars_opt, f"opt{idx}")
                        
                        filtered_opt = current_df[current_df['เบอร์รถ'].astype(str).isin(active_cars_opt)]
                        render_limited_dataframe(filtered_opt[existing_cols], f"opt{idx}")
                        
                        if st.button(f"เลือกทางเลือกที่ {idx} สำหรับ Export", key=f"btn_opt{idx}"):
                            st.session_state['selected_option_df'] = current_df
                            st.success(f"บันทึกทางเลือกที่ {idx} เรียบร้อยแล้ว")

        # ----------------------------------------------------
        # TAB 3: EXPORT
        # ----------------------------------------------------
        with tab3:
            st.subheader("📥 Export ข้อมูล")
            final_export_df = st.session_state.get('selected_option_df', df)
            cols_to_drop = ['latitude', 'longitude', 'base_color', 'ยอดส่งเฉลี่ยต่อวัน_พิกัด']
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
