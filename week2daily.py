import streamlit as st
import pandas as pd
import datetime
import hashlib
import io
from pathlib import Path

# ==================================================
# 주간 체크리스트 (CSV 기반 라이트 버전)
#   - 입력: 주간 계획 CSV (컬럼: 요일, 상세 플랜(메인), 상세 플랜(배경))
#   - 동작: 요일별 체크리스트 + 일간/주간 진행률 바
# ==================================================

st.set_page_config(page_title="주간 체크리스트 (CSV 라이트)", layout="wide")
st.title("✅ 주간 체크리스트 — CSV만으로 간단하게")
st.caption("업로드한 주간 계획 CSV를 기반으로, 요일별 체크와 진행률을 확인합니다.")

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
        for sep in [" ", ","]:
            if sep in s:
                parts = [x.strip() for x in s.split(sep)]
                break
        if not parts:
            parts = [s.strip()]
    return [x for x in parts if x]


def _stable_task_key(week_id: str, day: str, prefix: str, text: str) -> str:
    raw = f"{week_id}|{day}|{prefix}|{text}"
    return "chk_" + hashlib.md5(raw.encode("utf-8")).hexdigest()


def load_week_plan_from_csv(file) -> pd.DataFrame:
    file.seek(0)
    try:
        df = pd.read_csv(file, encoding="utf-8-sig")
    except UnicodeDecodeError:
        file.seek(0)
        df = pd.read_csv(file, encoding="utf-8")
    need = {"요일", "상세 플랜(메인)", "상세 플랜(배경)"}
    if not need.issubset(df.columns):
        raise ValueError("CSV에 '요일', '상세 플랜(메인)', '상세 플랜(배경)' 컬럼이 필요합니다.")
    df = df.fillna("")
    df["요일"] = df["요일"].astype(str).str.strip()
    # 요일 정렬 보장
    cat = pd.CategoricalDtype(categories=DAYS_KR, ordered=True)
    df["요일"] = pd.Categorical(df["요일"], dtype=cat)
    df = df.sort_values("요일")
    return df.reset_index(drop=True)


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
    # DAYS_KR 순으로 재정렬
    ordered_days = [d for d in DAYS_KR if d in ordered_days]
    return day_map, ordered_days


# ---------------------
# Sidebar — CSV 업로드
# ---------------------
with st.sidebar:
    st.markdown("### 📎 주간 계획 CSV")
    uploaded = st.file_uploader("CSV 업로드 (utf-8-sig 권장)", type=["csv"])
    keep_hint = "한 번 업로드하면, 다른 파일을 업로드할 때까지 유지됩니다."

    if "persisted_csv" not in st.session_state:
        st.session_state.persisted_csv = None  # {name:str, bytes:bytes}

    col1, col2 = st.columns([3,2])
    with col1:
        st.caption("필수 컬럼: 요일 / 상세 플랜(메인) / 상세 플랜(배경)")
        st.caption(keep_hint)
    with col2:
        if st.button("파일 해제/초기화", use_container_width=True):
            st.session_state.persisted_csv = None
            st.success("고정된 CSV를 해제했어요.")

    if uploaded is not None:
        try:
            uploaded.seek(0)
            data_bytes = uploaded.read()
            st.session_state.persisted_csv = {
                "name": uploaded.name or "week_from_csv.csv",
                "bytes": data_bytes,
            }
            st.success(f"업로드 고정됨: {st.session_state.persisted_csv['name']}")
        except Exception as e:
            st.error(f"업로드 처리 오류: {e}")

# 활성 파일 결정
active_file = None
active_name = None
if st.session_state.persisted_csv:
    active_name = st.session_state.persisted_csv["name"]
    active_file = io.BytesIO(st.session_state.persisted_csv["bytes"])  # 파일 핸들 재생성

if "completed_by_day" not in st.session_state:
    st.session_state.completed_by_day = {}  # key: (week_id, day) -> set(labels)

week_id = Path(active_name).stem if active_name else "week_from_csv"

if active_file is None:
    st.info("CSV를 업로드하면 요일별 체크리스트가 생성됩니다. (업로드한 파일은 유지됩니다)")
    st.stop()

# ---------------------
# Load & Preview
# ---------------------
try:
    df_plan = load_week_plan_from_csv(active_file)
except Exception as e:
    st.error(f"CSV 읽기 오류: {e}")
    st.stop()

st.caption(f"현재 파일: **{active_name}** (고정됨)")
with st.expander("🔍 CSV 미리보기", expanded=False):
    st.dataframe(df_plan, use_container_width=True)

# 요일 → 태스크 매핑
day_map, ordered_days = explode_tasks(df_plan)
if not ordered_days:
    st.warning("유효한 '요일' 데이터가 없습니다.")
    st.stop()

# ---------------------
# Daily Checklist UI
# ---------------------
# 오늘 요일 자동 인식 (수동 변경 가능)
_today = datetime.date.today()
auto_idx = min(_today.weekday(), 6)
sel_day = st.radio("🗓 오늘 요일 선택", ordered_days, index=ordered_days.index(DAYS_KR[auto_idx]) if DAYS_KR[auto_idx] in ordered_days else 0, horizontal=True)

# 오늘 태스크
main_tasks = day_map[sel_day]["main"]
routine_tasks = day_map[sel_day]["routine"]
all_tasks = [("[메인]", t) for t in main_tasks] + [("[배경]", t) for t in routine_tasks]

# 체크 상태 컨테이너 확보
if (week_id, sel_day) not in st.session_state.completed_by_day:
    st.session_state.completed_by_day[(week_id, sel_day)] = set()
completed = st.session_state.completed_by_day[(week_id, sel_day)]

# 체크박스 렌더
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

    # 일간 진행률
    pct_day = int(len(completed) / len(all_tasks) * 100) if all_tasks else 0
    st.progress(pct_day)
    st.write(f"📊 **{sel_day} 달성률**: {pct_day}%  ")

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
