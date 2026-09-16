import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import urllib3

# Tắt cảnh báo SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="Thủy Văn TP.HCM", page_icon="🌊", layout="wide")

st.title("🌊 Theo Dõi Thủy Văn TP.HCM (Nguồn Chính Thức)")
st.caption("Dữ liệu từ: Ban Chỉ huy Phòng thủ dân sự / Phòng chống thiên tai TP.HCM")

# Nguồn gốc yêu cầu giữ lại
TARGET_URL = "https://www.phongchonglutbaotphcm.gov.vn/index.php/dubaocanhbao/du-bao-thuy-van"

@st.cache_data(ttl=1800)
def fetch_exact_source():
    # Giả lập hoàn toàn một trình duyệt Chrome thực sự
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.phongchonglutbaotphcm.gov.vn/",
        "Connection": "keep-alive"
    }
    
    try:
        # Gửi request có bỏ qua xác thực SSL (verify=False) để xử lý triệt để lỗi HTTPS
        session = requests.Session()
        response = session.get(TARGET_URL, headers=headers, timeout=15, verify=False)
        response.encoding = 'utf-8'
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            news_items = []
            
            # Quét tất cả thẻ <a> trên trang web nguồn
            for a_tag in soup.find_all('a', href=True):
                title = a_tag.get_text(strip=True)
                link = a_tag['href']
                
                # Bóc tách các liên kết thuộc danh mục tin tức/bản tin
                if len(title) > 10 and not link.startswith('javascript:'):
                    if not link.startswith('http'):
                        link = "https://www.phongchonglutbaotphcm.gov.vn" + link
                    
                    news_items.append({
                        "Tiêu đề bản tin": title,
                        "Liên kết chi tiết": link
                    })
            
            return news_items, None
        else:
            return None, f"Máy chủ trả về mã lỗi: {response.status_code}"
            
    except requests.exceptions.ConnectionError as e:
        return None, "Lỗi DNS/Mạng: Máy tính của bạn không thể phân giải tên miền phongchonglutbaotphcm.gov.vn (Hãy thử đổi DNS máy tính sang 8.8.8.8)."
    except Exception as e:
        return None, f"Lỗi không xác định: {str(e)}"

# Giao diện hiển thị Streamlit
with st.spinner("Đang kết nối trực tiếp tới phongchonglutbaotphcm.gov.vn..."):
    data, error_msg = fetch_exact_source()

if data:
    st.success("✅ Kết nối thành công tới nguồn phongchonglutbaotphcm.gov.vn!")
    df = pd.DataFrame(data).drop_duplicates(subset=["Tiêu đề bản tin"]).reset_index(drop=True)
    
    st.dataframe(
        df,
        column_config={
            "Tiêu đề bản tin": st.column_config.TextColumn("Tiêu đề bản tin thủy văn", width="large"),
            "Liên kết chi tiết": st.column_config.LinkColumn("Thao tác", display_text="Xem bản tin 🔗")
        },
        use_container_width=True,
        hide_index=True
    )
else:
    st.error(f"⚠️ {error_msg}")
    
    # Hướng dẫn xử lý trực tiếp nếu máy cá nhân bị chặn DNS
    with st.expander("🛠️ Cách khắc phục nếu máy bạn vẫn bị lỗi NameResolutionError"):
        st.write("""
        1. **Đổi DNS trên máy tính:** Chuyển DNS Wi-Fi/Ethernet sang Google DNS (`8.8.8.8` và `8.8.4.4`) hoặc Cloudflare (`1.1.1.1`).
        2. **Deploy lên Cloud:** Đẩy mã nguồn này lên **Streamlit Community Cloud** (Server của họ nằm ở nước ngoài nên giải DNS trang `.gov.vn` cực kỳ chuẩn xác và không bao giờ bị lỗi này).
        """)