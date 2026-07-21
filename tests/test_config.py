def register(test, skip, client=None):

    def _run_import_config(env_overrides, code="import config"):
        import os
        import subprocess
        import sys

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ)
        env.update(env_overrides)
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=project_root, env=env,
            capture_output=True, text=True, timeout=30,
        )

    def test_default_secret_key_refuses_to_start():
        result = _run_import_config({"SECRET_KEY": "change-me-in-production"})
        assert result.returncode != 0
        assert "SECRET_KEY" in result.stderr

    def test_missing_stripe_key_refuses_to_start():
        result = _run_import_config({"STRIPE_SECRET_KEY": ""})
        assert result.returncode != 0
        assert "STRIPE_SECRET_KEY" in result.stderr

    def test_sub_price_id_falls_back_to_price_id():
        result = _run_import_config(
            {"STRIPE_SUB_PRICE_ID": "", "STRIPE_PRICE_ID": "price_fallback_test"},
            code="import config; assert config.STRIPE_SUB_PRICE_ID == 'price_fallback_test'",
        )
        assert result.returncode == 0, result.stderr

    test("Refuses to start: default SECRET_KEY",       test_default_secret_key_refuses_to_start)
    test("Refuses to start: missing STRIPE_SECRET_KEY", test_missing_stripe_key_refuses_to_start)
    test("STRIPE_SUB_PRICE_ID falls back to STRIPE_PRICE_ID", test_sub_price_id_falls_back_to_price_id)

    def test_config_loads():
        import config
        assert config.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY not set"
        assert config.SECRET_KEY != "change-me-in-production", "SECRET_KEY is still default"

    def test_stripe_keys_present():
        import config
        assert config.STRIPE_SECRET_KEY, "STRIPE_SECRET_KEY not configured"

    def test_referral_coupon_key_defined():
        import config
        assert hasattr(config, "STRIPE_REFERRAL_COUPON_ID"), "STRIPE_REFERRAL_COUPON_ID missing from config"

    def test_base_url_set():
        import config
        assert config.BASE_URL, "BASE_URL not set"

    test("Config loads and required keys present",    test_config_loads)
    test("Stripe keys configured",                   test_stripe_keys_present)
    test("STRIPE_REFERRAL_COUPON_ID defined",        test_referral_coupon_key_defined)
    test("BASE_URL is set",                          test_base_url_set)
