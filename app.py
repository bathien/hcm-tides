import io
import re
import pandas as pd
import pdfplumber
import requests
import streamlit as st
import urllib3
from bs4 import BeautifulSoup

# Tắt cảnh báo SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(
    page_title="Theo Dõi Thủy Văn TP.HCM", page_icon="🌊", layout="wide"
)

st.title("🌊 Ứng Dụng Theo Dõi Thủy Văn TP.HCM Hằng Ngày")
st.caption("Nguồn dữ liệu: phongchonglutbaotphcm.gov.vn")

BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
TARGET_URL = f"{BASE_DOMAIN}/index.php/da-ba-o-tha-y-v-n"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


@st.cache_data(ttl=1800)
def fetch_articles():
  try:
    res = requests.get(TARGET_URL, headers=HEADERS, timeout=15, verify=False)
    res.encoding = "utf-8"
    soup = BeautifulSoup(res.text, "html.parser")

    articles = []
    for a in soup.find_all("a", href=True):
      title = a.get_text(strip=True)
      href = a["href"]

      if len(title) > 10 and not href.startswith("javascript:"):
        if any(
            k in href.lower()
            for k in ["da-ba-o-tha-y-v-n", "dubaocanhbao", "article", "view="]
        ):
          full_url = BASE_DOMAIN + href if not href.startswith("http") else href
          articles.append({"title": title, "url": full_url})

    return articles
  except Exception as e:
    st.error(f"Lỗi tải danh sách: {e}")
    return []


def get_pdf_link(article_url):
  try:
    res = requests.get(article_url, headers=HEADERS, timeout=15, verify=False)
    res.encoding = "utf-8"
    soup = BeautifulSoup(res.text, "html.parser")

    for a in soup.find_all("a", href=True):
      href = a["href"]
      if ".pdf" in href.lower() or "download" in href.lower():
        return BASE_DOMAIN + href if not href.startswith("http") else href
    return None
  except Exception:
    return None


def parse_pdf_advanced(pdf_url):
  """Đọc PDF nâng cao: Kết hợp bóc bảng kẻ + Tự dựng bảng từ Raw Text"""
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

        # 1. Thử bóc bảng bằng cấu hình linh hoạt (kể cả bảng không nét kẻ)
        table_settings = {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "intersection_y_tolerance": 5,
        }
        extracted_tables = page.extract_tables(table_settings)

        for tb in extracted_tables:
          df_tb = pd.DataFrame(tb).dropna(how="all")
          if len(df_tb) > 1 and len(df_tb.columns) > 1:
            tables_out.append(df_tb)

    # 2. XỬ LÝ DỰ PHÒNG: Nếu pdfplumber không tạo được bảng, tự parse Raw Text
    if not tables_out and text_out:
      structured_rows = []
      lines = text_out.split("\n")

      for line in lines:
        # Tìm các dòng chứa tên trạm (Phú An, Nhà Bè, Thủ Dầu Một...) hoặc số liệu mực nước/giờ
        if any(
            t in line.lower()
            for t in [
                "phú an",
                "nhà bè",
                "thủ dầu một",
                "báo động",
                "mực nước",
                "đỉnh triều",
            ]
        ) or re.search(r"\d{1,2}h\d{0,2}|\d+,\d+|\d+\.\d+", line):
          # Tách các từ/con số cách nhau bằng nhiều dấu cách
          parts = [p.strip() for p in re.split(r"\s{2,}|\t", line) if p.strip()]
          if len(parts) > 1:
            structured_rows.append(parts)

      if structured_rows:
        tables_out.append(pd.DataFrame(structured_rows))

    return text_out, tables_out
  except Exception as e:
    return f"Lỗi đọc PDF: {e}", []


# --- GIAO DIỆN STREAMLIT ---
with st.spinner("Đang lấy danh sách bản tin thủy văn..."):
  articles = fetch_articles()

if articles:
  df_art = pd.DataFrame(articles).drop_duplicates(subset=["url"])
  unique_articles = df_art.to_dict("records")

  selected_title = st.selectbox(
      "📅 Chọn bản tin thủy văn:",
      options=[item["title"] for item in unique_articles],
  )

  selected_item = next(
      item for item in unique_articles if item["title"] == selected_title
  )

  with st.spinner("Đang tìm và đọc tệp PDF..."):
    pdf_url = get_pdf_link(selected_item["url"])

  st.markdown("---")

  if pdf_url:
    st.success("✅ Đã tìm thấy tệp PDF!")
    st.markdown(f"📥 **Link PDF gốc:** [{pdf_url}]({pdf_url})")

    with st.spinner("Đang phân tích số liệu từ PDF..."):
      pdf_text, pdf_tables = parse_pdf_advanced(pdf_url)

    if pdf_tables:
      st.subheader("📊 Bảng thông số mực nước / Đỉnh triều đã tự động trích xuất")
      for i, df_tb in enumerate(pdf_tables):
        # Tối ưu giao diện bảng
        st.dataframe(df_tb, use_container_width=True)
    else:
      st.info("ℹ️ Không thể tự dựng bảng từ PDF này.")

    with st.expander("📝 Xem toàn bộ nội dung Raw Text từ PDF"):
      st.text_area("Raw Text:", pdf_text, height=300)
  else:
    st.warning("Bài viết này không có tệp PDF đính kèm.")
else:
  st.error("Không thể lấy dữ liệu bản tin.")