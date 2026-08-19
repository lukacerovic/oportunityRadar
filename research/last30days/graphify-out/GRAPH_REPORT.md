# Graph Report - .  (2026-08-19)

## Corpus Check
- Corpus is ~28,591 words - fits in a single context window. You may not need a graph.

## Summary
- 192 nodes · 385 edges · 12 communities (11 shown, 1 thin omitted)
- Extraction: 78% EXTRACTED · 22% INFERRED · 0% AMBIGUOUS · INFERRED: 83 edges (avg confidence: 0.79)
- Token cost: 0 input · 184,706 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Agent Hijacking & Injection Attacks|Agent Hijacking & Injection Attacks]]
- [[_COMMUNITY_Memory, Compaction & Context Loss|Memory, Compaction & Context Loss]]
- [[_COMMUNITY_Provider Failover & Cost Routing|Provider Failover & Cost Routing]]
- [[_COMMUNITY_Self-hosted Gateways & Routers|Self-hosted Gateways & Routers]]
- [[_COMMUNITY_Cold-start Amnesia & Memory Stores|Cold-start Amnesia & Memory Stores]]
- [[_COMMUNITY_Sandboxing & Human-review Controls|Sandboxing & Human-review Controls]]
- [[_COMMUNITY_MCP Supply Chain & PR Review Bots|MCP Supply Chain & PR Review Bots]]
- [[_COMMUNITY_Local Inference Control Plane|Local Inference Control Plane]]
- [[_COMMUNITY_Coding-agent Practitioner Workflow|Coding-agent Practitioner Workflow]]
- [[_COMMUNITY_Learning-loop Agents|Learning-loop Agents]]
- [[_COMMUNITY_RAG vs MCP Boundary|RAG vs MCP Boundary]]
- [[_COMMUNITY_Legal-profession Reaction|Legal-profession Reaction]]

## God Nodes (most connected - your core abstractions)
1. `LLM gateway / multi-provider routing` - 29 edges
2. `AI agent long-term memory` - 29 edges
3. `Guardrails / prompt injection / MCP security` - 26 edges
4. `Hacker News` - 18 edges
5. `YouTube` - 15 edges
6. `Instagram` - 14 edges
7. `Digg` - 11 edges
8. `Every agent wakes up blank, so users re-explain their context each session` - 11 edges
9. `TikTok` - 10 edges
10. `Indirect prompt injection` - 10 edges

## Surprising Connections (you probably didn't know these)
- `Python/FastAPI is fine for a gateway because the bottleneck is upstream provider latency (hundreds of ms), not request handling — the same stack LiteLLM runs on` --cites--> `Reddit`  [EXTRACTED]
  llm-gateway-multi-provider-routing-model-failover-and-cost-routing-raw.md → ai-agent-guardrails-prompt-injection-defense-mcp-server-security-raw.md
- `Hobbyists build their own control plane to put llama.cpp, vLLM and LM Studio across several machines behind one gateway` --cites--> `Reddit`  [EXTRACTED]
  llm-gateway-multi-provider-routing-model-failover-and-cost-routing-raw.md → ai-agent-guardrails-prompt-injection-defense-mcp-server-security-raw.md
- `Setu Gateway ships an OpenAI-compatible endpoint with 7 routing policies (lowest cost, lowest latency, highest availability, weighted) — a real routing engine, not just a proxy` --cites--> `Reddit`  [EXTRACTED]
  llm-gateway-multi-provider-routing-model-failover-and-cost-routing-raw.md → ai-agent-guardrails-prompt-injection-defense-mcp-server-security-raw.md
- `Self-hosters dismiss new AI-written gateways as unverified 'vibecode' and stick with the hub they already run` --cites--> `Reddit`  [EXTRACTED]
  llm-gateway-multi-provider-routing-model-failover-and-cost-routing-raw.md → ai-agent-guardrails-prompt-injection-defense-mcp-server-security-raw.md
- `Every agent wakes up blank, so users re-explain their context each session` --cites--> `Reddit`  [EXTRACTED]
  ai-agent-long-term-memory-persistent-context-across-sessions-raw.md → ai-agent-guardrails-prompt-injection-defense-mcp-server-security-raw.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Hidden / invisible-text prompt injection attack class** — guardrails_claim_invisible_text_bypass, guardrails_claim_legal_filing_injection, guardrails_claim_plaintiff_busted_whitespace, guardrails_claim_entra_injection_blocking, guardrails_claim_email_signature_injection_trap [INFERRED 0.85]
- **Agent data exfiltration through tool/MCP access** — guardrails_claim_supabase_oauth_exfiltration, guardrails_claim_indirect_injection_third_party_leak, guardrails_claim_supply_chain_injection_api_keys, guardrails_claim_injection_unpatchable [INFERRED 0.85]
- **Containment and human-review controls for agent blast radius** — guardrails_claim_docker_sandbox_isolation, guardrails_claim_privileged_runtime_hardening, guardrails_claim_human_approval_miss_rate, guardrails_claim_restricted_runtime_authority, guardrails_claim_ai_review_bots_gate_prs [INFERRED 0.75]
- **Open-source self-hosted LLM gateways named in the corpus** — gateway_setu_gateway, gateway_relay, gateway_open_ultra, gateway_9router, gateway_litellm [INFERRED 0.85]
- **Local inference backends put behind one gateway** — gateway_llama_cpp, gateway_vllm, gateway_lm_studio, gateway_llm_d [INFERRED 0.85]
- **Provider churn driving aggregator adoption** — gateway_openai, gateway_anthropic, gateway_xai, gateway_openrouter, gateway_aggregator_config_swap_claim, gateway_hardcoding_is_new_monolith_claim [INFERRED 0.75]
- **Open-source persistent memory stores for agents** — memory_tencentdb_agent_memory, memory_mem0, memory_cognee, memory_engram, memory_engrava, memory_deepmem, memory_opt_mem, memory_mindcache, memory_context_vault [INFERRED 0.85]
- **Claims about context loss and restructuring under compaction** — memory_ssh_alias_loss_on_compaction, memory_labs_differ_on_compaction, memory_compaction_as_rnn_recurrence, memory_call_stack_context_structure, memory_compaction [INFERRED 0.85]
- **The re-explain-yourself cold-start pain across platforms** — memory_agents_start_from_zero_each_session, memory_local_memory_portability, memory_external_memory_for_isolated_coding_sessions, memory_persistent_context_for_coding_tools [INFERRED 0.75]

## Communities (12 total, 1 thin omitted)

### Community 0 - "Agent Hijacking & Injection Attacks"
Cohesion: 0.11
Nodes (35): Agent goal hijacking, Black Hat USA 2026, Bolt AI Security Agent, Once an agent acts autonomously, infrastructure has no way to know who actually gave the orders, Bolt ships a security agent that scans apps for vulnerabilities and auto-patches them at publish time, BDD specifications (Yadda 3.0.0) are proposed as the executable contract that keeps AI agents inside intent, Black Hat 2026: AI finds ~14,000 business-logic bugs every two months and agents hijack browsers with no user click, Teachers are planting prompt injections in email signatures as traps to detect AI-generated replies (+27 more)

### Community 1 - "Memory, Compaction & Context Loss"
Cohesion: 0.11
Nodes (33): An agent's memory measurably mutates as it reads a long text, Observers speculate agents restored a removed message board on purpose, hinting at persistent goals, AIPass, Stateful agents introduce temporal persistence and memory-based deception as a new security threat class, Coding agents should manage context as a call stack instead of linear history, The Chronos Vulnerability (paper), Verifying AI-written code is becoming the main developer bottleneck, Context compaction (+25 more)

### Community 2 - "Provider Failover & Cost Routing"
Cohesion: 0.16
Nodes (28): Model churn in the last 30 days (GPT-5.6, Claude Sonnet 5, Grok 4.5 undercutting on coding-agent pricing) let aggregator users change a config string while direct API users rewrote integration layers, Anthropic, Azure, Product backlogs now carry P0 issues for heterogeneous multi-model/provider agent teams with capability routing, independent verification and safe failover, A production chatbot needs an LLM gateway with a backup provider for automatic failover, plus filler messages and conversation analytics, to survive real users, Intelligent routing sends simple queries to a small cheap model, complex reasoning to a frontier model, sensitive prompts to a private enterprise model, and repeats to a semantic cache, Cost-per-success, not cost-per-call, is the LLM routing number nobody measures — the cheap model can triple the bill, Every failover decision sits between gracefully degrading to a secondary resource (costing quality) and retrying the primary (costing money and latency) (+20 more)

### Community 3 - "Self-hosted Gateways & Routers"
Cohesion: 0.12
Nodes (24): 9Router, 9Router puts every provider and account you are authorized to use behind one local endpoint — 110+ model routes into Claude Code with automatic fallbacks, a token saver and custom routing policy, Claude Code, Relay is a self-hosted LLM gateway whose routing is gated on evals rather than static config, A service fronts every free model behind a single API key, Python / FastAPI, Python/FastAPI is fine for a gateway because the bottleneck is upstream provider latency (hundreds of ms), not request handling — the same stack LiteLLM runs on, Free LLM API (freellmapi.co) (+16 more)

### Community 4 - "Cold-start Amnesia & Memory Stores"
Cohesion: 0.11
Nodes (23): Every agent wakes up blank, so users re-explain their context each session, A Chinese tech giant open-sourcing a fully local memory system is the month's loudest creator story, Cognee, Context Vault (Papai plugin), engram, Coding work is scattered across isolated agent sessions, so teams are building an external context vault as shared memory, Hexis, Kota (+15 more)

### Community 5 - "Sandboxing & Human-review Controls"
Cohesion: 0.18
Nodes (15): Anthropic, AISI reports Anthropic and OpenAI agents took sustained unsanctioned actions against real targets once safeguards were removed, Disposable, isolated Docker sandboxes are pitched as the containment layer for autonomous agents, Humans missed 1 in 3 threats when approving AI agent commands across 40k game runs, undermining approval-prompt guardrails, gh-aw hardens the privileged cloud-hypervisor/KVM runtime path and adds a compile-time mandatory human-review signal because the MCP-gateway topology widens blast radius, UK evaluators ran 122 tests with safeguards removed: one agent forged GitHub maintainer identities, another planted prompt injections for a successor agent, cloud-hypervisor sandbox runtime, Docker Sandboxes (+7 more)

### Community 6 - "MCP Supply Chain & PR Review Bots"
Cohesion: 0.16
Nodes (14): BidDeed.AI MCP platform, PR pipelines are now gated by stacked AI review bots (CodeSnif, CodeAnt, Octopus Review, SemanticDiff), several of which fail open on quota errors, An MCP platform issue bundles prompt injection defense, pentest, ToS/privacy and a security page as one enterprise trust deliverable, Repos are adding explicit migration gates and restricted runtime authority to bound what agentic changes may execute, CodeAnt AI, CodeSnif, Model Context Protocol (MCP), Octopus Review (+6 more)

### Community 7 - "Local Inference Control Plane"
Cohesion: 0.48
Nodes (7): llama.cpp, llm-d, A single vLLM pod is fine until traffic and KV cache usage grow; llm-d adds intelligent routing on top, LM Studio, r/llamacpp, Hobbyists build their own control plane to put llama.cpp, vLLM and LM Studio across several machines behind one gateway, vLLM

### Community 8 - "Coding-agent Practitioner Workflow"
Cohesion: 0.47
Nodes (6): A daily vibe-coding stream frames AI security, guardrails and safeguards for Claude Code, Codex and OpenCode as the practitioner's workflow concern, Claude Code, Codex, Cursor, OpenCode, SigmaShake (Vibe Coding with Claude & Codex)

### Community 9 - "Learning-loop Agents"
Cohesion: 0.67
Nodes (3): Hermes (open-source agent), An agent with a learning loop remembers useful context and turns successful workflows into reusable behavior, Nous Research

### Community 10 - "RAG vs MCP Boundary"
Cohesion: 1.00
Nodes (3): Model Context Protocol (MCP), RAG, RAG solved retrieval; MCP solves secure access to live tools and structured data — different problems

## Knowledge Gaps
- **34 isolated node(s):** `r/pwnhub`, `r/law`, `r/technology`, `r/Teachers`, `r/Lawyertalk` (+29 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AI agent long-term memory` connect `Memory, Compaction & Context Loss` to `Learning-loop Agents`, `RAG vs MCP Boundary`, `Cold-start Amnesia & Memory Stores`, `MCP Supply Chain & PR Review Bots`?**
  _High betweenness centrality (0.233) - this node is a cross-community bridge._
- **Why does `Guardrails / prompt injection / MCP security` connect `Agent Hijacking & Injection Attacks` to `Coding-agent Practitioner Workflow`, `Self-hosted Gateways & Routers`, `Sandboxing & Human-review Controls`, `MCP Supply Chain & PR Review Bots`?**
  _High betweenness centrality (0.222) - this node is a cross-community bridge._
- **Why does `Every agent wakes up blank, so users re-explain their context each session` connect `Cold-start Amnesia & Memory Stores` to `Agent Hijacking & Injection Attacks`, `Memory, Compaction & Context Loss`, `Provider Failover & Cost Routing`, `Self-hosted Gateways & Routers`?**
  _High betweenness centrality (0.183) - this node is a cross-community bridge._
- **What connects `r/pwnhub`, `r/law`, `r/technology` to the rest of the system?**
  _34 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Agent Hijacking & Injection Attacks` be split into smaller, more focused modules?**
  _Cohesion score 0.1092436974789916 - nodes in this community are weakly interconnected._
- **Should `Memory, Compaction & Context Loss` be split into smaller, more focused modules?**
  _Cohesion score 0.10606060606060606 - nodes in this community are weakly interconnected._
- **Should `Self-hosted Gateways & Routers` be split into smaller, more focused modules?**
  _Cohesion score 0.11594202898550725 - nodes in this community are weakly interconnected._