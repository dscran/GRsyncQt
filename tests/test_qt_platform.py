def test_gui_tests_render_offscreen(qapp):
    assert qapp.platformName() == "offscreen"
