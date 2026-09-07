import streamlit as st
import pandas as pd
import numpy as np
import folium
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
st.caption("ระบบบริหารจัดการและจัดสายส่งน้ำดื่มอัจฉริยะ (Spatial Clustering Route Optimization)")

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

# แม่สี HEX ประจำเบอร์รถ
def assign_vehicle_colors(df):
    unique_cars = sorted(df['เบอร์รถ'].astype(str).unique())
    base_palette_hex = [
        '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728',
        '#9467bd', '#8c564b', '#e377c2', '#17becf',
        '#bcbd22', '#7f7f7f', '#ff9896', '#aec7e8'
    ]
    hex_map = {}
    for i, car in enumerate(unique_cars):
        hex_map[car] = base_palette_hex[i % len(base_palette_hex)]
        
    df['base_color'] = df['เบอร์รถ'].astype(str).map(hex_map)
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

# ฟังก์ชันแสดงแผนที่ OpenStreetMap (OSM) มีเส้นทางถนน และกด Hover/Popup ดูข้อมูลได้
def render_folium_map(df_input, selected_cars, key_prefix):
    map_center = [df_input['latitude'].mean(), df_input['longitude'].mean()]
    m = folium.Map(location=map_center, zoom_start=12, tiles="OpenStreetMap")

    for _, row in df_input.iterrows():
        car_str = str(row['เบอร์รถ'])
        is_selected = car_str in selected_cars
        
        marker_color = row['base_color'] if is_selected else '#D3D3D3'
        radius = 7 if is_selected else 5
        opacity = 0.9 if is_selected else 0.4
        
        cust_code = row.get('รหัสสมาชิก', '-')
        cust_name = row.get('ชื่อ-นามสกุล', '-')
        address = row.get('ที่อยู่จัดส่ง บ้านเลขที่/อาคาร', '-')
        qty = row.get('ยอดส่ง/เดือน', 0)

        popup_html = f"""
        <div style="font-family: sans-serif; font-size: 13px; width: 200px;">
            <b style="color: #0288d1;">📍 จุดส่งน้ำดื่ม</b><br/>
            <b>🆔 รหัส:</b> {cust_code}<br/>
            <b>👤 ชื่อ:</b> {cust_name}<br/>
            <b>🚚 รถ:</b> <b style="color:{marker_color};">{car_str}</b><br/>
            <b>📦 ยอดส่ง:</b> {qty} ถัง/เดือน<br/>
            <b>🏠 ที่อยู่:</b> {address}
        </div>
        """

        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=radius,
            color=marker_color,
            fill=True,
            fill_color=marker_color,
            fill_opacity=opacity,
            popup=folium.Popup(popup_html, max_width=260),
            tooltip=f"🚚 รถ: {car_str} | {cust_name} ({cust_code})"
        ).add_to(m)

    st_folium(m, width="100%", height=520, key=f"folium_{key_prefix}")

# ฟังก์ชันจัดการการแสดงผลตารางพร้อมตัวเลือกจำกัดจำนวนรายการ
def render_limited_dataframe(df_to_show, key_suffix):
    col_limit, _ = st.columns([1, 2])
    with col_limit:
        limit = st.selectbox(
            "⚡ เลือกจำนวนรายการตารางที่ต้องการแสดง (เพื่อความรวดเร็ว):",
            options=[20, 50, 100, "แสดงทั้งหมด"],
            index=1,
            key=f"row_limit_{key_suffix}"
        )
    
    if limit == "แสดงทั้งหมด":
        st.dataframe(df_to_show, use_container_width=True)
        st.caption(f"แสดงผลทั้งหมด {len(df_to_show):,} รายการ")
    else:
        st.dataframe(df_to_show.head(limit), use_container_width=True)
        st.caption(f"แสดง {limit} รายการแรก จากทั้งหมด {len(df_to_show):,} รายการ (ดาวน์โหลดข้อมูลทั้งหมดได้ที่ Tab 3)")

# อัลกอริทึมจัดสายส่งแบบกระจุกตัวตามพื้นที่ (Spatial Clustering)
def rebalance_routes_spatial(df_in, target_cars, fix_stay_ids, fix_move_ids, fraction_to_move):
    df_res = df_in.copy()
    
    eligible_mask = (df_res['เบอร์รถ'].astype(str).isin(target_cars)) & (~df_res['รหัสสมาชิก'].isin(fix_stay_ids))
    if fix_move_ids:
        eligible_mask = eligible_mask | (df_res['รหัสสมาชิก'].isin(fix_move_ids))
        
    eligible_df = df_res[eligible_mask]
    
    if len(eligible_df) >= 5:
        coords = eligible_df[['latitude', 'longitude']].values
        n_clusters = max(2, int(len(eligible_df) * fraction_to_move / 5))
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10).fit(coords)
        
        cluster_labels = kmeans.labels_
        eligible_df_copy = eligible_df.copy()
        eligible_df_copy['cluster'] = cluster_labels
        
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
            st.subheader("🗺️ แผนที่พิกัดส่งน้ำดื่ม (OpenStreetMap ภาษาไทย + ซอยถนนชัดเจน)")
            
            selected_cars_tab1 = st.multiselect(
                "🎨 เลือกเบอร์รถเพื่อเน้นแสดงผลพิกัดบนแผนที่ (คันที่ไม่เลือกจะเป็นสีเทา):",
                options=all_cars,
                default=all_cars,
                key="tab1_car_selector"
            )
            
            active_cars_tab1 = selected_cars_tab1 if selected_cars_tab1 else all_cars
            
            render_folium_map(df, active_cars_tab1, "tab1")

            st.subheader("📋 ตารางรายละเอียดพิกัดงาน (แสดงเฉพาะเบอร์รถที่เลือก)")
            filtered_df_tab1 = df[df['เบอร์รถ'].astype(str).isin(active_cars_tab1)]
            cols_to_show = ['รหัสสมาชิก', 'ชื่อ-นามสกุล', 'เบอร์รถ', 'รอบส่งประจำสัปดาห์', 'ยอดส่ง/เดือน', 'กำลังบรรทุกต่อวัน(ถัง)', 'ที่อยู่จัดส่ง บ้านเลขที่/อาคาร', 'พิกัด Lat/Long']
            existing_cols = [c for c in cols_to_show if c in filtered_df_tab1.columns]
            
            # เรียกใช้ฟังก์ชันแสดงตารางแบบจำกัดแถว
            render_limited_dataframe(filtered_df_tab1[existing_cols], "tab1")

        # ----------------------------------------------------
        # TAB 2: OPTIMIZATION (3 OPTIONS)
        # ----------------------------------------------------
        with tab2:
            st.subheader("⚙️ เงื่อนไขการจัดสายส่งใหม่และเลือกเบอร์รถต้นทาง")
            
            col_a, col_b = st.columns(2)
            with col_a:
                selected_source_cars = st.multiselect(
                    "🚚 เลือกเฉพาะเบอร์รถที่จะนำมาจัดสายส่งใหม่:",
                    options=all_cars,
                    default=all_cars,
                    help="เลือกเฉพาะเบอร์รถที่ต้องการดึงงานออกมาทำสายใหม่ รถคันอื่นที่ไม่เลือกจะคงเดิมไว้"
                )
            with col_b:
                fix_no = st.multiselect("🔒 รหัสสมาชิกที่ไม่ยอมให้ย้าย (Fix Stay)", df['รหัสสมาชิก'].unique())
                
            col_c, col_d = st.columns(2)
            with col_c:
                fix_move = st.multiselect("🚚 รหัสสมาชิกที่บังคับย้ายไปรถคันใหม่", df['รหัสสมาชิก'].unique())
            with col_d:
                target_pct = st.slider("เป้าหมาย % กำลังบรรทุกของรถคันใหม่", 80, 100, (90, 95))

            if st.button("🚀 ประมวลผลสร้าง 3 ทางเลือกแบบเกาะกลุ่มพื้นที่ (Spatial Optimization)"):
                source_cars = selected_source_cars if selected_source_cars else all_cars
                
                df_opt1 = rebalance_routes_spatial(df, source_cars, fix_no, fix_move, fraction_to_move=0.12)
                df_opt2 = rebalance_routes_spatial(df, source_cars, fix_no, fix_move, fraction_to_move=0.20)
                df_opt3 = rebalance_routes_spatial(df, source_cars, fix_no, fix_move, fraction_to_move=0.28)

                st.session_state['df_opt1'] = df_opt1
                st.session_state['df_opt2'] = df_opt2
                st.session_state['df_opt3'] = df_opt3
                st.success("คำนวณสายส่งใหม่แบบเกาะกลุ่มตามพื้นที่เรียบร้อยแล้ว!")

            if 'df_opt1' in st.session_state:
                df_opt1 = st.session_state['df_opt1']
                df_opt2 = st.session_state['df_opt2']
                df_opt3 = st.session_state['df_opt3']

                opt_tab1, opt_tab2, opt_tab3 = st.tabs([
                    "ทางเลือกที่ 1: เกาะกลุ่มพื้นที่ย้ายงานน้อยที่สุด",
                    "ทางเลือกที่ 2: เกาะกลุ่มความหนาแน่นสูงสุด",
                    "ทางเลือกที่ 3: กระจายยอดส่งสมดุลที่สุด"
                ])

                # OPTION 1
                with opt_tab1:
                    st.markdown("### 🔹 ทางเลือกที่ 1: เกาะกลุ่มพื้นที่ย้ายงานน้อยที่สุด")
                    sum1 = calculate_vehicle_utilization(df_opt1, target_year, target_month)
                    st.dataframe(sum1, use_container_width=True)
                    
                    st.caption("🗺️ แผนที่สายส่งใหม่ (Option 1)")
                    all_cars_opt1 = sorted(df_opt1['เบอร์รถ'].astype(str).unique())
                    selected_cars_opt1 = st.multiselect(
                        "🎨 เลือกเบอร์รถเพื่อเน้นแสดงผลพิกัด (Option 1):",
                        options=all_cars_opt1,
                        default=all_cars_opt1,
                        key="opt1_car_selector"
                    )
                    active_cars_opt1 = selected_cars_opt1 if selected_cars_opt1 else all_cars_opt1
                    render_folium_map(df_opt1, active_cars_opt1, "opt1")
                    
                    filtered_opt1 = df_opt1[df_opt1['เบอร์รถ'].astype(str).isin(active_cars_opt1)]
                    render_limited_dataframe(filtered_opt1[existing_cols], "opt1")
                    
                    if st.button("เลือกทางเลือกที่ 1 สำหรับ Export"):
                        st.session_state['selected_option_df'] = df_opt1
                        st.success("บันทึกทางเลือกที่ 1 เรียบร้อยแล้ว สามารถไปดาวน์โหลดที่ Tab 3")

                # OPTION 2
                with opt_tab2:
                    st.markdown("### 🔹 ทางเลือกที่ 2: เกาะกลุ่มความหนาแน่นสูงสุด")
                    sum2 = calculate_vehicle_utilization(df_opt2, target_year, target_month)
                    st.dataframe(sum2, use_container_width=True)
                    
                    st.caption("🗺️ แผนที่สายส่งใหม่ (Option 2)")
                    all_cars_opt2 = sorted(df_opt2['เบอร์รถ'].astype(str).unique())
                    selected_cars_opt2 = st.multiselect(
                        "🎨 เลือกเบอร์รถเพื่อเน้นแสดงผลพิกัด (Option 2):",
                        options=all_cars_opt2,
                        default=all_cars_opt2,
                        key="opt2_car_selector"
                    )
                    active_cars_opt2 = selected_cars_opt2 if selected_cars_opt2 else all_cars_opt2
                    render_folium_map(df_opt2, active_cars_opt2, "opt2")

                    filtered_opt2 = df_opt2[df_opt2['เบอร์รถ'].astype(str).isin(active_cars_opt2)]
                    render_limited_dataframe(filtered_opt2[existing_cols], "opt2")
                    
                    if st.button("เลือกทางเลือกที่ 2 สำหรับ Export"):
                        st.session_state['selected_option_df'] = df_opt2
                        st.success("บันทึกทางเลือกที่ 2 เรียบร้อยแล้ว สามารถไปดาวน์โหลดที่ Tab 3")

                # OPTION 3
                with opt_tab3:
                    st.markdown("### 🔹 ทางเลือกที่ 3: กระจายยอดส่งสมดุลที่สุด")
                    sum3 = calculate_vehicle_utilization(df_opt3, target_year, target_month)
                    st.dataframe(sum3, use_container_width=True)
                    
                    st.caption("🗺️ แผนที่สายส่งใหม่ (Option 3)")
                    all_cars_opt3 = sorted(df_opt3['เบอร์รถ'].astype(str).unique())
                    selected_cars_opt3 = st.multiselect(
                        "🎨 เลือกเบอร์รถเพื่อเน้นแสดงผลพิกัด (Option 3):",
                        options=all_cars_opt3,
                        default=all_cars_opt3,
                        key="opt3_car_selector"
                    )
                    active_cars_opt3 = selected_cars_opt3 if selected_cars_opt3 else all_cars_opt3
                    render_folium_map(df_opt3, active_cars_opt3, "opt3")

                    filtered_opt3 = df_opt3[df_opt3['เบอร์รถ'].astype(str).isin(active_cars_opt3)]
                    render_limited_dataframe(filtered_opt3[existing_cols], "opt3")
                    
                    if st.button("เลือกทางเลือกที่ 3 สำหรับ Export"):
                        st.session_state['selected_option_df'] = df_opt3
                        st.success("บันทึกทางเลือกที่ 3 เรียบร้อยแล้ว สามารถไปดาวน์โหลดที่ Tab 3")

        # ----------------------------------------------------
        # TAB 3: EXPORT
        # ----------------------------------------------------
        with tab3:
            st.subheader("📥 Export และดาวน์โหลดไฟล์ข้อมูลสายส่งใหม่")
            
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
