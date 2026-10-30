# Texas Hold'em Vision Analyzer

Python 3.12 / PySide6 Windows 데스크톱 개발 버전입니다. 자체 모의 화면 분석과, 사용자가 명시적으로 선택·보정한 실제 화면의 픽셀 캡처를 지원합니다. 기본 캡처 목표 간격은 **1초**입니다. 실제 화면의 사이트별 기본 카드 템플릿은 포함하지 않습니다. 아직 PokerNow 실제 화면으로 정확도를 검증하지 않았으므로 최초 보정과 새 카드 샘플 등록이 필요합니다.

**[Windows 실행용 코드 ZIP 다운로드](https://github.com/Wonybott/holdem/archive/refs/heads/main.zip)** — 압축을 푼 뒤 아래 설치 안내를 따르세요. 비공개 저장소는 GitHub 로그인이 필요합니다.

**처음 사용하는 분:** [다운로드부터 실행·실제 화면 설정까지 한국어 안내](docs/START_HERE_KO.md).

Windows에서 Python 3.12를 설치하고 ZIP을 풀어 **run_windows.bat**를 더블클릭하세요. 직접 실행하려면 프로젝트 폴더의 PowerShell에서 다음을 사용합니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src.main
```

실제 화면의 숫자 OCR에는 선택적 외부 프로그램 Tesseract(영어 데이터)가 필요합니다. 모의 모드는 추가 OCR 설치 없이 실행됩니다. 앱은 로컬 화면 픽셀만 사용합니다. 사이트 API·DOM·패킷 접근, 자동 클릭·베팅을 구현하지 않습니다. 사이트의 사용 허가 여부를 확인한 제품이나 공식 연동이 아닙니다.

## 기능

- 다크 GUI, 시작·중지·재시작, 항상 위, 클릭 통과(10초 후 복구), 수동 결과 수정
- 모의 테이블 생성/PNG 분석, 모의 창의 Windows mss 캡처
- **실제 모니터 → 테이블 영역 선택 → 카드/금액 보정 → 반복 캡처**
- 카드 템플릿과 숫자 OCR의 불확실성 처리, 두 프레임 안정화, 설정/소스 변경 시 결과 무효화
- 홀 카드/보드/팟/콜 인식. 실제 상대 수·포지션은 수동 설정, 스택은 선택적 OCR 또는 명시적 수동값
- 52장 덱, 중복 방지, 상대 1~8명, 상대 범위, Monte Carlo, 무승부 팟 분배
- 팟 오즈·손익분기 지분, 조건부 콜 EV, 신규 베팅 25/50/75/100% 시나리오
- 별도 캡처·계산 스레드, 취소/재시도, 실패 시 오래된 결과 제거

실제 화면: 상단 **실제 화면 캡처·보정**을 실행해 테이블, 카드 7개 슬롯, 팟과 콜 숫자 영역을 지정하고 현재 보이는 정답 카드를 등록한 뒤 저장·시작합니다. 알 수 없는 카드는 추측하지 않습니다. 새 카드와 빈 보드의 샘플을 추가해야 합니다. `.local/screen-profile.json`에 좌표와 카드 샘플을 저장하며 Git에서 제외합니다. 전체 화면을 자동 저장/전송하지 않습니다.

## 입력과 계산 가정

카드 형식: `As Kh` / `Qs Jh 2c`. T=10, s/h/d/c=스페이드/하트/다이아/클럽. 보드는 0/3/4/5장, 스택은 나 먼저 상대 수+1개입니다. 상대 범위는 `random`, `AA,KK,AKs`, `AKo`, `AK`, `AsKh`를 지원합니다. `;`로 상대마다 범위를 구분할 수 있습니다. 가중치/`+` 문법은 미지원입니다.

팟 P는 내 콜 이전 총 팟(상대 베팅 포함), 내 유효 콜은 C입니다. 손익분기 지분은 `C/(P+C)`, 콜 EV는 `equity*(P+C)-C`입니다. 추가 베팅 없이 쇼다운하는 조건부 계산입니다. equity에는 공동 승자 수에 따른 팟 분배를 반영합니다. 상대 폴드 확률과 콜에 조건화된 equity가 없으면 베팅 EV는 미상으로 두고 최적 행동을 확정하지 않습니다. MC 표준오차와 인식 템플릿 일치도는 상대 범위 가정이 옳을 확률이 아닙니다.

## 테스트 / GUI 없는 실행

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m src.main --analyze assets/mock_flop.png --iterations 3000
.\.venv\Scripts\python.exe -m src.utils.fixtures
```

Linux 클라우드는 `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`로 검사합니다. 실제 사용자 화면은 Windows 로컬 실행으로만 확인할 수 있습니다. CLI `--analyze`는 모의 PNG 전용이며 실제 화면 보정은 GUI에서 합니다. OpenCV는 Qt 충돌 방지를 위해 headless 배포판을 사용합니다. 숫자 OCR 테스트는 Tesseract가 없으면 선택적으로 건너뜁니다.

## 구조 / 남은 제한

`src/gui/`는 대시보드·모의 창·보정창, `capture/`는 소스·스레드·Windows 화면 캡처, `vision/`은 모의 인식·실제 보정 프로필·선택적 OCR, `poker/`는 범위·핸드 평가·MC, `strategy/`는 조건부 EV, `models/`는 검증 모델, `utils/`는 fixture 생성입니다.

일반 테이블의 무보정 인식, 자동 좌석/포지션/상대 수 추적, 이전 행동 기록, 사이드 팟·레이크·합법 최소 레이즈·멀티스트리트 최적화는 미지원입니다. 콜 숫자가 표시되지 않는 UI는 0으로 자동 가정하지 않습니다. 실제 Windows mss, 혼합 DPI/다중 모니터, 네이티브 클릭 통과와 PokerNow 정확도는 수동 검증이 남아 있습니다. 1초는 목표 캡처 간격이며 계산 완료 주기 보장은 아닙니다.

[설계](docs/architecture.md) · [검증](docs/validation.md). 사용자 요청에 따라 GitHub 저장소에 코드를 반영했습니다. 클라우드 환경 게시는 수행하지 않습니다.
