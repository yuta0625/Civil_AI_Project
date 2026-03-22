"""
RAG用ベクトルデータベース構築スクリプト

Markdown資料を「意味」で検索できるように、テキストをベクトル化して保存する。
エージェントが「似た意味の解説」を探し出すための検索エンジン（索引）を作成する。

- LangChain: ドキュメントの読み込み・分割の制御。
- Ollama (nomic-embed-text): テキストを多次元ベクトル（数値リスト）に変換する専用モデル。->.envから読み込む
- FAISS: Facebook製。高速なベクトル類似度検索を行うためのデータベース。

処理フロー
1. Load: Markdownファイルを UnstructuredLoader でテキストとして読み込み。
2. Split: 長い文章をチャンクに分割。
3. Embed: nomic-embed-text を用いて各チャンクをベクトル変換。
4. Store: FAISS インデックスとしてローカルディレクトリに保存。
"""

import os
from langchain_community.document_loaders import DirectoryLoader, UnstructuredMarkdownLoader
from langchain_text_splitters import CharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import FAISS

# パス設定（.envから読み込む）
DOCS_PATH = os.getenv("DOCS_PATH", "/app/data/markdown_docs")
VECTOR_DB_PATH = os.getenv("VECTORSTORE_PATH", "/app/data/vectorstore")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

def ingest_docs():
    """
        DirectoryLoader: 指定したフォルダ内のファイルをまとめて読み込むためのツール
        UnstructuredMarkdownLoader: Mrakdown特有の記号(#,*)を適切に処理し、人間が読むテキストとして抽出する
        text_spliter: LLMには一度に読み取ることができる限界(トークン制限)があるため、長い文を「チャンク」に分割
        OllamaEmbeddings: テキストをベクトルに変換する
    """
    
    # PATHから.mdを読み込む
    loader = DirectoryLoader(DOCS_PATH, glob="**/*.md", loader_cls=UnstructuredMarkdownLoader)
    documents = loader.load()

    print(f"total {len(documents)} files)")
    # chunk_size=1000: 1つの塊を最大1000文字にする
    # chunk_overlap=100: 前後の塊を100文字ずつダブらせてる。-> 文脈が途切れて意味がわからなくならないように
    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    docs = text_splitter.split_documents(documents)

    # ベクトル変換
    embeddings = OllamaEmbeddings(
        model=EMBEDDING_MODEL,
        base_url=OLLAMA_BASE_URL
    )   
    
    # ベクトルデータベースへの保存(FAISS)
    vectorstore = FAISS.from_documents(docs, embeddings)
    vectorstore.save_local(VECTOR_DB_PATH)

if __name__ == "__main__":
    ingest_docs()