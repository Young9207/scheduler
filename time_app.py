import streamlit as st
import pandas as pd
import re
import calendar
import datetime
import hashlib
import json
from pathlib import Path
import unicodedata
from collections import defaultdict, OrderedDict

# =========================
# Constants
# =========================
STATE_FILE = Path("state_storage.json")
STATE_KEYS = ["weekly_plan", "day_detail", "completed_by_day", "weekly_review", "default_blocks"]
DAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]
MONTH_MAP = {f"{i}월": i for i in range(1, 13)}

# =========================
# Utility functions
# =========================
def _normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).strip()
    s = re.sub(r"\s+", " ", s)
    return s

def _parse_pipe_or_lines(s: str):
    if not s:
        return []
    s = str(s)
    if "|" in s:
        parts = [x.strip() for x in s.split("|")]
    else:
        for sep in ["\n", ","]:
            if sep in s:
                parts = [x.strip() for x in s.split(sep)]
                break
        else:
            parts = [s.strip()]
    return [x for x in parts if x]

# =========================
# Week helpers
# =========================
def month_weeks(year: int, month: int, week_start: int = 0):
    cal = calendar.Calendar(firstweekday=week_start)
    weeks_meta, weeks_map = [], OrderedDict()
    for i, week_days in enumerate(cal.monthdatescalendar(year, month), start=1):
        start, end = week_days[0], week_days[-1]
        label = f"{i}주차 ({start.month}/{start.day}~{end.month}/{end.day})"
        key = f"week{i}"
        weeks_meta.append({"label": label, "key": key, "start": start, "end": end, "days": week_days})
        weeks_map[label] = key
    return weeks_meta, weeks_map

def find_current_week_label(weeks_meta, today=None):
    today = today or datetime.date.today()
    for w in weeks_meta:
        if w["start"] <= today <= w["end"]:
            return w["label"]
    return None

def parse_week_dates_from_label(week_label: str, year=None):
    year = year or datetime.date.today().year
    m = re.search(r"\((\d{1,2})/(\d{1,2})[~–-](\d{1,2})/(\d{1,2})\)", week_label)
    if not m:
        today = datetime.date.today()
        start = today - datetime.timedelta(days=today.weekday())
        return [start + datetime.timedelta(days=i) for i in range(7)]
    sm, sd, em, ed = map(int, m.groups())
    start, end = datetime.date(year, sm, sd), datetime.date(year, em, ed)
    return [start + datetime.timedelta(days=i) for i in range(7)]

# =========================
# Core planning logic
# =========================
def _build_virtual_plan(base_plan, suggestions, swaps, month_goals):
    import copy
    virtual = copy.deepcopy(base_plan)
    applied = []
    for wk, gid in suggestions:
        label = month_goals[gid]["label"]
        plan = virtual.get(wk, {"focus": [], "routine": []})
        if label not in plan["focus"] and len(plan["focus"]) < 2:
            plan["focus"].append(label)
            applied.append(("add", wk, label, "빈 슬롯에 최대선 배치"))
        virtual[wk] = plan
    for wk, gid in swaps:
        label = month_goals[gid]["label"]
        plan = virtual.get(wk, {"focus": [], "routine": []})
        plan["routine"] = [x for x in plan.get("routine", []) if _normalize_text(x) != gid]
        if label not in plan["focus"]:
            plan["focus"].append(label)
            if len(plan["focus"]) > 2:
                plan["focus"] = plan["focus"][-2:]
            applied.append(("promote", wk, label, "routine→focus 승격"))
        virtual[wk] = plan
    return virtual, applied

def generate_weekly_detail(selected_week_key, week_dates):
    plan = st.session_state.weekly_plan.get(selected_week_key, {"focus": [], "routine": []})
    mains, routines = plan.get("focus", [])[:2], plan.get("routine", [])
    main_a = mains[0] if len(mains) >= 1 else None
    main_b = mains[1] if len(mains) >= 2 else None

    detail = {}
    for date_obj in week_dates:
        d = DAYS_KR[date_obj.weekday()]
        detail[d] = {"main": [], "routine": []}
        if d in ["월", "수", "금"] and main_a:
            detail[d]["main"].append(main_a)
        if d in ["화", "목", "금"] and main_b:
            detail[d]["main"].append(main_b)
        if routines:
            detail[d]["routine"].append(routines[week_dates.index(date_obj) % len(routines)])
        if d == "토":
            detail[d]["main"].append("보완/미완료 항목 정리")
        elif d == "일":
            detail[d]["main"].append("회고 및 다음 주 준비")
    return detail

def _build_default_blocks_from_weekplan(week_key: str):
    blocks = {d: [] for d in DAYS_KR}
    plan = st.session_state.weekly_plan.get(week_key, {"focus": [], "routine": []})
    mains, routines = plan.get("focus", [])[:2], plan.get("routine", [])
    if mains:
        main_a = mains[0]
        main_b = mains[1] if len(mains) > 1 else None
        assign = {"월": [main_a], "화": [main_b or main_a], "수": [main_a], "목": [main_b or main_a], "금": [main_a, main_b]}
        for d, items in assign.items():
            for t in items:
                if t: blocks[d].append(f"메인: {t}")
    blocks["토"].append("보완/보충: 이번 주 미완료 항목 처리")
    blocks["일"].append("회고/정리: 다음 주 준비")
    if routines:
        for i, d in enumerate(DAYS_KR):
            blocks[d].append(f"배경: {routines[i % len(routines)]}")
    return blocks

# =========================
# Streamlit App
# =========================
st.set_page_config(page_title="Time Focus Flow", layout="wide")
st.title("🧠 주간 시간관리 웹앱")

# Init state
for k in STATE_KEYS:
    if k not in st.session_state:
        st.session_state[k] = {} if "review" not in k else ""

_today = datetime.date.today()
weeks_meta, weeks_map = month_weeks(_today.year, _today.month)
current_week_label = find_current_week_label(weeks_meta)
current_week_key = weeks_map.get(current_week_label, "week1")

# Select week
selected_week_label = st.selectbox("📆 주차 선택", list(weeks_map.keys()), index=list(weeks_map.keys()).index(current_week_label))
selected_week_key = weeks_map[selected_week_label]
week_dates = parse_week_dates_from_label(selected_week_label)

# Ensure blocks
if selected_week_key not in st.session_state.default_blocks:
    st.session_state.default_blocks[selected_week_key] = _build_default_blocks_from_weekplan(selected_week_key)

# =========================
# 상세 플랜 자동 생성
# =========================
st.markdown(f"### 🗓 {selected_week_label} — 주간 상세 플랜 자동 생성")
if st.button("⚙️ 자동 생성", use_container_width=True):
    st.session_state.day_detail[selected_week_key] = generate_weekly_detail(selected_week_key, week_dates)
    st.success("✅ 자동 생성 완료!")

if selected_week_key in st.session_state.day_detail:
    detail = st.session_state.day_detail[selected_week_key]
    rows = [{"날짜": d.strftime("%m/%d"), "요일": DAYS_KR[d.weekday()],
             "메인": " | ".join(detail[DAYS_KR[d.weekday()]]["main"]) or "-",
             "배경": " | ".join(detail[DAYS_KR[d.weekday()]]["routine"]) or "-"} for d in week_dates]
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)
    st.download_button("📥 CSV 다운로드", df.to_csv(index=False).encode("utf-8-sig"), f"week_detail_{selected_week_key}.csv")

# =========================
# 오늘 체크리스트
# =========================
st.markdown("---")
st.markdown("### ✅ 오늘의 실행 체크리스트")
today = datetime.date.today()
sel_day = DAYS_KR[min(today.weekday(), 6)]
st.caption(f"오늘은 **{sel_day}요일**입니다.")

# 보장
default_blocks = st.session_state.default_blocks[selected_week_key]
if selected_week_key not in st.session_state.day_detail:
    st.session_state.day_detail[selected_week_key] = {d: {"main": [], "routine": []} for d in DAYS_KR}
_detail = st.session_state.day_detail[selected_week_key][sel_day]

auto_items = default_blocks.get(sel_day, [])
auto_main = [x for x in auto_items if not x.startswith("배경:")]
auto_routine = [x for x in auto_items if x.startswith("배경:")]
final_main = _detail["main"] or auto_main
final_routine = _detail["routine"] or auto_routine

store_key = (selected_week_key, today.isoformat())
if store_key not in st.session_state.completed_by_day:
    st.session_state.completed_by_day[store_key] = set()
completed = st.session_state.completed_by_day[store_key]

tasks = [("[메인]", t) for t in final_main] + [("[배경]", t.replace("배경:", "").strip()) for t in final_routine]
for kind, text in tasks:
    label = f"{kind} {text}"
    key = hashlib.md5(f"{selected_week_key}|{label}".encode()).hexdigest()
    checked = st.checkbox(label, value=label in completed, key=key)
    if checked: completed.add(label)
    else: completed.discard(label)

if tasks:
    pct = int(len(completed) / len(tasks) * 100)
    st.progress(pct)
    st.write(f"📊 달성률: {pct}% ({len(completed)}/{len(tasks)})")
else:
    st.info("오늘 할 일이 없습니다.")

# =========================
# 회고
# =========================
st.markdown("---")
st.markdown("### 📝 이번 주 회고 메모")
review_text = st.text_area("이번 주를 돌아보며 남기고 싶은 메모", st.session_state.weekly_review.get(selected_week_key, ""), height=140)
st.session_state.weekly_review[selected_week_key] = review_text
