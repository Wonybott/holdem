from dataclasses import replace
from src.gui.window import MainWindow
from src.poker.equity import EquityResult
from src.vision.recognizer import Observation


def publish(window,state=None,equity=.5,error=.008):
    state=state or window.source.state
    window.on_analyzed(state,EquityResult(equity,0,equity,3000,error),
                       window.accepted_revision,window.source.revision)


def test_primary_view_shows_action_and_amount_without_opening_settings(app):
    window=MainWindow(); window.show(); app.processEvents()
    try:
        publish(window)
        assert window.tabs.currentWidget()==window.play_page
        assert window.dashboard.title.text()=='콜 검토'
        assert window.dashboard.amount.text()=='콜 20칩'
        assert window.dashboard.title.isVisible()
        assert not window.settings_page.isVisible()
        assert window.dashboard.hero.cards[0].text()=='A♠'
        assert window.dashboard.equity.value.text()=='50.0%'
    finally: window.close()


def test_stale_result_and_capture_failure_remove_action_and_money(app):
    window=MainWindow()
    try:
        publish(window)
        window.on_observed(Observation(errors=['bad frame']),window.source.revision)
        assert window.result_state is None
        assert window.dashboard.title.text()=='화면을 읽지 못했습니다'
        assert window.dashboard.equity.value.text()=='—'
        assert window.dashboard.hero.cards[0].text()=='—'
        assert not window.dashboard.amount.text()
        assert not window.output.toPlainText()
    finally: window.close()


def test_real_screen_errors_keep_specific_recovery_when_status_follows(app):
    window=MainWindow()
    try:
        window.profile=object()  # No OCR needed to present a failed observation.
        window.mode.setCurrentIndex(2)
        window.worker.stop_event.clear()
        window.on_observed(Observation(errors=['card0: 카드 인식 실패']),window.source.revision)
        window.on_status('인식 실패 / 갱신 필요')
        assert window.dashboard.title.text()=='카드 인식 실패'
        assert '샘플' in window.dashboard.instruction.text()
        window.dashboard.next_button.click()
        assert window.tabs.currentWidget()==window.settings_page
    finally: window.close()


def test_missing_profile_tells_user_which_tab_to_open(app):
    window=MainWindow()
    try:
        window.mode.setCurrentIndex(2)
        assert window.dashboard.title.text()=='먼저 화면을 설정하세요'
        window.dashboard.next_button.click()
        assert window.tabs.currentWidget()==window.settings_page
    finally: window.close()


def test_check_uses_zero_amount_and_keeps_bet_ev_unknown(app):
    window=MainWindow()
    try:
        publish(window,replace(window.source.state,to_call=0))
        assert window.dashboard.title.text()=='체크 가능'
        assert window.dashboard.amount.text()=='추가 금액 0칩'
        assert '체크 EV' in window.dashboard.ev.caption.text()
        assert window.dashboard.scenarios.rowCount()==4
        assert all(window.dashboard.scenarios.item(i,2).text()=='미상' for i in range(4))
    finally: window.close()


def test_stopping_removes_previously_displayed_decision(app):
    window=MainWindow()
    try:
        publish(window,equity=.05)
        assert window.dashboard.title.text()=='폴드 검토'
        window.stop_capture()
        assert window.dashboard.title.text()=='분석을 시작하세요'
        assert window.dashboard.required.value.text()=='—'
    finally: window.close()


def test_closing_window_stops_ui_timers(app):
    window=MainWindow()
    window.pass_timer.start(10000)
    assert window.stale_timer.isActive()
    window.close()
    assert not window.stale_timer.isActive()
    assert not window.pass_timer.isActive()


def test_automatic_mode_starts_without_a_profile(app):
    window=MainWindow()
    try:
        window.mode.setCurrentIndex(1)
        assert window.is_auto()
        assert window.profile is None
        assert window.dashboard.title.text()=='분석을 시작하세요'
    finally:window.close()


def test_unknown_call_does_not_show_check_or_zero_cost(app):
    window=MainWindow()
    try:
        state=replace(window.source.state,to_call=None,hero_turn=False)
        publish(window,state)
        assert window.dashboard.title.text()=='상대 차례입니다'
        assert window.dashboard.required.value.text()=='—'
        assert window.dashboard.ev.value.text()=='—'
        assert not window.dashboard.amount.text()
        assert window.mini.title.text()=='상대 차례입니다'
        window.stop_capture()
        assert not window.mini.cards.text()
    finally:window.close()


def test_lobby_and_paused_scenes_show_seats_without_action(app):
    from src.models.table import Seat,TableSnapshot
    window=MainWindow()
    try:
        seats=(Seat('s',.7,1,occupied=True,name='hero',stack=100000),Seat('e',.3,0,number=6,occupied=False))
        waiting=TableSnapshot(seats,'waiting',settled_pot=0,total_pot=0)
        window.on_observed(Observation(table=waiting),window.source.revision)
        assert window.dashboard.title.text()=='플레이어 / 딜 대기 중'
        assert window.seat_view.rows.rowCount()==2
        assert not window.dashboard.amount.text()
        paused=TableSnapshot(seats,'paused',settled_pot=4000,total_pot=4000)
        window.on_observed(Observation(table=paused,errors=['hidden cards']),window.source.revision)
        window.on_status('인식 실패 / 갱신 필요')
        assert window.dashboard.title.text()=='게임 일시정지'
        assert window.mini.title.text()=='게임 일시정지'
        assert window.dashboard.ev.value.text()=='—'
    finally:window.close()


def test_partial_cards_stay_visible_while_advice_waits_and_clear_on_next_failure(app):
    from src.vision.recognizer import CardReading
    window=MainWindow()
    try:
        window.mode.setCurrentIndex(1)
        window.worker.stop_event.clear()
        partial=Observation(cards=CardReading(('6d','Kd'),()),errors=['팟 OCR 확인 필요'])
        window.on_observed(partial,window.source.revision)
        window.on_status('인식 실패 / 갱신 필요')
        assert window.dashboard.hero.cards[0].text()=='6♦'
        assert window.dashboard.hero.cards[1].text()=='K♦'
        assert '6♦ K♦' in window.mini.cards.text()
        assert window.dashboard.equity.value.text()=='—'
        assert window.result_state is None
        assert not window.dashboard.amount.text()
        assert '팟 OCR' in window.dashboard.instruction.text()
        window.on_observed(Observation(errors=['카드 가려짐']),window.source.revision)
        assert window.dashboard.hero.cards[0].text()=='—'
        assert not window.mini.cards.text()
        window.on_observed(partial,window.source.revision)
        window.stop_capture()
        assert window.dashboard.hero.cards[0].text()=='—'
        assert not window.mini.cards.text()
    finally:window.close()
