#!/usr/bin/env python3
"""
ESP32 Writer オーケストレーター実行スクリプト
"""
import sys
import os
import asyncio
import argparse
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.orchestrator import ESP32WriterOrchestrator

def parse_args():
    """コマンドライン引数の解析"""
    parser = argparse.ArgumentParser(
        description="ESP32 Writer - Arduino スケッチの自動書き込みシステム",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python3 bin/orchestrator.py                    # 通常起動
  python3 bin/orchestrator.py --config /path    # 設定ディレクトリ指定
  python3 bin/orchestrator.py --test            # テストモード
        """
    )
    
    parser.add_argument(
        "--config", "-c",
        type=str,
        help="設定ディレクトリのパス (デフォルト: ./config)"
    )
    
    parser.add_argument(
        "--test", "-t",
        action="store_true",
        help="テストモード（実際のハードウェアなしで動作確認）"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="詳細ログを表示"
    )
    
    return parser.parse_args()

async def main():
    """メイン関数"""
    try:
        # コマンドライン引数の解析
        args = parse_args()
        
        # 設定ディレクトリのパス
        if args.config:
            config_dir = args.config
        else:
            config_dir = str(project_root / "config")
        
        print(f"ESP32 Writer システム起動中...")
        print(f"設定ディレクトリ: {config_dir}")
        if args.test:
            print("テストモード: ハードウェアなしで動作")
        
        # オーケストレーター作成・実行
        orchestrator = ESP32WriterOrchestrator(config_dir)
        await orchestrator.start()
        
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())