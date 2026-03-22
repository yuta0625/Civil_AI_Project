"""
    ・PDFファイルをMarkdown(.md)に一括変換するスクリプト
    ・変換後のMarkdownはingest.pyでベクトルDB(FAISS)に取り込まれる
    ・「marker」パッケージを使用して行う
        ・高品質なMarkdownを生成できる点から利用する
"""


import os
import glob
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict

def main() -> None:
    # パスの設定
    input_dir = "/app/data/"
    output_dir = "/app/data/markdown_docs"
    os.makedirs(output_dir, exist_ok=True)
    
    # デフォルト設定でモデルを構築
    model_dict = create_model_dict()
    converter = PdfConverter(artifact_dict=model_dict)
    
    # PDFファイルを再帰的に検索
    pdf_files = glob.glob(os.path.join(input_dir, "**/*.pdf"), recursive=True)
    print(f"total {len(pdf_files)} files")

    for i, pdf_path in enumerate(pdf_files, 1):
        rel_path = os.path.relpath(pdf_path, input_dir)
        base_name = os.path.splitext(os.path.basename(rel_path))[0]
        sub_dir = os.path.dirname(rel_path)
        
        # 保存先ディレクトリの作成
        target_dir = os.path.join(output_dir, sub_dir)
        os.makedirs(target_dir, exist_ok=True)
        
        md_path = os.path.join(target_dir, f"{base_name}.md")
        
        # すでに変換済みの場合はスキップ（再開を容易にするため）
        if os.path.exists(md_path):
            print(f"[{i}/{len(pdf_files)}] skip: {rel_path}")
            continue

        try:
            print(f"[{i}/{len(pdf_files)}] change: {rel_path}")
            
            # 解析実行
            output = converter(pdf_path)
            
            # Markdownテキストを抽出して保存
            # 最新のMarkdownOutputクラスからテキストを取得
            markdown_text = output.markdown
            
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(markdown_text)
                
            print(f"success -> {md_path}")
            
        except Exception as e:
            print(f"Error ({rel_path}): {str(e)}")

if __name__ == "__main__":
    main()