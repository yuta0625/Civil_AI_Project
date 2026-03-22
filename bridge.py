"""
Fuseki（RDF）のデータをNeo4jに変換・投入する
一回限りの初期化スクリプト。

[なぜFusekiとNeo4jの両方が必要なのか]
    ・Fuseki(RDF): 条文間の参照関係を厳密なオントロジーとして表現・検索するのに向く
    ・Neo4j(グラフDB): ノード間の関係を高速にたどるに向いている
    -> main_agent.py の sparql_nodeとFuseki, neo4j_nodeはNeo4jをそれぞれ使い分ける

[実行タイミング]
データ初期化時に一度だけ実行する(md_to_fuseki.py -> Fuseki投入 -> bridge.pyの順)
MERGE を使っているため、重複実行しても二重登録にはならない。

[前提条件]
    1. docker compose up fuseki neo4j -dが立っていること
    2. FusekiにConstructionLaw データセットが投入済みであること
    (md_to_fuseki.pyの出力 .ttlをアップロード済みである)

[パイプライン上の位置付け]
    md_to_fuseki.py -> .ttl -> Fuseki -> bridge.py -> Neo4j

[初期化フェーズ]（一回限り、Mac本体から実行）                                               
    bridge.py   → localhost:3030（Fuseki）からデータ取得                                            
                → localhost:7687（Neo4j）に投入                                                      
                                                                                                
[推論フェーズ]（リクエストのたびに、Docker内から実行）                                      
    main_agent.py   → neo4j:7687（Neo4j）にクエリ
                    → fuseki:3030（Fuseki）にクエリ
"""
import os
from dotenv import load_dotenv
from SPARQLWrapper import SPARQLWrapper, JSON
from neo4j import GraphDatabase

# .env を読み込む（プロジェクトルートの .env）
load_dotenv()

# --- 接続設定 ---
# bridge.py はホスト（Mac）から実行するため localhost を使う
# bridge.pyはデータ仕込むためのツールで、Dockerネットワークの外から一度だけ使う
FUSEKI_QUERY_URL = "http://localhost:3030/ConstructionLaw/query"
NEO4J_URL        = "bolt://localhost:7687"
NEO4J_USER       = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD   = os.getenv("NEO4J_PASSWORD", "password")

LAW_PREFIX = "http://example.org/construction/contract/"


#  SPARQL ヘルパー 
def run_sparql(query: str) -> list[dict]:
    """
        FusekiにSPARQLクエリを投げ、結果をバインディングのリストで返す共通ヘルパー
    """
    sparql = SPARQLWrapper(FUSEKI_QUERY_URL)
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()
    return results["results"]["bindings"]


# Fuseki からデータ取得 
def fetch_nodes() -> list[dict]:
    """
        Fuseki から全 TreatiseElement ノード（Article・Chapter）を取得する。                      
        各ノードの id・label・summary・sourceFile をプロパティとして返す。
    """
    query = f"""
    PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX law:  <{LAW_PREFIX}>

    SELECT ?id ?label ?summary ?sourceFile WHERE {{
      ?s rdf:type law:TreatiseElement .
      ?s rdfs:label ?label .
      BIND(strafter(str(?s), "{LAW_PREFIX}") AS ?id)
      OPTIONAL {{ ?s law:summary    ?summary    }}
      OPTIONAL {{ ?s law:sourceFile ?sourceFile }}
    }}
    """
    rows = run_sparql(query)
    nodes = []
    for r in rows:
        nodes.append({
            "id":         r["id"]["value"],
            "label":      r["label"]["value"],
            "summary":    r.get("summary",    {}).get("value", ""),
            "sourceFile": r.get("sourceFile", {}).get("value", ""),
        })
    print(f"  取得ノード数: {len(nodes)}")
    return nodes


def fetch_refers_to() -> list[dict]:
    """refersTo（条文間の参照関係）を取得"""
    query = f"""
    PREFIX law: <{LAW_PREFIX}>

    SELECT ?fromId ?toId WHERE {{
      ?from law:refersTo ?to .
      BIND(strafter(str(?from), "{LAW_PREFIX}") AS ?fromId)
      BIND(strafter(str(?to),   "{LAW_PREFIX}") AS ?toId)
    }}
    """
    rows = run_sparql(query)
    rels = [{"from": r["fromId"]["value"], "to": r["toId"]["value"]} for r in rows]
    print(f"  取得 REFERS_TO 数: {len(rels)}")
    return rels


def fetch_relates_to() -> list[dict]:
    """
        Fuseki から条文と概念（工期・損害・不可抗力など）のリレーション（relatesTo）を取得する。
        md_to_fuseki.py のキーワード辞書によって付与されたエッジが対象。
    """
    query = f"""
    PREFIX law: <{LAW_PREFIX}>

    SELECT ?fromId ?concept WHERE {{
      ?from law:relatesTo ?c .
      BIND(strafter(str(?from), "{LAW_PREFIX}") AS ?fromId)
      BIND(strafter(str(?c),    "{LAW_PREFIX}") AS ?concept)
    }}
    """
    rows = run_sparql(query)
    rels = [{"from": r["fromId"]["value"], "concept": r["concept"]["value"]} for r in rows]
    print(f"  取得 RELATES_TO 数: {len(rels)}")
    return rels


# Neo4j へ投入 

def insert_nodes(tx, nodes: list[dict]):
    """
        Article / Chapter ノードを Neo4j に投入する。
        MERGE を使うため重複実行しても二重登録にならない。   
    """
    for node in nodes:
        node_type = "Chapter" if node["id"].startswith("Chapter") else "Article"
        tx.run(
            f"""
            MERGE (n:{node_type} {{id: $id}})
            SET n.label      = $label,
                n.summary    = $summary,
                n.sourceFile = $sourceFile
            """,
            id=node["id"],
            label=node["label"],
            summary=node["summary"],
            sourceFile=node["sourceFile"],
        )


def insert_refers_to(tx, rels: list[dict]):
    """条文間の REFERS_TO リレーションを Neo4j に投入する。"""
    for rel in rels:
        tx.run(
            """
            MATCH (a {id: $from_id})
            MATCH (b {id: $to_id})
            MERGE (a)-[:REFERS_TO]->(b)
            """,
            from_id=rel["from"],
            to_id=rel["to"],
        )


def insert_relates_to(tx, rels: list[dict]):
    """
        概念ノード（Concept）と RELATES_TO リレーションを Neo4j に投入する。
        Concept ノードが存在しない場合は MERGE で自動生成する。
    """
    for rel in rels:
        tx.run(
            """
            MERGE (c:Concept {name: $concept})
            WITH c
            MATCH (a {id: $from_id})
            MERGE (a)-[:RELATES_TO]->(c)
            """,
            concept=rel["concept"],
            from_id=rel["from"],
        )


def main():
    # Fuseki からデータ取得
    nodes = fetch_nodes()
    refers = fetch_refers_to()
    relates = fetch_relates_to()

    # Neo4j に接続して投入
    driver = GraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASSWORD))

    with driver.session() as session:
        session.execute_write(insert_nodes, nodes)
        session.execute_write(insert_refers_to, refers)
        session.execute_write(insert_relates_to, relates)

    driver.close()


if __name__ == "__main__":
    main()
