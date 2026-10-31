from src.listener import DECISIONS_HTML


def test_decisions_workbench_precedes_comparisons_and_route_timeline():
    toolbar = DECISIONS_HTML.index('<div class="toolbar-title">Endpoint route transitions</div>')
    focus = DECISIONS_HTML.index('id="focusBoard"')
    compare = DECISIONS_HTML.index('id="classCompareTitle"')
    route = DECISIONS_HTML.index('<b>Endpoint route transitions</b>', compare)
    assert toolbar < focus < compare < route


def test_focused_workbench_contains_reference_structure_without_asset_dependency():
    for label in (
        'Level ${lvl} Talents',
        'Level ${lvl} Overview',
        'Rotation &amp; Priority',
        'Pull configuration',
        'Timing breakdown · per mob',
        'Stat Weights',
        'Gear · Level ${lvl}',
        'Coverage',
    ):
        assert label in DECISIONS_HTML
    assert 'class="config-grid"' in DECISIONS_HTML
    assert 'class="timing-bars"' in DECISIONS_HTML
    assert 'class="talent-summary"' in DECISIONS_HTML


def test_level_selection_updates_focus_without_forcing_scroll_to_raw_timeline():
    bind = DECISIONS_HTML[DECISIONS_HTML.index('function bind(){'):DECISIONS_HTML.index('async function load(){')]
    load = DECISIONS_HTML[DECISIONS_HTML.index('async function load(){'):DECISIONS_HTML.index("load().catch")]
    assert 'scrollToLevel()' not in bind
    assert 'scrollToLevel' not in load
