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
STATE_KEYS = ["weekly_plan", "day_detail", "completed_by_day", "weekly_review"]
DAYS_KR = ["월","화","수","목","금","토","일"]
MONTH_MAP = {f"{i}월": i for i in range(1, 13)}

# =========================
# Utilities
# =========================
def _build_virtual_plan(base_plan, suggestions, swaps, month_goals):
    """원본을 건드리지 않고 제안을 적용한 가상 계획을 생성"""
    import copy
    virtual = copy.deepcopy(base_plan)
    applied = []

    # 1) 빈 슬롯에 최대선 추가
    for wk, gid in suggestions:
        label = month_goals[gid]["label"]
        plan = virtual.get(wk, {"focus": [], "routine": []})
        if label not in plan["focus"] and len(plan["focus"]) < 2:
            plan["focus"].append(label)
            applied.append(("add", wk, label, "빈 슬롯에 최대선 배치"))
        virtual[wk] = plan

    # 2) routine → focus 승격 (2개 제한 유지)
    for wk, gid in swaps:
        label = month_goals[gid]["label"]
        plan = virtual.get(wk, {"focus": [], "routine": []})
        # routine에서 제거
        plan["routine"] = [x for x in plan.get("routine", []) if _normalize_text(x) != gid]
        if label not in plan["focus"]:
            plan["focus"].append(label)
            if len(plan["focus"]) > 2:
                # 가장 앞쪽 것을 잘라서 2개 유지
                dropped = plan["focus"][:-2]
                plan["focus"] = plan["focus"][-2:]
                for dlab in dropped:
                    applied.append(("drop", wk, dlab, "과밀 조정(2개 제한)"))
            applied.append(("promote", wk, label, "routine→focus 승격"))
        virtual[wk] = plan

    return virtual, applied

def generate_weekly_detail(selected_week_key, week_dates):
    """메인/루틴 기반으로 주간 디테일 자동 생성"""
    plan = st.session_state.weekly_plan.get(selected_week_key, {"focus": [], "routine": []})
    mains = plan.get("focus", [])[:2]
    routines = plan.get("routine", [])

    main_a = mains[0] if len(mains) >= 1 else None
    main_b = mains[1] if len(mains) >= 2 else None

    detail = {}
    for date_obj in week_dates:
        weekday_kr = DAYS_KR[date_obj.weekday()]
        detail[weekday_kr] = {"main": [], "routine": []}

        # --- 메인 패턴 ---
        if weekday_kr in ["월", "수", "금"] and main_a:
            detail[weekday_kr]["main"].append(main_a)
        if weekday_kr in ["화", "목", "금"] and main_b:
            detail[weekday_kr]["main"].append(main_b)

        # --- 배경 루틴 분배 ---
        if routines:
            idx = week_dates.index(date_obj) % len(routines)
            detail[weekday_kr]["routine"].append(routines[idx])

        # --- 주말 처리 ---
        if weekday_kr == "토":
            detail[weekday_kr]["main"].append("보완/미완료 항목 정리")
        elif weekday_kr == "일":
            detail[weekday_kr]["main"].append("회고 및 다음 주 준비")

    return detail
    
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
    The function covers all weeks touching the month using calendar.monthdatescalendar.
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
    """Parse label of the form '1주차 (10/7~10/13)' or '1주차 (10/7–10/13)' to list[date] length 7.
    Falls back to current year if not given.
    """
    if year is None:
        year = datetime.date.today().year
    m = re.search(r"\((\d{1,2})/(\d{1,2})\s*[~–-]\s*(\d{1,2})/(\d{1,2})\)", week_label)
    if not m:
        # fallback: return current week's dates
        today = datetime.date.today()
        start = today - datetime.timedelta(days=today.weekday())
        return [start + datetime.timedelta(days=i) for i in range(7)]
    sm, sd, em, ed = map(int, m.groups())
    start = datetime.date(year, sm, sd)
    end = datetime.date(year, em, ed)
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
    lines = text.strip().splitlines()
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


def build_month_goals(df):
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
    cov = {gid: {"focus": 0, "routine": 0, "weeks": []} for gid in month_goals.keys()}
    week_focus_count = defaultdict(int)

    for wk in weeks_map.values():
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
# Default blocks from weekly plan
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


def auto_place_blocks(main_a: str, main_b: str | None, routines: list[str]):
    day_blocks = {d: [] for d in DAYS_KR}
    assign_map = {
        "월": [("메인", main_a)],
        "화": [("메인", main_b if main_b else main_a)],
        "수": [("메인", main_a)],
        "목": [("메인", main_b if main_b else main_a)],
        "금": [("메인-마무리/체크업", main_a)],
    }
    if main_b:
        assign_map["금"].append(("메인-마무리/체크업", main_b))
    for d, items in assign_map.items():
        for tag, title in items:
            if title:
                day_blocks[d].append(f"{tag}: {title}")
    day_blocks["토"].append("보완/보충: 이번 주 미완료 항목 처리")
    day_blocks["일"].append("회고/정리: 다음 주 준비")
    if routines:
        ri = 0
        for d in DAYS_KR:
            day_blocks[d].append(f"배경: {routines[ri % len(routines)]}")
            ri += 1
    return day_blocks


# =========================
# Streamlit App
# =========================
st.set_page_config(page_title="Time Focus Flow", layout="wide")
st.title("🧠 주간 시간관리 웹앱")
st.markdown("분기/월 목표에서 이번 주의 메인 목표를 선택하고, 실행 배경을 설계하세요.")

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

# Ensure core session keys
for k, default in (
    ("weekly_plan", {}),
    ("day_detail", {}),
    ("completed_by_day", {}),
    ("weekly_review", {}),
    ("default_blocks", {}),
):
    if k not in st.session_state:
        st.session_state[k] = default

# =========================
# 0) Optional: Load pre-baked weekly day-detail CSV (auto-apply)
# =========================
st.markdown("### 📦 이미 뽑아둔 weekly 계획표 불러오기")
uploaded_week_csv = st.file_uploader("📥 주간 계획표 CSV 업로드", type=["csv"], key="restore_weekly_plan")
if uploaded_week_csv is not None:
    try:
        uploaded_week_csv.seek(0)
        try:
            df = pd.read_csv(uploaded_week_csv, encoding="utf-8-sig")
        except UnicodeDecodeError:
            uploaded_week_csv.seek(0)
            df = pd.read_csv(uploaded_week_csv, encoding="utf-8")

        required_cols = {"요일", "상세 플랜(메인)", "상세 플랜(배경)"}
        if not required_cols.issubset(df.columns):
            st.warning("CSV에 필요한 컬럼이 없습니다.")
        else:
            match = re.search(r"week\d+", uploaded_week_csv.name or "")
            week_key = match.group(0) if match else "week_manual"
            if week_key not in st.session_state.day_detail:
                st.session_state.day_detail[week_key] = {d: {"main": [], "routine": []} for d in DAYS_KR}
            for _, row in df.iterrows():
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
# 1) Monthly-Weekly plan CSV (virtual/original)
# =========================
st.markdown("### 📦 montly-weekly 플랜 CSV 업로드 (가상/원본 둘 다 지원)")
uploaded_plan_csv = st.file_uploader("📥 주차 플랜 CSV 업로드 (예: weekly_plan_virtual.csv)", type=["csv"], key="weekly_plan_csv")


def _pick_first_existing(cols, candidates):
    for c in candidates:
        if c in cols:
            return c
    return None

# Prepare base calendar (fallback when we don't yet have monthly excel)
_today = datetime.date.today()
weeks_meta, weeks_map = month_weeks(_today.year, _today.month, week_start=0)

if uploaded_plan_csv is not None:
    try:
        uploaded_plan_csv.seek(0)
        try:
            df_plan = pd.read_csv(uploaded_plan_csv, encoding="utf-8-sig")
        except UnicodeDecodeError:
            uploaded_plan_csv.seek(0)
            df_plan = pd.read_csv(uploaded_plan_csv, encoding="utf-8")

        st.markdown("#### 🗂 업로드한 주차 플랜 미리보기")
        st.dataframe(df_plan, use_container_width=True)

        if "주차" not in df_plan.columns:
            st.warning("이 파일에는 '주차' 컬럼이 없습니다. (예: '1주차 (10/7~10/13)')")
        else:
            focus_col = _pick_first_existing(df_plan.columns, ["포커스(가상)", "메인 포커스", "포커스"])
            routine_col = _pick_first_existing(df_plan.columns, ["배경(가상)", "배경"])
            if focus_col is None and routine_col is None:
                st.warning("포커스/배경 컬럼을 찾지 못했습니다. (예: '포커스(가상)', '배경(가상)' 또는 '메인 포커스', '배경')")
            else:
                updated_rows = 0
                first_week_key_seen = None
                for _, row in df_plan.fillna("").iterrows():
                    label = str(row["주차"]).strip()
                    if not label:
                        continue
                    if label in weeks_map:
                        wk = weeks_map[label]
                    else:
                        m = re.search(r"(\d+)\s*주차", label)
                        wk = f"week{int(m.group(1))}" if m else "week_" + hashlib.md5(label.encode("utf-8")).hexdigest()[:8]
                    focus_raw = str(row[focus_col]).strip() if focus_col else ""
                    routine_raw = str(row[routine_col]).strip() if routine_col else ""
                    st.session_state.weekly_plan[wk] = {
                        "focus": _parse_pipe_or_lines(focus_raw)[:2],
                        "routine": _parse_pipe_or_lines(routine_raw)[:5],
                    }
                    updated_rows += 1
                    if first_week_key_seen is None:
                        first_week_key_seen = wk
                auto_week_key = None
                current_label = find_current_week_label(weeks_meta)
                if current_label and current_label in weeks_map:
                    auto_week_key = weeks_map[current_label]
                if auto_week_key is None:
                    auto_week_key = first_week_key_seen
                if auto_week_key:
                    st.session_state["selected_week_key_auto"] = auto_week_key
                st.success(f"✅ 주차 플랜 적용 완료! ({updated_rows}개 주차 갱신)")
    except Exception as e:
        st.error(f"주차 플랜 CSV 처리 오류: {e}")

# =========================
# 2) Yearly Excel upload → month selection → goals → weeks
# =========================
st.markdown("### 📦 Yearly 플랜 Excel 업로드")
uploaded_file = st.file_uploader("📁 엑셀 파일 업로드", type=["xlsx"])

all_goals = []
filtered = pd.DataFrame()

if uploaded_file:
    with st.expander("🔍 시트 미리보기"):
        sheet_names = pd.ExcelFile(uploaded_file).sheet_names
        st.write("엑셀 시트 목록:", sheet_names)
    df = pd.read_excel(uploaded_file, sheet_name="최대선_최소선")
    df = df[["프로젝트", "월", "최소선", "최대선", "측정지표"]].dropna(subset=["월"])  # type: ignore

    selected_month = st.selectbox("📅 월을 선택하세요", sorted(df["월"].dropna().unique()))

    year = datetime.date.today().year
    month_num = MONTH_MAP[selected_month]

    weeks_meta, weeks_map = month_weeks(year, month_num, week_start=0)

    # Goals for selected month
    filtered = df[df["월"] == selected_month].reset_index(drop=True)
    st.markdown("### 🔍 해당 월의 목표 목록")
    st.dataframe(filtered[["프로젝트", "최대선", "최소선"]], use_container_width=True)

    st.markdown(f"### 🗓 {selected_month}의 주차별 일정 ({len(weeks_meta)}주차)")
    for i, w in enumerate(weeks_meta, start=1):
        in_month_days = [d for d in w["days"] if d.month == month_num]
        label = f"{i}주차 ({w['start'].strftime('%m/%d')}–{w['end'].strftime('%m/%d')})"
        with st.expander(label, expanded=False):
            st.write("해당 월 날짜:", ", ".join(d.strftime("%m/%d") for d in in_month_days))

    # Parse goals once
    text_blocks = filtered["최소선"].dropna().tolist() + filtered["최대선"].dropna().tolist()
    parsed = parse_goals("\n".join(map(str, text_blocks)))
    all_goals = [f"{section} - {item}" for section, item in parsed]

    # 3) Week-by-week selection UI
    if "weekly_plan" not in st.session_state:
        st.session_state.weekly_plan = {}

    for label, key in weeks_map.items():
        c1, c2, c3 = st.columns([1.5, 3, 3])
        with c1:
            st.markdown(f"**📌 {label}**")
        with c2:
            focus = st.multiselect(
                "메인 포커스 (1-2개)",
                options=all_goals,
                max_selections=2,
                key=f"{key}_focus",
            )
        with c3:
            routine = st.multiselect(
                "백그라운드 배경 (최대 5개)",
                options=all_goals,
                max_selections=5,
                key=f"{key}_routine",
            )
        st.session_state.weekly_plan[key] = {"focus": focus, "routine": routine}

    # 4) Summary table
    st.markdown("---")
    st.markdown("## 📝 이번달 주간 요약")
    summary_data = []
    for label, key in weeks_map.items():
        f = st.session_state.weekly_plan.get(key, {}).get("focus", [])
        r = st.session_state.weekly_plan.get(key, {}).get("routine", [])
        summary_data.append({
            "주차": label,
            "메인 포커스": ", ".join(f) if f else "선택 안됨",
            "배경": ", ".join(r) if r else "선택 안됨",
        })
    summary_df = pd.DataFrame(summary_data)
    st.dataframe(summary_df, use_container_width=True)

    # 5) Coverage feedback
    st.markdown("## 🔎 최대선 커버리지 피드백")
    month_goals = build_month_goals(filtered)
    cov_res = compute_coverage(weeks_map, st.session_state.weekly_plan, month_goals)

    if not cov_res["capacity_ok"]:
        st.error(
            f"최대선 개수({cov_res['num_max_goals']})가 이번달 포커스 슬롯 수({cov_res['total_focus_slots']})보다 많아요. "
            "일부 최대선을 다음 달로 미루거나, 우선순위를 조정하세요."
        )
    else:
        st.success(
            f"포커스 슬롯 충분 ✅ (최대선 {cov_res['num_max_goals']}개 / 사용 가능 슬롯 {cov_res['total_focus_slots']}개)"
        )

    rows = []
    for gid, g in month_goals.items():
        cv = cov_res["coverage"][gid]
        rows.append({
            "구분": "최대선" if g["kind"] == "max" else "최소선",
            "목표": g["label"],
            "포커스 횟수": cv["focus"],
            "배경 횟수": cv["routine"],
            "배치 주": ", ".join(cv["weeks"]) if cv["weeks"] else "-",
            "상태": ("누락(포커스 미배정)" if (g["kind"] == "max" and cv["focus"] == 0) else "OK"),
        })
    cov_df = pd.DataFrame(rows).sort_values(["구분", "상태", "목표"])  # type: ignore
    st.dataframe(cov_df, use_container_width=True)

    missing_max_labels = [month_goals[gid]["label"] for gid in cov_res["missing_focus"]]
    if missing_max_labels:
        st.warning("🚨 포커스로 배정되지 않은 ‘최대선’이 있습니다:\n- " + "\n- ".join(missing_max_labels))
    else:
        st.info("모든 ‘최대선’이 최소 1회 이상 포커스로 배정되었습니다. 👍")

    st.markdown("#### 👀 제안 미리보기")
    preview_rows = []
    for wk, gid in cov_res["suggestions"]:
        preview_rows.append({"주차": wk, "조치": "add", "대상": month_goals[gid]["label"], "설명": "빈 슬롯에 최대선 배치"})
    for wk, gid in cov_res["swaps"]:
        preview_rows.append({"주차": wk, "조치": "promote", "대상": month_goals[gid]["label"], "설명": "과밀 주 routine→focus 승격"})

    if preview_rows:
        suggest_df = pd.DataFrame(preview_rows)
        st.dataframe(suggest_df, use_container_width=True)
        st.download_button(
            "📥 제안 미리보기 CSV",
            suggest_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="suggestions_preview.csv",
            mime="text/csv",
            key="dl_suggest_preview",
        )
    else:
        st.caption("현재 자동 제안 없음.")

    st.markdown("#### ✅ 제안 반영 시뮬레이션 (원본은 변경되지 않음)")
    if st.button("제안 반영한 '가상 계획' 생성"):
        original = _snapshot_weekly_plan(st.session_state.weekly_plan)
        virtual_plan, applied_log = _build_virtual_plan(original, cov_res["suggestions"], cov_res["swaps"], month_goals)

        diff_rows = []
        for wk in weeks_map.values():
            b_focus = set(original.get(wk, {}).get("focus", []))
            a_focus = set(virtual_plan.get(wk, {}).get("focus", []))
            added = sorted(list(a_focus - b_focus))
            removed = sorted(list(b_focus - a_focus))
            diff_rows.append({
                "주차": wk,
                "추가된 포커스": " | ".join(added) if added else "-",
                "제거된 포커스(가상)": " | ".join(removed) if removed else "-",
                "가상 계획 포커스": " | ".join(virtual_plan.get(wk, {}).get("focus", [])) if virtual_plan.get(wk) else "-",
                "가상 계획 배경": " | ".join(virtual_plan.get(wk, {}).get("routine", [])) if virtual_plan.get(wk) else "-",
            })
        diff_df = pd.DataFrame(diff_rows)
        st.success("가상 계획이 생성되었습니다. (원래 계획은 그대로입니다)")
        st.markdown("##### 🔁 반영 결과(diff, 원본 vs. 가상)")
        st.dataframe(diff_df, use_container_width=True)
        st.download_button(
            "📥 반영 결과(diff) CSV",
            diff_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="weekly_plan_virtual_diff.csv",
            mime="text/csv",
            key="dl_virtual_diff",
        )

        st.markdown("##### 🗂 가상 계획(제안 반영본) 일람")
        plan_rows = []
        for label, wk in weeks_map.items():
            v = virtual_plan.get(wk, {"focus": [], "routine": []})
            plan_rows.append({
                "주차": label,
                "포커스(가상)": " | ".join(v.get("focus", [])) or "-",
                "배경(가상)": " | ".join(v.get("routine", [])) or "-",
            })
        virtual_df = pd.DataFrame(plan_rows)
        st.dataframe(virtual_df, use_container_width=True)
        st.download_button(
            "📥 가상 계획 CSV",
            virtual_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="weekly_plan_virtual.csv",
            mime="text/csv",
            key="dl_virtual_plan",
        )

        if applied_log:
            log_df = pd.DataFrame(applied_log, columns=["action", "week_key", "label", "note"])
            st.markdown("##### 🧾 가상 적용 로그")
            st.dataframe(log_df, use_container_width=True)
            st.download_button(
                "📥 가상 적용 로그 CSV",
                log_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="virtual_applied_actions_log.csv",
                mime="text/csv",
                key="dl_virtual_log",
            )
        else:
            st.caption("실행된 가상 조치가 없습니다.")

# =========================
# 3) Ensure calendar weeks even without Excel
# =========================
if not uploaded_file:
    _today = datetime.date.today()
    weeks_meta, weeks_map = month_weeks(_today.year, _today.month, week_start=0)

# Selected/current week logic
current_week_label = find_current_week_label(weeks_meta)
if current_week_label is None and weeks_meta:
    current_week_label = weeks_meta[0]["label"]
current_week_key = weeks_map.get(current_week_label, "week_manual")

# Ensure storage skeletons
if current_week_key not in st.session_state.default_blocks:
    st.session_state.default_blocks[current_week_key] = _build_default_blocks_from_weekplan(current_week_key)
if "day_detail" not in st.session_state:
    st.session_state.day_detail = {}
if current_week_key not in st.session_state.day_detail:
    st.session_state.day_detail[current_week_key] = {d: {"main": [], "routine": []} for d in DAYS_KR}

# Week selector
options = list(weeks_map.keys())
default_index = options.index(current_week_label) if current_week_label in options else 0
selected_week_label = st.selectbox("📆 체크할 주 차를 선택하세요", options, index=default_index)
selected_week_key = weeks_map[selected_week_label]
selected_week_key = st.session_state.get("selected_week_key_auto", selected_week_key)

# Parse week dates from label
week_dates = parse_week_dates_from_label(selected_week_label)

# ===============================
# 📅 이 주의 상세 플랜 (날짜 기준, 표로 직접 편집)
# ===============================
st.markdown(f"### 🗓 {selected_week_label} — 날짜 기준 상세 플랜 자동 생성")
st.caption("메인A는 월·수·금, 메인B는 화·목·금 / 토·일은 보완·회고로 자동 배치됩니다.")

# 세션 가드
if "day_detail" not in st.session_state:
    st.session_state.day_detail = {}

# 자동 생성 버튼
if st.button("⚙️ 이 주 상세 플랜 자동 생성", use_container_width=True):
    st.session_state.day_detail[selected_week_key] = generate_weekly_detail(selected_week_key, week_dates)
    st.success("✅ 주간 디테일이 자동 생성되었습니다!")

# 표 보기
if selected_week_key in st.session_state.day_detail:
    detail = st.session_state.day_detail[selected_week_key]
    rows = []
    for i, date_obj in enumerate(week_dates):
        weekday_kr = DAYS_KR[date_obj.weekday()]
        date_str = date_obj.strftime("%m/%d")
        rows.append({
            "날짜": date_str,
            "요일": weekday_kr,
            "메인(자동)": " | ".join(detail[weekday_kr]["main"]) or "-",
            "배경(자동)": " | ".join(detail[weekday_kr]["routine"]) or "-",
        })
    df_week_auto = pd.DataFrame(rows)
    st.dataframe(df_week_auto, use_container_width=True)

    csv_auto = df_week_auto.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 자동 생성 주간 디테일 CSV 다운로드",
        data=csv_auto,
        file_name=f"auto_week_detail_{selected_week_key}.csv",
        mime="text/csv",
        key=f"auto_csv_{selected_week_key}"
    )



# Weekly table (day-wise)
# 📊 이 주 요약표 (상세/자동/최종 + 진행현황)
# ===============================
st.markdown("## ✅ 이 주 플랜 대시보드")
st.markdown("---")

tab1, tab2, tab3 = st.tabs(["📋 요약 보기", "🧩 상세 플랜 보기", "📊 진행 현황 보기"])

# 1️⃣ 이번 주 메인 포커스 & 배경 루틴
week_plan = st.session_state.weekly_plan.get(selected_week_key, {"focus": [], "routine": []})
main_focus = " | ".join(week_plan.get("focus", [])) or "-"
background_focus = " | ".join(week_plan.get("routine", [])) or "-"

with st.container():
    st.markdown("#### 🎯 이 주 요약표 (메인 포커스 → 요일별 상세)")
    c1, c2 = st.columns(2)
    with c1:
        st.info(f"**메인 포커스:** {main_focus}")
    with c2:
        st.info(f"**배경 루틴:** {background_focus}")

# 2️⃣ 상세 플랜 보기
# 2️⃣ 상세 플랜 보기
with tab2:
    st.markdown("### ✍️ 날짜별 상세 플랜 (실제 달력 기준)")
    st.caption("이번 주 실제 날짜에 맞춰 플랜을 편집할 수 있습니다.")

    # 안전 가드
    if "day_detail" not in st.session_state:
        st.session_state.day_detail = {}
    if selected_week_key not in st.session_state.day_detail:
        st.session_state.day_detail[selected_week_key] = {d: {"main": [], "routine": []} for d in DAYS_KR}

    days_kr = ["월", "화", "수", "목", "금", "토", "일"]
    edit_rows = []

    for date_obj in week_dates:
        weekday_kr = days_kr[date_obj.weekday()]
        date_disp = date_obj.strftime("%m/%d")
        detail_main = st.session_state.day_detail[selected_week_key][weekday_kr]["main"]
        detail_routine = st.session_state.day_detail[selected_week_key][weekday_kr]["routine"]
        edit_rows.append({
            "날짜": date_disp,
            "요일": weekday_kr,
            "상세 플랜(메인)": " | ".join(detail_main),
            "상세 플랜(배경)": " | ".join(detail_routine),
        })

    df_edit = pd.DataFrame(edit_rows, columns=["날짜", "요일", "상세 플랜(메인)", "상세 플랜(배경)"])

    edited = st.data_editor(df_edit, hide_index=True, use_container_width=True)

    # 수정 내용 반영
    for _, row in edited.iterrows():
        weekday = row["요일"]
        st.session_state.day_detail[selected_week_key][weekday]["main"] = _parse_pipe_or_lines(row["상세 플랜(메인)"])
        st.session_state.day_detail[selected_week_key][weekday]["routine"] = _parse_pipe_or_lines(row["상세 플랜(배경)"])

    # CSV 다운로드
    csv_week = edited.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 이 주 상세 플랜 CSV 다운로드 (날짜 기준)",
        data=csv_week,
        file_name=f"week_detail_{selected_week_key}.csv",
        mime="text/csv",
    )

# 3️⃣ 진행 현황 보기
with tab3:
    st.markdown("### 📊 이번 주 진행률 요약")
    progress_rows = []
    for i, d in enumerate(DAYS_KR):
        date_obj = week_dates[i]
        date_disp = f"{date_obj.month}/{date_obj.day}"
        store_key = (selected_week_key, date_obj.isoformat())
        completed = st.session_state.completed_by_day.get(store_key, set())
        detail_main = st.session_state.day_detail[selected_week_key][d]["main"]
        detail_routine = st.session_state.day_detail[selected_week_key][d]["routine"]
        total_tasks = len(detail_main) + len(detail_routine)
        done = sum((f"[메인] {t}" in completed) for t in detail_main)
        done += sum((f"[배경] {t}" in completed) for t in detail_routine)
        rate = int(done / total_tasks * 100) if total_tasks else 0
        progress_rows.append({"요일": d, "날짜": date_disp, "완료/총계": f"{done}/{total_tasks}", "달성률(%)": rate})
    st.dataframe(pd.DataFrame(progress_rows), use_container_width=True)


# st.markdown("### ✅ 이 주 요약표 (상세/자동/최종 + 진행현황)")
# st.markdown("---")

# rows = []

# # 안전 가드
# if "completed_by_day" not in st.session_state:
#     st.session_state.completed_by_day = {}
# if not week_dates:
#     today = datetime.date.today()
#     week_dates = [today + datetime.timedelta(days=i) for i in range(7)]

# for i, d in enumerate(DAYS_KR):
#     date_obj = week_dates[i]
#     date_disp = f"{date_obj.month}/{date_obj.day}"

#     # 1) 상세(CSV/사용자 입력)
#     detail_main = list(st.session_state.day_detail[selected_week_key][d]["main"])
#     detail_routine = list(st.session_state.day_detail[selected_week_key][d]["routine"])

#     # 2) 자동(default blocks)
#     auto_items = default_blocks.get(d, [])
#     auto_main = [x for x in auto_items if not x.startswith("배경:")]
#     auto_routine = [x for x in auto_items if x.startswith("배경:")]

#     # 3) 최종(상세 우선 + 자동 보강, 중복 제거)
#     def _dedupcat(primary, fallback):
#         out, seen = [], set()
#         for v in primary + fallback:
#             if v not in seen:
#                 out.append(v)
#                 seen.add(v)
#         return out

#     final_main = _dedupcat(detail_main, auto_main)
#     final_routine = _dedupcat(detail_routine, auto_routine)

#     # 4) 진행현황(완료/총계, 달성률)
#     store_key = (selected_week_key, date_obj.isoformat())
#     completed = st.session_state.completed_by_day.get(store_key, set())
#     total_tasks = len(final_main) + len(final_routine)

#     # 체크박스 라벨 규칙과 동일하게 집계
#     done_main = sum((f"[메인] {t}" in completed) for t in final_main)
#     # 최종 라벨에서는 '배경:' 접두를 떼고 체크라벨과 매칭
#     done_routine = 0
#     for t in final_routine:
#         clean = t.replace("배경:", "").strip()
#         if f"[배경] {clean}" in completed:
#             done_routine += 1

#     done_cnt = done_main + done_routine
#     rate = int(done_cnt / total_tasks * 100) if total_tasks else 0

#     rows.append({
#         "요일": d,
#         "날짜": date_disp,

#         # 메인
#         "메인(상세)": " | ".join(detail_main) if detail_main else "-",
#         "메인(자동)": " | ".join(auto_main) if auto_main else "-",
#         "메인(최종)": " | ".join(final_main) if final_main else "-",

#         # 배경
#         "배경(상세)": " | ".join(detail_routine) if detail_routine else "-",
#         "배경(자동)": " | ".join(auto_routine) if auto_routine else "-",
#         "배경(최종)": " | ".join(final_routine) if final_routine else "-",

#         # 진행현황
#         "완료/총계": f"{done_cnt}/{total_tasks}",
#         "달성률(%)": rate,
#     })

# week_df = pd.DataFrame(rows)
# st.dataframe(week_df, use_container_width=True)

# # 내려받기 (최종 포함 요약본)
# csv = week_df.to_csv(index=False).encode("utf-8-sig")
# st.download_button(
#     "📥 이 주 계획(상세·자동·최종·진행현황 포함) CSV 다운로드",
#     data=csv,
#     file_name=f"week_plan_full_{selected_week_key}.csv",
#     mime="text/csv"
# )

# =========================
# 4) Today checklist
# =========================
st.markdown("---")
st.markdown("### ✅ 오늘의 실행 체크리스트")

if "completed_by_day" not in st.session_state:
    st.session_state.completed_by_day = {}

# Choose day (auto index)
today = datetime.date.today()
today_idx_auto = min(today.weekday(), 6)  # 0=월 ... 6=일
sel_day = st.selectbox("🗓 오늘 요일을 선택/확인하세요", DAYS_KR, index=today_idx_auto)

# Pick date string
if week_dates:
    day_idx = DAYS_KR.index(sel_day)
    date_str = week_dates[day_idx].isoformat()
else:
    date_str = today.isoformat()

# Merge detail + default
_detail = st.session_state.day_detail[selected_week_key][sel_day]
auto_items = default_blocks.get(sel_day, [])
auto_main = [x for x in auto_items if not x.startswith("배경:")]
auto_routine = [x for x in auto_items if x.startswith("배경:")]
final_main = _detail["main"] if _detail["main"] else auto_main
final_routine = _detail["routine"] if _detail["routine"] else auto_routine

store_key = (selected_week_key, date_str)
if store_key not in st.session_state.completed_by_day:
    st.session_state.completed_by_day[store_key] = set()
completed = st.session_state.completed_by_day[store_key]

# Render checkboxes
def _task_key(prefix, text):
    raw = f"{selected_week_key}|{date_str}|{prefix}|{text}"
    return "chk_" + hashlib.md5(raw.encode("utf-8")).hexdigest()

today_tasks: list[tuple[str, str]] = []
for t in final_main:
    today_tasks.append(("[메인]", t))
for t in final_routine:
    today_tasks.append(("[배경]", t.replace("배경:", "").strip()))

if not today_tasks:
    st.info("오늘 체크할 항목이 없습니다. (CSV의 요일별 상세 플랜을 올리거나, 주차 자동 제안을 확인하세요.)")
else:
    for kind, text in today_tasks:
        label = f"{kind} {text}"
        key = _task_key(kind, text)
        default_checked = label in completed
        checked = st.checkbox(label, value=default_checked, key=key)
        if checked:
            completed.add(label)
        else:
            completed.discard(label)
    if len(today_tasks) > 0:
        percent = int(len(completed) / len(today_tasks) * 100)
    else:
        percent = 0
    st.progress(percent)
    st.write(f"📊 오늘의 달성률: **{percent}%** ({len(completed)} / {len(today_tasks)})")

with st.expander("📋 오늘 체크 내역 보기/내보내기"):
    rows = [{"날짜": date_str, "유형": kind, "할 일": text, "완료": (f"{kind} {text}" in completed)} for kind, text in today_tasks]
    df_today = pd.DataFrame(rows)
    st.dataframe(df_today, use_container_width=True)
    csv_today = df_today.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "📥 오늘 체크 내역 CSV 다운로드",
        data=csv_today,
        file_name=f"today_tasks_{selected_week_key}_{date_str}.csv",
        mime="text/csv",
    )

# =========================
# 5) Weekly review notes
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
