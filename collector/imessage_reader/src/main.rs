//! Thin read-only JSON adapter over `imessage_database`.
//! Never writes to chat.db. Does not log message bodies.

use clap::Parser;
use rusqlite::Connection;
use imessage_database::{
    tables::{
        handle::Handle,
        messages::Message,
        table::{get_connection, Cacheable, Table},
    },
    util::dates::{get_local_time, get_offset},
};
use serde::Serialize;
use std::collections::HashMap;
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(about = "Read macOS Messages in JSON for the local spending tracker")]
struct Args {
    #[arg(long)]
    db_path: PathBuf,
    #[arg(long, default_value_t = 0)]
    after_id: i32,
    #[arg(long, default_value_t = 100)]
    limit: i32,
    #[arg(long, default_value_t = false)]
    incoming_only: bool,
    #[arg(long, default_value_t = false)]
    list_senders: bool,
}

#[derive(Serialize)]
struct OutMessage {
    id: i32,
    guid: String,
    sender: String,
    text: String,
    timestamp: String,
    service: String,
    is_from_me: bool,
}

#[derive(Serialize)]
struct OutSender {
    sender: String,
    count: i64,
}

fn main() {
    let args = Args::parse();
    let db = match get_connection(&args.db_path) {
        Ok(conn) => conn,
        Err(err) => {
            eprintln!("Failed to open Messages database READ ONLY: {err}");
            std::process::exit(2);
        }
    };

    if args.list_senders {
        list_senders(&db);
        return;
    }

    let handles = Handle::cache(&db).unwrap_or_default();
    let offset = get_offset();
    let sql = r#"
        SELECT
            *,
            c.chat_id,
            (SELECT COUNT(*) FROM message_attachment_join a WHERE m.ROWID = a.message_id) as num_attachments,
            NULL as deleted_from,
            0 as num_replies
        FROM message as m
        LEFT JOIN chat_message_join as c ON m.ROWID = c.message_id
        WHERE m.ROWID > ?1
          AND (?2 = 0 OR m.is_from_me = 0)
        ORDER BY m.ROWID ASC
        LIMIT ?3
    "#;

    let mut statement = match db.prepare(sql) {
        Ok(stmt) => stmt,
        Err(err) => {
            eprintln!("Query failed: {err}");
            std::process::exit(3);
        }
    };

    let incoming_flag: i32 = if args.incoming_only { 1 } else { 0 };
    let rows = match Message::rows(&mut statement, [args.after_id, incoming_flag, args.limit]) {
        Ok(iter) => iter,
        Err(err) => {
            eprintln!("Row mapping failed: {err}");
            std::process::exit(3);
        }
    };

    let mut out = Vec::new();
    for row in rows {
        let mut message = match row {
            Ok(msg) => msg,
            Err(_) => continue,
        };
        if let Ok(body) = message.parse_body(&db) {
            message.apply_body(body);
        }
        let sender = resolve_sender(&message, &handles);
        let timestamp = get_local_time(message.date, offset)
            .map(|dt| dt.to_rfc3339())
            .unwrap_or_else(|_| "1970-01-01T00:00:00+00:00".to_string());
        out.push(OutMessage {
            id: message.rowid,
            guid: message.guid.clone(),
            sender,
            text: message.text.clone().unwrap_or_default(),
            timestamp,
            service: message.service().to_string(),
            is_from_me: message.is_from_me,
        });
    }

    println!("{}", serde_json::to_string(&out).unwrap());
}

fn resolve_sender(message: &Message, handles: &HashMap<i32, String>) -> String {
    message
        .handle_id
        .and_then(|id| handles.get(&id).cloned())
        .unwrap_or_default()
}

fn list_senders(db: &Connection) {
    let sql = r#"
        SELECT COALESCE(h.id, '') AS sender, COUNT(*) AS message_count
        FROM message AS m
        LEFT JOIN handle AS h ON m.handle_id = h.ROWID
        WHERE m.is_from_me = 0 AND COALESCE(h.id, '') != ''
        GROUP BY h.id
        ORDER BY message_count DESC, sender ASC
    "#;
    let mut statement = db.prepare(sql).expect("sender query");
    let rows = statement
        .query_map([], |row| {
            Ok(OutSender {
                sender: row.get(0)?,
                count: row.get(1)?,
            })
        })
        .expect("sender rows");
    let mut out = Vec::new();
    for row in rows.flatten() {
        out.push(row);
    }
    println!("{}", serde_json::to_string(&out).unwrap());
}
