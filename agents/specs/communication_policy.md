# Communication Policy

## Action Types

Every outbound message must be classified as one of these action types:

| Action Type | Description |
|---|---|
| `REPLY_TO_CALLER` | Respond to whoever sent you a message |
| `SUBMIT_DOMAIN_RESULT` | Submit your domain-specific assessment result |
| `REQUEST_CLARIFICATION` | Ask for more information |
| `DISPATCH_AGENT_TASK` | Assign a task to another agent |
| `FINAL_NOTIFY_HUMAN` | Notify the human that workflow is complete |
| `NO_ACTION` | No outbound message needed |

## Role Permissions

### Coordinator (VendorCoordinator)
Allowed: `REPLY_TO_CALLER`, `REQUEST_CLARIFICATION`, `DISPATCH_AGENT_TASK`, `FINAL_NOTIFY_HUMAN`

### Specialists (all other agents)
Allowed: `REPLY_TO_CALLER`, `SUBMIT_DOMAIN_RESULT`, `REQUEST_CLARIFICATION`, `NO_ACTION`

Specialists are FORBIDDEN from using `DISPATCH_AGENT_TASK`.

## Reply vs Dispatch

- **Reply**: Responding to whoever called you. This is NOT delegation.
- **Dispatch**: Assigning a new task to another agent. ONLY the coordinator can do this.
- **Submit**: Sending your completed work back. This is NOT delegation.

## Clarification Rules

- **Direct chat with human**: You may ask the human directly for clarification.
- **Task from coordinator**: Send clarification request back to the coordinator. The coordinator will then ask the human. You must NOT bypass the coordinator.

## Human Mention Policy

- You may reply to a human who directly called you.
- During coordinated workflow: specialists must NOT mention humans for progress updates. All communication goes through coordinator.
- Coordinator may mention human only for: clarification requests, final notification, or unrecoverable failure.
- Coordinator must NOT mention human on every progress update.

## Mention Rules

- NEVER mention yourself (causes `cannot_mention_self` error).
- NEVER include raw `@AgentName` in report body text. Use plain names like "SecurityReviewer".
- Transport mentions are handled by the runtime, not by you.
- Email addresses and legal text with `@` symbols will be preserved.
