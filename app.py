import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import io
import urllib3
import pdfplumber

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="Hệ Thống Thủy Văn TP.HCM", page_icon="🌊", layout="wide")

st.title("🌊 Theo Dõi & Phân Tích Thủy Văn TP.HCM")
st.caption("Nguồn dữ liệu: phongchonglutbaotphcm.gov.vn")

BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
TARGET_URL = f"{BASE_DOMAIN}/index.php/dubaocanhbao/du-bao-thuy-van"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

@st.cache_data(ttl=1800)
def get_articles_list():
    """Lấy danh sách bài viết bản tin từ trang danh mục"""
    try:
        response = requests.get(TARGET_URL, headers=HEADERS, timeout=15, verify=False)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        articles = []
        for a in soup.find_all('a', href=True):
            title = a.get_text(strip=True)
            href = a['href']
            
            # Lọc các liên kết thuộc danh mục bài viết
            if len(title) > 12 and not href.startswith('javascript:'):
                if not href.startswith('http'):
                    href = BASE_DOMAIN + href
                articles.append({"title": title, "link": href})
                
        return articles
    except Exception as e:
        st.error(f"Lỗi kết nối trang chủ: {e}")
        return []

def extract_pdf_from_article(article_url):
    """Vào trang bài viết chi tiết để tìm liên kết PDF"""
    try:
        res = requests.get(article_url, headers=HEADERS, timeout=15, verify=False)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Tìm mọi thẻ <a> có liên kết chứa đuôi .pdf hoặc bộ tải về
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '.pdf' in href.lower() or 'download' in href.lower() or 'phocadownload' in href.lower():
                if not href.startswith('http'):
                    href = BASE_DOMAIN + href
                return href
                
        # Nếu bài viết viết trực tiếp nội dung văn bản (không có PDF)
        main_content = soup.find('div', class_='item-page') or soup.find('body')
        return main_content.get_text("\n", strip=True) if main_content else None
    except Exception:
        return None

def parse_pdf_bytes(pdf_url):
    """Tải và trích xuất bảng/chữ từ file PDF"""
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
                
                tables = page.extract_tables()
                for t in tables:
                    tables_data.append(pd.DataFrame(t))
                    
        return text_content, tables_data
    except Exception as e:
        return f"Lỗi đọc dữ liệu PDF: {e}", []

# --- GIAO DIỆN CHÍNH ---
with st.spinner("Đang kết nối và lấy danh sách bản tin mới nhất..."):
    articles = get_articles_list()

if articles:
    # Bỏ các tiêu đề trùng lặp
    unique_articles = pd.DataFrame(articles).drop_duplicates(subset=["title"]).to_dict('records')
    
    selected_title = st.selectbox(
        "📌 Chọn bản tin thủy văn cần đọc thông số:",
        options=[item["title"] for item in unique_articles]
    )
    
    selected_item = next(item for item in unique_articles if item["title"] == selected_title)
    
    with st.spinner("Đang trích xuất nội dung bài viết và tệp đính kèm..."):
        pdf_or_text = extract_pdf_from_article(selected_item["link"])
    
    st.markdown("---")
    
    if pdf_or_text and pdf_or_text.startswith("http"):
        st.info(f"📄 Đã phát hiện tệp PDF đính kèm trong bài viết.")
        st.markdown(f"[📥 Bấm vào đây để tải về tệp PDF gốc]({pdf_or_text})")
        
        with st.spinner("Đang đọc các bảng số liệu mực nước từ PDF..."):
            text_data, tables = parse_pdf_bytes(pdf_or_text)
            
        if tables:
            st.subheader("📊 Bảng thông số thủy văn & mực nước trích xuất")
            for i, df_tb in enumerate(tables):
                # Làm sạch cột
                df_tb.columns = df_tb.iloc[0]
                clean_df = df_tb[1:].reset_index(drop=True)
                st.dataframe(clean_df, use_container_width=True)
                
        st.subheader("📝 Văn bản chi tiết trong bản tin")
        st.text_area("Toàn văn:", text_data, height=350)
        
    elif pdf_or_text:
        st.subheader("📝 Nội dung bản tin (Được trình bày dạng văn bản)")
        st.text_area("Chi tiết:", pdf_or_text, height=400)
    else:
        st.warning("Không tìm thấy nội dung chi tiết hoặc tệp đính kèm trong bài viết này.")
else:
    st.error("Không thể kết nối đến trang danh mục tin tức. Vui lòng thử lại sau.")