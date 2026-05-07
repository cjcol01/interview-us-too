def register(test, skip, client=None):

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
