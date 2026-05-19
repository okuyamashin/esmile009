# Chrome 拡張（準備中）

`esmile009` の変換 API（例: `/health`）への疎通確認と、設定（API ベース URL）のひな型です。

## 読み込み方（開発）

1. Chrome で `chrome://extensions` を開く
2. 右上で **デベロッパーモード** をオン
3. **パッケージ化されていない拡張機能を読み込む**
4. この `chrome-extension` フォルダを選択

## 設定

拡張のポップアップから **設定（API の URL）** を開いて、共通プレフィックスを保存します。

- 例（Apache が `/esmile009/` でプロキしている前提）  
  **`https://engawa2525.com/esmile009`**

## `host_permissions` について（重要）

manifest の許可リストに無いホストへは、`fetch()` が失敗します（ローカルの Docker で試すとき等）。

開発用に増やしたいホストがある場合、`manifest.json` の `host_permissions` を編集して拡張を **再読み込み**してください。

## 次のステップ（この後の実装）

- 対象サイトのフォーム/DOMに合わせた **コンテンツスクリプト**
- **`/convert`** へのファイル送信（multipart）と、`downloads.download` での保存など
