# 일감몰아주기 증여세 확인 앱 — 시작하기

## 폴더 구조 (이미 세팅됨)
```
illgam-app/
├─ backend/
│  ├─ data/          ← 지분율·규모 데이터 4개 (이미 들어있음, 기밀)
│  ├─ calc.py        ← 계산 엔진 (엑셀 검증본과 동일, 이미 검증 통과)
│  ├─ tests/test_calc.py
│  └─ requirements.txt
├─ frontend/         ← 화면 (Claude Code가 생성)
├─ 붙여넣기_프롬프트.md  ← 이 내용을 Claude Code에 붙여넣기
└─ .gitignore
```

## 순서
1. VS Code에서 이 `illgam-app` 폴더를 연다 (File → Open Folder).
2. (선택) 계산 엔진이 맞는지 먼저 확인 — **저장소 루트에서** 실행한다
   (`backend` 은 패키지라 `cd backend` 후에는 import 가 풀리지 않는다):
   ```
   pip install -r backend/requirements-dev.txt
   python -m pytest backend -q      # 전부 통과하면 정상 (엑셀과 동일)
   ```
3. `붙여넣기_프롬프트.md` 안의 프롬프트 블록을 통째로 복사해 Claude Code 채팅창에 붙여넣는다.
   - calc.py·데이터가 이미 있으니 Claude Code는 이걸 재사용해 API·인증·프론트·배포를 붙이면 된다.
4. 완성 후 실행:
   ```
   # 백엔드 (저장소 루트에서)
   uvicorn backend.main:app --reload
   # 프론트엔드는 프롬프트대로 생성/실행
   ```

## 보안 원칙 (중요)
- `backend/data/`의 지분율은 계산에만 쓰고 화면·API 응답·로그에 노출하지 않는다.
- `calc.py`는 집계 결과만 반환하도록 이미 설계돼 있다(지분율·지배주주별 내역 미반환).
- 사내 배포 시 데이터를 공개 경로에 두지 말 것.

## 주의
- 계산은 2026.06.30 지분·규모 기준의 개략 추정이며, 최종 신고 전 세무대리인 검토가 필요.
- ② 법인세상당액을 0으로 두면 증여세가 과대 산출된다.
