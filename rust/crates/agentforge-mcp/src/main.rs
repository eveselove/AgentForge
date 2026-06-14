use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::io::{self, AsyncBufReadExt, AsyncWriteExt, BufReader};

#[derive(Deserialize, Debug)]
struct RpcRequest {
    jsonrpc: String,
    id: Option<Value>,
    method: String,
    #[serde(default)]
    params: Value,
}

#[derive(Serialize, Debug)]
struct RpcResponse {
    jsonrpc: String,
    id: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<Value>,
}

#[tokio::main]
async fn main() {
    let stdin = io::stdin();
    let mut stdout = io::stdout();
    let mut reader = BufReader::new(stdin).lines();
    let client = Client::new();
    let api_base =
        std::env::var("AGENTFORGE_API").unwrap_or_else(|_| "http://127.0.0.1:9090".to_string());

    while let Ok(Some(line)) = reader.next_line().await {
        let req: Result<RpcRequest, _> = serde_json::from_str(&line);
        if let Ok(request) = req {
            if let Some(id) = request.id.clone() {
                let result =
                    handle_request(&client, &request.method, request.params, &api_base).await;
                let response = match result {
                    Ok(res) => RpcResponse {
                        jsonrpc: "2.0".to_string(),
                        id,
                        result: Some(res),
                        error: None,
                    },
                    Err(e) => RpcResponse {
                        jsonrpc: "2.0".to_string(),
                        id,
                        result: None,
                        error: Some(json!({
                            "code": -32603,
                            "message": e.to_string(),
                        })),
                    },
                };
                let out = serde_json::to_string(&response).unwrap() + "\n";
                let _ = stdout.write_all(out.as_bytes()).await;
                let _ = stdout.flush().await;
            }
        }
    }
}

async fn handle_request(
    client: &Client,
    method: &str,
    params: Value,
    api_base: &str,
) -> Result<Value, Box<dyn std::error::Error>> {
    match method {
        "initialize" => Ok(json!({
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "agentforge-rust-mcp",
                "version": "1.0.0"
            }
        })),
        "notifications/initialized" => Ok(json!({})),
        "tools/list" => Ok(json!({
            "tools": [
                {
                    "name": "agentforge_list_tasks",
                    "description": "List tasks from AgentForge queue",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "status": { "type": "string" }
                        }
                    }
                },
                {
                    "name": "agentforge_create_task",
                    "description": "Create a new AgentForge task",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "title": { "type": "string" },
                            "description": { "type": "string" },
                            "priority": { "type": "string" },
                            "complexity": { "type": "string" },
                            "tags": { "type": "array", "items": { "type": "string" } }
                        },
                        "required": ["title"]
                    }
                },
                {
                    "name": "agentforge_get_task",
                    "description": "Get task details by ID",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "task_id": { "type": "string" }
                        },
                        "required": ["task_id"]
                    }
                },
                {
                    "name": "agentforge_dispatch_task",
                    "description": "Dispatch task to agent",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "task_id": { "type": "string" },
                            "agent": { "type": "string" }
                        },
                        "required": ["task_id", "agent"]
                    }
                },
                {
                    "name": "agentforge_update_task",
                    "description": "Update task status",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "task_id": { "type": "string" },
                            "status": { "type": "string" },
                            "result": { "type": "string" }
                        },
                        "required": ["task_id", "status"]
                    }
                },
                {
                    "name": "agentforge_metrics",
                    "description": "Get system metrics",
                    "inputSchema": {
                        "type": "object",
                        "properties": {}
                    }
                }
            ]
        })),
        "tools/call" => {
            let tool_name = params.get("name").and_then(|v| v.as_str()).unwrap_or("");
            let args = params.get("arguments").cloned().unwrap_or(json!({}));

            let output = match tool_name {
                "agentforge_list_tasks" => {
                    let mut url = format!("{}/tasks", api_base);
                    if let Some(status) = args.get("status").and_then(|s| s.as_str()) {
                        url = format!("{}?status={}", url, status);
                    }
                    let res = client.get(&url).send().await?.text().await?;
                    let parsed: Value = serde_json::from_str(&res).unwrap_or(json!({"error": res}));

                    let mut text = String::new();
                    if let Some(tasks) = parsed.get("tasks").and_then(|t| t.as_array()) {
                        text.push_str(&format!("📋 Найдено задач: {}\n\n", tasks.len()));
                        for task in tasks {
                            let id = task.get("id").and_then(|i| i.as_str()).unwrap_or("")[0..8]
                                .to_string();
                            let st = task
                                .get("status")
                                .and_then(|s| s.as_str())
                                .unwrap_or("unknown");
                            let desc = task
                                .get("description")
                                .and_then(|d| d.as_str())
                                .unwrap_or("");
                            let desc_short = desc
                                .lines()
                                .next()
                                .unwrap_or("")
                                .chars()
                                .take(80)
                                .collect::<String>();
                            let ag = task
                                .get("assigned_agent")
                                .and_then(|a| a.as_str())
                                .unwrap_or("None");
                            text.push_str(&format!(
                                "- [{}] {}... | статус: {} | агент: {}\n",
                                id, desc_short, st, ag
                            ));
                        }
                    } else {
                        text = res;
                    }
                    text
                }
                "agentforge_get_task" => {
                    let task_id = args.get("task_id").and_then(|v| v.as_str()).unwrap_or("");
                    client
                        .get(&format!("{}/tasks/{}", api_base, task_id))
                        .send()
                        .await?
                        .text()
                        .await?
                }
                "agentforge_create_task" => {
                    client
                        .post(&format!("{}/tasks", api_base))
                        .json(&args)
                        .send()
                        .await?
                        .text()
                        .await?
                }
                "agentforge_dispatch_task" => {
                    let task_id = args.get("task_id").and_then(|v| v.as_str()).unwrap_or("");
                    let agent = args.get("agent").and_then(|v| v.as_str()).unwrap_or("");
                    client
                        .post(&format!("{}/tasks/{}/dispatch", api_base, task_id))
                        .json(&json!({"agent": agent}))
                        .send()
                        .await?
                        .text()
                        .await?
                }
                "agentforge_update_task" => {
                    let task_id = args.get("task_id").and_then(|v| v.as_str()).unwrap_or("");
                    let mut payload = args.clone();
                    if let Some(obj) = payload.as_object_mut() {
                        obj.remove("task_id");
                    }
                    client
                        .patch(&format!("{}/tasks/{}", api_base, task_id))
                        .json(&payload)
                        .send()
                        .await?
                        .text()
                        .await?
                }
                "agentforge_metrics" => {
                    client
                        .get(&format!("{}/metrics", api_base))
                        .send()
                        .await?
                        .text()
                        .await?
                }
                _ => format!("Unknown tool: {}", tool_name),
            };

            Ok(json!({
                "content": [
                    {
                        "type": "text",
                        "text": output
                    }
                ]
            }))
        }
        _ => Err(format!("Method not found: {}", method).into()),
    }
}
