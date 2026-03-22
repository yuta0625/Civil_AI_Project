"""
Markdown資料をRDF(turtle形式)に変換し、Fusekiへのアップロード用ファイルを生成するスクリプト
    ・ingest.pyがベクトル検索用のFAISSを作るのに対しこのスクリプトは「条件間の参照関係」や「
    キーワード概念との繋がり」をグラフ構造として表現するものである。

[output]
    ・construction_treatise.ttl(Turtle形式のRDFファイル)

[トリプルストアのApachFusekiへの投入方法]
    ・生成した.ttlファイルをFusekiのWeb UI(http://localhost:3030)から
    ・ConstructionLaw データセットに手動でアップロードする。                                                   
    ・アップロード後は bridge.py を実行して Neo4j にも同期できる
"""
import os
import re
import unicodedata
from rdflib import Graph, Literal, Namespace, RDF, RDFS

# --- 1. 設定 ---
INPUT_DIR = "./markdown_docs"  # 39個のファイルが格納されているディレクトリ
OUTPUT_FILE = "construction_treatise.ttl"
BASE_URI = "http://example.org/construction/contract/"
LAW = Namespace(BASE_URI)

def normalize_num(text):
    """全角数字を半角に変換する"""
    return unicodedata.normalize('NFKC', text)

def create_rdf_graph():
    """
        markdown_docs/ の全 .mdファイルを読み込み、RDFグラフを構築して.ttlファイルに出力する
        
        各ファイルに対して以下を行う：
            ・ファイル名から条文番号(Article_N)または章番号(Chapter_N)を特定しノード化
            ・本文中の条文参照(「第◯条」）を refersTo エッジとして登録)
            ・キーワード辞書と参照し、概念ノードへの relatesTo エッジを付与
            ・本文冒頭200文字を summary として保存（Fuseki上でのクイック確認用）
    """
    g = Graph()
    g.bind("law", LAW)

    if not os.path.exists(INPUT_DIR):
        print(f"Error: {INPUT_DIR} not found")
        return

    files = [f for f in os.listdir(INPUT_DIR) if f.endswith(".md")]
    
    for filename in files:
        filepath = os.path.join(INPUT_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # file名に「第14条」があれば Article_14, 「第3章」があれば Chapter_3
        main_match = re.search(r'第\s*([０-９0-9]+)\s*[条章]', filename)
        
        if main_match:
            raw_num = main_match.group(1)
            art_id = normalize_num(raw_num)
            is_chapter = "章" in filename
            
            suffix = f"Chapter_{art_id}" if is_chapter else f"Article_{art_id}"
            subject = LAW[suffix]
            label = f"第{art_id}{'章' if is_chapter else '条'}"
        else:
            # 条文番号がない資料はファイル名をIDにする
            safe_name = re.sub(r'[^\w]', '_', filename.replace(".md", ""))
            subject = LAW[safe_name]
            label = filename.replace(".md", "")

        # メタデータをトリプルとして追加
        g.add((subject, RDF.type, LAW.TreatiseElement))
        g.add((subject, RDFS.label, Literal(label)))
        g.add((subject, LAW.sourceFile, Literal(filename)))
        
        # 本文の冒頭200文字を要約として保存（Fusekiでのクイック確認用）
        summary = content.replace('\n', ' ')[:200] + "..."
        g.add((subject, LAW.summary, Literal(summary)))

        # 条文間・章間リレーションの動的抽出 
        all_refs = re.findall(r'第\s*([０-９0-9]+)\s*[条章]', content)
        for ref_num_raw in set(all_refs):
            ref_num = normalize_num(ref_num_raw)
            # 自分自身へのリンクは除外
            if ref_num == art_id if 'art_id' in locals() else False:
                continue
                
            # 文脈に応じて参照先を推測
            ref_target = LAW[f"Article_{ref_num}"]
            g.add((subject, LAW.refersTo, ref_target))

        # 逐条解説のコンテキスト抽出(タグ付け)
        context_map = {
            "工期": LAW.TimeExtension,
            "代金": LAW.PriceAdjustment,
            "損害": LAW.Damages,
            "中止": LAW.Suspension,
            "設計図書": LAW.DesignChange,
            "不可抗力": LAW.ForceMajeure,
            "通知": LAW.Procedure
        }
        for keyword, concept_uri in context_map.items():
            if keyword in content:
                g.add((subject, LAW.relatesTo, concept_uri))

    # 出力
    g.serialize(destination=OUTPUT_FILE, format="turtle")

if __name__ == "__main__":
    create_rdf_graph()