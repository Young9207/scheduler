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
        
    current_week_label = find_current_week_label(weeks)

    
    # --- [6] 전체 요약 ---
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

#----------테스트1
    # 없으면 간단히 더미 하나:
    if "weeks" not in st.session_state:
        st.session_state.weeks = {"예시주차 (10/7~10/13)": "week_demo"}
    if "selected_week_label" not in st.session_state:
        st.session_state.selected_week_label = list(st.session_state.weeks.keys())[0]
    
    weeks = st.session_state.weeks
    selected_week_label = st.selectbox("📆 자동 배치할 주차를 선택하세요", list(weeks.keys()), index=0)
    selected_week_key = weeks[selected_week_label]
    
    # 📌 주차의 날짜 범위 파싱 (라벨: "1주차 (10/7~10/13)")
    def parse_week_dates(week_label: str, year: int = None):
        if year is None:
            year = datetime.date.today().year
        rng = week_label.split("(")[1].strip(")")
        start_str, end_str = rng.split("~")
        sm, sd = map(int, start_str.split("/"))
        em, ed = map(int, end_str.split("/"))
        start = datetime.date(year, sm, sd)
        end = datetime.date(year, em, ed)
        # 월~일 (7일) 보장
        days = [start + datetime.timedelta(days=i) for i in range((end - start).days + 1)]
        # 날짜가 7개가 아니어도 표시는 7열로 맞추기 위해 보정
        while len(days) < 7:
            days.append(days[-1] + datetime.timedelta(days=1))
        return days[:7]
    
    days_kr = ["월", "화", "수", "목", "금", "토", "일"]
    week_dates = parse_week_dates(selected_week_label)
    
    st.markdown(f"### 🗓 {selected_week_label} 요일(월~일)")
    st.caption("자동 배치 후 각 요일별 항목은 자유롭게 수정할 수 있어요.")
    
    # ✅ 메인 1~2개 입력 (없으면 수동 입력)
    st.markdown("#### 🎯 이번 주 메인 1~2개 입력")
    col_a, col_b = st.columns(2)
    with col_a:
        main_a = st.text_input("메인 A (예: [박사] 컨택 리스트 완성)", value="메인 A")
    with col_b:
        main_b = st.text_input("메인 B (선택)", value="")
    
    # 각 메인을 7단계 Flow Unit으로 자동 분해
    default_steps = ["리서치", "정리", "초안", "개선/개별화", "검토/발송", "보완", "회고"]
    def build_flow(title: str, steps=default_steps):
        return [f"{title} - Step {i+1}: {s}" for i, s in enumerate(steps)]
    
    flow_a = build_flow(main_a) if main_a.strip() else []
    flow_b = build_flow(main_b) if main_b.strip() else []
    
    # 배치 패턴 선택
    st.markdown("#### 🧭 배치 패턴")
    pattern = st.radio(
        "요일에 어떻게 배치할까요?",
        ["교차 배치 (A-B 교차)", "집중 배치 (전반 A, 후반 B)", "A만 사용"],
        index=0,
        horizontal=True
    )
    
    # 요일별 자동 배치
    def distribute_flows(flow_a, flow_b, pattern):
        schedule = {i: [] for i in range(7)}  # 0=월 ... 6=일
        if pattern == "교차 배치 (A-B 교차)":
            # i가 짝수면 A, 홀수면 B (B 없으면 A 계속)
            ai, bi = 0, 0
            for i in range(7):
                if ai < len(flow_a):
                    schedule[i].append(flow_a[ai]); ai += 1
                if flow_b and bi < len(flow_b):
                    schedule[i].append(flow_b[bi]); bi += 1
        elif pattern == "집중 배치 (전반 A, 후반 B)":
            # 앞부분은 A를 먼저 채우고, 남은 칸에 B
            ai, bi = 0, 0
            for i in range(7):
                if ai < len(flow_a):
                    schedule[i].append(flow_a[ai]); ai += 1
                elif flow_b and bi < len(flow_b):
                    schedule[i].append(flow_b[bi]); bi += 1
        else:  # "A만 사용"
            for i in range(7):
                if i < len(flow_a):
                    schedule[i].append(flow_a[i])
        return schedule
    
    auto_schedule = distribute_flows(flow_a, flow_b, pattern)
    
    # 🌱 루틴(배경음)도 기본 제공
    st.markdown("#### 🌱 루틴(배경음) 선택")
    routine_default = st.text_input("쉼표로 구분 (예: 식단 기록, 운동, 독서 20분)", value="식단 기록, 운동, 독서 20분")
    routine_list = [r.strip() for r in routine_default.split(",") if r.strip()]
    
    # UI: 요일별로 자동 배치된 내용을 수정 가능 (멀티라인 편집)
    st.markdown("#### ✏️ 요일별 계획 (자동 배치 → 자유 수정)")
    if "weekday_plan" not in st.session_state:
        st.session_state.weekday_plan = {}
    
    # 초기 채우기 (처음 렌더링 시만)
    if selected_week_key not in st.session_state.weekday_plan:
        st.session_state.weekday_plan[selected_week_key] = {}
        for i in range(7):
            items = auto_schedule[i] + routine_list  # 기본: 루틴도 같이 제안
            st.session_state.weekday_plan[selected_week_key][i] = items
    
    # 에디터 렌더링
    for i, date in enumerate(week_dates):
        day_label = f"{days_kr[i]} ({date.month}/{date.day})"
        st.write(f"**{day_label}**")
        current_items = st.session_state.weekday_plan[selected_week_key].get(i, [])
        text_value = "\n".join(current_items)
        new_text = st.text_area(
            label="",
            value=text_value,
            key=f"edit_{selected_week_key}_{i}",
            height=100,
            placeholder="한 줄에 한 항목씩 입력하세요"
        )
        # 변경 반영
        st.session_state.weekday_plan[selected_week_key][i] = [line.strip() for line in new_text.splitlines() if line.strip()]
        st.divider()
    
    # 요약 테이블
    st.markdown("### ✅ 주간 요약표")
    rows = []
    for i, date in enumerate(week_dates):
        items = st.session_state.weekday_plan[selected_week_key].get(i, [])
        rows.append({
            "요일": f"{days_kr[i]}",
            "날짜": f"{date.month}/{date.day}",
            "할 일": " | ".join(items) if items else "-"
        })
    summary_df = pd.DataFrame(rows)
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
