"use client";

import { useState, useRef, useEffect } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

type Step = { label: string; icon: string };
type Message = { role: "user" | "assistant"; content: string };

const STEP_LABELS: Record<string, { label: string; icon: string }> = {
  router:    { label: "質問を分析中",           icon: "🔍" },
  sparql:    { label: "知識グラフを検索中",      icon: "🕸️" },
  neo4j:     { label: "グラフDBを検索中",        icon: "🔗" },
  fetch_law: { label: "法令原文を取得中",        icon: "📜" },
  fetch_rag: { label: "実務資料を検索中",        icon: "📚" },
  generate:  { label: "回答を生成中",           icon: "✨" },
};

const SUGGESTIONS = [
  "第14条において受注者の義務を教えて",
  "工期の変更はどのような場合に認められるか",
  "現場代理人の常駐義務について教えて",
  "第20条における損害賠償の規定を説明して",
];

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, steps]);

  const sendMessage = async (text?: string) => {
    const question = (text ?? input).trim();
    if (!question || loading) return;

    setInput("");
    setLoading(true);
    setSteps([]);
    setMessages((prev) => [...prev, { role: "user", content: question }]);

    try {
      const res = await fetch(`${API_URL}/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: question }),
      });

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6);
          if (data === "[DONE]") break;

          try {
            const parsed = JSON.parse(data);
            if (parsed.type === "step") {
              const info = STEP_LABELS[parsed.step] ?? { label: parsed.step, icon: "⚙️" };
              setSteps((prev) => [...prev, info]);
            } else if (parsed.type === "answer") {
              setMessages((prev) => [...prev, { role: "assistant", content: parsed.content }]);
              setSteps([]);
            }
          } catch {}
        }
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "⚠️ APIサーバーに接続できません。\ndocker compose up を確認してください。" },
      ]);
      setSteps([]);
    } finally {
      setLoading(false);
      textareaRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const isEmpty = messages.length === 0 && !loading;

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-white">

      {/* ヘッダー */}
      <header className="flex items-center gap-3 px-6 py-4 border-b border-slate-800 bg-slate-900/80 backdrop-blur">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-sm font-bold shadow-lg">
          建
        </div>
        <div>
          <h1 className="text-sm font-semibold text-white tracking-wide">
            建設法務 AI エージェント
          </h1>
          <p className="text-xs text-slate-400">
            公共工事標準請負契約約款 · 建設業法 · 民法
          </p>
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-xs text-slate-400">稼働中</span>
        </div>
      </header>

      {/* メッセージエリア */}
      <main className="flex-1 overflow-y-auto px-4 py-6">
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center h-full gap-8 pb-10">
            <div className="text-center space-y-2">
              <div className="text-4xl mb-4">⚖️</div>
              <h2 className="text-xl font-semibold text-slate-200">
                建設法務について質問してください
              </h2>
              <p className="text-sm text-slate-500">
                法令原文・逐条解説・知識グラフを統合して回答します
              </p>
            </div>

            {/* サジェスト */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-2xl">
              {SUGGESTIONS.map((s, i) => (
                <button
                  key={i}
                  onClick={() => sendMessage(s)}
                  className="text-left px-4 py-3 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 hover:border-slate-500 text-sm text-slate-300 transition-all duration-150 group"
                >
                  <span className="text-slate-500 group-hover:text-blue-400 mr-2 transition-colors">→</span>
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto space-y-6">
            {messages.map((msg, i) => (
              <div key={i} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                {msg.role === "assistant" && (
                  <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5 shadow">
                    AI
                  </div>
                )}
                <div
                  className={`max-w-xl px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                    msg.role === "user"
                      ? "bg-blue-600 text-white rounded-tr-sm shadow-lg"
                      : "bg-slate-800 text-slate-200 border border-slate-700 rounded-tl-sm shadow"
                  }`}
                >
                  {msg.content}
                </div>
                {msg.role === "user" && (
                  <div className="w-7 h-7 rounded-full bg-slate-600 flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5">
                    You
                  </div>
                )}
              </div>
            ))}

            {/* ステップ表示 */}
            {loading && (
              <div className="flex gap-3 justify-start">
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5 shadow">
                  AI
                </div>
                <div className="bg-slate-800 border border-slate-700 rounded-2xl rounded-tl-sm px-4 py-3 text-sm space-y-2 min-w-56 shadow">
                  {steps.map((s, i) => (
                    <div key={i} className="flex items-center gap-2 text-slate-300">
                      <span>{s.icon}</span>
                      <span>{s.label}</span>
                      <span className="ml-auto text-emerald-400 text-xs">完了</span>
                    </div>
                  ))}
                  <div className="flex items-center gap-2 text-slate-500 pt-1 border-t border-slate-700">
                    <span className="flex gap-1">
                      {[0, 1, 2].map((j) => (
                        <span
                          key={j}
                          className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce"
                          style={{ animationDelay: `${j * 150}ms` }}
                        />
                      ))}
                    </span>
                    <span className="text-xs">
                      {steps.length > 0
                        ? STEP_LABELS[Object.keys(STEP_LABELS)[steps.length]]?.label ?? "処理中..."
                        : "処理を開始しています..."}
                    </span>
                  </div>
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        )}
      </main>

      {/* 入力エリア */}
      <footer className="px-4 py-4 border-t border-slate-800 bg-slate-900/80 backdrop-blur">
        <div className="flex gap-2 max-w-3xl mx-auto">
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="建設法務について質問する...　(Enter で送信 / Shift+Enter で改行)"
              disabled={loading}
              rows={2}
              className="w-full resize-none rounded-xl bg-slate-800 border border-slate-700 focus:border-blue-500 px-4 py-3 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-40 transition-colors"
            />
          </div>
          <button
            onClick={() => sendMessage()}
            disabled={loading || !input.trim()}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-sm font-medium disabled:opacity-30 disabled:cursor-not-allowed transition-all duration-150 shadow-lg hover:shadow-blue-500/25 self-end mb-0"
          >
            送信
          </button>
        </div>
        <p className="text-center text-xs text-slate-600 mt-2">
          Fuseki · Neo4j · FAISS · e-Gov API · Ollama (qwen2.5:7b)
        </p>
      </footer>
    </div>
  );
}
