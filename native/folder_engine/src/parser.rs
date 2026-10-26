#![allow(non_snake_case)]

use crate::model::{box_color, BoxInfo, MachineEvent, MachineState};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Seek, SeekFrom};
use std::path::Path;
use std::sync::LazyLock;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DuplicateRange {
    pub first_line: u64,
    pub last_line: u64,
    pub source_first_line: u64,
}

#[derive(Debug, Serialize)]
pub struct ParseResult {
    pub frame_count: u64,
    pub line_count: u64,
    pub duplicate_ranges: Vec<DuplicateRange>,
    pub blocks: Vec<String>,
}

macro_rules! pattern {
    ($name:ident, $text:expr) => {
        static $name: LazyLock<Regex> = LazyLock::new(|| Regex::new($text).expect("Expression reguliere interne"));
    };
}

pattern!(HDR, r"[*L ]?\s*(\d{1,2})\|(\d{2}):(\d{2}):(\d{2})\.(\d+)\s+(.*)");
pattern!(T0, r"\bT0:\s+(\S+)\s+eT0:(-?\d+)\s+C0:(\d+)");
pattern!(T1, r"\bT1:\s+(\S+)\s+eT1:(-?\d+)");
pattern!(T2, r"\bT2:\s+(\S+)\s+eT2:(-?\d+)(?:\s+eT3:(-?\d+))?\s+C2:(\d+)\s+C3:(\d+)\s+C4:(\d+)");
pattern!(TEA, r"tEA-T3:\s+(\S+)\s+C4:(\d+)\s+C5:(\d+)\s+fgBfinT3:(\d+)\s+eT3:(-?\d+)\s+pT3:(-?\d+)mm(?:\s+IdCB1:(\S+))?");
pattern!(TT3T4, r"tT3/T4:\s+(\S+)\s+eT4:(-?\d+)(?:\s+C5:(\d+))?\s+C6:(\d+)\s+pT3:(-?\d+)mm\s+pT4:(-?\d+)mm\s+LgBtT4:(-?[\d,]+)mm");
pattern!(TT4T5, r"tT4\*T5:\s+(\S+)\s+C6:(\d+)\s+fgBfinT4:(\d+)\s+pT4:(-?\d+)mm");
pattern!(T5, r"\bT5:\s+(\S+)\s+eT5=(-?\d+).*?larg:(-?\d+).*?C9:(\d+).*?pT5:(-?\d+).*?eT5useO:(\d+).*?eT5useA:(\d+)");
pattern!(CUBESTOP_INFO, r"(?i)\bCubeStop:([YN])\b");
pattern!(CUBESTOP_MOVE, r"(?i)mvt\s+CubeStop\s+vers\s+le\s+(HAUT|BAS)(?:\s*\((.*?)\))?");
pattern!(BOX_INIT_T5, r"sur T5:\s+(\S+)\s+(\S+)\s+lot:(\S+)\s+\S+\s+x=(\d+)");
pattern!(BOX_CREATE, r"Cr[eé]ation de la boite '([^']*)'\s+(.+?)\s+x=(\d+)\s+\((\d+)x(\d+)x(\d+)\)\s+IdA:(\d+)");
pattern!(BOX_REMOVE, r"supp\. de T5 la boite Id:(\d+)\s+ref:(\S+)");
pattern!(BOX_REMOVE2, r"-suppression de la boite ID:(\d+)");
pattern!(BOX_REMOVE3, r"Suppr\. la boite IdA:(\d+)");
pattern!(CB_HIST, r"(?i)\bCB([12]):\s+ajout Hist_LectCB .*?(\d+)code\(s\) lu\(s\)");
pattern!(CB_IDENTIF, r"(?i)idCB([12]):\s*-->\s*R\S*f:(\S+)\s+lot:\s*(\S*)");
pattern!(CB2_NBOITE, r"(?i)idCB2:\s*\(Nboite=\s*(\d+)\)");
pattern!(CB2_DIRECT_IDENTIF, r"(?i)idCB2:.*?Ok '([^']+)'.*?\(Nboite=\s*(\d+)\)");
pattern!(T3_T4_FIN_IDB, r"(?i)transfert T3->T4 termin.*?longueur=([\d,]+) mm.*?idB=(\d+)");
pattern!(AJOUT_T5_ID, r"(?i)AjoutBtT5\.idA(\d+)\.idB(-?\d+)");
pattern!(T4_T5_REQUEST, r"(?i)Demande le transfert \(physique\).*?T4 vers T5 '([^']*)'");
pattern!(DB_INFO, r"-->\s+(.+?)\s+(\d+)x(\d+)x(\d+)\s+[\d,]+g");
pattern!(RECH_INFOS, r"Rech\. infos.*?pour (\S+)");
pattern!(MAJ_T5_POS, r"MAJ \(BUTEE-T5\) boite Id:(\d+) ref:(\S*).*?nvlle dim:\d+x(\d+)\s+X:(\d+)");
pattern!(MAJ_T5_MESURE, r"MAJ \(APRES-MESURE-LARG\) bt IdA:(\d+) '([^']*)'.*?nvlle lxH:(\d+)x(\d+) \[x(\d+)\] X:(\d+)(?:.*?\(BdD:(\d+)x(\d+)x(\d+)\))?");
pattern!(ERROR_WORD, r"(?i)\b(err|erreur|timeout|alarme|defaut|défaut)\b");
pattern!(DEPL_T5, r"D[eé]place toutes les boites.*?sur (-?\d+) mm");
pattern!(DEPL_T5_ACTIVE, r"(?i)DeplBtSurT5\.(-?\d+)mm\.Ref\S+\.idA(\d+)");
pattern!(C1_SENSOR, r"capteurC1=(\d+)");
pattern!(POUBELLE, r"(?i)FlagPoubellePleine\s*=\s*(\w+)");
pattern!(LZB, r"\bLzB[:\s=]+(-?\d+)");
pattern!(T4_LENGTH_SUMMARY, r"(?i)longueur boite .*?\(BdD\)=(-?\d+).*?\(T2T\)=(-?\d+).*?\(T4C\)=(-?\d+).*?\(T4T\)=(-?\d+).*?diffT4=(-?\d+)mm");
pattern!(T5_WIDTH_C9_INVALID, r"(?i)largeur lue sur T5\s*<\s*2mm\s+et\s+C9=1");
static OPENING: LazyLock<regex::bytes::Regex> = LazyLock::new(||
    regex::bytes::Regex::new(r"(?-u)OUVERTURE DE LA TRACE.*\ble\s+\d{2}/\d{2}/\d{4}").unwrap());
static STAMP: LazyLock<regex::bytes::Regex> = LazyLock::new(||
    regex::bytes::Regex::new(r"(?-u)^\s*[*L ]?\s*\d{1,2}\|\d{2}:\d{2}:\d{2}\.\d+").unwrap());

#[derive(Default)]
struct Context {
    active_errors: HashMap<String, i64>,
    last_error_ts: HashMap<(String, i64), f64>,
    last_sensors: HashMap<&'static str, i64>,
    last_belt_et: HashMap<&'static str, i64>,
    last_t4_et: Option<i64>,
    t4_cycle_id: u64,
    last_t4_c6_measure_cycle: Option<u64>,
    last_pT4: Option<i64>,
    last_t4_direction: i64,
    last_pT5: Option<i64>,
    last_t5_direction: i64,
    t5_visual_anchor_pT5: Option<i64>,
    t5_visual_anchor_pending: bool,
    last_reader: String,
    last_hist_reader: Option<String>,
    pending_reader: String,
    pending_bc: Option<String>,
    pending_name: String,
    pending_dims: Option<[i64; 3]>,
    pending_t5_creation_box: Option<BoxInfo>,
    pending_t4_length_transfer: Option<u64>,
    pending_t4_length_idb: Option<i64>,
    pending_t4_length_ida: Option<i64>,
    t4_t5_requested_ref: Option<String>,
    idb_to_ida: HashMap<i64, i64>,
    ida_to_idb: HashMap<i64, i64>,
    idb_to_box: HashMap<i64, BoxInfo>,
    object_aliases: HashMap<u64, HashSet<i64>>,
    seen_error_lines: HashSet<u64>,
}

fn n(c: &regex::Captures<'_>, index: usize) -> i64 {
    c.get(index).and_then(|s| s.as_str().parse().ok()).unwrap_or(0)
}

fn remember_box(ctx: &mut Context, id_b: i64, b: &BoxInfo) {
    if let Some(previous)=ctx.idb_to_box.insert(id_b,b.clone()) {
        if let Some(aliases)=ctx.object_aliases.get_mut(&previous.parser_object_id) {aliases.remove(&id_b);}
    }
    ctx.object_aliases.entry(b.parser_object_id).or_default().insert(id_b);
}

fn add_event(s: &mut MachineState, line: u64, severity: &str, kind: &str, title: impl Into<String>, detail: impl Into<String>) {
    s.events.push(MachineEvent { line_num: line, timestamp: s.timestamp,
        timestamp_str: s.timestamp_str.clone(), severity: severity.into(), kind: kind.into(),
        title: title.into(), detail: detail.into() });
}

fn unknown(reference: &str) -> bool {
    let v = reference.trim().to_uppercase();
    v.is_empty() || ["ALPHA-INC", "ALPHA-DET", "ALPHA-DIF"].iter().any(|p| v.starts_with(p)) || v.contains("UNKNOW")
}

fn record_identification(b: &mut BoxInfo, reference: &str, name: &str, line: u64, source: &str, camera: bool) {
    if unknown(reference) { return; }
    if !b.identified_barcode.is_empty() && b.identified_barcode != reference {
        b.identity_conflict = true;
        return;
    }
    b.identified_barcode = reference.into();
    if !name.is_empty() { b.identified_name = name.into(); }
    if line != 0 && b.identity_line == 0 { b.identity_line = line; b.identity_source = source.into(); }
    if camera && line != 0 && matches!(source, "CB1" | "CB2") && b.camera_identity_line == 0 {
        b.camera_identity_line = line; b.camera_identity_source = source.into();
    }
}

fn set_bdd_dimensions(b: &mut BoxInfo, dims: [i64; 3], reference: &str, line: u64) {
    let reference = if reference.is_empty() { b.identified_barcode.as_str() } else { reference };
    if dims.iter().any(|v| *v <= 0) || unknown(reference) { return; }
    b.bdd_reference = reference.into();
    b.bdd_width_mm = dims[0]; b.bdd_height_mm = dims[1]; b.bdd_length_mm = dims[2]; b.bdd_source_line = line;
}

fn apply_identity(b: &mut BoxInfo, barcode: &str, lot: &str, name: &str, dims: Option<[i64; 3]>, line: u64, source: &str, camera: bool) {
    record_identification(b, barcode, name, line, source, camera);
    if !b.barcode.is_empty() && unknown(&b.barcode) && barcode != b.barcode {
        b.source_ref = b.barcode.clone();
    } else if !barcode.is_empty() && unknown(barcode) && b.source_ref.is_empty() {
        b.source_ref = barcode.into();
    }
    if !barcode.is_empty() { b.barcode = barcode.into(); b.color = box_color(barcode); }
    if !lot.is_empty() { b.lot = lot.into(); }
    if !name.is_empty() { b.name = name.into(); }
    if let Some(dims) = dims {
        set_bdd_dimensions(b, dims, barcode, line);
        b.width_mm = dims[0]; b.height_mm = dims[1]; b.length_mm = dims[2];
    }
}

fn measurement_excluded(b: &BoxInfo) -> bool {
    b.identity_conflict || (unknown(&b.barcode) && !(b.barcode.to_uppercase().contains("[DINH]") && !b.identified_barcode.is_empty()))
        || b.identified_barcode.is_empty() || b.identity_line == 0
        || (!unknown(&b.barcode) && b.barcode != b.identified_barcode)
        || (!b.bdd_reference.is_empty() && b.bdd_reference != b.identified_barcode)
        || b.camera_identity_line == 0 || !matches!(b.camera_identity_source.as_str(), "CB1" | "CB2")
        || b.bdd_reference.is_empty() || [b.bdd_width_mm, b.bdd_height_mm, b.bdd_length_mm].iter().any(|v| *v <= 0)
}

fn classify(b: &mut BoxInfo) {
    if b.measurement_status == "c9_error" { return; }
    if measurement_excluded(b) || b.measured_t4_line == 0 { b.measurement_status.clear(); return; }
    let e = [b.bdd_width_mm, b.bdd_height_mm, b.bdd_length_mm];
    if e.iter().any(|v| *v <= 0) { return; }
    let m = [b.measured_t5_width_mm, b.measured_t5_height_mm, b.measured_t4_length_mm];
    if m.iter().any(|v| *v <= 0) { b.measurement_status.clear(); return; }
    let score = |p: [i64; 3]| -> i64 { (0..3).map(|i| (m[i] - p[i]).abs()).sum() };
    let normal = score(e);
    let permutations = [[e[0],e[1],e[2]],[e[0],e[2],e[1]],[e[1],e[0],e[2]],
        [e[1],e[2],e[0]],[e[2],e[0],e[1]],[e[2],e[1],e[0]]];
    let oriented = permutations.iter().any(|p| *p != e && score(*p) <= normal);
    let bad = [(m[0]-e[0]).abs() > 3, (m[1]-e[1]).abs() > 2, (m[2]-e[2]).abs() > 3];
    b.measurement_status = if oriented { "orientation" } else { match bad {
        [false,false,false] => "ok", [true,false,false] => "width", [false,true,false] => "height",
        [false,false,true] => "length", _ => "multiple",
    }}.into();
}

fn copy_dimension_tracking(dst: &mut BoxInfo, src: &BoxInfo) {
    dst.t5_transfer_id = src.t5_transfer_id; dst.source_ref = src.source_ref.clone();
    dst.identified_barcode = src.identified_barcode.clone(); dst.identified_name = src.identified_name.clone();
    dst.identity_line = src.identity_line; dst.identity_source = src.identity_source.clone();
    dst.camera_identity_line = src.camera_identity_line; dst.camera_identity_source = src.camera_identity_source.clone();
    dst.identity_conflict = src.identity_conflict; dst.bdd_reference = src.bdd_reference.clone();
    dst.bdd_source_line = src.bdd_source_line; dst.measured_t4t_length_mm = src.measured_t4t_length_mm;
    dst.measured_t4_diff_mm = src.measured_t4_diff_mm; dst.measured_t4_line = src.measured_t4_line;
    dst.measured_t5_line = src.measured_t5_line; dst.measured_height_line = src.measured_height_line;
    dst.bdd_width_mm = src.bdd_width_mm; dst.bdd_height_mm = src.bdd_height_mm; dst.bdd_length_mm = src.bdd_length_mm;
    dst.measured_t4_length_mm = src.measured_t4_length_mm; dst.measured_t5_width_mm = src.measured_t5_width_mm;
    dst.measured_t5_height_mm = src.measured_t5_height_mm; dst.measured_t5_length_mm = src.measured_t5_length_mm;
    dst.measurement_status = src.measurement_status.clone();
}

fn unique_barcode(boxes: &[BoxInfo], barcode: &str) -> Option<usize> {
    if barcode.is_empty() { return None; }
    let mut found = None;
    for (i, b) in boxes.iter().enumerate() {
        if b.barcode == barcode { if found.is_some() { return None; } found = Some(i); }
    }
    found
}

fn find_t5(s: &MachineState, id_a: i64, id_b: i64, barcode: &str) -> Option<usize> {
    if id_a != 0 { if let Some(i) = s.boxes_on_T5.iter().position(|b| b.id_alpha == id_a) { return Some(i); } }
    if id_b != 0 { if let Some(i) = s.boxes_on_T5.iter().position(|b| b.id_b == id_b) { return Some(i); } }
    unique_barcode(&s.boxes_on_T5, barcode)
}

fn find_t4_measure(s: &MachineState, ctx: &Context) -> Option<usize> {
    let matches: Vec<usize> = if let Some(transfer) = ctx.pending_t4_length_transfer.filter(|v| *v != 0) {
        s.boxes_on_T5.iter().enumerate().filter(|(_,b)| b.t5_transfer_id == transfer).map(|(i,_)| i).collect()
    } else if let Some(id_b) = ctx.pending_t4_length_idb.filter(|v| *v != 0) {
        let id_a = ctx.pending_t4_length_ida.unwrap_or(0);
        s.boxes_on_T5.iter().enumerate().filter(|(_,b)| if id_a != 0 { b.id_alpha == id_a } else { b.id_b == id_b }).map(|(i,_)| i).collect()
    } else { return None; };
    if matches.len() == 1 { Some(matches[0]) } else { None }
}

fn box_label(b: Option<&BoxInfo>) -> String {
    match b {
        Some(b) if b.id_b != 0 => format!("idB={}", b.id_b),
        Some(b) if !b.barcode.is_empty() => b.barcode.clone(),
        Some(b) if !b.source_ref.is_empty() => b.source_ref.clone(),
        _ => "boite".into(),
    }
}

fn ensure_reader<'a>(s: &'a mut MachineState, reader: &str, barcode: &str) -> Option<&'a mut BoxInfo> {
    let color = box_color(if barcode.is_empty() { "0" } else { barcode });
    if reader == "CB1" {
        Some(s.box_in_EA.get_or_insert_with(|| BoxInfo { color, ..BoxInfo::default() }))
    } else if reader == "CB2" {
        if s.box_on_T3.is_none() && s.C5 == 1 { s.box_on_T3 = Some(BoxInfo { color, ..BoxInfo::default() }); }
        s.box_on_T3.as_mut()
    } else { None }
}

fn track_motor_error(s: &mut MachineState, line: u64, ctx: &mut Context, belt: &str, et: i64, detail: &str) {
    if et < 0 && et != -1 {
        if ctx.active_errors.get(belt) != Some(&et) {
            ctx.active_errors.insert(belt.into(), et);
            let key = (belt.into(), et);
            if ctx.last_error_ts.get(&key).is_some_and(|ts| s.timestamp - ts < 300.0) { return; }
            ctx.last_error_ts.insert(key, s.timestamp);
            add_event(s, line, "error", "ERREUR", format!("{belt} en erreur eT:{et}"), detail.trim());
        }
    } else { ctx.active_errors.remove(belt); }
}

fn track_task(s: &mut MachineState, line: u64, ctx: &mut Context, belt: &'static str, et: i64, name: &str) {
    if let Some(previous) = ctx.last_belt_et.insert(belt, et) {
        if previous != et && et.abs() > 2 {
            add_event(s, line, if et < 0 { "error" } else { "info" }, belt, format!("{belt} eT:{et} {name}"), "");
        }
    }
}

fn track_signals(s: &mut MachineState, line: u64, ctx: &mut Context) {
    let sensors = [("C0",s.C0,"Presence T1 entree detectee"),("C2",s.C2,"Presence T2 sortie detectee"),
        ("C3",s.C3,"Presence T2 chargee detectee"),("C4",s.C4,"Presence EA detectee"),
        ("C5",s.C5,"Presence T3 detectee"),("C6",s.C6,"Presence T4 detectee"),
        ("C9",s.C9,"Laser T5 actif"),("Poubelle",s.flag_poubelle_pleine,"Poubelle pleine")];
    for (name,value,label) in sensors {
        if ctx.last_sensors.insert(name, value) == Some(0) && value == 1 {
            add_event(s,line,if name == "Poubelle" { "warning" } else { "info" },"CAPTEUR",label,"");
        }
    }
}

fn track_t4_cycle(s: &mut MachineState, line: u64, ctx: &mut Context) {
    if ctx.last_t4_et != Some(s.eT4) {
        ctx.last_t4_et = Some(s.eT4);
        let detail = format!("boite T4 pT4:{}mm", s.pT4);
        let full = format!("boite T4 C6:{} pT4:{}mm",s.C6,s.pT4);
        match s.eT4 {
            41 => {ctx.t4_cycle_id += 1; add_event(s,line,"info","T4","T3 vers T4 demarre",detail);},
            42 => add_event(s,line,"info","T4","Mesure longueur T4 en cours",detail),
            43 if s.LgBtT4 > 0.0 => add_event(s,line,"info","T4",format!("Longueur T4 mesuree {:.0}mm",s.LgBtT4),full),
            46 => { let detail = if s.LgBtT4 > 0.0 {format!("{full} Lg:{:.0}mm",s.LgBtT4)} else {full};
                add_event(s,line,"info","T4","T3 vers T4 termine",detail); },
            81 => add_event(s,line,"info","T4","Transfert T4 vers T5 demarre",detail),
            83 => add_event(s,line,"info","T4","Retour index T4 apres depot",detail),
            85 => add_event(s,line,"info","T4","Cycle T4 termine",detail), _ => (),
        }
    }
    if s.C6 == 1 && s.LgBtT4 > 0.0 && ctx.last_t4_c6_measure_cycle != Some(ctx.t4_cycle_id) {
        ctx.last_t4_c6_measure_cycle = Some(ctx.t4_cycle_id);
        add_event(s,line,"info","T4",format!("C6 declenche longueur {:.0}mm",s.LgBtT4),format!("boite T4 pT4:{}mm",s.pT4));
    }
}

fn update_t4_direction(s: &mut MachineState, pos: i64, ctx: &mut Context) {
    if s.eT4.abs() <= 2 || matches!(s.eT4,5|51|85) { s.t4_direction = 0; }
    else if let Some(prev) = ctx.last_pT4.filter(|v| *v != pos) {
        let delta = pos-prev;
        if delta.abs() >= 2 { s.t4_direction = if delta < 0 {1} else {-1}; ctx.last_t4_direction = s.t4_direction; }
        else {s.t4_direction = ctx.last_t4_direction;}
    } else {s.t4_direction = ctx.last_t4_direction;}
    ctx.last_pT4 = Some(pos);
}

fn visual_with_offset(b: &BoxInfo, butee: i64, offset: i64) -> i64 {
    let base = if b.t5_visual_x_pos != 0 {b.t5_visual_x_pos} else {b.x_pos};
    if butee > 1750 && base > 1750 {
        let distance = (base-butee).abs() + offset;
        if base >= butee {butee+distance} else {butee-distance}
    } else {base+offset}
}

fn commit_visual(s: &mut MachineState) {
    if s.t5_visual_offset_mm != 0 {
        for b in &mut s.boxes_on_T5 {b.t5_visual_x_pos = visual_with_offset(b,s.t5_x_butee,s.t5_visual_offset_mm);}
    }
    s.t5_visual_offset_mm = 0;
}

fn reset_visual(s: &mut MachineState, ctx: &mut Context, commit: bool) {
    if commit {commit_visual(s);} else {s.t5_visual_offset_mm=0;}
    ctx.t5_visual_anchor_pT5=Some(s.pT5); ctx.t5_visual_anchor_pending=true;
}

fn update_visual(s: &mut MachineState, pos: i64, ctx: &mut Context) {
    if ctx.t5_visual_anchor_pending {
        ctx.t5_visual_anchor_pending=false; ctx.t5_visual_anchor_pT5=Some(pos); s.t5_visual_offset_mm=0; return;
    }
    match ctx.t5_visual_anchor_pT5 {
        Some(anchor) if !s.boxes_on_T5.is_empty() => s.t5_visual_offset_mm=pos-anchor,
        _ => {ctx.t5_visual_anchor_pT5=Some(pos);s.t5_visual_offset_mm=0;},
    }
}

fn apply_list_pack(s: &mut MachineState, text: &str, ctx: &mut Context) {
    if !text.contains("ALPHA:T5-LIST-PACK") {return;}
    let mut parsed=Vec::new();
    for chunk in text.split('@') {
        let sep=if chunk.starts_with("<Dc2>") {"<Dc2>"} else if chunk.starts_with('¶') {"¶"} else {continue;};
        let v: Vec<&str> = chunk.split(sep).skip(1).collect();
        if v.len()<14 {continue;}
        let numbers: Option<Vec<i64>> = [0,4,5,6,13].iter().map(|i| v[*i].parse().ok()).collect();
        let Some(numbers)=numbers else {continue;};
        let (id_a,bc,x)=(numbers[0],v[2],numbers[4]);
        let id_b=ctx.ida_to_idb.get(&id_a).copied().unwrap_or(0);
        let mut footprint=0;
        for (i,value) in v.iter().enumerate() {
            if value.starts_with("X990") && i+2<v.len() {footprint=v[i+1].parse().unwrap_or(0);break;}
        }
        let mut b=BoxInfo {barcode:bc.into(),name:v[3].into(),lot:v[8].into(),width_mm:numbers[1],
            height_mm:numbers[2],length_mm:numbers[3],t5_footprint_mm:footprint,id_b,id_alpha:id_a,
            x_pos:x,t5_visual_x_pos:x,t5_after_c9:true,color:box_color(bc),..BoxInfo::default()};
        if let Some(i)=find_t5(s,id_a,id_b,"").or_else(|| unique_barcode(&s.boxes_on_T5,bc)) {
            copy_dimension_tracking(&mut b,&s.boxes_on_T5[i]);
            record_identification(&mut b,bc,v[3],0,"",false);classify(&mut b);
        }
        parsed.push(b);
    }
    if !parsed.is_empty() || text.trim_end().ends_with("@FP") {
        s.boxes_on_T5=parsed;
        if s.t5_active_id_alpha!=0 && !s.boxes_on_T5.iter().any(|b| b.id_alpha==s.t5_active_id_alpha) {s.t5_active_id_alpha=0;}
        reset_visual(s,ctx,false);
    }
}

fn update(s: &mut MachineState, text: &str, ctx: &mut Context, line: u64) {
    if text.contains("version logiciel VBalpha:") {
        ctx.pending_t5_creation_box=None; ctx.pending_t4_length_transfer=None;
        ctx.pending_t4_length_idb=None; ctx.pending_t4_length_ida=None; ctx.t4_t5_requested_ref=None;
    }
    if text.contains("idCB2:") || text.contains("CB2:") {ctx.last_reader="CB2".into();}
    else if text.contains("idCB1:") || text.contains("CB1:") {ctx.last_reader="CB1".into();}
    if let Some(c)=CUBESTOP_INFO.captures(text) {
        s.cubestop_present=if c[1].eq_ignore_ascii_case("Y") {1} else {0};
        if s.cubestop_present==0 {s.cubestop_position.clear();s.cubestop_reason.clear();}
    }
    if let Some(c)=CUBESTOP_MOVE.captures(text) {
        s.cubestop_position=c[1].to_uppercase();s.cubestop_reason=c.get(2).map_or("",|v|v.as_str()).trim().into();
        s.cubestop_present=1;
        let title=if s.cubestop_position=="HAUT" {"CubeStop monte"} else {"CubeStop descend"};
        add_event(s,line,"info","CUBESTOP",title,s.cubestop_reason.clone());
    }
    if let Some(c)=CB_HIST.captures(text) {
        let reader=format!("CB{}",&c[1]);let count=n(&c,2);
        ctx.last_reader=reader.clone();ctx.last_hist_reader=Some(reader.clone());ctx.pending_reader=reader.clone();
        if reader=="CB1" {
            ensure_reader(s,"CB1","");
            add_event(s,line,"info","IDENTIF",format!("Lecture CB1 sur EA ({count} code)"),"");
        } else if ensure_reader(s,"CB2","").is_some() {
            add_event(s,line,"info","IDENTIF",format!("Lecture CB2 sur T3 ({count} code)"),"");
        } else {
            add_event(s,line,"warning","IDENTIF",format!("Lecture CB2 sans boite T3 ({count} code)"),format!("C5:{}",s.C5));
        }
    }
    apply_list_pack(s,text,ctx);
    if let Some(c)=T0.captures(text) {
        s.state_T0=c[1].into();s.eT0=n(&c,2);s.C0=n(&c,3);
        track_motor_error(s,line,ctx,"T0",s.eT0,text);
        track_task(s,line,ctx,"T0",s.eT0,&s.state_T0.clone());
    }
    if let Some(c)=T1.captures(text) {
        s.state_T1=c[1].into();s.eT1=n(&c,2);
        track_motor_error(s,line,ctx,"T1",s.eT1,text);
        track_task(s,line,ctx,"T1",s.eT1,&s.state_T1.clone());
    }
    if let Some(c)=T2.captures(text) {
        s.state_T2=c[1].into();s.eT2=n(&c,2);if c.get(3).is_some() {s.eT3=n(&c,3);}
        s.C2=n(&c,4);s.C3=n(&c,5);s.C4=n(&c,6);
        track_motor_error(s,line,ctx,"T2",s.eT2,text);
        if c.get(3).is_some() {track_motor_error(s,line,ctx,"T3",s.eT3,text);}
        track_task(s,line,ctx,"T2",s.eT2,&s.state_T2.clone());
    }
    if let Some(c)=TEA.captures(text) {
        s.state_tEA_T3=c[1].into();s.C4=n(&c,2);s.C5=n(&c,3);s.fgBfinT3=n(&c,4);s.eT3=n(&c,5);s.pT3=n(&c,6);
        track_motor_error(s,line,ctx,"T3",s.eT3,text);
    }
    if let Some(c)=TT3T4.captures(text) {
        s.state_tT3_T4=c[1].into();s.eT4=n(&c,2);if c.get(3).is_some() {s.C5=n(&c,3);}
        s.C6=n(&c,4);s.pT3=n(&c,5);
        update_t4_direction(s,n(&c,6),ctx);s.pT4=n(&c,6);s.LgBtT4=c[7].replace(',',".").parse().unwrap_or(0.0);
        track_motor_error(s,line,ctx,"T4",s.eT4,text);
        if s.box_on_T4.is_none() && s.box_on_T3.is_some() && s.C5==0 && matches!(s.eT4,41|42|43) && s.pT4>0 {
            s.box_on_T4=s.box_on_T3.take();
            add_event(s,line,"info","TRANSFERT",format!("T3->T4 en cours {}",box_label(s.box_on_T4.as_ref())),format!("eT4:{} pT4:{}mm",s.eT4,s.pT4));
        }
        track_t4_cycle(s,line,ctx);
    }
    if let Some(c)=TT4T5.captures(text) {
        s.state_tT4_T5=c[1].into();s.C6=n(&c,2);s.fgBfinT4=n(&c,3);
        update_t4_direction(s,n(&c,4),ctx);s.pT4=n(&c,4);
    }
    if let Some(c)=T5.captures(text) {
        s.state_T5=c[1].into();s.eT5=n(&c,2);s.larg_T5=n(&c,3);s.C9=n(&c,4);
        if s.C9!=0 && s.t5_active_id_alpha!=0 {
            if let Some(i)=find_t5(s,s.t5_active_id_alpha,0,"") {s.boxes_on_T5[i].t5_after_c9=true;}
        }
        let pos=n(&c,5);
        if s.eT5.abs()<=2 || matches!(s.eT5,5|51) {s.t5_direction=0;}
        else if let Some(prev)=ctx.last_pT5.filter(|v| *v!=pos) {
            s.t5_direction=if pos-prev>0 {-1} else {1};ctx.last_t5_direction=s.t5_direction;
        } else {s.t5_direction=ctx.last_t5_direction;}
        s.pT5=pos;update_visual(s,pos,ctx);ctx.last_pT5=Some(pos);s.eT5useO=n(&c,6);s.eT5useA=n(&c,7);
        track_motor_error(s,line,ctx,"T5",s.eT5,text);
    }
    if T5_WIDTH_C9_INVALID.is_match(text) {
        let found=find_t5(s,s.t5_active_id_alpha,0,"").or_else(||if s.boxes_on_T5.len()==1 {Some(0)} else {None});
        if let Some(i)=found {s.boxes_on_T5[i].measurement_status="c9_error".into();}
        add_event(s,line,"warning","T5","Largeur C9 invalide","largeur lue sur T5 < 2mm et C9=1");
    }
    if let Some(c)=BOX_INIT_T5.captures(text) {
        let bc=&c[1];let x=n(&c,4);
        if !s.boxes_on_T5.iter().any(|b|b.barcode==bc) {
            s.boxes_on_T5.push(BoxInfo {barcode:bc.into(),name:c[2].into(),lot:c[3].into(),x_pos:x,
                t5_visual_x_pos:x,color:box_color(bc),..BoxInfo::default()});
        }
        add_event(s,line,"info","BOITE",format!("Boite deja sur T5 {bc}"),text.trim());
    }
    if let Some(c)=BOX_CREATE.captures(text) {
        let (bc,name,x,id_a)=(&c[1],c[2].trim(),n(&c,3),n(&c,7));
        let pending=ctx.pending_t5_creation_box.take().map(|old| {
            s.boxes_on_T5.iter().find(|b|b.parser_object_id==old.parser_object_id).cloned().unwrap_or(old)
        });
        let id_b=pending.as_ref().map_or(0,|b|b.id_b);
        let mut idx=find_t5(s,id_a,id_b,"").filter(|i|matches!(s.boxes_on_T5[*i].id_alpha,0) || s.boxes_on_T5[*i].id_alpha==id_a);
        if idx.is_none() {
            if let Some(p)=pending.as_ref().filter(|p|p.id_alpha==0) {
                idx=s.boxes_on_T5.iter().position(|b|b.parser_object_id==p.parser_object_id);
            }
        }
        let idx=idx.unwrap_or_else(|| {s.boxes_on_T5.push(BoxInfo::default());s.boxes_on_T5.len()-1});
        let b=&mut s.boxes_on_T5[idx];
        apply_identity(b,bc,"",name,Some([n(&c,4),n(&c,5),n(&c,6)]),line,"BdD creation",false);
        if !b.t5_entry_aligned {b.x_pos=x;b.t5_visual_x_pos=x;b.t5_after_c9=false;}
        b.id_alpha=id_a;
        if id_b!=0 {b.id_b=id_b;ctx.idb_to_ida.insert(id_b,id_a);ctx.ida_to_idb.insert(id_a,id_b);}
        if ctx.pending_t4_length_transfer==Some(b.t5_transfer_id) || (id_b!=0 && ctx.pending_t4_length_idb==Some(id_b)) {
            ctx.pending_t4_length_ida=Some(id_a);
        }
        let label=box_label(Some(b));
        add_event(s,line,"info","BOITE",format!("T4->T5 {label} -> IdA={id_a}"),format!("{bc} {name} x={x}"));
        if s.box_on_T4.as_ref().is_some_and(|b|(id_b!=0 && b.id_b==id_b) || (id_b==0 && b.barcode==bc)) {s.box_on_T4=None;}
    }
    if let Some(c)=BOX_REMOVE.captures(text) {
        let (id_a,bc)=(n(&c,1),&c[2]);
        if id_a!=0 {
            s.boxes_on_T5.retain(|b|b.id_alpha!=id_a);
            if s.t5_active_id_alpha==id_a {s.t5_active_id_alpha=0;reset_visual(s,ctx,true);}
        } else if let Some(i)=unique_barcode(&s.boxes_on_T5,bc) {s.boxes_on_T5.remove(i);}
        add_event(s,line,"info","BOITE",format!("Robot prend IdA={id_a}"),bc);
    }
    if let Some(c)=BOX_REMOVE2.captures(text) {
        let id_a=n(&c,1);s.boxes_on_T5.retain(|b|b.id_alpha!=id_a);
        if s.t5_active_id_alpha==id_a {s.t5_active_id_alpha=0;reset_visual(s,ctx,true);}
        add_event(s,line,"info","BOITE",format!("Robot prend IdA={id_a}"),"");
    }
    if let Some(c)=BOX_REMOVE3.captures(text) {
        let id_a=n(&c,1);s.boxes_on_T5.retain(|b|b.id_alpha!=id_a);
        if s.t5_active_id_alpha==id_a {s.t5_active_id_alpha=0;reset_visual(s,ctx,true);}
        add_event(s,line,"info","BOITE",format!("Boite retiree de T5 IdA:{id_a}"),"");
    }
    if let Some(c)=MAJ_T5_POS.captures(text) {
        let (id_a,bc,h,x)=(n(&c,1),&c[2],n(&c,3),n(&c,4));
        s.t5_active_id_alpha=id_a;s.t5_x_butee=x;reset_visual(s,ctx,true);
        let id_b=ctx.ida_to_idb.get(&id_a).copied().unwrap_or(0);
        if let Some(i)=find_t5(s,id_a,0,bc) {
            let b=&mut s.boxes_on_T5[i];b.x_pos=x;b.t5_visual_x_pos=x;b.t5_entry_aligned=false;b.t5_after_c9=false;b.id_alpha=id_a;
            if id_b!=0 {b.id_b=id_b;}
            if h>0 {b.measured_t5_height_mm=h;b.measured_height_line=line;b.height_mm=h;}
        } else {
            s.boxes_on_T5.push(BoxInfo {barcode:bc.into(),id_alpha:id_a,x_pos:x,t5_visual_x_pos:x,id_b,
                height_mm:h,measured_t5_height_mm:h,measured_height_line:line,color:box_color(bc),..BoxInfo::default()});
        }
        add_event(s,line,"info","BOITE",format!("MAJ butee T5 {bc}"),format!("IdA:{id_a} X:{x} haut:{h}"));
    }
    if let Some(c)=MAJ_T5_MESURE.captures(text) {
        let (id_a,bc,w,h,l,x)=(n(&c,1),&c[2],n(&c,3),n(&c,4),n(&c,5),n(&c,6));
        let dims=c.get(7).map(|_|[n(&c,7),n(&c,8),n(&c,9)]);
        s.t5_active_id_alpha=id_a;reset_visual(s,ctx,true);
        let id_b=ctx.ida_to_idb.get(&id_a).copied().unwrap_or(0);
        if let Some(i)=find_t5(s,id_a,0,bc) {
            let b=&mut s.boxes_on_T5[i];b.x_pos=x;b.t5_visual_x_pos=x;b.t5_entry_aligned=false;b.t5_after_c9=true;b.id_alpha=id_a;
            if id_b!=0 {b.id_b=id_b;}
            if let Some(dims)=dims {record_identification(b,bc,"",line,"BdD MAJ",false);set_bdd_dimensions(b,dims,bc,line);}
            b.measured_t5_width_mm=w;b.measured_t5_height_mm=h;b.measured_t5_line=line;b.measured_height_line=line;
            b.measured_t5_length_mm=l;b.width_mm=w;b.height_mm=h;b.length_mm=l;classify(b);
        } else {
            let d=dims.unwrap_or([0,0,0]);
            let mut b=BoxInfo {barcode:bc.into(),id_alpha:id_a,x_pos:x,id_b,width_mm:w,height_mm:h,length_mm:l,
                bdd_width_mm:d[0],bdd_height_mm:d[1],bdd_length_mm:d[2],measured_t5_width_mm:w,measured_t5_height_mm:h,
                measured_t5_length_mm:l,measured_t5_line:line,measured_height_line:line,t5_footprint_mm:w,
                t5_visual_x_pos:x,t5_after_c9:true,color:box_color(bc),..BoxInfo::default()};
            record_identification(&mut b,bc,"",line,"BdD MAJ",false);
            if let Some(dims)=dims {set_bdd_dimensions(&mut b,dims,bc,line);}classify(&mut b);s.boxes_on_T5.push(b);
        }
        add_event(s,line,"info","BOITE",format!("MAJ mesure T5 {bc}"),format!("IdA:{id_a} X:{x} {w}x{h}x{l}"));
    }
    if let Some(c)=DEPL_T5.captures(text) {
        let delta=n(&c,1);
        for b in &mut s.boxes_on_T5 {
            let visual=visual_with_offset(b,s.t5_x_butee,s.t5_visual_offset_mm);
            if b.t5_entry_aligned {if s.t5_visual_offset_mm!=0 {b.t5_visual_x_pos=visual;}continue;}
            b.x_pos+=delta;b.t5_visual_x_pos=if s.t5_visual_offset_mm!=0 {visual} else {b.x_pos};
        }
        reset_visual(s,ctx,false);
    }
    if let Some(c)=DEPL_T5_ACTIVE.captures(text) {s.t5_active_id_alpha=n(&c,2);}
    if let Some(c)=RECH_INFOS.captures(text) {
        ctx.pending_bc=Some(c[1].into());ctx.pending_name.clear();ctx.pending_dims=None;
        ctx.pending_reader=ctx.last_hist_reader.take().unwrap_or_else(||ctx.last_reader.clone());
    }
    if let Some(c)=DB_INFO.captures(text) {
        if let Some(bc)=ctx.pending_bc.as_ref() {
            ctx.pending_name=c[1].trim().into();ctx.pending_dims=Some([n(&c,2),n(&c,3),n(&c,4)]);
            let target=if ctx.pending_reader=="CB2" {ensure_reader(s,"CB2",bc)}
                else if ctx.pending_reader=="CB1" {ensure_reader(s,"CB1",bc)}
                else {s.box_in_EA.as_mut().filter(|b|b.barcode==*bc || (!bc.is_empty() && unknown(bc)))};
            if let Some(target)=target {
                apply_identity(target,bc,"",&ctx.pending_name,ctx.pending_dims,line,
                    if ctx.pending_reader.is_empty() {"BdD"} else {&ctx.pending_reader},false);
            }
        }
    }
    if let Some(c)=CB_IDENTIF.captures(text) {
        let (reader,bc,lot)=(n(&c,1),&c[2],&c[3]);
        let (name,dims)=if ctx.pending_bc.as_deref()==Some(bc) {(ctx.pending_name.as_str(),ctx.pending_dims)} else {("",None)};
        if reader==1 {
            s.idCB1_barcode=bc.into();s.idCB1_state="IDENTIFIED".into();
            if let Some(target)=ensure_reader(s,"CB1",bc) {apply_identity(target,bc,lot,name,dims,line,"CB1",true);}
            let title=if !bc.is_empty() && unknown(bc) {format!("CB1 inconnu {bc}")} else {format!("Identification CB1 {bc}")};
            add_event(s,line,"info","IDENTIF",title,format!("lot:{lot}"));
        } else if let Some(target)=ensure_reader(s,"CB2",bc) {
            let previous=if target.source_ref.is_empty() {target.barcode.clone()} else {target.source_ref.clone()};
            apply_identity(target,bc,lot,name,dims,line,"CB2",true);
            let detail=if !previous.is_empty() && previous!=bc {format!("{previous} -> {bc}")} else {bc.into()};
            add_event(s,line,"info","IDENTIF",format!("CB2 identifie {detail}"),format!("lot:{lot}"));
        } else {add_event(s,line,"warning","IDENTIF",format!("CB2 identifie {bc} sans boite T3"),format!("C5:{}",s.C5));}
    }
    if let Some(c)=CB2_NBOITE.captures(text) {
        let id_b=n(&c,1);
        if let Some(target)=ensure_reader(s,"CB2","") {
            target.id_b=id_b;remember_box(ctx,id_b,target);
            let reference=if target.barcode.is_empty() {target.source_ref.clone()} else {target.barcode.clone()};
            add_event(s,line,"info","IDENTIF",format!("CB2 identifie idB={id_b} -> {reference}"),"");
        } else {add_event(s,line,"warning","IDENTIF",format!("Nboite={id_b} sans boite T3"),format!("C5:{}",s.C5));}
    }
    if let Some(c)=CB2_DIRECT_IDENTIF.captures(text) {
        let (bc,id_b)=(&c[1],n(&c,2));
        if let Some(target)=ensure_reader(s,"CB2",bc) {
            apply_identity(target,bc,"","",None,line,"CB2",true);target.id_b=id_b;remember_box(ctx,id_b,target);
            add_event(s,line,"info","IDENTIF",format!("CB2 identifie idB={id_b} -> {bc}"),"");
        } else {add_event(s,line,"warning","IDENTIF",format!("Identification CB2 directe sans boite T3 {bc}"),format!("Nboite:{id_b} C5:{}",s.C5));}
    }
    if (text.contains("T2: une boite est charg") || text.contains("BOITE-LOAD")) && s.box_in_EA.is_none() {
        s.box_in_EA=Some(BoxInfo {color:box_color("0"),..BoxInfo::default()});
    }
    if text.contains("le transfert (EA->T3) est termin") {
        if let Some(b)=s.box_in_EA.take() {
            let barcode=if b.barcode.is_empty() {"boite".to_owned()} else {b.barcode.clone()};
            s.box_on_T3=Some(b);add_event(s,line,"info","TRANSFERT",format!("EA vers T3 {barcode}"),"");
        }
    }
    if let Some(c)=T3_T4_FIN_IDB.captures(text) {
        let length=c[1].replace(',',".").parse::<f64>().unwrap_or(0.0);let id_b=n(&c,2);
        if s.box_on_T4.is_none() && s.box_on_T3.is_none() {s.box_on_T3=ctx.idb_to_box.get(&id_b).cloned();}
        if s.box_on_T4.is_none() {
            if let Some(mut b)=s.box_on_T3.take() {
                if length>0.0 {b.length_mm=length.round_ties_even() as i64;}s.box_on_T4=Some(b);
            }
        }
        if let Some(b)=s.box_on_T4.as_mut() {
            b.id_b=id_b;if length>0.0 {b.length_mm=length.round_ties_even() as i64;b.measured_t4_length_mm=b.length_mm;}
            remember_box(ctx,id_b,b);
            let detail=if b.barcode.is_empty() {b.source_ref.clone()} else {b.barcode.clone()};
            add_event(s,line,"info","TRANSFERT",format!("T3->T4 idB={id_b}"),detail);
        }
    }
    if let Some(c)=T4_T5_REQUEST.captures(text) {ctx.t4_t5_requested_ref=Some(c[1].into());}
    if text.contains("la boite est rendu (physiquement) sur T5") {
        ctx.pending_t5_creation_box=None;ctx.pending_t4_length_transfer=None;
        let reference=ctx.t4_t5_requested_ref.take();
        if reference.as_deref()==Some("") && s.box_on_T4.as_ref().is_some_and(|b|!b.barcode.is_empty()) {s.box_on_T4=Some(BoxInfo::default());}
        let id_b=s.box_on_T4.as_ref().map_or(0,|b|b.id_b);ctx.pending_t4_length_idb=Some(id_b);ctx.pending_t4_length_ida=None;
        let label=box_label(s.box_on_T4.as_ref());
        if let Some(b)=s.box_on_T4.as_ref() {
            let previous=b.clone();
            let idx=if let Some(i)=find_t5(s,0,b.id_b,"") {i} else {
                let mut new=BoxInfo {barcode:b.barcode.clone(),source_ref:b.source_ref.clone(),name:b.name.clone(),lot:b.lot.clone(),
                    length_mm:b.length_mm,width_mm:b.width_mm,height_mm:b.height_mm,t5_footprint_mm:b.t5_footprint_mm,
                    id_b:b.id_b,id_alpha:b.id_alpha,color:b.color.clone(),..BoxInfo::default()};
                copy_dimension_tracking(&mut new,b);s.boxes_on_T5.push(new);s.boxes_on_T5.len()-1
            };
            let b=&mut s.boxes_on_T5[idx];b.x_pos=1060;b.t5_visual_x_pos=0;b.t5_entry_aligned=true;b.t5_after_c9=false;
            copy_dimension_tracking(b,&previous);b.t5_transfer_id=line;
            ctx.pending_t5_creation_box=Some(b.clone());ctx.pending_t4_length_transfer=Some(line);
        }
        add_event(s,line,"info","TRANSFERT",format!("T4 vers T5 {label}"),"");s.box_on_T4=None;
    }
    if let Some(c)=AJOUT_T5_ID.captures(text) {
        let (id_a,id_b)=(n(&c,1),n(&c,2));ctx.idb_to_ida.insert(id_b,id_a);ctx.ida_to_idb.insert(id_a,id_b);
        if let Some(i)=find_t5(s,id_a,id_b,"") {
            let b=&mut s.boxes_on_T5[i];b.id_alpha=id_a;b.id_b=id_b;
            let detail=if b.barcode.is_empty() {b.source_ref.clone()} else {b.barcode.clone()};
            add_event(s,line,"info","TRANSFERT",format!("T4->T5 idB={id_b} -> IdA={id_a}"),detail);
        }
    }
    if let Some(c)=T4_LENGTH_SUMMARY.captures(text) {
        let (bdd,t2t,t4c,t4t,diff)=(n(&c,1),n(&c,2),n(&c,3),n(&c,4),n(&c,5));
        if let Some(i)=find_t4_measure(s,ctx) {
            let b=&mut s.boxes_on_T5[i];
            if bdd>0 && b.bdd_length_mm==0 {b.bdd_length_mm=bdd;b.bdd_reference=b.identified_barcode.clone();b.bdd_source_line=line;}
            b.measured_t4_length_mm=t4c;b.measured_t4t_length_mm=t4t;b.measured_t4_diff_mm=Some(diff);b.measured_t4_line=line;classify(b);
        }
        ctx.pending_t4_length_idb=None;ctx.pending_t4_length_ida=None;ctx.pending_t4_length_transfer=None;
        add_event(s,line,if diff.abs()>10 {"warning"} else {"info"},"T4",format!("Controle longueur T4 diff {diff}mm"),format!("BdD:{bdd} T2T:{t2t} T4C:{t4c} T4T:{t4t}"));
    }
    if let Some(c)=C1_SENSOR.captures(text) {s.C1=n(&c,1);}
    if let Some(c)=POUBELLE.captures(text) {s.flag_poubelle_pleine=if matches!(c[1].to_lowercase().as_str(),"faux"|"0"|"false"|"non") {0} else {1};}
    if let Some(c)=LZB.captures(text) {s.lzb=n(&c,1);}
    if ERROR_WORD.is_match(text) && ctx.seen_error_lines.insert(line) {add_event(s,line,"warning","TRACE","Message erreur trace",text.trim());}
    if s.t5_active_id_alpha!=0 && !s.boxes_on_T5.iter().any(|b|b.id_alpha==s.t5_active_id_alpha) {
        s.t5_active_id_alpha=0;commit_visual(s);
    }
    track_signals(s,line,ctx);
    // Les pointeurs Python de contexte suivent les boites encore actives.
    for b in [&s.box_in_EA,&s.box_on_T3,&s.box_on_T4].into_iter().flatten() {
        if let Some(aliases)=ctx.object_aliases.get(&b.parser_object_id) {
            for id_b in aliases {ctx.idb_to_box.insert(*id_b,b.clone());}
        }
    }
    if let Some(saved)=ctx.pending_t5_creation_box.as_mut() {
        if let Some(b)=s.boxes_on_T5.iter().find(|b|b.parser_object_id==saved.parser_object_id) {*saved=b.clone();}
    }
}

const KEYWORDS: &[&str] = &["T0:","T1:","T2:","tEA-T3","tT3/T4","tT4*T5","T5:","BdD:","sur T5","Rech.","-->",
    "idCB1","idCB2","CB1:","CB2:","boite est charg","BOITE-LOAD","EA->T3","rendu","supp.","suppression","Suppr.",
    "Déplace","MAJ (BUTEE","MAJ (APRES","ALPHA:T5-LIST-PACK","Création","AjoutBtT5","DeplBtSurT5", "capteurC1",
    "FlagPoubelle","LzB","longueur boite","mesure de longueur","tassement","diffT4","CubeStop","version logiciel VBalpha:"];

fn latin1(raw: &[u8]) -> String {raw.iter().map(|v|char::from(*v)).collect()}

fn flush_block(output: &Path, frames: &mut Vec<MachineState>, result: &mut ParseResult) -> Result<(),String> {
    if frames.is_empty() {return Ok(());}
    let filename=format!("block-{:06}.msgpack",result.blocks.len());
    let data=rmp_serde::to_vec_named(frames).map_err(|e|format!("Encodage des frames : {e}"))?;
    fs::write(output.join(&filename),data).map_err(|e|format!("Ecriture du bloc : {e}"))?;
    result.frame_count+=frames.len() as u64;result.blocks.push(filename);frames.clear();Ok(())
}

pub fn parse_file(path: &Path, output_dir: &Path) -> Result<ParseResult,String> {
    fs::create_dir_all(output_dir).map_err(|e|format!("Dossier des frames : {e}"))?;
    let mut source=BufReader::new(File::open(path).map_err(|e|format!("Lecture trace : {e}"))?);
    let mut previous=BufReader::new(File::open(path).map_err(|e|format!("Lecture trace : {e}"))?);
    let mut openings: HashMap<Vec<u8>,Vec<(u64,u64)>>=HashMap::new();
    let mut result=ParseResult {frame_count:0,line_count:0,duplicate_ranges:Vec::new(),blocks:Vec::new()};
    let mut frames=Vec::with_capacity(500);let mut state=MachineState::default();let mut ctx=Context::default();
    let (mut current_ts,mut first_ts)=(None,None);let mut raw=Vec::new();
    loop {
        let offset=source.stream_position().map_err(|e|e.to_string())?;
        raw.clear();if source.read_until(b'\n',&mut raw).map_err(|e|e.to_string())?==0 {break;}
        result.line_count+=1;
        let decoded=latin1(&raw);
        if OPENING.is_match(&raw) {
            let resume=source.stream_position().map_err(|e|e.to_string())?;let mut duplicate=false;
            if let Some(candidates)=openings.get(&raw) {
                for (old_offset,old_line) in candidates {
                    previous.seek(SeekFrom::Start(*old_offset)).map_err(|e|e.to_string())?;
                    source.seek(SeekFrom::Start(offset)).map_err(|e|e.to_string())?;
                    let (mut count,mut stamps)=(0u64,0u64);
                    let (mut candidate,mut prior)=(Vec::new(),Vec::new());
                    while previous.stream_position().map_err(|e|e.to_string())?<offset {
                        let position=source.stream_position().map_err(|e|e.to_string())?;
                        candidate.clear();prior.clear();
                        let size=source.read_until(b'\n',&mut candidate).map_err(|e|e.to_string())?;
                        previous.read_until(b'\n',&mut prior).map_err(|e|e.to_string())?;
                        if size==0 || candidate!=prior {source.seek(SeekFrom::Start(position)).map_err(|e|e.to_string())?;break;}
                        count+=1;stamps+=u64::from(STAMP.is_match(&candidate));
                    }
                    if stamps>=3 {
                        result.duplicate_ranges.push(DuplicateRange {first_line:result.line_count,
                            last_line:result.line_count+count-1,source_first_line:*old_line});
                        result.line_count+=count-1;duplicate=true;break;
                    }
                }
            }
            if duplicate {continue;}
            source.seek(SeekFrom::Start(resume)).map_err(|e|e.to_string())?;
            openings.entry(raw.clone()).or_default().push((offset,result.line_count));
        }
        if !decoded.contains('|') {continue;}
        let text_line=decoded.trim_end_matches(['\r','\n']);
        let Some(c)=HDR.captures(text_line) else {continue;};
        let ts=(n(&c,1)*86400+n(&c,2)*3600+n(&c,3)*60+n(&c,4)) as f64+n(&c,5) as f64*0.1;
        let stamp=format!("{}:{}:{}",&c[2],&c[3],&c[4]);
        if first_ts.is_none() {
            first_ts=Some(ts);current_ts=Some(ts);state.timestamp=0.0;state.timestamp_str=stamp.clone();state.line_num=result.line_count;
        }
        if current_ts!=Some(ts) {
            frames.push(state.clone());if frames.len()==500 {flush_block(output_dir,&mut frames,&mut result)?;}
            state.timestamp=ts-first_ts.unwrap_or(ts);state.timestamp_str=stamp;state.line_num=result.line_count;
            state.raw_lines.clear();state.events.clear();current_ts=Some(ts);
        }
        let text=&c[6];let known=KEYWORDS.iter().any(|k|text.contains(k));
        state.raw_lines.push((result.line_count,text.trim_end().into(),known));
        if known {update(&mut state,text,&mut ctx,result.line_count);}
    }
    if current_ts.is_some() {frames.push(state);}
    flush_block(output_dir,&mut frames,&mut result)?;
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn visual_commit_preserves_large_alpha_coordinates() {
        let mut state=MachineState {t5_x_butee:4125,t5_visual_offset_mm:50,
            boxes_on_T5:vec![BoxInfo {x_pos:4125,..BoxInfo::default()},BoxInfo {x_pos:4400,t5_after_c9:true,..BoxInfo::default()}],
            ..MachineState::default()};
        commit_visual(&mut state);
        assert_eq!(state.t5_visual_offset_mm,0);
        assert_eq!(state.boxes_on_T5[0].t5_visual_x_pos,4175);
        assert_eq!(state.boxes_on_T5[1].t5_visual_x_pos,4450);
        assert_eq!(state.boxes_on_T5[0].x_pos,4125);
    }

    #[test]
    fn identity_provenance_and_strict_height_threshold() {
        let mut b=BoxInfo::default();
        apply_identity(&mut b,"DEMO","","",Some([76,62,110]),1,"BdD",false);
        assert_eq!(b.camera_identity_line,0);
        apply_identity(&mut b,"DEMO","","",None,2,"CB2",true);
        b.measured_t4_line=3;b.measured_t4_length_mm=110;b.measured_t5_width_mm=76;b.measured_t5_height_mm=64;
        classify(&mut b);assert_eq!(b.measurement_status,"ok");
        b.measured_t5_height_mm=65;classify(&mut b);assert_eq!(b.measurement_status,"height");
        apply_identity(&mut b,"OTHER","","",None,4,"CB2",true);
        classify(&mut b);assert!(b.identity_conflict);assert_eq!(b.measurement_status,"");
        assert_eq!(b.camera_identity_line,2);
    }

    #[test]
    fn context_aliases_follow_pre_t5_objects_only() {
        let mut s=MachineState {C5:1,..MachineState::default()};let mut ctx=Context::default();
        update(&mut s,"idCB2: --> Ref:DEMO lot: LOT",&mut ctx,1);
        update(&mut s,"idCB2: (Nboite= 1)",&mut ctx,2);
        update(&mut s,"idCB2: (Nboite= 2)",&mut ctx,3);
        assert_eq!(ctx.idb_to_box[&1].id_b,2);
        update(&mut s,"transfert T3->T4 termine longueur=110 mm idB=2",&mut ctx,4);
        update(&mut s,"la boite est rendu (physiquement) sur T5",&mut ctx,5);
        update(&mut s,"longueur boite (BdD)=110 (T2T)=109 (T4C)=111 (T4T)=112 diffT4=1mm",&mut ctx,6);
        assert_eq!(s.boxes_on_T5[0].measured_t4_line,6);
        assert_eq!(ctx.idb_to_box[&2].measured_t4_line,0);
    }

    #[test]
    fn parser_object_identity_stays_out_of_protocol() {
        let b=BoxInfo::default();
        let value=serde_json::to_value(&b).unwrap();
        assert!(value.get("parser_object_id").is_none());
        assert_eq!(value.as_object().unwrap().len(),38);
    }
}
