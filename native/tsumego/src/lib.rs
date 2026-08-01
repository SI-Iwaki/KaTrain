//! C ABI（ctypes から呼ぶ）。JSON in / JSON out。
//!   ts_new(problem_json) -> handle (0 = エラー)
//!   ts_call(handle, request_json) -> *mut c_char（ts_free_str で解放）
//!   ts_drop(handle), ts_free_str(ptr)

mod board;
mod solver;

use board::{Board, BLACK, WHITE};
use serde::Deserialize;
use solver::{Solver, PRED_ALIVE, PRED_SEKI, PRED_SEM_SEKI, PRED_SEM_WIN};
use std::collections::HashMap;
use std::ffi::{c_char, CStr, CString};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::Mutex;
use std::time::{Duration, Instant};

static REGISTRY: Mutex<Option<HashMap<u64, Solver>>> = Mutex::new(None);
static NEXT_ID: Mutex<u64> = Mutex::new(1);

#[derive(Deserialize)]
struct ProblemIn {
    width: usize,
    height: usize,
    black: Vec<(usize, usize)>,
    white: Vec<(usize, usize)>,
    region: Vec<(usize, usize)>,
    to_play: String,
    target: Vec<(usize, usize)>,
    #[serde(default)]
    own_target: Vec<(usize, usize)>,
    target_color: String,
}

#[derive(Deserialize)]
struct RequestIn {
    op: String,
    #[serde(default)]
    pred: Option<String>,
    #[serde(default)]
    komaster: Option<String>,
    #[serde(default = "default_budget")]
    budget: i32,
    /// null = root から / "pass" 相当は -1 / それ以外は [x, y]
    #[serde(default)]
    first_move: Option<serde_json::Value>,
    #[serde(default)]
    want: Option<bool>,
    #[serde(default)]
    node_limit: Option<u64>,
    #[serde(default)]
    time_limit_ms: Option<u64>,
    #[serde(default)]
    opt_node_limit: Option<u64>,
    #[serde(default)]
    color: Option<String>,
}

fn default_budget() -> i32 {
    -1
}

fn color_of(s: &str) -> u8 {
    if s == "B" {
        BLACK
    } else {
        WHITE
    }
}

fn pred_of(s: &str) -> u8 {
    match s {
        "alive" => PRED_ALIVE,
        "seki" => PRED_SEKI,
        "sem_win" => PRED_SEM_WIN,
        _ => PRED_SEM_SEKI,
    }
}

fn to_cstring(s: String) -> *mut c_char {
    CString::new(s).unwrap().into_raw()
}

#[no_mangle]
pub extern "C" fn ts_new(problem_json: *const c_char) -> u64 {
    let result = catch_unwind(|| {
        let raw = unsafe { CStr::from_ptr(problem_json) }.to_str().ok()?;
        let p: ProblemIn = serde_json::from_str(raw).ok()?;
        let mut b = Board::new(p.width, p.height);
        for (x, y) in &p.black {
            b.set_stone(y * p.width + x, BLACK);
        }
        for (x, y) in &p.white {
            b.set_stone(y * p.width + x, WHITE);
        }
        let region: Vec<u16> = {
            let mut v: Vec<u16> = p.region.iter().map(|(x, y)| (y * p.width + x) as u16).collect();
            v.sort();
            v
        };
        let tc = color_of(&p.target_color);
        let tp = color_of(&p.to_play);
        // 既に取られている元石は live-origin から落とす（Python 側と同じ）
        let t_origin: Vec<u16> = {
            let mut v: Vec<u16> = p
                .target
                .iter()
                .map(|(x, y)| (y * p.width + x) as u16)
                .filter(|&q| b.stones[q as usize] == tc)
                .collect();
            v.sort();
            v
        };
        let o_origin: Vec<u16> = {
            let mut v: Vec<u16> = p
                .own_target
                .iter()
                .map(|(x, y)| (y * p.width + x) as u16)
                .filter(|&q| b.stones[q as usize] == tp)
                .collect();
            v.sort();
            v
        };
        if t_origin.len() > 64 || o_origin.len() > 64 {
            return None;
        }
        Some(Solver::new(b, region, tc, tp, tp, t_origin, o_origin))
    });
    match result {
        Ok(Some(solver)) => {
            let mut id_guard = NEXT_ID.lock().unwrap();
            let id = *id_guard;
            *id_guard += 1;
            let mut reg = REGISTRY.lock().unwrap();
            reg.get_or_insert_with(HashMap::new).insert(id, solver);
            id
        }
        _ => 0,
    }
}

#[no_mangle]
pub extern "C" fn ts_call(handle: u64, request_json: *const c_char) -> *mut c_char {
    // 呼び出し元（Python メインスレッド）のスタックは 1MB 程度しかなく、df-pn の深い再帰で
    // あふれるとプロセスごと即死する（トレースバックも出ない）。大スタックの専用スレッドで実行する
    let raw_owned = unsafe { CStr::from_ptr(request_json) }.to_owned();
    let result = std::thread::Builder::new()
        .stack_size(512 * 1024 * 1024)
        .spawn(move || ts_call_inner(handle, raw_owned))
        .map(|h| h.join());
    match result {
        Ok(Ok(s)) => to_cstring(s),
        _ => to_cstring("{\"error\":\"panic\"}".to_string()),
    }
}

fn ts_call_inner(handle: u64, raw_owned: std::ffi::CString) -> String {
    let result = catch_unwind(AssertUnwindSafe(|| {
        let raw = raw_owned.to_str().unwrap_or("");
        let req: RequestIn = match serde_json::from_str(raw) {
            Ok(r) => r,
            Err(e) => return format!("{{\"error\":\"bad request: {}\"}}", e),
        };
        let mut reg = REGISTRY.lock().unwrap();
        let solver = match reg.as_mut().and_then(|m| m.get_mut(&handle)) {
            Some(s) => s,
            None => return "{\"error\":\"bad handle\"}".to_string(),
        };
        solver.node_limit = match req.node_limit {
            Some(lim) => solver.nodes.saturating_add(lim), // per-call の予算（nodes は累積）
            None => u64::MAX,
        };
        solver.deadline = req.time_limit_ms.map(|ms| Instant::now() + Duration::from_millis(ms));
        if let Some(lim) = req.opt_node_limit {
            solver.opt_node_limit = lim;
        }
        let first_move: i32 = match &req.first_move {
            None => -2,
            Some(serde_json::Value::Null) => -2,
            Some(serde_json::Value::String(_)) => -1, // "pass"
            Some(serde_json::Value::Array(a)) => {
                let x = a[0].as_u64().unwrap() as usize;
                let y = a[1].as_u64().unwrap() as usize;
                (y * solver.board.w + x) as i32
            }
            _ => -2,
        };
        let komaster = req.komaster.as_deref().map(color_of).unwrap_or(0);
        let budget: i8 = req.budget.clamp(-1, 100) as i8;
        match req.op.as_str() {
            "solve" => {
                let pred = pred_of(req.pred.as_deref().unwrap_or("alive"));
                let n0 = solver.nodes;
                match solver.solve_after(first_move, pred, komaster, budget) {
                    Ok((v, t)) => format!(
                        "{{\"value\":{},\"taint\":{},\"nodes\":{}}}",
                        v,
                        t,
                        solver.nodes - n0
                    ),
                    Err(_) => "{\"timeout\":true}".to_string(),
                }
            }
            "optimize" => {
                let pred = pred_of(req.pred.as_deref().unwrap_or("alive"));
                let want = req.want.unwrap_or(true);
                match solver.optimize_after(first_move, pred, komaster, budget, want) {
                    Ok((plies, mat, line)) => {
                        let pts: Vec<String> = line
                            .iter()
                            .map(|&m| {
                                if m < 0 {
                                    "null".to_string()
                                } else {
                                    format!("[{},{}]", m as usize % solver.board.w, m as usize / solver.board.w)
                                }
                            })
                            .collect();
                        format!(
                            "{{\"plies\":{},\"material\":{},\"line\":[{}]}}",
                            plies,
                            mat,
                            pts.join(",")
                        )
                    }
                    Err(_) => "{\"timeout\":true}".to_string(),
                }
            }
            "probe" => {
                let pred = pred_of(req.pred.as_deref().unwrap_or("alive"));
                let want = req.want.unwrap_or(true);
                match solver.probe_store(pred, komaster, budget, want) {
                    Some(mv) => {
                        let mv_json = if mv == -1 {
                            "\"pass\"".to_string()
                        } else {
                            format!("[{},{}]", mv as usize % solver.board.w, mv as usize / solver.board.w)
                        };
                        format!("{{\"hit\":true,\"move\":{}}}", mv_json)
                    }
                    None => "{\"hit\":false}".to_string(),
                }
            }
            "play" => {
                // root を1手進める（相手/自分の実着手の反映。TT 温存）
                let color = color_of(req.color.as_deref().unwrap_or("B"));
                let ok = solver.advance_root(first_move, color);
                format!("{{\"ok\":{},\"root_ban\":{}}}", ok, solver.root_ban)
            }
            "legal_moves" => {
                let moves = solver.legal_root_moves();
                let pts: Vec<String> = moves
                    .iter()
                    .map(|&m| format!("[{},{}]", m as usize % solver.board.w, m as usize / solver.board.w))
                    .collect();
                format!("{{\"moves\":[{}]}}", pts.join(","))
            }
            "stats" => format!("{{\"nodes\":{}}}", solver.nodes),
            other => format!("{{\"error\":\"unknown op {}\"}}", other),
        }
    }));
    match result {
        Ok(s) => s,
        Err(_) => "{\"error\":\"panic\"}".to_string(),
    }
}

#[no_mangle]
pub extern "C" fn ts_drop(handle: u64) {
    if let Ok(mut reg) = REGISTRY.lock() {
        if let Some(m) = reg.as_mut() {
            m.remove(&handle);
        }
    }
}

#[no_mangle]
pub extern "C" fn ts_free_str(ptr: *mut c_char) {
    if !ptr.is_null() {
        unsafe {
            drop(CString::from_raw(ptr));
        }
    }
}
