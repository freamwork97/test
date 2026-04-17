# Codex Delegation Rule

**Codex CLI is your highly capable supporter.**

## Context Management (CRITICAL)

**컨텍스트 소비를 의식해서 Codex를 사용하세요.**  
출력이 커질 것으로 예상되는 경우에는 **서브 에이전트 경유를 권장**합니다.

| 상황 | 권장 방법 |
|------|-----------|
| 짧은 질문 · 짧은 답변 | 직접 호출 OK |
| 상세한 설계 상담 | 서브 에이전트 경유 |
| 디버깅 분석 | 서브 에이전트 경유 |
| 여러 개의 질문이 있는 경우 | 서브 에이전트 경유 |

```
┌──────────────────────────────────────────────────────────┐
│  Main Claude Code                                        │
│  → 짧은 질문이면 직접 호출하면 됨                             │
│  → 출력이 클 것으로 예상되면 서브 에이전트 경유                   │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │  Subagent (general-purpose)                         │ │
│  │  → Calls Codex CLI                                  │ │
│  │  → Processes full response                          │ │
│  │  → Returns key insights only                        │ │
│  └────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

## About Codex

Codex CLI is an AI with exceptional reasoning and task completion abilities.
Think of it as a trusted senior expert you can always consult.

**When facing difficult decisions → Delegate to subagent → Subagent consults Codex.**

## When to Consult Codex

ALWAYS consult Codex BEFORE:

1. **Design decisions** - How to structure code, which pattern to use
2. **Debugging** - If cause isn't obvious or first fix failed
3. **Implementation planning** - Multi-step tasks, multiple approaches
4. **Trade-off evaluation** - Choosing between options

### Trigger Phrases (User Input)

Consult Codex when user says:

| Korean | English |
|----------|---------|
| "어떻게 설계해야 할까?", "어떻게 구현하지?" | "How should I design/implement?" |
| "「왜 안 돌아가지?", "원인은?", "에러가 나요" | "Why doesn't this work?" "Error" |
| "어느 쪽이 좋아?", "비교해 줘", "트레이드오프는?" | "Which is better?" "Compare" |
| "~를 만들고 싶다", "~를 구현해 줘" | "Build X" "Implement X" |
| "생각해 줘", "분석해 줘", "깊게 생각해" | "Think" "Analyze" "Think deeper" |

## When NOT to Consult

Skip Codex for simple, straightforward tasks:

- Simple file edits (typo fixes, small changes)
- Following explicit user instructions
- Standard operations (git commit, running tests)
- Tasks with clear, single solutions
- Reading/searching files

## Quick Check

Ask yourself: "Am I about to make a non-trivial decision?"

- YES → Consult Codex first
- NO → Proceed with execution

## How to Consult (via Subagent)

**IMPORTANT: Use subagent to preserve main context.**

### Recommended: Subagent Pattern

Use Task tool with `subagent_type: "general-purpose"`:

```
Task tool parameters:
- subagent_type: "general-purpose"
- run_in_background: true (for parallel work)
- prompt: |
    {Task description}

    Call Codex CLI:
    codex exec --model gpt-5.2-codex --sandbox read-only --full-auto "
    {Question for Codex}
    " 2>/dev/null

    Return CONCISE summary:
    - Key recommendation
    - Main rationale (2-3 points)
    - Any concerns or risks
```

### Direct Call (Only When Necessary)

Only use direct Bash call when:
- Quick, simple question (< 1 paragraph response expected)
- Subagent overhead not justified

```bash
# Only for simple queries
codex exec --model gpt-5.2-codex --sandbox read-only --full-auto "Brief question" 2>/dev/null
```

### Sandbox Modes

| Mode | Sandbox | Use Case |
|------|---------|----------|
| Analysis | `read-only` | Design review, debugging analysis, trade-offs |
| Work | `workspace-write` | Implement, fix, refactor (subagent recommended) |

**Language protocol:**
1. Ask Codex in **English**
2. Subagent receives response in **English**
3. Subagent summarizes and returns to main
4. Main reports to user in **Korean**

## Why Subagent Pattern?

- **Context preservation**: Main orchestrator stays lightweight
- **Full analysis**: Subagent can process entire Codex response
- **Concise handoff**: Main only receives actionable summary
- **Parallel work**: Background subagents enable concurrent tasks

**Don't hesitate to delegate. Subagents + Codex = efficient collaboration.**
