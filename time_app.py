import streamlit as st
import pandas as pd

st.set_page_config(page_title="Time Focus Flow", layout="wide")

st.title("🧠 주간 시간관리 웹앱")
st.markdown("분기/월 목표에서 이번 주의 메인 목표를 선택하고, 실행 루틴을 설계하세요.")

# 1. 엑셀 업로드
uploaded_file = st.file_uploader("📁 엑셀 파일 업로드", type=["xlsx"])

if uploaded_file:
    with st.expander("🔍 시트 미리보기"):
        sheet_names = pd.ExcelFile(uploaded_file).sheet_names
        st.write("엑셀 시트 목록:", sheet_names)

    # 시트 선택
    selected_sheet = st.selectbox("📄 사용할 시트를 선택하세요", sheet_names)
    df = pd.read_excel(uploaded_file, sheet_name=selected_sheet)
    goals = df.dropna().iloc[:, 0].unique().tolist()

    st.markdown("### 🎯 이번 주 포커스 목표")
    focus_goals = st.multiselect("1~2개 선택하세요", goals, max_selections=2)

    st.markdown("### 🌱 루틴 항목")
    routine_input = st.text_area("쉼표로 구분해서 입력하세요", "식단기록, 발레, 글쓰기")
    routines = [r.strip() for r in routine_input.split(",") if r.strip()]

    st.markdown("### 📅 주간 시간 블록 설계")
    days = ["월", "화", "수", "목", "금", "토", "일"]
    times = ["오전", "오후", "저녁"]

    schedule = {}
    for day in days:
        st.subheader(f"🗓 {day}")
        schedule[day] = {}
        for time in times:
            col1, col2 = st.columns(2)
            with col1:
                f = st.selectbox(f"{day} {time} - 포커스", ["-"] + focus_goals, key=f"{day}-{time}-focus")
            with col2:
                r = st.selectbox(f"{day} {time} - 루틴", ["-"] + routines, key=f"{day}-{time}-routine")
            schedule[day][time] = {"focus": f, "routine": r}

    st.markdown("---")
    st.markdown("### ✅ 오늘의 실행 체크리스트")
    today = st.selectbox("오늘은 무슨 요일인가요?", days)
    today_tasks = []
    for time in times:
        block = schedule.get(today, {}).get(time, {})
        if block.get("focus") and block["focus"] != "-":
            today_tasks.append(f"[포커스] {block['focus']} ({time})")
        if block.get("routine") and block["routine"] != "-":
            today_tasks.append(f"[루틴] {block['routine']} ({time})")

    completed = []
    for task in today_tasks:
        if st.checkbox(task):
            completed.append(task)

    if today_tasks:
        percent = int(len(completed) / len(today_tasks) * 100)
        st.progress(percent)
        st.write(f"📊 오늘의 달성률: **{percent}%**")
    else:
        st.info("오늘 할 일이 아직 배정되지 않았습니다.")

    st.markdown("### 📝 이번 주 회고 메모")
    st.text_area("이번 주를 돌아보며 남기고 싶은 메모를 입력하세요", "")

else:
    st.warning("엑셀 파일을 먼저 업로드해주세요.")
