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
# Utility
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

def _snapshot_weekly_plan(plan_dict: dict):
    snap = {}
    for wk, v in plan_dict.items():
        snap[wk] = {"focus": list(v.get("focus", [])), "routine": list(v.get("routine", []))}
    return snap

# =========================
# Calendar helpers
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
    return weeks_meta[0]["label"] if weeks_meta else None

def parse_week_dates_from_label(week_label: str, year=None):
    year = year or datetime.date.today().year
    m = re.search(r"\((\d{1,2})/(\d{1,2})\s*[~–-]\s*(\d{1,2})/(\d{1,2})\)", week_label)
    if not m:
        today = datetime.date.today()
        start = today - datetime.timedelta(days=today.weekday())
        return [start + datetime.timedelta(days=i) for i in range(7)]
    sm, sd, em, ed = map(int, m.groups())
    start = datetime.date(year, sm, sd)
    # 7일 표 고정
    return [start + datetime.timedelta(days=i) for i in range(7)]

# =========================
# Goal parsing (엑셀: 최대선_최소선)
# =========================
def parse_goals(text: str):
    """[섹션] •아이템 형태를 안전하게 파싱 (없어도 전체 문자열을 아이템으로 처리)"""
    if not str(text).strip():
        return []
    results = []
    current_section = None
    lines = str(text).splitlines()
    found_bullet = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        header_match = re.match(r"\[(.*?)\]", line)
        if header_match:
            current_section = header_match.group(1).strip()
            after = line[header_match.end():].strip()
            if after.startswith("•"):
                item = after.lstrip("•").strip()
                results.append((current_section or "기타", item))
                found_bullet = True
            continue
        if line.startswith("•"):
            results.append((current_section or "기타", line.lstrip("•").strip()))
            found_bullet = True
    if not found_bullet:
        # 불릿이 없으면, 전체 텍스트를 한 항목으로
        results.append(("기타", str(text).strip()))
    return results

def build_month_goals(df_month):
    """선택한 월의 최대선/최소선을 (섹션 - 아이템) 목록으로 전개"""
    goals_max, goals_min = [], []
    if "최대선" in df_month.columns:
        for x in df_month["최대선"].dropna():
            goals_max += [f"{s} - {i}" for s, i in parse_goals(x)]
    if "최소선" in df_month.columns:
        for x in df_month["최소선"].dropna():
            goals_min += [f"{s} - {i}" for s, i in parse_goals(x)]
    # 중복 제거 (정규화 기반)
    def _dedup_keep_order(items):
        seen, out = set(), []
        for it in items:
            k = _normalize_text(it)
            if k not in seen:
                seen.add(k)
                out.append(it)
        return out
    return _dedup_keep_order(goals_max), _dedup_keep_order(goals_min)

# =========================
# Auto weekly plan from month goals
# =========================
def auto_assign_weekly_plan(weeks_map: OrderedDict, goals_max: list[str], goals_min: list[str]):
    """각 주차별 포커스(최대선) 1-2개, 배경(최소선) 5개 자동 배치 (라운드로빈)"""
    if "weekly_plan" not in st.session_state:
        st.session_state.weekly_plan = {}
    gi_max, gi_min = 0, 0
    for _, wk in weeks_map.items():
        f, r = [], []
        for _ in range(2):
            if goals_max:
                f.append(goals_max[gi_max % len(goals_max)])
                gi_max += 1
        for _ in range(5):
            if goals_min:
                r.append(goals_min[gi_min % len(goals_min)])
                gi_min += 1
        st.session_state.weekly_plan[wk] = {"focus": f, "routine": r}

# =========================
# Build default blocks (A/B 패턴 + 주말)
# =========================
def _build_default_blocks_from_weekplan(week_key: str):
    blocks = {d: [] for d in DAYS_KR}
    plan = st.session_state.weekly_plan.get(week_key, {"focus": [], "routine": []})
    mains, routines = plan.get("focus", [])[:2], plan.get("routine", [])
    main_a = mains[0] if len(mains) >= 1 else None
    main_b = mains[1] if len(mains) >= 2 else None

    assign = {
        "월": [main_a],
        "화": [main_b if main_b else main_a],
        "수": [main_a],
        "목": [main_b if main_b else main_a],
        "금": [main_a] + ([main_b] if main_b else []),
        "토": ["보완/보충: 이번 주 미완료 항목 처리"],
        "일": ["회고/정리: 다음 주 준비"],
    }
    for d, items in assign.items():
        for t in items:
            if t:
                if t.startswith("보완") or t.startswith("회고"):
                    blocks[d].append(t)
                else:
                    blocks[d].append(f"메인: {t}")

    if routines:
        for i, d in enumerate(DAYS_KR):
            blocks[d].append(f"배경: {routines[i % len(routines)]}")
    return blocks

# =========================
# Weekly detail generator (편집용 원본)
# =========================
def generate_weekly_detail(selected_week_key: str, week_dates: list[datetime.date]):
    """메인A/B 패턴: A=월수금, B=화목금 / 주말 보완·회고 / 배경 루틴 순환"""
    plan = st.session_state.weekly_plan.get(selected_week_key, {"focus": [], "routine": []})
    mains, routines = plan.get("focus", [])[:2], plan.get("routine", [])
    main_a = mains[0] if len(mains) >= 1 else None
    main_b = mains[1] if len(mains) >= 2 else None

    detail = {d: {"main": [], "routine": []} for d in DAYS_KR}
    for idx, date_obj in enumerate(week_dates):
        d = DAYS_KR[date_obj.weekday()]
        if d in ["월", "수", "금"] and main_a:
            detail[d]["main"].append(main_a)
        if d in ["화", "목", "금"] and main_b:
            detail[d]["main"].append(main_b)
        if routines:
            detail[d]["routine"].append(routines[idx % len(routines)])
        if d == "토":
            detail[d]["main"].append("보완/미완료 항목 정리")
        if d == "일":
            detail[d]["main"].append("회고 및 다음 주 준비")
    return detail

# =========================
# Coverage (제안)
# =========================
def compute_coverage(weeks_map: OrderedDict, weekly_plan: dict, goals_max: list[str], goals_min: list[str]):
    """최대선/최소선이 주 전체에 포커스/배경으로 들어갔는지 체크"""
    norm = lambda xs: {_normalize_text(x): x for x in xs}
    need_max, need_min = set(norm(goals_max).keys()), set(norm(goals_min).keys())

    covered_max, covered_min = set(), set()
    for wk in weeks_map.values():
        sel = weekly_plan.get(wk, {"focus": [], "routine": []})
        for f in sel.get("focus", []):
            covered_max.add(_normalize_text(f))
        for r in sel.get("routine", []):
            covered_min.add(_normalize_text(r))

    missing_max = [x for x in goals_max if _normalize_text(x) not in covered_max]
    missing_min = [x for x in goals_min if _normalize_text(x) not in covered_min]
    return missing_max, missing_min

# =========================
# App
# =========================
st.set_page_config(page_title="Time Focus Flow", layout="wide")
st.title("🧠 주간 시간관리 웹앱")

# Init state
for k in STATE_KEYS:
    if k not in st.session_state:
        st.session_state[k] = {} if k not in ("weekly_review",) else {}

# ===== 0) Excel 업로드 & 월 선택 =====
st.markdown("### 📦 Yearly 플랜 Excel 업로드")
uploaded_file = st.file_uploader("📁 '최대선_최소선' 시트가 있는 엑셀 업로드", type=["xlsx"], key="upload_yearly")
weeks_meta_base, weeks_map_base = month_weeks(datetime.date.today().year, datetime.date.today().month, week_start=0)

goals_max_all, goals_min_all = [], []
weeks_meta, weeks_map = weeks_meta_base, weeks_map_base
selected_month = None

if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    if "최대선_최소선" not in xls.sheet_names:
        st.error("시트 '최대선_최소선' 을 찾을 수 없습니다.")
    else:
        df_all = pd.read_excel(uploaded_file, sheet_name="최대선_최소선")
        # 필요한 컬럼만 유지(있으면)
        keep_cols = [c for c in ["프로젝트", "월", "최소선", "최대선", "측정지표"] if c in df_all.columns]
        df_all = df_all[keep_cols]
        months = sorted(df_all["월"].dropna().unique()) if "월" in df_all.columns else []
        selected_month = st.selectbox("📅 월 선택", months) if months else None

        if selected_month is not None:
            year = datetime.date.today().year
            month_num = MONTH_MAP.get(selected_month, None)
            if month_num:
                weeks_meta, weeks_map = month_weeks(year, month_num, week_start=0)
            df_month = df_all[df_all["월"] == selected_month] if "월" in df_all.columns else df_all
            goals_max_all, goals_min_all = build_month_goals(df_month)

            with st.expander("🔍 이 달 목표(전개본)"):
                st.write("**최대선 후보**", goals_max_all)
                st.write("**최소선 후보**", goals_min_all)

            # 1) 주차 자동 배치
            if st.button("⚙️ 이 달 목표로 주차 자동 배치", use_container_width=True, key="btn_auto_assign"):
                auto_assign_weekly_plan(weeks_map, goals_max_all, goals_min_all)
                st.success("주차별 메인(최대선)/배경(최소선) 자동 배치 완료!")

            # 2) 커버리지 제안
            if st.session_state.get("weekly_plan"):
                miss_max, miss_min = compute_coverage(weeks_map, st.session_state.weekly_plan, goals_max_all, goals_min_all)
                if miss_max or miss_min:
                    st.warning("🧩 커버리지 제안")
                    if miss_max:
                        st.write("• 포커스로 배정되지 않은 **최대선**:", miss_max)
                    if miss_min:
                        st.write("• 배경으로 배정되지 않은 **최소선**:", miss_min)
                else:
                    st.info("모든 최대선/최소선이 최소 1회 이상 배정되었습니다. 👍")

# ===== 1) 주차 선택 =====
current_week_label = find_current_week_label(weeks_meta)
selected_week_label = st.selectbox("📆 주차 선택", list(weeks_map.keys()), index=list(weeks_map.keys()).index(current_week_label))
selected_week_key = weeks_map[selected_week_label]
week_dates = parse_week_dates_from_label(selected_week_label)

# 보장: weekly_plan / default_blocks / day_detail
if "weekly_plan" not in st.session_state:
    st.session_state.weekly_plan = {}
if selected_week_key not in st.session_state.weekly_plan:
    st.session_state.weekly_plan[selected_week_key] = {"focus": [], "routine": []}
if "default_blocks" not in st.session_state:
    st.session_state.default_blocks = {}
if selected_week_key not in st.session_state.default_blocks:
    st.session_state.default_blocks[selected_week_key] = _build_default_blocks_from_weekplan(selected_week_key)
if "day_detail" not in st.session_state:
    st.session_state.day_detail = {}
if selected_week_key not in st.session_state.day_detail:
    st.session_state.day_detail[selected_week_key] = {d: {"main": [], "routine": []} for d in DAYS_KR}

# ===== 2) 이 주 개요 =====
st.markdown("---")
st.markdown(f"### 🗓 {selected_week_label} — 이 주 개요")
wk_plan = st.session_state.weekly_plan.get(selected_week_key, {"focus": [], "routine": []})
st.info(f"**메인 포커스(최대 2):** {' | '.join(wk_plan.get('focus', [])[:2]) or '-'}")
st.info(f"**배경 루틴(최대 5):** {' | '.join(wk_plan.get('routine', [])[:5]) or '-'}")

# ===== 3) 주간 상세 자동 생성 + 표 편집 =====
st.markdown("#### ✍️ 이 주 상세 플랜 (날짜 기준, 표에서 직접 편집)")

colA, colB = st.columns([1,1])
with colA:
    if st.button("⚙️ 기본 스케줄 자동 생성 (A:월수금 / B:화목금, 토:보완 / 일:회고)", key=f"btn_gen_{selected_week_key}", use_container_width=True):
        st.session_state.day_detail[selected_week_key] = generate_weekly_detail(selected_week_key, week_dates)
        st.session_state.default_blocks[selected_week_key] = _build_default_blocks_from_weekplan(selected_week_key)
        st.success("✅ 자동 생성 완료!")

# 표 데이터 구성 (날짜 순)
def _join_for_cell(items): return " | ".join(items) if items else ""
table_rows = []
for date_obj in week_dates:
    dkr = DAYS_KR[date_obj.weekday()]
    table_rows.append({
        "날짜": date_obj.strftime("%m/%d"),
        "요일": dkr,
        "메인(편집)": _join_for_cell(st.session_state.day_detail[selected_week_key][dkr]["main"]),
        "배경(편집)": _join_for_cell(st.session_state.day_detail[selected_week_key][dkr]["routine"]),
    })
df_edit = pd.DataFrame(table_rows, columns=["날짜", "요일", "메인(편집)", "배경(편집)"])

edited = st.data_editor(
    df_edit,
    hide_index=True,
    use_container_width=True,
    num_rows="fixed",
    key=f"editor::{selected_week_key}",
)
# 편집 반영
for _, row in edited.iterrows():
    dkr = row["요일"]
    st.session_state.day_detail[selected_week_key][dkr]["main"] = _parse_pipe_or_lines(row["메인(편집)"])
    st.session_state.day_detail[selected_week_key][dkr]["routine"] = _parse_pipe_or_lines(row["배경(편집)"])

# ===== 4) 최종 확정 CSV =====
st.markdown("#### ✅ 확정본 내보내기 (CSV)")
final_rows = []
for date_obj in week_dates:
    dkr = DAYS_KR[date_obj.weekday()]
    final_rows.append({
        "날짜": date_obj.strftime("%Y-%m-%d"),
        "요일": dkr,
        "메인": " | ".join(st.session_state.day_detail[selected_week_key][dkr]["main"]) or "-",
        "배경": " | ".join(st.session_state.day_detail[selected_week_key][dkr]["routine"]) or "-",
    })
df_final = pd.DataFrame(final_rows)
st.dataframe(df_final, use_container_width=True)
st.download_button(
    "📥 이 주 확정본 CSV 다운로드",
    data=df_final.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"week_final_{selected_week_key}.csv",
    mime="text/csv",
    key=f"dl_final_{selected_week_key}"
)

# ===== 5) 오늘 체크리스트 =====
st.markdown("---")
st.markdown("### ✅ 오늘의 실행 체크리스트")

today = datetime.date.today()
sel_day = DAYS_KR[min(today.weekday(), 6)]
st.caption(f"오늘은 **{sel_day}요일**입니다.")

default_blocks = st.session_state.default_blocks[selected_week_key]
_detail = st.session_state.day_detail[selected_week_key][sel_day]
auto_items = default_blocks.get(sel_day, [])
auto_main = [x for x in auto_items if not x.startswith("배경:")]
auto_routine = [x for x in auto_items if x.startswith("배경:")]
final_main = _detail["main"] or [x.replace("메인:","").strip() for x in auto_main]
final_routine = _detail["routine"] or [x.replace("배경:","").strip() for x in auto_routine]

store_key = (selected_week_key, today.isoformat())
if store_key not in st.session_state.completed_by_day:
    st.session_state.completed_by_day[store_key] = set()
completed = st.session_state.completed_by_day[store_key]

tasks = [("[메인]", t) for t in final_main] + [("[배경]", t) for t in final_routine]
for kind, text in tasks:
    label = f"{kind} {text}"
    key = "chk_" + hashlib.md5(f"{selected_week_key}|{today.isoformat()}|{label}".encode()).hexdigest()
    checked = st.checkbox(label, value=(label in completed), key=key)
    if checked: completed.add(label)
    else: completed.discard(label)

if tasks:
    pct = int(len(completed) / len(tasks) * 100)
    st.progress(pct)
    st.write(f"📊 달성률: {pct}% ({len(completed)}/{len(tasks)})")
else:
    st.info("오늘 할 일이 없습니다.")

# ===== 6) 주간 회고 =====
st.markdown("---")
st.markdown("### 📝 이번 주 회고 메모")
if "weekly_review" not in st.session_state:
    st.session_state.weekly_review = {}
review_text = st.text_area(
    "이번 주를 돌아보며 남기고 싶은 메모",
    value=st.session_state.weekly_review.get(selected_week_key, ""),
    height=140,
    key=f"review::{selected_week_key}",
)
st.session_state.weekly_review[selected_week_key] = review_text
