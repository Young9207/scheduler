import streamlit as st
import pandas as pd
import re
import calendar
import datetime

def parse_goals(text: str):
    """
    문자열에서 [소주제]와 • 항목들을 매핑하여 리스트로 반환
    """
    results = []
    current_section = None

    # 줄 단위로 분리
    lines = text.strip().splitlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # [소주제] 탐지
        header_match = re.match(r"\[(.*?)\]", line)
        if header_match:
            current_section = header_match.group(1).strip()
            # 헤더에 바로 붙은 bullet이 있는 경우 ([박사] • ~)
            after = line[header_match.end():].strip()
            if after.startswith("•"):
                item = after.lstrip("•").strip()
                results.append((current_section, item))
            continue

        # 일반 bullet 항목
        if line.startswith("•"):
            item = line.lstrip("•").strip()
            section = current_section if current_section else "기타"
            results.append((section, item))

    return results

# --- [2] 주차 계산 함수 ---
def generate_weeks_for_month(year: int, month: int):
    """
    주어진 연도/월 기준으로 (주차명, 주차코드) 딕셔너리 생성
    """
    weeks = {}
    # 월의 마지막 날짜 구하기
    last_day = calendar.monthrange(year, month)[1]

    # 1일 ~ 마지막일까지 datetime 객체 리스트
    days = [datetime.date(year, month, d) for d in range(1, last_day + 1)]

    # 주차 단위로 나누기 (월요일 시작 기준)
    week_num = 1
    start_day = days[0]
    for i in range(0, len(days), 7):
        end_day = days[i:i + 7][-1]
        label = f"{week_num}주차 ({start_day.month}/{start_day.day}~{end_day.month}/{end_day.day})"
        weeks[label] = f"week{week_num}"
        week_num += 1
        start_day = end_day + datetime.timedelta(days=1)
        if start_day.month != month:
            break

    return weeks


# -------
month_map = {"1월": 1, "2월": 2, "3월": 3, "4월": 4, "5월": 5, "6월": 6,
              "7월": 7, "8월": 8, "9월": 9, "10월": 10, "11월": 11, "12월": 12}

st.set_page_config(page_title="Time Focus Flow", layout="wide")

st.title("🧠 주간 시간관리 웹앱")
st.markdown("분기/월 목표에서 이번 주의 메인 목표를 선택하고, 실행 루틴을 설계하세요.")

# 1. 엑셀 업로드
uploaded_file = st.file_uploader("📁 엑셀 파일 업로드", type=["xlsx"])

if uploaded_file:
    with st.expander("🔍 시트 미리보기"):
        sheet_names = pd.ExcelFile(uploaded_file).sheet_names
        st.write("엑셀 시트 목록:", sheet_names)
    # 시트 불러오기
    df = pd.read_excel(uploaded_file, sheet_name="최대선_최소선")
    df = df[["프로젝트", "월", "최소선", "최대선", "측정지표"]].dropna(subset=["월"])
    
    # Streamlit 설정
    st.set_page_config(page_title="월별 포커스 & 주간 설정", layout="wide")
    st.title("🧠 월별 포커스 선택 및 주간 메인/루틴 구성")

    selected_month = st.selectbox("📅 월을 선택하세요", sorted(df["월"].dropna().unique()))
    #     selected_month = st.selectbox("📅 월을 선택하세요", sorted(df["월"].dropna().unique()))

    year = datetime.date.today().year
    month_num = month_map[selected_month]
    
    weeks = generate_weeks_for_month(year, month_num)
    
    st.markdown(f"### 🗓 {selected_month}의 주차별 일정 ({len(weeks)}주차)")
    
    # --- [4] 목표 데이터 파싱 ---
    filtered = df[df["월"] == selected_month].reset_index(drop=True)
    text_blocks = filtered["최소선"].dropna().tolist() + filtered["최대선"].dropna().tolist()
    parsed = parse_goals("\n".join(map(str, text_blocks)))
    all_goals = [f"{section} - {item}" for section, item in parsed]
    
    # --- [5] 주차별 선택 UI ---
    if "weekly_plan" not in st.session_state:
        st.session_state.weekly_plan = {}
    
    for label, key in weeks.items():
        c1, c2, c3 = st.columns([1.5, 3, 3])
        with c1:
            st.markdown(f"**📌 {label}**")
        with c2:
            focus = st.multiselect(
                "메인 포커스 (1~2개)",
                options=all_goals,
                max_selections=2,
                key=f"{key}_focus"
            )
        with c3:
            routine = st.multiselect(
                "백그라운드 루틴 (최대 3개)",
                options=all_goals,
                max_selections=3,
                key=f"{key}_routine"
            )
        st.session_state.weekly_plan[key] = {"focus": focus, "routine": routine}
    
    # --- [6] 전체 요약 ---
    st.markdown("---")
    st.markdown("## 📝 주간 요약")
    summary_data = []
    for label, key in weeks.items():
        f = st.session_state.weekly_plan.get(key, {}).get("focus", [])
        r = st.session_state.weekly_plan.get(key, {}).get("routine", [])
        summary_data.append({
            "주차": label,
            "메인 포커스": ", ".join(f) if f else "선택 안됨",
            "루틴": ", ".join(r) if r else "선택 안됨"
        })
# st.set_page_config(page_title="Time Focus Flow", layout="wide")

# st.title("🧠 주간 시간관리 웹앱")
# st.markdown("분기/월 목표에서 이번 주의 메인 목표를 선택하고, 실행 루틴을 설계하세요.")

# # 1. 엑셀 업로드
# uploaded_file = st.file_uploader("📁 엑셀 파일 업로드", type=["xlsx"])

# if uploaded_file:
#     with st.expander("🔍 시트 미리보기"):
#         sheet_names = pd.ExcelFile(uploaded_file).sheet_names
#         st.write("엑셀 시트 목록:", sheet_names)

#     # 시트 선택
#     # selected_sheet = st.selectbox("📄 사용할 시트를 선택하세요", sheet_names)
#     # df = pd.read_excel(uploaded_file, sheet_name=selected_sheet)
#     # goals = df.dropna().iloc[:, 0].unique().tolist()

#     ######    
#     # 시트 불러오기
#     df = pd.read_excel(uploaded_file, sheet_name="최대선_최소선")
#     df = df[["프로젝트", "월", "최소선", "최대선", "측정지표"]].dropna(subset=["월"])
    
#     # Streamlit 설정
#     st.set_page_config(page_title="월별 포커스 & 주간 설정", layout="wide")
#     st.title("🧠 월별 포커스 선택 및 주간 메인/루틴 구성")
    
#     # 1. 월 선택
#     selected_month = st.selectbox("📅 월을 선택하세요", sorted(df["월"].dropna().unique()))
    
#     # 2. 해당 월 목표표 보기
#     filtered = df[df["월"] == selected_month].reset_index(drop=True)
#     st.markdown("### 🔍 해당 월의 목표 목록")
#     st.dataframe(filtered[["프로젝트", "최소선", "최대선"]], use_container_width=True)

#     text_data = df[df["월"] == "10월"]["최대선"].iloc[0]
#     parsed = parse_goals(text_data)

#     # 3. 목표 항목 추출
#     all_goals = filtered["최소선"].dropna().tolist() + filtered["최대선"].dropna().tolist()
#     all_goals = list({g.strip() for text in all_goals for g in str(text).split("\n") if g.strip()})
    
#     # 4. 주차별 선택 UI
#     # 4. 주차별 선택 UI
#     st.markdown("## 📆 주차별 메인 포커스 & 루틴 선택")
    
#     weeks = {
#         "1주차 (10/1~10/6)": "week1",
#         "2주차 (10/7~10/13)": "week2",
#         "3주차 (10/14~10/20)": "week3",
#         "4주차 (10/21~10/27)": "week4",
#         "5주차 (10/28~10/31)": "week5",
#     }
    
#     # 세션 상태 초기화 (유지용)
#     if "weekly_plan" not in st.session_state:
#         st.session_state.weekly_plan = {}
    
#     # 한눈에 보기 좋은 표 형태 (각 주차가 한 행)
#     for label, key in weeks.items():
#         c1, c2, c3 = st.columns([1.5, 3, 3])  # 주차 / 메인 / 루틴

#         with c1:
#             st.markdown(f"**📌 {label}**")
    
#         with c2:
#             focus = st.multiselect(
#                 "메인 포커스 (1~2개)",
#                 options=all_goals,
#                 max_selections=2,
#                 key=f"{key}_focus"
#             )
    
#         with c3:
#             routine = st.multiselect(
#                 "백그라운드 루틴 (최대 3개)",
#                 options=all_goals,
#                 max_selections=3,
#                 key=f"{key}_routine"
#             )
    
#         # 주차별 선택 내용 저장
#         st.session_state.weekly_plan[key] = {
#             "focus": focus,
#             "routine": routine
#         }
    
    st.markdown("---")
    st.markdown("## 📝 전체 요약")
    
    # 요약 테이블 생성
    summary_data = []
    for label, key in weeks.items():
        f = st.session_state.weekly_plan.get(key, {}).get("focus", [])
        r = st.session_state.weekly_plan.get(key, {}).get("routine", [])
        summary_data.append({
            "주차": label,
            "메인 포커스": ", ".join(f) if f else "선택 안됨",
            "루틴": ", ".join(r) if r else "선택 안됨"
        })
    
    summary_df = pd.DataFrame(summary_data)
    st.dataframe(summary_df, use_container_width=True)






    

   
    # st.markdown("### 🎯 이번 주 포커스 목표")
    # focus_goals = st.multiselect("1~2개 선택하세요", goals, max_selections=2)

    # st.markdown("### 🌱 루틴 항목")
    # routine_input = st.text_area("쉼표로 구분해서 입력하세요", "식단기록, 발레, 글쓰기")
    # routines = [r.strip() for r in routine_input.split(",") if r.strip()]

    # st.markdown("### 📅 주간 시간 블록 설계")
    # days = ["월", "화", "수", "목", "금", "토", "일"]
    # times = ["오전", "오후", "저녁"]

    # schedule = {}
    # for day in days:
    #     st.subheader(f"🗓 {day}")
    #     schedule[day] = {}
    #     for time in times:
    #         col1, col2 = st.columns(2)
    #         with col1:
    #             f = st.selectbox(f"{day} {time} - 포커스", ["-"] + focus_goals, key=f"{day}-{time}-focus")
    #         with col2:
    #             r = st.selectbox(f"{day} {time} - 루틴", ["-"] + routines, key=f"{day}-{time}-routine")
    #         schedule[day][time] = {"focus": f, "routine": r}

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
