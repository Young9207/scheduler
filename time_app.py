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
# Constants & Globals
# =========================
STATE_FILE = Path("state_storage.json")
STATE_KEYS = ["weekly_plan", "day_detail", "completed_by_day", "weekly_review", "default_blocks"]
DAYS_KR = ["월","화","수","목","금","토","일"]
MONTH_MAP = {f"{i}월": i for i in range(1, 13)}

# =========================
# Utilities
# =========================
def _parse_pipe_or_lines(s: str):
    if not s:
        return []
    s = str(s)
    if "|" in s:
        parts = [x.strip() for x in s.split("|")]
    else:
        parts = []
        for sep in ["\n", ","]:
            if sep in s:
                parts = [x.strip() for x in s.split(sep)]
                break
        if not parts:
            parts = [s.strip()]
    return [x for x in parts if x]


def _normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _snapshot_weekly_plan(plan_dict):
    snap = {}
    for wk, v in plan_dict.items():
        snap[wk] = {"focus": list(v.get("focus", [])), "routine": list(v.get("routine", []))}
    return snap


# =========================
# Week/Calendar helpers
# =========================

def month_weeks(year: int, month: int, week_start: int = 0):
    """Return (weeks_meta, weeks_map)
    - weeks_meta: list of dicts [{label, key, start, end, days(list[date])}, ...]
    - weeks_map: OrderedDict label -> key (for quick lookup/selection)
    """
    cal = calendar.Calendar(firstweekday=week_start)
    weeks_meta = []
    weeks_map: "OrderedDict[str, str]" = OrderedDict()
    for i, week_days in enumerate(cal.monthdatescalendar(year, month), start=1):
        start = week_days[0]
        end = week_days[-1]
        label = f"{i}주차 ({start.month}/{start.day}~{end.month}/{end.day})"
        key = f"week{i}"
        weeks_meta.append({
            "label": label,
            "key": key,
            "start": start,
            "end": end,
            "days": week_days,
        })
        weeks_map[label] = key
    return weeks_meta, weeks_map


def find_current_week_label(weeks_meta, today_date: datetime.date | None = None):
    if today_date is None:
        today_date = datetime.date.today()
    for w in weeks_meta:
        if w["start"] <= today_date <= w["end"]:
            return w["label"]
    return None


def parse_week_dates_from_label(week_label: str, year: int | None = None):
    """Parse label '1주차 (10/7~10/13)' to list[date] length 7.
    Handles year rollovers (e.g., 12/30~1/5).
    """
    if year is None:
        year = datetime.date.today().year
    m = re.search(r"\((\d{1,2})/(\d{1,2})\s*[~–-]\s*(\d{1,2})/(\d{1,2})\)", week_label)
    if not m:
        today = datetime.date.today()
        start = today - datetime.timedelta(days=today.weekday())
        return [start + datetime.timedelta(days=i) for i in range(7)]
    sm, sd, em, ed = map(int, m.groups())

    start_year = year
    end_year = year + (1 if em < sm else 0)

    start = datetime.date(start_year, sm, sd)
    end = datetime.date(end_year, em, ed)
    days = [start + datetime.timedelta(days=i) for i in range((end - start).days + 1)]
    while len(days) < 7:
        days.append(days[-1] + datetime.timedelta(days=1))
    return days[:7]


# =========================
# Goal parsing & coverage
# =========================

def parse_goals(text: str):
    results = []
    current_section = None
    lines = str(text).strip().splitlines()
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
                results.append((current_section, item))
            continue
        if line.startswith("•"):
            item = line.lstrip("•").strip()
            section = current_section if current_section else "기타"
            results.append((section, item))
    return results


def build_month_goals(df: pd.DataFrame):
    """엑셀의 '최대선/최소선'을 파싱해서 월 전체 목표 dict 생성."""
    goals = {}
    seen = set()
    blocks = []
    if "최대선" in df.columns:
        blocks += [("max", x) for x in df["최대선"].dropna().tolist()]
    if "최소선" in df.columns:
        blocks += [("min", x) for x in df["최소선"].dropna().tolist()]

    for kind, text in blocks:
        parsed = parse_goals(str(text))
        for section, item in parsed:
            label = f"{section} - {item}"
            key = _normalize_text(label)
            if key in seen:
                continue
            seen.add(key)
            goals[key] = {
                "label": label,
                "kind": kind,
                "section": section,
                "item": item,
            }
    return goals


def compute_coverage(weeks_map: dict, weekly_plan: dict, month_goals: dict):
    """월 목표가 주차 포커스/배경에 얼마나 배치됐는지 확인."""
    cov = {gid: {"focus": 0, "routine": 0, "weeks": []} for gid in month_goals.keys()}
    week_focus_count = defaultdict(int)

    for _, wk in weeks_map.items():
        sel = weekly_plan.get(wk, {"focus": [], "routine": []})
        for bucket, name in [("focus", "focus"), ("routine", "routine")]:
            for raw in sel.get(name, []):
                gid = _normalize_text(raw)
                if gid in cov:
                    cov[gid][bucket] += 1
                    if wk not in cov[gid]["weeks"]:
                        cov[gid]["weeks"].append(wk)
        week_focus_count[wk] = len(sel.get("focus", []))

    num_weeks = len(weeks_map)
    total_focus_slots = num_weeks * 2
    max_goals = [gid for gid, g in month_goals.items() if g["kind"] == "max"]
    capacity_ok = total_focus_slots >= len(max_goals)

    missing_focus = [gid for gid in max_goals if cov[gid]["focus"] == 0]
    covered_focus = [gid for gid in max_goals if cov[gid]["focus"] >= 1]

    free_weeks = [wk for wk, c in week_focus_count.items() if c < 2]
    suggestions = []
    gi = 0
    for wk in free_weeks:
        if gi >= len(missing_focus):
            break
        suggestions.append((wk, missing_focus[gi]))
        gi += 1

    swaps = []
    if gi < len(missing_focus):
        crowded = [wk for wk, c in week_focus_count.items() if c >= 2]
        for wk in crowded:
            rts = weekly_plan.get(wk, {}).get("routine", [])
            r_norm = set(_normalize_text(x) for x in rts)
            for gid in missing_focus[gi:]:
                if gid in r_norm:
                    swaps.append((wk, gid))
                    gi += 1
                    if gi >= len(missing_focus):
                        break
            if gi >= len(missing_focus):
                break

    return {
        "capacity_ok": capacity_ok,
        "total_focus_slots": total_focus_slots,
        "num_max_goals": len(max_goals),
        "coverage": cov,
        "missing_focus": missing_focus,
        "covered_focus": covered_focus,
        "suggestions": suggestions,
        "swaps": swaps,
    }


# =========================
# State (load/save/reset)
# =========================

def _serialize_state(s):
    out = {}
    for k in STATE_KEYS:
        if k not in s:
            continue
        v = s[k]
        if k == "completed_by_day":
            conv = {}
            for tkey, val in v.items():
                if isinstance(tkey, tuple):
                    saved_key = "|".join(list(tkey))
                else:
                    saved_key = str(tkey)
                conv[saved_key] = list(val)
            out[k] = conv
        else:
            out[k] = v
    return out


def _deserialize_state(d):
    result = {}
    for k in STATE_KEYS:
        if k not in d:
            continue
        v = d[k]
        if k == "completed_by_day":
            conv = {}
            for skey, lst in v.items():
                parts = skey.split("|")
                tkey = tuple(parts) if len(parts) > 1 else (skey,)
                conv[tkey] = set(lst)
            result[k] = conv
        else:
            result[k] = v
    return result


def load_state():
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            restored = _deserialize_state(data)
            for k, v in restored.items():
                st.session_state[k] = v
            st.sidebar.success("저장된 상태를 불러왔어요.")
        except Exception as e:
            st.sidebar.warning(f"상태 불러오기 오류: {e}")


def save_state():
    try:
        payload = _serialize_state(st.session_state)
        STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        st.sidebar.info("상태 저장 완료.")
    except Exception as e:
        st.sidebar.error(f"상태 저장 실패: {e}")


def reset_state():
    for k in STATE_KEYS:
        if k in st.session_state:
            del st.session_state[k]
    if STATE_FILE.exists():
        STATE_FILE.unlink(missing_ok=True)
    st.sidebar.warning("상태를 초기화했어요.")


# =========================
# Default blocks from weekly plan + Ensurer
# =========================

def _build_default_blocks_from_weekplan(week_key: str):
    blocks = {d: [] for d in DAYS_KR}
    plan = st.session_state.weekly_plan.get(week_key, {"focus": [], "routine": []})
    mains = plan.get("focus", [])[:2]
    routines = plan.get("routine", [])

    if mains:
        main_a = mains[0]
        main_b = mains[1] if len(mains) > 1 else None
        assign = {
            "월": [("메인", main_a)],
            "화": [("메인", main_b if main_b else main_a)],
            "수": [("메인", main_a)],
            "목": [("메인", main_b if main_b else main_a)],
            "금": [("메인-마무리/체크업", main_a)],
        }
        if main_b:
            assign["금"].append(("메인-마무리/체크업", main_b))
        for d, items in assign.items():
            for tag, title in items:
                blocks[d].append(f"{tag}: {title}")

    blocks["토"].append("보완/보충: 이번 주 미완료 항목 처리")
    blocks["일"].append("회고/정리: 다음 주 준비")

    if routines:
        ri = 0
        for d in DAYS_KR:
            blocks[d].append(f"배경: {routines[ri % len(routines)]}")
            ri += 1
    return blocks


def ensure_default_blocks(selected_week_key: str):
    if "default_blocks" not in st.session_state:
        st.session_state.default_blocks = {}
    if selected_week_key not in st.session_state.default_blocks:
        st.session_state.default_blocks[selected_week_key] = _build_default_blocks_from_weekplan(selected_week_key)
    return st.session_state.default_blocks[selected_week_key]


# =========================
# Core planning: auto assign + weekly detail
# =========================

def auto_assign_weekly_plan(weeks_map: OrderedDict, goals_max: list[str], goals_min: list[str]):
    """각 주차 메인 1-2, 배경 최대 5를 라운드로빈 자동 배치."""
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


def generate_weekly_detail(selected_week_key: str, week_dates: list[datetime.date]):
    """
    메인 A/B 배치:
      - A: 월/수/금
      - B: 화/목/금
    주말:
      - 토: 보완/미완료
      - 일: 회고/다음주 준비
    배경: 요일 순환
    """
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
# Streamlit App
# =========================
st.set_page_config(page_title="Time Focus Flow", layout="wide")
st.title("🧠 주간 시간관리 웹앱")
st.markdown("분기/월 목표에서 ‘최대선/최소선’을 바탕으로 이번 주의 메인/배경을 자동 배치하고, A/B 패턴으로 일주일 스케줄을 생성한 뒤 디테일을 바로 편집/확정하세요.")

# Sidebar: state controls
with st.sidebar:
    st.markdown("### 💾 상태 관리")
    col_a, col_b, col_c = st.columns(3)
    if col_a.button("불러오기"):
        load_state()
    if col_b.button("저장하기"):
        save_state()
    if col_c.button("초기화"):
        reset_state()

# Ensure core session keys (weekly_review must be a dict)
for k in STATE_KEYS:
    if k not in st.session_state:
        if k in ("weekly_review",):
            st.session_state[k] = {}
        else:
            st.session_state[k] = {}

# =========================
# 1) Yearly 플랜 Excel 업로드 → 월 선택 → 목표 파싱
# =========================
st.markdown("### 📦 Yearly 플랜 Excel 업로드")
uploaded_file = st.file_uploader("📁 엑셀 파일 업로드 (최대선_최소선 시트 포함)", type=["xlsx"])

# default current month context
_today = datetime.date.today()
current_year = _today.year
current_month = _today.month

weeks_meta, weeks_map = month_weeks(current_year, current_month, week_start=0)

filtered = pd.DataFrame()
month_goals = {}

if uploaded_file:
    try:
        with st.expander("🔍 시트 미리보기", expanded=False):
            # reading sheet names might advance the stream pointer; we'll reset before actual read
            xls = pd.ExcelFile(uploaded_file)
            st.write("엑셀 시트 목록:", xls.sheet_names)
            uploaded_file.seek(0)
        df = pd.read_excel(uploaded_file, sheet_name="최대선_최소선")
        required_cols = {"프로젝트", "월", "최소선", "최대선"}
        missing = required_cols - set(df.columns)
        if missing:
            st.error(f"시트에 필요한 컬럼이 없습니다: {', '.join(sorted(missing))}")
        else:
            df = df[["프로젝트", "월", "최소선", "최대선", *(["측정지표"] if "측정지표" in df.columns else [])]]
            df = df.dropna(subset=["월"])  # type: ignore

            # 월 선택값을 안전하게 정수 월로 변환
            raw_months = sorted(df["월"].dropna().unique())
            display_months = [f"{int(m)}월" if isinstance(m, (int, float)) or (isinstance(m, str) and m.isdigit()) else str(m) for m in raw_months]
            selected_month = st.selectbox("📅 월을 선택하세요", display_months)

            def _to_month_num(mval: str) -> int:
                if mval in MONTH_MAP:
                    return MONTH_MAP[mval]
                mval2 = re.sub(r"[^0-9]", "", mval)
                return int(mval2) if mval2 else current_month

            month_num = _to_month_num(selected_month)
            year = current_year

            weeks_meta, weeks_map = month_weeks(year, month_num, week_start=0)

            # 원본 행 필터링 (원본 df의 월 값과 비교를 위해 숫자화)
            def _month_col_to_num(x):
                if isinstance(x, (int, float)):
                    return int(x)
                xs = str(x)
                m2 = re.sub(r"[^0-9]", "", xs)
                return int(m2) if m2 else None

            df = df.assign(__월숫자=df["월"].map(_month_col_to_num))
            filtered = df[df["__월숫자"] == month_num].reset_index(drop=True)
            st.markdown("#### 🔍 해당 월의 목표 원본 (최대선/최소선)")
            cols_show = [c for c in ["프로젝트", "최대선", "최소선"] if c in filtered.columns]
            st.dataframe(filtered[cols_show], use_container_width=True)

            # 월 목표 dict (kind: max/min)
            month_goals = build_month_goals(filtered)
            goals_max_all = [g["label"] for g in month_goals.values() if g["kind"] == "max"]
            goals_min_all = [g["label"] for g in month_goals.values() if g["kind"] == "min"]

            with st.expander("📌 파싱된 목표(라벨)", expanded=False):
                st.write("**최대선 후보(메인)**", goals_max_all)
                st.write("**최소선 후보(배경)**", goals_min_all)

            # 주차 자동 배치
            if st.button("⚙️ 이 달 목표로 주차 자동 배치 (메인 1–2 / 배경 5)", use_container_width=True, key="btn_auto_assign_month"):
                auto_assign_weekly_plan(weeks_map, goals_max_all, goals_min_all)
                st.success("주차별 메인/배경 자동 배치 완료!")

            # 커버리지 체크 (최대선 미배정/용량)
            if st.session_state.get("weekly_plan"):
                cov_res = compute_coverage(weeks_map, st.session_state.weekly_plan, month_goals)
                if not cov_res["capacity_ok"]:
                    st.error(
                        f"최대선 개수({cov_res['num_max_goals']})가 이번달 포커스 슬롯 수({cov_res['total_focus_slots']})보다 많습니다. "
                        "일부 최대선을 다음 달로 미루거나 우선순위를 조정하세요."
                    )
                else:
                    st.success(
                        f"포커스 슬롯 충분 ✅ (최대선 {cov_res['num_max_goals']}개 / 사용 가능 슬롯 {cov_res['total_focus_slots']}개)"
                    )
                missing_max_labels = [month_goals[gid]["label"] for gid in cov_res["missing_focus"]]
                if missing_max_labels:
                    st.warning("🧩 포커스로 배정되지 않은 ‘최대선’:\n- " + "\n- ".join(missing_max_labels))
                else:
                    st.info("모든 ‘최대선’이 최소 1회 이상 포커스로 배정되었습니다. 👍")

    except Exception as e:
        st.error(f"엑셀 처리 오류: {e}")

# =========================
# 2) (옵션) 이미 뽑아둔 weekly 계획표 불러오기
# =========================
st.markdown("### 📦 이미 뽑아둔 weekly 계획표 CSV 불러오기 (선택)")
uploaded_week_csv = st.file_uploader("📥 주간 계획표 CSV 업로드 (컬럼: 요일, 상세 플랜(메인), 상세 플랜(배경))", type=["csv"], key="restore_weekly_plan")
if uploaded_week_csv is not None:
    try:
        uploaded_week_csv.seek(0)
        try:
            dfw = pd.read_csv(uploaded_week_csv, encoding="utf-8-sig")
        except UnicodeDecodeError:
            uploaded_week_csv.seek(0)
            dfw = pd.read_csv(uploaded_week_csv, encoding="utf-8")

        required_cols = {"요일", "상세 플랜(메인)", "상세 플랜(배경)"}
        if not required_cols.issubset(dfw.columns):
            st.warning("CSV에 필요한 컬럼이 없습니다.")
        else:
            match = re.search(r"week\d+", uploaded_week_csv.name or "")
            week_key = match.group(0) if match else "week_manual"
            if week_key not in st.session_state.day_detail:
                st.session_state.day_detail[week_key] = {d: {"main": [], "routine": []} for d in DAYS_KR}
            for _, row in dfw.iterrows():
                day = str(row["요일"]).strip()
                if day in DAYS_KR:
                    st.session_state.day_detail[week_key][day]["main"] = _parse_pipe_or_lines(row["상세 플랜(메인)"])
                    st.session_state.day_detail[week_key][day]["routine"] = _parse_pipe_or_lines(row["상세 플랜(배경)"])
            st.session_state["selected_week_key_auto"] = week_key
            st.session_state["last_uploaded_week_csv"] = uploaded_week_csv.name
            st.success(f"✅ '{week_key}' 주간 계획표 자동 적용 완료!")
    except Exception as e:
        st.error(f"CSV 처리 오류: {e}")

# =========================
# 3) 주차 선택 & 보장
# =========================
if not uploaded_file:
    weeks_meta, weeks_map = month_weeks(current_year, current_month, week_start=0)

current_week_label = find_current_week_label(weeks_meta) or (weeks_meta[0]["label"] if weeks_meta else "")

options = list(weeks_map.keys())
default_index = options.index(current_week_label) if current_week_label in options else 0
selected_week_label = st.selectbox("📆 체크할 주 차를 선택하세요", options, index=default_index)
selected_week_key = weeks_map[selected_week_label]
selected_week_key = st.session_state.get("selected_week_key_auto", selected_week_key)

# parse dates (use current_year by default; rollover handled inside)
week_dates = parse_week_dates_from_label(selected_week_label, year=current_year)
ensure_default_blocks(selected_week_key)

# =========================
# 4) 이 주 상세 플랜 (날짜 기준, 자동생성 + 편집 + 확정 CSV)
# =========================
st.markdown(f"### 🗓 {selected_week_label} — 날짜 기준 상세 플랜")
week_plan = st.session_state.weekly_plan.get(selected_week_key, {"focus": [], "routine": []})
st.info(f"**메인(최대 2):** {' | '.join(week_plan.get('focus', [])[:2]) or '-'}")
st.info(f"**배경(최대 5):** {' | '.join(week_plan.get('routine', [])[:5]) or '-'}")

if st.button("⚙️ 기본 스케줄 자동 생성 (A:월수금 / B:화목금, 토:보완 / 일:회고)",
             key=f"btn_gen_detail_{selected_week_key}", use_container_width=True):
    st.session_state.day_detail[selected_week_key] = generate_weekly_detail(selected_week_key, week_dates)
    ensure_default_blocks(selected_week_key)
    st.success("✅ 자동 생성 완료!")

if "day_detail" not in st.session_state:
    st.session_state.day_detail = {}
if selected_week_key not in st.session_state.day_detail:
    st.session_state.day_detail[selected_week_key] = {d: {"main": [], "routine": []} for d in DAYS_KR}


def _join_for_cell(items):
    return " | ".join(items) if items else ""


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
    df_edit, hide_index=True, use_container_width=True, num_rows="fixed",
    key=f"editor::{selected_week_key}::date"
)
for _, row in edited.iterrows():
    dkr = row["요일"]
    st.session_state.day_detail[selected_week_key][dkr]["main"] = _parse_pipe_or_lines(row["메인(편집)"])
    st.session_state.day_detail[selected_week_key][dkr]["routine"] = _parse_pipe_or_lines(row["배경(편집)"])

# 확정 미리보기 + CSV
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

# =========================
# 5) 이번달 주간 요약 (선택)
# =========================
st.markdown("### 🗂 이번 달 주간 요약 미리보기")
if st.session_state.get("weekly_plan"):
    summary_rows = []
    for label, wk in weeks_map.items():
        plan = st.session_state.weekly_plan.get(wk, {"focus": [], "routine": []})
        summary_rows.append({
            "주차": label,
            "메인 포커스": " | ".join(plan.get("focus", [])) or "-",
            "배경": " | ".join(plan.get("routine", [])) or "-",
        })
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)
else:
    st.caption("아직 주간 계획(포커스/배경)이 없습니다. 엑셀 업로드 후 자동 배치를 눌러보세요.")

# =========================
# 6) 오늘 체크리스트
# =========================
st.markdown("---")
st.markdown("### ✅ 오늘의 실행 체크리스트")

# 오늘 요일 텍스트 (월~일)
_today2 = datetime.date.today()
sel_day = DAYS_KR[min(_today2.weekday(), 6)]
st.caption(f"오늘은 **{sel_day}요일**입니다.")

default_blocks = ensure_default_blocks(selected_week_key)

if selected_week_key not in st.session_state.day_detail:
    st.session_state.day_detail[selected_week_key] = {d: {"main": [], "routine": []} for d in DAYS_KR}
_detail = st.session_state.day_detail[selected_week_key][sel_day]

auto_items = default_blocks.get(sel_day, [])
auto_main = [x for x in auto_items if not x.startswith("배경:")]
auto_routine = [x for x in auto_items if x.startswith("배경:")]
final_main = _detail["main"] or auto_main
final_routine = _detail["routine"] or auto_routine

store_key = (selected_week_key, _today2.isoformat())
if store_key not in st.session_state.completed_by_day:
    st.session_state.completed_by_day[store_key] = set()
completed = st.session_state.completed_by_day[store_key]

tasks = ([("[메인]", t) for t in final_main] +
         [("[배경]", t.replace("배경:", "").strip()) for t in final_routine])
for kind, text in tasks:
    label = f"{kind} {text}"
    key = "chk_" + hashlib.md5(f"{selected_week_key}|{label}".encode("utf-8")).hexdigest()
    checked = st.checkbox(label, value=(label in completed), key=key)
    if checked:
        completed.add(label)
    else:
        completed.discard(label)

if tasks:
    pct = int(len(completed) / len(tasks) * 100)
    st.progress(pct)
    st.write(f"📊 달성률: **{pct}%** ({len(completed)} / {len(tasks)})")
else:
    st.info("오늘 할 일이 없습니다.")

with st.expander("📋 오늘 체크 내역 보기/내보내기", expanded=False):
    rows = [{"날짜": _today2.isoformat(), "유형": kind, "할 일": text, "완료": (f"{kind} {text}" in completed)} for kind, text in tasks]
    df_today = pd.DataFrame(rows)
    st.dataframe(df_today, use_container_width=True)
    csv_today = df_today.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 오늘 체크 내역 CSV 다운로드",
        data=csv_today,
        file_name=f"today_tasks_{selected_week_key}_{_today2.isoformat()}.csv",
        mime="text/csv",
        key=f"dl_today_{selected_week_key}"
    )

# =========================
# 7) Weekly review notes
# =========================
st.markdown("### 📝 이번 주 회고 메모")
current_review = st.session_state.weekly_review.get(selected_week_key, "")
review_text = st.text_area(
    "이번 주를 돌아보며 남기고 싶은 메모",
    value=current_review,
    key=f"review::{selected_week_key}",
    height=140,
    placeholder="이번 주 무엇을 배웠는지, 다음 주에 개선할 1가지만 적어도 좋아요.",
)
st.session_state.weekly_review[selected_week_key] = review_text
