from app.db.sessions import save_message, get_history

def test_save_and_get():
    save_message("sess-test", "user", "你好")
    hist = get_history("sess-test")
    assert hist[-1]["content"] == "你好"
    assert hist[-1]["role"] == "user"
