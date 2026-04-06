# Agent Autonomy Q&A

## Q1. How can the autonomous agent maintain continuity across repeated heartbeat invocations without overloading the LLM context?

**Answer**
The LLM context should be treated as short-term working memory, not as permanent memory.  
Each heartbeat may start fresh, as long as the agent reconstructs context from durable state.  
Past work should come from DB records, artifacts, incidents, and run history.  
Current work should come from active queues, due items, and the selected work unit.  
Future work should come from the workflow state machine and persisted next-step rules.

**Keywords**
working memory, durable state, context reconstruction, state machine, checkpointing

## Q2. If each heartbeat starts with a fresh context, won’t that interrupt an in-progress autonomous run?

**Answer**
No, not if heartbeat cycles and pipeline runs are modeled separately.  
The heartbeat is only a short supervisor invocation; the real run lives in persistent state.  
Use a lock or lease so only one supervisor cycle is active at a time.  
Checkpoint every meaningful step so the next heartbeat can safely resume from that point.  
A fresh context continues the durable run; it does not replace or interrupt it.

**Keywords**
heartbeat cycle, pipeline run, lock, lease, single-flight execution, resume

## Q3. Is this the correct mental model: heartbeat keeps the agent alive, the LLM is the reasoning brain, the project is the execution machinery, web access supports information gathering, and the agent can repair small issues to stay stable?

**Answer**
Yes, that is the right overall model.  
The heartbeat keeps the supervisor active, while the LLM handles reasoning and decisions.  
The project code, DB, artifacts, and integrations are the execution machinery the agent operates.  
Web and scraping-like capabilities are for information gathering only when needed and allowed by policy.  
Repair should be bounded: the agent can fix small project or ops issues, but larger or risky changes should escalate.

**Keywords**
heartbeat, reasoning brain, execution machinery, information gathering, bounded self-repair, escalation

## Q4. How should I open the chat interface for the autonomous agent in practice?

**Answer**
You should not first open a generic Codex session and then type `jhc-chat` inside it.  
`jhc-chat` itself should be the terminal entrypoint that launches Codex with the correct project-specific operator instructions.  
So the normal flow is: open Terminal, go to the project folder if needed, and run `jhc-chat` or `./bin/jhc-chat`.  
That command should start the right Codex chat session for this project automatically.  
`jhc-agent-start` and `jhc-agent-stop` should work the same way as terminal commands, not as chat messages.

**Keywords**
terminal entrypoint, jhc-chat, Codex launcher, project bootstrap, local command

## Q5. What happens to the autonomous agent if the MacBook sleeps, and do I need to do anything before closing the laptop?

**Answer**
If the MacBook sleeps, the `launchd` heartbeat does not keep progressing as if the laptop were still awake.  
With `StartInterval`, missed intervals during sleep are missed rather than replayed one by one later.  
When the laptop wakes, the loaded job should start running again, but the first post-wake cycle should do recovery first, not normal work.  
That recovery should reconcile leases, inspect interrupted work, and pause or escalate if anything looks unsafe.  
You do not need a mandatory pre-close chat step; closing the laptop is allowed and the protection comes from strict post-wake recovery.

**Keywords**
sleep, wake, launchd, StartInterval, missed intervals, recovery-first, stale lease

## Q6. Is there a reliable way to know that the laptop actually slept, instead of only inferring it from delayed heartbeats?

**Answer**
Yes. `launchd` by itself does not tell you clearly, but macOS exposes sleep/wake information through system power events and power logs.  
So the best design is to use OS-visible sleep/wake signals as the primary detection path.  
Timing gaps and stale leases should remain fallback signals, not the only method.  
For diagnostics, the agent should also persist how the sleep/wake was detected and when the wake was observed.  
That gives the agent stricter and safer post-wake recovery than relying only on a missed 3-minute heartbeat.

**Keywords**
sleep detection, wake detection, macOS power events, launchd limitation, pmset log, stale lease
