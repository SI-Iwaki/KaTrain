---
description: 上流との同期状態・エンジン切替の経緯・Smart App Control による katago のブロック（WinError 4551）の仕組みと切り分け
paths:
  - "katrain/core/engine.py"
  - "katrain/KataGo/**"
  - "tools/warm_katago_sac.ps1"
---

# 環境（上流同期・エンジン切替・Smart App Control）

上流の修正を移植するとき、エンジン／モデルを差し替えるとき、起動や `cargo` が 4551 で失敗したときに読む。2026-11-15 に CLAUDE.md から文言を変えずに移した。

## 上流との同期とエンジン切替

- 上流との同期: git remote `upstream`（`git fetch upstream --tags` で最新を取る。fork は v1.17.1.1 の tarball 起点で git 履歴を共有しないので merge はできず、cherry-pick も効かない＝差分を読んで手で移植する）。**2026-09-04 に v1.20.0 までの修正を移植済み**: エンジンのスレッド競合修正（`query_generation`・RLock・stdin flush をロック外へ）、`Game` のロック整理と `expected_node`、AI 待ちループの `raise_if_discarded`（新規対局中に AI が考えていると固まるバグ）、未知の戦略名のフォールバック、GIB パーサ、`show_move_numbers` / `anim_pv_moves` 設定、KataGo ダウンロード一覧 v1.18.1。**移植しなかったもの**: KivyMD 撤去（`widgets/material/`）、`pysgf` への置換、リモートエンジン（websocket）、ruff 整形、Ctrl+H への reset-analysis 移動、同梱エンジン／モデルの更新（TensorRT 版は手動管理＝解析条件が変わるので校正のやり直しが要る。**2026-09-04 に A/B 実測のうえ v1.18.2 CUDA＋transformer b10c384 へ切替**: 難解の E 尺度は不変、解析は +34〜54% 速いが、詰碁 E2E の回帰点 2 件〈F2@4・AA@6〉がネット起因で 3/3 壊れた。**同日に詰碁を再校正済み**（同ディレクトリの results §8）: AA@6 は PV コウ検出の「打つ側の既存コウ」除外〈判定のみ・解析不変〉で 3/3 回復、F2@4 はネットの読みそのもの＝既知限界、O@0 は PV 依存の揺れ 1〜2/3。回答帳 538 手順は 320→302〈破損 60・回復 42＝機構別の失敗率は不変の拡散した揺れ〉、閾値〈gain_epsilon / points_epsilon〉は反実仮想で差引 +4 以下＝動かさない。記録と切替用 config は `docs/superpowers/specs/calibration-data/engine-ab/`）

## WinError 4551（Smart App Control）

**起動が `[WinError 4551] アプリケーション制御ポリシーによってこのファイルがブロックされました` で失敗したら**: Smart App Control（SAC）が未署名の katago を止めている。**2026-11-13 にユーザーが SAC をオフにした**（`HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy` の `VerifiedAndReputablePolicyState` = 0。累積更新 KB5083769〈2026-04〉以降は再インストールなしでオン／オフできる＝Windows セキュリティ → アプリとブラウザーの制御 → スマート アプリ コントロール）ので、4551 が出たらまずこの値が 1 に戻っていないかを見る。SAC オンのときの仕組み（実測 2026-11-13）: 許可判定は NTFS 拡張属性 `$KERNEL.PURGE.ESBCACHE` に載り、オフセット 0x20 の FILETIME が**許可の有効期限**（前回の許可から約24時間・DLL によっては数日。期限切れのファイルは全部止まり期限内は全部通る、で全ファイル一致）。**再起動しなくても期限切れの次の起動でクラウドに再照会され、拒否されうる**（11/12 20:09 に通った cuda 版が 22:02 に期限切れ → 00:44 の KaTrain 起動で拒否。新しいコピーを作って照会し直させてもその場で拒否、13分待っても回復しなかった）。拒否の直後の再試行はクラウドに聞き直さない（イベント 3118 の `DefenderMadeCloudCall=false`）。期限内に起動しても期限は延びないので、ログオン時に空打ちする `tools/warm_katago_sac.ps1`（タスク `KaTrain-WarmKataGoSAC`・ログ `~/.katrain/logs/sac_warmup.log`。SAC オフの間は無害な no-op）では日中の期限切れを防げない。旧記述の「再起動後の初回だけ止まり数分で自然回復」は一部の現象でしかない（2026-09-09 の実測はそうだった）。同スクリプトは 2026-11-13 まで、exe が拒否されると直前の exe の終了コードを読んで **OK と誤記録**していた（修正済み）。**自己署名では効かない**（信頼された CA の証明書による署名なら通る）。切り分けは `Get-WinEvent -LogName Microsoft-Windows-CodeIntegrity/Operational` の 3077/3033（ブロック・ファイル名入り）と 3118（`DefenderMadeCloudCall` / `DefenderCloudHTTPCode`）、`fsutil file queryEA <exe>`。CLAUDE.md 内の `cargo` の `os error 4551` も同じ SAC が原因
