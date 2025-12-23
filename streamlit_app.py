import streamlit as st
import traceback

st.set_page_config(page_title="Diag", layout="wide")
st.write("BUILD:", "2025-12-23 DIAG")

st.title("Диагностика импорта")

try:
    from src.moysklad import MoySkladClient
    st.success("Импорт src.moysklad OK ✅")
except Exception as e:
    st.error("Ошибка при импорте src.moysklad:")
    st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))
    st.stop()

try:
    from src.config import Settings
    st.success("Импорт src.config OK ✅")
except Exception as e:
    st.error("Ошибка при импорте src.config:")
    st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))
    st.stop()

try:
    from src.http import HttpError
    st.success("Импорт src.http OK ✅")
except Exception as e:
    st.error("Ошибка при импорте src.http:")
    st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))
    st.stop()

st.info("Если ты видишь эту строку — импорты живы. Можно возвращать рабочий streamlit_app.py.")
