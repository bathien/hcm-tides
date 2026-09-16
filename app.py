import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd

st.set_page_config(page_title="Theo Dõi Thủy Văn TP.HCM", page_icon="🌊", layout="wide")

st.title("🌊 Ứng Dụng Theo Dõi Thủy Văn TP.HCM Hằng Ngày")
st.caption("Dữ liệu được cập nhật từ Ban Chỉ huy PCTT & TKCN TP.HCM")

URL = "https://www.phongchoglutbaotphcm.gov.vn/index.php/dubaocanhbao/du-bao-thuy-van"

@st.cache_data(ttl=3600)  # Tự động lưu cache 1 tiếng để tránh gửi yêu cầu liên tục
def fetch_hydro_data():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        response = requests.get(URL, headers=headers, timeout=10)
        response.encoding = 'utf-8'
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Tìm danh sách các bản tin dự báo thủy văn mới nhất
            news_items = []
            # Giả định cấu trúc bài viết dạng liên kết/tiêu đề
            for a_tag in soup.find_all('a', href=True):
                title = a_tag.get_text(strip=True)
                link = a_tag['href']
                if "thủy văn" in title.lower() or "triều cường" in title.lower():
                    if not link.startswith('http'):
                        link = "https://www.phongchoglutbaotphcm.gov.vn" + link
                    news_items.append({"Tiêu đề bản tin": title, "Liên kết": link})
            
            return news_items
        else:
            return None
    except Exception as e:
        st.error(f"Lỗi khi kết nối tới máy chủ: {e}")
        return None

with st.spinner("Đang tải dữ liệu thủy văn mới nhất..."):
    data = fetch_hydro_data()

if data:
    st.subheader("📌 Các bản tin dự báo & cảnh báo mới nhất")
    df = pd.DataFrame(data).drop_duplicates(subset=["Tiêu đề bản tin"])
    
    # Hiển thị dạng bảng tương tác
    st.dataframe(
        df, 
        column_config={
            "Liên kết": st.column_config.LinkColumn("Xem chi tiết bản tin")
        },
        use_container_width=True
    )
else:
    st.warning("Không thể lấy dữ liệu tự động. Vui lòng kiểm tra lại kết nối hoặc cấu trúc trang web nguồn.")

st.markdown("---")
st.info("💡 **Mẹo:** Bạn có thể nhấn **R** trên bàn phím để làm mới dữ liệu thủ công.")
