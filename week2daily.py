import streamlit as st
import pandas as pd
import datetime
import hashlib
import io
from pathlib import Path
import re

# ================================================
# 듀얼 CSV 체크앱 (심플)
#   - A = virtual.csv (형식 자유) → "그대로 DataFrame" 으로 상단 고정 영역에 표시만 함
#   - B = week.csv    (요일별 태스크) → 체크리스트/진행률의 유일한 데이터 소스
#   - 업로드한 파일은 세션에 고정(다른 파일 올릴 때까지 유지)
# ================================================

st.set_page_config(page_title="주간 체크리스트 — 듀얼 CSV(심플)", layout="wide")
st.title("✅ 주간 체크리스트 — 듀얼 CSV (심플)")
st.caption("A(virtual)는 그냥 표로 보여주고, B(week)만 체크/진행률에 사용합니다.")

DAYS_KR = ["월","화","수","목","금","토","일"]

# ---------------------
# Helpers
# ---------------------
def _parse_pipe_or_lines(s: str):
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

# B용(week.csv) 유연 로더 — 최소 요건: 요일 + (메인 칼럼 하나) + (배경 칼럼 하나)
HEADER_ALIASES = {
    "day": ["요일", "day", "일자"],
    "main": ["상세 플랜(메인)", "메인", "main", "포커스", "focus"],
    "routine": ["상세 플랜(배경)", "배경", "routine", "background"],
}
_DEF_MAIN = "상세 플랜(메인)"
_DEF_ROUT = "상세 플랜(배경)"

def _norm_header(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"\s+", "", s)
    return s.replace("_", "")

def _pick(df: pd.DataFrame, keys: list[str]):
    # 완전일치 → 부분포함 순
    cols = list(df.columns)
    by_norm = {_norm_header(c): c for c in cols}
    for k in keys:
        if _norm_header(k) in by_norm:
            return by_norm[_norm_header(k)]
    for c in cols:
        nc = _norm_header(c)
        if any(_norm_header(k) in nc for k in keys):
            return c
    return None

def load_week_like(file) -> pd.DataFrame:
    """
    CSV를 읽어 아래 6개 컬럼을 '항상' 갖도록 정규화해서 돌려줍니다.
      - 요일, 날짜, 자동 제안(메인), 자동 제안(배경), 상세 플랜(메인), 상세 플랜(배경)
    원본 CSV에 없으면 빈 문자열("")로 채우고, 헤더는 유연하게 매핑합니다.
    """
    file.seek(0)
    try:
        df = pd.read_csv(file, encoding="utf-8-sig")
    except UnicodeDecodeError:
        file.seek(0)
        df = pd.read_csv(file, encoding="utf-8")

    # ---- 컬럼 후보 (유연 매핑) ----
    # 요일/메인/배경은 기존 별칭 사용
    day_aliases  = HEADER_ALIASES["day"]          # ["요일","day","일자"]
    main_aliases = HEADER_ALIASES["main"]         # ["상세 플랜(메인)","메인","main","포커스","focus"]
    rout_aliases = HEADER_ALIASES["routine"]      # ["상세 플랜(배경)","배경","routine","background"]

    # 추가: 날짜/자동제안 별칭
    date_aliases      = ["날짜", "date", "일자", "날짜(yyyy-mm-dd)", "날짜(YYYY-MM-DD)"]
    auto_main_aliases = ["자동 제안(메인)", "자동제안(메인)", "자동제안메인", "제안(메인)", "제안메인", "auto_main", "suggest_main"]
    auto_rout_aliases = ["자동 제안(배경)", "자동제안(배경)", "자동제안배경", "제안(배경)", "제안배경", "auto_routine", "suggest_routine"]

    # ---- 유연 매핑 픽 ----
    day_col       = _pick(df, day_aliases)
    date_col      = _pick(df, date_aliases)
    main_col      = _pick(df, main_aliases)
    rout_col      = _pick(df, rout_aliases)
    auto_main_col = _pick(df, auto_main_aliases)
    auto_rout_col = _pick(df, auto_rout_aliases)

    # ---- 필수 최소 요건: '요일'은 있어야 함 ----
    if day_col is None:
        raise ValueError(f"B 파일에 '요일'에 해당하는 칼럼이 없습니다. CSV 헤더: {list(df.columns)}")

    # ---- 누락된 컬럼은 빈 문자열로 만들어 채워 넣기 ----
    if date_col is None:
        df["__날짜__"] = ""
        date_col = "__날짜__"
    if main_col is None:
        df["__상세메인__"] = ""
        main_col = "__상세메인__"
    if rout_col is None:
        df["__상세배경__"] = ""
        rout_col = "__상세배경__"
    if auto_main_col is None:
        df["__자동메인__"] = ""
        auto_main_col = "__자동메인__"
    if auto_rout_col is None:
        df["__자동배경__"] = ""
        auto_rout_col = "__자동배경__"

    # ---- 출력 스키마 구성 ----
    out = df[[day_col, date_col, auto_main_col, auto_rout_col, main_col, rout_col]].copy()
    out.columns = ["요일", "날짜", "자동 제안(메인)", "자동 제안(배경)", "상세 플랜(메인)", "상세 플랜(배경)"]

    # ---- 정리/정렬 ----
    out = out.fillna("")
    # 요일 카테고리 정렬 (존재하는 행만 반영)
    cat = pd.CategoricalDtype(categories=DAYS_KR, ordered=True)
    out["요일"] = pd.Categorical(out["요일"].astype(str).str.strip(), dtype=cat)
    out = out.sort_values("요일").reset_index(drop=True)

    return out


# ---------------------
# Sidebar — A/B 업로드 및 고정
# ---------------------
with st.sidebar:
    st.markdown("### 📎 CSV 업로드 (A=virtual, B=week)")
    colA, colB = st.columns(2)
    with colA:
        upA = st.file_uploader("A: virtual.csv", type=["csv"], key="uA")
    with colB:
        upB = st.file_uploader("B: week.csv (요일/메인/배경)", type=["csv"], key="uB")

    if "persist_A" not in st.session_state:
        st.session_state.persist_A = None  # {name, bytes}
    if "persist_B" not in st.session_state:
        st.session_state.persist_B = None

    c1, c2, c3 = st.columns([2,2,2])
    with c1:
        if st.button("A 저장/갱신", use_container_width=True) and upA is not None:
            upA.seek(0)
            st.session_state.persist_A = {"name": upA.name, "bytes": upA.read()}
            st.success(f"A 고정: {upA.name}")
    with c2:
        if st.button("B 저장/갱신", use_container_width=True) and upB is not None:
            upB.seek(0)
            st.session_state.persist_B = {"name": upB.name, "bytes": upB.read()}
            st.success(f"B 고정: {upB.name}")
    with c3:
        if st.button("모두 해제", use_container_width=True):
            st.session_state.persist_A = None
            st.session_state.persist_B = None
            st.success("두 파일 모두 해제됨")

    st.caption("A는 표로만 보여주고, B만 체크/진행률에 사용합니다. 업로드된 파일은 변경 전까지 유지됩니다.")

# 준비된 바이트 → 파일핸들
A_blob = st.session_state.get("persist_A")
B_blob = st.session_state.get("persist_B")
A_name = A_blob["name"] if A_blob else None
B_name = B_blob["name"] if B_blob else None
A_file = io.BytesIO(A_blob["bytes"]) if A_blob else None
B_file = io.BytesIO(B_blob["bytes"]) if B_blob else None

if "completed_by_day" not in st.session_state:
    st.session_state.completed_by_day = {}

# ---------------------
# 상단 고정: 두 파일 모두 보여주기 (A는 그대로 df, B는 요약표)
# ---------------------
st.markdown(
    """
    <style>
    .sticky-plan {position: sticky; top: 0; z-index: 999; background: var(--background-color); padding: 0.5rem 0.25rem; border-bottom: 1px solid rgba(0,0,0,0.08);} 
    .sticky-card {padding: 0.5rem 0.75rem; border: 1px solid rgba(0,0,0,0.08); border-radius: 10px; margin-bottom: 8px;}
    .sticky-table {font-size: 0.92rem; width: 100%; border-collapse: collapse;}
    .sticky-table th, .sticky-table td {padding: 6px 8px; vertical-align: top; border-bottom: 1px dashed rgba(0,0,0,0.06);} 
    .day {font-weight: 600; white-space: nowrap;}
    .muted {opacity: .7; font-size: .85rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

# A 표 미리읽기 (그대로 표시)
A_df = None
if A_file is not None:
    try:
        A_file.seek(0)
        try:
            A_df = pd.read_csv(A_file, encoding="utf-8-sig")
        except UnicodeDecodeError:
            A_file.seek(0)
            A_df = pd.read_csv(A_file)
    except Exception as e:
        st.warning(f"A 파일 읽기 오류: {e}")

# B 요약표 구성(요일/메인/배경이 있는 경우)
B_df = None
if B_file is not None:
    try:
        B_df = load_week_like(B_file)
    except Exception as e:
        st.warning(f"B 파일 해석 오류: {e}")

# Sticky HTML/controls
st.markdown("<div class='sticky-plan'>", unsafe_allow_html=True)

if A_df is not None:
    st.markdown(f"**📌 A(virtual) — {A_name}**")
    st.dataframe(A_df.head(50), use_container_width=True)
    st.download_button("📥 A 다운로드", data=A_blob.get("bytes", b""), file_name=A_name or "virtual.csv", mime="text/csv", key="dlA")
else:
    st.markdown("**📌 A(virtual)**: (파일 없음 또는 읽기 실패)")

if B_df is not None:
    st.markdown(f"**📌 B(week) — {B_name} (요일·메인·배경 요약)**")
    st.dataframe(B_df, use_container_width=True)
    st.download_button("📥 B 다운로드", data=B_blob.get("bytes", b""), file_name=B_name or "week.csv", mime="text/csv", key="dlB")
else:
    st.markdown("**📌 B(week)**: (파일 없음 또는 해석 불가 — 체크리스트 비활성화)")

st.markdown("</div>", unsafe_allow_html=True)

# ---------------------
# 체크리스트(오직 B로만!)
# ---------------------
if B_df is None:
    st.info("B(week) 파일이 있어야 체크리스트를 사용할 수 있어요.")
    st.stop()

# 요일 → 태스크 매핑 (B)
B_map = {}
ordered_days = []
for _, row in B_df.iterrows():
    d = str(row["요일"]) if row["요일"] == row["요일"] else ""
    if not d:
        continue
    mains = _parse_pipe_or_lines(row.get(_DEF_MAIN, ""))
    routines = _parse_pipe_or_lines(row.get(_DEF_ROUT, ""))
    B_map[d] = {"main": mains, "routine": routines}
    if d not in ordered_days:
        ordered_days.append(d)
ordered_days = [d for d in DAYS_KR if d in ordered_days]

# 오늘 요일 자동 인식 (수동 변경 가능)
_today = datetime.date.today()
auto_idx = min(_today.weekday(), 6)
sel_day = st.radio(
    "🗓 오늘 요일 선택",
    ordered_days,
    index=ordered_days.index(DAYS_KR[auto_idx]) if DAYS_KR[auto_idx] in ordered_days else 0,
    horizontal=True,
)

week_id = Path(B_name or "week").stem
main_tasks = B_map[sel_day]["main"]
routine_tasks = B_map[sel_day]["routine"]
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
# 주간 집계 (B 기준)
# ---------------------
st.markdown("---")
st.markdown("### 🧮 주간 진행률 (B 기준)")
rows = []
weekly_total = 0
weekly_done = 0
for d in ordered_days:
    tasks_d = [("[메인]", t) for t in B_map[d]["main"]] + [("[배경]", t) for t in B_map[d]["routine"]]
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
with st.expander("📤 현 진행상태 CSV로 내보내기 (B 기준)", expanded=False):
    out_rows = []
    for d in ordered_days:
        tasks_d = [("[메인]", t) for t in B_map[d]["main"]] + [("[배경]", t) for t in B_map[d]["routine"]]
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
