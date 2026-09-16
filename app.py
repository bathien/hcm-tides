import io
import re
import pandas as pd
import pdfplumber
import requests
import streamlit as st
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(
    page_title="Đọc Dữ Liệu Thủy Văn TP.HCM", page_icon="🌊", layout="wide"
)

st.title("🌊 Ứng Dụng Theo Dõi Thủy Văn TP.HCM")
st.caption("Nguồn dữ liệu: Ban Chỉ huy PCTT & TKCN TP.HCM (phongchonglutbaotphcm.gov.vn)")

BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
TARGET_URL = f"{BASE_DOMAIN}/index.php/dubaocanhbao/du-bao-thuy-van"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

@st.cache_data(ttl=1800)
def fetch_joomla_hydro_links():
    """Quét danh mục Joomla để lấy các liên kết bài viết / file thủy văn"""
    try:
        res = requests.get(TARGET_URL, headers=HEADERS, timeout=15, verify=False)
        res.encoding = "utf-8"
        soup = BeautifulSoup(res.text, "html.parser")

        items = []
        
        # Quét tất cả thẻ <a> trong Joomla Content
        for a in soup.find_all("a", href=True):
            href = a["href"]
            title = a.get_text(strip=True)
            
            # Loại bỏ các link menu chung, CSS, JavaScript
            if not href.startswith("javascript:") and len(title) > 5:
                # Tìm các đường dẫn thuộc component phocadownload hoặc các bài viết danh mục
                if any(k in href.lower() for k in ["phocadownload", "category", "detail", ".pdf", "download"]):
                    if not href.startswith("http"):
                        full_url = BASE_DOMAIN + href
                    else:
                        full_url = href
                    items.append({"title": title, "url": full_url})
        
        # Nếu chưa tìm thấy link chuyên biệt, lấy toàn bộ link bài viết có trong phần nội dung chính
        if not items:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                title = a.get_text(strip=True)
                if "/index.php/dubaocanhbao/" in href and len(title) > 10:
                    full_url = BASE_DOMAIN + href if not href.startswith("http") else href
                    items.append({"title": title, "url": full_url})
                    
        return items
    except Exception as e:
        st.error(f"Lỗi khi quét trang Joomla: {e}")
        return []

def get_pdf_from_url(page_url):
    """Đi vào trang chi tiết để tìm file PDF thật hoặc link download"""
    try:
        if page_url.lower().endswith(".pdf"):
            return page_url
            
        res = requests.get(page_url, headers=HEADERS, timeout=15, verify=False)
        res.encoding = "utf-8"
        soup = BeautifulSoup(res.text, "html.parser")

        # 1. Tìm thẻ <a> có chứa link .pdf hoặc phocadownload
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if ".pdf" in href.lower() or "phocadownload" in href.lower():
                # Xử lý nếu link nằm trong javascript window.open
                match = re.search(r"window\.open\('([^']+)'", href)
                clean_link = match.group(1) if match else href
                
                return BASE_DOMAIN + clean_link if not clean_link.startswith("http") else clean_link

        return None
    except Exception:
        return None

def read_pdf_tables(pdf_url):
    """Tải và trích xuất dữ liệu bảng từ PDF"""
    try:
        res = requests.get(pdf_url, headers=HEADERS, timeout=15, verify=False)
        pdf_file = io.BytesIO(res.content)

        text_out = ""
        tables_out = []

        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                txt = page.extract_text()
                if txt:
                    text_out += txt + "\n"
                for tb in page.extract_tables():
                    tables_out.append(pd.DataFrame(tb))

        return text_out, tables_out
    except Exception as e:
        return f"Không thể đọc file PDF ({pdf_url}): {e}", []

# --- GIAO DIỆN HỂN THỊ ---
with st.spinner("Đang kết nối đến hệ thống Joomla và tải danh sách bản tin..."):
    item_list = fetch_joomla_hydro_links()

if item_list:
    df_items = pd.DataFrame(item_list).drop_duplicates(subset=["url"])
    unique_items = df_items.to_dict("records")

    selected_title = st.selectbox(
        "📅 Chọn bản tin thủy văn bạn muốn xem:",
        options=[item["title"] for item in unique_items],
    )

    selected_item = next(item for item in unique_items if item["title"] == selected_title)
    
    with st.spinner("Đang tìm và phân tích file PDF bản tin..."):
        pdf_url = get_pdf_from_url(selected_item["url"])

    st.markdown("---")
    
    if pdf_url:
        st.success("✅ Đã tìm thấy tệp PDF của bản tin!")
        st.markdown(f"🔗 **Tải về file gốc:** [{pdf_url}]({pdf_url})")

        with st.spinner("Đang đọc các bảng số liệu mực nước từ PDF..."):
            pdf_text, pdf_tables = read_pdf_tables(pdf_url)

        if pdf_tables:
            st.subheader("📊 Bảng thông số mực nước / Đỉnh triều trích xuất")
            for df_tb in pdf_tables:
                df_tb.columns = df_tb.iloc[0]
                clean_df = df_tb[1:].reset_index(drop=True)
                st.dataframe(clean_df, use_container_width=True)

        st.subheader("📝 Văn bản chi tiết bản tin")
        st.text_area("Toàn văn bản tin:", pdf_text, height=350)
    else:
        st.warning("Bản tin này hiện không kèm tệp PDF hoặc liên kết tải về trực tiếp.")
else:
    st.error("Không tìm thấy liên kết bản tin nào trên trang web nguồn.")