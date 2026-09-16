import io
import re
import pandas as pd
import pdfplumber
import requests
import streamlit as st
import urllib3
from bs4 import BeautifulSoup

# Tắt cảnh báo kết nối SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(
    page_title="Theo Dõi Thủy Văn TP.HCM", page_icon="🌊", layout="wide"
)

st.title("🌊 Ứng Dụng Theo Dõi Thủy Văn TP.HCM Hằng Ngày")
st.caption("Nguồn dữ liệu trực tiếp: phongchonglutbaotphcm.gov.vn")

BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
# Đường dẫn trực tiếp bạn cung cấp
TARGET_URL = f"{BASE_DOMAIN}/index.php/da-ba-o-tha-y-v-n"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


@st.cache_data(ttl=1800)
def fetch_articles_from_new_url():
  """Bóc tách các bản tin thủy văn từ đường dẫn mới"""
  try:
    res = requests.get(TARGET_URL, headers=HEADERS, timeout=15, verify=False)
    res.encoding = "utf-8"
    soup = BeautifulSoup(res.text, "html.parser")

    articles = []

    # Quét tất cả thẻ <a> trên trang
    for a in soup.find_all("a", href=True):
      title = a.get_text(strip=True)
      href = a["href"]

      # Điều kiện lọc bài viết: Độ dài tiêu đề > 10 và liên kết thuộc danh mục bài viết
      if len(title) > 10 and not href.startswith("javascript:"):
        # Bỏ qua các link menu hệ thống trùng lặp
        if any(
            k in href.lower()
            for k in ["da-ba-o-tha-y-v-n", "dubaocanhbao", "article", "view="]
        ):
          full_url = BASE_DOMAIN + href if not href.startswith("http") else href
          articles.append({"title": title, "url": full_url})

    return articles
  except Exception as e:
    st.error(f"Lỗi khi lấy dữ liệu: {e}")
    return []


def extract_detail_and_pdf(article_url):
  """Đi vào trang bài viết chi tiết để lấy link PDF hoặc đọc trực tiếp bảng số liệu"""
  try:
    res = requests.get(article_url, headers=HEADERS, timeout=15, verify=False)
    res.encoding = "utf-8"
    soup = BeautifulSoup(res.text, "html.parser")

    # 1. Quét tìm tệp PDF đính kèm trong bài viết (nếu có)
    for a in soup.find_all("a", href=True):
      href = a["href"]
      if ".pdf" in href.lower() or "download" in href.lower():
        pdf_url = BASE_DOMAIN + href if not href.startswith("http") else href
        return pdf_url, "pdf"

    # 2. Nếu không có PDF, bóc tách bảng HTML trực tiếp trong bài viết
    tables = soup.find_all("table")
    if tables:
      parsed_tables = []
      for tb in tables:
        df_list = pd.read_html(str(tb))
        if df_list:
          parsed_tables.append(df_list[0])
      if parsed_tables:
        return parsed_tables, "html_table"

    # 3. Trích xuất toàn văn bản nội dung bài viết
    main_content = (
        soup.find("div", class_="item-page")
        or soup.find("div", id="content")
        or soup
    )
    return main_content.get_text("\n", strip=True), "text"

  except Exception as e:
    return f"Lỗi trích xuất bài viết: {e}", "error"


def parse_pdf(pdf_url):
  """Trích xuất bảng và nội dung từ file PDF bằng pdfplumber"""
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
    return f"Lỗi đọc file PDF: {e}", []


# --- GIAO DIỆN HỂN THỊ STREAMLIT ---
with st.spinner("Đang kết nối và lấy danh sách bản tin thủy văn hằng ngày..."):
  articles = fetch_articles_from_new_url()

if articles:
  # Lọc bỏ các bài viết trùng lặp URL
  df_art = pd.DataFrame(articles).drop_duplicates(subset=["url"])
  unique_articles = df_art.to_dict("records")

  selected_title = st.selectbox(
      "📅 Chọn bản tin thủy văn bạn muốn xem:",
      options=[item["title"] for item in unique_articles],
  )

  selected_item = next(
      item for item in unique_articles if item["title"] == selected_title
  )

  with st.spinner("Đang tải dữ liệu thông số thủy văn..."):
    content, content_type = extract_detail_and_pdf(selected_item["url"])

  st.markdown("---")

  # XỬ LÝ KẾT QUẢ HIỂN THỊ
  if content_type == "pdf":
    st.success("✅ Đã phát hiện tệp PDF thủy văn đính kèm!")
    st.markdown(f"📥 **Tải về file gốc:** [{content}]({content})")

    with st.spinner("Đang đọc các bảng số liệu mực nước từ PDF..."):
      pdf_text, pdf_tables = parse_pdf(content)

    if pdf_tables:
      st.subheader("📊 Bảng thông số mực nước / Đỉnh triều trích xuất từ PDF")
      for df_tb in pdf_tables:
        df_tb.columns = df_tb.iloc[0]
        clean_df = df_tb[1:].reset_index(drop=True)
        st.dataframe(clean_df, use_container_width=True)

    st.subheader("📝 Văn bản chi tiết trong bản tin")
    st.text_area("Toàn văn bản tin:", pdf_text, height=300)

  elif content_type == "html_table":
    st.subheader("📊 Bảng thông số mực nước / Đỉnh triều (Dạng Bảng HTML)")
    for df_tb in content:
      st.dataframe(df_tb, use_container_width=True)

  elif content_type == "text":
    st.subheader("📝 Nội dung chi tiết bản tin")
    st.text_area("Nội dung:", content, height=400)

else:
  st.error(
      "Không thể tải danh sách bài viết từ đường dẫn mới. Vui lòng kiểm tra lại"
      " kết nối mạng."
  )