# 詰碁（ai:tsumego）の校正・回帰データ

## SGF

**対象局面（`generate_move_e2e.py` の第2引数＝進める手数）の求め方**: 詰碁モードは**常に黒番**
なので、各 SGF 本譜で下表の「旧実装は X で失敗」の **X が黒の手として現れる直前**が対象局面。
下表の「N手目」表記はケース間で不統一（game move 起点と黒の着手数起点が混在）なので使わない。
**期待手（正解）を本譜から探してはいけない** — 黒が正解を打ち損ねた後に**白が急所を取った手**を
拾って、解く側が白の局面を測ってしまう（実測 2026-07-31: case D の `WA4`、case E の `WK1` で
これを踏み、D/E を誤った局面で回帰させた）。導出済みの値:
`D=4 / E=6 / F=2 / G=0 / G2=2 / H=4 / F2=4 / I=0 / J=10 / K=0 / L=0 / M=4 / N=0 / O=0 / P=2 / Q=0 / R=0 / S=0 / T=2 / U=0`

| ファイル | 内容 |
|---|---|
| `case-d-gain-region-20260730.sgf` | 枠外の代償地帯が gain の符号を反転させた誤答局面（13路左下、正解 A4／別解 B3、旧実装は C3 で失敗）。region = `0,8,0,8`、対象は 4手目 |
| `case-e-ko-margin-20260730.sgf` | コウ勝ち前提のマージンが小さすぎて無条件の正解を捨てた誤答局面（13路下辺、正解 K1、旧実装は L1 でコウにして失敗）。region = `3,12,0,8`、対象は 6手目 |
| `case-f-gain-visit-share-20260730.sgf` | 探索の浅い候補の gain ノイズが正解を上回った誤答局面（13路右上、正解 N8、旧実装は N7 を選び白が生きた）。region = `4,12,3,12`、対象は 2手目。`gain_min_visit_ratio`（深さゲート）と `gain_verify`（同深さ検証）の回帰対象。**追記30（2026-07-31）の注**: この盤は `frame_destroys_problem`（追記18）導入前に保存された**壊れた枠**で、黒は実は**守り方**（`solver_attacks=False`・自石10子/相手石35子）。同深さ800visits では **全候補が 自石 −0.97〜−0.99/子・相手石 −1.00/子・−30目**＝どの手を打っても解けない（`class_screen_probe.py` 2run 一致）。つまり「正解 N8」は当時の選択則の回帰値であって解ける問題の正解ではない。それでもこの盤は**コウ脱出の退化を再現する唯一のケース**として有用で、N8 がコウ経路（応手 N7 の PV）と出た後、脱出が policy 上位 J11/J10/N11/M12 を全部「採用候補」にして 0.08 差で J11 を採っていた（`tsumego_ko_escape_succeeds` の回帰対象。E2E: **N8 3/3**、導入前は J11/N11/J10） |
| `case-g-frame-role-20260730.sgf` | 枠が詰碁自体を消していた誤答局面（13路左上、正解は初手 A11 でコウ、旧実装は B13 で不正解）。region = `0,7,3,12`、対象は 1手目（初手）。`frame_destroys_problem` / `solver_core_points`（枠採否判定と枠なしフォールバック）の回帰対象 |
| `case-g2-frameless-guard-20260730.sgf` | case G の枠なしフォールバック後の盤で、目数ガードが正解を足切りした誤答局面（2手目、正解 C13、旧実装は B13）。region = `0,7,3,12`。枠なし盤では目数差が圧縮され C13 の pointsLost 1.56〜2.26 がガード帯（best+2.0）を挟んで揺れる。`gain_rescue_margin`（救済＝gain 争いに参加できなかった候補でも gain が明確に上回る手を同深さ検証にかける）の回帰対象。**注（2026-07-30 追記17 の回帰時）**: 現在の解析は A10 を v1729〜1752 の本命として読み、gain が飽和（C13 の救済トリガー消失）して選択則の新旧どちらでも A10 3/3 になる（stash A/B で選択則起因でないことを確認済み）。A10 がアプリの解答樹にある別解かは GUI で要観察 |
| `case-f2-rescue-shadow-20260730.sgf` | gain 1位に立った v10 のノイズ手が本物を検証から締め出した誤答局面（case F 枠なし盤の 5手目、正解 N11/M12、旧実装は J11）。region = `5,12,6,12`。ノイズ N9(g+6.77) > 本物 N11(g+5.41)/M12(g+5.30) の順で、トップ1検証では N9 却下で救済終了。検証は毎回正しく序列化する（N11 -17.1 / M12 -17.2 / J11 -19.4 / N9 -26.9）ので、救済のトップ3全員検証（`TSUMEGO_GAIN_RESCUE_MAX_CANDIDATES`）の回帰対象。**追記17 のクラス裁定ゲートの回帰対象でもある**: 目数ガード外の救済採用手 N11 はコウ経路検査にかけない（応手が N9 に振れた run の偶発コウ形で、検証に負けている clean な失敗手 J10 に差し替わった実測あり） |
| `case-h-gate-cliff-20260730.sgf` | 深さゲートが目数ガード内の正解を足切りした誤答局面（13路右下・枠なし、5手目、正解 N4、旧実装は J7）。region = `5,12,0,6`。N4 は gain +4.4 断トツ・ガード内なのに visit比 0.46〜0.49 < 0.5 でゲート外、当時の救済（ガード外のみ）も届かず。救済対象の拡大（非 contenders 全体・visit比撤廃・採用マージン 1.0）の回帰対象。同深さ検証 N4 +13.2〜+14.2 vs 代替 +8.9〜+9.7 |

| `case-i-defender-ko-20260730.sgf` | **未対処の既知限界**: 守り側で「無条件の生き（捨て石あり）> コウ」を選べなかった誤答局面（13路右下・枠なし、初手、正解 N2、AI は J1 でコウ生きになり不正解）。region = `6,12,0,8`。原因は KataGo の探索崩壊（咎め W-N2 を 6000visits でも誤読）で、選択則・枠・深掘りのどれでも判別不能と実測済み（spec 追記13）。復帰はアンドゥで次候補（N2 が2位）。**エンジン更新時に再評価** |
| `case-j-points-tie-20260730.sgf` | gain も目数も 0.02 差で並んだ「正しい別解」を選んで不正解になった局面（13路右上・枠あり、11手目、正解 N10、旧実装は N11）。region = `6,12,1,12`。N11 も実際に白を殺せている（8000visits でも分離不能・同深さ検証も差 0.05 で無力）が、アプリの解答樹には N10 しか無い。目数同着バンド `points_epsilon` 内で visits 最多（KataGo の本命）を採るタイブレークの回帰対象（spec 追記14） |
| `case-k-ko-route-20260730.sgf` | 同着バンドの visits タイブレークが「コウで殺す手」を選んだ誤答局面（13路左上・枠あり、初手、正解 C13=無条件、旧実装は A12=W A11→B B11 のコウ）。region = `0,8,3,12`。KataGo はコウも黒勝ちと読むので gain・目数とも同着でクラス差が出ず、親 PV は白が枠へ手抜きしてコウが現れない。リージョン子局面解析の最善応手 PV のコウ形検出（`tie_ko_screen` / `tsumego_pv_reaches_region_ko`＝バンド内 無条件 > コウ）の回帰対象（spec 追記15）。A12 格下げ後の clean な2手 {C13, A10} は visits 接近の別解同士で、稀に手順前後の別解 A10 が選ばれる（spec 追記16 の残余） |
| `case-l-immediate-ko-20260730.sgf` | 候補手自身がコウを開始する形をコウ検査が素通しした誤答局面（13路右下・枠あり、初手、正解 J6=2子捨ての石の下、旧実装は L5=白L6の1子取りコウ）。region = `4,12,0,9`。守り方は次にコウ禁止で取り返せないため応手 PV にコウ形が現れない。検査シーケンスを [候補手]+応手PV に拡張した `tsumego_candidate_reaches_region_ko`（ply0 はクエリ不要で確定）の回帰対象（spec 追記16） |
| `case-n-live-frame-drop-20260730.sgf` | 生き問題の有効な枠が浅い読みで捨てられ、枠なし盤で詰碁が消えた誤答局面（13路左下・**枠なし**、初手、正解 B3=無条件生き、旧実装は D10＝死活と無関係な点）。region = `0,5,0,9`。**保存 SGF は認識盤そのもの**（枠なしで出題された回なので枠を剥がす復元ができない。`frame_validity_probe.py` は `core` として扱う）。枠あり（実 generate_move）B3 5/5 OK・枠なし D10 2/2 NG で、枠を捨てた判断そのものが誤答の原因。`frame_validity_visits`（捨てる前に 1800visits・**wideRootNoise=0** で読み直す）と `frame_over_frameless`（捨てる先の枠なし盤を測ってから捨てる）の回帰対象（spec 追記18）。**測るときは engine 起動を挟むこと**: 同一プロセスの再クエリは NN キャッシュが効いて独立サンプルにならない |
| `case-m-capture-gain-ko-20260730.sgf` | コウ手の gain が実信号になり同着バンドのコウ検査を素通りした誤答局面（13路右下・枠あり、5手目、正解 K1=無条件生き、旧実装は M2=白L2の1子取りからコウ生きに転落）。region = `4,12,0,8`。M2 の gain +1.8〜1.9 は「コウに勝つ前提」で白 L2/M3 を取り切る**実信号**（同深さ検証も +1.29 でコウ側を追認＝gain・目数・検証のスコア系メトリックはクラスを分離できない）のため gain 同着バンドが形成されず、旧 tie_ko_screen（バンド2手以上が条件）が不発のまま採用された。コウ検査を「選択パイプライン最後の成功クラス裁定」に一般化した `tsumego_class_screen_pool` / `tsumego_declass_choice` の回帰対象（spec 追記17）。構造検出は安定: 子局面の白最善応手 K1（アプリの反撃と同一）の PV の B M4（1子取り）がコウ形（2/2 run）。**追記24（2026-07-31）**: その後 K1 1〜3/6 に劣化していた（旧コードでも 2/3）。選択則は毎回 M2 を選んでおり、分岐しているのはコウ検査だけで、`拮抗応手 ['M4']` しか歩けない run では検査ブロックごと不発になる。原因は子局面解析の `wideRootNoise=0.04` で、root の Dirichlet ノイズが応手の visits 比を run ごとに揺らす（wRN=0.04 で K1 の比 0.44〜0.88 → **wRN=0 で 0.15 が 4/4 不動**）。`TSUMEGO_KO_SCREEN_WIDE_ROOT_NOISE`(0) と選択手専用の敏感な比 `TSUMEGO_KO_REPLY_RATIO_CHOSEN`(0.05) の回帰対象（**K1 8/8**）。切り分けは `ko_reply_ratio_probe.py` |

| `case-o-all-ko-band-20260731.sgf` | **正解が root 探索の visit 配分から漏れ、到達できる候補が全部コウだった誤答局面**（13路左上・枠あり、初手、正解 A11=無条件、旧実装は B12 で白 A11 のコウ）。region = `0,8,3,12`。root 1800visits の配分は B12 v1172 / C10 v622 / **残り46手すべて v1** で、正解 A11 は **12000visits にしても v1 のまま**（root の value が約29目ずれており PUCT が二度と訪れない＝深さでは原理的に届かない）。1visit の評価 pt+28.74 で min_visits・目数ガード・gain・救済・コウ検査プールの全部から締め出される。コウ経路検査自体は B12/C10 の両方を正しくコウと判定していた（2/2）ので、足りないのは対抗馬プールだけ。「目数ガード内が全部コウ経路」をトリガーに root policy 上位（未検査分）を同深さで測り直す `_ko_escape_choice` / `tsumego_ko_escape_candidates` / `tsumego_ko_escape_accepts` の回帰対象（spec 追記19）。**採用条件の不等号に注意**: コウ手のほうがスコアは高く出る（同深さ検証 B12 +41.95 > 正解 A11 +41.85）ので「上回ること」を要求すると正解が落ちる。失敗する clean 手は +18.5〜18.8 で 23 点下 |

| `case-p-visits-tie-ko-20260731.sgf` | **コウ経路検査の証拠（守り方の応手 PV）が枠へ手抜きして消えた誤答局面**（13路下辺・枠あり、3手目、正解 J1=無条件、旧実装は H1 で白 G1 のコウ）。region = `2,12,0,6`、対象は **2手目まで進めた局面**（`generate_move_e2e.py ... 2 2,12,0,6`）。選択自体は設計どおり（gain 飽和 → 目数差 0.03 が `points_epsilon` 内 → visits 最多の H1）で、**正解 J1 は目数最善**だったのでクラス裁定さえ働けば必ず J1 になる。不発の原因は `avoidMoves` の `untilDepth=1` が root の着手選択しか縛らず、**PV が ply3 で枠外（J12）へ手抜き**して肝心の G1 に届かないこと。歩く深さぶん縛る `TSUMEGO_KO_REGION_UNTIL_DEPTH`（=`TSUMEGO_TIE_KO_PLIES`=6）の回帰対象（spec 追記20）。実測 4 trial: untilDepth=1 で検出 1/4（PV `J1,L2,J12,...`）→ untilDepth=6 で 4/4（`J1,L2,G1,...`）、正解 J1 はどちらでも 4/4 clean。**必ずプロセスを分けて測ること**（1プロセス内では NN キャッシュで 3/3・4/4 と安定して見える） |

| `case-q-ko-is-answer-20260731.sgf` | **未対処の既知限界**: 準備手が正解の詰碁で、どの指標にも信号が出なかった誤答局面（13路右上・枠あり、初手、正解 N9=コウ、AI は H13 で白の無条件生き）。region = `4,12,4,12`。白は2群 A={J13,K13,J12} / B={L12,K11,L11,M11,J10,K10,K9,L9} が **K12 を共通の最後の呼吸点**として持ち、黒は外側の H13 と N11 を詰めてから K12 で両取りする形。ところが **B N11 は単独では自殺手**（M11・N10 に挟まれ呼吸点 N12 のみ）なので、先に **N9 で N10 をアタリ**にする準備手が要る。実測: root は H13 に 1800visits 中 1764・**12000visits でも 11943** を割き、N9 は v1〜v4。**全盤 20000visits/wRN=0 でも N9 は v3・winrate 0.450**（KataGo の value が準備手を「負け」と読んでいる）。子局面 8000visits でも白12子は H13 −11.56 / N9 −10.30 で**どちらも生存**、コウ勝ち前提の ownership はむしろ H13 が上（−7.45 で A群が死ぬ vs N9 −9.24）。同深さ検証は untilDepth=1 で差 2.2 → 8000visits で 1.26 → untilDepth=6 で 0.2（誤差内）と**解析パラメータで消える＝実信号ではない**。枠は `frame_validity_probe.py` で復元すると `black_attacks=True, ko=True`（推定もコウダテ側も正しい）で、**枠なし盤でも H13 が選ばれる**ため枠起因でもない。case O と違い policy 上位を同深さで測り直しても浮かばないので `_ko_escape_choice` でも救えない（spec 追記21）。**エンジン更新時に再評価** |

| `case-r-declass-nonsolution-20260731.sgf` | **答えがコウの詰碁で、クラス裁定が正解を「詰碁と無関係な clean 手」に差し替えた誤答局面**（13路上辺・**枠なし**、初手、正解 G13→白 J12→黒 J13 のコウ、旧実装は D8）。region = `0,12,7,12`。選択パイプラインは正解 G13（目数最善 pt+0.03 v1345）を選んでおり、コウ経路検査の**検出も正しい**（応手 J12 の PV がコウ形に到達）。落ちたのは格下げ先の妥当性で、**「無条件」は「攻めないので何も起きず自明に clean」でも成立する**。ownership で検算しても救えない（`class_screen_probe.py` 2run: 正解 G13 +0.86/+0.97 に対し誤答 D8 +1.32/+2.34 と**誤答のほうが高い**。相手石は全候補 −0.55〜−0.72＝答えがコウなら ply1 で成否は決着しない）。符号が一貫するのは目数だけで、格下げが正しい4ケースは格下げ先が必ず目数で優る（K −0.05 / L −0.11 / M −0.57 / P −0.03）のに case R の D8 は +0.52 劣る。格下げ先を同着バンド `points_epsilon` 内に限る `tsumego_declass_choice` と、脱出トリガーを「pool が全員コウ」に戻す `tsumego_class_screen_all_ko` の回帰対象（spec 追記23）。**追記24 の訂正 → 追記26 で救済経路は解決**: 「G13 3/3」は1セッション3run の過小評価で、実際は救済経路で揺れていた（`_verified_choice` の J13 vs G13 の差が margin=1.0 をまたいで **−1.05〜+1.31**、**wRN=0 にしても収まらない**）。救済候補の visits 床 `TSUMEGO_GAIN_RESCUE_MIN_VISIT_RATIO`(0.15) で J13（比 0.036〜0.05＝本物の 0.30〜0.90 より1桁下）を入口で落として解決。**残る揺れは root 解析（1800visits・wRN=0.04＝着手選択のクエリ）の visit 配分の分散**で、稀に J13/C8 が select 段階で選ばれる＝case I / Q と同じエンジン側の限界。**測るときは必ずセッションを分けること** |

| `case-s-attacker-role-tie-20260731.sgf` | **枠の攻め方推定が極値のタイで反転し、詰碁がスコアから切り離された誤答局面**（13路右上・枠あり、初手、正解 M10＝白を無条件に殺す、旧実装は H12 で詰碁と無関係な点）。region = `5,12,2,12`。**選択則は無実**（対抗馬 M10 も居て機構は全部動いており、それでも H12 が目数 -0.52 vs +0.15・gain +0.58 vs -1.01 の両方で勝つ＝KataGo が H12 を最善と読んでいる）。原因は盤で、コアの最左列 H に H11(白)/H10(黒) が並ぶタイを `min_by` が row-major 順で白に崩し、`guess_black_to_attack` が **-1** で反転していた（H10 を採れば +42、極値線を全部足せば +21）。反転枠は代償地帯を攻め方の黒に渡すので黒が +21目リードし、死活がスコアから切り離される。安全網 `frame_destroys_problem` は**手番側が攻め方だと反転しても本体石が壁と連絡して生きたまま**なので効かず、実測は v400 で +0.4977/+0.65（閾値 0.5 をまたぐ）→ v1800 +0.46。浅い読みの「生」を即採用していたため run ごとに採否が入れ替わっていた。`extremum_stones`（攻め方判定を極値線の石全部で取る）と `FRAME_SOLVER_CONFIRM_OWNERSHIP`(0.9、閾値近傍の「生」も確かめてから採用）の回帰対象（spec 追記27）。**役割を実測で選ぶ案は不可**（`frame_role_ab.py` の実測: 生きる詰碁 case M では誤った役割のほうが solver_core +0.99 > 正しい役割 +0.72、バランス距離も S/M とも誤った役割が最良） |

| `case-t-defender-seki-20260731.sgf` | **守り側の正解がセキで、目数ガードが正解を候補から落とした誤答局面**（13路下辺・枠あり、3手目、正解 L1＝セキ、旧実装は J2 でコウ生き）。region = `2,12,0,6`、対象は **2手目まで進めた局面**（`generate_move_e2e.py ... 0,2 2,12,0,6`。初手 M1 は新旧とも正解）。**詰碁の正解順序は役割で逆転する**（攻め方: 無条件死 > コウ > セキ ／ 守り方: 無条件生き > **セキ > コウ**）のに、選択則のスカラーは全部「どれだけ得したか」を測るので守り方のセキ（地0目・相手も生きる）は必ずコウ勝ちの下に出る。実測: root 目数 J2 -0.34 / L1 +4.30（**目数ガード best+2.0 が正解を落とし eligible=[J2] に潰れる**）、gain +0.20 / -3.83、同深さ検証値（全リージョン石）-16.66 / -19.79 と**どれも順序が逆**で、正しく出るのは**自石だけ**の +0.99 / **+1.00**/子。クラス検出そのものは正しい（`ko_route_probe.py` 1/1: J2=KO（応手 L1 の PV に L1 の取り返し）/ L1=clean / H2・N4=KO）。`tsumego_solver_attacks`（リージョン境界の壁の色＝攻め方）・`tsumego_role_stones`（成否を担う石だけで測る）・`tsumego_class_screen_applies`（対抗馬が1手も居なくてもクラス裁定を走らせる）・`tsumego_ko_escape_applies`（役割が読めるなら clean な対抗馬が居ても脱出する）の回帰対象（spec 追記28）。E2E: **M1 4/4・L1 4/4**（旧実装は L1 0/2） |

| `case-u-move-order-ko-20260731.sgf` | **PV を証拠にするコウ検出が「エンジンがそのコウを打たない」ために黙った誤答局面**（13路左下・枠あり、初手、正解 C1＝白を無条件死、旧実装は A3 で白 C1 → 黒 D1 がアタリ → 白 E1 の1子取りでコウ）。region = `0,8,0,8`。**手順前後そのものが争点**で、C1 を先に打つと D1 が {C1,D1} の2子連結になり白 E1 が2子取り＝コウにならない（正解本譜も白は E1 を打ってくるが黒 D1 で取り返せる）。A3 だと D1 が単独のまま残りコウを避けられない。選択則は A3 pt-0.09 v983 / C1 pt+0.12 v811 の**目数同着バンド内 visits タイブレーク**で A3 を採っており、クラス裁定さえ効けば C1 は格下げ先として届く位置に居た。不発の原因は**証拠の側**: コウを作る白の応手 C1 は visits比 **0.01**（v7/617）で敏感側 0.05 にも届かず、しかも C1 自身の PV `C1,A4,D6,E6,D7` にコウ手 E1 が無い（KataGo は C1 を黒+8.99＝白の損と評価）。**比 0.00 まで全応手を歩いても PV 由来の検出は 0/5 run**。リージョン解析は `untilDepth` で守り方からコウダテを取り上げるので、コウを仕掛けることが守り方の純損になり、**コウが争点の局面ほどエンジンはそのコウを打たない**。第2判定「守り方がコウ取りを**打てる状態**になったか」（`tsumego_defender_ko_points` / `TSUMEGO_KO_AVAIL_PLIES`=5）の回帰対象（spec 追記29）。E2E: **C1 3/3**（旧実装は A3）。3手目以降は既に手遅れで（白 C1 の時点で D1 はアタリ、黒 A1 の「clean」は PV を歩いただけの偽陰性）、**誤答を1手目に帰着させないと直せない**ケース |

## 診断スクリプト

KaTrain 本体とは独立。KataGo を起動するのでプロジェクトルートから実行する。
`REGION` は各スクリプト先頭の定数で、SGF ごとに合わせる（本番のリージョンは
`__main__.py` の `_apply_tsumego_region` / `_do_tsumego_frame` が設定する値。
KaTrain のログの `avoidMoves` から読み取れる）。

### `gain_probe.py` — 候補手ごとの gain 内訳を出す

```bash
python docs/superpowers/specs/calibration-data/tsumego/gain_probe.py <sgf> <move_number> [visits]
```

候補手を `gain(全石)` / `gain(リージョン内)` / `gain(リージョン内の相手石)` の3通りで並べ、
注目手については石ごとの ownership 変化（枠内 `in` / 枠外 `OUT` の区別つき）を出す。
**枠外の石が大きく動いていたら counterweight が効いている**サイン。

### `gain_region_ab.py` — 選択則の A/B 比較

```bash
python docs/superpowers/specs/calibration-data/tsumego/gain_region_ab.py <sgf> <moves_csv> [repeats]
# 例: ... case-d-gain-region-20260730.sgf 0,2,4 4
```

**1回の解析から旧（全石）/新（リージョン内）の両方の選択を計算する**ので、
KataGo の並列探索の run 間分散が交絡しない。選択則を変えるときはこの形で比較すること
（別 run で比べると分散に埋もれる → memory `feedback_batch_eval_variance` と同じ罠）。

### `points_tie_ab.py` — 目数同着タイブレーク（points_epsilon）の A/B 比較

```bash
python docs/superpowers/specs/calibration-data/tsumego/points_tie_ab.py <sgf> <moves_csv> <xmin,xmax,ymin,ymax> [repeats]
# 例: ... case-j-points-tie-20260730.sgf 0,2,4,6,8,10 6,12,1,12 3
```

gain_region_ab.py と同じく **1回の解析から旧（points_epsilon=0）/新（既定 0.25）の
両方の選択を計算する**。gain も目数もノイズ同着の局面（case J）で、旧則がコイン投げに
なるのに対し新則が visits 最多（KataGo の本命）へ寄ることを確認する。

### `generate_move_e2e.py` — 実 generate_move の E2E（検証・救済経路込み）

```bash
python docs/superpowers/specs/calibration-data/tsumego/generate_move_e2e.py <sgf> <moves_csv> <xmin,xmax,ymin,ymax> [repeats]
# 例: ... case-j-points-tie-20260730.sgf 0,10 6,12,1,12 3
```

select 単体の A/B は generate_move 後段（score_best 同深さ検証・救済）を通らないので、
そこで巻き戻される回帰を見逃す（実測 case J: select は N10 を選んだのに無条件の
score_best 検証が却下して N11 に巻き戻し、GUI で誤答が再発）。**選択則を変えたら
select レベルの A/B に加えて必ずこれも回すこと**。

### `child_depth_probe.py` — 「本当に悪い手」か「読まれていないだけ」かを切り分ける

```bash
python docs/superpowers/specs/calibration-data/tsumego/child_depth_probe.py \
    <sgf> <move_n> <xmin,xmax,ymin,ymax> <moves_csv|-> [root_visits] [child_visits] [root_wrn]
# 例: ... case-o-all-ko-band-20260731.sgf 0 0,8,3,12 A11,B12,C10 1800 1800
```

root の候補表（visits / **prior** / pointsLost / gain / 相手石 ownership）と、指定手を1手
進めた**子局面を独立に解析した値**を並べる。root の movesOwnership・pointsLost は候補ごとに
探索の深さが違うので、**visits が付かなかった手の数字は NN の生評価1回でしかない**。
「その手が本当に悪いのか、単に読まれていないだけか」はこれを回さないと区別できない
（実測 case O: root 1visit の A11 は pt+28.74/白は生き、子局面 1800visits では +11.53目/白は全滅）。

`moves_csv` に `-` を渡すと root の表だけ出す。`root_visits` を変えて **深さで届くのか**を
確かめるのにも使う（case O は 12000visits でも A11 が v1 のままだった）。

### `ko_route_probe.py` — 候補がコウ経路か無条件かを本番と同じ手順で判定

```bash
python docs/superpowers/specs/calibration-data/tsumego/ko_route_probe.py \
    <sgf> <move_n> <xmin,xmax,ymin,ymax> <moves_csv> [visits] [repeats]
# 例: ... case-o-all-ko-band-20260731.sgf 0 0,8,3,12 A11,B12,C10,C13,B13 800 2
```

`_ko_route_screen` と同じ判定（候補手自身の1子取り＋守り方の拮抗応手の PV）に加え、
同深さの目数と相手石 ownership も出す。**クラス（コウ/無条件）と成否（殺せている/いない）は
別軸**であることを1枚で確認できる（実測 case O: A11=clean かつ成功 / B12・C10=コウだが成功 /
C13・B13=clean だが失敗）。`repeats` で run 間の安定性を見る。

### `class_screen_probe.py` — コウ経路検査の「格下げ先」が本当に詰碁を解いているか測る

```bash
python docs/superpowers/specs/calibration-data/tsumego/class_screen_probe.py \
    <sgf> <move_n> <xmin,xmax,ymin,ymax> <moves_csv> [visits] [repeats]
# 例: ... case-r-declass-nonsolution-20260731.sgf 0 0,12,7,12 G13,D8,J13,C8 800 2
```

本番の `_region_child_verdict` をそのまま呼び、クラス（コウ/無条件）に加えて**格下げの採否に
使える値**（全リージョン石の絶対 ownership＝`tsumego_ko_escape_accepts` が見る値、自石・相手石の
1子平均）を並べる。`ko_route_probe.py` はクラスと相手石しか出さないので、「clean な対抗馬が
**成功しているか**」を判定できるかどうかの検算にはこちらを使う。実測 case R: どの指標でも
正解（コウ）が誤答（clean）を下回り、**答えがコウの詰碁では ply1 の ownership では判別できない**
ことがこれで確定した（→ 目数の同着バンドで裁定する設計になった。spec 追記23）。

### `ko_reply_ratio_probe.py` — 守り方の応手を全部並べ、コウ検出の閾値を決める

```bash
python docs/superpowers/specs/calibration-data/tsumego/ko_reply_ratio_probe.py \
    <sgf> <move_n> <xmin,xmax,ymin,ymax> <moves_csv> [visits] [top_n] [wide_root_noise]
# 例: ... case-m-capture-gain-ko-20260730.sgf 4 4,12,0,8 M2,K1 800 6 0.0
```

`ko_route_probe.py` は現在の比を通った応手しか見せないので、閾値そのものを決められない。
こちらは比の外の応手も含めて visits / 比 / 目数 / コウ到達を並べ、「**この比以下まで歩けば
検出できる**」を出す。`wide_root_noise` を 0 にすると root の Dirichlet ノイズが消えて
応手配分が決定的になる（実測 case M: 0.04 で比 0.44〜0.88 とばらつく → 0 で 0.15 が 4/4 不動）。
**閾値を動かす前に必ず全ケースで両側（検出すべき手 / clean のままにすべき手）を測ること** —
実測では単一閾値で分離できない（検出すべき最小 0.09 ＜ clean にすべき最大 0.16、spec 追記24）。

### `ko_available_probe.py` — 「PV が打つコウ」と「守り方が打てるコウ」を並べる

```bash
python docs/superpowers/specs/calibration-data/tsumego/ko_available_probe.py \
    <sgf> <move_n> <xmin,xmax,ymin,ymax> <moves_csv> [visits] [ratio] [repeats]
# 例: ... case-u-move-order-ko-20260731.sgf 0 0,8,0,8 A3,C1 800 0.05 3
```

同じ応手 PV を歩きながら `PLAYED`（従来判定＝PV がコウ形に到達）と `AVAIL`（新判定＝守り方が
コウ取りを打てる状態になった ply）を両方出す。**ヒットした ply が全部出る**ので、真陽性
（ply1/3/5）と偶発コウ（ply7）の切り分けに使う。閾値 `TSUMEGO_KO_AVAIL_PLIES` を動かす前に
必ず全ケースで両側を測ること — 実測では ply7 に **case G2 の正解 C13** と **case R の C8** が
立っており、そこまで数えると正解が格下げ・脱出に流れる。

### `ko_liability_probe.py` — 守り方のコウの権利を純盤面で見る（KataGo 不要）

```bash
python docs/superpowers/specs/calibration-data/tsumego/ko_liability_probe.py \
    <sgf> <move_n> <xmin,xmax,ymin,ymax> <moves_csv>
```

`immediate`（守り方が今すぐ打てるコウ取り）と `setup`（1手かけて作れるか＝攻め方の受けを
考えない上界）を候補ごとに出す。**着手前**の値も出るので「そのコウは局面に元からあるのか、
候補手が作ったのか」が分かる（本番の判定は元からあるコウを除外する）。`setup` は上界なので
**単独で候補を失格にしてはいけない** — 実測 case U では正解 C1 の後も白 G1→E1 のコウが作れる
（黒に受ける手番があるので実現しない）ため、A3 と C1 を分離できない。

### `ko_margin_ab.py` — コウ勝ち前提の採用判定を検証

```bash
python docs/superpowers/specs/calibration-data/tsumego/ko_margin_ab.py <sgf> <move_number> <xmin,xmax,ymin,ymax> <期待手> [repeats]
# 例: ... case-e-ko-margin-20260730.sgf 6 3,12,0,8 K1 3
```

現在の `ko_win_margin` で N 回走らせ、最後に `ko_win_margin=0.5`（旧既定）でも1回走らせて
新旧を比較する。コウ判定ログ（通常最善・コウ勝ち前提・差・閾値）だけを抜き出して表示する。

### `frame_validity_probe.py` — 枠が詰碁を壊していないか判定し、枠あり／枠なしを比較

```bash
python docs/superpowers/specs/calibration-data/tsumego/frame_validity_probe.py <sgf> <move_number> <xmin,xmax,ymin,ymax> <期待手csv> [trial_visits] [visits] [validity_visits]
# 例: ... case-g-frame-role-20260730.sgf 0 0,7,3,12 A11
# 枠なしで出題された回の SGF（case N）もそのまま渡せる（枠が無い盤はコアとして扱う）
```

引数の SGF は**キャプチャで出題された盤**（保存SGFのroot）。枠付きならそこから本体（コア）石を
復元し（4辺の壁の総当たり×攻め方×コウダテを再枠張りして元の盤に一致する組合せを採る）、
枠候補ごとに「手番側の本体石が生きているか」を**本番と同じ二段構え**（浅い読みで死と出たら
`validity_visits` で読み直す＝`frame_validity_verdicts`）で判定し、全枠が壊れ判定なら
捨てる先の枠なし盤も測って比較する（`frame_over_frameless`）。その上で
**枠あり・枠なしそれぞれで `select_tsumego_move` が何を選ぶか**を出す。

**分散を見るときは engine 起動を挟むこと**（1プロセス内で同じ局面を測り直しても探索木が
再利用されて独立サンプルにならない。実測 case N: 1プロセス内では +0.57/+0.76/+0.71 と
安定して見えるが、プロセスを分けると -0.95〜+0.95 の二峰性）。

誤答報告が来たら最初にこれを回す。枠が詰碁を消していれば `DESTROYS the problem` が出る
（＝選択則をいじっても無駄。実測 case G: 枠あり B13 NG / 枠なし A11 OK）。

### `frame_role_ab.py` — 枠の攻め方推定を強制して A/B する

```bash
python docs/superpowers/specs/calibration-data/tsumego/frame_role_ab.py \
    <sgf> <move_number> <xmin,xmax,ymin,ymax> <期待手csv> [trial_visits] [visits]
# 例: ... case-s-attacker-role-tie-20260731.sgf 0 5,12,2,12 M10
```

`frame_validity_probe.py` は本番と同じ経路（＝`guess_black_to_attack` の推定をそのまま使う）
しか測らないので、「枠が壊れている」と出たときに**推定が反転しているのか、この詰碁では
どちらの役割でも枠が張れないのか**を区別できない。こちらは (攻め方, コウダテ) の4通りを
すべて張り、枠ごとに root lead / バランス距離 / 手番側の本体石 ownership / `select_tsumego_move`
の選ぶ手を並べる。推定が反転しているだけなら反対の役割の枠だけが usable かつ正解手を選ぶ
（実測 case S: role=True の2枠が +1.00/子 で M10、role=False の2枠が +0.65/+0.08 で H12）。

**この出力を「役割の自動判定」に使ってはいけない**: 反転した枠では手番側が「攻め方」に
なって壁と連絡するので、生きる詰碁では**誤った役割のほうが solver_core が高く出る**
（実測 case M: 誤 +0.99 vs 正 +0.72）。バランス距離も S/M とも誤った役割が最良を出す。

## 注意

- SGF には必ず `RU[chinese]` を入れる。未指定だと engine 既定の japanese になり、
  面積計算前提の枠のスコアが 25目規模でずれる（spec の「落とし穴（要注意）」参照）
- 実測値は spec `docs/superpowers/specs/2026-07-29-tsumego-ownership-design.md` の追記に記録
