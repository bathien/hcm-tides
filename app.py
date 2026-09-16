import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import io
import re
import urllib3
import pdfplumber

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="Debug & Đọc Thủy Văn TP.HCM", page_icon="🌊", layout="wide")

st.title("🌊 Ứng Dụng Đọc Thủy Văn TP.HCM (Phoca Download Scraper)")

BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
TARGET_URL = f"{BASE_DOMAIN}/index.php/dubaocanhbao/du-bao-thuy-van"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

@st.cache_data(ttl=600)
def debug_and_fetch():
    try:
        res = requests.get(TARGET_URL, headers=HEADERS, timeout=15, verify=False)
        res.encoding = 'utf-8'
        raw_html = res.text
        soup = BeautifulSoup(raw_html, 'html.parser')
        
        results = []

        # TẦNG 1: Quét theo thẻ <a> có chứa javascript:window.open hoặc link download/preview/pdf
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text(strip=True)
            
            # Kiểm tra link nếu là file PDF hoặc đường dẫn Phoca Download
            if any(k in href.lower() for k in ['.pdf', 'phocadownload', 'download', 'preview']):
                # Nếu href chứa javascript window.open, dùng Regex bóc tách URL thật bên trong
                match = re.search(r"window\.open\('([^']+)'", href)
                if match:
                    clean_link = match.group(1)
                else:
                    clean_link = href

                if not clean_link.startswith('http'):
                    clean_link = BASE_DOMAIN + clean_link

                title = text if (text and len(text) > 5) else clean_link.split('/')[-1]
                
                results.append({
                    "title": title,
                    "pdf_link": clean_link
                })

        return results, raw_html
    except Exception as e:
        st.error(f"Lỗi kết nối: {e}")
        return [], ""

def parse_pdf(pdf_url):
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
        return f"Lỗi đọc file PDF ({pdf_url}): {e}", []

# --- GIAO DIỆN CHÍNH ---
with st.spinner("Đang kết nối và debug cấu trúc trang web..."):
    hydro_list, raw_html = debug_and_fetch()

# KHU VỰC DEBUG HTML GỐC
with st.expander("🔍 Bật/Tắt công cụ DEBUG cấu trúc HTML"):
    st.write(f"**Tổng số liên kết PDF/Preview bắt được:** {len(hydro_list)}")
    st.caption("Nếu danh sách bên dưới trống, hãy mở phần mã nguồn HTML bên dưới để xem class thực tế:")
    st.code(raw_html[:3000], language="html") # Hiển thị 3000 ký tự HTML đầu tiên

st.markdown("---")

if hydro_list:
    df_list = pd.DataFrame(hydro_list).drop_duplicates(subset=["pdf_link"])
    items = df_list.to_dict('records')
    
    selected_title = st.selectbox(
        "📅 Chọn bản tin thủy văn cần xem thông số:",
        options=[f"{item['title']} | ({item['pdf_link']})" for item in items]
    )
    
    selected_item = next(item for item in items if f"{item['title']} | ({item['pdf_link']})" == selected_title)
    pdf_url = selected_item["pdf_link"]
    
    st.markdown(f"🔗 **Đường dẫn PDF đang đọc:** [{pdf_url}]({pdf_url})")
    
    with st.spinner("Đang tải và bóc tách dữ liệu từ PDF..."):
        text_data, tables = parse_pdf(pdf_url)
    
    if tables:
        st.subheader("📊 Bảng số liệu mực nước trích xuất từ PDF")
        for df_tb in tables:
            df_tb.columns = df_tb.iloc[0]
            clean_df = df_tb[1:].reset_index(drop=True)
            st.dataframe(clean_df, use_container_width=True)
            
    st.subheader("📝 Nội dung văn bản trong PDF")
    st.text_area("Toàn văn bản tin:", text_data, height=350)
else:
    st.error("⚠️ Vẫn chưa bóc tách được link PDF. Hãy mở hộp thoại 'DEBUG cấu trúc HTML' ở trên để kiểm tra.")