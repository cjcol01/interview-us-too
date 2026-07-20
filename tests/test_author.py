def register(test, skip, client):
    import config

    def test_no_credentials_returns_401():
        r = client.get("/verify-author")
        assert r.status_code == 401

    def test_wrong_password_returns_401():
        r = client.get("/verify-author", auth=("cjcol01", "definitelywrong"))
        assert r.status_code == 401

    def test_wrong_username_returns_401():
        r = client.get("/verify-author", auth=("admin", config.AUTHOR_PASSWORD or "x"))
        assert r.status_code == 401

    test("Author page: no credentials → 401",   test_no_credentials_returns_401)
    test("Author page: wrong password → 401",    test_wrong_password_returns_401)
    test("Author page: wrong username → 401",    test_wrong_username_returns_401)

    if config.AUTHOR_PASSWORD:
        def test_correct_password_returns_200():
            r = client.get("/verify-author", auth=("cjcol01", config.AUTHOR_PASSWORD))
            assert r.status_code == 200
        test("Author page: correct password → 200", test_correct_password_returns_200)
    else:
        skip("Author page: correct password → 200", "AUTHOR_PASSWORD not set")
