# Chrome 拡張

`esmile009` の変換 API を使い、ページ上の Excel ダウンロードボタンの下から **PDF で保存** できます。

## 動作

1. 対象ページの Excel ダウンロードリンク（`.download-btn` など）を検出
2. その直下に **PDF で保存** ボタンを表示
3. クリックすると Excel を取得 → `/convert` API で PDF 化 → ブラウザのダウンロードフォルダへ保存

## 読み込み方（開発）

1. Chrome で `chrome://extensions` を開く
2. 右上で **デベロッパーモード** をオン
3. **パッケージ化されていない拡張機能を読み込む**
4. この `chrome-extension` フォルダを選択

## 設定

拡張のポップアップから **設定（API の URL）** を開いて、共通プレフィックスを保存します。

- 本番例: `https://engawa2525.com/esmile009`
- ローカル例: `http://127.0.0.1:18083`

## 動作確認

1. API を起動する（例: `docker compose up -d --build`）
2. テストページを開く: `http://127.0.0.1:18083/test-download`
3. 拡張を読み込んだ状態で **PDF で保存** をクリック

## `host_permissions` について

manifest の許可リストに無いホストへは `fetch()` が失敗します。別ドメインで試す場合は `manifest.json` の `host_permissions` と `content_scripts.matches` を編集して拡張を **再読み込み** してください。
