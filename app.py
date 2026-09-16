import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import io
import urllib3
import pdfplumber

# Tắt cảnh báo SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="Hệ Thống Đọc Dữ Liệu Thủy Văn TP.HCM", page_icon="🌊", layout="wide")

st.title("🌊 Ứng Dụng Đọc & Phân Tích Bản Tin Thủy Văn TP.HCM")
st.caption("Nguồn dữ liệu: phongchonglutbaotphcm.gov.vn")

TARGET_URL = "https://www.phongchonglutbaotphcm.gov.vn/index.php/dubaocanhbao/du-bao-thuy-van"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# 1. Hàm lấy danh sách các tệp PDF bản tin
@st.cache_data(ttl=1800)
def get_pdf_list():
    try:
        response = requests.get(TARGET_URL, headers=HEADERS, timeout=15, verify=False)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        pdf_files = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text(strip=True)
            
            # Lấy các liên kết tải PDF hoặc chứa đuôi .pdf
            if '.pdf' in href.lower() or 'phocadownload' in href.lower() or 'download=' in href.lower():
                if not href.startswith('http'):
                    href = "https://www.phongchonglutbaotphcm.gov.vn" + href
                
                title = text if text else href.split('/')[-1]
                pdf_files.append({"Tên bản tin": title, "Link_PDF": href})
        
        return pdf_files
    except Exception as e:
        st.error(f"Lỗi khi lấy danh sách bản tin: {e}")
        return []

# 2. Hàm đọc và trích xuất nội dung/bảng biểu từ PDF
def extract_pdf_data(pdf_url):
    try:
        res = requests.get(pdf_url, headers=HEADERS, timeout=15, verify=False)
        pdf_file = io.BytesIO(res.content)
        
        text_content = ""
        tables_data = []
        
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                # Đọc văn bản
                text = page.extract_text()
                if text:
                    text_content += text + "\n"
                
                # Trích xuất bảng số liệu nếu có
                tables = page.extract_tables()
                for table in tables:
                    df_table = pd.DataFrame(table)
                    tables_data.append(df_table)
                    
        return text_content, tables_data
    except Exception as e:
        return f"Không thể đọc file PDF: {e}", []

# --- GIAO DIỆN CHÍNH ---
pdf_list = get_pdf_list()

if pdf_list:
    st.success(f"✅ Đã tìm thấy {len(pdf_list)} bản tin PDF trên hệ thống.")
    
    # Cho phép người dùng chọn bản tin muốn xem thông số
    options = [item["Tên bản tin"] for item in pdf_list]
    selected_option = st.selectbox("📌 Chọn bản tin cần xem thông số chi tiết:", options)
    
    # Lấy URL của file PDF được chọn
    selected_pdf_url = next(item["Link_PDF"] for item in pdf_list if item["Tên bản tin"] == selected_option)
    
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(f"[📥 Tải file PDF gốc]({selected_pdf_url})")
    
    with st.spinner("Đang phân tích dữ liệu bên trong tệp PDF..."):
        pdf_text, pdf_tables = extract_pdf_data(selected_pdf_url)
    
    st.markdown("---")
    
    # Hiển thị thông số dạng Bảng (nếu có)
    if pdf_tables:
        st.subheader("📊 Bảng số liệu mực nước trích xuất từ PDF")
        for i, table in enumerate(pdf_tables):
            # Làm sạch bảng: lấy dòng đầu tiên làm tiêu đề cột nếu hợp lệ
            table.columns = table.iloc[0]
            clean_df = table[1:].reset_index(drop=True)
            st.dataframe(clean_df, use_container_width=True)
    
    # Hiển thị nội dung văn bản chi tiết
    st.subheader("📝 Nội dung chi tiết bản tin")
    st.text_area("Toàn văn bản tin:", pdf_text, height=400)

else:
    st.warning("Không tìm thấy tệp PDF dự báo nào hoặc không thể kết nối tới trang web nguồn.")