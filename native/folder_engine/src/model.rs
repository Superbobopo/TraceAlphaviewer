#![allow(non_snake_case)]

use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicU64, Ordering};

static NEXT_OBJECT_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct MachineEvent {
    pub line_num: u64,
    pub timestamp: f64,
    pub timestamp_str: String,
    pub severity: String,
    pub kind: String,
    pub title: String,
    pub detail: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct BoxInfo {
    #[serde(skip)]
    pub(crate) parser_object_id: u64,
    pub barcode: String,
    pub source_ref: String,
    pub name: String,
    pub lot: String,
    pub identified_barcode: String,
    pub identified_name: String,
    pub identity_line: u64,
    pub identity_source: String,
    pub camera_identity_line: u64,
    pub camera_identity_source: String,
    pub identity_conflict: bool,
    pub bdd_reference: String,
    pub bdd_source_line: u64,
    pub length_mm: i64,
    pub width_mm: i64,
    pub height_mm: i64,
    pub bdd_width_mm: i64,
    pub bdd_height_mm: i64,
    pub bdd_length_mm: i64,
    pub measured_t4_length_mm: i64,
    pub measured_t4t_length_mm: i64,
    pub measured_t4_diff_mm: Option<i64>,
    pub measured_t4_line: u64,
    pub measured_t5_line: u64,
    pub measured_height_line: u64,
    pub measured_t5_width_mm: i64,
    pub measured_t5_height_mm: i64,
    pub measured_t5_length_mm: i64,
    pub measurement_status: String,
    pub t5_footprint_mm: i64,
    pub id_b: i64,
    pub id_alpha: i64,
    pub t5_transfer_id: u64,
    pub x_pos: i64,
    pub t5_visual_x_pos: i64,
    pub t5_entry_aligned: bool,
    pub t5_after_c9: bool,
    pub color: String,
}

impl Default for BoxInfo {
    fn default() -> Self {
        Self {
            parser_object_id: NEXT_OBJECT_ID.fetch_add(1, Ordering::Relaxed),
            barcode: String::new(), source_ref: String::new(), name: String::new(), lot: String::new(),
            identified_barcode: String::new(), identified_name: String::new(), identity_line: 0,
            identity_source: String::new(), camera_identity_line: 0, camera_identity_source: String::new(),
            identity_conflict: false, bdd_reference: String::new(), bdd_source_line: 0,
            length_mm: 0, width_mm: 0, height_mm: 0, bdd_width_mm: 0, bdd_height_mm: 0,
            bdd_length_mm: 0, measured_t4_length_mm: 0, measured_t4t_length_mm: 0,
            measured_t4_diff_mm: None, measured_t4_line: 0, measured_t5_line: 0,
            measured_height_line: 0, measured_t5_width_mm: 0, measured_t5_height_mm: 0,
            measured_t5_length_mm: 0, measurement_status: String::new(), t5_footprint_mm: 0,
            id_b: 0, id_alpha: 0, t5_transfer_id: 0, x_pos: 0, t5_visual_x_pos: 0,
            t5_entry_aligned: false, t5_after_c9: false, color: "#4FC3F7".into(),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct MachineState {
    pub line_num: u64,
    pub timestamp: f64,
    pub timestamp_str: String,
    pub state_T0: String,
    pub state_T1: String,
    pub state_T2: String,
    pub state_tEA_T3: String,
    pub state_tT3_T4: String,
    pub state_tT4_T5: String,
    pub state_T5: String,
    pub eT0: i64, pub eT1: i64, pub eT2: i64, pub eT3: i64, pub eT4: i64, pub eT5: i64,
    pub C0: i64, pub C1: i64, pub C2: i64, pub C3: i64, pub C4: i64,
    pub C5: i64, pub C6: i64, pub C9: i64,
    pub flag_poubelle_pleine: i64,
    pub lzb: i64,
    pub pT3: i64, pub pT4: i64, pub pT5: i64,
    pub LgBtT4: f64,
    pub larg_T5: i64,
    pub fgBfinT3: i64, pub fgBfinT4: i64,
    pub eT5useO: i64, pub eT5useA: i64,
    pub t4_direction: i64, pub t5_direction: i64,
    pub t5_active_id_alpha: i64,
    pub t5_x_butee: i64,
    pub t5_visual_offset_mm: i64,
    pub cubestop_present: i64,
    pub cubestop_position: String,
    pub cubestop_reason: String,
    pub idCB1_state: String,
    pub idCB1_barcode: String,
    pub box_in_EA: Option<BoxInfo>,
    pub box_on_T3: Option<BoxInfo>,
    pub box_on_T4: Option<BoxInfo>,
    pub boxes_on_T5: Vec<BoxInfo>,
    pub raw_lines: Vec<(u64, String, bool)>,
    pub events: Vec<MachineEvent>,
}

impl Default for MachineState {
    fn default() -> Self {
        Self {
            line_num: 0, timestamp: 0.0, timestamp_str: String::new(),
            state_T0: "INIT".into(), state_T1: "INIT".into(), state_T2: "INIT".into(),
            state_tEA_T3: "INIT".into(), state_tT3_T4: "INIT".into(), state_tT4_T5: "INIT".into(),
            state_T5: "INIT".into(), eT0: 0, eT1: 0, eT2: 0, eT3: 0, eT4: 0, eT5: 0,
            C0: 0, C1: 0, C2: 0, C3: 0, C4: 0, C5: 0, C6: 0, C9: 0,
            flag_poubelle_pleine: 0, lzb: 0, pT3: 0, pT4: 0, pT5: 0, LgBtT4: 0.0,
            larg_T5: 0, fgBfinT3: 0, fgBfinT4: 0, eT5useO: 0, eT5useA: 0,
            t4_direction: 0, t5_direction: 0, t5_active_id_alpha: 0, t5_x_butee: 0,
            t5_visual_offset_mm: 0, cubestop_present: 0, cubestop_position: String::new(),
            cubestop_reason: String::new(), idCB1_state: String::new(), idCB1_barcode: String::new(),
            box_in_EA: None, box_on_T3: None, box_on_T4: None,
            boxes_on_T5: Vec::new(), raw_lines: Vec::new(), events: Vec::new(),
        }
    }
}

pub fn box_color(barcode: &str) -> String {
    const COLORS: [&str; 12] = ["#4FC3F7", "#81C784", "#FFB74D", "#F06292", "#BA68C8",
        "#4DB6AC", "#FF8A65", "#E6EE9C", "#CE93D8", "#80DEEA", "#FFCC02", "#A5D6A7"];
    let chars: Vec<char> = barcode.chars().collect();
    let suffix: String = chars[chars.len().saturating_sub(5)..].iter().collect();
    let idx = suffix.trim().parse::<i64>().map(|n| n.rem_euclid(12) as usize)
        .unwrap_or_else(|_| chars.iter().map(|c| *c as usize).sum::<usize>() % 12);
    COLORS[idx].into()
}
