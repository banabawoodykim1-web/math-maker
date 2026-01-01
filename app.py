import streamlit as st
import pandas as pd
import logic
import io
import streamlit_authenticator as stauth
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from datetime import datetime, timedelta
import time
import requests 
import uuid
import base64
import streamlit.components.v1 as components

# -----------------------------------------------------------------------------
# 1. 페이지 설정
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="지니매쓰 - Genie Math",
    page_icon="🧞‍♂️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------------------------
# [스타일] CSS (엑셀 스타일 리스트 구현)
# -----------------------------------------------------------------------------
st.markdown("""
<style>
    html, body, [class*="css"] { font-family: 'Pretendard', 'Apple SD Gothic Neo', 'NanumGothic', 'Malgun Gothic', sans-serif !important; }
    .stApp{background-color:#F3F4F6;}
    
    .control-card { background-color: #FFFFFF; padding: 25px 30px; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid #E5E7EB; margin-bottom: 20px; }
    .card-header { font-size: 1.2rem; font-weight: 700; color: #1F2937; margin-bottom: 15px; display: flex; align-items: center; gap: 8px; }
    
    .product-card { 
        background-color: white; 
        border: 2px solid #E5E7EB; 
        border-radius: 15px; 
        padding: 20px; 
        text-align: center; 
        height: 220px; 
        display: flex; 
        flex-direction: column; 
        justify-content: center; 
        margin-bottom: 15px;
    }

    /* [핵심] 보관함 리스트 스타일링 (제목 버튼화) */
    .history-header-row {
        background-color: #F3F4F6;
        padding: 10px 15px;
        border-top: 2px solid #E5E7EB;
        border-bottom: 2px solid #E5E7EB;
        font-weight: bold;
        color: #374151;
        font-size: 0.95rem;
        display: flex;
        align-items: center;
    }
    
    /* 제목(다운로드 버튼)을 텍스트 링크처럼 보이게 커스텀 */
    div[data-testid="stVerticalBlock"] .stDownloadButton button {
        border: none !important;
        background: transparent !important;
        text-align: left !important;
        justify-content: flex-start !important;
        padding-left: 0 !important;
        color: #111827 !important;
        font-weight: 500 !important;
        font-size: 1rem !important;
        width: 100% !important;
    }
    div[data-testid="stVerticalBlock"] .stDownloadButton button:hover {
        color: #2563EB !important;
        background-color: #F9FAFB !important;
        text-decoration: underline !important;
    }
    
    /* 날짜 텍스트 정렬 */
    .date-text {
        font-size: 0.9rem;
        color: #6B7280;
        display: flex;
        align-items: center;
        height: 100%;
        padding-top: 10px; /* 버튼 높이와 맞추기 위한 미세 조정 */
    }

    /* 메인 생성 탭의 다운로드 버튼은 여전히 크고 파랗게 유지 */
    .big-download-btn button {
        background-color: #2563EB !important;
        color: white !important;
        border-radius: 8px !important;
        text-align: center !important;
        justify-content: center !important;
        font-weight: bold !important;
        padding: 12px !important;
    }
    
    .cs-btn button { background-color: #FEE500; color: #3C1E1E; border: none; padding: 8px 15px; border-radius: 20px; font-weight: bold; font-size: 0.9rem; cursor: pointer; }
    header{visibility:hidden;}
    footer{visibility:hidden;}
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# [진단] 시스템 상태 점검
# -----------------------------------------------------------------------------
st.sidebar.title("🛠 시스템 점검")

ai_email = "확인 불가"
try:
    if "gcp_service_account" in st.secrets:
        ai_email = st.secrets["gcp_service_account"]["client_email"]
        st.sidebar.success("✅ GCP 키 로드 성공")
        st.sidebar.info(f"🤖 **현재 AI 이메일:**\n\n`{ai_email}`")
        st.sidebar.warning("위 이메일이 구글 드라이브 폴더에 [편집자]로 초대되어 있어야 합니다!")
    else:
        st.sidebar.error("❌ GCP 키 없음")
        
    if "google_drive" in st.secrets:
        DRIVE_FOLDER_ID = st.secrets["google_drive"]["folder_id"]
        st.sidebar.success("✅ 폴더 ID 설정됨")
    else:
        DRIVE_FOLDER_ID = ""
        st.sidebar.error("❌ 폴더ID 없음")

    if "toss_payments" in st.secrets:
        TOSS_CLIENT_KEY = st.secrets["toss_payments"]["client_key"]
        TOSS_SECRET_KEY = st.secrets["toss_payments"]["secret_key"]
    else:
        TOSS_CLIENT_KEY = "TEST"; TOSS_SECRET_KEY = "TEST"

except Exception as e:
    st.sidebar.error(f"시크릿 로드 오류: {e}")

CS_LINK = "https://open.kakao.com/o/sample" 

# 세션 초기화
if "file_history" not in st.session_state: st.session_state["file_history"] = []
if "processed_list" not in st.session_state: st.session_state["processed_list"] = []
if "alert_msg" not in st.session_state: st.session_state["alert_msg"] = None

# -----------------------------------------------------------------------------
# 2. 구글 연동 함수
# -----------------------------------------------------------------------------
def get_gcp_creds():
    try:
        if "gcp_service_account" not in st.secrets: return None
        key_dict = st.secrets["gcp_service_account"]
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        return ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
    except: return None

def get_db_client():
    creds = get_gcp_creds()
    if not creds: return None
    return gspread.authorize(creds)

def get_drive_service():
    creds = get_gcp_creds()
    if not creds: return None
    return build('drive', 'v3', credentials=creds)

def upload_to_drive(file_obj, filename):
    if not DRIVE_FOLDER_ID:
        st.session_state["alert_msg"] = "❌ 설정 오류: Secrets에 folder_id가 비어있습니다."
        return None
    try:
        service = get_drive_service()
        if not service: 
            st.session_state["alert_msg"] = "❌ 인증 오류: 구글 드라이브 서비스 연결 실패"
            return None
        
        file_metadata = {'name': filename, 'parents': [DRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(file_obj, mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e: 
        st.session_state["alert_msg"] = f"❌ 업로드 실패: {str(e)}\n\n💡 힌트: `{ai_email}` 계정이 폴더에 [편집자]로 초대되었나요?"
        return None

def download_from_drive(file_id):
    try:
        service = get_drive_service()
        request = service.files().get_media(fileId=file_id)
        file = io.BytesIO()
        downloader = MediaIoBaseDownload(file, request)
        done = False
        while done is False: status, done = downloader.next_chunk()
        file.seek(0)
        return file
    except Exception as e:
        st.error(f"❌ 다운로드 실패: {str(e)}")
        return None

def fetch_all_users():
    client = get_db_client()
    if not client: return []
    try: return client.open("math_app_db").worksheet("users").get_all_records()
    except Exception as e:
        return []

def register_user(new_username, new_name, new_password):
    client = get_db_client()
    if not client: return "DB 연결 실패"
    try:
        sheet = client.open("math_app_db").worksheet("users")
        existing_users = sheet.col_values(1)
        if new_username in existing_users: return "DUPLICATE"
        hashed_pw = stauth.Hasher([new_password]).generate()[0]
        sheet.append_row([new_username, hashed_pw, new_name, 5])
        return "SUCCESS"
    except Exception as e: return str(e)

def get_user_credits(username, force_refresh=False):
    if "cached_credits" in st.session_state and not force_refresh:
        return st.session_state["cached_credits"]
    
    client = get_db_client()
    if not client: return 0
    try:
        sheet = client.open("math_app_db").worksheet("users")
        cell = sheet.find(username)
        if cell:
            val = sheet.cell(cell.row, 4).value
            try: credits = int(val)
            except: credits = 0
            st.session_state["cached_credits"] = credits
            return credits
        else: return 0
    except Exception as e:
        return st.session_state.get("cached_credits", 0)

def add_credit(username, amount):
    client = get_db_client()
    if not client: return
    try:
        sheet = client.open("math_app_db").worksheet("users")
        cell = sheet.find(username)
        current = int(sheet.cell(cell.row, 4).value)
        new_amount = current + amount
        sheet.update_cell(cell.row, 4, new_amount)
        st.session_state["cached_credits"] = new_amount
    except: pass

def deduct_credit(username, amount):
    add_credit(username, -amount)

def log_activity(username, type_or_school, detail_or_grade, extra1="", extra2="", extra3="", file_id=""):
    client = get_db_client()
    if not client: return
    try:
        sheet = client.open("math_app_db").worksheet("logs")
        kst_now = datetime.now() + timedelta(hours=9)
        now_str = kst_now.strftime("%Y-%m-%d %H:%M:%S")
        
        row = [now_str, username, type_or_school, detail_or_grade, extra1, extra2, extra3, file_id]
        sheet.append_row(row)
    except Exception as e:
        print(f"로그 저장 실패: {e}")

def format_kor_date(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%m.%d %H:%M") 
    except:
        return date_str

def get_user_history_processed(username):
    client = get_db_client()
    if not client: return []
    try:
        sheet = client.open("math_app_db").worksheet("logs")
        records = sheet.get_all_values()
        
        my_logs = []
        if len(records) < 2: return []
        
        for row in records[1:]:
            if len(row) > 7:
                r_user = str(row[1]).strip()
                r_file = str(row[7]).strip()
                
                if r_user == username and r_file != "":
                    activity_type = str(row[2]).strip()
                    detail_content = str(row[3]).strip()
                    if activity_type == "문제생성":
                        base_desc = detail_content
                    else:
                        base_desc = f"{activity_type} {detail_content}"
                        
                    my_logs.append({
                        "raw_date": str(row[0]),
                        "base_desc": base_desc,
                        "file_id": r_file
                    })
        
        topic_counts = {}
        processed_history = []
        
        for item in my_logs:
            topic = item["base_desc"]
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
            count = topic_counts[topic]
            final_desc = f"{topic} ({count})"
            
            processed_history.append({
                "date": format_kor_date(item["raw_date"]),
                "desc": final_desc,
                "file_id": item["file_id"]
            })
            
        return processed_history[::-1]
        
    except Exception as e:
        return []

def check_daily_free_used(username):
    client = get_db_client()
    if not client: return True 
    try:
        sheet = client.open("math_app_db").worksheet("logs")
        records = sheet.get_all_values()
        today_str = (datetime.now() + timedelta(hours=9)).strftime("%Y-%m-%d")
        for row in reversed(records):
            if len(row) > 4:
                if row[0].startswith(today_str) and row[1] == username and row[4] == "DAILY_FREE":
                    return True
        return False
    except: return True

def confirm_toss_payment(payment_key, order_id, amount):
    url = "https://api.tosspayments.com/v1/payments/confirm"
    secret_key_str = f"{TOSS_SECRET_KEY}:"
    encoded_key = base64.b64encode(secret_key_str.encode("utf-8")).decode("utf-8")
    headers = {"Authorization": f"Basic {encoded_key}", "Content-Type": "application/json"}
    data = {"paymentKey": payment_key, "orderId": order_id, "amount": amount}
    try:
        res = requests.post(url, json=data, headers=headers)
        return res.json()
    except Exception as e: return {"error": str(e)}

@st.cache_data(ttl=3600) 
def load_curriculum_optimized():
    try: 
        df = pd.read_excel("통합_수학_커리큘럼.xlsx")
        df['grade'] = df['grade'].astype(str).str.replace('학년', '')
        df['search_label'] = df['school'] + " " + df['grade'] + "학년 - " + df['unit']
        return df
    except: 
        return pd.DataFrame({"school":["초등"],"grade":["3"],"unit":["샘플"],"search_label":["초등 3학년 - 샘플 데이터"]})

# -----------------------------------------------------------------------------
# 로그인
# -----------------------------------------------------------------------------
users_data = fetch_all_users()
if not users_data:
    st.sidebar.error("🚨 DB 연결 실패: users 시트를 읽을 수 없습니다.")
    names, usernames, hashed_passwords = ["관리자"], ["admin"], ["$2b$12$EXAMPLE..."]
else:
    names, usernames, hashed_passwords = [], [], []
    for user in users_data:
        usernames.append(str(user['username']))
        names.append(str(user['name']))
        hashed_passwords.append(str(user['password']))

authenticator = stauth.Authenticate(names, usernames, hashed_passwords, 'mk_cookie', 'mk_key', cookie_expiry_days=30)

if 'authentication_status' not in st.session_state or st.session_state['authentication_status'] is None:
    tab1, tab2 = st.tabs(["🔑 로그인", "📝 회원가입"])
    with tab1:
        name, authentication_status, username = authenticator.login('main')
        if authentication_status == False: st.error('로그인 실패')
    with tab2:
        with st.form("signup"):
            uid = st.text_input("ID"); uname = st.text_input("이름"); upw = st.text_input("PW", type="password")
            st.caption("✨ 가입 즉시 무료 이용권 5장을 드립니다!")
            if st.form_submit_button("가입"):
                res = register_user(uid, uname, upw)
                if res=="SUCCESS": st.success("가입 완료! 로그인 해주세요.")
                else: st.error(res)
else:
    username = st.session_state['username']
    name = st.session_state['name']
    authentication_status = True

if authentication_status:
    
    if "credits_refreshed" not in st.session_state:
        get_user_credits(username, force_refresh=True)
        st.session_state["credits_refreshed"] = True

    curr_credits = get_user_credits(username)
    
    query_params = st.query_params
    my_app_url = "https://math-maker-try.streamlit.app" 

    if "paymentKey" in query_params and "orderId" in query_params:
        st.markdown("<h2 style='text-align:center;'>💸 결제 처리 결과</h2>", unsafe_allow_html=True)
        payment_key = query_params["paymentKey"]
        order_id = query_params["orderId"]
        amount = int(query_params["amount"])
        
        if payment_key in st.session_state["processed_list"]:
            st.info("✅ 이미 완료된 결제입니다.")
            st.markdown(f'<br><a href="{my_app_url}" target="_self" style="text-decoration:none;"><button style="width:100%; background-color:#2563EB; color:white; padding:15px; border:none; border-radius:12px; font-size:1.1rem; font-weight:bold; cursor:pointer;">🏠 홈으로 돌아가기</button></a>', unsafe_allow_html=True)
            st.stop()
        else:
            with st.spinner("승인 처리 중..."):
                result = confirm_toss_payment(payment_key, order_id, amount)
            
            if "status" in result and result["status"] == "DONE":
                if amount == 1000: added_credits = 20
                elif amount == 5000: added_credits = 110
                elif amount == 10000: added_credits = 240
                elif amount == 30000: added_credits = 750
                else: added_credits = 0
                
                add_credit(username, added_credits)
                log_activity(username, "결제완료", f"{amount}원", "충전", f"+{added_credits}장", "")
                st.session_state["processed_list"].append(payment_key)
                st.balloons()
                st.success(f"🎉 결제 성공! {added_credits}장이 충전되었습니다.")
                st.markdown(f"""
                    <div style="background-color:#F0FDF4; padding:20px; border-radius:10px; border:1px solid #BBF7D0; text-align:center; margin-bottom:20px;">
                        <h3 style="color:#166534; margin:0;">✅ 충전 완료</h3>
                        <p style="color:#15803D; margin-top:5px;">이제 바로 문제를 만드실 수 있습니다.</p>
                    </div>
                    <a href="{my_app_url}" target="_self" style="text-decoration:none;">
                        <button style="width:100%; background-color:#2563EB; color:white; padding:20px; border:none; border-radius:15px; font-size:1.2rem; font-weight:bold; cursor:pointer;">🏠 홈으로 돌아가기 (클릭)</button>
                    </a>
                """, unsafe_allow_html=True)
                st.stop()
            else:
                st.error(f"결제 실패: {result.get('message', '오류')}")
                st.stop()

    col_t1, col_t2 = st.columns([6, 4])
    with col_t2:
        c1, c2, c3 = st.columns([1.5, 1.5, 1])
        with c1: st.markdown(f"""<a href="{CS_LINK}" target="_blank" class="cs-btn"><button>💬 문의하기</button></a>""", unsafe_allow_html=True)
        with c2: st.markdown(f'<div style="text-align:right; padding-top:8px;">👤 <b>{name}</b> | 🎫 <b>{curr_credits}</b></div>', unsafe_allow_html=True)
        with c3: authenticator.logout('로그아웃', 'main')

    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        try: 
            st.image("logo.png", width=400) 
        except: 
            st.markdown("<h1 style='text-align:center; font-size: 3.5rem; color: #2563EB;'>🧞‍♂️ 지니매쓰</h1>", unsafe_allow_html=True)
    st.write("")

    tab_make, tab_store, tab_history = st.tabs(["📄 학습지 만들기", "🏪 충전소", "📂 내 보관함"])
    
    if st.session_state["alert_msg"]:
        st.error(st.session_state["alert_msg"])

    with tab_make:
        df = load_curriculum_optimized()
        with st.container():
            st.markdown("""<div class="control-card"><div class="card-header">🔍 학습 내용 선택</div>""", unsafe_allow_html=True)
            all_options = df['search_label'].unique()
            selected_full_label = st.selectbox("원하는 학년이나 단원을 검색하세요", all_options, label_visibility="collapsed")
            try:
                part1, part2 = selected_full_label.split(" - ")
                p_school = part1.split(" ")[0]; p_grade = part1.split(" ")[1].replace("학년", ""); p_topic = part2
            except: p_school, p_grade, p_topic = "초등", "3", "덧셈"
            st.markdown("</div>", unsafe_allow_html=True)

        with st.container():
            st.markdown("""<div class="control-card" style="background-color:#F0F9FF; border:1px solid #BAE6FD;">
            <div class="card-header">🌱 매일 무료 학습 (1일 1회)</div>""", unsafe_allow_html=True)
            col_d1, col_d2 = st.columns([3, 1])
            with col_d1:
                st.write(f"**[{selected_full_label}]** 내용으로 **난이도 '하' 4문제**를 무료로 만들어 드립니다!")
                st.caption("※ 무료 버전은 개인 학습용입니다. (배포 금지)")
            with col_d2:
                is_used_today = check_daily_free_used(username)
                if "last_generated_free" in st.session_state:
                    st.success("✅ 생성 완료!")
                    # 메인 탭에서는 버튼 크게 (CSS .big-download-btn)
                    st.markdown('<div class="big-download-btn">', unsafe_allow_html=True)
                    st.download_button("📥 다운로드 (무료)", data=st.session_state["last_generated_free"]["data"], file_name=st.session_state["last_generated_free"]["name"], mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key="dl_free_imm")
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                    if st.button("닫기 (새로고침)"): 
                        del st.session_state["last_generated_free"]
                        st.session_state["alert_msg"] = None 
                        st.rerun()
                elif is_used_today:
                    st.button("✅ 오늘 완료", disabled=True, key="daily_done")
                else:
                    if st.button("🎁 무료 받기", key="daily_btn", type="primary"):
                        st.session_state["alert_msg"] = None 
                        with st.spinner(f"🎁 {p_topic} 무료 생성 중..."):
                            try:
                                docx_obj = logic.generate_math_docx(p_school, p_grade, p_topic, "하", 4, is_commercial=False)
                                docx_bytes = docx_obj.getvalue()
                                file_name = f"지니매쓰_무료_{p_school}{p_grade}_{p_topic}.docx"
                                
                                file_id = upload_to_drive(io.BytesIO(docx_bytes), file_name)
                                log_activity(username, "무료생성", selected_full_label, "DAILY_FREE", "4문제", "0장", file_id=file_id)
                                st.session_state["last_generated_free"] = {"data": docx_bytes, "name": file_name}
                                st.rerun()
                            except Exception as e: 
                                st.session_state["alert_msg"] = f"오류 발생: {e}"
                                st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)

        with st.container():
            st.markdown("""<div class="control-card"><div class="card-header">⚡ 맞춤형 생성 (상세 옵션)</div>""", unsafe_allow_html=True)
            st.write("📋 **라이선스 선택**")
            lc1, lc2 = st.columns(2)
            with lc1: st.info("👤 **개인용**\n- 편집 불가 (잠금)")
            with lc2: st.success("🏢 **상업용**\n- 8배 가격 / 편집 자유")
            l_type = st.radio("요금제", ["개인용", "상업용"], label_visibility="collapsed")
            is_commercial = True if "상업용" in l_type else False
            st.markdown("<hr>", unsafe_allow_html=True)
            c_opt1, c_opt2 = st.columns(2)
            with c_opt1: difficulty = st.selectbox("난이도", ["하", "중", "상", "최상"])
            with c_opt2: prob_count = st.selectbox("문제 수", [4, 8, 12, 20])
            st.markdown("</div>", unsafe_allow_html=True)

        base_cost = prob_count // 4
        final_cost = base_cost * 8 if is_commercial else base_cost
        
        b_col1, b_col2, b_col3 = st.columns([1, 2, 1])
        with b_col2:
            if curr_credits < final_cost:
                btn_text = f"🚫 이용권이 부족합니다 (필요: {final_cost}장)"
                btn_disabled = True
            else:
                l_label = "💎 상업용" if is_commercial else "👤 개인용"
                btn_text = f"🚀 {l_label} 생성하기 ({final_cost}장 차감)"
                btn_disabled = False
            
            st.markdown("""<style>div.stButton > button { width: 100%; padding: 16px 0; font-size: 1.1rem; border-radius: 12px; }</style>""", unsafe_allow_html=True)
            
            if "last_generated_paid" in st.session_state:
                st.success("✅ 생성 완료!")
                # 메인 탭에서는 버튼 크게
                st.markdown('<div class="big-download-btn">', unsafe_allow_html=True)
                st.download_button("📥 다운로드 (파일 저장)", data=st.session_state["last_generated_paid"]["data"], file_name=st.session_state["last_generated_paid"]["name"], mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key="dl_paid_imm")
                st.markdown('</div>', unsafe_allow_html=True)
                
                if st.button("계속 만들기"): 
                    del st.session_state["last_generated_paid"]
                    st.session_state["alert_msg"] = None
                    st.rerun()
            elif st.button(btn_text, disabled=btn_disabled, key="gen_btn"):
                st.session_state["alert_msg"] = None
                with st.spinner(f"💡 {selected_full_label} 문제 생성 중..."):
                    try:
                        docx_obj = logic.generate_math_docx(p_school, p_grade, p_topic, difficulty, prob_count, is_commercial=is_commercial)
                        docx_bytes = docx_obj.getvalue()
                        deduct_credit(username, final_cost)
                        
                        license_log = "COMMERCIAL" if is_commercial else "PERSONAL"
                        file_name = f"지니매쓰_{license_log}_{p_school}{p_grade}_{p_topic}.docx"
                        
                        file_id = upload_to_drive(io.BytesIO(docx_bytes), file_name)
                        log_activity(username, "문제생성", selected_full_label, p_topic, f"{prob_count}문제", f"-{final_cost}장 ({license_log})", file_id=file_id)
                        st.session_state["last_generated_paid"] = {"data": docx_bytes, "name": file_name}
                        st.rerun()
                    except Exception as e: 
                        st.session_state["alert_msg"] = f"오류: {e}"
                        st.rerun()

    with tab_store:
        try:
            st.markdown("<br><h3 style='text-align:center;'>🏪 필요한 만큼 충전해서 사용하세요</h3><br>", unsafe_allow_html=True)
            
            row1_col1, row1_col2 = st.columns(2)
            row2_col1, row2_col2 = st.columns(2)
            
            with row1_col1:
                st.markdown("""<div class="product-card"><div style="font-size:1.2rem; font-weight:bold;">🎫 알뜰형 (20장)</div><div style="font-size:1.5rem; font-weight:800; color:#2563EB;">1,000원</div><div style="color:#666; font-size:0.9rem; margin-top:5px;">장당 50원</div></div>""", unsafe_allow_html=True)
                order_id_1000 = f"{username}_{uuid.uuid4().hex}"
                components.html(f"""<style>button{{width:95%;padding:15px;background:#2563EB;color:white;border:none;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer;}}button:hover{{background:#1D4ED8;}}</style><button onclick="pay(1000, '{order_id_1000}', '지니매쓰 20장')">1,000원 결제</button><script src="https://js.tosspayments.com/v1/payment"></script><script>var clientKey='{TOSS_CLIENT_KEY}';var tossPayments=TossPayments(clientKey);function pay(amt, oid, name){{tossPayments.requestPayment('카드',{{amount:amt,orderId:oid,orderName:name,customerName:'{name}',successUrl:'{my_app_url}',failUrl:'{my_app_url}'}}).catch(e=>{{if(e.code!=='USER_CANCEL')alert('오류:'+e.message);}});}}</script>""", height=70)
            
            with row1_col2:
                st.markdown("""<div class="product-card"><div style="font-size:1.2rem; font-weight:bold;">👑 실속형 (110장)</div><div style="font-size:1.5rem; font-weight:800; color:#4F46E5;">5,000원</div><div style="color:#666; font-size:0.9rem; margin-top:5px;">장당 45원 (10% 보너스)</div></div>""", unsafe_allow_html=True)
                order_id_5000 = f"{username}_{uuid.uuid4().hex}"
                components.html(f"""<style>button{{width:95%;padding:15px;background:#4F46E5;color:white;border:none;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer;}}button:hover{{background:#4338CA;}}</style><button onclick="pay(5000, '{order_id_5000}', '지니매쓰 110장')">5,000원 결제</button><script src="https://js.tosspayments.com/v1/payment"></script><script>var clientKey='{TOSS_CLIENT_KEY}';var tossPayments=TossPayments(clientKey);function pay(amt, oid, name){{tossPayments.requestPayment('카드',{{amount:amt,orderId:oid,orderName:name,customerName:'{name}',successUrl:'{my_app_url}',failUrl:'{my_app_url}'}}).catch(e=>{{if(e.code!=='USER_CANCEL')alert('오류:'+e.message);}});}}</script>""", height=70)
            
            with row2_col1:
                st.markdown("""<div class="product-card"><div style="font-size:1.2rem; font-weight:bold;">🔥 인기형 (240장)</div><div style="font-size:1.5rem; font-weight:800; color:#E11D48;">10,000원</div><div style="color:#666; font-size:0.9rem; margin-top:5px;">장당 41원 (20% 보너스)</div></div>""", unsafe_allow_html=True)
                order_id_10000 = f"{username}_{uuid.uuid4().hex}"
                components.html(f"""<style>button{{width:95%;padding:15px;background:#E11D48;color:white;border:none;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer;}}button:hover{{background:#BE123C;}}</style><button onclick="pay(10000, '{order_id_10000}', '지니매쓰 240장')">10,000원 결제</button><script src="https://js.tosspayments.com/v1/payment"></script><script>var clientKey='{TOSS_CLIENT_KEY}';var tossPayments=TossPayments(clientKey);function pay(amt, oid, name){{tossPayments.requestPayment('카드',{{amount:amt,orderId:oid,orderName:name,customerName:'{name}',successUrl:'{my_app_url}',failUrl:'{my_app_url}'}}).catch(e=>{{if(e.code!=='USER_CANCEL')alert('오류:'+e.message);}});}}</script>""", height=70)

            with row2_col2:
                st.markdown("""<div class="product-card"><div style="font-size:1.2rem; font-weight:bold;">💎 전문가 (750장)</div><div style="font-size:1.5rem; font-weight:800; color:#059669;">30,000원</div><div style="color:#666; font-size:0.9rem; margin-top:5px;">장당 40원 (25% 보너스)</div></div>""", unsafe_allow_html=True)
                order_id_30000 = f"{username}_{uuid.uuid4().hex}"
                components.html(f"""<style>button{{width:95%;padding:15px;background:#059669;color:white;border:none;border-radius:10px;font-size:16px;font-weight:bold;cursor:pointer;}}button:hover{{background:#047857;}}</style><button onclick="pay(30000, '{order_id_30000}', '지니매쓰 750장')">30,000원 결제</button><script src="https://js.tosspayments.com/v1/payment"></script><script>var clientKey='{TOSS_CLIENT_KEY}';var tossPayments=TossPayments(clientKey);function pay(amt, oid, name){{tossPayments.requestPayment('카드',{{amount:amt,orderId:oid,orderName:name,customerName:'{name}',successUrl:'{my_app_url}',failUrl:'{my_app_url}'}}).catch(e=>{{if(e.code!=='USER_CANCEL')alert('오류:'+e.message);}});}}</script>""", height=70)

        except Exception as e: st.error(f"충전소 로딩 오류: {e}")

    # -------------------------------------------------------------------------
    # TAB 3: 내 보관함 (최종: 2열 구조 + 제목이 버튼)
    # -------------------------------------------------------------------------
    with tab_history:
        st.markdown("<br><h3 style='text-align:center;'>📂 내가 만든 학습지 보관함</h3><br>", unsafe_allow_html=True)
        try:
            history = get_user_history_processed(username)
            if not history:
                st.info("📭 보관함이 비어있습니다.")
            else:
                # 2열 헤더 (날짜 | 학습 내용 - 클릭해서 다운로드)
                st.markdown("""
                <div class='history-header-row'>
                    <div style='flex:1.5;'>날짜</div>
                    <div style='flex:8;'>학습 내용 (클릭하여 다운로드)</div>
                </div>
                """, unsafe_allow_html=True)
                
                for item in history:
                    # 행 컨테이너
                    with st.container():
                        c1, c2 = st.columns([1.5, 8])
                        
                        # 1열: 날짜 (텍스트)
                        c1.markdown(f"<div class='date-text'>{item['date']}</div>", unsafe_allow_html=True)
                        
                        # 2열: 학습 내용 자체가 '투명 버튼' (클릭 시 다운로드)
                        with c2:
                            if item['file_id']:
                                # 버튼이지만 텍스트처럼 보이게 CSS 적용됨
                                # 키(key)를 유니크하게 설정하여 충돌 방지
                                if st.download_button(
                                    label=item['desc'],
                                    data=download_from_drive(item['file_id']) or b'',
                                    file_name=f"지니매쓰_{item['date'].replace('.','').replace(':','')}.docx",
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    key=f"dl_link_{item['file_id']}_{uuid.uuid4()}"
                                ):
                                    pass # 다운로드는 자동 처리됨
                            else:
                                st.caption("파일 없음")
                        
                        # 구분선 (엑셀 라인 느낌)
                        st.markdown("<div style='border-bottom:1px solid #E5E7EB; margin-top:-5px;'></div>", unsafe_allow_html=True)

        except Exception as e:
            st.error(f"보관함 오류: {e}")

