def register(test, skip, client):
    import config
    from unittest.mock import patch

    def test_no_credentials_returns_401():
        r = client.get("/verify-author")
        assert r.status_code == 401

    def test_wrong_password_returns_401():
        r = client.get("/verify-author", auth=(config.ADMIN_USERNAME, "definitelywrong"))
        assert r.status_code == 401

    def test_wrong_username_returns_401():
        r = client.get("/verify-author", auth=("admin", config.AUTHOR_PASSWORD or "x"))
        assert r.status_code == 401

    def test_unset_admin_username_rejects_empty_username():
        """ADMIN_USERNAME unset must fail closed. secrets.compare_digest(b"", b"") is True,
        so without the explicit truthiness guard in _require_author an empty Basic-auth
        username would satisfy the name half of the check on any server that hasn't set it."""
        with patch("server.ADMIN_USERNAME", ""):
            r = client.get("/verify-author", auth=("", config.AUTHOR_PASSWORD or "x"))
            assert r.status_code == 401

    test("Author page: no credentials → 401",   test_no_credentials_returns_401)
    test("Author page: wrong password → 401",    test_wrong_password_returns_401)
    test("Author page: wrong username → 401",    test_wrong_username_returns_401)
    test("Author page: unset ADMIN_USERNAME fails closed", test_unset_admin_username_rejects_empty_username)

    if config.AUTHOR_PASSWORD:
        def test_correct_password_returns_200():
            r = client.get("/verify-author", auth=(config.ADMIN_USERNAME, config.AUTHOR_PASSWORD))
            assert r.status_code == 200
        test("Author page: correct password → 200", test_correct_password_returns_200)
    else:
        skip("Author page: correct password → 200", "AUTHOR_PASSWORD not set")
