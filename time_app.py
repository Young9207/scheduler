import streamlit as st
import pandas as pd
import re
import calendar
import datetime

# 오늘이 포함된 주차 자동 탐색
def find_current_week_label(weeks_dict):
    for label in weeks_dict.keys():
        date_range = label.split("(")[1].strip(")")
        start_str, end_str = date_range.split("~")
        start_month, start_day = map(int, start_str.split("/"))
        end_month, end_day = map(int, end_str.split("/"))
        start_date = datetime.date(today_date.year, start_month, start_day)
        end_date = datetime.date(today_date.year, end_month, end_day)
        if start_date <= today_date <= end_date:
            return label
    return None
    
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
def generate_calendar_weeks(year: int, month: int):
    """
    실제 달력 기준 (월요일~일요일)으로 주차 계산
    월 경계 포함, 예: 9/30(월)~10/6(일)
    """
    weeks = {}

    # 이번 달 1일과 마지막 날
    first_day = datetime.date(year, month, 1)
    last_day = datetime.date(year, month, calendar.monthrange(year, month)[1])

    # 이번 달 첫 주의 월요일 찾기 (1일 이전일 수도 있음)
    start_of_first_week = first_day - datetime.timedelta(days=first_day.weekday())

    current_start = start_of_first_week
    week_num = 1

    while current_start <= last_day:
        current_end = current_start + datetime.timedelta(days=6)
        label = f"{week_num}주차 ({current_start.month}/{current_start.day}~{current_end.month}/{current_end.day})"
        weeks[label] = f"week{week_num}"
        current_start += datetime.timedelta(days=7)
        week_num += 1

    return weeks


# -------
month_map = {"1월": 1, "2월": 2, "3월": 3, "4월": 4, "5월": 5, "6월": 6,
              "7월": 7, "8월": 8, "9월": 9, "10월": 10, "11월": 11, "12월": 12}

# --- 현재 날짜 및 주차 판별 ---
today_date = datetime.date.today()
today_name = today_date.strftime("%A")  



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
    
    weeks = generate_calendar_weeks(year, month_num)


    # 2. 해당 월 목표표 보기
    filtered = df[df["월"] == selected_month].reset_index(drop=True)
    st.markdown("### 🔍 해당 월의 목표 목록")
    st.dataframe(filtered[["프로젝트", "최소선", "최대선"]], use_container_width=True)

    
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

    st.markdown("---")
    st.markdown("## 📝 이번달 주간 요약")
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
#--------테스트
    current_week_label = find_current_week_label(weeks)
    
    if current_week_label:
        st.markdown(f"### 📅 이번 주: **{current_week_label}**")
        plan = st.session_state.weekly_plan.get(weeks[current_week_label], {})
    else:
        st.warning("오늘 날짜에 해당하는 주차를 찾을 수 없습니다.")
        plan = {"focus": [], "routine": []}
    
    # --- 오늘의 실행 블록 ---
    st.markdown("### ✅ 오늘의 실행 체크리스트")
    
    today_tasks = []
    for f in plan.get("focus", []):
        today_tasks.append(f"[포커스] {f}")
    for r in plan.get("routine", []):
        today_tasks.append(f"[루틴] {r}")
    
    completed = []
    for task in today_tasks:
        if st.checkbox(task, key=f"chk_{task}"):
            completed.append(task)
    
    if today_tasks:
        percent = int(len(completed) / len(today_tasks) * 100)
        st.progress(percent)
        st.write(f"📊 오늘의 달성률: **{percent}%**")
    else:
        st.info("오늘 할 일이 아직 배정되지 않았습니다.")
    
    # --- 주간 회고 ---
    st.markdown("### 📝 이번 주 회고 메모")
    review_text = st.text_area("이번 주를 돌아보며 남기고 싶은 메모를 입력하세요", "")
    st.session_state["weekly_review"] = {current_week_label: review_text}




    
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
