# Long-Running Jobs Skill

This skill allows the agent to handle tasks that take a long time to complete by backgrounding them and providing a way to notify the user/agent when the task is finished.

## Context
When an agent starts a process that is expected to take significant time (e.g., a long build, a large data migration, or a complex simulation), it should not block the session if possible. Instead, it can run the command in the background and use the built-in notification system to "wake up" the session when done.

**How it works**: When you call `chat-acp chat notify`, the bridge will post the message to Discord and then **refeed that message back to you as a new prompt**. This allows you to "wake up" and take the next step automatically once the background task is finished.

The following environment variables are injected into your environment:
- `ACP_CHAT_SESSION_ID`: The unique identifier for the current chat session (e.g., Discord thread ID).
- `ACP_CHAT_WORKSPACE_ID`: The identifier for the workspace.
- `ACP_CHAT_PLATFORM`: The name of the chat platform (e.g., "discord").

## Usage
To run a command in the background and receive a notification upon completion or failure, use the following pattern:

```bash
(your_long_command; chat-acp chat notify $ACP_CHAT_PLATFORM $ACP_CHAT_SESSION_ID "Job 'your_job_name' finished with exit code $?") &
```

### Examples

#### 1. Running a long test suite
```bash
(npm test; chat-acp chat notify $ACP_CHAT_PLATFORM $ACP_CHAT_SESSION_ID "Tests completed with status $?") &
```

#### 2. Running a build and deployment
```bash
(make build && make deploy; chat-acp chat notify $ACP_CHAT_PLATFORM $ACP_CHAT_SESSION_ID "Build and deploy successful!") || chat-acp chat notify $ACP_CHAT_PLATFORM $ACP_CHAT_SESSION_ID "Build/Deploy failed" &
```

## Best Practices
1. **Be Specific**: Include the name of the job in the notification message.
2. **Handle Errors**: Use `||` or check `$?` to report failures accurately.
3. **Don't Overuse**: Only use this for tasks that genuinely take more than a minute or two.
4. **Inform the User**: Always tell the user that you've started a background task and will notify them when it's done.
