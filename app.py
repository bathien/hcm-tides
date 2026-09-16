import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import io
import urllib3
import pdfplumber

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="Theo Dõi Thủy Văn TP.HCM", page_icon="🌊", layout="wide")

st.title("🌊 Ứng Dụng Theo Dõi Thủy Văn TP.HCM")
st.caption("Nguồn dữ liệu: Ban Chỉ huy PCTT & TKCN TP.HCM (phongchonglutbaotphcm.gov.vn)")

BASE_URL = "https://www.phongchonglutbaotphcm.gov.vn"
HYDRO_URL = f"{BASE_URL}/index.php/dubaocanhbao/du-bao-thuy-van"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

@st.cache_data(ttl=1800)
def get_hydro_articles():
    """Lọc CHÍNH XÁC các bài viết về Thủy Văn"""
    try:
        res = requests.get(HYDRO_URL, headers=HEADERS, timeout=15, verify=False)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        hydro_list = []
        # Lấy tất cả link bài viết trong khu vực nội dung
        for a in soup.find_all('a', href=True):
            title = a.get_text(strip=True)
            href = a['href']
            
            # ĐIỀU KIỆN LỌC CHỈ LẤY THỦY VĂN:
            # Tiêu đề phải chứa từ khóa thủy văn/triều cường/mực nước và không phải menu ngắn
            title_lower = title.lower()
            if any(k in title_lower for k in ["thủy văn", "triều cường", "mực nước", "dự báo thủy"]) and len(title) > 15:
                if not href.startswith('http'):
                    href = BASE_URL + href
                hydro_list.append({"title": title, "link": href})
                
        return hydro_list
    except Exception as e:
        st.error(f"Lỗi khi tải danh sách thủy văn: {e}")
        return []

def get_pdf_from_hydro_page(page_url):
    """Vào bài viết thủy văn lấy link PDF hoặc nội dung"""
    try:
        res = requests.get(page_url, headers=HEADERS, timeout=15, verify=False)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Tìm file PDF trong bài viết thủy văn này
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '.pdf' in href.lower() or 'download' in href.lower():
                if not href.startswith('http'):
                    href = BASE_URL + href
                return href, "pdf"
        
        # Nếu không có file PDF đính kèm, lấy chữ trong bài
        content = soup.find('div', class_='item-page') or soup.find('article') or soup.find('body')
        return content.get_text("\n", strip=True) if content else "Không có nội dung", "text"
    except Exception:
        return None, "error"

def process_pdf(pdf_url):
    """Đọc bảng số liệu thủy văn từ PDF"""
    try:
        res = requests.get(pdf_url, headers=HEADERS, timeout=15, verify=False)
        pdf_file = io.BytesIO(res.content)
        
        text_out = ""
        tables_out = []
        
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_out += text + "\n"
                
                # Trích xuất bảng mực nước
                for tb in page.extract_tables():
                    tables_out.append(pd.DataFrame(tb))
                    
        return text_out, tables_out
    except Exception as e:
        return f"Không thể đọc file PDF: {e}", []

# --- GIAO DIỆN STREAMLIT ---
with st.spinner("Đang lọc danh sách Bản tin Thủy văn mới nhất..."):
    articles = get_hydro_articles()

if articles:
    # Loại bỏ bài viết trùng tiêu đề
    df_articles = pd.DataFrame(articles).drop_duplicates(subset=["title"])
    hydro_items = df_articles.to_dict('records')
    
    selected_title = st.selectbox(
        "📌 Chọn bản tin thủy văn bạn muốn xem thông số:",
        options=[item["title"] for item in hydro_items]
    )
    
    # Lấy thông tin bài được chọn
    selected_item = next(item for item in hydro_items if item["title"] == selected_title)
    
    with st.spinner("Đang tải dữ liệu thủy văn..."):
        data_source, data_type = get_pdf_from_hydro_page(selected_item["link"])
    
    st.markdown("---")
    
    if data_type == "pdf":
        st.success("📄 Đã tìm thấy tệp PDF Thủy văn chính thức.")
        st.markdown(f"[📥 Tải về file PDF gốc]({data_source})")
        
        with st.spinner("Đang trích xuất bảng mực nước & đỉnh triều từ PDF..."):
            pdf_text, pdf_tables = process_pdf(data_source)
            
        if pdf_tables:
            st.subheader("📊 Bảng thông số mực nước / Đỉnh triều trích xuất")
            for df_tb in pdf_tables:
                # Định dạng lại bảng cho dễ nhìn
                df_tb.columns = df_tb.iloc[0]
                clean_df = df_tb[1:].reset_index(drop=True)
                st.dataframe(clean_df, use_container_width=True)
        
        st.subheader("📝 Văn bản chi tiết bản tin")
        st.text_area("Nội dung:", pdf_text, height=300)
        
    elif data_type == "text":
        st.subheader("📝 Nội dung bản tin Thủy văn")
        st.text_area("Chi tiết:", data_source, height=400)
    else:
        st.error("Lỗi khi tải nội dung bản tin này.")
else:
    st.warning("Không tìm thấy bản tin thủy văn nào hoặc trang web nguồn thay đổi cấu trúc.")