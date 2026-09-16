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
    page_title="Hệ Thống Thủy Văn TP.HCM", page_icon="🌊", layout="wide"
)

st.title("🌊 Ứng Dụng Theo Dõi & Đọc Thủy Văn TP.HCM")
st.caption("Nguồn dữ liệu chính thức: phongchonglutbaotphcm.gov.vn")

BASE_DOMAIN = "https://www.phongchonglutbaotphcm.gov.vn"
TARGET_URL = f"{BASE_DOMAIN}/index.php/dubaocanhbao/du-bao-thuy-van"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


@st.cache_data(ttl=1800)
def fetch_hydro_articles():
  """Lấy danh sách các bản tin thủy văn từ Joomla"""
  try:
    res = requests.get(TARGET_URL, headers=HEADERS, timeout=15, verify=False)
    res.encoding = "utf-8"
    soup = BeautifulSoup(res.text, "html.parser")

    items = []
    for a in soup.find_all("a", href=True):
      href = a["href"]
      title = a.get_text(strip=True)

      if len(title) > 8 and not href.startswith("javascript:"):
        if any(
            k in href
            for k in [
                "/dubaocanhbao/",
                "phocadownload",
                "view=category",
                "view=detail",
            ]
        ):
          full_url = BASE_DOMAIN + href if not href.startswith("http") else href
          items.append({"title": title, "url": full_url})

    return items
  except Exception as e:
    st.error(f"Lỗi khi quét danh sách bản tin: {e}")
    return []


def extract_content_or_pdf(page_url):
  """Bóc tách triệt để link PDF từ iFrame, onclick hoặc lấy bảng HTML"""
  try:
    res = requests.get(page_url, headers=HEADERS, timeout=15, verify=False)
    res.encoding = "utf-8"
    raw_html = res.text
    soup = BeautifulSoup(raw_html, "html.parser")

    # 1. Quét tìm link PDF trong thẻ <iframe> (Phoca PDF viewer)
    for iframe in soup.find_all("iframe", src=True):
      src = iframe["src"]
      if ".pdf" in src.lower() or "phocadownload" in src.lower():
        pdf_url = re.search(r"file=([^&]+)", src)
        clean_pdf = pdf_url.group(1) if pdf_url else src
        return (
            BASE_DOMAIN + clean_pdf
            if not clean_pdf.startswith("http")
            else clean_pdf
        ), "pdf"

    # 2. Tìm link PDF trong thẻ <a> hoặc JavaScript onclick
    for a in soup.find_all("a", href=True):
      href = a["href"]
      if ".pdf" in href.lower() or "download" in href.lower():
        match = re.search(r"window\.open\('([^']+)'", href)
        clean_link = match.group(1) if match else href
        return (
            BASE_DOMAIN + clean_link
            if not clean_link.startswith("http")
            else clean_link
        ), "pdf"

    # 3. Nếu không có PDF, quét lấy bảng HTML trực tiếp trong bài viết
    tables = soup.find_all("table")
    if tables:
      html_tables = []
      for tb in tables:
        df_list = pd.read_html(str(tb))
        if df_list:
          html_tables.append(df_list[0])
      if html_tables:
        return html_tables, "html_table"

    # 4. Cuối cùng lấy toàn bộ văn bản bài viết
    main_text = soup.get_text("\n", strip=True)
    return main_text, "text"

  except Exception as e:
    return f"Lỗi trích xuất: {e}", "error"


def read_pdf(pdf_url):
  """Đọc PDF bằng pdfplumber"""
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
    return f"Không thể tải hoặc phân tích file PDF ({pdf_url}): {e}", []


# --- GIAO DIỆN STREMLIT ---
with st.spinner("Đang tải danh sách bản tin thủy văn..."):
  articles = fetch_hydro_articles()

if articles:
  df_articles = pd.DataFrame(articles).drop_duplicates(subset=["url"])
  unique_articles = df_articles.to_dict("records")

  selected_title = st.selectbox(
      "📌 Chọn bản tin thủy văn hằng ngày:",
      options=[item["title"] for item in unique_articles],
  )

  selected_item = next(
      item for item in unique_articles if item["title"] == selected_title
  )

  with st.spinner("Đang trích xuất dữ liệu thủy văn..."):
    content_data, content_type = extract_content_or_pdf(selected_item["url"])

  st.markdown("---")

  # TRƯỜNG HỢP 1: BÁO TÁCH THÀNH CÔNG FILE PDF
  if content_type == "pdf":
    st.success("✅ Đã trích xuất thành công tệp PDF đính kèm!")
    st.markdown(f"📥 **Đường dẫn PDF gốc:** [{content_data}]({content_data})")

    with st.spinner("Đang đọc các bảng mực nước từ PDF..."):
      pdf_text, pdf_tables = read_pdf(content_data)

    if pdf_tables:
      st.subheader("📊 Bảng thông số mực nước / Đỉnh triều")
      for df_tb in pdf_tables:
        df_tb.columns = df_tb.iloc[0]
        clean_df = df_tb[1:].reset_index(drop=True)
        st.dataframe(clean_df, use_container_width=True)

    st.subheader("📝 Văn bản chi tiết trong bản tin")
    st.text_area("Toàn văn bản tin:", pdf_text, height=300)

  # TRƯỜNG HỢP 2: BẢN TIN LÀ BẢNG HTML TRỰC TIẾP
  elif content_type == "html_table":
    st.info("📊 Bản tin trình bày trực tiếp dưới dạng bảng số liệu HTML.")
    for df_tb in content_data:
      st.dataframe(df_tb, use_container_width=True)

  # TRƯỜNG HỢP 3: VĂN BẢN
  elif content_type == "text":
    st.subheader("📝 Nội dung chi tiết bản tin")
    st.text_area("Chi tiết:", content_data, height=350)

else:
    st.error("Không tìm thấy dữ liệu bản tin nào.")