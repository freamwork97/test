# 위임 패턴 상세

## 위임 결정 순서도

```
작업 수신
    │
    ▼
┌─────────────────────────┐
│ 명시적인 Codex 지시?    │
└───────────┬─────────────┘
    ┌───────┴───────┐
    │ Yes          │ No
    ▼              ▼
  위임        ┌─────────────────────────┐
              │ 복잡도 체크          │
              └───────────┬─────────────┘
              ┌───────────┴───────────┐
              │ Yes                   │ No
              ▼                       ▼
            위임              ┌─────────────────────────┐
                              │ 실패 ​​체크(2회 이상)  │
                              └───────────┬─────────────┘
                              ┌───────────┴───────────┐
                              │ Yes                   │ No
                              ▼                       ▼
                            위임              ┌─────────────────────────┐
                                              │ 품질·보안 요건  │
                                              └───────────┬─────────────┘
                                              ┌───────────┴───────────┐
                                              │ Yes                   │ No
                                              ▼                       ▼
                                            위임              Claude Code에서 실행
```

## 패턴별 실행 예

### Pattern 1: 아키텍처 검토

```bash
codex exec \
  --model gpt-5-codex \
  --config model_reasoning_effort="high" \
  --sandbox read-only \
  --full-auto \
  "Review the architecture of src/auth/ module. Focus on:
   1. Single Responsibility adherence
   2. Dependency direction (should flow inward)
   3. Interface design clarity
   4. Extensibility for future auth providers

   Related files: src/auth/**/*.py
   Constraints: Must maintain backward compatibility" 2>/dev/null
```

### Pattern 2: 실패 기반 위임

```bash
codex exec \
  --model gpt-5-codex \
  --config model_reasoning_effort="high" \
  --sandbox read-only \
  --full-auto \
  "This bug has resisted 2 fix attempts:

   Symptom: Race condition in user session handling

   Previous attempts:
   1. Added mutex lock → Deadlock in high concurrency
   2. Switched to RWLock → Still intermittent failures

   Please analyze from fresh perspective:
   - What root cause might we be missing?
   - Are there architectural issues causing this?
   - What alternative approaches should we consider?" 2>/dev/null
```

### Pattern 3: 성능 최적화

```bash
codex exec \
  --model gpt-5-codex \
  --config model_reasoning_effort="xhigh" \
  --sandbox read-only \
  --full-auto \
  "Optimize the algorithm in src/data/aggregator.py:

   Current: O(n²) nested loops for data aggregation
   Target: O(n log n) or better

   Constraints:
   - Must handle 100K+ records
   - Memory limit: 512MB
   - Cannot change public API

   Provide:
   1. Optimized implementation
   2. Complexity analysis
   3. Benchmark comparison approach" 2>/dev/null
```

### Pattern 4: 보안 감사

```bash
codex exec \
  --model gpt-5-codex \
  --config model_reasoning_effort="xhigh" \
  --sandbox read-only \
  --full-auto \
  "Security audit of src/api/auth.py:

   Check for:
   - SQL injection vulnerabilities
   - XSS attack vectors
   - CSRF protection
   - Proper input validation
   - Secure password handling
   - Session management issues

   Output format:
   - CRITICAL: Must fix immediately
   - HIGH: Fix before release
   - MEDIUM: Address in next sprint
   - LOW: Tech debt" 2>/dev/null
```

## 위임하지 않는 경우

| 케이스 | 이유 |
|--------|------|
| 간단한 CRUD 조작 | 정형 작업, 깊은 분석 불필요 |
| 소규모 버그 수정 (첫 번째) | 우선 Claude Code에서 시도 |
| 문서 업데이트 전용 | 창의성보다 정확성에 중점 |
| 포맷 및 린트 수정 | 기계적 처리 |
