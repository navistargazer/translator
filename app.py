import sys
import time
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
from google import genai
from google.genai import types
from api_key import GEMINI_API_KEY

from flask import Flask, render_template, Response
import json

app = Flask(__name__)
client = genai.Client(api_key=GEMINI_API_KEY)

# ==========================================
# 1. State 정의 (심플해진 결재 서류철)
# ==========================================
class TranslationState(TypedDict):
    full_original_text: str         # 회차 전체 원문
    translated_result: str          # 최종 번역 결과물
    episode_summaries: List[str]    # 이전 회차들의 요약 리스트
    qa_feedback: str                # 검수 피드백
    retry_count: int
    is_finished: bool

# ==========================================
# 2. Node 구현 (회차 단위 처리)
# ==========================================

def node_parser(state: TranslationState):
    print("\n[🔍 시스템] 회차 전체 원문을 수집합니다...")
    # 실제 구현 시 웹 스크래핑 로직이 들어갈 자리입니다.
    sample_chapter = """
    クノンは笑った。
    「本当に、見えないの？」
    彼は盲目の魔術師だ。
    """
    return {
        "full_original_text": sample_chapter.strip(),
        "qa_feedback": "PASS",
        "retry_count": 0
    }

def node_translator(state: TranslationState):
    """회차 전체를 한 번에 번역"""
    print("\n[🎨 시스템] 전체 번역을 시작합니다 (스트리밍)...")
    
    past_history = "\n".join(state.get("episode_summaries", []))
    original = state["full_original_text"]
    
    # 지휘관님의 요청: 번역문 아래 원문 한 줄씩 배치
    system_instruction = f"""
    당신은 'syosetu.colomo.dev' 스타일의 전문 대역 번역기입니다.
    아래의 [이전 줄거리 요약]을 참고하여 [원문]을 한국어로 번역하세요.

    [이전 줄거리 요약]
    {past_history}

    [반드시 준수할 출력 알고리즘]
    1. 원문의 첫 번째 문장을 읽는다.
    2. 해당 문장의 한국어 번역문을 출력한다.
    3. 바로 다음 줄(Line break)에 해당 일본어 원문을 출력한다.
    4. 한 줄을 비운다(Double line break).
    5. 다음 문장으로 넘어가 1~4 과정을 반복한다.

    [출력 예시 - 반드시 이 패턴만 따를 것]
    그는 조용히 눈을 떴다.
    彼は静かに目を開けた。

    "여기는 어디지?"라고 그는 중얼거렸다.
    「ここはどこだ？」と彼は呟いた.

    [주의사항]
    - 절대로 번역문을 모두 출력한 뒤에 원문을 몰아서 출력하지 마십시오.
    - 원문의 문장 부호(「」, 。 등)를 기준으로 한 문장씩 끊어서 처리하십시오.
    """
    
    prompt = f"다음 소설 내용을 번역하세요:\n\n{original}"
    if state["qa_feedback"] != "PASS":
        prompt = f"반려 사유를 반영해 다시 번역하세요: {state['qa_feedback']}\n\n원문:\n{original}"

    print("\n" + "="*30)
    full_response = ""
    chunks = client.models.generate_content_stream(
        model="gemini-3-flash-preview", 
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system_instruction)
    )
    
    for chunk in chunks:
        part = chunk.text
        full_response += part
        sys.stdout.write(part) # 실시간 출력
        sys.stdout.flush()
    
    print("\n" + "="*30)
    return {"translated_result": full_response.strip()}

def node_qa(state: TranslationState):
    """전체 결과물 검수"""
    print("\n[🧐 시스템] 품질 검수 중...")
    # 무료 티어 보호를 위한 짧은 휴식
    time.sleep(2) 
    
    # 실제로는 여기서 제미나이를 호출하여 검수하지만, 
    # 통과되었다고 가정하고 바로 요약 단계로 넘깁니다.
    return {"qa_feedback": "PASS"}

def node_summarizer(state: TranslationState):
    """다음 화를 위한 요약 생성"""
    print("\n[📊 시스템] 이번 회차 요약 중...")
    
    # 요약 로직 수행
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=f"다음 번역본의 핵심 내용을 2줄로 요약해:\n\n{state['translated_result']}"
    )
    
    return {
        "episode_summaries": state.get("episode_summaries", []) + [response.text.strip()],
        "is_finished": True
    }

# ==========================================
# 3. Graph 조립 (직선형에 가까운 단순 구조)
# ==========================================

workflow = StateGraph(TranslationState)

workflow.add_node("Parser", node_parser)
workflow.add_node("Translator", node_translator)
workflow.add_node("QA", node_qa)
workflow.add_node("Summarizer", node_summarizer)

workflow.set_entry_point("Parser")
workflow.add_edge("Parser", "Translator")
workflow.add_edge("Translator", "QA")

# QA 결과에 따른 분기
def router(state):
    if state["qa_feedback"] == "PASS": return "Summarizer"
    return "Translator"

workflow.add_conditional_edges("QA", router)
workflow.add_edge("Summarizer", END)

graph = workflow.compile()

@app.route('/')
def index():
    # 번역 페이지 메인 HTML 출력
    return render_template('index.html')

@app.route('/translate')
def translate():
    def generate():
        # 1. 초기 상태 설정
        state = {
            "full_original_text": "クノンは笑った。\n「本当に、見えないの？」\n彼は盲目の魔術師だ。",
            "episode_summaries": ["쿠논은 마법사의 길을 걷기 시작했다."],
            "qa_feedback": "PASS"
        }

        # 2. LangGraph 실행 (stream 모드 활용)
        # 굳이 전체 루프를 돌리지 않고, 번역 노드만 예시로 스트리밍합니다.
        system_instruction = "당신은 전문 번역가입니다. 번역문 아래에 원문을 배치하세요."
        
        chunks = client.models.generate_content_stream(
            model="gemini-3-flash-preview",
            contents=state["full_original_text"],
            config=types.GenerateContentConfig(system_instruction=system_instruction)
        )

        for chunk in chunks:
            if chunk.text:
                # SSE 형식으로 데이터 전송: "data: <내용>\n\n"
                yield f"data: {json.dumps({'text': chunk.text}, ensure_ascii=False)}\n\n"
        
        yield "data: {\"event\": \"done\"}\n\n"

    return Response(generate(), mimetype='text/event-stream')

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5001)