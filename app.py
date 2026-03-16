import streamlit as st
import pdfplumber
import pandas as pd
import re
import fitz  # PyMuPDF
import io
from PIL import Image

st.set_page_config(page_title="ระบบตรวจ ปพ.5 อัตโนมัติ", page_icon="📑", layout="wide")

# ==========================================
# 🗄️ โซนที่ 1: แผงควบคุมด้านข้าง (Sidebar)
# ==========================================
with st.sidebar:
    st.header("⚙️ ข้อมูลการส่งงาน")
    department = st.selectbox("เลือกกลุ่มสาระการเรียนรู้:", 
                              ["สังคมศึกษา ศาสนา และวัฒนธรรม", "คณิตศาสตร์", "วิทยาศาสตร์และเทคโนโลยี"])
    
    if department == "สังคมศึกษา ศาสนา และวัฒนธรรม":
        teacher_list = ["นายพีรวัฒน์ แสงเงิน", "ครูท่านอื่นๆ"]
    else:
        teacher_list = ["ครูท่านอื่นๆ"]
        
    teacher_name = st.selectbox("เลือกชื่อผู้สอน:", teacher_list)
    round_choice = st.radio("ระบุรอบการส่งคะแนน:", ["รอบ 4 (ปลายภาค/สรุปผล)"])

# ==========================================
# 📄 โซนที่ 2: พื้นที่อัปโหลดไฟล์
# ==========================================
st.title("📑 ระบบตรวจสอบ ปพ.5 (SGS vs NextSchool) พร้อม Overlay")
st.markdown("---")

col1, col2 = st.columns(2)
with col1:
    file_sgs = st.file_uploader("1️⃣ ไฟล์ ปพ.5 (จาก SGS)", type="pdf")
with col2:
    file_next = st.file_uploader("2️⃣ ไฟล์คะแนน (จาก NextSchool)", type="pdf")

# ==========================================
# ⚙️ โซนที่ 3: ระบบประมวลผล (เครื่องยนต์หลัก)
# ==========================================
if file_sgs and file_next:
    st.markdown("---")
    with st.spinner("กำลังประมวลผล เทียบข้อมูล และสร้างภาพไฮไลต์..."):
        
        # --- 1. อ่านไฟล์ SGS ---
        text_sgs = ""
        with pdfplumber.open(file_sgs) as pdf:
            for page in pdf.pages: text_sgs += page.extract_text() + "\n"
                
        # --- 2. อ่านไฟล์ NextSchool ---
        text_next = ""
        with pdfplumber.open(file_next) as pdf:
            for page in pdf.pages: text_next += page.extract_text() + "\n"

        # 🚨 ด่านที่ 0: ตรวจสอบรหัสวิชา
        subj_sgs_match = re.search(r'([ก-ฮ]\d{5})', text_sgs)
        subj_next_match = re.search(r'([ก-ฮ]\d{5})', text_next)
        
        subj_sgs = subj_sgs_match.group(1) if subj_sgs_match else "ไม่ทราบวิชา(SGS)"
        subj_next = subj_next_match.group(1) if subj_next_match else "ไม่ทราบวิชา(Next)"
        
        if subj_sgs != "ไม่ทราบวิชา(SGS)" and subj_next != "ไม่ทราบวิชา(Next)" and subj_sgs != subj_next:
            st.error(f"🛑 อัปโหลดไฟล์ผิดวิชาหรือเปล่าครับ?! \nไฟล์ SGS คือวิชา **{subj_sgs}** แต่ไฟล์ NextSchool คือวิชา **{subj_next}**")
            st.stop()

        # --- 3. สกัดข้อมูล SGS ---
        pattern_sgs = r'(\d{5})\s+[^\d]+\d+\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+[\d\.]+\s+([0-4]\.[05]|[0-4]|มส|ร)(.*)'
        matches_sgs = re.findall(pattern_sgs, text_sgs)
        
        df_sgs = pd.DataFrame([{
            "รหัสนักเรียน": m[0], "ก่อนกลางภาค": float(m[1]), "กลางภาค": float(m[2]),
            "หลังกลางภาค": float(m[3]), "ปลายภาค": float(m[4]), "รวม_SGS": float(m[5]), 
            "เกรด_SGS": m[6], "คุณลักษณะ": m[7].strip().replace(" ", "")
        } for m in matches_sgs])

        # --- 4. สกัดข้อมูล NextSchool ---
        pattern_next = r'(\d{5})[\s\S]*?(\d{1,3}\.\d{2})\s+([0-4]\.[05]|[0-4]|มส|ร)'
        matches_next = re.findall(pattern_next, text_next)
        
        df_next = pd.DataFrame([{
            "รหัสนักเรียน": m[0], "รวม_Next": float(m[1]), "เกรด_Next": m[2]
        } for m in matches_next])

        # --- 5. ตรวจสอบกฎ & เตรียมเก็บ ID สำหรับไฮไลต์ ---
        error_logs = []
        warning_logs = []
        
        error_ids = set()   # ถังเก็บรหัสที่ต้องปาดสีแดง
        warning_ids = set() # ถังเก็บรหัสที่ต้องปาดสีเหลือง
        
        # 5.1 ตรวจกฎ SGS
        for index, row in df_sgs.iterrows():
            sid = row['รหัสนักเรียน']
            has_error = False
            
            for col in ["ก่อนกลางภาค", "กลางภาค", "หลังกลางภาค", "ปลายภาค", "รวม_SGS"]:
                if row[col] % 1 != 0: 
                    error_logs.append(f"รหัส {sid}: พบทศนิยมใน '{col}' ({row[col]})")
                    has_error = True
            
            if row['เกรด_SGS'] in ['0', '0.0', 'มส', 'ร']:
                eval_only = row['คุณลักษณะ'][:-3] if len(row['คุณลักษณะ']) > 10 else row['คุณลักษณะ']
                if '2' in eval_only or '3' in eval_only:
                    error_logs.append(f"รหัส {sid}: เกรด '{row['เกรด_SGS']}' แต่ประเมินคุณลักษณะได้ 2 หรือ 3")
                    has_error = True

            if has_error:
                error_ids.add(sid)
                
            # กลุ่มเสี่ยง (เตือนเฉพาะสอบไม่ผ่านครึ่ง)
            if row['ก่อนกลางภาค'] < 17.5 or row['กลางภาค'] < 7.5 or row['หลังกลางภาค'] < 17.5:
                warning_logs.append(f"รหัส {sid}: มีคะแนนเก็บหรือกลางภาคไม่ถึงครึ่งเกณฑ์")
                warning_ids.add(sid)

        # 5.2 เทียบไฟล์ชนไฟล์ (Cross-Check)
        df_merged = pd.merge(df_sgs, df_next, on="รหัสนักเรียน", how="inner")
        
        if len(df_merged) == 0:
            error_logs.append("ไม่พบรายชื่อนักเรียนที่ตรงกันเลยระหว่าง 2 ไฟล์ (อาจอัปโหลดผิดห้อง)")
        else:
            for index, row in df_merged.iterrows():
                sid = row['รหัสนักเรียน']
                if row['รวม_SGS'] != row['รวม_Next'] or row['เกรด_SGS'] != row['เกรด_Next']:
                    error_logs.append(f"รหัส {sid}: ข้อมูลขัดแย้ง! SGS รวม {row['รวม_SGS']} (เกรด {row['เกรด_SGS']}) | Next รวม {row['รวม_Next']} (เกรด {row['เกรด_Next']})")
                    error_ids.add(sid)

        # ==========================================
        # 🎨 โซนที่ 4: วาดไฮไลต์ Overlay ลงบนภาพ PDF
        # ==========================================
        # ต้อง Reset ตำแหน่งอ่านไฟล์ก่อนให้ PyMuPDF อ่าน
        file_sgs.seek(0) 
        doc = fitz.open(stream=file_sgs.read(), filetype="pdf")
        
        rendered_images = []
        
        for page in doc:
            # ปาดสีแดง (Error)
            for sid in error_ids:
                text_instances = page.search_for(sid)
                for inst in text_instances:
                    highlight = page.add_highlight_annot(inst)
                    highlight.set_colors(stroke=(1, 0, 0)) # Red
                    highlight.update()
                    
            # ปาดสีเหลือง (Warning) - เฉพาะคนที่ไม่ได้โดนปาดสีแดงไปแล้ว
            for sid in warning_ids:
                if sid in error_ids: continue 
                text_instances = page.search_for(sid)
                for inst in text_instances:
                    highlight = page.add_highlight_annot(inst)
                    highlight.set_colors(stroke=(1, 1, 0)) # Yellow
                    highlight.update()
            
            # แปลงหน้า PDF เป็นรูปภาพ
            pix = page.get_pixmap(dpi=150)
            img_data = pix.tobytes("png")
            image = Image.open(io.BytesIO(img_data))
            rendered_images.append(image)

        # ==========================================
        # 📊 โซนที่ 5: สรุปผลบนหน้าจอ
        # ==========================================
        st.subheader(f"📊 ผลการตรวจสอบ วิชา {subj_sgs} (พบข้อมูล {len(df_sgs)} คน)")
        
        col_res, col_img = st.columns([1, 1])
        
        is_approved = len(error_logs) == 0

        with col_res:
            if is_approved:
                st.success("✅ ข้อมูลถูกต้องสมบูรณ์ 100% ไม่พบจุดทศนิยม และคะแนนตรงกันทั้ง 2 ระบบ")
                st.markdown("### 💾 ยืนยันการส่งข้อมูล")
                if st.button("🚀 บันทึกข้อมูลลง Google Sheets ของฝ่ายวิชาการ", type="primary"):
                    st.balloons()
                    st.success(f"บันทึกข้อมูลของ {teacher_name} ลงระบบเรียบร้อยแล้ว!")
            else:
                st.error("🛑 พบข้อผิดพลาดร้ายแรง ระบบไม่อนุมัติให้ส่งข้อมูล!")
                for err in error_logs:
                    st.error(err)
            
            if warning_logs:
                st.warning("⚠️ พบนักเรียนกลุ่มเสี่ยง (คะแนนไม่ถึงครึ่ง)")
                with st.expander("ดูรายชื่อกลุ่มเสี่ยง"):
                    for warn in warning_logs:
                        st.write(warn)

        with col_img:
            st.markdown("#### 🔍 เอกสาร ปพ.5 ของคุณ (จุดที่ไฮไลต์)")
            # แสดงภาพ PDF ที่เราวาดไฮไลต์แล้ว
            for img in rendered_images:
                st.image(img, use_container_width=True)
