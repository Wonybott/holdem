# 자체 테스트 이미지

이 PNG 3개는 사이트 스크린샷이 아니라 `python -m src.utils.fixtures`로 생성한 자체 이미지입니다. 헤더/테두리와 카드·숫자 glyph는 버전 1 전용 테스트 규약입니다. 모의 화면 구조를 변경하면 fixture와 인식기를 함께 변경하고 테스트하세요.

- mock_preflop.png: As Kh, 보드 없음, 팟 120, 콜 0, 상대 2
- mock_flop.png: As Kh / Qs Jh 2c, 팟 120, 콜 20, 상대 2
- mock_river.png: As Kh / Qs Jh 2c 3d 4s, 팟 300, 콜 0, 상대 2
