use chrono::{Datelike, Duration, NaiveDate, NaiveDateTime};
use rayon::prelude::*;
use regex::Regex;
use serde::{Serialize, Serializer};
use std::{collections::{BTreeMap, BTreeSet, hash_map::DefaultHasher}, fs::{self, File}, hash::Hasher,
    io::{BufRead, BufReader, Read}, path::{Path, PathBuf}, sync::{Mutex, OnceLock}};

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct Identity {
    pub alpha_database: String,
    pub pharmacy_database: String,
    pub alpha_number: Option<String>,
    pub pharmacy: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct Source {
    pub filepath: String,
    pub line_count: u64,
    pub bytes: u64,
    pub identity: Option<Identity>,
    pub alpha_databases: Vec<String>,
    pub pharmacy_databases: Vec<String>,
    pub start: Option<String>,
    pub end: Option<String>,
    pub start_timestamp: Option<f64>,
    pub end_timestamp: Option<f64>,
    pub status: String,
    pub issues: Vec<String>,
    pub duplicate_of: Option<String>,
    #[serde(serialize_with = "serialize_fingerprint")]
    fingerprint: u64,
    #[serde(skip)]
    dated_headers: Vec<String>,
    #[serde(skip)]
    timestamp_count: u64,
}

#[derive(Debug, Serialize)]
pub struct Group {
    pub id: String,
    pub label: String,
    pub identity: Option<Identity>,
    pub sources: Vec<Source>,
    pub duplicates: Vec<Source>,
    pub start: Option<String>,
    pub end: Option<String>,
    pub status: String,
    pub issues: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct Catalog {
    pub path: String,
    pub files: usize,
    pub ignored_files: usize,
    pub issues: Vec<String>,
    pub groups: Vec<Group>,
}

fn serialize_fingerprint<S: Serializer>(value: &u64, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_str(&format!("{value:016x}"))
}

fn changed(path: &Path) -> String {
    format!("La trace {} a changé depuis le catalogue. Rouvrez le dossier avant son analyse.", path.display())
}

pub fn verify_source_before(path: &Path, expected: Option<&str>) -> Result<fs::Metadata, String> {
    let metadata = fs::metadata(path).map_err(|e| format!("Lecture de la trace {} impossible : {e}", path.display()))?;
    if let Some(expected) = expected {
        let mut file = BufReader::new(File::open(path).map_err(|e| e.to_string())?);
        let mut fingerprint = DefaultHasher::new();
        let mut buffer = [0; 65536];
        loop {
            let size = file.read(&mut buffer).map_err(|e| e.to_string())?;
            if size == 0 { break; }
            fingerprint.write(&buffer[..size]);
        }
        if format!("{:016x}", fingerprint.finish()) != expected { return Err(changed(path)); }
        verify_source_after(path, &metadata)?;
    }
    Ok(metadata)
}

pub fn verify_source_after(path: &Path, before: &fs::Metadata) -> Result<(), String> {
    let after = fs::metadata(path).map_err(|_| changed(path))?;
    if before.len() != after.len() || before.modified().ok() != after.modified().ok() {
        return Err(changed(path));
    }
    Ok(())
}

fn bases() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r#"(?i)\b(BASEALPHA(?:2)?_[^\\/:*?"<>|\r\n']*?\.MDB|BASEFIC[^\\/:*?"<>|\r\n']*?\.MDB)\b"#).unwrap())
}

fn timestamp() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^\s*[*L ]?\s*(\d{1,2})\|(\d{2}):(\d{2}):(\d{2})\.(\d+)").unwrap())
}

fn header_date(text: &str) -> Option<NaiveDate> {
    let upper = text.to_uppercase();
    if !(upper.contains("OUVERTURE DE LA TRACE") || upper.contains("ATION DE LA TRACE")) { return None; }
    static RE: OnceLock<Regex> = OnceLock::new();
    let captures = RE.get_or_init(|| Regex::new(r"\ble\s+(\d{2}/\d{2}/\d{4})\b").unwrap()).captures(text)?;
    NaiveDate::parse_from_str(&captures[1], "%d/%m/%Y").ok()
}

fn title_case(value: &str) -> String {
    value.split_whitespace().map(|word| {
        let mut chars = word.chars();
        match chars.next() { Some(first) => first.to_uppercase().collect::<String>() + &chars.as_str().to_lowercase(), None => String::new() }
    }).collect::<Vec<_>>().join(" ")
}

fn identity(alpha: &BTreeSet<String>, pharmacy: &BTreeSet<String>) -> Option<Identity> {
    if alpha.len() != 1 || pharmacy.len() != 1 { return None; }
    let a = alpha.first()?.clone();
    let p = pharmacy.first()?.clone();
    static NUMBER: OnceLock<Regex> = OnceLock::new();
    let number = NUMBER.get_or_init(|| Regex::new(r"^BASEALPHA(?:2)?_#?(?:\d{4}\.)?(\d+)\.MDB$").unwrap())
        .captures(&a).map(|m| m[1].to_string());
    let pharmacy_name = p.strip_prefix("BASEFIC").unwrap_or(&p).strip_suffix(".MDB").unwrap_or(&p);
    let pharmacy_name = pharmacy_name.trim_start_matches(|c: char| c.is_ascii_digit() || c == '_' || c == '-');
    Some(Identity { alpha_database: a, pharmacy_database: p.clone(), alpha_number: number,
        pharmacy: if pharmacy_name.is_empty() { p } else { title_case(pharmacy_name) } })
}

fn empty_source(path: &Path) -> Source {
    Source { filepath: path.to_string_lossy().into(), line_count: 0, bytes: 0, identity: None,
        alpha_databases: vec![], pharmacy_databases: vec![], start: None, end: None,
        start_timestamp: None, end_timestamp: None, status: "verify".into(), issues: vec![],
        duplicate_of: None, fingerprint: 0, dated_headers: vec![], timestamp_count: 0 }
}

fn scan(path: &Path) -> Source {
    let mut source = empty_source(path);
    let file = match File::open(path) { Ok(file) => file, Err(error) => {
        source.issues.push(format!("Lecture impossible : {error}")); return source;
    }};
    let mut reader = BufReader::new(file);
    let (mut alpha, mut pharmacy) = (BTreeSet::new(), BTreeSet::new());
    let mut fingerprint = DefaultHasher::new();
    let (mut date, mut first, mut last): (Option<NaiveDate>, Option<NaiveDateTime>, Option<NaiveDateTime>) = (None, None, None);
    let mut calendar_invalid = false;
    let mut pending_first: Option<(u32, u32, u32, u32, i64)> = None;
    let mut buffer = Vec::new();
    loop {
        buffer.clear();
        match reader.read_until(b'\n', &mut buffer) {
            Ok(0) => break,
            Ok(size) => { source.bytes += size as u64; source.line_count += 1; fingerprint.write(&buffer); }
            Err(error) => { source.issues.push(format!("Lecture interrompue : {error}")); return source; }
        }
        let text: String = buffer.iter().map(|&b| b as char).collect();
        for captures in bases().captures_iter(&text) {
            let name = captures[1].to_uppercase();
            if name.starts_with("BASEALPHA") { alpha.insert(name); } else { pharmacy.insert(name); }
        }
        if let Some(header) = header_date(&text) {
            date = Some(header);
            source.dated_headers.push(text.trim_end_matches(['\r', '\n']).into());
            if first.is_none() {
                if let Some((day, h, m, s, ms)) = pending_first {
                    if header.day() == day { first = header.and_hms_opt(h, m, s).map(|d| d + Duration::milliseconds(ms)); last = first; }
                    else { calendar_invalid = true; }
                }
            }
        }
        if let Some(captures) = timestamp().captures(&text) {
            source.timestamp_count += 1;
            let values: Option<Vec<u32>> = (1..=5).map(|i| captures[i].parse::<u32>().ok()).collect();
            let Some(values) = values else { calendar_invalid = true; continue; };
            let (day, h, m, s) = (values[0], values[1], values[2], values[3]);
            // Alpha exprime la fraction en dixiemes, comme le parser historique.
            let ms = i64::from(values[4]) * 100;
            pending_first.get_or_insert((day, h, m, s, ms));
            if let Some(current) = date {
                let mut month = current.with_day(1).unwrap();
                if day < current.day() && current.day() >= 28 && day <= 3 {
                    month = (month + Duration::days(32)).with_day(1).unwrap();
                } else if day < current.day() {
                    calendar_invalid = true;
                }
                if let Some(observed) = month.with_day(day).and_then(|d| d.and_hms_opt(h, m, s)).map(|d| d + Duration::milliseconds(ms)) {
                    date = Some(observed.date());
                    first = Some(first.map_or(observed, |t| t.min(observed)));
                    last = Some(last.map_or(observed, |t| t.max(observed)));
                } else { calendar_invalid = true; }
            }
        }
    }
    source.fingerprint = fingerprint.finish();
    source.identity = identity(&alpha, &pharmacy);
    source.alpha_databases = alpha.into_iter().collect();
    source.pharmacy_databases = pharmacy.into_iter().collect();
    if source.alpha_databases.len() > 1 || source.pharmacy_databases.len() > 1 {
        source.issues.push("Identités de bases contradictoires dans ce fichier".into());
    } else if source.identity.is_none() { source.issues.push("Identité Alpha/pharmacie absente ou incomplète".into()); }
    if first.is_none() || last.is_none() || calendar_invalid {
        source.issues.push("Calendrier de trace absent ou incohérent".into());
    } else {
        source.start = first.map(|d| d.format("%Y-%m-%dT%H:%M:%S%.3f").to_string());
        source.end = last.map(|d| d.format("%Y-%m-%dT%H:%M:%S%.3f").to_string());
        source.start_timestamp = first.map(|d| d.and_utc().timestamp_millis() as f64 / 1000.0);
        source.end_timestamp = last.map(|d| d.and_utc().timestamp_millis() as f64 / 1000.0);
    }
    if source.issues.is_empty() { source.status = "ready".into(); }
    source
}

fn walk(path: &Path, files: &mut Vec<PathBuf>, ignored: &mut usize, issues: &mut Vec<String>, root: bool) -> Result<(), String> {
    let entries = match fs::read_dir(path) {
        Ok(entries) => entries,
        Err(error) if root => return Err(format!("Dossier inaccessible {} : {error}", path.display())),
        Err(error) => { *ignored += 1; issues.push(format!("Sous-dossier ignoré {} : {error}", path.display())); return Ok(()); }
    };
    for entry in entries {
        let entry = match entry { Ok(entry) => entry, Err(error) => { *ignored += 1; issues.push(format!("Entrée ignorée dans {} : {error}", path.display())); continue; } };
        let kind = match entry.file_type() { Ok(kind) => kind, Err(error) => { *ignored += 1; issues.push(format!("Entrée ignorée {} : {error}", entry.path().display())); continue; } };
        let path = entry.path();
        if kind.is_dir() {
            let name = entry.file_name().to_string_lossy().to_lowercase();
            if [".trace_work", ".git", "node_modules", ".venv", "__pycache__", "target", ".next"].contains(&name.as_str()) { *ignored += 1; continue; }
            walk(&path, files, ignored, issues, false)?;
        }
        else if kind.is_file() && path.extension().and_then(|e| e.to_str()).is_some_and(|e| e.eq_ignore_ascii_case("old") || e.eq_ignore_ascii_case("txt")) { files.push(path); }
        else { *ignored += 1; }
    }
    Ok(())
}

fn same_bytes(left: &str, right: &str) -> bool {
    let (Ok(left), Ok(right)) = (File::open(left), File::open(right)) else { return false; };
    let (mut left, mut right) = (BufReader::new(left), BufReader::new(right));
    let (mut a, mut b) = ([0u8; 65536], [0u8; 65536]);
    loop {
        match (left.read(&mut a), right.read(&mut b)) {
            (Ok(0), Ok(0)) => return true,
            (Ok(n), Ok(m)) if n == m && a[..n] == b[..m] => {},
            _ => return false,
        }
    }
}

fn group_key(source: &Source, index: usize) -> String {
    if source.status != "ready" { return format!("verify:{index:08}"); }
    let identity = source.identity.as_ref().unwrap();
    format!("{}|{}", identity.alpha_database, identity.pharmacy_database)
}

pub fn catalog(path: &Path, pool: &rayon::ThreadPool, progress: impl Fn(usize, usize) + Sync) -> Result<Catalog, String> {
    let path = fs::canonicalize(path).map_err(|e| e.to_string())?;
    let (mut files, mut ignored, mut issues) = (vec![], 0, vec![]);
    walk(&path, &mut files, &mut ignored, &mut issues, true)?;
    files.sort_by_cached_key(|p| p.to_string_lossy().to_lowercase());
    let completed = Mutex::new(0);
    let mut sources: Vec<Source> = pool.install(|| files.par_iter().map(|path| {
        let result = scan(path);
        let mut done = completed.lock().unwrap();
        *done += 1;
        progress(*done, files.len());
        result
    }).collect());
    sources.retain(|source| {
        if source.timestamp_count > 0 { return true; }
        ignored += 1;
        if !source.issues.is_empty() && source.line_count == 0 {
            issues.push(format!("Fichier ignoré {} : {}", source.filepath, source.issues.join(" ; ")));
        }
        false
    });
    let trace_files = sources.len();
    // Un hash ne suffit jamais à confirmer une copie.
    let mut fingerprints: BTreeMap<(u64, u64), Vec<usize>> = BTreeMap::new();
    for index in 0..sources.len() {
        if sources[index].dated_headers.is_empty() { continue; }
        let key = (sources[index].bytes, sources[index].fingerprint);
        if let Some(candidates) = fingerprints.get(&key) {
            for &candidate in candidates {
                if sources[index].dated_headers == sources[candidate].dated_headers && same_bytes(&sources[index].filepath, &sources[candidate].filepath) {
                    sources[index].duplicate_of = Some(sources[candidate].filepath.clone());
                    sources[index].status = "duplicate".into();
                    break;
                }
            }
        }
        if sources[index].duplicate_of.is_none() { fingerprints.entry(key).or_default().push(index); }
    }
    // Tout recouvrement non prouvé comme copie isole chacun des fichiers concernés.
    let mut ready: BTreeMap<String, Vec<usize>> = BTreeMap::new();
    for (index, source) in sources.iter().enumerate().filter(|(_, s)| s.status == "ready") {
        ready.entry(group_key(source, index)).or_default().push(index);
    }
    let mut overlaps = BTreeSet::new();
    for indices in ready.values_mut() {
        indices.sort_by(|&a, &b| sources[a].start_timestamp.partial_cmp(&sources[b].start_timestamp).unwrap());
        let mut active: Vec<usize> = vec![];
        for &index in indices.iter() {
            let start = sources[index].start_timestamp.unwrap();
            active.retain(|&other| sources[other].end_timestamp.unwrap() >= start);
            for &other in &active { overlaps.insert(other); overlaps.insert(index); }
            active.push(index);
        }
    }
    for index in overlaps {
        sources[index].status = "verify".into();
        sources[index].issues.push("Recouvrement temporel ambigu avec une autre trace : fichier isolé".into());
    }
    let mut grouped: BTreeMap<String, Vec<Source>> = BTreeMap::new();
    let duplicates: Vec<Source> = sources.iter().filter(|s| s.duplicate_of.is_some()).cloned().collect();
    for (index, source) in sources.into_iter().enumerate().filter(|(_, s)| s.duplicate_of.is_none()) {
        grouped.entry(group_key(&source, index)).or_default().push(source);
    }
    let mut groups = vec![];
    for (index, (_, mut sources)) in grouped.into_iter().enumerate() {
        sources.sort_by(|a, b| a.start_timestamp.partial_cmp(&b.start_timestamp).unwrap_or(std::cmp::Ordering::Equal).then_with(|| a.filepath.cmp(&b.filepath)));
        let identity = sources[0].identity.clone();
        let status = sources[0].status.clone();
        let mut label = identity.as_ref().map(|id| format!("{} — Pharmacie {}", id.alpha_number.as_ref().map(|n| format!("Alpha {n}")).unwrap_or_else(|| id.alpha_database.clone()), id.pharmacy)).unwrap_or_else(|| "Identité à vérifier".into());
        if status != "ready" {
            let name = Path::new(&sources[0].filepath).file_name().unwrap_or_default().to_string_lossy();
            label = if identity.is_some() { format!("{label} — Identité à vérifier ({name})") }
                else { format!("Identité à vérifier — {name}") };
        }
        let issues = sources.iter().flat_map(|s| s.issues.clone()).collect::<BTreeSet<_>>().into_iter().collect();
        let copies = duplicates.iter().filter(|copy| sources.iter().any(|s| Some(&s.filepath) == copy.duplicate_of.as_ref())).cloned().collect();
        groups.push(Group { id: format!("group-{index:06}"), label, identity, start: sources.iter().filter_map(|s| s.start.clone()).min(),
            end: sources.iter().filter_map(|s| s.end.clone()).max(), sources, duplicates: copies, status, issues });
    }
    groups.sort_by(|a, b| a.label.cmp(&b.label).then_with(|| a.start.cmp(&b.start)));
    Ok(Catalog { path: path.to_string_lossy().into(), files: trace_files, ignored_files: ignored, issues, groups })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};
    static NEXT: AtomicU64 = AtomicU64::new(0);
    fn directory() -> PathBuf {
        let path = std::env::temp_dir().join(format!("tracealpha-catalog-{}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::SeqCst)));
        fs::create_dir_all(&path).unwrap(); path
    }
    fn sample(day: u32, alpha: &str, pharmacy: &str) -> String {
        format!("creation de la trace le {day:02}/05/2026\n* {day}|08:00:00.0 OUVERTURE DE LA TRACE le {day:02}/05/2026\n {day}|08:00:00.1 ouverture de la base C:\\APOTEKA\\{alpha}\n {day}|08:00:00.2 ouverture de la base C:\\APOTEKA\\{pharmacy}\n {day}|08:01:00.0 fin\n")
    }
    #[test]
    fn groups_and_exact_duplicates() {
        let path = directory();
        fs::write(path.join("a.old"), sample(1, "BASEALPHA_#2025.031.MDB", "BASEFIC1560LAHLOU.MDB")).unwrap();
        fs::write(path.join("b.old"), sample(2, "basealpha_#2025.031.mdb", "basefic1560lahlou.mdb")).unwrap();
        fs::copy(path.join("a.old"), path.join("copy.txt")).unwrap();
        fs::write(path.join("motte.OLD"), sample(1, "BASEALPHA_#2025.009.MDB", "BASEFICMOTTE.MDB")).unwrap();
        let result = catalog(&path, &rayon::ThreadPoolBuilder::new().num_threads(2).build().unwrap(), |_, _| {}).unwrap();
        assert_eq!(result.groups.len(), 2);
        let lahlou = result.groups.iter().find(|g| g.label == "Alpha 031 — Pharmacie Lahlou").unwrap();
        assert_eq!(lahlou.sources.len(), 2); assert_eq!(lahlou.duplicates.len(), 1);
        fs::remove_dir_all(path).unwrap();
    }
    #[test]
    fn contradictions_missing_dates_and_overlap_are_isolated() {
        let path = directory();
        let sample = sample(1, "BASEALPHA2_1184VILLAUME.MDB", "BASEFIC1184VILLAUME.MDB");
        fs::write(path.join("a.old"), &sample).unwrap();
        fs::write(path.join("overlap.old"), sample.replace("fin", "autre fin")).unwrap();
        fs::write(path.join("contradiction.old"), format!("{sample} C:\\APOTEKA\\BASEALPHA_#2025.009.MDB\n")).unwrap();
        fs::write(path.join("unknown.txt"), " 01|08:00:00.0 trace sans calendrier\n").unwrap();
        let result = catalog(&path, &rayon::ThreadPoolBuilder::new().num_threads(2).build().unwrap(), |_, _| {}).unwrap();
        assert_eq!(result.groups.len(), 4);
        assert!(result.groups.iter().all(|g| g.status == "verify"));
        fs::remove_dir_all(path).unwrap();
    }
    #[test]
    fn year_rollover_uses_header() {
        let path = directory();
        fs::write(path.join("year.old"), "creation de la trace le 31/12/2025\n* 31|23:59:59.0 OUVERTURE DE LA TRACE le 31/12/2025\n 31|23:59:59.1 C:\\BASEALPHA_#2025.031.MDB C:\\BASEFICLAHLOU.MDB\nL 01|00:00:01.0 fin\n").unwrap();
        let source = scan(&path.join("year.old"));
        assert_eq!(source.end.as_deref(), Some("2026-01-01T00:00:01.000"));
        assert_eq!(source.status, "ready");
        fs::remove_dir_all(path).unwrap();
    }
    #[test]
    fn ignores_internal_directories_and_requires_accessible_root() {
        let path = directory();
        fs::create_dir_all(path.join(".trace_work")).unwrap();
        fs::write(path.join(".trace_work").join("private.old"), "ne pas cataloguer").unwrap();
        fs::write(path.join("visible.old"), sample(1, "BASEALPHA_#2025.031.MDB", "BASEFICLAHLOU.MDB")).unwrap();
        fs::write(path.join("document.txt"), "document qui n'est pas une trace").unwrap();
        let pool = rayon::ThreadPoolBuilder::new().num_threads(1).build().unwrap();
        let result = catalog(&path, &pool, |_, _| {}).unwrap();
        assert_eq!(result.files, 1); assert_eq!(result.ignored_files, 2);
        assert!(catalog(&path.join("absent"), &pool, |_, _| {}).is_err());
        fs::remove_dir_all(path).unwrap();
    }
    #[test]
    fn multi_digit_fraction_matches_parser_tenths() {
        let path = directory();
        fs::write(path.join("fraction.old"), "creation de la trace le 01/05/2026\n* 01|08:00:00.12 OUVERTURE DE LA TRACE le 01/05/2026\n 01|08:00:01.12 C:\\BASEALPHA2_#0061.MDB C:\\BASEFICLAHLOU.MDB\n").unwrap();
        let source = scan(&path.join("fraction.old"));
        assert_eq!(source.start.as_deref(), Some("2026-05-01T08:00:01.200"));
        assert_eq!(source.identity.unwrap().alpha_number.as_deref(), Some("0061"));
        fs::remove_dir_all(path).unwrap();
    }
}
