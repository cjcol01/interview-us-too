def register(test, skip, client):
    import io

    import server
    from auth import create_token
    from database import SessionLocal
    from models import AccountLevel, InterviewContext
    from server import (
        BEHAVIOURAL_CONTEXT_MAX_LENGTH,
        CONTEXT_TEXT_MAX_LENGTH,
        CONTEXT_UPLOAD_MAX_BYTES,
        CV_CONTEXT_MAX_LENGTH,
        MAX_CONTEXTS_PER_USER,
        _context_suffix,
        _extract_text_from_upload,
        _split_name_and_body,
        _truncate_on_boundary,
    )
    from tests.helpers import cleanup, make_user

    # -- Fixture builders (no external deps: hand-crafted PDF, docx via python-docx)

    def _make_pdf(text: str) -> bytes:
        objs = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            None,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        stream = b"BT /F1 24 Tf 72 700 Td (" + text.encode("latin-1") + b") Tj ET"
        objs[3] = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        out = io.BytesIO()
        out.write(b"%PDF-1.4\n")
        offsets = []
        for i, body in enumerate(objs, start=1):
            offsets.append(out.tell())
            out.write(str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n")
        xref_pos = out.tell()
        n = len(objs) + 1
        out.write(b"xref\n0 " + str(n).encode() + b"\n0000000000 65535 f \n")
        for off in offsets:
            out.write(("%010d 00000 n \n" % off).encode())
        out.write(b"trailer\n<< /Size " + str(n).encode() + b" /Root 1 0 R >>\n")
        out.write(b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF")
        return out.getvalue()

    def _make_empty_pdf() -> bytes:
        # Valid single page with no text content stream (mimics a scanned/image PDF).
        objs = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
        ]
        out = io.BytesIO()
        out.write(b"%PDF-1.4\n")
        offsets = []
        for i, body in enumerate(objs, start=1):
            offsets.append(out.tell())
            out.write(str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n")
        xref_pos = out.tell()
        n = len(objs) + 1
        out.write(b"xref\n0 " + str(n).encode() + b"\n0000000000 65535 f \n")
        for off in offsets:
            out.write(("%010d 00000 n \n" % off).encode())
        out.write(b"trailer\n<< /Size " + str(n).encode() + b" /Root 1 0 R >>\n")
        out.write(b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF")
        return out.getvalue()

    def _make_docx(text: str) -> bytes:
        import docx
        d = docx.Document()
        d.add_paragraph(text)
        buf = io.BytesIO()
        d.save(buf)
        return buf.getvalue()

    # -- Helper behaviour ------------------------------------------------

    def test_context_suffix_empty_when_no_active_slot():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            assert _context_suffix(u, db) == ""
        finally:
            cleanup(db, u); db.close()

    def test_context_suffix_includes_active_slot_text():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            db.add(InterviewContext(user_id=u.id, slot=1, name="Acme", text="Interviewing at Acme Corp for a backend role."))
            u.active_context_slot = 1
            db.commit()
            suffix = _context_suffix(u, db)
            assert "Acme Corp" in suffix
        finally:
            cleanup(db, u); db.close()

    def test_context_suffix_ignores_inactive_slot():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            db.add(InterviewContext(user_id=u.id, slot=1, name="Acme", text="Interviewing at Acme Corp."))
            db.commit()
            # slot 1 is saved but not marked active
            assert _context_suffix(u, db) == ""
        finally:
            cleanup(db, u); db.close()

    # -- POST /api/settings/context (cookie, web-facing) ------------------

    def test_api_settings_context_persists():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context",
                json={"slot": 1, "name": "Globex", "text": "  Applying to Globex as a data engineer.  "},
                cookies={"session": token},
            )
            assert r.status_code == 200
            ctx = db.query(InterviewContext).filter(InterviewContext.user_id == u.id, InterviewContext.slot == 1).first()
            assert ctx.name == "Globex"
            assert ctx.text == "Applying to Globex as a data engineer."
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_blank_clears_slot():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            db.add(InterviewContext(user_id=u.id, slot=1, name="Old", text="Old context"))
            u.active_context_slot = 1
            db.commit()
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context",
                json={"slot": 1, "name": "  ", "text": "   "},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert db.query(InterviewContext).filter(InterviewContext.user_id == u.id, InterviewContext.slot == 1).first() is None
            assert u.active_context_slot is None
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_requires_session():
        r = client.post("/api/settings/context", json={"slot": 1, "name": "x", "text": "hello"})
        assert r.status_code in (401, 403)

    def test_api_settings_context_rejects_over_max_length():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context",
                json={"slot": 1, "name": "x", "text": "x" * (CONTEXT_TEXT_MAX_LENGTH + 1)},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_rejects_slot_out_of_range():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context",
                json={"slot": MAX_CONTEXTS_PER_USER + 1, "name": "x", "text": "hello"},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u); db.close()

    # -- POST /api/settings/context/activate -------------------------------

    def test_api_settings_context_activate_sets_active_slot():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            db.add(InterviewContext(user_id=u.id, slot=2, name="Globex", text="Data engineer role at Globex."))
            db.commit()
            token = create_token(u.id)
            r = client.post("/api/settings/context/activate", json={"slot": 2}, cookies={"session": token})
            assert r.status_code == 200
            db.refresh(u)
            assert u.active_context_slot == 2
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_activate_null_clears_active_slot():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            db.add(InterviewContext(user_id=u.id, slot=1, name="Acme", text="Acme role."))
            u.active_context_slot = 1
            db.commit()
            token = create_token(u.id)
            r = client.post("/api/settings/context/activate", json={"slot": None}, cookies={"session": token})
            assert r.status_code == 200
            db.refresh(u)
            assert u.active_context_slot is None
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_activate_rejects_empty_slot():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post("/api/settings/context/activate", json={"slot": 3}, cookies={"session": token})
            assert r.status_code == 400
        finally:
            cleanup(db, u); db.close()

    # -- GET /settings reflects saved contexts ------------------------------

    def test_settings_page_renders_saved_contexts():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            db.add(InterviewContext(user_id=u.id, slot=1, name="Acme", text="Context for the settings page test."))
            db.commit()
            token = create_token(u.id)
            r = client.get("/settings", cookies={"session": token})
            assert r.status_code == 200
            assert "Context for the settings page test." in r.text
        finally:
            cleanup(db, u); db.close()

    # -- Extraction helpers (no network) -----------------------------------

    def test_extract_pdf_returns_text():
        data = _make_pdf("Jane Doe Senior Engineer Acme Corp 2020-2024 Python FastAPI")
        text = _extract_text_from_upload("cv.pdf", data)
        assert "Acme Corp" in text and "FastAPI" in text

    def test_extract_docx_returns_text():
        data = _make_docx("Applied to Globex as Data Engineer; built ETL pipelines in Airflow.")
        text = _extract_text_from_upload("cover.docx", data)
        assert "Globex" in text and "Airflow" in text

    def test_extract_rejects_unsupported_extension():
        raised = False
        try:
            _extract_text_from_upload("notes.txt", b"hello")
        except ValueError:
            raised = True
        assert raised

    def test_extract_rejects_corrupt_pdf():
        raised = False
        try:
            _extract_text_from_upload("broken.pdf", b"%PDF-1.4 not really a pdf")
        except ValueError:
            raised = True
        assert raised

    def test_extract_empty_pdf_returns_blank():
        text = _extract_text_from_upload("scan.pdf", _make_empty_pdf())
        assert text == ""

    def test_truncate_under_limit_unchanged():
        assert _truncate_on_boundary("short text", 2000) == "short text"

    def test_truncate_over_limit_cuts_on_boundary():
        s = "EXP: first fact. " * 300  # ~5100 chars
        out = _truncate_on_boundary(s, 2000)
        assert len(out) <= 2000
        assert not out.endswith("fir")  # didn't cut mid-word

    # -- POST /api/settings/context/extract --------------------------------

    def test_extract_endpoint_requires_session():
        r = client.post(
            "/api/settings/context/extract",
            files={"file": ("cv.pdf", _make_pdf("hello Acme"), "application/pdf")},
        )
        assert r.status_code in (401, 403)

    def test_extract_endpoint_rejects_bad_extension():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context/extract",
                files={"file": ("notes.txt", b"hello", "text/plain")},
                cookies={"session": token},
            )
            assert r.status_code == 400
        finally:
            cleanup(db, u); db.close()

    def test_extract_endpoint_rejects_empty_file():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context/extract",
                files={"file": ("cv.pdf", b"", "application/pdf")},
                cookies={"session": token},
            )
            assert r.status_code == 400
        finally:
            cleanup(db, u); db.close()

    def test_extract_endpoint_rejects_too_large():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            big = b"%PDF-1.4\n" + b"0" * (CONTEXT_UPLOAD_MAX_BYTES + 1)
            r = client.post(
                "/api/settings/context/extract",
                files={"file": ("cv.pdf", big, "application/pdf")},
                cookies={"session": token},
            )
            assert r.status_code == 413
        finally:
            cleanup(db, u); db.close()

    def test_extract_endpoint_no_text_returns_422():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context/extract",
                files={"file": ("scan.pdf", _make_empty_pdf(), "application/pdf")},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u); db.close()

    def test_split_name_and_body_extracts_name():
        name, body = _split_name_and_body("NAME: Jane Doe — Acme CV\n\nEXP: Acme Corp; Python.")
        assert name == "Jane Doe — Acme CV"
        assert body == "EXP: Acme Corp; Python."

    def test_split_name_and_body_missing_name_line():
        name, body = _split_name_and_body("EXP: Acme Corp; Python.")
        assert name == ""
        assert body == "EXP: Acme Corp; Python."

    async def _fake_stream(raw, max_chars=None):
        # Mirrors _compress_context_stream's event protocol without calling Haiku.
        yield {"type": "progress", "chars": 12}
        yield {"type": "progress", "chars": 58}
        yield {"type": "done", "name": "Jane Doe — Acme CV",
               "text": "EXP: Acme Corp Senior Engineer 2020-2024; Python; FastAPI."}

    def _stream_events(resp):
        # The endpoint returns newline-delimited JSON; parse each line back to a dict.
        import json as _json
        return [_json.loads(line) for line in resp.text.splitlines() if line.strip()]

    def test_extract_endpoint_happy_path():
        orig = server._compress_context_stream
        server._compress_context_stream = _fake_stream
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context/extract",
                files={"file": ("cv.pdf", _make_pdf("Jane Doe Acme Corp Python"), "application/pdf")},
                cookies={"session": token},
            )
            assert r.status_code == 200
            events = _stream_events(r)
            assert any(e["type"] == "progress" for e in events)
            done = next(e for e in events if e["type"] == "done")
            assert "Acme Corp" in done["text"]
            assert done["name"] == "Jane Doe — Acme CV"
        finally:
            server._compress_context_stream = orig
            cleanup(db, u); db.close()

    async def _fake_stream_error(raw, max_chars=None):
        yield {"type": "progress", "chars": 5}
        yield {"type": "error", "detail": "Couldn't summarise that document just now — please try again."}

    def test_extract_endpoint_ai_error_streams_error_event():
        # Once streaming has begun the HTTP status is already 200; an AI failure
        # must surface as an in-stream 'error' event, not a broken response.
        orig = server._compress_context_stream
        server._compress_context_stream = _fake_stream_error
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context/extract",
                files={"file": ("cv.pdf", _make_pdf("Jane Doe Acme Corp Python"), "application/pdf")},
                cookies={"session": token},
            )
            assert r.status_code == 200
            events = _stream_events(r)
            assert any(e["type"] == "error" for e in events)
            assert not any(e["type"] == "done" for e in events)
        finally:
            server._compress_context_stream = orig
            cleanup(db, u); db.close()

    def test_extract_endpoint_rate_limited_after_limit_in_5min():
        # 4 summaries per 5 minutes are allowed (sized for a 3-section setup + a redo);
        # the 5th is rate limited.
        orig = server._compress_context_stream
        server._compress_context_stream = _fake_stream
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            files = {"file": ("cv.pdf", _make_pdf("Jane Doe Acme Corp Python"), "application/pdf")}
            codes = [client.post("/api/settings/context/extract", files=files, cookies={"session": token}).status_code
                     for _ in range(5)]
            assert codes[:4] == [200, 200, 200, 200]
            assert codes[4] == 429
        finally:
            server._compress_context_stream = orig
            cleanup(db, u); db.close()

    # -- Three-section context: CV + behavioural fixed fields --------------

    def test_context_suffix_includes_cv_and_behavioural():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            u.cv_context = "Senior engineer at Acme, Python and FastAPI."
            u.behavioural_context = "Led a team through a tough migration."
            db.commit()
            suffix = _context_suffix(u, db)
            assert "Senior engineer at Acme" in suffix
            assert "Led a team through a tough migration" in suffix
        finally:
            cleanup(db, u); db.close()

    def test_context_suffix_combines_all_three_sections():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            u.cv_context = "CV: Python dev."
            u.behavioural_context = "STAR: leadership story."
            db.add(InterviewContext(user_id=u.id, slot=1, name="Acme", text="Company: Acme backend role."))
            u.active_context_slot = 1
            db.commit()
            suffix = _context_suffix(u, db)
            assert "CV: Python dev." in suffix
            assert "STAR: leadership story." in suffix
            assert "Company: Acme backend role." in suffix
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_fixed_saves_cv():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context/fixed",
                json={"section": "cv", "text": "  Senior engineer, Python.  "},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.cv_context == "Senior engineer, Python."
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_fixed_saves_behavioural():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context/fixed",
                json={"section": "behavioural", "text": "A time I showed leadership."},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.behavioural_context == "A time I showed leadership."
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_fixed_blank_clears():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            u.cv_context = "old cv"
            db.commit()
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context/fixed",
                json={"section": "cv", "text": "   "},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.cv_context is None
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_fixed_over_max_length_422():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            # behavioural cap is below the Pydantic ceiling, so the handler enforces it
            r = client.post(
                "/api/settings/context/fixed",
                json={"section": "behavioural", "text": "x" * (BEHAVIOURAL_CONTEXT_MAX_LENGTH + 1)},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_fixed_unknown_section_422():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context/fixed",
                json={"section": "bogus", "text": "hello"},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_fixed_requires_session():
        r = client.post("/api/settings/context/fixed", json={"section": "cv", "text": "hi"})
        assert r.status_code in (401, 403)

    def test_api_settings_context_first_save_auto_activates():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context",
                json={"slot": 2, "name": "Acme", "text": "Acme backend role."},
                cookies={"session": token},
            )
            assert r.status_code == 200
            assert r.json()["active_slot"] == 2
            db.refresh(u)
            assert u.active_context_slot == 2
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_save_does_not_override_active():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            db.add(InterviewContext(user_id=u.id, slot=1, name="A", text="one"))
            u.active_context_slot = 1
            db.commit()
            token = create_token(u.id)
            # saving a *different* slot must not steal the active flag from slot 1
            r = client.post(
                "/api/settings/context",
                json={"slot": 2, "name": "B", "text": "two"},
                cookies={"session": token},
            )
            assert r.status_code == 200
            assert r.json()["active_slot"] == 1
            db.refresh(u)
            assert u.active_context_slot == 1
        finally:
            cleanup(db, u); db.close()

    def test_extract_unknown_section_422():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context/extract",
                files={"file": ("cv.pdf", _make_pdf("Jane Doe Acme Corp Python"), "application/pdf")},
                data={"section": "bogus"},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u); db.close()

    test("_context_suffix is empty when no slot is active",           test_context_suffix_empty_when_no_active_slot)
    test("_context_suffix includes the active slot's text",           test_context_suffix_includes_active_slot_text)
    test("_context_suffix ignores a saved-but-inactive slot",         test_context_suffix_ignores_inactive_slot)
    test("POST /api/settings/context persists name+text",             test_api_settings_context_persists)
    test("POST /api/settings/context: blank clears the slot",         test_api_settings_context_blank_clears_slot)
    test("POST /api/settings/context requires session",               test_api_settings_context_requires_session)
    test("POST /api/settings/context: over max length → 422",         test_api_settings_context_rejects_over_max_length)
    test("POST /api/settings/context: slot out of range → 422",       test_api_settings_context_rejects_slot_out_of_range)
    test("POST /api/settings/context/activate sets active slot",      test_api_settings_context_activate_sets_active_slot)
    test("POST /api/settings/context/activate: null clears active",   test_api_settings_context_activate_null_clears_active_slot)
    test("POST /api/settings/context/activate: empty slot → 400",     test_api_settings_context_activate_rejects_empty_slot)
    test("GET /settings renders saved contexts",                      test_settings_page_renders_saved_contexts)
    test("_extract_text_from_upload: PDF → text",                     test_extract_pdf_returns_text)
    test("_extract_text_from_upload: DOCX → text",                    test_extract_docx_returns_text)
    test("_extract_text_from_upload: bad extension → ValueError",     test_extract_rejects_unsupported_extension)
    test("_extract_text_from_upload: corrupt PDF → ValueError",       test_extract_rejects_corrupt_pdf)
    test("_extract_text_from_upload: image-only PDF → ''",            test_extract_empty_pdf_returns_blank)
    test("_truncate_on_boundary: under limit unchanged",             test_truncate_under_limit_unchanged)
    test("_truncate_on_boundary: over limit cuts on boundary",       test_truncate_over_limit_cuts_on_boundary)
    test("_split_name_and_body: extracts NAME line",                 test_split_name_and_body_extracts_name)
    test("_split_name_and_body: missing NAME line → empty name",     test_split_name_and_body_missing_name_line)
    test("POST /context/extract requires session",                   test_extract_endpoint_requires_session)
    test("POST /context/extract: bad extension → 400",               test_extract_endpoint_rejects_bad_extension)
    test("POST /context/extract: empty file → 400",                  test_extract_endpoint_rejects_empty_file)
    test("POST /context/extract: too large → 413",                   test_extract_endpoint_rejects_too_large)
    test("POST /context/extract: no text → 422",                     test_extract_endpoint_no_text_returns_422)
    test("POST /context/extract: happy path → 200 + streamed text",  test_extract_endpoint_happy_path)
    test("POST /context/extract: AI failure → in-stream error event", test_extract_endpoint_ai_error_streams_error_event)
    test("POST /context/extract: 5th in 5min → 429",                 test_extract_endpoint_rate_limited_after_limit_in_5min)
    test("_context_suffix includes CV + behavioural",                test_context_suffix_includes_cv_and_behavioural)
    test("_context_suffix combines all three sections",              test_context_suffix_combines_all_three_sections)
    test("POST /context/fixed saves CV",                             test_api_settings_context_fixed_saves_cv)
    test("POST /context/fixed saves behavioural",                    test_api_settings_context_fixed_saves_behavioural)
    test("POST /context/fixed: blank clears the field",              test_api_settings_context_fixed_blank_clears)
    test("POST /context/fixed: over section max → 422",              test_api_settings_context_fixed_over_max_length_422)
    test("POST /context/fixed: unknown section → 422",               test_api_settings_context_fixed_unknown_section_422)
    test("POST /context/fixed requires session",                     test_api_settings_context_fixed_requires_session)
    test("POST /context: first save auto-activates the slot",        test_api_settings_context_first_save_auto_activates)
    test("POST /context: save doesn't override an active slot",      test_api_settings_context_save_does_not_override_active)
    test("POST /context/extract: unknown section → 422",             test_extract_unknown_section_422)
