import streamlit as st
import pandas as pd
import datetime
import hashlib
import io
from pathlib import Path
import re

# ==================================================
# 주간 체크리스트 — 듀얼 CSV (A: virtual.csv, B: week.csv)
#   - 두 CSV를 세션에 고정 저장 (다른 파일 올리기 전까지 유지)
#   - 상단 고정(Sticky) 요약: A/B 둘 다 항상 보여줌
#   - 체크는 '활성 파일' 기준으로 수행 → 일간/주간 진행률 표시
#   - 내보내기: 현재 진행상태 CSV로 다운로드
# ==================================================

st.set_page_config(page_title="주간 체크리스트 — 듀얼 CSV", layout="wide")
st.title("✅ 주간 체크리스트 — 듀얼 CSV (A: virtual, B: week)")
st.caption("A/B 두 CSV를 올려 상단에서 모두 보면서, 선택한 파일로 체크와 진행률을 관리합니다.")

DAYS_KR = ["월","화","수","목","금","토","일"]

# ---------------------
# Helpers
# ---------------------
def _parse_pipe_or_lines(s: str):
    """Split by '|', or fallback to newline/comma."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
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

def _stable_task_key(week_id: str, day: str, prefix: str, text: str) -> str:
    raw = f"{week_id}|{day}|{prefix}|{text}"
    return "chk_" + hashlib.md5(raw.encode("utf-8")).hexdigest()

def _norm_header(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"\s+", "", s)
    return s.replace("_", "")

def _pick_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    # 1) 정규화된 완전일치
    by_norm = {_norm_header(c): c for c in df.columns}
    for cand in candidates:
        k = _norm_header(cand)
        if k in by_norm:
            return by_norm[k]
    # 2) 부분 포함(후순위)
    for c in df.columns:
        nc = _norm_header(c)
        if any(_norm_header(x) in nc for x in candidates):
            return c
    return None

def load_flexible_plan(file, prefer: str = "A") -> pd.DataFrame:
    """
    Flexible loader for A(virtual.csv) and B(week.csv).
    Maps headers to: [요일, 상세 플랜(메인), 상세 플랜(배경)].
    prefer = 'A' or 'B' controls candidate priority.
    """
    file.seek(0)
    try:
        df = pd.read_csv(file, encoding="utf-8-sig")
    except UnicodeDecodeError:
        file.seek(0)
        df = pd.read_csv(file, encoding="utf-8")

    # Candidate names per role
    day_A  = ["요일", "day", "일자", "date"]
    main_A = ["상세 플랜(메인)", "메인", "main", "main_tasks", "main task", "상세플랜메인"]
    rout_A = ["상세 플랜(배경)", "배경", "routine", "background", "routine_tasks", "상세플랜배경"]

    day_B  = ["요일", "day"]
    main_B = ["상세 플랜(메인)", "메인", "main"]
    rout_B = ["상세 플랜(배경)", "배경", "routine"]

    if str(prefer).upper() == "A":
        day_col  = _pick_col(df, day_A)  or _pick_col(df, day_B)
        main_col = _pick_col(df, main_A) or _pick_col(df, main_B)
        rout_col = _pick_col(df, rout_A) or _pick_col(df, rout_B)
    else:
        day_col  = _pick_col(df, day_B)  or _pick_col(df, day_A)
        main_col = _pick_col(df, main_B) or _pick_col(df, main_A)
        rout_col = _pick_col(df, rout_B) or _pick_col(df, rout_A)

    missing = [name for name, col in [("요일", day_col), ("메인", main_col), ("배경", rout_col)] if col is None]
    if missing:
        raise ValueError(f"필수 컬럼을 찾을 수 없습니다: {', '.join(missing)} — CSV 헤더: {list(df.columns)}")

    out = df[[day_col, main_col, rout_col]].copy()
    out.columns = ["요일", "상세 플랜(메인)", "상세 플랜(배경)"]
    out = out.fillna("")
    cat = pd.CategoricalDtype(categories=DAYS_KR, ordered=True)
    out["요일"] = pd.Categorical(out["요일"].astype(str).str.strip(), dtype=cat)
    out = out.sort_values("요일").reset_index(drop=True)
    return out

def explode_tasks(df: pd.DataFrame):
    """Return dict: day -> {main: [...], routine: [...]} and ordered day list."""
    day_map = {}
    ordered_days = []
    for _, row in df.iterrows():
        day = str(row["요일"]) if row["요일"] == row["요일"] else ""
        if not day:
            continue
        mains = _parse_pipe_or_lines(row.get("상세 플랜(메인)", ""))
        routines = _parse_pipe_or_lines(row.get("상세 플랜(배경)", ""))
        day_map[day] = {"main": mains, "routine": routines}
        if day not in ordered_days:
            ordered_days.append(day)
    ordered_days = [d for d in DAYS_KR if d in ordered_days]
    return day_map, ordered_days

# ---------------------
# Sidebar — CSV 업로드 (A=virtual, B=week)
# ---------------------
with st.sidebar:
    st.markdown("### 📎 주간 계획 CSV (2개 지원: A=virtual.csv, B=week.csv)")
    colA, colB = st.columns(2)
    with colA:
        uploaded_A = st.file_uploader("파일 A 업로드 (virtual.csv 용)", type=["csv"], key="uploader_A")
    with colB:
        uploaded_B = st.file_uploader("파일 B 업로드 (week_plan 용)", type=["csv"], key="uploader_B")

    if "persisted_csv_A" not in st.session_state:
        st.session_state.persisted_csv_A = None  # {name, bytes}
    if "persisted_csv_B" not in st.session_state:
        st.session_state.persisted_csv_B = None

    c1, c2, c3 = st.columns([2,2,2])
    with c1:
        if st.button("A 저장/갱신", use_container_width=True) and uploaded_A is not None:
            uploaded_A.seek(0)
            st.session_state.persisted_csv_A = {"name": uploaded_A.name, "bytes": uploaded_A.read()}
            st.success(f"A 고정: {uploaded_A.name}")
    with c2:
        if st.button("B 저장/갱신", use_container_width=True) and uploaded_B is not None:
            uploaded_B.seek(0)
            st.session_state.persisted_csv_B = {"name": uploaded_B.name, "bytes": uploaded_B.read()}
            st.success(f"B 고정: {uploaded_B.name}")
    with c3:
        if st.button("모두 해제", use_container_width=True):
            st.session_state.persisted_csv_A = None
            st.session_state.persisted_csv_B = None
            st.success("두 파일 모두 해제됨")

    st.caption("두 파일을 고정해두고 아래에서 활성(체크 대상)을 선택하세요. 업로드한 파일은 변경 전까지 유지됩니다.")

# 활성 파일 선택
active_choice = "A" if st.session_state.get("persisted_csv_A") else ("B" if st.session_state.get("persisted_csv_B") else None)
if active_choice is None:
    st.info("최소 한 개의 CSV를 저장/고정해 주세요.")
    st.stop()

active_choice = st.radio("체크 대상 파일 선택", [c for c in ["A","B"] if st.session_state.get(f"persisted_csv_{c}")], horizontal=True)

# 활성 & 보조 파일 핸들
active_blob = st.session_state.get(f"persisted_csv_{active_choice}")
active_file = io.BytesIO(active_blob["bytes"]) if active_blob else None
active_name = active_blob["name"] if active_blob else None

aux_choice = "B" if active_choice == "A" else "A"
aux_blob = st.session_state.get(f"persisted_csv_{aux_choice}")
aux_file = io.BytesIO(aux_blob["bytes"]) if aux_blob else None
aux_name = aux_blob["name"] if aux_blob else None

if "completed_by_day" not in st.session_state:
    st.session_state.completed_by_day = {}

week_id = Path(active_name).stem if active_name else "week_from_csv"

if active_file is None:
    st.info("체크 대상 파일을 준비하지 못했습니다. 사이드바에서 파일을 올린 뒤 '저장/갱신'을 눌러주세요.")
    st.stop()

# ---------------------
# Load & Preview (활성/보조)
# ---------------------
try:
    df_plan = load_flexible_plan(active_file, prefer=active_choice)
except Exception as e:
    st.error(f"활성 파일 읽기 오류: {e}")
    st.stop()

aux_plan = None
if aux_file is not None:
    try:
        aux_plan = load_flexible_plan(aux_file, prefer=aux_choice)
    except Exception:
        aux_plan = None

st.caption(f"현재 체크 대상: **{active_name}** ({active_choice})")
with st.expander("🔍 활성 파일 미리보기", expanded=False):
    st.dataframe(df_plan, use_container_width=True)
if aux_plan is not None:
    with st.expander(f"🗂 보조 파일 미리보기 — {aux_name} ({aux_choice})", expanded=False):
        st.dataframe(aux_plan, use_container_width=True)

# 요일 → 태스크 매핑
day_map, ordered_days = explode_tasks(df_plan)
if not ordered_days:
    st.warning("유효한 '요일' 데이터가 없습니다.")
    st.stop()

# ---------------------
# Sticky Top — 전체 주간 플랜 요약 (항상 상단 고정, A/B 모두)
# ---------------------
st.markdown(
    """
    <style>
    .sticky-plan {position: sticky; top: 0; z-index: 999; background: var(--background-color); padding: 0.5rem 0.25rem; border-bottom: 1px solid rgba(0,0,0,0.08);} 
    .sticky-card {padding: 0.5rem 0.75rem; border: 1px solid rgba(0,0,0,0.08); border-radius: 10px;}
    .sticky-table {font-size: 0.92rem; width: 100%; border-collapse: collapse;}
    .sticky-table th, .sticky-table td {padding: 6px 8px; vertical-align: top; border-bottom: 1px dashed rgba(0,0,0,0.06);} 
    .day {font-weight: 600; white-space: nowrap;}
    .muted {opacity: .7; font-size: .85rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")) if isinstance(s, str) else str(s)

def _join_html_bullets(items):
    if not items:
        return "-"
    return "<br>".join(["• " + _html_escape(x) for x in items])

def _make_plan_table(df, title, fname):
    if df is None:
        return f"<div class='sticky-card'><div><strong>{_html_escape(title)}</strong> — 없음</div></div>"
    tmp = {}
    for _, row in df.iterrows():
        d = str(row.get("요일", "")).strip()
        mains = _parse_pipe_or_lines(row.get("상세 플랜(메인)", ""))
        routines = _parse_pipe_or_lines(row.get("상세 플랜(배경)", ""))
        if d:
            tmp[d] = {"main": mains, "routine": routines}
    order = [d for d in DAYS_KR if d in tmp]
    rows_html = [f"<tr><td class='day'>{_html_escape(d)}</td><td>{_join_html_bullets(tmp[d]['main'])}</td><td>{_join_html_bullets(tmp[d]['routine'])}</td></tr>"] * 0
    rows_html = [f"<tr><td class='day'>{_html_escape(d)}</td><td>{_join_html_bullets(tmp[d]['main'])}</td><td>{_join_html_bullets(tmp[d]['routine'])}</td></tr>" for d in order]
    return f"""
    <div class='sticky-card'>
      <div><strong>{_html_escape(title)}</strong> <span class='muted'>(파일: {_html_escape(fname) if fname else '-'})</span></div>
      <table class='sticky-table'>
        <thead><tr><th>요일</th><th>메인</th><th>배경</th></tr></thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
    </div>
    """

plan_html_active = _make_plan_table(df_plan, f"📌 전체 주간 플랜 — 활성({active_choice})", active_name)
plan_html_aux = _make_plan_table(aux_plan, f"🗂 참고 플랜 — 보조({aux_choice})", aux_name)

st.markdown(
    f"""
    <div class='sticky-plan'>
      {plan_html_active}
      {plan_html_aux}
    </div>
    """,
    unsafe_allow_html=True,
)

# 상단: 현재 '활성' CSV 빠른 조작(다운로드/프리뷰)
cols_top = st.columns([4,1])
with cols_top[1]:
    st.download_button(
        "📥 활성 CSV 다운로드",
        data=active_blob.get("bytes", b"") if active_blob else b"",
        file_name=active_name or "week_from_csv.csv",
        mime="text/csv",
        use_container_width=True,
        key="dl_active_csv_top",
    )

with st.expander("🗂 상단 빠른 미리보기 (활성 CSV 일부)", expanded=False):
    _preview = None
    try:
        _preview = pd.read_csv(io.BytesIO(active_blob["bytes"]), encoding="utf-8-sig")
    except Exception:
        try:
            _preview = pd.read_csv(io.BytesIO(active_blob["bytes"]))
        except Exception:
            _preview = None
    if _preview is not None:
        st.dataframe(_preview.head(20), use_container_width=True)
    else:
        st.caption("CSV 미리보기를 표시할 수 없습니다.")

# ---------------------
# Daily Checklist UI (활성 파일 기준)
# ---------------------
_today = datetime.date.today()
auto_idx = min(_today.weekday(), 6)
sel_day = st.radio(
    "🗓 오늘 요일 선택",
    ordered_days,
    index=ordered_days.index(DAYS_KR[auto_idx]) if DAYS_KR[auto_idx] in ordered_days else 0,
    horizontal=True,
)

main_tasks = day_map[sel_day]["main"]
routine_tasks = day_map[sel_day]["routine"]
all_tasks = [("[메인]", t) for t in main_tasks] + [("[배경]", t) for t in routine_tasks]

if (week_id, sel_day) not in st.session_state.completed_by_day:
    st.session_state.completed_by_day[(week_id, sel_day)] = set()
completed = st.session_state.completed_by_day[(week_id, sel_day)]

st.subheader(f"{sel_day} 체크리스트")
if not all_tasks:
    st.info("해당 요일에 등록된 태스크가 없습니다.")
else:
    for kind, text in all_tasks:
        label = f"{kind} {text}"
        key = _stable_task_key(week_id, sel_day, kind, text)
        checked = st.checkbox(label, value=(label in completed), key=key)
        if checked:
            completed.add(label)
        else:
            completed.discard(label)

    pct_day = int(len(completed) / len(all_tasks) * 100) if all_tasks else 0
    st.progress(pct_day)
    st.write(f"📊 **{sel_day} 달성률**: {pct_day}%")

# ---------------------
# Weekly Progress (전체 요일 집계)
# ---------------------
st.markdown("---")
st.markdown("### 🧮 주간 진행률")
rows = []
weekly_total = 0
weekly_done = 0
for d in ordered_days:
    tasks_d = [("[메인]", t) for t in day_map[d]["main"]] + [("[배경]", t) for t in day_map[d]["routine"]]
    total_d = len(tasks_d)
    done_set = st.session_state.completed_by_day.get((week_id, d), set())
    done_d = len(done_set)
    weekly_total += total_d
    weekly_done += done_d
    pct_d = int((done_d/total_d)*100) if total_d else 0
    rows.append({"요일": d, "전체": total_d, "완료": done_d, "달성률(%)": pct_d})

if rows:
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
    pct_week = int((weekly_done/weekly_total)*100) if weekly_total else 0
    st.success(f"**주간 합계** — 완료 {weekly_done} / 전체 {weekly_total} → 달성률 **{pct_week}%**")
else:
    st.caption("표시할 주간 집계가 없습니다.")

# ---------------------
# (선택) 내보내기
# ---------------------
with st.expander("📤 현 진행상태 CSV로 내보내기", expanded=False):
    out_rows = []
    for d in ordered_days:
        tasks_d = [("[메인]", t) for t in day_map[d]["main"]] + [("[배경]", t) for t in day_map[d]["routine"]]
        done_set = st.session_state.completed_by_day.get((week_id, d), set())
        for kind, text in tasks_d:
            label = f"{kind} {text}"
            out_rows.append({"요일": d, "유형": kind, "할 일": text, "완료": (label in done_set)})
    if out_rows:
        out_df = pd.DataFrame(out_rows)
        st.download_button(
            "📥 진행상태 CSV 다운로드",
            data=out_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"progress_{week_id}.csv",
            mime="text/csv",
        )
    else:
        st.caption("내보낼 데이터가 없습니다.")
