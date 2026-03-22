"""
LangGraphを用いたマルチソースRAGエージェント
api_server.py から app としてインポートされ、質問応答の中核を担う

[使用データソース]
    ・e-Gov API: 法令の正確な最新原文
    ・Fuseki: 条文間の参照関係・章節構造（md_to_fuseki.py で構築）
    ・Neo4j: 条文の双方向参照・関連概念のグラフ検索（bridge.py で構築）
    ・FAISS(RAG): 逐条解説・実務資料からの意味検索（ingest.py で構築）

[処理フロー]
Router -> SPARQL(Fuseki) → Neo4j → e-Gov(法令原文) → RAG(FAISS) → Generate

[LangGraphの役割]
    各処理ステップをノードとして定義し、StateGraphで順序・分岐を制御する
    AgentState が各ノード間のデータの受け渡しを担う。
"""
import operator
import requests
import re
import json
import os
from typing import Annotated, List, TypedDict, Dict, Any, Union
from langgraph.graph import StateGraph, END
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_community.vectorstores import FAISS
from SPARQLWrapper import SPARQLWrapper, JSON
from neo4j import GraphDatabase

# 基本設定（.envから読み込む）
OLLAMA_URL       = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
FUSEKI_URL       = os.getenv("FUSEKI_URL", "http://fuseki:3030/ConstructionLaw/query")
LLM_MODEL        = os.getenv("LLM_MODEL", "qwen2.5:7b")
EMBEDDING_MODEL  = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
VECTORSTORE_PATH = os.getenv("VECTORSTORE_PATH", "/app/data/vectorstore")
NEO4J_URL        = os.getenv("NEO4J_URL", "bolt://neo4j:7687")
NEO4J_USER       = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD   = os.getenv("NEO4J_PASSWORD", "password")


class AgentState(TypedDict):
    """
        エージェント全体で共有される状態オブジェクト。
        各ノードはこの辞書の一部を更新して次のノードへ引き継ぐ。
        Attributes:
            messages:　ユーザーの質問と最終回答を格納するメッセージ履歴。Annotated[List, operator.add]
                    　 により各ノードの追記がリストに蓄積される。
            target_law: router_node が特定した対象法律名（例: "建設業法"）
            target_article: router_node が特定した条文番号（例: "14"）
            law_text     : fetch_law_node が e-Gov API から取得した条文原文
            rag_context  : fetch_rag_node が FAISS から取得した実務解説テキスト
            graph_data   : sparql_node が Fuseki から取得した関連章節情報
            neo4j_data   : neo4j_node が Neo4j から取得した参照関係・概念情報
            source_info  : 各ノードが参照したデータソースの記録（回答末尾に付与）
    """
    messages: Annotated[List[BaseMessage], operator.add]
    target_law: str
    target_article: str
    law_text: str
    rag_context: str
    graph_data: str   # Fusekiからの知見を格納
    neo4j_data: str   # Neo4jからの知見を格納
    source_info: str


def to_kanji(n_str) -> str:
    """
        (123)などの数字を日本の法令で使われる漢数字に変換する
    """
    kanji = "〇一二三四五六七八九"
    try:
        n = int(n_str.split('_')[0])
        if n < 10: res = kanji[n]
        elif n < 100: res = (kanji[n//10] if n//10 > 1 else "") + "十" + (kanji[n%10] if n%10 != 0 else "")
        elif n < 1000:
            h, t, u = n // 100, (n % 100) // 10, n % 10
            res = (kanji[h] if h > 1 else "") + "百"
            if t > 0: res += (kanji[t] if t > 1 else "") + "十"
            if u > 0: res += kanji[u]
        res = res.replace("十〇", "十").replace("百〇", "百")
        return res
    except: return n_str

# --- ノード定義 ---

def router_node(state: AgentState) -> Dict[str, Union[str, List[BaseMessage]]]:
    """
    ユーザーの自然言語入力を解析し、対象の「法律名」と「条文番号」を特定する
    「建設業法14条」のように直接言及されている場合は正規表現で即座に抽出
    言及がない場合はQwen2.5-7bにJSON形式で推測させる
    推測に失敗した場合は建設業法第1条にフォールバックする。
    """
    
    # 一番最後にaddされたものを取得する
    user_msg = state['messages'][-1].content
    
    # 直接「第〇条」と言及された場合の処理
    direct_match = re.search(r'(民法|建設業法|労働安全衛生規則)\s*(\d+)条', user_msg)
    if direct_match:
        return {"target_law": direct_match.group(1), "target_article": direct_match.group(2), "graph_data": ""}
    
    # Qwen2.5-7bを呼ぶ
    llm = ChatOllama(model=LLM_MODEL, base_url=OLLAMA_URL)

    prompt = f"""【土木専門エージェント：質問解析】
    ユーザーの質問を解析し、最も関連性の高い日本の法律と条文番号を推測してください。
    - 支払い、報酬、出来高、契約の解除 → 民法 (632〜642)
    - 建設業の許可区分（一般・特定）、許可の基準 → 建設業法 (3)
    - 建設業の許可申請、許可の要件 → 建設業法 (7〜8)
    - 請負契約の書面化、契約書の記載事項 → 建設業法 (18〜19)
    - 主任技術者、監理技術者の配置 → 建設業法 (26)
    - 工事現場の安全管理、足場、墜落防止 → 労働安全衛生規則 (518〜575)
    - 公共工事の品質確保、品確法 → 公共工事品質確保促進法 (1〜22)

    条文番号が不明確な場合は、その法律の第1条（目的）を返してください。
    JSON形式で出力してください: {{ "law": "法律名", "article": "数字のみ" }}
    質問: {user_msg}"""
    
    try:
        # モデルがpromptと照らし合わせて推論を行う
        res = llm.invoke(prompt).content
        data = json.loads(re.search(r'\{.*\}', res, re.DOTALL).group())
        return {"target_law": data.get("law"), "target_article": str(data.get("article")), "graph_data": ""}
    except:
        return {"target_law": "建設業法", "target_article": "1", "graph_data": ""}


def sparql_node(state: AgentState) -> Dict[str, str]:
    """
        Fuseki(SPARQL)を検索し、対象条文に関連する情報を取得する
        router_node で特定した条文番号をもとに refersTo リレーションを検索する。
        Fuseki が起動していない・データが未投入の場合はエラーを返して処理を継続する。
    """
    # router_nodeでの条文検索を受け取る
    art_num = state['target_article']
    print(f"知識グラフ(Fuseki)検索中: 第{art_num}条 に関連する項目...")
    
    # RDF形式のデータベースに足して問い合わせるクエリ
    query = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX contract: <http://example.org/construction/contract/>
    
    SELECT ?relatedLabel WHERE {{
      ?chapter contract:refersTo ?article .
      ?chapter rdfs:label ?relatedLabel .
      FILTER(contains(str(?article), "Article_{art_num}"))
    }} LIMIT 5
    """
    
    # SPAQLWrapper: PythonからFusekiサーバーへ「クエリを投げて結果をもらう」ためのメッセンジャー
    sparql = SPARQLWrapper(FUSEKI_URL)
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON) # Pythonで扱いやすいようにJSONで受け取る設定
    
    try:
        # HTTPリクエストを送り、返ってきたJSONをPythonの辞書型(Dict)に変換する
        results = sparql.query().convert()
        bindings = results["results"]["bindings"]
        if bindings:
            # 取得した関連情報を文字列にまとめる
            info = "\n".join([f"・関連章節: {b['relatedLabel']['value']}" for b in bindings])
            return {"graph_data": info, "source_info": "【Fuseki知識グラフ参照】"}
        return {"graph_data": "関連データなし", "source_info": ""}
    except Exception as e:
        print(f"SPARQLエラー: {e}")
        return {"graph_data": "検索エラー", "source_info": ""}

def neo4j_node(state: AgentState) -> Dict[str, str]:
    """
        Neo4j から対象条文の双方向参照と関連概念を取得する。
        　・REFERS_TO  : この条文が参照している条文 / この条文を参照している条文
        　・RELATES_TO : 関連概念（工期・損害・不可抗力など）
        Neo4j が起動していない場合はエラーを返して処理を継続する。
    """
    art_num = state["target_article"]
    print(f"🔗 Neo4j検索中: Article_{art_num} の関係を取得...")

    query = """
    MATCH (a {id: $node_id})
    OPTIONAL MATCH (a)-[:REFERS_TO]->(out)
    OPTIONAL MATCH (in)-[:REFERS_TO]->(a)
    OPTIONAL MATCH (a)-[:RELATES_TO]->(c:Concept)
    RETURN
      collect(DISTINCT out.label) AS refers_to,
      collect(DISTINCT in.label)  AS referred_from,
      collect(DISTINCT c.name)    AS concepts
    """
    try:
        driver = GraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as session:
            result = session.run(query, node_id=f"Article_{art_num}")
            record = result.single()

        driver.close()

        if not record:
            return {"neo4j_data": "Neo4j: 該当ノードなし", "source_info": state["source_info"]}

        refers_to     = [l for l in record["refers_to"]     if l]
        referred_from = [l for l in record["referred_from"] if l]
        concepts      = [c for c in record["concepts"]      if c]

        lines = []
        if refers_to:
            lines.append(f"・この条文が参照: {', '.join(refers_to)}")
        if referred_from:
            lines.append(f"・この条文を参照している: {', '.join(referred_from)}")
        if concepts:
            lines.append(f"・関連概念: {', '.join(concepts)}")

        info = "\n".join(lines) if lines else "関連データなし"
        return {
            "neo4j_data": info,
            "source_info": state["source_info"] + "\n【Neo4j グラフ参照】",
        }
    except Exception as e:
        print(f"Neo4jエラー: {e}")
        return {"neo4j_data": "Neo4j接続エラー", "source_info": state["source_info"]}


def fetch_law_node(state: AgentState) -> Dict[str, str]:
    """
        e-Gov API から対象法令の条文原文を取得する。

        条文番号はアラビア数字（14）から漢数字（十四）に変換してXML内を検索する。
        XMLタグを除去したプレーンテキストを最大2000文字で返す。
        対応していない法令名・API通信エラーの場合はその旨を返して処理を継続する。
    """
    law_name, art_num = state["target_law"], state["target_article"]
    print(f"🌐 e-Gov API検索: {law_name} 第{art_num}条")
    
    LAW_IDS = {
        "建設業法": "324AC0000000100", "民法": "129AC0000000089",
        "労働安全衛生法": "347AC0000000057", "労働安全衛生規則": "347M50000100032"
    }
    law_id = LAW_IDS.get(law_name)
    if not law_id: return {"law_text": "対象外の法律です。", "source_info": state["source_info"] + "【API参照】未対応"}

    try:
        res = requests.get(f"https://elaws.e-gov.go.jp/api/1/lawdata/{law_id}", timeout=10)
        kanji_num = to_kanji(art_num)
        pattern = rf"<ArticleTitle>第{kanji_num}条</ArticleTitle>(.*?)(?=<ArticleTitle>|<SuppleProvision>|$)"
        match = re.search(pattern, res.text, re.DOTALL)
        
        if match:
            text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
            return {"law_text": text[:2000], "source_info": state["source_info"] + f"\n【e-Gov API参照】{law_name} 第{art_num}条"}
        return {"law_text": "条文テキストが見つかりませんでした。", "source_info": state["source_info"] + f"\n【API検索失敗】"}
    except:
        return {"law_text": "API通信エラー", "source_info": state["source_info"] + "\n【API通信失敗】"}

def fetch_rag_node(state: AgentState) -> Dict[str, str]:
    """
        FAISS ベクトルDBから質問に意味的に近い実務解説・資料を取得する。
        ingest.py で構築した FAISS インデックスを読み込み、上位2件のチャンクを返す。
        FAISS インデックスが存在しない場合は空文字列を返して処理を継続する。
    """
    embeddings = OllamaEmbeddings(
        model=EMBEDDING_MODEL,
        base_url=OLLAMA_URL
    )
    try:
        vectorstore = FAISS.load_local(VECTORSTORE_PATH, embeddings, allow_dangerous_deserialization=True)
        docs = vectorstore.similarity_search(state["messages"][-1].content, k=2)
        rag_info = "\n".join([f"・{d.metadata.get('source', '不明')}" for d in docs])
        context = "\n\n".join([d.page_content for d in docs])
        return {"rag_context": context, "source_info": state["source_info"] + f"\n【RAG参照資料】\n{rag_info}"}
    except:
        return {"rag_context": "", "source_info": state["source_info"] + "\n【RAG参照】なし"}

def generate_final_node(state: AgentState) -> Dict[str, List[BaseMessage]]:
    """         
        4つのデータソースをまとめてプロンプトを構築し、最終回答を生成する。                                                                                                                
        [根拠資料1]法令原文（e-Gov）                                                            
        [根拠資料2]実務解説（FAISS）                                                            
        [根拠資料3]関連章節（Fuseki）                                                           
        [根拠資料4]参照関係・概念（Neo4j）                                                      
        回答末尾に source_info（参照ソース一覧）を付与する。                                      
        文字コードエラー対策として全テキストを UTF-8 でクリーニングしてからプロンプトに渡す。
    """   
    llm = ChatOllama(model=LLM_MODEL, base_url=OLLAMA_URL)
    
    # 文字コードクリーニング（先ほどのエラー対策）
    def clean_text(text):
        return text.encode('utf-8', 'ignore').decode('utf-8')

    law_text   = clean_text(state.get('law_text', ''))
    graph_data = clean_text(state.get('graph_data', ''))
    neo4j_data = clean_text(state.get('neo4j_data', ''))
    rag_context = clean_text(state.get('rag_context', ''))

    prompt = f"""あなたは建設業・公共工事に精通した法務の専門家です。
以下の【根拠資料】をもとに、ユーザーの質問に対して丁寧かつ正確に回答してください。

【回答ルール】
1. 質問に対して直接答えること。「正しい/間違い」の判定形式にしないこと。
2. 根拠となる条文・資料の内容を引用しながら説明すること。
3. 根拠資料に記載がない事項は「資料には明記がありませんが」と断った上で一般的な解説を補足してよい。
4. 回答は日本語で、実務担当者がすぐ使えるよう具体的に書くこと。

---
【根拠資料1：法令原文】: {law_text}
【根拠資料2：逐条解説/実務資料】: {rag_context}
【根拠資料3：Fuseki 関連章節】: {graph_data}
【根拠資料4：Neo4j 参照関係・概念】: {neo4j_data}
---
質問: {state['messages'][-1].content}
"""
    response = llm.invoke([HumanMessage(content=clean_text(prompt))])
    
    final_content = response.content + f"\n\n---\n### 参照ソース\n{state['source_info']}"
    return {"messages": [HumanMessage(content=final_content)]}


# --- LangGraph の構築 ---
# ノード関数を StateGraph に登録し、実行順序（エッジ）を定義する。
# compile() で実行可能な app になり、api_server.py から import して使われる。
workflow = StateGraph(AgentState)

workflow.add_node("router",    router_node)
workflow.add_node("sparql",    sparql_node)
workflow.add_node("neo4j",     neo4j_node)
workflow.add_node("fetch_law", fetch_law_node)
workflow.add_node("fetch_rag", fetch_rag_node)
workflow.add_node("generate",  generate_final_node)

workflow.set_entry_point("router")

# フロー: Router -> SPARQL(Fuseki) -> Neo4j -> Law(e-Gov) -> RAG -> Generate
workflow.add_edge("router",    "sparql")
workflow.add_edge("sparql",    "neo4j")
workflow.add_edge("neo4j",     "fetch_law")
workflow.add_edge("fetch_law", "fetch_rag")
workflow.add_edge("fetch_rag", "generate")
workflow.add_edge("generate",  END)

app = workflow.compile()

if __name__ == "__main__":
    while True:
        try:
            user_input = input("\n質問 > ")
            if not user_input: continue
            # ストリーム表示をシンプルにするため、最終回答のみ表示するロジックに調整
            for output in app.stream({"messages": [HumanMessage(content=user_input)]}):
                for key, value in output.items():
                    if key == "generate":
                        print(f"\n{value['messages'][-1].content}\n")
        except KeyboardInterrupt: break