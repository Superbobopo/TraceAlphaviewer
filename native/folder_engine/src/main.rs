mod catalog;
pub mod model;
pub mod parser;

use rayon::prelude::*;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{fs, io::{self, Write}, path::{Path, PathBuf}, sync::Mutex};

const PROTOCOL_VERSION: u32 = 1;

#[derive(Deserialize)]
struct Request {
    protocol_version: u32,
    job_id: Value,
    operation: String,
    #[serde(default)]
    path: String,
    #[serde(default)]
    session: String,
    #[serde(default)]
    sources: Vec<Value>,
}

fn emit(job_id: &Value, kind: &str, payload: Value) {
    let stdout = io::stdout();
    let mut output = stdout.lock();
    let _ = serde_json::to_writer(&mut output, &json!({
        "protocol_version": PROTOCOL_VERSION, "job_id": job_id, "kind": kind, "payload": payload,
    }));
    let _ = output.write_all(b"\n");
    let _ = output.flush();
}

fn concurrency() -> usize {
    std::thread::available_parallelism().map(|n| n.get().saturating_sub(1).clamp(1, 4)).unwrap_or(1)
}

fn run(request: &Request) -> Result<(), String> {
    if request.protocol_version != PROTOCOL_VERSION {
        return Err("Version du protocole du moteur dossier incompatible".into());
    }
    let pool = rayon::ThreadPoolBuilder::new().num_threads(concurrency()).build().map_err(|e| e.to_string())?;
    match request.operation.as_str() {
        "catalog" => {
            let result = catalog::catalog(Path::new(&request.path), &pool, |done, total| {
                emit(&request.job_id, "progress", json!({"phase":"catalog", "done":done,"total":total}));
            })?;
            emit(&request.job_id, "catalog", serde_json::to_value(result).map_err(|e| e.to_string())?);
        }
        "parse_group" => {
            if request.sources.is_empty() || request.session.is_empty() {
                return Err("Le groupe ou le répertoire de session est vide".into());
            }
            let session = PathBuf::from(&request.session);
            fs::create_dir_all(&session).map_err(|e| e.to_string())?;
            let completed = Mutex::new(0usize);
            let results: Vec<Result<Value, String>> = pool.install(|| request.sources.par_iter().enumerate().map(|(index, source)| {
                let filepath = source.get("filepath").or_else(|| source.get("path")).and_then(Value::as_str)
                    .ok_or_else(|| "Chemin de trace absent".to_string())?;
                let store = session.join("segments").join(format!("{index:06}"));
                fs::create_dir_all(&store).map_err(|e| e.to_string())?;
                let snapshot = catalog::verify_source_before(Path::new(filepath), source.get("fingerprint").and_then(Value::as_str))?;
                let parsed = parser::parse_file(Path::new(filepath), &store)?;
                catalog::verify_source_after(Path::new(filepath), &snapshot)?;
                let mut row = source.clone();
                if !row.is_object() { return Err("Source de trace invalide".into()); }
                let object = row.as_object_mut().unwrap();
                let parsed_value = serde_json::to_value(parsed).map_err(|e| e.to_string())?;
                for (key, value) in parsed_value.as_object().ok_or("Résultat du parser invalide")? {
                    object.insert(key.clone(), value.clone());
                }
                object.insert("store".into(), json!(store));
                object.insert("segment_index".into(), json!(index));
                let mut done = completed.lock().map_err(|e| e.to_string())?;
                *done += 1;
                emit(&request.job_id, "progress", json!({"phase":"parse","done":*done,"total":request.sources.len()}));
                Ok(row)
            }).collect());
            let sources: Vec<Value> = results.into_iter().collect::<Result<_, _>>()?;
            let result = json!({"protocol_version":PROTOCOL_VERSION,"session":session,"sources":sources});
            let manifest = session.join("native-manifest.json");
            fs::write(&manifest, serde_json::to_vec_pretty(&result).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
            let mut result = result;
            result["manifest_path"] = json!(manifest);
            emit(&request.job_id, "result", result);
        }
        _ => return Err("Opération du moteur dossier inconnue".into()),
    }
    emit(&request.job_id, "done", json!({}));
    Ok(())
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(String::as_str) == Some("--version") {
        println!("{}", json!({"name":"tracealpha-folder-worker","version":env!("CARGO_PKG_VERSION"),"protocol_version":PROTOCOL_VERSION}));
        return;
    }
    let result = (|| -> Result<(), String> {
        if args.len() != 3 || args[1] != "--request" { return Err("Utilisation : --request <fichier JSON>".into()); }
        let bytes = fs::read(&args[2]).map_err(|e| e.to_string())?;
        let request: Request = serde_json::from_slice(bytes.strip_prefix(&[0xef, 0xbb, 0xbf]).unwrap_or(&bytes)).map_err(|e| e.to_string())?;
        match run(&request) {
            Ok(()) => Ok(()),
            Err(message) => {
                emit(&request.job_id, "error", json!({"message":message}));
                Err(message)
            }
        }
    })();
    if let Err(message) = result {
        eprintln!("{message}");
        std::process::exit(1);
    }
}
