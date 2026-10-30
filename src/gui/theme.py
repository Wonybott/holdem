STYLE = """
QWidget { background:#101820; color:#e7edf4; font-family:'Malgun Gothic','Segoe UI',sans-serif; font-size:14px; }
QMainWindow { background:#101820; }
QLabel { background:transparent; }
QLabel#appTitle { font-size:21px; font-weight:700; }
QLabel#muted, QLabel#eyebrow { color:#a9b8c8; font-size:12px; }
QLabel#statusPill { color:#bcd4e8; padding:7px 10px; background:#1b2a38; border-radius:8px; }
QPushButton { background:#253746; border:1px solid #3b5368; padding:9px 14px; border-radius:7px; font-weight:600; }
QPushButton:hover { background:#354e63; border-color:#6c9dbb; }
QPushButton:disabled { color:#8794a2; background:#1d2833; }
QPushButton#primary { background:#087e69; color:#fff; border-color:#20ae92; }
QPushButton#primary:hover { background:#10957d; }
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit { background:#0b1118; border:1px solid #435468; border-radius:5px; padding:7px; selection-background-color:#276f91; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color:#5bc9b0; }
QTabWidget::pane { border:0; }
QTabBar::tab { color:#aebdcb; padding:11px 19px; background:#182430; border-bottom:3px solid #182430; }
QTabBar::tab:selected { color:#fff; border-bottom-color:#42d3b1; background:#223342; }
QScrollArea { border:0; }
QGroupBox { border:1px solid #354759; border-radius:8px; margin-top:14px; padding:17px 12px 12px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 5px; }
QFrame#actionPanel { background:#1b2b3a; border:1px solid #45637d; border-left:5px solid #8db9da; border-radius:10px; }
QFrame#actionPanel[tone="good"] { background:#102e2a; border-color:#2a7b69; border-left-color:#56dfb6; }
QFrame#actionPanel[tone="caution"] { background:#33291d; border-color:#816139; border-left-color:#ffd18a; }
QLabel#actionTitle { font-size:32px; font-weight:700; }
QLabel#actionAmount { font-size:24px; font-weight:700; color:#fff; }
QLabel#actionInstruction { font-size:15px; color:#e1eaf2; }
QLabel#actionBadge { font-size:12px; font-weight:700; color:#b8d8dd; }
QFrame#metric { background:#1a2733; border:1px solid #32495e; border-radius:8px; }
QLabel#metricValue { font-size:27px; font-weight:700; }
QLabel#playingCard { background:#f2f5f7; color:#142334; border:1px solid #b8c9d8; border-radius:7px; font-size:25px; font-weight:700; }
QLabel#playingCard[cardColor="red"] { color:#ba2245; }
QLabel#playingCard[cardColor="empty"] { background:#1a2835; color:#8294a8; border:1px dashed #4e6479; }
QHeaderView::section { background:#243747; color:#dce7f0; padding:6px; border:0; }
QTableWidget { background:#17232e; border:1px solid #354759; gridline-color:#304355; }
QCheckBox { spacing:8px; }
QToolTip { background:#243747; color:#fff; border:1px solid #64829a; padding:5px; }
"""
