ARCHER System Upgrade - Technical Implementation Specification
Target System: ARCHER AI Assistant
Current Architecture: LangGraph MCP, FastAPI backend, PyQt6 GUI, Qwen 2.5 (7B)
Implementation Approach: REPL-based iterative development with comprehensive QA gates

CORE OBJECTIVES
1. Memory System Upgrade
Replace mem0 with hybrid three-layer architecture combining immediate recovery, human-readable logging, and graph-based long-term storage.
2. Agent Personality Enhancement
Implement six distinct agent personalities with contextual system prompts optimized for conversational quality.
3. GPU Resource Management
Maintain GPU overhead below 8GB to reserve headroom for future local TTS integration (KittenTTS or similar).

ARCHITECTURAL CHANGES
Memory Architecture: Kimmy 3-Layer + OpenMemory Hybrid
Layer 1: Redis Buffer

Purpose: Crash recovery and session continuity
Storage duration: 24 hours with auto-expiry
Key pattern: archer:buffer:{user_id}:{timestamp}
Heartbeat interval: 30 minutes
Data format: JSON with content hash for deduplication

Layer 2: Markdown Logging

Purpose: Human-readable audit trail and manual editing capability
File structure:

Daily logs: memory/YYYY-MM-DD.md
Site continuity: site_log.md
Task validation: audit.md


Format: Markdown with structured metadata
Retention: Permanent, compress files older than 90 days

Layer 3: OpenMemory Cognitive Storage

Purpose: Graph-based associative memory with temporal knowledge graphs
Storage: Local SQLite database
Key features required:

Five cognitive sectors (episodic, semantic, procedural, emotional, reflective)
Waypoint graph for entity associations (e.g., "Luke Skywalker" → "Star Wars" → "Death Star" conversations)
Temporal decay with sector-specific rates
Hybrid retrieval: 60% graph traversal + 40% vector similarity
Graph hop limit: 3 levels for association discovery
Explainable recall traces showing connection paths



Critical Graph Retrieval Requirement:
Memory retrieval must prioritize contextual associations over keyword matching. Example: If user previously discussed "Death Star," a new mention of "Luke Skywalker" should retrieve the Death Star conversation through graph traversal (Luke → Star Wars → Death Star), not just direct keyword matches.
Agent System Enhancement
Six distinct personalities with enhanced system prompts:

Assistant: General-purpose, friendly, practical
Therapist: Empathetic, supportive, non-clinical with clear professional boundaries
Trainer: Motivational, progress-focused, compassionate accountability
Finance: Educational, non-judgmental, clear legal disclaimers
Investment: Analytical, risk-aware, educational disclaimers required
Observer: Pattern detection, behavioral monitoring, privacy-respectful

Each agent receives memory context injection before LLM invocation. System prompts must include relevant user history from OpenMemory retrieval.

DEPENDENCY MANAGEMENT CONSTRAINTS
Critical: Existing voice pipeline must remain functional throughout implementation.
Current voice stack dependencies:

faster-whisper (STT)
pyttsx3 (TTS - current)
mediapipe==0.10.9
protobuf==3.20.3
sounddevice
webrtcvad

Installation approach:

Use virtual environment isolation
Install new dependencies in separate venv first
Test compatibility before merging
Document any version conflicts immediately
Rollback capability required at each integration point

New dependencies to add:

redis-py
openmemory-py (verify compatible with Python 3.10+)
Any OpenMemory dependencies


GPU RESOURCE ALLOCATION
Total VRAM Available: 16GB (RTX 5080)
Reserved for future TTS: 8GB minimum
Maximum LLM allocation: 8GB
Current LLM: Qwen 2.5:7b-instruct (~5-6GB VRAM usage)
Decision: Retain Qwen 2.5:7b-instruct as primary LLM - DO NOT upgrade to Mistral Small 3.1
Rationale: Mistral Small 3.1 (24B quantized) requires ~13-14GB VRAM, leaving insufficient headroom for local TTS integration. Qwen 2.5 provides adequate conversational quality while preserving GPU resources.

QUALITY CONTROL FRAMEWORK
Pre-Implementation Validation
Environment Audit:

Document all current dependencies with versions
Capture current VRAM usage baseline
Record response latency metrics for existing system
Export current memory database for rollback capability
Verify all existing tests pass before any changes

Dependency Conflict Detection:

Create isolated test environment
Install new dependencies
Run dependency conflict checker
Validate existing voice pipeline still functional
Check for protobuf version conflicts (known issue area)

Implementation Gates
Each implementation phase requires passing validation before proceeding to next phase.
Gate 1: Redis Integration

 Redis server running and accessible
 Heartbeat mechanism stores conversation snapshots every 30 minutes
 TTL auto-expiry verified (test with 1-minute TTL, confirm deletion)
 Recovery mechanism restores state from Redis on restart
 No impact on existing conversation flow
 Response latency impact < 50ms

Gate 2: Markdown Logging

 Daily log files created with correct naming
 Conversation appends properly formatted
 File permissions prevent unauthorized access
 Log rotation tested (verify 90-day compression)
 Manual editing of markdown preserved on next write
 No data loss when markdown and Redis both active

Gate 3: OpenMemory Core Integration

 SQLite database created with correct schema
 Memory writes succeed with proper sector classification
 Basic retrieval returns results
 Five-sector classification working (episodic, semantic, procedural, emotional, reflective)
 Existing conversation flow unchanged
 No VRAM increase detected

Gate 4: Graph-Based Retrieval

 Waypoint graph creates entity associations
 Graph traversal finds indirect connections (test: "Luke Skywalker" retrieves previous "Death Star" conversation)
 Hybrid scoring (60% graph + 40% vector) produces better results than pure vector
 Temporal decay applies correctly (newer memories score higher)
 Retrieval latency < 100ms for 5 results
 Graph hop limit prevents runaway queries

Gate 5: Agent Personality Integration

 System prompts successfully injected for all 6 agents
 Memory context properly formatted in system prompts
 Triage routing selects appropriate agent
 Agent responses reflect personality differences
 Legal disclaimers present in Finance/Investment responses
 Therapist maintains non-clinical boundaries

Gate 6: Nightly Maintenance

 Cron job setup verified
 Redis → OpenMemory sync processes correctly
 Markdown → OpenMemory sync catches missed entries
 Memory decay calculation correct
 Markdown compression works (test with old files)
 No data loss during maintenance window

Integration Testing Protocol
Test Scenarios (must pass all):

Contextual Memory Retrieval

Conversation A (Day 1): Discuss "Death Star explosion scene"
Wait 2 weeks
Conversation B (Day 14): Mention "Luke Skywalker character arc"
Expected: System retrieves Death Star conversation via graph traversal
Validation: Check LLM system prompt includes Death Star context


Crash Recovery

Start conversation
Force kill ARCHER process mid-conversation
Restart within 5 minutes
Expected: Conversation state restored from Redis
Validation: User sees seamless continuation


Memory Sector Classification

Input test messages designed for each sector:

Episodic: "Yesterday I attended a presentation"
Semantic: "The capital of France is Paris"
Procedural: "To deploy code, I run git push then docker build"
Emotional: "I'm feeling anxious about tomorrow's meeting"
Reflective: "I've noticed I perform better with morning preparation"


Validation: Query OpenMemory database, confirm correct sector assignment


Agent Personality Differentiation

Same user input to different agents: "I'm stressed about money"
Assistant: Should offer practical help or route to Finance agent
Therapist: Should validate feelings and explore emotional impact
Finance: Should request specifics and provide educational guidance with disclaimers
Validation: Responses differ meaningfully in tone and content


Voice Pipeline Continuity

Record audio input via faster-whisper
Process through agent system
Generate TTS output via pyttsx3
Validation: Complete round-trip with no errors or quality degradation


VRAM Boundary

Monitor VRAM during:

Idle state
Active conversation
Memory retrieval operations
Nightly maintenance


Validation: Peak usage never exceeds 8GB


Dependency Isolation

Install all new dependencies
Run existing tests for voice pipeline
Check for import conflicts
Validation: All existing functionality unchanged



Performance Benchmarks
Establish baseline metrics before changes, validate within tolerance after:
MetricBaselineAcceptable RangeFailure ThresholdResponse latencyCurrent measurement+100ms+500msMemory retrievalN/A (new)<100ms>250msVRAM usageCurrent measurement+2GB>8GB totalConversation throughputCurrent measurement-10%-30%Redis write latencyN/A (new)<10ms>50ms
Error Recovery Procedures
Critical Failure Handling:
If any gate fails validation:

Document exact failure mode
Preserve failure state for analysis
Rollback to last passing gate
Analyze root cause before retry
Adjust implementation approach based on findings

Rollback Triggers:

Any dependency conflict affecting voice pipeline
VRAM usage exceeding 8GB
Response latency degradation >500ms
Data loss in any memory layer
Agent routing failures >5% of requests

Rollback Procedure:

Stop all ARCHER services
Restore previous git commit
Restore Redis database from backup
Restore OpenMemory database from backup
Verify voice pipeline functionality
Resume normal operation
Document rollback reason for analysis


IMPLEMENTATION APPROACH
REPL-Based Development:
Work iteratively with continuous validation. Each change should be small enough to verify independently. Build confidence in each component before integration.
Autonomy vs. Guidance Balance:
This specification provides objectives and constraints, not implementation details. Use your expertise to solve problems as they arise. The QA gates define success criteria - the path to achieve them is flexible.
When Encountering Issues:

Investigate root cause before attempting fixes
Consider alternative approaches if first attempt fails
Document unexpected behavior for pattern analysis
Don't proceed to next gate until current gate passes
Seek clarification if objectives conflict or are ambiguous

Testing Philosophy:
Comprehensive testing is mandatory. Each gate must pass completely. Partial success is not sufficient to proceed. If a feature cannot be implemented within constraints (VRAM, latency, compatibility), document why and propose alternatives rather than compromising quality gates.

CRITICAL SUCCESS FACTORS

Zero Impact on Voice Pipeline: Existing STT/TTS functionality must work identically post-implementation
VRAM Discipline: Total GPU usage must not exceed 8GB under any circumstance
Contextual Memory: Graph-based retrieval must successfully connect indirect associations (test case: Luke Skywalker → Death Star retrieval)
Data Integrity: No memory loss across all three layers under normal or crash conditions
Response Quality: Agent personalities must be distinguishable in responses
Performance: Response latency increase must not exceed 100ms


DELIVERABLES
Upon completion, provide:

Validation Report: Status of all QA gates with evidence (logs, metrics, test outputs)
Architecture Documentation: Actual implementation details including any deviations from spec with rationale
Performance Metrics: Comparison table showing before/after measurements for all benchmarked metrics
Dependency Manifest: Complete list of added dependencies with versions and compatibility notes
Rollback Package: Instructions and necessary files for reverting changes if issues discovered post-deployment
Known Issues Log: Any limitations, edge cases, or areas requiring future attention


OMISSIONS AND IMPLICIT REQUIREMENTS
This specification intentionally does not include:

Specific code implementations (use best judgment)
Exact file structures (organize logically)
Detailed API contracts (design for clarity and maintainability)
Timeline estimates (work at sustainable pace ensuring quality)

This specification assumes:

Proficiency with Python async patterns for Redis operations
Understanding of LangGraph state management for memory injection
Familiarity with vector databases and graph traversal algorithms
Ability to diagnose GPU memory issues and optimize allocations
Experience with dependency management in Python ecosystems


Final Note: The success of this implementation depends on rigorous validation at each step. Do not skip gates. Do not compromise on quality criteria. If a gate cannot be passed within constraints, stop and analyze rather than proceeding with known deficiencies. Comprehensive testing now prevents catastrophic failures later.