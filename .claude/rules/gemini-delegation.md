# Gemini Delegation Rule

**Gemini CLI is your research specialist with massive context and multimodal capabilities.**

## Context Management (CRITICAL)

**컨텍스트 소비를 의식해서 Gemini를 사용한다.**  
Gemini는 출력이 커지기 쉬우므로, **서브 에이전트 경유를 권장**한다.

| 상황 | 권장 방법 |
|------|-----------|
| 짧은 질문 · 짧은 답변 | 직접 호출 OK |
| 코드베이스 분석 | 서브 에이전트 경유 (출력 큼) |
| 라이브러리 조사 | 서브 에이전트 경유 (출력 큼) |
| 멀티모달 처리 | 서브 에이전트 경유 |

```
┌──────────────────────────────────────────────────────────┐
│  Main Claude Code                                        │
│  → 짧은 질문이면 직접 호출하면 됨                             │
│  → 출력이 클 것으로 예상되면 서브 에이전트 경유          │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │  Subagent (general-purpose)                         │ │
│  │  → Calls Gemini CLI                                 │ │
│  │  → Saves full output to .claude/docs/research/      │ │
│  │  → Returns key findings only                        │ │
│  └────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

## About Gemini

Gemini CLI excels at:
- **1M token context window** — Analyze entire codebases at once
- **Google Search grounding** — Access latest information
- **Multimodal processing** — Video, audio, PDF analysis

Think of Gemini as your research assistant who can quickly gather and synthesize information.

**When you need research → Delegate to subagent → Subagent consults Gemini.**

## Gemini vs Codex: Choose the Right Tool

| Task | Codex | Gemini |
|------|-------|--------|
| Design decisions | ✓ | |
| Debugging | ✓ | |
| Code implementation | ✓ | |
| Trade-off analysis | ✓ | |
| Large codebase understanding | | ✓ |
| Pre-implementation research | | ✓ |
| Latest docs/library research | | ✓ |
| Video/Audio/PDF analysis | | ✓ |

## When to Consult Gemini

ALWAYS consult Gemini BEFORE:

1. **Pre-implementation research** - Best practices, library comparison
2. **Large codebase analysis** - Repository-wide understanding
3. **Documentation search** - Latest official docs, breaking changes
4. **Multimodal tasks** - Video, audio, PDF content extraction

### Trigger Phrases (User Input)

Consult Gemini when user says:

| Korean | English |
|----------|---------|
| "조사해 줘", "리서치해 줘", "조사해" | "Research" "Investigate" "Look up" |
| "이 PDF/영상/오디오를 봐줘"  | "Analyze this PDF/video/audio" |
| "코드베이스 전체를 이해해 줘" | "Understand the entire codebase" |
| "최신 문서를 확인해 줘" | "Check the latest documentation" |
| "~에 대한 정보를 모아줘" | "Gather information about X" |

## When NOT to Consult

Skip Gemini for:

- Design decisions (use Codex instead)
- Code implementation (use Codex instead)
- Debugging (use Codex instead)
- Simple file operations (do directly)
- Running tests/linting (do directly)

## How to Consult (via Subagent)

**IMPORTANT: Use subagent to preserve main context.**

### Recommended: Subagent Pattern

Use Task tool with `subagent_type: "general-purpose"`:

```
Task tool parameters:
- subagent_type: "general-purpose"
- run_in_background: true (for parallel work)
- prompt: |
    Research: {topic}

    1. Call Gemini CLI:
       gemini -p "{research question}" 2>/dev/null

    2. Save full output to: .claude/docs/research/{topic}.md

    3. Return CONCISE summary (5-7 bullet points):
       - Key findings
       - Recommended approach
       - Important caveats
```

### Subagent Patterns by Task Type

**Research Pattern:**
```
prompt: |
  Research best practices for {topic}.

  gemini -p "Research: {topic}. Include recommended approaches,
  common pitfalls, and library recommendations." 2>/dev/null

  Save to .claude/docs/research/{topic}.md
  Return 5-7 key bullet points.
```

**Codebase Analysis Pattern:**
```
prompt: |
  Analyze codebase for {purpose}.

  gemini -p "Analyze architecture, key modules, data flow,
  and entry points." --include-directories . 2>/dev/null

  Save to .claude/docs/research/codebase-analysis.md
  Return architecture summary and key insights.
```

**Multimodal Pattern:**
```
prompt: |
  Extract information from {file}.

  gemini -p "{extraction prompt}" < {file_path} 2>/dev/null

  Save to .claude/docs/research/{output}.md
  Return key extracted information.
```

### Step 2: Continue Your Work

While subagent is processing, you can:
- Work on other files
- Run tests
- Spawn another subagent for Codex consultation

### Step 3: Receive Summary

Subagent returns concise summary. Full output available in `.claude/docs/research/` if needed.

## Gemini CLI Commands Reference

For use within subagents:

```bash
# Research
gemini -p "{question}" 2>/dev/null

# Codebase analysis
gemini -p "{question}" --include-directories . 2>/dev/null

# Multimodal
gemini -p "{prompt}" < /path/to/file.pdf 2>/dev/null

# JSON output
gemini -p "{question}" --output-format json 2>/dev/null
```

**Language protocol:**
1. Ask Gemini in **English**
2. Subagent receives response in **English**
3. Subagent summarizes and saves full output
4. Main receives summary, reports to user in **Korean**

## Why Subagent Pattern?

- **Context preservation**: Main orchestrator stays lightweight
- **Full capture**: Subagent can save entire Gemini output to file
- **Concise handoff**: Main only receives key findings
- **Parallel work**: Background subagents enable concurrent research

**Use Gemini (via subagent) for research, Codex (via subagent) for reasoning, Claude for orchestration.**
