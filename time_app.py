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
                "메인 포커스 (1-2개)",
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


#--------테스트    
    current_week_label = find_current_week_label(weeks)

    if current_week_label:
        st.markdown(f"### 📅 이번 주: **{current_week_label}**")
        plan = st.session_state.weekly_plan.get(weeks[current_week_label], {})
    else:
        st.warning("오늘 날짜에 해당하는 주차를 찾을 수 없습니다.")
        plan = {"focus": [], "routine": []}
    
    # --- 오늘의 실행 블록 ---
    # ---테스트1---
    # # 요일 정의 (월~일)
    # DAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]
    # UNIT_TEMPLATES = ["Step 1: 리서치/구조", "Step 2: 제작/초안", "Step 3: 정리/공유"]
    
    # # --- 주차 선택(해당 주만 보이기) ---
    # selected_week_label = st.selectbox("📆 볼 주차를 선택하세요", list(weeks.keys()))
    # selected_week_key = weeks[selected_week_label]
    
    # st.markdown(f"### 🗓 {selected_week_label} — 요일별 블록 (월-일 가로 배치)")
    
    # # --- 선택된 주의 메인 1~2개 가져오기 ---
    # plan = st.session_state.weekly_plan.get(selected_week_key, {"focus": [], "routine": []})
    # mains = plan.get("focus", [])[:2]
    # routines = plan.get("routine", [])
    
    # # 메인이 없으면 안내 후 종료
    # if not mains:
    #     st.info("이 주차에 선택된 메인이 없습니다. 먼저 메인 1~2개를 선택해주세요.")
    # else:
    #     # --- 메인을 3단계 데일리 블록으로 분해 ---
    #     def build_flow(title: str):
    #         return [f"{title} - {u}" for u in UNIT_TEMPLATES]
    
    #     flows = [build_flow(m) for m in mains]  # [[A1,A2,A3], [B1,B2,B3]]
    #     # 교차 순서: A1, B1, A2, B2, A3, B3
    #     queue = []
    #     for i in range(3):
    #         for f in flows:
    #             if i < len(f):
    #                 queue.append(f[i])
    
    #     # --- 요일별 블록 자동 배치 (월~토 6칸 → 남는 일요일은 루틴/버퍼로) ---
    #     day_blocks = {d: [] for d in DAYS_KR}
    #     qi = 0
    #     for d in DAYS_KR:
    #         if qi < len(queue):
    #             day_blocks[d].append(queue[qi]); qi += 1
    
    #     # 일요일 등 남는 칸에는 루틴을 기본 추천으로 채워 넣을 수 있음 (선택)
    #     if routines:
    #         for d in DAYS_KR:
    #             # 이미 메인 블록이 없으면 루틴 1개 추천
    #             if not day_blocks[d]:
    #                 day_blocks[d].append(f"루틴: {routines[0]}")
    
    #     # --- 편집 가능하게 세션에 저장 ---
    #     if "day_edit" not in st.session_state:
    #         st.session_state.day_edit = {}
    #     if selected_week_key not in st.session_state.day_edit:
    #         st.session_state.day_edit[selected_week_key] = {d: list(day_blocks[d]) for d in DAYS_KR}
    
    #     # --- 월~일 가로 컬럼 구성 ---
    #     cols = st.columns(7)
    #     for i, d in enumerate(DAYS_KR):
    #         with cols[i]:
    #             st.markdown(f"**{d}**")
    #             # 현재 항목 (한 줄에 하나씩)
    #             current = st.session_state.day_edit[selected_week_key].get(d, [])
    #             text_value = "\n".join(current)
    #             new_text = st.text_area(
    #                 label="",
    #                 value=text_value,
    #                 key=f"dayedit::{selected_week_key}::{d}",
    #                 height=160,
    #                 placeholder="한 줄에 한 항목씩 입력"
    #             )
    #             st.session_state.day_edit[selected_week_key][d] = [
    #                 x.strip() for x in new_text.splitlines() if x.strip()
    #             ]
    
    #     st.markdown("---")
    #     st.markdown("### ✅ 이 주 요약표")
    #     rows = []
    #     for d in DAYS_KR:
    #         items = st.session_state.day_edit[selected_week_key].get(d, [])
    #         rows.append({"요일": d, "할 일": " | ".join(items) if items else "-"})
    #     week_df = pd.DataFrame(rows)
    #     st.dataframe(week_df, use_container_width=True)


    # ---

    DAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]
    
    # --- (전제) 주차 선택: 해당 주만 보이도록 ---
    # weeks = {"1주차 (10/7~10/13)": "week1", ...} 가 이미 있다고 가정
    selected_week_label = st.selectbox("📆 볼 주차를 선택하세요", list(weeks.keys()))
    selected_week_key = weeks[selected_week_label]
    
    # 주차 라벨에서 날짜 범위 파싱 (옵션)
    def parse_week_dates(week_label: str, year: int = None):
        if year is None:
            year = datetime.date.today().year
        rng = week_label.split("(")[1].strip(")")
        start_str, end_str = rng.split("~")
        sm, sd = map(int, start_str.split("/"))
        em, ed = map(int, end_str.split("/"))
        start = datetime.date(year, sm, sd)
        end = datetime.date(year, em, ed)
        days = [start + datetime.timedelta(days=i) for i in range((end - start).days + 1)]
        # 길이가 7이 아닐 수 있어도 표시 맞춤
        while len(days) < 7:
            days.append(days[-1] + datetime.timedelta(days=1))
        return days[:7]
    
    week_dates = parse_week_dates(selected_week_label)
    
    st.markdown(f"### 🗓 {selected_week_label} — 월~일 가로 블록 + 상세 플랜")
    
    # --- 이 주의 메인/루틴 가져오기 ---
    plan = st.session_state.weekly_plan.get(selected_week_key, {"focus": [], "routine": []})
    mains = plan.get("focus", [])[:2]  # 메인 최대 2개
    routines = plan.get("routine", [])
    
    if not mains:
        st.info("이 주차에 메인이 없습니다. 먼저 ‘주차별 메인/루틴’을 선택해주세요.")
        st.stop()
    
    main_a = mains[0]
    main_b = mains[1] if len(mains) > 1 else None
    
    # --- 자동 배치 로직 ---
    def auto_place_blocks(main_a: str, main_b: str | None, routines: list[str]):
        """
        월/수/금 → A, 화/목/금 → B, 금요일은 마무리/체크업,
        토/일은 미완료 보완/보충. 루틴은 요일별로 순환 삽입.
        """
        day_blocks = {d: [] for d in DAYS_KR}
    
        # 메인 배치
        assign_map = {
            "월": [("메인", main_a)],
            "화": [("메인", main_b if main_b else main_a)],
            "수": [("메인", main_a)],
            "목": [("메인", main_b if main_b else main_a)],
            "금": [("메인-마무리/체크업", main_a)]
        }
        if main_b:
            assign_map["금"].append(("메인-마무리/체크업", main_b))
    
        # 적용
        for d, items in assign_map.items():
            for tag, title in items:
                if title:
                    # 스텝 라벨 없이 핵심만 (UI엔 스텝 숨김)
                    day_blocks[d].append(f"{tag}: {title}")
    
        # 주말: 보완/보충/회고 제안
        day_blocks["토"].append("보완/보충: 이번 주 미완료 항목 처리")
        day_blocks["일"].append("회고/정리: 다음 주 준비")
    
        # 루틴을 요일별로 고르게 순환 삽입
        if routines:
            ri = 0
            for d in DAYS_KR:
                # 금요일엔 '마무리'가 있으니 루틴은 1개만 제안
                if d == "금":
                    day_blocks[d].append(f"루틴: {routines[ri % len(routines)]}"); ri += 1
                else:
                    # 평일 1~2개, 주말 1개 정도로 제안 (필요시 조절 가능)
                    day_blocks[d].append(f"루틴: {routines[ri % len(routines)]}"); ri += 1
    
        return day_blocks
    
    default_blocks = auto_place_blocks(main_a, main_b, routines)
    
    # --- ‘빈 플랜 박스’(상세 계획) + 자동 제안 블록 병기 ---
    if "day_detail" not in st.session_state:
        st.session_state.day_detail = {}
    if selected_week_key not in st.session_state.day_detail:
        st.session_state.day_detail[selected_week_key] = {d: [] for d in DAYS_KR}
    
    cols = st.columns(7)
    for i, d in enumerate(DAYS_KR):
        with cols[i]:
            date_tag = f" ({week_dates[i].month}/{week_dates[i].day})" if week_dates else ""
            st.markdown(f"**{d}{date_tag}**")
    
            # 자동 제안 블록(읽기용)
            if default_blocks[d]:
                st.caption("🔹 자동 제안")
                for item in default_blocks[d]:
                    st.write(f"- {item}")
    
            # 네가 직접 적는 ‘빈 플랜 박스’ (이게 요약표의 ‘해야할 일’로 반영됨)
            st.caption("✏️ 오늘 상세 플랜 (한 줄에 한 항목)")
            current_detail = st.session_state.day_detail[selected_week_key].get(d, [])
            new_text = st.text_area(
                label="",
                value="\n".join(current_detail),
                key=f"detail::{selected_week_key}::{d}",
                height=140,
                placeholder="예) 교수 3명 컨택 메일 발송\n예) 브랜드 스토리 문장 다듬기 30분\n예) 식단 기록 + 운동 30분"
            )
            st.session_state.day_detail[selected_week_key][d] = [
                line.strip() for line in new_text.splitlines() if line.strip()
            ]
    
    st.markdown("---")
    st.markdown("### ✅ 이 주 요약표 (당신이 적은 상세 플랜 기준)")
    
    # 요약표: 네가 적은 상세 플랜이 우선, 비어있으면 자동 제안으로 보완
    rows = []
    for i, d in enumerate(DAYS_KR):
        user_items = st.session_state.day_detail[selected_week_key].get(d, [])
        if user_items:
            items = user_items
        else:
            items = default_blocks[d] if default_blocks[d] else []
        rows.append({
            "요일": f"{d}",
            "날짜": f"{week_dates[i].month}/{week_dates[i].day}" if week_dates else "-",
            "해야할 일": " | ".join(items) if items else "-"
        })
    
    week_df = pd.DataFrame(rows)
    st.dataframe(week_df, use_container_width=True)
    
    # (선택) CSV 다운로드
    csv = week_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 이 주 계획 CSV 다운로드",
        data=csv,
        file_name=f"week_plan_{selected_week_key}.csv",
        mime="text/csv"
    )


    # ---
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

