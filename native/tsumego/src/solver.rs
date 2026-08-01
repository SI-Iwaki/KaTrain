//! 死活ソルバの探索カーネル。Python 参照実装（reference.py）の
//! _search / _opt と同一の意味論（差分テストで突き合わせる）。
//! 分類ラダー・root 全手評価・コウ細分は Python 側（NativeSolver が編成）。

use crate::board::{opponent, Board, ChainBuf, EMPTY};
use std::collections::HashMap;
use std::hash::{BuildHasherDefault, Hasher};
use std::time::Instant;

/// SipHash を避ける軽量ハッシュ（キーは既に Zobrist で混ざっている）
#[derive(Default)]
pub struct FxHasher(u64);

impl Hasher for FxHasher {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.0 = (self.0.rotate_left(5) ^ b as u64).wrapping_mul(0x517CC1B727220A95);
        }
    }
    fn write_u64(&mut self, v: u64) {
        self.0 = (self.0.rotate_left(5) ^ v).wrapping_mul(0x517CC1B727220A95);
    }
    fn write_u8(&mut self, v: u8) {
        self.write_u64(v as u64);
    }
    fn write_i8(&mut self, v: i8) {
        self.write_u64(v as u64);
    }
}

type FxMap<K, V> = HashMap<K, V, BuildHasherDefault<FxHasher>>;

pub const PRED_ALIVE: u8 = 0;
pub const PRED_SEKI: u8 = 1;
pub const PRED_SEM_WIN: u8 = 2;
pub const PRED_SEM_SEKI: u8 = 3;

const INF_DEP: u32 = u32::MAX;
const PASS: i32 = -1;

pub struct Timeout;

fn mix64(mut x: u64) -> u64 {
    x = (x ^ (x >> 33)).wrapping_mul(0xFF51AFD7ED558CCD);
    x = (x ^ (x >> 33)).wrapping_mul(0xC4CEB9FE1A85EC53);
    x ^ (x >> 33)
}

type PosKey = (u64, u64);

pub struct Solver {
    pub board: Board,
    pub region: Vec<u16>,
    pub in_region: Vec<bool>,
    pub target_color: u8,
    pub attacker_color: u8,
    pub own_color: u8,
    pub root_to_play: u8,
    pub t_bit: Vec<u64>, // 点 -> live-origin ビット（0 = origin でない）
    pub o_bit: Vec<u64>,
    pub live_t: u64,
    pub live_o: u64,
    pub t_origin: Vec<u16>,
    pub o_origin: Vec<u16>,
    tt: FxMap<(u64, u64, u8, u8, i8), (bool, bool)>,
    history: FxMap<PosKey, u32>,
    path_moves: Vec<(i32, Vec<u16>)>,
    benson_cache: FxMap<(u64, u64, u8), Vec<u64>>,
    hist_order: Vec<[u32; 3]>,
    pub nodes: u64,
    pub node_limit: u64,
    pub deadline: Option<Instant>,
    pub taint_any: bool,
    buf: ChainBuf,
    opt_memo: FxMap<(u64, u64, u8, u8, i8, bool), (u32, u32, Vec<i32>)>,
    opt_nodes: u64,
    pub opt_node_limit: u64,
    // ordered_moves 用の使い回しバッファ（連の呼吸点数を cap 付きで測る）
    cl_epoch: Vec<u32>,
    cl_libs: Vec<u16>,
    cl_size: Vec<u16>,
    cl_gen: u32,
    pn_tt: FxMap<(u64, u64, u8, u8, i8), (u64, u64, bool, i32)>,
    pub use_dfpn: bool,
    pub root_ban: i32, // 直前に root へ適用した着手が作ったコウ禁止点（-1 = なし）
}

impl Solver {
    pub fn new(
        board: Board,
        region: Vec<u16>,
        target_color: u8,
        own_color: u8,
        root_to_play: u8,
        t_origin: Vec<u16>,
        o_origin: Vec<u16>,
    ) -> Solver {
        let n = board.stones.len();
        let mut in_region = vec![false; n];
        for &p in &region {
            in_region[p as usize] = true;
        }
        let mut t_bit = vec![0u64; n];
        let mut live_t = 0u64;
        for (i, &p) in t_origin.iter().enumerate() {
            t_bit[p as usize] = 1u64 << i;
            live_t |= 1u64 << i;
        }
        let mut o_bit = vec![0u64; n];
        let mut live_o = 0u64;
        for (i, &p) in o_origin.iter().enumerate() {
            o_bit[p as usize] = 1u64 << i;
            live_o |= 1u64 << i;
        }
        let buf = ChainBuf::new(n);
        Solver {
            board,
            region,
            in_region,
            target_color,
            attacker_color: opponent(target_color),
            own_color,
            root_to_play,
            t_bit,
            o_bit,
            live_t,
            live_o,
            t_origin,
            o_origin,
            tt: FxMap::default(),
            history: FxMap::default(),
            path_moves: Vec::new(),
            benson_cache: FxMap::default(),
            hist_order: vec![[0u32; 3]; n],
            nodes: 0,
            node_limit: u64::MAX,
            deadline: None,
            taint_any: false,
            buf: buf,
            opt_memo: FxMap::default(),
            opt_nodes: 0,
            opt_node_limit: 4_000_000,
            cl_epoch: vec![0u32; n],
            cl_libs: vec![0u16; n],
            cl_size: vec![0u16; n],
            cl_gen: 0,
            pn_tt: FxMap::default(),
            use_dfpn: true,
            root_ban: -1,
        }
    }

    /// root を1手進める（TT は位置キーなので温存される。§6.6 の証明ストア）。
    /// 戻り値 false = 非合法手
    pub fn advance_root(&mut self, mv: i32, color: u8) -> bool {
        self.history.clear();
        self.path_moves.clear();
        if mv == PASS {
            self.root_ban = -1;
            self.root_to_play = opponent(color);
            return true;
        }
        match self.play(mv as usize, color) {
            None => false,
            Some((_u, new_ban, _rt, _ro)) => {
                self.root_ban = new_ban;
                self.root_to_play = opponent(color);
                true
            }
        }
    }

    /// use_dfpn に応じて df-pn / DFS で現局面の値を求める
    #[allow(clippy::too_many_arguments)]
    fn value_here(
        &mut self,
        pred: u8,
        komaster: u8,
        budget: i8,
        to_play: u8,
        ban: i32,
        pass_count: u8,
        ply: u32,
    ) -> Result<(bool, bool), Timeout> {
        if self.use_dfpn {
            self.dfpn_value(pred, komaster, budget, to_play, ban, pass_count, ply)
        } else {
            let (v, t, _d) = self.search(pred, komaster, budget, to_play, ban, pass_count, ply)?;
            Ok((v, t))
        }
    }

    /// p の連の (呼吸点数, 石数) を cap 付きで測る（cap 到達で打ち切り。順序付け専用）。
    /// 結果は cl_gen 世代で連の全石にメモする
    fn capped_chain_info(&mut self, p: usize, cap: u16) -> (u16, u16) {
        if self.cl_epoch[p] == self.cl_gen {
            return (self.cl_libs[p], self.cl_size[p]);
        }
        let color = self.board.stones[p];
        self.buf.epoch += 2;
        let ce = self.buf.epoch;
        let mark = &mut self.buf.mark;
        let mut stack = vec![p as u16];
        mark[p] = ce;
        let mut stones: Vec<u16> = Vec::with_capacity(16);
        let mut libs: u16 = 0;
        while let Some(q) = stack.pop() {
            stones.push(q);
            for &n in &self.board.neighbors[q as usize] {
                let v = self.board.stones[n as usize];
                if v == EMPTY {
                    if mark[n as usize] != ce + 1 {
                        mark[n as usize] = ce + 1;
                        libs += 1;
                    }
                } else if v == color && mark[n as usize] != ce {
                    mark[n as usize] = ce;
                    stack.push(n);
                }
            }
            if libs >= cap {
                break; // 順序付けには「3以上」で十分 = 壁の大連を全走査しない
            }
        }
        let libs_c = libs.min(cap);
        let size_c = (stones.len() as u16).min(64);
        for &q in &stones {
            self.cl_epoch[q as usize] = self.cl_gen;
            self.cl_libs[q as usize] = libs_c;
            self.cl_size[q as usize] = size_c;
        }
        (libs_c, size_c)
    }

    fn beneficiary(&self, pred: u8) -> u8 {
        if pred == PRED_ALIVE || pred == PRED_SEKI {
            self.target_color
        } else {
            self.own_color
        }
    }

    fn pass_alive_bits(&mut self, color: u8) -> Vec<u64> {
        let key = (self.board.h1, self.board.h2, color);
        if let Some(hit) = self.benson_cache.get(&key) {
            return hit.clone();
        }
        let bits = self.board.benson_pass_alive(color);
        if self.benson_cache.len() > 400_000 {
            self.benson_cache.clear();
        }
        self.benson_cache.insert(key, bits.clone());
        bits
    }

    fn any_live_pass_alive(&mut self, color: u8, own_side: bool) -> bool {
        let bits = self.pass_alive_bits(color);
        let (origins, live, bitmap) = if own_side {
            (&self.o_origin, self.live_o, &self.o_bit)
        } else {
            (&self.t_origin, self.live_t, &self.t_bit)
        };
        for &p in origins {
            if live & bitmap[p as usize] != 0 && bits[p as usize / 64] & (1u64 << (p % 64)) != 0 {
                return true;
            }
        }
        false
    }

    /// live-origin 連のどれかが「全隣接がその連の石」の完全眼を2つ持つか。
    /// 持てば Benson を呼ばずに無条件生きが確定する（両眼への打ち込みは常に自殺手）。
    /// Benson より弱い（大きな眼空間の pass-alive を見ない）が健全＝早期打ち切りが
    /// 少し遅れるだけで値は変わらない。毎ノードの Benson が最大のコストだったため導入
    fn cheap_two_eyes(&mut self, own_side: bool) -> bool {
        let origins: Vec<u16> = if own_side {
            self.o_origin
                .iter()
                .cloned()
                .filter(|&p| self.live_o & self.o_bit[p as usize] != 0)
                .collect()
        } else {
            self.t_origin
                .iter()
                .cloned()
                .filter(|&p| self.live_t & self.t_bit[p as usize] != 0)
                .collect()
        };
        let mut visited: Vec<u16> = Vec::new();
        let mut found = false;
        for &p in &origins {
            if visited.contains(&p) {
                continue; // 同じ連は一度だけ
            }
            self.buf.epoch += 2; // 連ごとに epoch を進める（別連の石を同一連と誤認しない）
            let ce = self.buf.epoch;
            self.board.chain(p as usize, &mut self.buf.stones, &mut self.buf.libs, &mut self.buf.mark, ce);
            visited.extend(self.buf.stones.iter().cloned());
            let mut eyes = 0;
            for &e in self.buf.libs.iter() {
                let all_own = self.board.neighbors[e as usize]
                    .iter()
                    .all(|&n| self.board.stones[n as usize] != EMPTY && self.buf.mark[n as usize] == ce);
                if all_own {
                    eyes += 1;
                    if eyes >= 2 {
                        found = true;
                        break;
                    }
                }
            }
            if found {
                break;
            }
        }
        found
    }

    /// 生存の早期確定: 一点眼2つ（安価）→ ダメなら Benson（キャッシュ付き）。
    /// Benson は大きな眼空間の pass-alive を「埋め尽くす前に」確定できる唯一の
    /// 打ち切りで、これが無いと広い地の生き証明が深い充填の探索に爆発する（§6.3-2）
    fn alive_now(&mut self, own_side: bool, deep: bool) -> bool {
        if self.cheap_two_eyes(own_side) {
            return true;
        }
        if !deep {
            return false; // probe（子見積もり）では Benson を呼ばない（1ノード×子数で爆発する）
        }
        let color = if own_side { self.own_color } else { self.target_color };
        self.any_live_pass_alive(color, own_side)
    }

    /// deep=false は probe 用の安価判定のみ（見逃した終端は展開先ノードの入口で捕まる＝健全）
    fn early_eval_at(&mut self, pred: u8, deep: bool) -> Option<bool> {
        if pred == PRED_ALIVE || pred == PRED_SEKI {
            if self.live_t == 0 {
                return Some(false);
            }
            if self.alive_now(false, deep) {
                return Some(true);
            }
            return None;
        }
        if self.live_o == 0 {
            return Some(false);
        }
        if pred == PRED_SEM_WIN {
            if self.live_t != 0 {
                if self.alive_now(false, deep) {
                    return Some(false); // 相手 target が両眼＝もう殺せない
                }
                return None;
            }
            if self.alive_now(true, deep) {
                return Some(true);
            }
            return None;
        }
        if self.alive_now(true, deep) {
            return Some(true);
        }
        None
    }

    fn early_eval(&mut self, pred: u8) -> Option<bool> {
        self.early_eval_at(pred, true)
    }

    fn two_pass_eval(&mut self, pred: u8) -> bool {
        match pred {
            PRED_ALIVE => self.any_live_pass_alive(self.target_color, false),
            PRED_SEKI => self.live_t != 0,
            PRED_SEM_WIN => self.live_t == 0 && self.any_live_pass_alive(self.own_color, true),
            _ => self.live_o != 0,
        }
    }

    fn real_eyes(&self, color: u8) -> Vec<u16> {
        let b = &self.board;
        let mut eyes = Vec::new();
        for p in 0..b.stones.len() {
            if b.stones[p] != EMPTY {
                continue;
            }
            if b.neighbors[p].iter().any(|&n| b.stones[n as usize] != color) {
                continue;
            }
            let (x, y) = ((p % b.w) as i32, (p / b.w) as i32);
            let mut diags = 0;
            let mut bad = 0;
            for (dx, dy) in [(-1, -1), (-1, 1), (1, -1), (1, 1)] {
                let (nx, ny) = (x + dx, y + dy);
                if nx >= 0 && nx < b.w as i32 && ny >= 0 && ny < b.h as i32 {
                    diags += 1;
                    if b.stones[(ny as usize) * b.w + nx as usize] == opponent(color) {
                        bad += 1;
                    }
                }
            }
            let limit = if diags == 4 { 2 } else { 1 };
            if bad < limit {
                eyes.push(p as u16);
            }
        }
        eyes
    }

    fn chain_points_of(&mut self, p: usize) -> Vec<u16> {
        self.buf.epoch += 2;
        let epoch = self.buf.epoch;
        self.board.chain(p, &mut self.buf.stones, &mut self.buf.libs, &mut self.buf.mark, epoch);
        self.buf.stones.clone()
    }

    fn adjudicate_cycle(&mut self, pred: u8, since: usize) -> bool {
        self.taint_any = true;
        let cycle_len = self.path_moves.len() - since;
        let single = cycle_len >= 4
            && (since..self.path_moves.len()).all(|i| {
                let (pt, ref caps) = self.path_moves[i];
                pt >= 0 && caps.len() == 1
            });
        if single {
            let mut pairs: Vec<(u16, u16)> = Vec::new();
            for i in since..self.path_moves.len() {
                let (pt, ref caps) = self.path_moves[i];
                let a = (pt as u16).min(caps[0]);
                let b = (pt as u16).max(caps[0]);
                if !pairs.contains(&(a, b)) {
                    pairs.push((a, b));
                }
            }
            if pairs.len() == 2 {
                // 両コウ: 閉形式裁定（§4.6.1）
                let t_eyes = self.real_eyes(self.target_color);
                let mut target_chain_pts: Vec<u16> = Vec::new();
                let t_live: Vec<u16> = self
                    .t_origin
                    .iter()
                    .cloned()
                    .filter(|&p| self.live_t & self.t_bit[p as usize] != 0)
                    .collect();
                for p in t_live {
                    if !target_chain_pts.contains(&p) {
                        let pts = self.chain_points_of(p as usize);
                        for q in pts {
                            if !target_chain_pts.contains(&q) {
                                target_chain_pts.push(q);
                            }
                        }
                    }
                }
                let t_eye_count = t_eyes
                    .iter()
                    .filter(|&&e| {
                        self.board.neighbors[e as usize].iter().any(|&n| target_chain_pts.contains(&n))
                    })
                    .count();
                let mut ko_points: Vec<u16> = Vec::new();
                for (a, b) in &pairs {
                    ko_points.push(*a);
                    ko_points.push(*b);
                }
                let a_color = self.attacker_color;
                let a_eyes = self.real_eyes(a_color);
                let mut a_near: Vec<u16> = Vec::new();
                for &kp in &ko_points {
                    for i in 0..self.board.neighbors[kp as usize].len() {
                        let n = self.board.neighbors[kp as usize][i];
                        if self.board.stones[n as usize] == a_color && !a_near.contains(&n) {
                            let pts = self.chain_points_of(n as usize);
                            for q in pts {
                                if !a_near.contains(&q) {
                                    a_near.push(q);
                                }
                            }
                        }
                    }
                }
                let a_eye_count = a_eyes
                    .iter()
                    .filter(|&&e| self.board.neighbors[e as usize].iter().any(|&n| a_near.contains(&n)))
                    .count();
                let verdict = if t_eye_count >= 1 && a_eye_count >= 1 {
                    2 // SEKI
                } else if t_eye_count >= 1 {
                    1 // ALIVE
                } else {
                    0 // DEAD
                };
                return match pred {
                    PRED_ALIVE => verdict == 1,
                    PRED_SEKI => verdict >= 1,
                    PRED_SEM_WIN => verdict == 0 && self.live_o != 0,
                    _ => self.live_o != 0,
                };
            }
        }
        // 基本則: 反復は生かす側の勝ち（§4.6）
        match pred {
            PRED_ALIVE | PRED_SEKI => true,
            PRED_SEM_WIN => false,
            _ => self.live_o != 0,
        }
    }

    const MAX_PLY: u32 = 1024; // 再帰の深さ上限（スタック保護。超過は打ち切り=安全側）

    fn check_limits(&self) -> Result<(), Timeout> {
        if self.nodes > self.node_limit {
            return Err(Timeout);
        }
        if let Some(d) = self.deadline {
            if self.nodes % 4096 == 0 && Instant::now() > d {
                return Err(Timeout);
            }
        }
        Ok(())
    }

    fn position_key(&self, to_play: u8, ban: i32, pass_count: u8) -> PosKey {
        let extra = mix64(to_play as u64)
            ^ mix64(0x9E37 ^ (ban + 2) as u64).rotate_left(17)
            ^ mix64(0xA5A5 ^ pass_count.min(1) as u64).rotate_left(31)
            ^ mix64(self.live_t).rotate_left(7)
            ^ mix64(self.live_o ^ 0xC3C3).rotate_left(43);
        (self.board.h1 ^ extra, self.board.h2 ^ mix64(extra))
    }

    fn ordered_moves(&mut self, to_play: u8) -> Vec<u16> {
        // §6.2 の順序付け（厳密性に影響しない）。呼吸点は 3 で打ち切る capped flood
        self.cl_gen = self.cl_gen.wrapping_add(1);
        let mut scored: Vec<(i64, u16)> = Vec::with_capacity(self.region.len());
        for i in 0..self.region.len() {
            let p = self.region[i];
            if self.board.stones[p as usize] != EMPTY {
                continue;
            }
            let mut score = self.hist_order[p as usize][to_play as usize] as i64;
            let mut near = false;
            for k in 0..self.board.neighbors[p as usize].len() {
                let nb = self.board.neighbors[p as usize][k];
                let v = self.board.stones[nb as usize];
                if v == EMPTY {
                    continue;
                }
                near = true;
                let (libs, size) = self.capped_chain_info(nb as usize, 3);
                if libs == 1 {
                    score += if v != to_play { 1000 + 10 * size as i64 } else { 500 };
                } else if libs == 2 {
                    score += 50;
                }
            }
            if near {
                score += 10;
            }
            scored.push((score, p));
        }
        scored.sort_by_key(|s| -s.0);
        scored.into_iter().map(|s| s.1).collect()
    }

    fn play(&mut self, p: usize, color: u8) -> Option<(crate::board::Undo, i32, u64, u64)> {
        let u = match self.board.try_play(p, color, &mut self.buf) {
            None => return None,
            Some(u) => u,
        };
        let mut new_ban: i32 = -1;
        if u.captured.len() == 1 {
            self.buf.epoch += 2;
            let epoch = self.buf.epoch;
            self.board.chain(p, &mut self.buf.stones, &mut self.buf.libs, &mut self.buf.mark, epoch);
            if self.buf.stones.len() == 1 && self.buf.libs.len() == 1 && self.buf.libs[0] == u.captured[0] {
                new_ban = u.captured[0] as i32;
            }
        }
        let mut removed_t = 0u64;
        let mut removed_o = 0u64;
        for &q in &u.captured {
            let tb = self.t_bit[q as usize];
            if self.live_t & tb != 0 {
                removed_t |= tb;
            }
            let ob = self.o_bit[q as usize];
            if self.live_o & ob != 0 {
                removed_o |= ob;
            }
        }
        self.live_t &= !removed_t;
        self.live_o &= !removed_o;
        Some((u, new_ban, removed_t, removed_o))
    }

    fn unplay(&mut self, u: &crate::board::Undo, removed_t: u64, removed_o: u64) {
        self.live_t |= removed_t;
        self.live_o |= removed_o;
        self.board.undo(u);
    }

    /// (value, taint, dep) を返す。Python の _search と同一。
    pub fn search(
        &mut self,
        pred: u8,
        komaster: u8,
        budget: i8,
        to_play: u8,
        ban: i32,
        pass_count: u8,
        ply: u32,
    ) -> Result<(bool, bool, u32), Timeout> {
        self.nodes += 1;
        self.check_limits()?;
        if ply > Self::MAX_PLY {
            return Err(Timeout);
        }
        if pass_count >= 2 {
            let v = self.two_pass_eval(pred);
            return Ok((v, false, INF_DEP));
        }
        let key = self.position_key(to_play, ban, pass_count);
        if let Some(&seen_ply) = self.history.get(&key) {
            let v = self.adjudicate_cycle(pred, seen_ply as usize);
            return Ok((v, true, seen_ply));
        }
        let tt_key = (key.0, key.1, pred, komaster, budget);
        if let Some(&(v, t)) = self.tt.get(&tt_key) {
            return Ok((v, t, INF_DEP));
        }
        // 終端（早期打ち切り）は TT に載らないので TT ミス後に判定すれば十分
        if let Some(v) = self.early_eval(pred) {
            return Ok((v, false, INF_DEP));
        }
        self.history.insert(key, ply);
        let maximizer = to_play == self.beneficiary(pred);
        let mut value = !maximizer;
        let mut taint_acc = false;
        let mut dep_acc = INF_DEP;
        let mut decided = false;
        let moves = self.ordered_moves(to_play);
        let result = (|| -> Result<(), Timeout> {
            for &p in &moves {
                let mut child_budget = budget;
                if p as i32 == ban {
                    if komaster == to_play && budget != 0 {
                        child_budget = if budget < 0 { -1 } else { budget - 1 };
                    } else {
                        continue; // コウ禁止
                    }
                }
                let played = self.play(p as usize, to_play);
                let (u, new_ban, rt, ro) = match played {
                    None => continue,
                    Some(x) => x,
                };
                self.path_moves.push((p as i32, u.captured.clone()));
                let res = self.search(pred, komaster, child_budget, opponent(to_play), new_ban, 0, ply + 1);
                self.path_moves.pop();
                self.unplay(&u, rt, ro);
                let (r, t, d) = res?;
                if r == maximizer {
                    value = r;
                    taint_acc = t;
                    dep_acc = d;
                    decided = true;
                    self.hist_order[p as usize][to_play as usize] += 1;
                    return Ok(());
                }
                taint_acc |= t;
                dep_acc = dep_acc.min(d);
            }
            // パス（§4.8）
            self.path_moves.push((PASS, Vec::new()));
            let res = self.search(pred, komaster, budget, opponent(to_play), -1, pass_count + 1, ply + 1);
            self.path_moves.pop();
            let (r, t, d) = res?;
            if r == maximizer {
                value = r;
                taint_acc = t;
                dep_acc = d;
            } else {
                taint_acc |= t;
                dep_acc = dep_acc.min(d);
            }
            Ok(())
        })();
        self.history.remove(&key);
        result?;
        let _ = decided;
        if dep_acc >= ply {
            self.tt.insert(tt_key, (value, taint_acc));
        }
        Ok((value, taint_acc, dep_acc))
    }

    // ---------- df-pn（証明数探索。§6.1）----------
    //
    // pn は常に「述語が True」の証明数（ノード種別で向きは変えない）。
    // beneficiary の手番 = OR ノード（pn = min 子pn / dn = Σ 子dn）、相手 = AND。
    // 反復終端は DFS と同じ裁定（§4.6）。証明/反証の TT 保存は経路非依存のときだけ
    //（GHI 対策）。バウンドは探索順序にしか効かないので常に保存してよい。

    const PN_INF: u64 = 1 << 40;

    fn dfpn_terminal(&mut self, pred: u8, pass_count: u8, deep: bool) -> Option<bool> {
        if pass_count >= 2 {
            return Some(self.two_pass_eval(pred)); // 連続パス終端の裁定は常に厳密（Benson 込み）
        }
        self.early_eval_at(pred, deep)
    }

    /// mv（PASS 含む）を適用して path_moves を積む。非合法手は None
    fn dfpn_apply(&mut self, mv: i32, to_play: u8) -> Option<(crate::board::Undo, i32, u64, u64)> {
        if mv == PASS {
            self.path_moves.push((PASS, Vec::new()));
            return Some((crate::board::Undo { point: u16::MAX, captured: Vec::new(), captured_color: 0 }, -1, 0, 0));
        }
        let (u, new_ban, rt, ro) = self.play(mv as usize, to_play)?;
        self.path_moves.push((mv, u.captured.clone()));
        Some((u, new_ban, rt, ro))
    }

    fn dfpn_unapply(&mut self, mv: i32, u: &crate::board::Undo, rt: u64, ro: u64) {
        self.path_moves.pop();
        if mv != PASS {
            self.unplay(u, rt, ro);
        }
    }

    /// 子を1手進めて (pn, dn, taint, dep) を見積もる。非合法手は None
    #[allow(clippy::too_many_arguments)]
    fn dfpn_probe(
        &mut self,
        pred: u8,
        komaster: u8,
        child_budget: i8,
        to_play: u8,
        mv: i32,
        pass_count: u8,
    ) -> Result<Option<(u64, u64, bool, u32)>, Timeout> {
        let (u, new_ban, rt, ro) = match self.dfpn_apply(mv, to_play) {
            None => return Ok(None),
            Some(x) => x,
        };
        let child_pass = if mv == PASS { pass_count + 1 } else { 0 };
        let key = self.position_key(opponent(to_play), new_ban, child_pass);
        let result = if let Some(&seen_ply) = self.history.get(&key) {
            let v = self.adjudicate_cycle(pred, seen_ply as usize);
            if v {
                (0, Self::PN_INF, true, seen_ply)
            } else {
                (Self::PN_INF, 0, true, seen_ply)
            }
        } else if let Some(&(pn, dn, t, _bm)) = self.pn_tt.get(&(key.0, key.1, pred, komaster, child_budget)) {
            (pn, dn, t, INF_DEP)
        } else if let Some(v) = self.dfpn_terminal(pred, child_pass, false) {
            if v {
                (0, Self::PN_INF, false, INF_DEP)
            } else {
                (Self::PN_INF, 0, false, INF_DEP)
            }
        } else {
            (1, 1, false, INF_DEP)
        };
        self.dfpn_unapply(mv, &u, rt, ro);
        Ok(Some(result))
    }

    #[allow(clippy::too_many_arguments)]
    fn dfpn_mid(
        &mut self,
        pred: u8,
        komaster: u8,
        budget: i8,
        to_play: u8,
        ban: i32,
        pass_count: u8,
        ply: u32,
        pn_th: u64,
        dn_th: u64,
    ) -> Result<(u64, u64, bool, u32), Timeout> {
        self.nodes += 1;
        self.check_limits()?;
        if ply > Self::MAX_PLY {
            return Err(Timeout);
        }
        let key = self.position_key(to_play, ban, pass_count);
        if let Some(&seen_ply) = self.history.get(&key) {
            let v = self.adjudicate_cycle(pred, seen_ply as usize);
            return Ok(if v { (0, Self::PN_INF, true, seen_ply) } else { (Self::PN_INF, 0, true, seen_ply) });
        }
        let tt_key = (key.0, key.1, pred, komaster, budget);
        if let Some(&(pn, dn, taint, _bm)) = self.pn_tt.get(&tt_key) {
            if pn == 0 || dn == 0 || pn >= pn_th || dn >= dn_th {
                return Ok((pn, dn, taint, INF_DEP));
            }
        }
        if let Some(v) = self.dfpn_terminal(pred, pass_count, true) {
            return Ok(if v { (0, Self::PN_INF, false, INF_DEP) } else { (Self::PN_INF, 0, false, INF_DEP) });
        }
        let maximizer = to_play == self.beneficiary(pred);
        self.history.insert(key, ply);
        let moves = self.ordered_moves(to_play);
        let mut children: Vec<(i32, i8)> = Vec::with_capacity(moves.len() + 1);
        for &p in &moves {
            let mut child_budget = budget;
            if p as i32 == ban {
                if komaster == to_play && budget != 0 {
                    child_budget = if budget < 0 { -1 } else { budget - 1 };
                } else {
                    continue; // コウ禁止
                }
            }
            children.push((p as i32, child_budget));
        }
        children.push((PASS, budget));
        let result = (|| -> Result<(u64, u64, bool, u32, i32), Timeout> {
            // 子の状態は最初に1回だけ probe し、以後は再帰の戻り値で更新する。
            // GHI 抑制で TT に載らなかった証明も戻り値経由で親に見える（probe 依存だと
            // 「解けているのに TT ミスで (1,1) のまま」の子を無限に選び直すライブロックになる）。
            // taint / dep は「値を決めた子」だけから取る（全子から min すると コウ近傍の
            // 証明が軒並み TT 抑制になり、再展開の連鎖で探索が爆発する）
            let mut states: Vec<(u64, u64, bool, u32)> = Vec::with_capacity(children.len());
            for ci in 0..children.len() {
                let (mv, cb) = children[ci];
                match self.dfpn_probe(pred, komaster, cb, to_play, mv, pass_count)? {
                    None => states.push((u64::MAX, u64::MAX, false, INF_DEP)), // 非合法: 選択対象外
                    Some((cpn, cdn, ct, cd)) => states.push((cpn, cdn, ct, cd)),
                }
            }
            loop {
                let mut pn_sum: u64 = 0;
                let mut dn_sum: u64 = 0;
                let mut pn_min = u64::MAX;
                let mut dn_min = u64::MAX;
                for &(cpn, cdn, _t, _d) in &states {
                    if cpn == u64::MAX && cdn == u64::MAX {
                        continue;
                    }
                    pn_sum = (pn_sum + cpn.min(Self::PN_INF)).min(Self::PN_INF);
                    dn_sum = (dn_sum + cdn.min(Self::PN_INF)).min(Self::PN_INF);
                    pn_min = pn_min.min(cpn);
                    dn_min = dn_min.min(cdn);
                }
                if pn_min == u64::MAX {
                    return Ok((Self::PN_INF, 0, false, INF_DEP, -2)); // 子が無い（起きないはず）
                }
                let (pn, dn) = if maximizer { (pn_min, dn_sum) } else { (pn_sum, dn_min) };
                if pn == 0 || dn == 0 {
                    // 値を決めた子から taint / dep / best_move を取る:
                    //   OR の証明 / AND の反証 = 決め手の子1つ。OR の反証 / AND の証明 = 全子
                    let proved_true = pn == 0;
                    let single = (maximizer && proved_true) || (!maximizer && !proved_true);
                    let mut taint = false;
                    let mut dep = INF_DEP;
                    let mut best_mv: i32 = -2;
                    for (i2, &(cpn, cdn, ct, cd)) in states.iter().enumerate() {
                        if cpn == u64::MAX && cdn == u64::MAX {
                            continue;
                        }
                        if single {
                            let decisive = if proved_true { cpn == 0 } else { cdn == 0 };
                            if decisive {
                                taint = ct;
                                dep = cd;
                                best_mv = children[i2].0; // 決め手の子 = 証明ストアの即答手（§6.6）
                                break;
                            }
                        } else {
                            taint |= ct;
                            dep = dep.min(cd);
                        }
                    }
                    return Ok((pn, dn, taint, dep, best_mv));
                }
                if pn >= pn_th || dn >= dn_th {
                    return Ok((pn, dn, false, INF_DEP, -2)); // バウンドは値でないので依存も無し
                }
                // 最良の子（OR: pn 最小 / AND: dn 最小）と次点
                let mut bi = usize::MAX;
                let mut bk = u64::MAX;
                let mut second = u64::MAX;
                for (i2, &(cpn, cdn, _t, _d)) in states.iter().enumerate() {
                    if cpn == u64::MAX && cdn == u64::MAX {
                        continue;
                    }
                    let k = if maximizer { cpn } else { cdn };
                    if k < bk {
                        second = bk;
                        bk = k;
                        bi = i2;
                    } else if k < second {
                        second = k;
                    }
                }
                let (mv, cb) = children[bi];
                let eps = |x: u64| x.saturating_add(x / 4).saturating_add(1).min(Self::PN_INF); // 1+ε trick
                let (c_pn_th, c_dn_th) = if maximizer {
                    (
                        pn_th.min(eps(second)),
                        dn_th.saturating_sub(dn_sum).saturating_add(states[bi].1).min(Self::PN_INF),
                    )
                } else {
                    (
                        pn_th.saturating_sub(pn_sum).saturating_add(states[bi].0).min(Self::PN_INF),
                        dn_th.min(eps(second)),
                    )
                };
                let (u, new_ban, rt, ro) = self.dfpn_apply(mv, to_play).expect("probe passed but apply failed");
                let child_pass = if mv == PASS { pass_count + 1 } else { 0 };
                let sub = self.dfpn_mid(
                    pred,
                    komaster,
                    cb,
                    opponent(to_play),
                    new_ban,
                    child_pass,
                    ply + 1,
                    c_pn_th,
                    c_dn_th,
                );
                self.dfpn_unapply(mv, &u, rt, ro);
                let (cpn2, cdn2, t, d) = sub?;
                states[bi] = (cpn2, cdn2, t, d);
            }
        })();
        self.history.remove(&key);
        let (pn, dn, taint, dep, best_mv) = result?;
        if pn == 0 || dn == 0 {
            if dep >= ply {
                self.pn_tt.insert(tt_key, (pn, dn, taint, best_mv)); // 証明/反証は経路非依存のときだけ保存
            }
        } else {
            self.pn_tt.insert(tt_key, (pn, dn, taint, -2)); // バウンドは順序にしか効かないので常に保存
        }
        Ok((pn, dn, taint, dep))
    }

    /// 証明ストア照会（§6.6 応答フロー）: 現 root の (pred, komaster, budget) が
    /// want どおりに証明済みなら決め手の手を返す（解析ゼロ）。
    pub fn probe_store(&mut self, pred: u8, komaster: u8, budget: i8, want: bool) -> Option<i32> {
        let key = self.position_key(self.root_to_play, self.root_ban, 0);
        let &(pn, dn, _t, best_mv) = self.pn_tt.get(&(key.0, key.1, pred, komaster, budget))?;
        let proven = if want { pn == 0 } else { dn == 0 };
        if proven && best_mv != -2 {
            Some(best_mv)
        } else {
            None
        }
    }

    /// df-pn のエントリ: 述語の真偽が確定するまで回す
    #[allow(clippy::too_many_arguments)]
    pub fn dfpn_value(
        &mut self,
        pred: u8,
        komaster: u8,
        budget: i8,
        to_play: u8,
        ban: i32,
        pass_count: u8,
        ply: u32,
    ) -> Result<(bool, bool), Timeout> {
        if let Some(v) = self.dfpn_terminal(pred, pass_count, true) {
            return Ok((v, false));
        }
        loop {
            let (pn, dn, taint, _dep) = self.dfpn_mid(
                pred,
                komaster,
                budget,
                to_play,
                ban,
                pass_count,
                ply,
                Self::PN_INF - 1,
                Self::PN_INF - 1,
            )?;
            if pn == 0 {
                return Ok((true, taint));
            }
            if dn == 0 {
                return Ok((false, taint));
            }
            // GHI 抑制で証明が保存されず (pn, dn) が有限のまま返ることがある → 回し直す
            self.check_limits()?;
        }
    }

    /// root で first_move（-2 = なし、-1 = パス、それ以外 = 点）を打ってから解く
    pub fn solve_after(
        &mut self,
        first_move: i32,
        pred: u8,
        komaster: u8,
        budget: i8,
    ) -> Result<(bool, bool), Timeout> {
        self.history.clear();
        self.path_moves.clear();
        let to_play = self.root_to_play;
        if first_move == -2 {
            let ban = self.root_ban;
            return self.value_here(pred, komaster, budget, to_play, ban, 0, 0);
        }
        if first_move == PASS {
            self.path_moves.push((PASS, Vec::new()));
            let res = self.value_here(pred, komaster, budget, opponent(to_play), -1, 1, 1);
            self.path_moves.pop();
            return res;
        }
        let played = self.play(first_move as usize, to_play).expect("illegal root move");
        let (u, new_ban, rt, ro) = played;
        self.path_moves.push((first_move, u.captured.clone()));
        let res = self.value_here(pred, komaster, budget, opponent(to_play), new_ban, 0, 1);
        self.path_moves.pop();
        self.unplay(&u, rt, ro);
        res
    }

    fn opt_gate(&mut self, pred: u8, komaster: u8, budget: i8, to_play: u8, ban: i32) -> Result<bool, Timeout> {
        let saved_hist = std::mem::take(&mut self.history);
        let saved_moves = std::mem::take(&mut self.path_moves);
        let res = self.value_here(pred, komaster, budget, to_play, ban, 0, 0);
        self.history = saved_hist;
        self.path_moves = saved_moves;
        let (v, _t) = res?;
        Ok(v)
    }

    const BIG: u32 = 1_000_000;

    fn opt(
        &mut self,
        pred: u8,
        komaster: u8,
        budget: i8,
        want: bool,
        to_play: u8,
        ban: i32,
        pass_count: u8,
        history: &mut FxMap<PosKey, bool>,
    ) -> Result<(u32, u32, Vec<i32>, bool), Timeout> {
        self.opt_nodes += 1;
        if self.opt_nodes > self.opt_node_limit {
            return Err(Timeout);
        }
        if history.len() as u32 > Self::MAX_PLY {
            return Err(Timeout);
        }
        self.check_limits()?;
        if let Some(ev) = self.early_eval(pred) {
            return Ok(if ev == want { (0, 0, Vec::new(), true) } else { (Self::BIG, Self::BIG, Vec::new(), true) });
        }
        if pass_count >= 2 {
            let v = self.two_pass_eval(pred);
            return Ok(if v == want { (0, 0, Vec::new(), true) } else { (Self::BIG, Self::BIG, Vec::new(), true) });
        }
        let key = self.position_key(to_play, ban, pass_count);
        if history.contains_key(&key) {
            return Ok((0, 0, Vec::new(), false)); // 反復＝クラスは裁定済み（経路依存なので memo しない）
        }
        let memo_key = (key.0, key.1, pred, komaster, budget, want);
        if let Some(hit) = self.opt_memo.get(&memo_key) {
            return Ok((hit.0, hit.1, hit.2.clone(), true));
        }
        history.insert(key, true);
        let solver_side = self.root_to_play;
        let mut best: Option<(u32, u32, Vec<i32>)> = None;
        let mut clean_acc = true;
        let moves = self.ordered_moves(to_play);
        let result = (|| -> Result<(), Timeout> {
            if to_play == solver_side {
                for &p in &moves {
                    let mut child_budget = budget;
                    if p as i32 == ban {
                        if komaster == to_play && budget != 0 {
                            child_budget = if budget < 0 { -1 } else { budget - 1 };
                        } else {
                            continue;
                        }
                    }
                    let played = self.play(p as usize, to_play);
                    let (u, new_ban, rt, ro) = match played {
                        None => continue,
                        Some(x) => x,
                    };
                    let gate = self.opt_gate(pred, komaster, child_budget, opponent(to_play), new_ban);
                    match gate {
                        Ok(g) if g == want => {
                            let sub = self.opt(pred, komaster, child_budget, want, opponent(to_play), new_ban, 0, history);
                            match sub {
                                Ok((plies, mat, line, clean)) => {
                                    clean_acc &= clean;
                                    let cand_key = (plies.saturating_add(1), mat);
                                    if best.is_none() || cand_key < (best.as_ref().unwrap().0, best.as_ref().unwrap().1) {
                                        let mut l = vec![p as i32];
                                        l.extend(line);
                                        best = Some((cand_key.0, cand_key.1, l));
                                    }
                                    self.unplay(&u, rt, ro);
                                }
                                Err(e) => {
                                    self.unplay(&u, rt, ro);
                                    return Err(e);
                                }
                            }
                        }
                        Ok(_) => {
                            self.unplay(&u, rt, ro);
                        }
                        Err(e) => {
                            self.unplay(&u, rt, ro);
                            return Err(e);
                        }
                    }
                }
                // パス
                if self.opt_gate(pred, komaster, budget, opponent(to_play), -1)? == want {
                    let (plies, mat, line, clean) =
                        self.opt(pred, komaster, budget, want, opponent(to_play), -1, pass_count + 1, history)?;
                    clean_acc &= clean;
                    if best.is_none() || (plies, mat) < (best.as_ref().unwrap().0, best.as_ref().unwrap().1) {
                        let mut l = vec![PASS];
                        l.extend(line);
                        best = Some((plies, mat, l));
                    }
                }
            } else {
                // 相手は (plies, material) を最大化。盤上に合法手がある限りパスしない（§4.2.1）
                for &p in &moves {
                    let mut child_budget = budget;
                    if p as i32 == ban {
                        if komaster == to_play && budget != 0 {
                            child_budget = if budget < 0 { -1 } else { budget - 1 };
                        } else {
                            continue;
                        }
                    }
                    let played = self.play(p as usize, to_play);
                    let (u, new_ban, rt, ro) = match played {
                        None => continue,
                        Some(x) => x,
                    };
                    let mat_edge = u.captured.len() as u32; // 相手の取りは常に解く側の石
                    let sub = self.opt(pred, komaster, child_budget, want, opponent(to_play), new_ban, 0, history);
                    match sub {
                        Ok((plies, mat, line, clean)) => {
                            clean_acc &= clean;
                            let cand = (plies, mat.saturating_add(mat_edge));
                            if best.is_none() || cand > (best.as_ref().unwrap().0, best.as_ref().unwrap().1) {
                                let mut l = vec![p as i32];
                                l.extend(line);
                                best = Some((cand.0, cand.1, l));
                            }
                            self.unplay(&u, rt, ro);
                        }
                        Err(e) => {
                            self.unplay(&u, rt, ro);
                            return Err(e);
                        }
                    }
                }
                if best.is_none() {
                    let (plies, mat, line, clean) =
                        self.opt(pred, komaster, budget, want, opponent(to_play), -1, pass_count + 1, history)?;
                    clean_acc &= clean;
                    let mut l = vec![PASS];
                    l.extend(line);
                    best = Some((plies, mat, l));
                }
            }
            Ok(())
        })();
        history.remove(&key);
        result?;
        let (plies, mat, line) = best.unwrap_or((Self::BIG, Self::BIG, Vec::new()));
        if clean_acc {
            self.opt_memo.insert(memo_key, (plies, mat, line.clone()));
        }
        Ok((plies, mat, line, clean_acc))
    }

    /// root の first_move 後の本手順を (plies, material) 最小で確定（Python の _optimize_after）
    pub fn optimize_after(
        &mut self,
        first_move: i32,
        pred: u8,
        komaster: u8,
        budget: i8,
        want: bool,
    ) -> Result<(u32, u32, Vec<i32>), Timeout> {
        self.opt_nodes = 0;
        self.opt_memo.clear();
        let to_play = self.root_to_play;
        let mut history = FxMap::default();
        if first_move == PASS {
            let (plies, mat, line, _clean) =
                self.opt(pred, komaster, budget, want, opponent(to_play), -1, 1, &mut history)?;
            return Ok((plies, mat, line));
        }
        let played = self.play(first_move as usize, to_play).expect("illegal root move");
        let (u, new_ban, rt, ro) = played;
        let res = self.opt(pred, komaster, budget, want, opponent(to_play), new_ban, 0, &mut history);
        self.unplay(&u, rt, ro);
        let (plies, mat, line, _clean) = res?;
        Ok((plies, mat, line))
    }

    pub fn legal_root_moves(&mut self) -> Vec<u16> {
        let to_play = self.root_to_play;
        let moves = self.ordered_moves(to_play);
        let mut result = Vec::new();
        for &p in &moves {
            if let Some((u, _ban, rt, ro)) = self.play(p as usize, to_play) {
                self.unplay(&u, rt, ro);
                result.push(p);
            }
        }
        result
    }
}
