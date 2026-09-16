import datetime
import os
import requests
import streamlit as st
import urllib3
from google import genai
from google.genai import types

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="Thủy Văn Phú An - AI Powered", page_icon="🤖", layout="wide")

st.title("🤖 Ứng Dụng Phân Tích Thủy Văn Phú An Bằng AI")
st.caption("Sử dụng Google Gemini AI để đọc và trích xuất thông số từ PDF bản tin")

# Nhập API Key trên giao diện (hoặc cấu hình trong st.secrets)
api_key = st.sidebar.text_input("🔑 Nhập Gemini API Key:", type="password")

BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

def build_pdf_url(target_date):
    yyyy = target_date.strftime("%Y")
    mm = target_date.strftime("%m")
    dd = target_date.strftime("%d")
    return f"{BASE_DOMAIN}/phocadownload/{yyyy}/{mm}-{yyyy}/HCMC_TVHN_{yyyy}{mm}{dd}.pdf"

@st.cache_data(ttl=1800)
def fetch_latest_pdf():
    today = datetime.date.today()
    for i in range(7):
        check_date = today - datetime.timedelta(days=i)
        pdf_url = build_pdf_url(check_date)
        try:
            res = requests.get(pdf_url, headers=HEADERS, timeout=5, verify=False)
            if res.status_code == 200 and len(res.content) > 1000:
                return pdf_url, check_date, res.content
        except Exception:
            continue
    return None, None, None

def analyze_pdf_with_gemini(pdf_bytes, api_key):
    """Dùng Gemini AI phân tích trực tiếp file PDF"""
    try:
        client = genai.Client(api_key=api_key)
        
        # Tạo yêu cầu cho AI (Prompt)
        prompt = """
        Bạn là một chuyên gia thủy văn. Hãy đọc tệp PDF bản tin dự báo thủy văn này và thực hiện các nhiệm vụ sau:
        1. Tìm và trích xuất TOÀN BỘ thông tin dự báo liên quan đến TRẠM PHÚ AN (Sông Sài Gòn).
        2. Tổng hợp các thông số quan trọng: Mực nước đỉnh triều cao nhất, Giờ xuất hiện đỉnh triều, Mực nước chân triều, Cấp báo động (BD1, BD2, BD3).
        3. Trình bày kết quả dưới dạng Markdown rõ ràng, gồm:
           - Tóm tắt ngắn gọn nhận định triều cường trạm Phú An.
           - Bảng thông số chi tiết theo từng ngày/lần xuất hiện.
        """
        
        # Gửi file PDF bytes trực tiếp sang cho Gemini
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                types.Part.from_bytes(
                    data=pdf_bytes,
                    mime_type='application/pdf',
                ),
                prompt
            ]
        )
        return response.text
    except Exception as e:
        return f"❌ Lỗi khi gọi Gemini AI: {e}"

# --- GIAO DIỆN CHÍNH ---
with st.spinner("Đang tìm bản tin thủy văn mới nhất..."):
    pdf_url, latest_date, pdf_bytes = fetch_latest_pdf()

if pdf_url and latest_date:
    st.success(f"📅 **Ngày bản tin:** {latest_date.strftime('%d/%m/%Y')}")
    st.markdown(f"🔗 [Mở tệp PDF gốc]({pdf_url})")
    st.markdown("---")
    
    if not api_key:
        st.warning("⚠️ Vui lòng nhập **Gemini API Key** ở thanh bên trái (Sidebar) để kích hoạt AI phân tích PDF.")
    else:
        with st.spinner("🤖 Gemini AI đang đọc và phân tích dữ liệu trạm Phú An..."):
            ai_result = analyze_pdf_with_gemini(pdf_bytes, api_key)
            
        st.subheader("📊 Kết quả phân tích từ AI (Dành riêng cho Trạm Phú An)")
        st.markdown(ai_result)
else:
  st.error("Không tìm thấy tệp PDF dự báo nào trong 7 ngày gần đây.")