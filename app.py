import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import io
import urllib3
import pdfplumber

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="Thủy Văn TP.HCM", page_icon="🌊", layout="wide")

st.title("🌊 Theo Dõi Thủy Văn TP.HCM Hằng Ngày")
st.caption("Nguồn dữ liệu: phongchonglutbaotphcm.gov.vn (Chuyên mục Dự báo Thủy văn)")

BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
TARGET_URL = f"{BASE_DOMAIN}/index.php/dubaocanhbao/du-bao-thuy-van"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

@st.cache_data(ttl=1800)
def fetch_phoca_hydro_data():
    """Bóc tách chính xác pd-title và link PDF từ pd-button-preview"""
    try:
        res = requests.get(TARGET_URL, headers=HEADERS, timeout=15, verify=False)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        results = []
        
        # Tìm tất cả các container bài viết thuộc cấu trúc Phoca Download
        pd_rows = soup.find_all('div', class_=lambda c: c and 'pd-filename' in c) or soup.find_all(['div', 'tr'])
        
        for row in pd_rows:
            # 1. Trích xuất tiêu đề từ pd-title
            title_tag = row.find(class_=lambda c: c and 'pd-title' in c)
            # 2. Trích xuất link PDF từ nút preview pd-button-preview
            preview_tag = row.find(class_=lambda c: c and 'pd-button-preview' in c)
            
            # Nếu tìm thấy preview button dạng thẻ <a>
            if preview_tag and preview_tag.name != 'a':
                preview_tag = preview_tag.find('a')
                
            if title_tag and preview_tag and preview_tag.get('href'):
                title = title_tag.get_text(strip=True)
                pdf_link = preview_tag['href']
                
                if not pdf_link.startswith('http'):
                    pdf_link = BASE_DOMAIN + pdf_link
                    
                results.append({
                    "title": title,
                    "pdf_link": pdf_link
                })
        
        # Trường hợp dự phòng nếu class bọc bên ngoài thay đổi
        if not results:
            titles = soup.find_all(class_=lambda c: c and 'pd-title' in c)
            previews = soup.find_all(class_=lambda c: c and 'pd-button-preview' in c)
            
            for t, p in zip(titles, previews):
                a_tag = p if p.name == 'a' else p.find('a')
                if a_tag and a_tag.get('href'):
                    href = a_tag['href']
                    if not href.startswith('http'):
                        href = BASE_DOMAIN + href
                    results.append({
                        "title": t.get_text(strip=True),
                        "pdf_link": href
                    })
                    
        return results
    except Exception as e:
        st.error(f"Lỗi khi đọc danh sách: {e}")
        return []

def parse_pdf(pdf_url):
    """Tải và trích xuất bảng số liệu từ file PDF"""
    try:
        res = requests.get(pdf_url, headers=HEADERS, timeout=15, verify=False)
        pdf_file = io.BytesIO(res.content)
        
        text_content = ""
        tables_data = []
        
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_content += text + "\n"
                
                for t in page.extract_tables():
                    tables_data.append(pd.DataFrame(t))
                    
        return text_content, tables_data
    except Exception as e:
        return f"Không thể tải hoặc đọc file PDF: {e}", []

# --- GIAO DIỆN CHÍNH ---
with st.spinner("Đang lấy danh sách bản tin thủy văn theo ngày..."):
    hydro_list = fetch_phoca_hydro_data()

if hydro_list:
    df_list = pd.DataFrame(hydro_list).drop_duplicates(subset=["title"])
    items = df_list.to_dict('records')
    
    selected_title = st.selectbox(
        "📅 Chọn bản tin thủy văn cần đọc (theo pd-title):",
        options=[item["title"] for item in items]
    )
    
    selected_item = next(item for item in items if item["title"] == selected_title)
    pdf_url = selected_item["pdf_link"]
    
    col1, col2 = st.columns([1, 4])
    with col1:
        st.markdown(f"[📥 Mở / Tải file PDF gốc]({pdf_url})")
    
    with st.spinner("Đang đọc bảng thông số từ PDF..."):
        text_data, tables = parse_pdf(pdf_url)
    
    st.markdown("---")
    
    if tables:
        st.subheader("📊 Bảng thông số mực nước / đỉnh triều trích xuất")
        for df_tb in tables:
            df_tb.columns = df_tb.iloc[0]
            clean_df = df_tb[1:].reset_index(drop=True)
            st.dataframe(clean_df, use_container_width=True)
            
    st.subheader("📝 Nội dung chi tiết trong PDF")
    st.text_area("Toàn văn bản tin:", text_data, height=350)

else:
    st.warning("Chưa tìm thấy phần tử `pd-title` hoặc `pd-button-preview` trên trang web nguồn.")