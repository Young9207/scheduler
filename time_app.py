import streamlit as st
import pandas as pd
import re
import calendar
import datetime
import hashlib
import json
from pathlib import Path
import streamlit as st
import unicodedata
from collections import defaultdict

STATE_FILE = Path("state_storage.json")
STATE_KEYS = ["weekly_plan", "day_detail", "completed_by_day", "weekly_review"]


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

def compute_coverage(weeks, weekly_plan, month_goals):
    week_capacity = {wk: 2 for wk in weeks.values()}
    cov = {gid: {"focus": 0, "routine": 0, "weeks": []} for gid in month_goals.keys()}
    week_focus_count = defaultdict(int)

    for wk in weeks.values():
        sel = weekly_plan.get(wk, {"focus": [], "routine": []})
        for bucket, name in [("focus", "focus"), ("routine", "routine")]:
            for raw in sel.get(name, []):
                gid = _normalize_text(raw)
                if gid in cov:
                    cov[gid][bucket] += 1
                    if wk not in cov[gid]["weeks"]:
                        cov[gid]["weeks"].append(wk)
        week_focus_count[wk] = len(sel.get("focus", []))

    num_weeks = len(weeks)
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

def generate_calendar_weeks(year: int, month: int):
    weeks = {}
    first_day = datetime.date(year, month, 1)
    last_day = datetime.date(year, month, calendar.monthrange(year, month)[1])
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

# --- 기본 변수들 ---
month_map = {"1월": 1, "2월": 2, "3월": 3, "4월": 4, "5월": 5, "6월": 6,
              "7월": 7, "8월": 8, "9월": 9, "10월": 10, "11월": 11, "12월": 12}

today_date = datetime.date.today()
today_name = today_date.strftime("%A")  

st.set_page_config(page_title="Time Focus Flow", layout="wide")
st.title("🧠 주간 시간관리 웹앱")
st.markdown("분기/월 목표에서 이번 주의 메인 목표를 선택하고, 실행 배경을 설계하세요.")

# --- [NEW] 주간 계획표 업로드 (엑셀 없이도 가능) ---
st.markdown("### 📦 이미 뽑아둔 주간 계획표 불러오기")

if "day_detail" not in st.session_state:
    st.session_state.day_detail = {}

uploaded_week_csv = st.file_uploader("📥 주간 계획표 CSV 업로드", type=["csv"], key="restore_weekly_plan")

# 버튼 없이 업로드 즉시 자동 적용되도록 변경
if uploaded_week_csv is not None:
    try:
        uploaded_week_csv.seek(0)
        try:
            df = pd.read_csv(uploaded_week_csv, encoding="utf-8-sig")
        except UnicodeDecodeError:
            uploaded_week_csv.seek(0)
            df = pd.read_csv(uploaded_week_csv, encoding="utf-8")

        if not set(["요일", "상세 플랜(메인)", "상세 플랜(배경)"]).issubset(df.columns):
            st.warning("CSV에 필요한 컬럼이 없습니다.")
        else:
            match = re.search(r"week\d+", uploaded_week_csv.name)
            week_key = match.group(0) if match else "week_manual"
            DAYS_KR = ["월","화","수","목","금","토","일"]

            # 세션 유지형 day_detail 보장
            if "day_detail" not in st.session_state:
                st.session_state.day_detail = {}
            if week_key not in st.session_state.day_detail:
                st.session_state.day_detail[week_key] = {d: {"main": [], "routine": []} for d in DAYS_KR}

            # CSV → 세션에 저장
            for _, row in df.iterrows():
                day = str(row["요일"]).strip()
                if not day or day not in DAYS_KR:
                    continue
                st.session_state.day_detail[week_key][day]["main"] = _parse_pipe_or_lines(row["상세 플랜(메인)"])
                st.session_state.day_detail[week_key][day]["routine"] = _parse_pipe_or_lines(row["상세 플랜(배경)"])

            # 주차 키 저장 (rerun 대비)
            st.session_state["selected_week_key_auto"] = week_key
            st.session_state["last_uploaded_week_csv"] = uploaded_week_csv.name

            st.success(f"✅ '{week_key}' 주간 계획표 자동 적용 완료!")
    except Exception as e:
        st.error(f"CSV 처리 오류: {e}")


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
    st.title("🧠 월별 포커스 선택 및 주간 메인/배경 구성")

    selected_month = st.selectbox("📅 월을 선택하세요", sorted(df["월"].dropna().unique()))

    year = datetime.date.today().year
    month_num = month_map[selected_month]
    
    weeks = generate_calendar_weeks(year, month_num)


    # 2. 해당 월 목표표 보기
    filtered = df[df["월"] == selected_month].reset_index(drop=True)
    st.markdown("### 🔍 해당 월의 목표 목록")
    st.dataframe(filtered[["프로젝트", "최대선", "최소선"]], use_container_width=True)

    
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
                "백그라운드 배경 (최대 5개)",
                options=all_goals,
                max_selections=5,
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
            "배경": ", ".join(r) if r else "선택 안됨"
        })
    
    summary_df = pd.DataFrame(summary_data)
    st.dataframe(summary_df, use_container_width=True)

    st.markdown("## 🔎 최대선 커버리지 피드백")

    # --- 요기부터: "이번달 주간 요약(summary_df)" 바로 밑에 붙이기 ---f
    
    month_goals = build_month_goals(filtered)  # 위에서 만든 filtered(선택 월 df) 사용
    cov_res = compute_coverage(weeks, st.session_state.weekly_plan, month_goals)
    
    # 1) 용량 진단
    if not cov_res["capacity_ok"]:
        st.error(
            f"최대선 개수({cov_res['num_max_goals']})가 이번달 포커스 슬롯 수({cov_res['total_focus_slots']})보다 많아요. "
            "일부 최대선을 다음 달로 미루거나, 우선순위를 조정하세요."
        )
    else:
        st.success(
            f"포커스 슬롯 충분 ✅ (최대선 {cov_res['num_max_goals']}개 / 사용 가능 슬롯 {cov_res['total_focus_slots']}개)"
        )
    
    # 2) 커버리지 표
    rows = []
    for gid, g in month_goals.items():
        cv = cov_res["coverage"][gid]
        rows.append({
            "구분": "최대선" if g["kind"]=="max" else "최소선",
            "목표": g["label"],
            "포커스 횟수": cv["focus"],
            "배경 횟수": cv["routine"],
            "배치 주": ", ".join(cv["weeks"]) if cv["weeks"] else "-",
            "상태": ("누락(포커스 미배정)" if (g["kind"]=="max" and cv["focus"]==0) else "OK")
        })
    cov_df = pd.DataFrame(rows).sort_values(["구분","상태","목표"])
    st.dataframe(cov_df, use_container_width=True)
    
    # 3) 누락 경고
    missing_max_labels = [month_goals[gid]["label"] for gid in cov_res["missing_focus"]]
    if missing_max_labels:
        st.warning("🚨 포커스로 배정되지 않은 ‘최대선’이 있습니다:\n- " + "\n- ".join(missing_max_labels))
    else:
        st.info("모든 ‘최대선’이 최소 1회 이상 포커스로 배정되었습니다. 👍")
    
    # ========= 새로 추가: "제안 미리보기" DF + 다운로드 =========
    # ====== 원본 유지: 제안만 적용한 '가상 계획' 생성/표시/다운로드 ======

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
            "📥 제안 미리보기 CSV", suggest_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="suggestions_preview.csv", mime="text/csv", key="dl_suggest_preview"
        )
    else:
        st.caption("현재 자동 제안 없음.")
    
    # ---------- 핵심: 원본을 복사해 '가상 계획'만 생성 ----------
    def _normalize_text(s: str) -> str:
        import unicodedata, re
        s = unicodedata.normalize("NFKC", str(s)).strip()
        s = re.sub(r"\s+", " ", s)
        return s
    
    def _snapshot_weekly_plan(plan_dict):
        snap = {}
        for wk, v in plan_dict.items():
            snap[wk] = {"focus": list(v.get("focus", [])), "routine": list(v.get("routine", []))}
        return snap
    
    def _build_virtual_plan(base_plan, suggestions, swaps, month_goals):
        """원본은 그대로 두고, 제안을 적용한 가상 계획과 로그를 반환"""
        virtual = _snapshot_weekly_plan(base_plan)  # 깊은 복사
        applied = []
    
        # 1) 빈 슬롯 add
        for wk, gid in suggestions:
            label = month_goals[gid]["label"]
            plan = virtual.get(wk, {"focus": [], "routine": []})
            if label not in plan["focus"] and len(plan["focus"]) < 2:
                plan["focus"].append(label)
                applied.append(("add", wk, label, "빈 슬롯에 최대선 배치"))
            virtual[wk] = plan
    
        # 2) routine→focus 승격 (2개 제한 유지, 넘치면 앞쪽 것을 잘라 2개만)
        for wk, gid in swaps:
            label = month_goals[gid]["label"]
            plan = virtual.get(wk, {"focus": [], "routine": []})
            plan["routine"] = [x for x in plan.get("routine", []) if _normalize_text(x) != gid]
            if label not in plan["focus"]:
                plan["focus"].append(label)
                if len(plan["focus"]) > 2:
                    # 정책: 가장 최근 2개만 유지
                    dropped = plan["focus"][:-2]
                    plan["focus"] = plan["focus"][-2:]
                    for dlab in dropped:
                        applied.append(("drop", wk, dlab, "과밀 조정(2개 제한)"))
                applied.append(("promote", wk, label, "routine→focus 승격"))
            virtual[wk] = plan
    
        return virtual, applied
    
    # ---------- 버튼: 가상 계획 만들기(원본 불변) ----------
    st.markdown("#### ✅ 제안 반영 시뮬레이션 (원본은 변경되지 않음)")
    
    if st.button("제안 반영한 '가상 계획' 생성"):
        original = _snapshot_weekly_plan(st.session_state.weekly_plan)
        virtual_plan, applied_log = _build_virtual_plan(original, cov_res["suggestions"], cov_res["swaps"], month_goals)
    
        # 주차별 diff
        diff_rows = []
        for wk in weeks.values():
            b_focus = set(original.get(wk, {}).get("focus", []))
            a_focus = set(virtual_plan.get(wk, {}).get("focus", []))
            added = sorted(list(a_focus - b_focus))
            removed = sorted(list(b_focus - a_focus))
            diff_rows.append({
                "주차": wk,
                "추가된 포커스": " | ".join(added) if added else "-",
                "제거된 포커스(가상)": " | ".join(removed) if removed else "-",
                "가상 계획 포커스": " | ".join(virtual_plan.get(wk, {}).get("focus", [])) if virtual_plan.get(wk) else "-",
                "가상 계획 배경":  " | ".join(virtual_plan.get(wk, {}).get("routine", [])) if virtual_plan.get(wk) else "-",
            })
        diff_df = pd.DataFrame(diff_rows)
    
        st.success("가상 계획이 생성되었습니다. (원래 계획은 그대로입니다)")
        st.markdown("##### 🔁 반영 결과(diff, 원본 vs. 가상)")
        st.dataframe(diff_df, use_container_width=True)
        st.download_button(
            "📥 반영 결과(diff) CSV", diff_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="weekly_plan_virtual_diff.csv", mime="text/csv", key="dl_virtual_diff"
        )
    
        # 가상 계획 전체 표(주차별 포커스/배경)
        st.markdown("##### 🗂 가상 계획(제안 반영본) 일람")
        plan_rows = []
        for label, wk in weeks.items():
            v = virtual_plan.get(wk, {"focus": [], "routine": []})
            plan_rows.append({
                "주차": label,
                "포커스(가상)": " | ".join(v.get("focus", [])) or "-",
                "배경(가상)":  " | ".join(v.get("routine", [])) or "-",
            })
        virtual_df = pd.DataFrame(plan_rows)
        st.dataframe(virtual_df, use_container_width=True)
        st.download_button(
            "📥 가상 계획 CSV", virtual_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="weekly_plan_virtual.csv", mime="text/csv", key="dl_virtual_plan"
        )
    
        # 적용 로그도 제공
        if applied_log:
            log_df = pd.DataFrame(applied_log, columns=["action","week_key","label","note"])
            st.markdown("##### 🧾 가상 적용 로그")
            st.dataframe(log_df, use_container_width=True)
            st.download_button(
                "📥 가상 적용 로그 CSV", log_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="virtual_applied_actions_log.csv", mime="text/csv", key="dl_virtual_log"
            )
        else:
            st.caption("실행된 가상 조치가 없습니다.")

#--------테스트    
    current_week_label = find_current_week_label(weeks)

    if current_week_label:
        st.markdown(f"### 📅 이번 주: **{current_week_label}**")
        plan = st.session_state.weekly_plan.get(weeks[current_week_label], {})
    else:
        st.warning("오늘 날짜에 해당하는 주차를 찾을 수 없습니다.")
        plan = {"focus": [], "routine": []}
    # ---

    DAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]
    
    # --- (전제) 주차 선택: 해당 주만 보이도록 ---
    # weeks = {"1주차 (10/7~10/13)": "week1", ...} 가 이미 있다고 가정
    selected_week_label = st.selectbox("📆 체크할 주 차를 선택하세요", list(weeks.keys()))
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
    
    st.markdown(f"### 🗓 {selected_week_label} — 월-일 가로 블록 + 상세 플랜")
    
    # --- 이 주의 메인/배경 가져오기 ---
    plan = st.session_state.weekly_plan.get(selected_week_key, {"focus": [], "routine": []})
    mains = plan.get("focus", [])[:2]  # 메인 최대 2개
    routines = plan.get("routine", [])
    
    if not mains:
        st.info("이 주차에 메인이 없습니다. 먼저 ‘주차별 메인/배경’을 선택해주세요.")
        st.stop()
    
    main_a = mains[0]
    main_b = mains[1] if len(mains) > 1 else None
    
    # --- 자동 배치 로직 ---
    def auto_place_blocks(main_a: str, main_b: str | None, routines: list[str]):
        """
        월/수/금 → A, 화/목/금 → B, 금요일은 마무리/체크업,
        토/일은 미완료 보완/보충. 배경은 요일별로 순환 삽입.
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
    
        # 배경을 요일별로 고르게 순환 삽입
        if routines:
            ri = 0
            for d in DAYS_KR:
                # 금요일엔 '마무리'가 있으니 배경은 1개만 제안
                if d == "금":
                    day_blocks[d].append(f"배경: {routines[ri % len(routines)]}"); ri += 1
                else:
                    # 평일 1~2개, 주말 1개 정도로 제안 (필요시 조절 가능)
                    day_blocks[d].append(f"배경: {routines[ri % len(routines)]}"); ri += 1
    
        return day_blocks
    
    default_blocks = auto_place_blocks(main_a, main_b, routines)
    
    # --- 상세 플랜 저장 구조: { week_key: { day: {"main":[], "routine":[]} } } ---
    # --- 상세 플랜 저장 구조 초기화 ---
    # --- 상세 플랜 저장 구조: { week_key: { day: {"main":[], "routine":[]} } } ---
# --- 상세 플랜 저장 구조 초기화 ---
    if "day_detail" not in st.session_state:
        st.session_state.day_detail = {}
    
    DAYS_KR = ["월","화","수","목","금","토","일"]  # ← 안전 가드(외부에서 못 받았을 때 대비)
    
    # --- [수정] 기존 week_plan CSV 업로드: 버튼 없이 업로드 즉시 적용 ---
    uploaded_week_csv = st.file_uploader(
        "📥 기존 주간 계획표 업로드 (예: week_plan_week2-2.csv)",
        type=["csv"],
        key="weekly_restore"
    )
    
    if uploaded_week_csv is not None:
        try:
            uploaded_week_csv.seek(0)
            try:
                df = pd.read_csv(uploaded_week_csv, encoding="utf-8-sig")
            except UnicodeDecodeError:
                uploaded_week_csv.seek(0)
                df = pd.read_csv(uploaded_week_csv, encoding="utf-8")
    
            # 필수 컬럼 확인
            required_cols = {"요일", "상세 플랜(메인)", "상세 플랜(배경)"}
            if not required_cols.issubset(df.columns):
                st.warning("CSV에 필요한 컬럼(요일, 상세 플랜(메인), 상세 플랜(배경))이 없습니다.")
            else:
                # 파일명에서 week_key 추출
                match = re.search(r"week\d+", uploaded_week_csv.name or "")
                week_key = match.group(0) if match else "week_manual"
    
                # 세션 구조 보장
                if week_key not in st.session_state.day_detail:
                    st.session_state.day_detail[week_key] = {d: {"main": [], "routine": []} for d in DAYS_KR}
    
                # 결측/공백 정리
                df = df.fillna("")
                df["요일"] = df["요일"].astype(str).str.strip()
    
                # CSV → 세션 반영
                updated = 0
                for _, row in df.iterrows():
                    day = str(row["요일"]).strip()
                    if day and day in DAYS_KR:
                        st.session_state.day_detail[week_key][day]["main"] = _parse_pipe_or_lines(row["상세 플랜(메인)"])
                        st.session_state.day_detail[week_key][day]["routine"] = _parse_pipe_or_lines(row["상세 플랜(배경)"])
                        updated += 1
    
                # 주차 키/파일명 세션 저장 (아래 섹션에서 자동 선택되도록)
                st.session_state["selected_week_key_auto"] = week_key
                st.session_state["last_uploaded_week_csv"] = uploaded_week_csv.name
    
                st.success(f"✅ {week_key} 주간 계획표 적용 완료! ({updated}개 요일 갱신)")
    
        except Exception as e:
            st.error(f"CSV 처리 오류: {e}")
    
    
    # --- ✅ 주차 선택 여부와 관계없이 CSV 추가 업로드/덮어쓰기 가능 ---
    st.markdown("### 📎 CSV로 상세 플랜 불러오기 (주차 선택 전에도 가능)")
    with st.expander("CSV 업로드 옵션 열기", expanded=False):
        apply_mode = st.radio(
            "적용 방식",
            ["비어있지 않은 값만 덮어쓰기", "완전 덮어쓰기(메인/루틴 전부 교체)"],
            index=0,
            horizontal=True,
            key="apply_mode_global"
        )
    
        uploaded_csv = st.file_uploader(
            "CSV 파일 업로드 (utf-8-sig, 예: week_plan_*.csv)",
            type=["csv"],
            key="csv_upload_global"
        )
    
        if uploaded_csv is not None and st.button("🪄 CSV 불러오기 적용", key="apply_csv_global"):
            try:
                uploaded_csv.seek(0)
                try:
                    df = pd.read_csv(uploaded_csv, encoding="utf-8-sig")
                except UnicodeDecodeError:
                    uploaded_csv.seek(0)
                    df = pd.read_csv(uploaded_csv, encoding="utf-8")
    
                if "요일" not in df.columns:
                    st.warning("CSV에 '요일' 컬럼이 없습니다. 다운로드한 형식을 사용해주세요.")
                else:
                    df = df.fillna("")
                    df["요일"] = df["요일"].astype(str).str.strip()
    
                    # 요일 → 값 매핑
                    csv_map = {}
                    for _, row in df.iterrows():
                        day = str(row.get("요일", "")).strip()
                        if not day:
                            continue
                        main_raw = row.get("상세 플랜(메인)", "")
                        routine_raw = row.get("상세 플랜(루틴)", "")
                        csv_map[day] = {
                            "main": _parse_pipe_or_lines(main_raw),
                            "routine": _parse_pipe_or_lines(routine_raw),
                        }
    
                    # 현재 선택 주차키: 업로드 주차키가 있으면 그걸 우선 사용
                    active_week = (
                        st.session_state.get("selected_week_key_auto")
                        or (locals().get("selected_week_key") if "selected_week_key" in locals() else None)
                        or "global_week"
                    )
                    if active_week not in st.session_state.day_detail:
                        st.session_state.day_detail[active_week] = {d: {"main": [], "routine": []} for d in DAYS_KR}
    
                    updated_count = 0
                    for d in DAYS_KR:
                        if d not in csv_map:
                            continue
                        new_main = csv_map[d]["main"]
                        new_routine = csv_map[d]["routine"]
    
                        if apply_mode.startswith("완전 덮어쓰기"):
                            st.session_state.day_detail[active_week][d]["main"] = new_main
                            st.session_state.day_detail[active_week][d]["routine"] = new_routine
                            updated_count += 1
                        else:
                            if new_main:
                                st.session_state.day_detail[active_week][d]["main"] = new_main
                            if new_routine:
                                st.session_state.day_detail[active_week][d]["routine"] = new_routine
                            if new_main or new_routine:
                                updated_count += 1
    
                    st.success(f"✅ CSV 적용 완료 — {updated_count}개 요일의 상세 플랜이 갱신되었습니다. (주차: {active_week})")
    
            except Exception as e:
                st.error(f"CSV 처리 중 오류: {e}")



    st.markdown("### ✅ 이 주 요약표 (당신이 적은 상세 플랜 기준)")
    st.markdown("---")
    
    DAYS_KR = ["월","화","수","목","금","토","일"]
    rows = []
    
    selected_week_key = (
        st.session_state.get("selected_week_key_auto")
        or locals().get("selected_week_key")
        or "week_manual"
    )
    
    if "day_detail" not in st.session_state:
        st.session_state.day_detail = {}
    if selected_week_key not in st.session_state.day_detail:
        st.session_state.day_detail[selected_week_key] = {d: {"main": [], "routine": []} for d in DAYS_KR}
    
    if "week_dates" not in locals() or not week_dates:
        today = datetime.date.today()
        week_dates = [today + datetime.timedelta(days=i) for i in range(7)]
    if "default_blocks" not in locals():
        default_blocks = {d: [] for d in DAYS_KR}
    
    for i, d in enumerate(DAYS_KR):
        date_str = f"{week_dates[i].month}/{week_dates[i].day}"
        auto_items = default_blocks.get(d, [])
        auto_main = [x for x in auto_items if not x.startswith("배경:")]
        auto_routine = [x for x in auto_items if x.startswith("배경:")]
        detail_main = st.session_state.day_detail[selected_week_key][d]["main"]
        detail_routine = st.session_state.day_detail[selected_week_key][d]["routine"]
        final_main = detail_main if detail_main else auto_main
        final_routine = detail_routine if detail_routine else auto_routine
        rows.append({
            "요일": d,
            "날짜": date_str,
            "상세 플랜(메인)": " | ".join(detail_main) if detail_main else "-",
            "상세 플랜(배경)": " | ".join(detail_routine) if detail_routine else "-",
        })
    
    week_df = pd.DataFrame(rows)
    st.dataframe(week_df, use_container_width=True)
    csv = week_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 이 주 계획 CSV 다운로드", data=csv, file_name=f"week_plan_{selected_week_key}.csv", mime="text/csv")
    
    # ✅ [수정③] 오늘의 실행 체크리스트 접근 안전화
    st.markdown("---")
    st.markdown("### ✅ 오늘의 실행 체크리스트")
    
    today = datetime.date.today()
    days_map = {0:"월",1:"화",2:"수",3:"목",4:"금",5:"토",6:"일"}
    sel_day = days_map[today.weekday()]
    
    if selected_week_key not in st.session_state.day_detail:
        st.session_state.day_detail[selected_week_key] = {day: {"main": [], "routine": []} for day in DAYS_KR}
    if sel_day not in st.session_state.day_detail[selected_week_key]:
        st.session_state.day_detail[selected_week_key][sel_day] = {"main": [], "routine": []}
    
    detail_main = st.session_state.day_detail[selected_week_key][sel_day]["main"]
    detail_routine = st.session_state.day_detail[selected_week_key][sel_day]["routine"]
    
    st.write(f"🗓 오늘({sel_day})의 메인: ", " | ".join(detail_main) if detail_main else "없음")
    st.write(f"🌿 오늘의 배경: ", " | ".join(detail_routine) if detail_routine else "없음")
    
    if "state_loaded_once" not in st.session_state:
        load_state()
        st.session_state["state_loaded_once"] = True
    
    save_state()
    
#     st.markdown("---")
#     st.markdown("### ✅ 오늘의 실행 체크리스트")

#     # --- CSV로 상세 플랜 불러오기/덮어쓰기 옵션 ---
#     st.markdown("#### 📎 CSV에서 상세 플랜 불러오기")
#     with st.expander("CSV 적용 옵션 열기", expanded=False):
#         apply_mode = st.radio(
#             "적용 방식",
#             ["비어있지 않은 값만 덮어쓰기", "완전 덮어쓰기(해당 요일 메인/배경 전부 교체)"],
#             index=0,
#             horizontal=True,
#         )
#         uploaded_csv = st.file_uploader("이 주 계획 CSV 업로드 (이전에 다운로드한 포맷 권장, utf-8-sig)", type=["csv"])
    
#         def _parse_pipe_or_lines(s: str):
#             if not s:
#                 return []
#             s = str(s)
#             # 다운로드 포맷: "a | b | c" 형태 → 우선 '|' 기준, 대안으로 줄바꿈/콤마도 허용
#             if "|" in s:
#                 parts = [x.strip() for x in s.split("|")]
#             else:
#                 parts = []
#                 for sep in ["\n", ","]:
#                     if sep in s:
#                         parts = [x.strip() for x in s.split(sep)]
#                         break
#                 if not parts:  # 구분자 없음 → 단일 항목
#                     parts = [s.strip()]
#             return [x for x in parts if x]
    
#         if uploaded_csv is not None and st.button("🪄 CSV 적용"):
#             try:
#                 import pandas as pd
#                 uploaded_csv.seek(0)
#                 try:
#                     df = pd.read_csv(uploaded_csv, encoding="utf-8-sig")
#                 except UnicodeDecodeError:
#                     uploaded_csv.seek(0)
#                     df = pd.read_csv(uploaded_csv, encoding="utf-8")
    
#                 # 필요한 컬럼 확인 (우리는 '요일', '상세 플랜(메인)', '상세 플랜(배경)'만 사용)
#                 if "요일" not in df.columns:
#                     st.warning("CSV에 '요일' 컬럼이 없습니다. 기존 다운로드한 포맷을 사용해 주세요.")
#                 else:
#                     df = df.fillna("")
#                     df["요일"] = df["요일"].astype(str).str.strip()
    
#                     # 요일 → (main, routine) 매핑 생성
#                     csv_map = {}
#                     for _, row in df.iterrows():
#                         day = str(row.get("요일", "")).strip()
#                         if not day:
#                             continue
#                         main_raw = row.get("상세 플랜(메인)", "")
#                         routine_raw = row.get("상세 플랜(배경)", "")
#                         csv_map[day] = {
#                             "main": _parse_pipe_or_lines(main_raw),
#                             "routine": _parse_pipe_or_lines(routine_raw),
#                         }
    
#                     # 세션 상태에 반영
#                     updated_count = 0
#                     for d in DAYS_KR:
#                         if d not in csv_map:
#                             continue
#                         new_main = csv_map[d]["main"]
#                         new_routine = csv_map[d]["routine"]
    
#                         if apply_mode.startswith("완전 덮어쓰기"):
#                             st.session_state.day_detail[selected_week_key][d]["main"] = new_main
#                             st.session_state.day_detail[selected_week_key][d]["routine"] = new_routine
#                             updated_count += 1
#                         else:
#                             # 비어있지 않은 값만 덮어쓰기
#                             if new_main:
#                                 st.session_state.day_detail[selected_week_key][d]["main"] = new_main
#                             if new_routine:
#                                 st.session_state.day_detail[selected_week_key][d]["routine"] = new_routine
#                             if new_main or new_routine:
#                                 updated_count += 1
    
#                     st.success(f"CSV 적용 완료! {updated_count}개 요일의 상세 플랜이 갱신되었습니다.")
#             except Exception as e:
#                 st.error(f"CSV 처리 중 오류가 발생했습니다: {e}")

  
#     # 1) 오늘 날짜/요일 자동 인식 + 필요시 수동 변경
#     today = datetime.date.today()
#     today_idx_auto = today.weekday()  # 0=월 ... 6=일
#     days_map = {0:"월",1:"화",2:"수",3:"목",4:"금",5:"토",6:"일"}
#     auto_day_label = days_map[today_idx_auto]
#     st.caption(f"자동 감지된 오늘 요일: {auto_day_label}")
    
#     day_options = DAYS_KR  # ["월","화","수","목","금","토","일"]
#     sel_day = st.selectbox("🗓 오늘 요일을 선택/확인하세요", day_options, index=today_idx_auto if today_idx_auto < len(day_options) else 0)
    
#     # 2) 오늘에 해당하는 상세 플랜(메인/배경) 불러오기 (없으면 자동 제안으로 대체)
#     detail_main = st.session_state.day_detail[selected_week_key][sel_day]["main"]
#     detail_routine = st.session_state.day_detail[selected_week_key][sel_day]["routine"]
    
#     auto_items = default_blocks.get(sel_day, []) if isinstance(default_blocks, dict) else []
#     auto_main = [x for x in auto_items if not x.startswith("배경:")]
#     auto_routine = [x for x in auto_items if x.startswith("배경:")]
    
#     final_main = detail_main if detail_main else auto_main
#     final_routine = detail_routine if detail_routine else auto_routine
    
#     # 3) 태스크 목록 만들기 (메인/배경에 라벨 붙이기)
#     today_tasks = []
#     today_tasks += [("[메인]", t) for t in final_main]
#     today_tasks += [("[배경]", t.replace("배경:", "").strip()) for t in final_routine]
    
#     # 4) 체크 상태 저장소 준비 (날짜+주차 기준으로 저장)
#     if "completed_by_day" not in st.session_state:
#         st.session_state.completed_by_day = {}  # dict[(week_key, date_str)] = set(labels)
    
#     # 주차의 특정 날짜 문자열 (선택 주의 해당 요일 날짜가 있으면 그걸 사용)
#     if week_dates:
#         # 선택 주의 day index를 구함
#         day_idx = DAYS_KR.index(sel_day)
#         date_str = f"{week_dates[day_idx].isoformat()}"
#     else:
#         date_str = today.isoformat()  # fallback
    
#     store_key = (selected_week_key, date_str)
#     if store_key not in st.session_state.completed_by_day:
#         st.session_state.completed_by_day[store_key] = set()
    
#     # 5) 체크박스 렌더 + 진행률
#     completed = st.session_state.completed_by_day[store_key]
    
#     def task_key(prefix, text):
#         raw = f"{selected_week_key}|{date_str}|{prefix}|{text}"
#         return "chk_" + hashlib.md5(raw.encode("utf-8")).hexdigest()
    
#     if not today_tasks:
#         st.info("오늘 체크할 항목이 없습니다. (해당 요일의 상세 플랜을 적거나, 주차 자동 제안을 확인해주세요.)")
#     else:
#         for kind, text in today_tasks:
#             label = f"{kind} {text}"
#             key = task_key(kind, text)
#             default_checked = label in completed
#             checked = st.checkbox(label, value=default_checked, key=key)
#             if checked:
#                 completed.add(label)
#             else:
#                 completed.discard(label)
    
#         percent = int(len(completed) / len(today_tasks) * 100)
#         st.progress(percent)
#         st.write(f"📊 오늘의 달성률: **{percent}%** ({len(completed)} / {len(today_tasks)})")
    
#     # 6) (선택) 오늘 체크 내역 표/다운로드
#     with st.expander("📋 오늘 체크 내역 보기/내보내기"):
#         rows = [{"날짜": date_str, "유형": kind, "할 일": text, "완료": (f"{kind} {text}" in completed)} for kind, text in today_tasks]
#         df_today = pd.DataFrame(rows)
#         st.dataframe(df_today, use_container_width=True)
#         csv_today = df_today.to_csv(index=False).encode("utf-8-sig")
#         st.download_button("📥 오늘 체크 내역 CSV 다운로드", data=csv_today, file_name=f"today_tasks_{date_str}.csv", mime="text/csv")
 
#     # --- 주간 회고 ---
#     st.markdown("### 📝 이번 주 회고 메모")
#     if "weekly_review" not in st.session_state:
#         st.session_state.weekly_review = {}
    
#     current_review = st.session_state.weekly_review.get(selected_week_key, "")
#     review_text = st.text_area(
#         "이번 주를 돌아보며 남기고 싶은 메모",
#         value=current_review,
#         key=f"review::{selected_week_key}",
#         height=140,
#         placeholder="이번 주 무엇을 배웠는지, 다음 주에 개선할 1가지만 적어도 좋아요."
#     )

#     st.session_state.weekly_review[selected_week_key] = review_text

# if "state_loaded_once" not in st.session_state:
#     load_state()
#     st.session_state["state_loaded_once"] = True
# # 페이지 맨 끝 (모든 UI 렌더 후)
# save_state()

