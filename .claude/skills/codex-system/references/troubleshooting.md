# 문제해결

## Codex CLI를 찾을 수 없음

```bash
# 확인
which codex
codex --version

# 설치
npm install -g @openai/codex
```

## 인증오류

```bash
# 재인증
codex login

# 상태확인
codex login status
```

## 타임 아웃

| reasoning_effort | 권장 시간 초과 |
|-----------------|-----------------|
| low             | 60s             |
| medium          | 180s            |
| high            | 600s            |
| xhigh           | 900s            |

config.toml에서 설정 :
```toml
[mcp_servers.codex]
tool_timeout_sec = 600
```

## Git 리포지토리 오류

```bash
# Git 관리 외부에서 실행하는 경우
codex exec --skip-git-repo-check ...
```

## reasoning 출력이 너무 많음

```bash
# stderr 억제
codex exec ... 2>/dev/null

# 또는 config.toml에서
hide_agent_reasoning = true
```

## 세션을 계속할 수 없음

```bash
# 최근 세션 목록
codex sessions list

# 특정 세션에 대해 자세히 알아보기
codex sessions show {SESSION_ID}
```

## sandbox 권한 오류

| 오류 | 원인 | 해결책 |
|--------|------|--------|
| Permission denied | read-only 로 쓰기 | workspace-write 로 변경 |
| Network blocked | sandbox 제한 | danger-full-access (조심스럽게) |

## 메모리 부족

큰 코드베이스를 분석하는 경우 :
1. 대상 파일을 좁히기
2. 단계적으로 분석
3. `--config context_limit=...` 로 조정
