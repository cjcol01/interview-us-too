# Merged section — How it works + Features (+ video)

Replaces the two separate `#how` and `#features` sections with one compressed `#how` section.
Prototype: `Merged How It Works.dc.html`.

## Editorial changes made while merging

- Dropped the **Screen or voice** and **Instant replay** tiles — both were already stated in step 1/step 2. Repeating them a third time made the section feel padded.
- Renamed **Streams to your phone** → **Readable at a glance** (step 3 already owns the streaming claim) and folded the platform list (Zoom · Teams · HireVue · Kira) into its body copy.
- The two remaining claim cards now sit **beside** the video (video `1.45fr`, cards stacked in a `1fr` column) rather than in a row above it. This is the single biggest height saving.
- Step badges are plain mono lines, not bordered pills. Claim cards carry no badges at all.
- Removed the "Why nobody sees it" sub-divider — with only two cards it was scaffolding for a beat that no longer exists.
- Section padding `120px → 88px`; section-header bottom margin `64px → 44px`; step grid gap `40px → 36px`.
- Kicker stays `02 · How it works`. Anything numbered `03` downstream shifts up by one.
- Nav: `#features` anchor should now point at `#how` (or keep both pointing to `#how`).

## Markup (Jinja)

```html
<!-- ===== HOW IT WORKS ===== -->
<section class="ia-section ia-section--panel ia-section--how" id="how">
  <div class="ia-container">
    <div class="ia-section-hd" data-reveal>
      <div class="ia-kicker"><span class="ia-kicker-n">02</span> &nbsp;·&nbsp; How it works</div>
      <h2 class="ia-h2">Three ways to capture. One silent result.</h2>
    </div>

    <div class="ia-steps">
      <div class="ia-step" data-reveal>
        <div class="ia-step-top">
          <div class="ia-step-num">1</div>
          <div class="ia-step-rule"></div>
        </div>
        <h3>Tap a hidden hotkey</h3>
        <p>Tap to capture your screen instantly — intercepted at the OS level, invisible to monitoring software. Hold while the interviewer speaks to send their words to AI. Or replay the last 15 seconds of conversation.</p>
        <div class="ia-step-note ia-step-note--accent">+ type your own question silently</div>
      </div>
      <div class="ia-step" data-reveal>
        <div class="ia-step-top">
          <div class="ia-step-num">2</div>
          <div class="ia-step-rule"></div>
        </div>
        <h3>AI reads or listens</h3>
        <p>Claude reads the problem, detects the language, and generates a solution with complexity analysis. For voice, Whisper transcribes first — same output, hands-free.</p>
        <div class="ia-step-note">auto language detection</div>
      </div>
      <div class="ia-step" data-reveal>
        <div class="ia-step-top">
          <div class="ia-step-num">3</div>
          <div class="ia-step-rule"></div>
        </div>
        <h3>Answer streams to your phone</h3>
        <p>Results appear in seconds with syntax-highlighted code and explanation — never on your interview screen.</p>
        <div class="ia-step-note">phone or second monitor</div>
      </div>
    </div>

    {% if DEV_BUILD %}
    <div class="ia-how-proof" data-reveal>
      <div class="ia-video-wrap">
        <iframe
          src="https://www.youtube.com/embed/WhBbMlNWlnU"
          title="InterviewAce — see it in action"
          frameborder="0"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
          allowfullscreen>
        </iframe>
      </div>

      <div class="ia-proof-col">
        <div class="ia-proof-card ia-proof-card--accent">
          <div class="ia-proof-hd">
            <span class="ia-proof-icon">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            </span>
            <h3>Undetectable by design</h3>
          </div>
          <p>No popups, no new windows, no clipboard access. Screen-shares and monitoring software see nothing unusual — nothing new ever appears on screen.</p>
        </div>

        <div class="ia-proof-card">
          <div class="ia-proof-hd">
            <span class="ia-proof-icon">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="20" x="5" y="2" rx="2"/><path d="M12 18h.01"/></svg>
            </span>
            <h3>Readable at a glance</h3>
          </div>
          <p>Syntax-highlighted code, complexity, and a short explanation — sized for a phone below the desk. Zoom, Teams, HireVue, Kira.</p>
        </div>
      </div>
    </div>
    {% endif %}
  </div>
</section>
```

If the video is not shipping yet, drop the whole `.ia-how-proof` block — the steps stand alone and the section still closes cleanly.

## CSS delta (append to the landing page CSS)

```css
/* compressed section rhythm — overrides the 120px default for this band only */
.ia-section--how { padding-top: 88px; padding-bottom: 88px; }
.ia-section--how .ia-section-hd { margin-bottom: 44px; }

.ia-steps { gap: 36px; margin-bottom: 56px; }

/* plain mono note replaces the old bordered pill */
.ia-step-note {
  margin-top: 14px;
  font-family: 'JetBrains Mono', monospace; font-size: 11px;
  color: var(--text-3);
}
.ia-step-note--accent { color: var(--accent); }

/* video + claims, side by side */
.ia-how-proof {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(300px, 1fr);
  gap: 18px;
  align-items: stretch;
}
.ia-video-wrap {
  position: relative; aspect-ratio: 16 / 9;
  border: 1px solid var(--line-strong); border-radius: 18px;
  overflow: hidden; background: #0A0A0C;
}
.ia-video-wrap iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }

.ia-proof-col { display: flex; flex-direction: column; gap: 14px; }
.ia-proof-card {
  flex: 1;
  background: var(--card); border: 1px solid var(--line); border-radius: 16px;
  padding: 22px 24px;
  transition: border-color .2s;
}
.ia-proof-card:hover { border-color: var(--line-strong); }
.ia-proof-card--accent:hover { border-color: var(--accent-line); }

.ia-proof-hd { display: flex; align-items: center; gap: 11px; margin-bottom: 9px; }
.ia-proof-icon { display: flex; color: var(--text-1); }
.ia-proof-card--accent .ia-proof-icon { color: var(--accent); }
.ia-proof-hd h3 {
  font-family: 'Space Grotesk', sans-serif; font-size: 17px; font-weight: 600;
  color: var(--text-1); letter-spacing: -0.02em;
}
.ia-proof-card p { font-size: 13.5px; color: var(--text-2); line-height: 1.6; text-wrap: pretty; }

@media (max-width: 900px) {
  .ia-section--how { padding-top: 72px; padding-bottom: 72px; }
  .ia-how-proof { grid-template-columns: 1fr; }
}
```

## Removed rules

These no longer have any markup pointing at them once the merge lands — delete if nothing else uses them:

- `.ia-bento` / `.ia-bento--pair` and the tile spans, if `#features` was their only consumer
- `.ia-tile`, `.ia-tile-icon`, `.ia-tile-badge` (+ `--accent` variants)
- `.ia-subrule`
- `.ia-video-hd` (the "See it in action / 90 sec" header — the video no longer carries a label)
