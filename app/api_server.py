import os
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn
from main_agent import app as langgraph_app
from langchain_core.messages import HumanMessage

api = FastAPI(title="Civil AI Agent API")

# CORS設定（Next.jsフロントからのアクセスを許可）
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class Question(BaseModel):
    text: str

@api.get("/health")
def health():
    """起動確認用エンドポイント"""
    return {"status": "ok"}

@api.post("/ask")
async def ask(item: Question):
    """質問を受け取り、LangGraphエージェントで回答を返す"""
    inputs = {"messages": [HumanMessage(content=item.text)]}
    result = langgraph_app.invoke(inputs)
    answer = result["messages"][-1].content
    return {"answer": answer}

@api.post("/ask/stream")
async def ask_stream(item: Question):
    """各ステップの進捗をServer-Sent Eventsで返す"""
    def generate():
        inputs = {"messages": [HumanMessage(content=item.text)]}
        for output in langgraph_app.stream(inputs):
            for key, value in output.items():
                if key == "generate":
                    answer = value["messages"][-1].content
                    yield f"data: {json.dumps({'type': 'answer', 'content': answer}, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'step', 'step': key}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

if __name__ == "__main__":
    port = int(os.getenv("API_PORT", 8080))
    uvicorn.run(api, host="0.0.0.0", port=port)
