//! 盤面機構: 着手・取り・自殺手・連/呼吸点・Benson pass-alive。
//! Python 参照実装（katrain/core/tsumego_solver/board.py）と同一の意味論。

pub const EMPTY: u8 = 0;
pub const BLACK: u8 = 1;
pub const WHITE: u8 = 2;

pub fn opponent(c: u8) -> u8 {
    if c == BLACK {
        WHITE
    } else {
        BLACK
    }
}

pub struct Undo {
    pub point: u16,
    pub captured: Vec<u16>,
    pub captured_color: u8,
}

pub struct Board {
    pub w: usize,
    pub h: usize,
    pub stones: Vec<u8>,
    pub neighbors: Vec<Vec<u16>>,
    // Zobrist（u64 x 2 で衝突を実用上排除）
    pub zob: Vec<[[u64; 3]; 2]>,
    pub h1: u64,
    pub h2: u64,
}

fn splitmix(state: &mut u64) -> u64 {
    *state = state.wrapping_add(0x9E3779B97F4A7C15);
    let mut z = *state;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
    z ^ (z >> 31)
}

impl Board {
    pub fn new(w: usize, h: usize) -> Board {
        let n = w * h;
        let mut neighbors = Vec::with_capacity(n);
        for p in 0..n {
            let (x, y) = (p % w, p / w);
            let mut ns = Vec::with_capacity(4);
            if x > 0 {
                ns.push((p - 1) as u16);
            }
            if x < w - 1 {
                ns.push((p + 1) as u16);
            }
            if y > 0 {
                ns.push((p - w) as u16);
            }
            if y < h - 1 {
                ns.push((p + w) as u16);
            }
            neighbors.push(ns);
        }
        let mut seed = 0x1234_5678_9ABC_DEFu64;
        let mut zob = Vec::with_capacity(n);
        for _ in 0..n {
            let mut e = [[0u64; 3]; 2];
            for k in 0..2 {
                for c in 1..3 {
                    e[k][c] = splitmix(&mut seed);
                }
            }
            zob.push(e);
        }
        Board { w, h, stones: vec![EMPTY; n], neighbors, zob, h1: 0, h2: 0 }
    }

    pub fn set_stone(&mut self, p: usize, color: u8) {
        let old = self.stones[p];
        if old != EMPTY {
            self.h1 ^= self.zob[p][0][old as usize];
            self.h2 ^= self.zob[p][1][old as usize];
        }
        self.stones[p] = color;
        if color != EMPTY {
            self.h1 ^= self.zob[p][0][color as usize];
            self.h2 ^= self.zob[p][1][color as usize];
        }
    }

    /// p の石が属する連の (石リスト, 呼吸点集合ビット)。visited バッファを使い回す
    pub fn chain(&self, p: usize, stones_out: &mut Vec<u16>, libs_out: &mut Vec<u16>, mark: &mut [u32], epoch: u32) {
        stones_out.clear();
        libs_out.clear();
        let color = self.stones[p];
        debug_assert!(color != EMPTY);
        let mut stack = vec![p as u16];
        mark[p] = epoch;
        while let Some(q) = stack.pop() {
            stones_out.push(q);
            for &n in &self.neighbors[q as usize] {
                let v = self.stones[n as usize];
                if v == EMPTY {
                    if mark[n as usize] != epoch + 1 {
                        // 呼吸点は epoch+1 でマーク（石の epoch と区別）
                        mark[n as usize] = epoch + 1;
                        libs_out.push(n);
                    }
                } else if v == color && mark[n as usize] != epoch {
                    mark[n as usize] = epoch;
                    stack.push(n);
                }
            }
        }
    }

    pub fn liberties_count(&self, p: usize, buf: &mut ChainBuf) -> usize {
        buf.epoch += 2;
        self.chain(p, &mut buf.stones, &mut buf.libs, &mut buf.mark, buf.epoch);
        buf.libs.len()
    }

    /// 着手（自殺手なら None）。コウ禁は呼び出し側。
    pub fn try_play(&mut self, p: usize, color: u8, buf: &mut ChainBuf) -> Option<Undo> {
        if self.stones[p] != EMPTY {
            return None;
        }
        let opp = opponent(color);
        self.set_stone(p, color);
        let mut captured: Vec<u16> = Vec::new();
        for i in 0..self.neighbors[p].len() {
            let n = self.neighbors[p][i] as usize;
            if self.stones[n] == opp {
                buf.epoch += 2;
                self.chain(n, &mut buf.stones, &mut buf.libs, &mut buf.mark, buf.epoch);
                if buf.libs.is_empty() {
                    for &q in buf.stones.iter() {
                        if self.stones[q as usize] == opp {
                            self.set_stone(q as usize, EMPTY);
                            captured.push(q);
                        }
                    }
                }
            }
        }
        if captured.is_empty() {
            buf.epoch += 2;
            self.chain(p, &mut buf.stones, &mut buf.libs, &mut buf.mark, buf.epoch);
            if buf.libs.is_empty() {
                self.set_stone(p, EMPTY);
                return None; // 自殺手
            }
        }
        Some(Undo { point: p as u16, captured, captured_color: opp })
    }

    pub fn undo(&mut self, u: &Undo) {
        for &q in &u.captured {
            self.set_stone(q as usize, u.captured_color);
        }
        self.set_stone(u.point as usize, EMPTY);
    }

    /// Benson pass-alive: color の pass-alive な石の点集合（ビットセット）
    pub fn benson_pass_alive(&self, color: u8) -> Vec<u64> {
        let n = self.w * self.h;
        let mut chain_id = vec![usize::MAX; n];
        let mut chains: Vec<(Vec<u16>, Vec<u64>)> = Vec::new(); // (stones, lib bitset)
        let words = (n + 63) / 64;
        let mut mark = vec![0u32; n];
        let mut epoch = 0u32;
        let mut st = Vec::new();
        let mut li = Vec::new();
        for p in 0..n {
            if self.stones[p] != color || chain_id[p] != usize::MAX {
                continue;
            }
            epoch += 2;
            self.chain(p, &mut st, &mut li, &mut mark, epoch);
            let id = chains.len();
            let mut libs = vec![0u64; words];
            for &q in &li {
                libs[q as usize / 64] |= 1u64 << (q % 64);
            }
            for &q in &st {
                chain_id[q as usize] = id;
            }
            chains.push((st.clone(), libs));
        }
        if chains.is_empty() {
            return vec![0u64; words];
        }
        // color 以外の点の連結成分
        struct Region {
            empties: Vec<u16>,
            adj: Vec<usize>,
        }
        let mut regions: Vec<Region> = Vec::new();
        let mut seen = vec![false; n];
        for p in 0..n {
            if self.stones[p] == color || seen[p] {
                continue;
            }
            let mut comp = vec![p as u16];
            seen[p] = true;
            let mut stack = vec![p as u16];
            let mut empties = Vec::new();
            let mut adj: Vec<usize> = Vec::new();
            while let Some(q) = stack.pop() {
                if self.stones[q as usize] == EMPTY {
                    empties.push(q);
                }
                for &m in &self.neighbors[q as usize] {
                    if self.stones[m as usize] == color {
                        let id = chain_id[m as usize];
                        if !adj.contains(&id) {
                            adj.push(id);
                        }
                    } else if !seen[m as usize] {
                        seen[m as usize] = true;
                        comp.push(m);
                        stack.push(m);
                    }
                }
            }
            regions.push(Region { empties, adj });
        }
        let mut alive_chain = vec![true; chains.len()];
        let mut alive_region = vec![true; regions.len()];
        loop {
            let mut changed = false;
            for ci in 0..chains.len() {
                if !alive_chain[ci] {
                    continue;
                }
                let mut vital = 0;
                for (ri, r) in regions.iter().enumerate() {
                    if !alive_region[ri] || !r.adj.contains(&ci) || r.empties.is_empty() {
                        continue;
                    }
                    let all_libs = r
                        .empties
                        .iter()
                        .all(|&e| chains[ci].1[e as usize / 64] & (1u64 << (e % 64)) != 0);
                    if all_libs {
                        vital += 1;
                    }
                }
                if vital < 2 {
                    alive_chain[ci] = false;
                    changed = true;
                }
            }
            for (ri, r) in regions.iter().enumerate() {
                if alive_region[ri] && !r.adj.iter().all(|&ci| alive_chain[ci]) {
                    alive_region[ri] = false;
                    changed = true;
                }
            }
            if !changed {
                break;
            }
        }
        let mut result = vec![0u64; words];
        for (ci, ch) in chains.iter().enumerate() {
            if alive_chain[ci] {
                for &q in &ch.0 {
                    result[q as usize / 64] |= 1u64 << (q % 64);
                }
            }
        }
        result
    }
}

pub struct ChainBuf {
    pub stones: Vec<u16>,
    pub libs: Vec<u16>,
    pub mark: Vec<u32>,
    pub epoch: u32,
}

impl ChainBuf {
    pub fn new(n: usize) -> ChainBuf {
        ChainBuf { stones: Vec::with_capacity(64), libs: Vec::with_capacity(64), mark: vec![0; n], epoch: 0 }
    }
}
