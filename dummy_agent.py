#!/usr/bin/env python3
import sys
import json
import time

def send_response(req_id, result=None, error=None):
    resp = {"jsonrpc": "2.0", "id": req_id}
    if error:
        resp["error"] = error
    else:
        resp["result"] = result or {}
    print(json.dumps(resp), flush=True)

def send_notification(method, params):
    notif = {"jsonrpc": "2.0", "method": method, "params": params}
    print(json.dumps(notif), flush=True)

def main():
    is_cancelled = False
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        
        try:
            req = json.loads(line.strip())
            req_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})

            if method == "initialize":
                # ACP: expects protocolVersion, clientInfo, capabilities
                send_response(req_id, {"serverInfo": {"name": "dummy-agent", "version": "1.0"}})
            elif method == "session/new":
                # ACP: expects cwd, mcpServers. Result should contain sessionId.
                # We'll use a dummy one if none exists
                dummy_sid = "dummy_agent_session_123"
                send_response(req_id, {"sessionId": dummy_sid})
            elif method == "session/cancel":
                is_cancelled = True
                # Cancellation is a notification in ACP, no response needed usually
                # but we can log to stderr for debugging
                sys.stderr.write("Agent received cancel\n")
            elif method == "session/prompt":
                is_cancelled = False
                # ACP: params['prompt'] is a list of content blocks
                prompt_blocks = params.get("prompt", [])
                content = ""
                for block in prompt_blocks:
                    if block.get("type") == "text":
                        content += block.get("text", "")

                # Simulate think/plan phase
                sid = params.get("sessionId")
                send_notification("session/update", {
                    "sessionId": sid,
                    "update": {
                        "sessionUpdate": "agent_plan",
                        "content": {"type": "text", "text": "I will greet the user and use a dummy tool."}
                    }
                })
                time.sleep(0.5)

                # Simulate tool call
                send_notification("session/update", {
                    "sessionId": sid,
                    "update": {
                        "sessionUpdate": "tool_call_start",
                        "content": {"name": "dummy_tool", "arguments": {}}
                    }
                })
                time.sleep(0.5)

                send_notification("session/update", {
                    "sessionId": sid,
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "Thinking... "}
                    }
                })
                
                # Simulate a longer task that can be cancelled
                for i in range(5):
                    if is_cancelled:
                        send_notification("session/update", {
                            "sessionId": params.get("sessionId"),
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": " [CANCELLED]"}
                            }
                        })
                        break
                    time.sleep(0.5)
                    send_notification("session/update", {
                        "sessionId": params.get("sessionId"),
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": f"Step {i} "}
                        }
                    })
                
                # Turn concludes
                send_response(req_id, {"stopReason": "cancelled" if is_cancelled else "end_turn"})
            else:
                send_response(req_id, error={"code": -32601, "message": "Method not found"})

        except json.JSONDecodeError:
            pass

if __name__ == "__main__":
    main()
