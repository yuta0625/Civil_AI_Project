"""
CLI_test/ask.py
prompt/question.txt の質問を API に投げて output/ に保存する

使い方:
  python CLI_test/ask.py
"""

import requests
import json
from datetime import datetime
from pathlib import Path

API_URL = "http://localhost:8080/ask"

PROMPT_FILE = Path(__file__).parent / "prompt" / "question.txt"
OUTPUT_DIR  = Path(__file__).parent / "output"

def main():
    # 質問を読み込む
    if not PROMPT_FILE.exists():
        print(f"エラー: {PROMPT_FILE} が見つかりません")
        return

    question = PROMPT_FILE.read_text(encoding="utf-8").strip()
    if not question:
        print("エラー: question.txt が空です")
        return

    print(f"質問: {question}")
    print("回答を生成中...")

    # APIに投げる
    try:
        response = requests.post(
            API_URL,
            headers={"Content-Type": "application/json"},
            json={"text": question},
            timeout=180,
        )
        response.raise_for_status()
        answer = response.json()["answer"]
    except requests.exceptions.ConnectionError:
        print("エラー: APIサーバーに接続できません。docker compose up を確認してください。")
        return
    except Exception as e:
        print(f"エラー: {e}")
        return

    # 出力内容を組み立てる
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_text = f"""【質問】
{question}

【回答】
{answer}

【実行日時】
{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

    # output/ に保存
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_file = OUTPUT_DIR / f"answer_{timestamp}.txt"
    output_file.write_text(output_text, encoding="utf-8")

    # ターミナルにも表示
    print("\n" + "="*50)
    print(answer)
    print("="*50)
    print(f"\n保存先: {output_file}")

if __name__ == "__main__":
    main()
