# 자체 테스트 이미지

이 PNG 3개는 사이트 스크린샷이 아니라 `python -m src.utils.fixtures`로 생성한 자체 이미지입니다. 헤더/테두리와 카드·숫자 glyph는 버전 1 전용 테스트 규약입니다. 모의 화면 구조를 변경하면 fixture와 인식기를 함께 변경하고 테스트하세요.

- mock_preflop.png: As Kh, 보드 없음, 팟 120, 콜 0, 상대 2
- mock_flop.png: As Kh / Qs Jh 2c, 팟 120, 콜 20, 상대 2
- mock_river.png: As Kh / Qs Jh 2c 3d 4s, 팟 300, 콜 0, 상대 2

`dashboard_example.png`는 새 플레이 화면을 자체 모의 데이터로 렌더링한 UI 예시입니다. 인식 테스트 fixture나 실제 PokerNow 화면이 아닙니다.

`pokernow_layout_demo.png`는 자동 탐지 검사에 쓰는 **자체 생성 이미지**입니다. 사용자가 올린 사진/실제 사이트 캡처를 재배포한 것이 아닙니다. `python -m src.main --analyze assets/pokernow_layout_demo.png --pokernow`로 보정 없이 카드·팟·스택을 판독할 수 있습니다. `automatic_dashboard_example.png`는 같은 검증 상태를 자동 인식 화면에 표시한 UI 예시입니다.
